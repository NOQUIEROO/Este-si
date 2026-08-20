#!/data/data/com.termux/files/usr/bin/bash
#
# Deja la Red de Anomalias corriendo en un Android viejo, con Termux.
# Sin cuentas, sin tarjeta, sin servidor.
#
#   curl -fsSL https://raw.githubusercontent.com/NOQUIEROO/Este-si/main/deploy/termux.sh | bash
#
set -euo pipefail

DEST="$HOME/Este-si"
REPO="${REPO:-https://github.com/NOQUIEROO/Este-si.git}"
BRANCH="${BRANCH:-main}"

say() { echo "▞ $*"; }
die() { echo "❌ $*" >&2; exit 1; }

say "Instalando lo que hace falta (esto tarda unos minutos)..."
pkg update -y >/dev/null 2>&1 || true
pkg install -y python git >/dev/null

if [ -d "$DEST/.git" ]; then
    say "Actualizando el código..."
    git -C "$DEST" fetch --quiet origin "$BRANCH"
    git -C "$DEST" reset --hard --quiet "origin/$BRANCH"
else
    say "Bajando el código..."
    git clone --quiet --branch "$BRANCH" --depth 1 "$REPO" "$DEST"
fi

cd "$DEST"
say "Instalando las librerías..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

if [ ! -f "$DEST/.env" ]; then
    echo
    echo "Pegá el token que te dio @BotFather y apretá Enter:"
    read -r BOT_TOKEN < /dev/tty
    [ -n "$BOT_TOKEN" ] || die "Sin token no puedo seguir."

    echo
    echo "Pegá tu número de usuario de Telegram (te lo dice @userinfobot)."
    echo "Si no lo sabés dejalo vacío y seguí:"
    read -r ADMIN_IDS < /dev/tty

    BACKUP_CHAT_ID=""
    case "$ADMIN_IDS" in
        ''|*[!0-9]*) BACKUP_CHAT_ID="" ;;
        *) BACKUP_CHAT_ID="$ADMIN_IDS" ;;
    esac

    umask 077
    cat > "$DEST/.env" <<ENVFILE
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS
DATA_DIR=$DEST/data
SCAN_RADIUS_M=3000
SCAN_LIMIT=5
BACKUP_EVERY_HOURS=6
BACKUP_KEEP=48
BACKUP_CHAT_ID=$BACKUP_CHAT_ID
ENVFILE
else
    say "Ya había configuración guardada: la dejo como está."
fi

# Que Android no lo mate mientras la pantalla esta apagada.
termux-wake-lock 2>/dev/null || true

# Arranque automatico cuando prendes el telefono (necesita la app Termux:Boot).
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/glitchmap.sh" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd "$HOME/Este-si" && exec python main.py
BOOT
chmod +x "$HOME/.termux/boot/glitchmap.sh"

echo
say "✅ Todo listo. Arranco el bot ahora."
say "   Para que siga andando, dejá Termux abierto y el teléfono enchufado."
say "   Instalá la app Termux:Boot y arranca solo cada vez que lo prendas."
echo
echo "   Para apagarlo: Ctrl+C"
echo "   Para volver a prenderlo:  cd ~/Este-si && python main.py"
echo
sleep 2
exec python main.py
