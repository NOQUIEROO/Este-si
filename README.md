# Red de Anomalías

Bot de Telegram para mapear, entre pocos, los lugares donde la realidad afloja
un poco: rincones tranquilos, con techo, donde no pasa nadie.

Es un mapa colaborativo con dos gestos y nada más: **escanear** lo que hay
cerca tuyo y **registrar** un punto nuevo. Todo lo demás es un botón sobre esos
dos.

> En este repo viven **dos bots**. El otro es **[ODD](ODD.md)**: te dice dónde
> hay bares con placa ODD, donde te invitan hasta USD 3 a cambio de una
> reflexión escrita. Comparten la geometría y nada más — token propio, base
> propia, proceso propio (`python odd_main.py`).

---

## Levantarlo

```bash
cp .env.example .env      # pegá el token de @BotFather y tu user id
docker compose up -d --build
docker compose logs -f    # acá aparece el primer código de acceso
```

Sin Docker:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python main.py
```

La primera vez que arranca con la base vacía, el bot emite un código de acceso
y lo escribe en el log:

```
PRIMER CÓDIGO DE ACCESO (usalo vos): GLX-VQ8S-KW77
```

Mandáselo al bot por chat y ya estás adentro. Si pusiste tu id en `ADMIN_IDS`,
entrás solo y podés generar códigos nuevos con `/invitar 10`.

---

## Cómo se usa

| | |
|---|---|
| **📡 Escanear la grilla** | Compartís tu posición y te devuelve las anomalías más cercanas ordenadas por distancia. Si no hay nada, ampliás el radio con un botón. |
| **🛰 Registrar anomalía** | Marcás el punto, le ponés un nombre y contestás tres botones. Treinta segundos. |
| **✅ / ⚠️** | En la ficha de cada lugar: confirmás que sigue sirviendo, o avisás que colapsó. |

### Comandos

| Comando | Qué hace |
|---|---|
| `/start` | Menú |
| `/escanear` | Barrido de la zona |
| `/registrar` | Cargar una anomalía |
| `/manual` | Manual de campo |
| `/privacidad` | Qué guarda y qué no |
| `/cancelar` | Abortar un registro a medias |
| `/invitar [usos]` | *(admin)* Emite un código + link de invitación |
| `/censo` | *(admin)* Estado de la grilla |
| `/respaldo` | *(admin)* Te manda la base por chat, ahora |

---

## El vocabulario carga información real

El disfraz no es decoración: cada campo "de ciencia ficción" es un dato que
usás parado en la calle.

| Campo | Qué te está diciendo |
|---|---|
| **Cobertura** | ¿Hay techo? ¿Te tapa el viento y la lluvia? |
| **Interferencia** | ¿Cuánta gente pasa por ahí? |
| **Ventana temporal** | ¿A qué hora conviene? |
| **Índice de estabilidad** | ¿Sigue sirviendo, según los que volvieron? |

### El índice de estabilidad

Es lo que evita que el mapa se pudra con el tiempo, y es una función pura
(`glitchmap/stability.py`) — mismo input, mismo resultado, testeable sin base:

- Arranca en **55**.
- **+9** por confirmación, **−22** por colapso reportado.
- Cada señal pesa **la mitad cada 30 días**: lo que pasó hace un año casi no
  cuenta.
- Si nadie toca un lugar en **45 días**, empieza a erosionarse solo.
- Por debajo de **25** deja de aparecer en los escaneos normales
  (`👻 Incluir desvanecidas` las muestra igual).

Un lugar que dejó de servir **no se borra: se desvanece**. La metáfora y la
salud de los datos son la misma cosa.

---

## Privacidad: qué guarda esto

Esto es lo que decide el diseño entero de la base, así que vale ser preciso.

**De los lugares** se guarda: coordenadas, alias, los tres atributos, la nota.

**De las personas** no se guarda nada.

Las tablas `glitches` y `signals` **no tienen ninguna columna de usuario**. Ni
el id de Telegram, ni un nombre, ni un hash. No existe forma de saber quién
cargó un punto ni quién lo confirmó — ni para el que corre el bot, ni para
alguien con la base entera en la mano. No es una promesa: es que el dato no
está. Hay un test que lo verifica (`test_nadie_puede_saber_quien_cargo_que`).

Lo único que recuerda personas es la lista de la puerta (`members`), y guarda
un HMAC-SHA256 de tu id con una sal secreta que vive **fuera** de la base
(`DATA_DIR/.salt` o `SECRET_SALT`). Es lo mínimo físicamente necesario para que
una red por invitación no te pida el código en cada mensaje, y no se cruza con
el contenido.

**Consecuencia asumida:** el bot no puede mostrarte "tus" reportes ni dejarte
borrar los tuyos, porque no sabe cuáles son. Ese es el precio del anonimato
fuerte, y está elegido a propósito.

El límite anti-spam vive **en memoria** y se pierde al reiniciar, justamente
para no dejar en disco un registro de quién hizo qué y cuándo.

> El disfraz de "glitches de la realidad" es una capa de vocabulario. Hace que
> el bot no se lea de un vistazo por encima del hombro, y nada más — no es
> protección legal ni criptográfica. Lo que sí protege de verdad es lo de
> arriba: los datos que directamente no existen.

---

## Que no se pierda nada

- **Nada se borra.** No hay un solo `DELETE` de SQL en el código, y hay un test que
  falla si alguien agrega un método que borre. Las tablas de contenido son de
  solo inserción: un lugar que colapsa pierde estabilidad, no filas.
- **SQLite en `WAL` + `synchronous = FULL`**: durabilidad antes que velocidad.
  Un corte de luz no se lleva la última escritura.
- **Respaldo al arrancar** y después cada `BACKUP_EVERY_HOURS` (6 por defecto),
  con la API `.backup` de SQLite: copia consistente con el bot funcionando.
- **Respaldo fuera del servidor**: si ponés `BACKUP_CHAT_ID`, cada copia se
  manda como archivo a ese chat. Si el disco se muere, la base sigue viva en
  Telegram.
- **La base vive en un volumen** (`/data`), nunca en la imagen: los redeploys
  reemplazan el código y no tocan los datos.
- Lo único que se poda son copias redundantes viejas, y solo cuando ya hay
  `BACKUP_KEEP` copias más nuevas.

Para restaurar: pará el bot, poné el `.db` del respaldo en
`DATA_DIR/glitchmap.db`, arrancá. Nada más.

**Guardá la sal.** Si perdés `DATA_DIR/.salt`, los lugares siguen todos ahí
pero cada miembro tiene que canjear un código de nuevo. Si vas a mover el bot
de máquina, fijá `SECRET_SALT` en el `.env` en vez de dejar que se genere sola.

---

## Cómo está armado

```
main.py                 arranque
glitchmap/
  config.py             variables de entorno, .env, sal secreta
  geo.py                haversine + caja de búsqueda (sin dependencias)
  stability.py          el índice, función pura
  db.py                 SQLite sin ORM, solo inserción, sin DELETE
  lexicon.py            todo lo que el bot dice, en un solo lugar
  handlers.py           la puerta, el escaneo y el registro
  backup.py             respaldos en caliente
tests/                  37 tests, ninguno toca la red
```

Sin webhook, sin servidor web, sin dominio, sin certificados: long polling.
Sin Postgres, sin PostGIS: la caja de búsqueda descarta casi todo en SQL y la
distancia final se calcula en Python. Corre en una Raspberry.

```bash
.venv/bin/python -m pytest -q
```
