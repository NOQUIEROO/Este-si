# ODD

El segundo bot del repo. Te dice dónde hay **bares ODD**: bares aprobados por
el criterio ODD, que se reconocen por una placa metálica del tamaño de una
tarjeta de crédito, numerada y pegada abajo en el frente, en el baño o en la
barra.

Si entrás a uno y decís que sabés de ODD, te invitan hasta **USD 3** en
consumición. Lo único que tenés que hacer es dejar una reflexión escrita y
dejar que el dueño le saque una foto. Si es tu primera vez, además dejás un
contacto — una sola vez, nunca más.

Las reflexiones las leemos. La que nos parece especial se paga con lo único
que no se compra: **esa persona elige el próximo bar de la red**.

---

## El circuito completo

```
   nosotros                 el bar                    la gente
   ────────                 ──────                    ────────
1. /altabar  ──────────────► queda en el mapa
2. /placas 20                                          
3. /asignar 7 3  ──────────► le llega la placa #7
4. código de anfitrión ────► el dueño lo canjea
                             y ve su panel
                                     ◄──────────────── entra y dice
                                                       que sabe de ODD
                             📷 carga la reflexión
                             + contacto si es 1ª vez
                                                       🪙 USD 3
5. la reflexión nos llega
   al toque, con dos botones
6. ✨ Especial ────────────────────────────────────────► código de nominación
                                                       elige un bar nuevo
7. /propuestas ► ✅ Entra ──► vuelve al paso 3
```

El círculo se cierra solo: cada bar nuevo lo elige alguien que escribió algo
que valió la pena en un bar viejo.

---

## Levantarlo

```bash
cp .env.odd.example .env.odd   # token de @BotFather + tu id y el de Andy
docker compose up -d --build odd
docker compose logs -f odd
```

Sin Docker:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.odd.example .env.odd
.venv/bin/python odd_main.py
```

Son **dos bots de Telegram distintos**: ODD necesita su propio token, su
propio `.env.odd` y su propia base. No se pisan.

---

## Los tres menús

El bot no te pregunta quién sos: se da cuenta.

### El que camina (cualquiera)

| | |
|---|---|
| **📍 Bares con placa cerca** | Compartís tu posición y te devuelve los bares de la red ordenados por distancia, con la dirección y dónde está la placa. |
| **🪙 Cómo funciona** | El trato entero, en una pantalla. |
| **🔎 Verificar una placa** | Mandás el número que dice la placa y te confirma si es de la red. Es lo que hace que la placa no se pueda falsificar de arriba: el número tiene que existir *y* corresponder a ese bar. |

### El que atiende (el dueño del bar)

Canjea una vez el código `ODD-XXXX-XXXX` que le pasamos y su menú cambia para
siempre.

| | |
|---|---|
| **✍️ Cargar una reflexión** | Foto → ¿primera vez? → contacto. Tres toques, veinte segundos, con el cliente todavía en la barra. |
| **📊 Mi bar** | Cuántas reflexiones lleva, cuántas primeras veces, cuántas resultaron especiales y cuánto invitó en total. |

### Nosotros (los admins)

| Comando | Qué hace |
|---|---|
| `/altabar` | Alta de un bar: pin, nombre, dirección, dónde va la placa, nota. Al final te devuelve el código de anfitrión para reenviarle al dueño. |
| `/bares` | La red entera con su estado, su placa y su actividad. |
| `/pausar <id>` · `/reactivar <id>` · `/retirar <id>` | Un bar que cierra en enero se pausa; uno que se portó mal se retira. Nunca se borra. |
| `/placas` | Estado del stock y qué números están libres. |
| `/placas 20` | Acuña 20 números nuevos, correlativos. Esos son los que mandás a grabar. |
| `/asignar <n> <bar>` · `/enviada <n>` · `/instalada <n>` | El viaje de una placa, de la caja a la pared. |
| `/anfitrion <bar>` | Un código nuevo para el dueño (por si cambió de teléfono o entró un socio). |
| `/pendientes` | Las reflexiones que todavía no leímos, con los dos botones. |
| `/propuestas` | Los bares que propuso la gente con reflexión especial. |
| `/censo` | Todo en números. |
| `/respaldo` | Te manda la base por chat, ahora. |

Cada reflexión que carga un bar **te llega al toque** con dos botones: ✨
Especial y ✓ Leída. Si tocás ✨, el bot emite el código de nominación y te
muestra el contacto de esa persona para que le escribas. Leerlas es el trabajo
de verdad de esta red, así que tiene la menor fricción posible.

---

## La placa

Es lo único que distingue un bar ODD de cualquier otro bar, así que el
software la trata como un objeto con vida propia:

```
emitida ──► asignada ──► enviada ──► instalada
   │                                     │
   └────────────── baja ◄────────────────┘
```

Los números son **correlativos y únicos**: la placa 7 existe una sola vez y
apunta a un solo bar. Cualquiera puede verificar un número desde el bot, y por
eso conviene emitir de a lotes chicos: un número que no emitiste nunca es un
número que el bot va a rechazar.

Si un bar sale de la red, su placa se da de baja y el número no se recicla.

---

## Qué guarda esto

Acá el contrato de privacidad es **distinto** al del otro bot del repo, y a
propósito.

**De quien solo busca bares: nada.** Buscar no escribe una fila en ningún
lado. La ubicación se usa para calcular distancias y se olvida.

**De una reflexión:** el `file_id` de la foto (los bytes viven en Telegram, no
en nuestro disco), en qué bar fue y cuándo. La reflexión no lleva nombre.

**Del contacto de la primera vez: se guarda en claro, y es el corazón del
trato.** La persona lo entrega sabiendo que lo entrega, una sola vez, a cambio
de la consumición, y sirve para una sola cosa: poder avisarle si su reflexión
resultó especial. Fingir que ese dato no existe sería mentirse; lo que
corresponde es tratarlo como lo que es. Por eso:

- vale la pena poner `BACKUP_CHAT_ID` (un contacto perdido no se puede volver
  a pedir);
- `/privacidad` en el bot lo dice con todas las letras, sin letra chica;
- si alguien pide que lo borremos, se borra.

**De los dueños de bar:** un HMAC de su id de Telegram con una sal que vive
fuera de la base (`DATA_DIR/.salt` o `SECRET_SALT`). Alcanza para saber qué
bar administran y no sirve para nada más.

---

## Cómo está armado

```
odd_main.py             arranque
odd/
  config.py             variables de entorno, .env.odd, sal secreta
  estado.py             estados derivados, funciones puras
  db.py                 SQLite sin ORM, solo inserción, sin DELETE
  lexicon.py            todo lo que el bot dice, en un solo lugar
  handlers.py           los tres menús
  backup.py             respaldos en caliente
```

**Nada se edita y nada se borra.** Un bar no cambia de estado: se le agrega un
evento. Una placa no se modifica: se le agrega un movimiento. El estado actual
siempre se *deriva* del último evento, en `estado.py`, con funciones puras que
se testean sin tocar la base. Ante dos eventos con la misma hora gana el
último cargado, así el estado nunca queda a merced del orden en que SQLite
devuelva las filas.

Lo único que comparte con el otro bot es `glitchmap.geo`: haversine y caja de
búsqueda. Tener dos copias de la misma trigonometría no le hace bien a nadie.

```bash
.venv/bin/python -m pytest -q
```
