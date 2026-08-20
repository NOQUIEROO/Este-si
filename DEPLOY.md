# Dónde dejarlo corriendo

## Primero, lo que confunde a todo el mundo

Un bot de Telegram **no** es una app que vive en el celular de cada uno. Es un
programa que tiene que estar escuchando cuando alguien le escribe. Si nada está
escuchando, el bot no contesta.

O sea: sí, algo tiene que estar prendido las 24 horas. Pero **no tiene que ser
tu computadora**, y no tiene que costarte plata.

---

## Opción A — Servidor gratis en la nube *(la recomendada)*

**Oracle Cloud Always Free** regala máquinas chiquitas gratis, sin vencimiento.
El bot consume tan poco que le sobra de todo.

1. Creá una cuenta en `cloud.oracle.com` → *Always Free*. Te pide una tarjeta
   **solo para verificar identidad**: mientras te quedes en el plan gratis no
   te cobran.
2. Creá una instancia con **Ubuntu**, la más chica que te ofrezcan.
3. Conectate por SSH (la propia web de Oracle te da un botón de consola) y
   pegá esto:

```bash
curl -fsSL https://raw.githubusercontent.com/NOQUIEROO/Este-si/main/deploy/install.sh | sudo bash
```

Te va a pedir el token de @BotFather y tu número de Telegram. Nada más.

Cuando termina, el bot queda andando **para siempre**: si se cae vuelve solo,
si el servidor se reinicia arranca solo.

> Los planes gratuitos de las nubes cambian cada tanto. Si Oracle no te
> funciona, cualquier servidor Linux con Ubuntu sirve — el comando es el mismo.

---

## Opción B — Un celular Android viejo *(gratis del todo)*

Si tenés un teléfono en un cajón, sirve perfecto: enchufado consume menos que
un cargador y no depende de ninguna cuenta.

1. Instalá **Termux** (desde F-Droid, no desde Play Store).
2. Adentro de Termux:

```bash
pkg install python git -y
git clone https://github.com/NOQUIEROO/Este-si.git
cd Este-si
pip install -r requirements.txt
cp .env.example .env
nano .env          # pegás el token y tu número
termux-wake-lock   # para que Android no lo duerma
python main.py
```

3. Instalá **Termux:Boot** para que arranque solo cuando prendés el teléfono.

Dejalo enchufado y conectado al wifi. Listo.

*(Acá no sirve `install.sh`: Android no tiene systemd.)*

---

## Opción C — Un servidor pago, si querés cero vueltas

Un VPS de **Hetzner** sale unos 4 €/mes y es el camino más corto: creás el
servidor con Ubuntu, entrás por SSH y pegás el mismo comando de la Opción A.

---

## Una vez que está andando

| Qué querés | Comando |
|---|---|
| Ver qué está haciendo | `journalctl -u glitchmap -f` |
| Apagarlo un rato | `sudo systemctl stop glitchmap` |
| Volver a prenderlo | `sudo systemctl start glitchmap` |
| Actualizar el código | `sudo bash /opt/glitchmap/deploy/install.sh` |
| Dónde vive la base | `/var/lib/glitchmap` |

Si pusiste tu número de Telegram durante la instalación, **cada 6 horas te va a
llegar por chat una copia de la base como archivo**. Ese es tu respaldo: aunque
se prenda fuego el servidor, los lugares siguen ahí.

Para volver a levantar todo desde cero en otra máquina: corrés el instalador,
parás el servicio, ponés el archivo de respaldo como
`/var/lib/glitchmap/glitchmap.db` y lo prendés de nuevo.
