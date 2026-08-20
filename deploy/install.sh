#!/usr/bin/env bash
#
# Instala la Red de Anomalias en cualquier Linux con systemd y la deja
# corriendo sola, para siempre. Se reinicia si se cae y arranca sola si el
# servidor se reinicia.
#
#   curl -fsSL https://raw.githubusercontent.com/NOQUIEROO/Este-si/main/deploy/install.sh | sudo bash
#
# O, si ya clonaste el repo:  sudo bash deploy/install.sh
#
set -euo pipefail

REPO="${REPO:-https://github.com/NOQUIEROO/Este-si.git}"
BRANCH="${BRANCH:-main}"
DEST="${DEST:-/opt/glitchmap}"
SERVICE_USER="glitchmap"

die() { echo "❌ $*" >&2; exit 1; }
say() { echo "▞ $*"; }

[ "$(id -u)" -eq 0 ] || die "Corrélo con sudo:  sudo bash $0"

say "Instalando lo que hace falta..."
if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip git ca-certificates
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q python3 python3-pip git ca-certificates
else
    die "No reconozco el gestor de paquetes. Instalá python3, python3-venv y git a mano."
fi

id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$DEST" --shell /usr/sbin/nologin "$SERVICE_USER"

if [ -d "$DEST/.git" ]; then
    say "Actualizando el código en $DEST..."
    git -C "$DEST" fetch --quiet origin "$BRANCH"
    git -C "$DEST" reset --hard --quiet "origin/$BRANCH"
else
    say "Bajando el código a $DEST..."
    rm -rf "$DEST"
    git clone --quiet --branch "$BRANCH" --depth 1 "$REPO" "$DEST"
fi

say "Preparando el entorno de Python..."
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install --quiet --upgrade pip
"$DEST/.venv/bin/pip" install --quiet -r "$DEST/requirements.txt"

# --- credenciales -----------------------------------------------------------
# Se piden una sola vez. Si el archivo ya existe no se toca, asi que volver a
# correr este script actualiza el codigo sin pedirte nada.
if [ ! -f "$DEST/.env" ]; then
    if [ -z "${BOT_TOKEN:-}" ]; then
        echo
        echo "Pegá el token que te dio @BotFather y apretá Enter:"
        read -r BOT_TOKEN < /dev/tty
    fi
    [ -n "$BOT_TOKEN" ] || die "Sin token no puedo seguir."

    if [ -z "${ADMIN_IDS:-}" ]; then
        echo
        echo "Pegá tu número de usuario de Telegram (te lo dice @userinfobot)."
        echo "Si lo dejás vacío, el bot te va a dar un código de acceso en el log:"
        read -r ADMIN_IDS < /dev/tty
    fi

    # El respaldo por chat solo tiene sentido si hay un unico destinatario.
    BACKUP_CHAT_ID=""
    case "$ADMIN_IDS" in
        ''|*[!0-9]*) BACKUP_CHAT_ID="" ;;
        *) BACKUP_CHAT_ID="$ADMIN_IDS" ;;
    esac

    umask 077
    cat > "$DEST/.env" <<ENVFILE
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS
SCAN_RADIUS_M=3000
SCAN_LIMIT=5
BACKUP_EVERY_HOURS=6
BACKUP_KEEP=48
BACKUP_CHAT_ID=$BACKUP_CHAT_ID
ENVFILE
    say "Guardé la configuración en $DEST/.env"
    if [ -n "$BACKUP_CHAT_ID" ]; then
        say "Los respaldos de la base te van a llegar por chat al mismo Telegram."
    fi
else
    say "Ya había un .env: lo dejo como está."
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$DEST"
chmod 600 "$DEST/.env"

say "Instalando el servicio..."
install -m 644 "$DEST/deploy/glitchmap.service" /etc/systemd/system/glitchmap.service
systemctl daemon-reload
systemctl enable --quiet --now glitchmap.service

sleep 3
echo
if systemctl is-active --quiet glitchmap.service; then
    say "✅ Listo. El bot está corriendo y va a seguir corriendo solo."
else
    say "⚠️  El servicio no quedó activo. Mirá qué pasó con:"
    echo "     journalctl -u glitchmap -n 50 --no-pager"
    exit 1
fi

echo
echo "  Ver qué está haciendo:     journalctl -u glitchmap -f"
echo "  Apagarlo:                  sudo systemctl stop glitchmap"
echo "  Prenderlo:                 sudo systemctl start glitchmap"
echo "  Actualizar el código:      sudo bash $DEST/deploy/install.sh"
echo "  La base vive en:           /var/lib/glitchmap"
echo
if [ -z "$(grep -E '^ADMIN_IDS=.+' "$DEST/.env" || true)" ]; then
    echo "  Como no pusiste tu número, buscá tu código de acceso acá:"
    echo "     journalctl -u glitchmap | grep 'PRIMER CÓDIGO'"
    echo
fi
