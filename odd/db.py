"""Capa de datos. SQLite, sin ORM, y sin DELETE.

Reglas de la casa
-----------------
1. Todo lo que pasa es un evento, y los eventos solo se insertan. Un bar no
   "cambia de estado": se le agrega una pausa. Una placa no se edita: se le
   agrega un envio. El estado actual siempre se deriva (ver `estado.py`).
   No hay un solo DELETE en este modulo, y hay un test que falla si aparece.
2. Lo unico que se actualiza en su lugar es el contador de usos de un codigo,
   igual que en la puerta del otro bot: es un cerrojo, no contenido.

Que se guarda de las personas — y por que aca es distinto
--------------------------------------------------------
El otro bot de este repo no guarda absolutamente nada de nadie. Este si, y no
es un descuido: **el contacto de la primera visita es el corazon del trato**.
La persona entrega un contacto una sola vez, a cambio del credito, y sabe que
lo entrega. Entonces:

- `pasos.contacto` guarda ese contacto en claro. Es un dato personal y hay que
  tratarlo como tal (ver /privacidad en el bot).
- La foto de la reflexion **no se guarda aca**: se guarda el `file_id` que
  devuelve Telegram. Los bytes viven en Telegram, la base solo apunta.
- De los anfitriones se guarda un HMAC del id de Telegram con una sal que vive
  fuera de la base, igual que en el otro bot.
- De los visitantes que solo *buscan* bares no se guarda nada: buscar no
  escribe una fila.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

# Geometria: funciones puras, mismo repo. No hay razon para tener dos haversine.
from glitchmap.geo import bounding_box, haversine_m

from .estado import (
    ALTA,
    APROBADA,
    ASIGNADA,
    BAJA,
    EMITIDA,
    ENVIADA,
    EVENTOS_BAR,
    EVENTOS_NOMINACION,
    EVENTOS_PLACA,
    INSTALADA,
    VEREDICTOS,
    es_visitable,
    estado_bar,
    estado_nominacion,
    estado_placa,
    veredicto,
)

ANFITRION = "anfitrion"
NOMINACION = "nominacion"
ROLES_CODIGO = (ANFITRION, NOMINACION)

# Donde puede estar la placa. Es la unica pista fisica de que el bar esta en la
# red, asi que el dato importa: quien llega tiene que saber donde mirar.
LUGARES_PLACA = ("frente", "bano", "barra", "sin_definir")

MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS bares (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                alias       TEXT    NOT NULL,
                lat         REAL    NOT NULL,
                lon         REAL    NOT NULL,
                direccion   TEXT,
                placa_lugar TEXT    NOT NULL,
                nota        TEXT,
                origen      TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_bares_lat ON bares (lat)",
            """
            CREATE TABLE IF NOT EXISTS bar_eventos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                bar_id     INTEGER NOT NULL REFERENCES bares (id),
                kind       TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_bar_eventos_bar ON bar_eventos (bar_id)",
            """
            CREATE TABLE IF NOT EXISTS placas (
                numero     INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS placa_eventos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                numero     INTEGER NOT NULL REFERENCES placas (numero),
                kind       TEXT    NOT NULL,
                bar_id     INTEGER REFERENCES bares (id),
                created_at TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_placa_eventos_numero ON placa_eventos (numero)",
            """
            CREATE TABLE IF NOT EXISTS pasos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                bar_id     INTEGER NOT NULL REFERENCES bares (id),
                foto       TEXT    NOT NULL,
                es_primera INTEGER NOT NULL,
                contacto   TEXT,
                credito    REAL    NOT NULL,
                created_at TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_pasos_bar ON pasos (bar_id)",
            """
            CREATE TABLE IF NOT EXISTS veredictos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                paso_id    INTEGER NOT NULL REFERENCES pasos (id),
                kind       TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_veredictos_paso ON veredictos (paso_id)",
            """
            CREATE TABLE IF NOT EXISTS anfitriones (
                host_hash  TEXT    NOT NULL,
                bar_id     INTEGER NOT NULL REFERENCES bares (id),
                created_at TEXT    NOT NULL,
                PRIMARY KEY (host_hash, bar_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS codigos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash  TEXT    NOT NULL UNIQUE,
                rol        TEXT    NOT NULL,
                bar_id     INTEGER REFERENCES bares (id),
                paso_id    INTEGER REFERENCES pasos (id),
                usos       INTEGER NOT NULL DEFAULT 0,
                max_usos   INTEGER NOT NULL,
                created_at TEXT    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS nominaciones (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                alias      TEXT    NOT NULL,
                lat        REAL    NOT NULL,
                lon        REAL    NOT NULL,
                motivo     TEXT,
                paso_id    INTEGER REFERENCES pasos (id),
                created_at TEXT    NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS nominacion_eventos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                nominacion_id INTEGER NOT NULL REFERENCES nominaciones (id),
                kind          TEXT    NOT NULL,
                bar_id        INTEGER REFERENCES bares (id),
                created_at    TEXT    NOT NULL
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
class Bar:
    id: int
    alias: str
    lat: float
    lon: float
    direccion: str | None
    placa_lugar: str
    nota: str | None
    origen: str
    created_at: datetime
    estado: str
    placa: int | None
    pasos: int
    ultimo_paso: datetime | None
    distance_m: float | None = None


@dataclass(frozen=True)
class Paso:
    id: int
    bar_id: int
    bar_alias: str
    foto: str
    es_primera: bool
    contacto: str | None
    credito: float
    created_at: datetime
    veredicto: str


@dataclass(frozen=True)
class Placa:
    numero: int
    estado: str
    bar_id: int | None
    bar_alias: str | None
    created_at: datetime


@dataclass(frozen=True)
class Codigo:
    id: int
    rol: str
    bar_id: int | None
    paso_id: int | None
    usos: int
    max_usos: int


@dataclass(frozen=True)
class Nominacion:
    id: int
    alias: str
    lat: float
    lon: float
    motivo: str | None
    paso_id: int | None
    created_at: datetime
    estado: str


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
        """Solo para el respaldo en caliente y para los tests."""
        return self._conn

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    # ------------------------------------------------------------------ bares

    def alta_bar(
        self,
        *,
        alias: str,
        lat: float,
        lon: float,
        direccion: str | None = None,
        placa_lugar: str = "sin_definir",
        nota: str | None = None,
        origen: str = "fundacional",
        now: datetime | None = None,
    ) -> int:
        if placa_lugar not in LUGARES_PLACA:
            raise ValueError(f"lugar de placa desconocido: {placa_lugar!r}")
        moment = _iso(now or utcnow())
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO bares (alias, lat, lon, direccion, placa_lugar, nota, origen, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (alias, lat, lon, direccion, placa_lugar, nota, origen, moment),
            )
            bar_id = int(cursor.lastrowid)
            self._conn.execute(
                "INSERT INTO bar_eventos (bar_id, kind, created_at) VALUES (?, ?, ?)",
                (bar_id, ALTA, moment),
            )
            self._conn.commit()
            return bar_id

    def evento_bar(self, bar_id: int, kind: str, now: datetime | None = None) -> None:
        if kind not in EVENTOS_BAR:
            raise ValueError(f"evento de bar desconocido: {kind!r}")
        with self._lock:
            self._conn.execute(
                "INSERT INTO bar_eventos (bar_id, kind, created_at) VALUES (?, ?, ?)",
                (bar_id, kind, _iso(now or utcnow())),
            )
            self._conn.commit()

    def _eventos_por_bar(self, ids: list[int]) -> dict[int, list[tuple[str, datetime]]]:
        if not ids:
            return {}
        marcas = ",".join("?" * len(ids))
        with self._lock:
            filas = self._conn.execute(
                f"SELECT bar_id, kind, created_at FROM bar_eventos WHERE bar_id IN ({marcas}) ORDER BY id",
                ids,
            ).fetchall()
        agrupado: dict[int, list[tuple[str, datetime]]] = {bid: [] for bid in ids}
        for fila in filas:
            agrupado[fila["bar_id"]].append((fila["kind"], _parse(fila["created_at"])))
        return agrupado

    def _placas_por_bar(self, ids: list[int]) -> dict[int, int | None]:
        """La placa vigente de cada bar: la ultima que se le asigno."""
        if not ids:
            return {}
        marcas = ",".join("?" * len(ids))
        with self._lock:
            filas = self._conn.execute(
                f"""
                SELECT numero, bar_id, kind, created_at FROM placa_eventos
                WHERE bar_id IN ({marcas})
                ORDER BY created_at, id
                """,
                ids,
            ).fetchall()
        vigente: dict[int, int | None] = {bid: None for bid in ids}
        for fila in filas:
            if fila["kind"] == BAJA:
                if vigente.get(fila["bar_id"]) == fila["numero"]:
                    vigente[fila["bar_id"]] = None
            else:
                vigente[fila["bar_id"]] = fila["numero"]
        return vigente

    def _pasos_por_bar(self, ids: list[int]) -> dict[int, tuple[int, datetime | None]]:
        if not ids:
            return {}
        marcas = ",".join("?" * len(ids))
        with self._lock:
            filas = self._conn.execute(
                f"""
                SELECT bar_id, COUNT(*) AS cuantos, MAX(created_at) AS ultimo
                FROM pasos WHERE bar_id IN ({marcas}) GROUP BY bar_id
                """,
                ids,
            ).fetchall()
        resumen: dict[int, tuple[int, datetime | None]] = {bid: (0, None) for bid in ids}
        for fila in filas:
            resumen[fila["bar_id"]] = (int(fila["cuantos"]), _parse(fila["ultimo"]))
        return resumen

    def _hidratar_bares(self, filas: list[sqlite3.Row]) -> list[Bar]:
        ids = [fila["id"] for fila in filas]
        eventos = self._eventos_por_bar(ids)
        placas = self._placas_por_bar(ids)
        pasos = self._pasos_por_bar(ids)
        bares = []
        for fila in filas:
            cuantos, ultimo = pasos[fila["id"]]
            bares.append(
                Bar(
                    id=fila["id"],
                    alias=fila["alias"],
                    lat=fila["lat"],
                    lon=fila["lon"],
                    direccion=fila["direccion"],
                    placa_lugar=fila["placa_lugar"],
                    nota=fila["nota"],
                    origen=fila["origen"],
                    created_at=_parse(fila["created_at"]),
                    estado=estado_bar(eventos[fila["id"]]),
                    placa=placas[fila["id"]],
                    pasos=cuantos,
                    ultimo_paso=ultimo,
                )
            )
        return bares

    def get_bar(self, bar_id: int) -> Bar | None:
        with self._lock:
            fila = self._conn.execute("SELECT * FROM bares WHERE id = ?", (bar_id,)).fetchone()
        if fila is None:
            return None
        return self._hidratar_bares([fila])[0]

    def cerca(
        self,
        lat: float,
        lon: float,
        radius_m: float,
        limit: int,
        incluir_cerrados: bool = False,
    ) -> list[Bar]:
        min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_m)
        with self._lock:
            filas = self._conn.execute(
                "SELECT * FROM bares WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
                (min_lat, max_lat, min_lon, max_lon),
            ).fetchall()

        candidatos = []
        for fila in filas:
            distancia = haversine_m(lat, lon, fila["lat"], fila["lon"])
            if distancia <= radius_m:
                candidatos.append((fila, distancia))

        encontrados = []
        for bar, (_, distancia) in zip(
            self._hidratar_bares([fila for fila, _ in candidatos]), candidatos
        ):
            if not incluir_cerrados and not es_visitable(bar.estado):
                continue
            encontrados.append(replace(bar, distance_m=distancia))

        encontrados.sort(key=lambda bar: bar.distance_m or 0.0)
        return encontrados[:limit]

    def listar_bares(self, limit: int = 50) -> list[Bar]:
        with self._lock:
            filas = self._conn.execute(
                "SELECT * FROM bares ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return self._hidratar_bares(filas)

    def count_bares(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM bares").fetchone()[0])

    # ----------------------------------------------------------------- placas

    def emitir_placas(self, cantidad: int, now: datetime | None = None) -> list[int]:
        """Acuña numeros nuevos, correlativos desde el ultimo. Devuelve la tira."""
        if cantidad < 1:
            return []
        moment = _iso(now or utcnow())
        with self._lock:
            ultimo = self._conn.execute("SELECT MAX(numero) FROM placas").fetchone()[0] or 0
            numeros = list(range(ultimo + 1, ultimo + 1 + cantidad))
            self._conn.executemany(
                "INSERT INTO placas (numero, created_at) VALUES (?, ?)",
                [(numero, moment) for numero in numeros],
            )
            self._conn.executemany(
                "INSERT INTO placa_eventos (numero, kind, bar_id, created_at) VALUES (?, ?, NULL, ?)",
                [(numero, EMITIDA, moment) for numero in numeros],
            )
            self._conn.commit()
        return numeros

    def evento_placa(
        self,
        numero: int,
        kind: str,
        bar_id: int | None = None,
        now: datetime | None = None,
    ) -> None:
        if kind not in EVENTOS_PLACA:
            raise ValueError(f"evento de placa desconocido: {kind!r}")
        with self._lock:
            existe = self._conn.execute(
                "SELECT 1 FROM placas WHERE numero = ?", (numero,)
            ).fetchone()
            if existe is None:
                raise ValueError(f"la placa {numero} no fue emitida")
            self._conn.execute(
                "INSERT INTO placa_eventos (numero, kind, bar_id, created_at) VALUES (?, ?, ?, ?)",
                (numero, kind, bar_id, _iso(now or utcnow())),
            )
            self._conn.commit()

    def asignar_placa(self, numero: int, bar_id: int, now: datetime | None = None) -> None:
        self.evento_placa(numero, ASIGNADA, bar_id, now)

    def get_placa(self, numero: int) -> Placa | None:
        with self._lock:
            fila = self._conn.execute(
                "SELECT * FROM placas WHERE numero = ?", (numero,)
            ).fetchone()
            if fila is None:
                return None
            eventos = self._conn.execute(
                "SELECT kind, bar_id, created_at FROM placa_eventos WHERE numero = ? ORDER BY created_at, id",
                (numero,),
            ).fetchall()
            bar_id = next(
                (
                    evento["bar_id"]
                    for evento in reversed(eventos)
                    if evento["bar_id"] is not None and evento["kind"] != BAJA
                ),
                None,
            )
            alias = None
            if bar_id is not None:
                bar = self._conn.execute(
                    "SELECT alias FROM bares WHERE id = ?", (bar_id,)
                ).fetchone()
                alias = bar["alias"] if bar else None
        return Placa(
            numero=numero,
            estado=estado_placa([(e["kind"], _parse(e["created_at"])) for e in eventos]),
            bar_id=bar_id,
            bar_alias=alias,
            created_at=_parse(fila["created_at"]),
        )

    def placas_en_stock(self) -> list[int]:
        """Numeros emitidos que todavia no se le asignaron a nadie."""
        with self._lock:
            filas = self._conn.execute("SELECT numero FROM placas ORDER BY numero").fetchall()
            asignadas = {
                fila["numero"]
                for fila in self._conn.execute(
                    "SELECT DISTINCT numero FROM placa_eventos WHERE bar_id IS NOT NULL"
                )
            }
        return [fila["numero"] for fila in filas if fila["numero"] not in asignadas]

    def resumen_placas(self) -> dict[str, int]:
        with self._lock:
            numeros = [
                fila["numero"] for fila in self._conn.execute("SELECT numero FROM placas")
            ]
            filas = self._conn.execute(
                "SELECT numero, kind, created_at FROM placa_eventos ORDER BY id"
            ).fetchall()
        eventos: dict[int, list[tuple[str, datetime]]] = {numero: [] for numero in numeros}
        for fila in filas:
            eventos[fila["numero"]].append((fila["kind"], _parse(fila["created_at"])))
        resumen = {clave: 0 for clave in EVENTOS_PLACA}
        for numero in numeros:
            resumen[estado_placa(eventos[numero])] += 1
        return resumen

    # ------------------------------------------------------------------ pasos

    def registrar_paso(
        self,
        *,
        bar_id: int,
        foto: str,
        es_primera: bool,
        contacto: str | None,
        credito: float,
        now: datetime | None = None,
    ) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO pasos (bar_id, foto, es_primera, contacto, credito, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    bar_id,
                    foto,
                    1 if es_primera else 0,
                    contacto,
                    credito,
                    _iso(now or utcnow()),
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def _hidratar_pasos(self, filas: list[sqlite3.Row]) -> list[Paso]:
        ids = [fila["id"] for fila in filas]
        veredictos: dict[int, list[tuple[str, datetime]]] = {pid: [] for pid in ids}
        if ids:
            marcas = ",".join("?" * len(ids))
            with self._lock:
                for fila in self._conn.execute(
                    f"SELECT paso_id, kind, created_at FROM veredictos WHERE paso_id IN ({marcas}) ORDER BY id",
                    ids,
                ):
                    veredictos[fila["paso_id"]].append((fila["kind"], _parse(fila["created_at"])))
        return [
            Paso(
                id=fila["id"],
                bar_id=fila["bar_id"],
                bar_alias=fila["bar_alias"],
                foto=fila["foto"],
                es_primera=bool(fila["es_primera"]),
                contacto=fila["contacto"],
                credito=float(fila["credito"]),
                created_at=_parse(fila["created_at"]),
                veredicto=veredicto(veredictos[fila["id"]]),
            )
            for fila in filas
        ]

    def get_paso(self, paso_id: int) -> Paso | None:
        with self._lock:
            fila = self._conn.execute(
                """
                SELECT pasos.*, bares.alias AS bar_alias
                FROM pasos JOIN bares ON bares.id = pasos.bar_id
                WHERE pasos.id = ?
                """,
                (paso_id,),
            ).fetchone()
        if fila is None:
            return None
        return self._hidratar_pasos([fila])[0]

    def pasos_sin_leer(self, limit: int = 10) -> list[Paso]:
        with self._lock:
            filas = self._conn.execute(
                """
                SELECT pasos.*, bares.alias AS bar_alias
                FROM pasos
                JOIN bares ON bares.id = pasos.bar_id
                LEFT JOIN veredictos ON veredictos.paso_id = pasos.id
                WHERE veredictos.id IS NULL
                ORDER BY pasos.id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return self._hidratar_pasos(filas)

    def juzgar(self, paso_id: int, kind: str, now: datetime | None = None) -> None:
        if kind not in VEREDICTOS:
            raise ValueError(f"veredicto desconocido: {kind!r}")
        with self._lock:
            self._conn.execute(
                "INSERT INTO veredictos (paso_id, kind, created_at) VALUES (?, ?, ?)",
                (paso_id, kind, _iso(now or utcnow())),
            )
            self._conn.commit()

    def resumen_bar(self, bar_id: int) -> dict[str, float]:
        with self._lock:
            fila = self._conn.execute(
                """
                SELECT COUNT(*) AS pasos,
                       COALESCE(SUM(es_primera), 0) AS primeras,
                       COALESCE(SUM(credito), 0) AS credito,
                       COUNT(contacto) AS contactos
                FROM pasos WHERE bar_id = ?
                """,
                (bar_id,),
            ).fetchone()
            especiales = self._conn.execute(
                """
                SELECT COUNT(DISTINCT veredictos.paso_id) FROM veredictos
                JOIN pasos ON pasos.id = veredictos.paso_id
                WHERE pasos.bar_id = ? AND veredictos.kind = 'especial'
                """,
                (bar_id,),
            ).fetchone()[0]
        return {
            "pasos": int(fila["pasos"]),
            "primeras": int(fila["primeras"]),
            "credito": float(fila["credito"]),
            "contactos": int(fila["contactos"]),
            "especiales": int(especiales),
        }

    # ------------------------------------------------------------ anfitriones

    def host_hash(self, user_id: int, salt: bytes) -> str:
        return hmac.new(salt, str(user_id).encode("ascii"), hashlib.sha256).hexdigest()

    def bar_de_anfitrion(self, host_hash: str) -> int | None:
        with self._lock:
            fila = self._conn.execute(
                "SELECT bar_id FROM anfitriones WHERE host_hash = ? ORDER BY created_at DESC LIMIT 1",
                (host_hash,),
            ).fetchone()
        return int(fila["bar_id"]) if fila else None

    def vincular_anfitrion(
        self, host_hash: str, bar_id: int, now: datetime | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO anfitriones (host_hash, bar_id, created_at) VALUES (?, ?, ?)",
                (host_hash, bar_id, _iso(now or utcnow())),
            )
            self._conn.commit()

    # ---------------------------------------------------------------- codigos

    @staticmethod
    def code_hash(code: str) -> str:
        return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()

    def crear_codigo(
        self,
        code: str,
        rol: str,
        *,
        bar_id: int | None = None,
        paso_id: int | None = None,
        max_usos: int = 1,
        now: datetime | None = None,
    ) -> None:
        if rol not in ROLES_CODIGO:
            raise ValueError(f"rol de codigo desconocido: {rol!r}")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO codigos (code_hash, rol, bar_id, paso_id, usos, max_usos, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (self.code_hash(code), rol, bar_id, paso_id, max_usos, _iso(now or utcnow())),
            )
            self._conn.commit()

    def validar_codigo(self, code: str) -> Codigo | None:
        """Mira si un codigo sirve. No lo gasta: eso es `consumir_codigo`."""
        with self._lock:
            fila = self._conn.execute(
                "SELECT * FROM codigos WHERE code_hash = ?", (self.code_hash(code),)
            ).fetchone()
        if fila is None or fila["usos"] >= fila["max_usos"]:
            return None
        return Codigo(
            id=fila["id"],
            rol=fila["rol"],
            bar_id=fila["bar_id"],
            paso_id=fila["paso_id"],
            usos=fila["usos"],
            max_usos=fila["max_usos"],
        )

    def consumir_codigo(self, codigo_id: int) -> bool:
        """Gasta un uso. El UPDATE condicional evita dos canjes en paralelo."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE codigos SET usos = usos + 1 WHERE id = ? AND usos < max_usos",
                (codigo_id,),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    # ----------------------------------------------------------- nominaciones

    def crear_nominacion(
        self,
        *,
        alias: str,
        lat: float,
        lon: float,
        motivo: str | None,
        paso_id: int | None,
        now: datetime | None = None,
    ) -> int:
        moment = _iso(now or utcnow())
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO nominaciones (alias, lat, lon, motivo, paso_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alias, lat, lon, motivo, paso_id, moment),
            )
            nominacion_id = int(cursor.lastrowid)
            self._conn.execute(
                "INSERT INTO nominacion_eventos (nominacion_id, kind, bar_id, created_at) VALUES (?, 'propuesta', NULL, ?)",
                (nominacion_id, moment),
            )
            self._conn.commit()
            return nominacion_id

    def evento_nominacion(
        self,
        nominacion_id: int,
        kind: str,
        bar_id: int | None = None,
        now: datetime | None = None,
    ) -> None:
        if kind not in EVENTOS_NOMINACION:
            raise ValueError(f"evento de nominacion desconocido: {kind!r}")
        with self._lock:
            self._conn.execute(
                "INSERT INTO nominacion_eventos (nominacion_id, kind, bar_id, created_at) VALUES (?, ?, ?, ?)",
                (nominacion_id, kind, bar_id, _iso(now or utcnow())),
            )
            self._conn.commit()

    def _hidratar_nominaciones(self, filas: list[sqlite3.Row]) -> list[Nominacion]:
        ids = [fila["id"] for fila in filas]
        eventos: dict[int, list[tuple[str, datetime]]] = {nid: [] for nid in ids}
        if ids:
            marcas = ",".join("?" * len(ids))
            with self._lock:
                for fila in self._conn.execute(
                    f"SELECT nominacion_id, kind, created_at FROM nominacion_eventos WHERE nominacion_id IN ({marcas}) ORDER BY id",
                    ids,
                ):
                    eventos[fila["nominacion_id"]].append(
                        (fila["kind"], _parse(fila["created_at"]))
                    )
        return [
            Nominacion(
                id=fila["id"],
                alias=fila["alias"],
                lat=fila["lat"],
                lon=fila["lon"],
                motivo=fila["motivo"],
                paso_id=fila["paso_id"],
                created_at=_parse(fila["created_at"]),
                estado=estado_nominacion(eventos[fila["id"]]),
            )
            for fila in filas
        ]

    def nominaciones_abiertas(self, limit: int = 10) -> list[Nominacion]:
        with self._lock:
            filas = self._conn.execute(
                "SELECT * FROM nominaciones ORDER BY id LIMIT ?", (limit * 4,)
            ).fetchall()
        abiertas = [n for n in self._hidratar_nominaciones(filas) if n.estado == "propuesta"]
        return abiertas[:limit]

    def get_nominacion(self, nominacion_id: int) -> Nominacion | None:
        with self._lock:
            fila = self._conn.execute(
                "SELECT * FROM nominaciones WHERE id = ?", (nominacion_id,)
            ).fetchone()
        if fila is None:
            return None
        return self._hidratar_nominaciones([fila])[0]

    def aprobar_nominacion(self, nominacion_id: int, now: datetime | None = None) -> int | None:
        """Convierte una propuesta en un bar de la red. Devuelve el id del bar."""
        nominacion = self.get_nominacion(nominacion_id)
        if nominacion is None or nominacion.estado != "propuesta":
            return None
        bar_id = self.alta_bar(
            alias=nominacion.alias,
            lat=nominacion.lat,
            lon=nominacion.lon,
            nota=nominacion.motivo,
            placa_lugar="sin_definir",
            origen="nominado",
            now=now,
        )
        self.evento_nominacion(nominacion_id, APROBADA, bar_id, now)
        return bar_id

    # ------------------------------------------------------------------ censo

    def stats(self) -> dict[str, float]:
        with self._lock:
            bares = self._conn.execute("SELECT * FROM bares").fetchall()
            pasos = self._conn.execute(
                "SELECT COUNT(*) AS cuantos, COALESCE(SUM(credito), 0) AS credito, COUNT(contacto) AS contactos FROM pasos"
            ).fetchone()
            especiales = int(
                self._conn.execute(
                    "SELECT COUNT(DISTINCT paso_id) FROM veredictos WHERE kind = 'especial'"
                ).fetchone()[0]
            )
            sin_leer = int(
                self._conn.execute(
                    """
                    SELECT COUNT(*) FROM pasos
                    LEFT JOIN veredictos ON veredictos.paso_id = pasos.id
                    WHERE veredictos.id IS NULL
                    """
                ).fetchone()[0]
            )
            anfitriones = int(
                self._conn.execute("SELECT COUNT(*) FROM anfitriones").fetchone()[0]
            )
        hidratados = self._hidratar_bares(bares)
        placas = self.resumen_placas()
        return {
            "bares": len(hidratados),
            "activos": sum(1 for bar in hidratados if es_visitable(bar.estado)),
            "pasos": int(pasos["cuantos"]),
            "contactos": int(pasos["contactos"]),
            "credito": float(pasos["credito"]),
            "especiales": especiales,
            "sin_leer": sin_leer,
            "anfitriones": anfitriones,
            "placas": sum(placas.values()),
            "placas_stock": placas.get(EMITIDA, 0),
            "placas_en_camino": placas.get(ENVIADA, 0),
            "placas_puestas": placas.get(INSTALADA, 0),
        }
