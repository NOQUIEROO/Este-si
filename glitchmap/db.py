"""Capa de datos. SQLite, sin ORM, y sobre todo: sin DELETE.

Reglas de la casa
-----------------
1. Las tablas de contenido (`glitches`, `signals`) son de solo insercion.
   Nada se edita, nada se borra. Un lugar que dejo de servir pierde
   estabilidad, no filas.
2. Ninguna tabla de contenido tiene columna de usuario. Ni en claro, ni
   hasheada. No hay forma de saber quien cargo que, ni siquiera con acceso
   total a la base.
3. La unica tabla que sabe de personas es `members`, y guarda un HMAC del id
   de Telegram con una sal que vive fuera de la base. Es la puerta, y no se
   cruza con el contenido.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .geo import bounding_box, haversine_m
from .stability import COLLAPSE, CONFIRM, is_faded, stability

MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS glitches (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                alias         TEXT    NOT NULL,
                lat           REAL    NOT NULL,
                lon           REAL    NOT NULL,
                cobertura     TEXT    NOT NULL,
                interferencia TEXT    NOT NULL,
                ventana       TEXT    NOT NULL,
                nota          TEXT,
                created_at    TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_glitches_lat ON glitches (lat)",
            """
            CREATE TABLE IF NOT EXISTS signals (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                glitch_id  INTEGER NOT NULL REFERENCES glitches (id),
                kind       TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_signals_glitch ON signals (glitch_id)",
            """
            CREATE TABLE IF NOT EXISTS members (
                member_hash TEXT PRIMARY KEY,
                joined_at   TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS invites (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash  TEXT    NOT NULL UNIQUE,
                max_uses   INTEGER NOT NULL,
                uses       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    NOT NULL
            )
            """,
        ),
    ),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Glitch:
    id: int
    alias: str
    lat: float
    lon: float
    cobertura: str
    interferencia: str
    ventana: str
    nota: str | None
    created_at: datetime
    score: int
    confirms: int
    collapses: int
    last_signal: datetime | None
    distance_m: float | None = None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = FULL")  # durabilidad antes que velocidad
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    # ---------------------------------------------------------------- esquema

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for target, statements in MIGRATIONS:
                if version >= target:
                    continue
                for statement in statements:
                    self._conn.execute(statement)
                self._conn.execute(f"PRAGMA user_version = {target}")
                version = target
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def raw_connection(self) -> sqlite3.Connection:
        """Solo para el respaldo en caliente."""
        return self._conn

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    # -------------------------------------------------------------- contenido

    def add_glitch(
        self,
        *,
        alias: str,
        lat: float,
        lon: float,
        cobertura: str,
        interferencia: str,
        ventana: str,
        nota: str | None,
        now: datetime | None = None,
    ) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO glitches
                    (alias, lat, lon, cobertura, interferencia, ventana, nota, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (alias, lat, lon, cobertura, interferencia, ventana, nota, _iso(now or utcnow())),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def add_signal(self, glitch_id: int, kind: str, now: datetime | None = None) -> None:
        if kind not in (CONFIRM, COLLAPSE):
            raise ValueError(f"senal desconocida: {kind!r}")
        with self._lock:
            self._conn.execute(
                "INSERT INTO signals (glitch_id, kind, created_at) VALUES (?, ?, ?)",
                (glitch_id, kind, _iso(now or utcnow())),
            )
            self._conn.commit()

    def _signals_by_glitch(self, ids: list[int]) -> dict[int, list[tuple[str, datetime]]]:
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT glitch_id, kind, created_at FROM signals WHERE glitch_id IN ({placeholders})",
                ids,
            ).fetchall()
        grouped: dict[int, list[tuple[str, datetime]]] = {gid: [] for gid in ids}
        for row in rows:
            grouped[row["glitch_id"]].append((row["kind"], _parse(row["created_at"])))
        return grouped

    def _hydrate(self, row: sqlite3.Row, signals: list[tuple[str, datetime]], now: datetime) -> Glitch:
        created = _parse(row["created_at"])
        return Glitch(
            id=row["id"],
            alias=row["alias"],
            lat=row["lat"],
            lon=row["lon"],
            cobertura=row["cobertura"],
            interferencia=row["interferencia"],
            ventana=row["ventana"],
            nota=row["nota"],
            created_at=created,
            score=stability(created, signals, now),
            confirms=sum(1 for kind, _ in signals if kind == CONFIRM),
            collapses=sum(1 for kind, _ in signals if kind == COLLAPSE),
            last_signal=max((when for _, when in signals), default=None),
        )

    def get_glitch(self, glitch_id: int, now: datetime | None = None) -> Glitch | None:
        now = now or utcnow()
        with self._lock:
            row = self._conn.execute("SELECT * FROM glitches WHERE id = ?", (glitch_id,)).fetchone()
        if row is None:
            return None
        signals = self._signals_by_glitch([glitch_id])[glitch_id]
        return self._hydrate(row, signals, now)

    def nearby(
        self,
        lat: float,
        lon: float,
        radius_m: float,
        limit: int,
        include_faded: bool = False,
        now: datetime | None = None,
    ) -> list[Glitch]:
        now = now or utcnow()
        min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_m)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM glitches
                WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                """,
                (min_lat, max_lat, min_lon, max_lon),
            ).fetchall()

        candidates = []
        for row in rows:
            distance = haversine_m(lat, lon, row["lat"], row["lon"])
            if distance <= radius_m:
                candidates.append((row, distance))

        signals = self._signals_by_glitch([row["id"] for row, _ in candidates])
        found: list[Glitch] = []
        for row, distance in candidates:
            glitch = self._hydrate(row, signals[row["id"]], now)
            if is_faded(glitch.score) and not include_faded:
                continue
            found.append(replace(glitch, distance_m=distance))

        found.sort(key=lambda g: g.distance_m or 0.0)
        return found[:limit]

    def count_glitches(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM glitches").fetchone()[0])

    def stats(self, now: datetime | None = None) -> dict[str, int]:
        now = now or utcnow()
        with self._lock:
            rows = self._conn.execute("SELECT * FROM glitches").fetchall()
            members = int(self._conn.execute("SELECT COUNT(*) FROM members").fetchone()[0])
            total_signals = int(self._conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
        signals = self._signals_by_glitch([row["id"] for row in rows])
        visible = 0
        for row in rows:
            if not is_faded(self._hydrate(row, signals[row["id"]], now).score):
                visible += 1
        return {
            "glitches": len(rows),
            "visibles": visible,
            "desvanecidos": len(rows) - visible,
            "senales": total_signals,
            "miembros": members,
        }

    # ------------------------------------------------------------------ puerta

    def member_hash(self, user_id: int, salt: bytes) -> str:
        return hmac.new(salt, str(user_id).encode("ascii"), hashlib.sha256).hexdigest()

    def ensure_member(self, member_hash: str, now: datetime | None = None) -> None:
        """Mete a alguien en la red sin código. Solo para los admins."""
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO members (member_hash, joined_at) VALUES (?, ?)",
                (member_hash, _iso(now or utcnow())),
            )
            self._conn.commit()

    def count_invites(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM invites").fetchone()[0])

    def count_members(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM members").fetchone()[0])

    def is_member(self, member_hash: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM members WHERE member_hash = ?", (member_hash,)
            ).fetchone()
        return row is not None

    @staticmethod
    def code_hash(code: str) -> str:
        return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()

    def create_invite(self, code: str, max_uses: int, now: datetime | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO invites (code_hash, max_uses, uses, created_at) VALUES (?, ?, 0, ?)",
                (self.code_hash(code), max_uses, _iso(now or utcnow())),
            )
            self._conn.commit()

    def redeem_invite(self, code: str, member_hash: str, now: datetime | None = None) -> bool:
        """Canjea un codigo. Devuelve True si la persona quedo adentro.

        No guarda ninguna relacion entre el codigo y el miembro: solo sube el
        contador de usos del codigo y anota el hash en la lista de la puerta.
        """
        moment = _iso(now or utcnow())
        with self._lock:
            already = self._conn.execute(
                "SELECT 1 FROM members WHERE member_hash = ?", (member_hash,)
            ).fetchone()
            if already:
                return True

            row = self._conn.execute(
                "SELECT id, max_uses, uses FROM invites WHERE code_hash = ?",
                (self.code_hash(code),),
            ).fetchone()
            if row is None or row["uses"] >= row["max_uses"]:
                return False

            self._conn.execute("UPDATE invites SET uses = uses + 1 WHERE id = ?", (row["id"],))
            self._conn.execute(
                "INSERT INTO members (member_hash, joined_at) VALUES (?, ?)",
                (member_hash, moment),
            )
            self._conn.commit()
            return True
