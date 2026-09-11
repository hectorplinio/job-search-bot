# Job Search Bot

Busca ofertas de backend en siete portales, las puntúa contra tu perfil y te
manda al Telegram solo las que valen la pena. Le pasas el enlace de una oferta
y te devuelve la cover letter y el summary del CV adaptados.

Hecho a medida para el perfil de Hector Plinio Navarro (Python, Node/TypeScript,
microservicios, arquitectura hexagonal). Todo el criterio vive en `config.yaml`
y `profile/cv.yaml`, así que cambiarlo no toca código.

---

## Arranque rápido

```bash
python -m venv .venv
.venv\Scripts\activate          # en Linux/macOS: source .venv/bin/activate
pip install -e .

copy .env.example .env          # en Linux/macOS: cp .env.example .env
```

Rellena `.env` con tres cosas:

| Variable | De dónde sale |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Habla con [@BotFather](https://t.me/BotFather), `/newbot` |
| `TELEGRAM_CHAT_ID` | Escríbele algo a tu bot y ejecuta `jobbot chat-id` |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/settings/keys) |

Prueba sin gastar nada ni mandar nada:

```bash
jobbot run --dry-run --no-llm
```

Cuando te convenza lo que sale por pantalla:

```bash
jobbot run
```

---

## Comandos

```
jobbot run                    una pasada: busca, filtra, puntúa y avisa
jobbot run --dry-run          igual, pero sin mandar nada a Telegram
jobbot run --no-llm           solo scoring por reglas, sin gastar en la API
jobbot bot                    arranca el bot para hablar con él
jobbot apply <url>            cover letter + summary de una oferta
jobbot apply <url> -o out/    y además los guarda en ficheros
jobbot stats                  qué lleva visto el bot
jobbot usage                  cuánto llevas gastado en la API de Claude
jobbot sources                qué fuentes están activas
jobbot check-sources          prueba cada fuente y dice cuántas devuelve
jobbot login [portal]         renueva la sesión de un portal con tu cuenta
jobbot cookies                estado de las sesiones guardadas
jobbot chat-id                tu chat id de Telegram
```

En Telegram, con `jobbot bot` corriendo:

```
/buscar          lanza una búsqueda ahora
/top             las mejores pendientes de mandarte
/oferta <url>    cover letter + summary
/carta <url>     solo la cover letter
/summary <url>   solo el summary del CV
/stats           historial
/usage           gasto en la API de Claude
/proxima         cuándo toca la siguiente búsqueda
```

También puedes pegarle un enlace a pelo, o el texto de la oferta cuando el
portal pide login. Cada alerta lleva dos botones, **Cover letter** y **Summary**,
que generan los documentos sin que tengas que copiar la URL.

---

## Las fuentes

Probadas contra los portales reales en septiembre de 2026.

| Fuente | Cómo entra | Estado |
|---|---|---|
| Manfred | API pública JSON | La mejor: trae salario y % de remoto en el listado |
| LinkedIn | Endpoint de invitado, sin login | Funciona, pero su ranking esconde ofertas |
| Tecnoempleo | HTML del buscador | Funciona |
| InfoJobs | HTML del buscador | Funciona a ratos: corta por IP y tarda en soltar |
| RemoteOK | API pública JSON | Funciona; ofertas internacionales en USD |
| We Work Remotely | RSS | Funciona |
| Remotive | API pública JSON | Empresas de EEUU; su feed libre son 16 ofertas |
| Himalayas | API pública JSON | Empresas de EEUU; pagina, pero 9 de cada 10 son US only |
| Otta | Navegador con tu sesión | Funciona: recorre tus matches uno a uno |
| Glassdoor | HTML del buscador | **Apagada**: 403 por IP a las pocas peticiones |

Otta es la única que necesita cuenta: Playwright más `jobbot login otta`. Las
otras seis funcionan sin registrarse en ningún sitio.

**Sobre las ofertas de Estados Unidos.** Remotive y Himalayas publican desde
qué países admiten candidatos, así que el bot descarta las que no puedes
aceptar antes de puntuarlas. La proporción medida en una pasada real:

```
120 ofertas revisadas en Himalayas -> 110 solo para EEUU -> 2 aptas
```

No es un fallo del filtro, es cómo está el mercado. Una empresa estadounidense
necesita un Employer of Record para contratar en España, y la mayoría no lo
tiene montado.

**Lo que LinkedIn no te va a dar.** Su endpoint de invitado sirve 10
resultados por petición, así que el bot pagina para recoger más. Aun así, su
ranking para búsquedas genéricas deja ofertas fuera del alcance: comprobado
que una oferta concreta no aparecía en los 100 primeros resultados de
`backend engineer python`, y sí salía buscando por el nombre de la empresa.
Ninguna cantidad de páginas arregla eso. Un buscador es un embudo, no una
garantía.

Una fuente que falla devuelve cero y las demás siguen: nunca tumba la ejecución.
El resumen de cada pasada te dice cuántas ha traído cada una, así que si una se
rompe lo ves enseguida.

---

## Usar tus cuentas

Cuatro portales cambian de comportamiento si entras logueado. Resumen de qué
gana cada uno y qué arriesgas:

| Portal | Qué gana con tu cuenta | Recomendación |
|---|---|---|
| InfoJobs | Deja de cortarte por IP | Sí |
| Glassdoor | Deja de responder 403 | Sí |
| Otta | Es la única forma: el listado está tras el alta | Sí, con navegador |
| LinkedIn | Prácticamente nada | **No** |

### Por qué LinkedIn no

El endpoint de invitado ya devuelve los mismos resultados sin autenticarse.
Añadir tu sesión no mejora nada apreciable y sí cambia quién paga si algo sale
mal: un bloqueo por IP anónima no te afecta, una restricción de cuenta te deja
sin perfil justo mientras buscas trabajo. LinkedIn es de los que más persiguen
el acceso automatizado. El código admite `LINKEDIN_COOKIE` porque es tu
decisión, pero avisa en cada ejecución y `jobbot login linkedin` te pregunta
antes de seguir.

### Cómo se renuevan las sesiones

Las cookies caducan. Copiarlas a mano del navegador cada semana no es plan, y
hacer login con usuario y contraseña por HTTP directo no funciona: los cuatro
portales protegen también el login, con captcha, con detección de cliente o,
en el caso de Otta, con un reto de AWS WAF que exige ejecutar JavaScript.

Lo que sí funciona es un navegador de verdad con perfil persistente:

```bash
pip install -e ".[browser]"
playwright install chromium

jobbot login              # abre una ventana por cada portal
jobbot login infojobs     # o solo uno
jobbot login infojobs --auto   # rellena el formulario con lo de .env
```

La primera vez entras tú en la ventana, con tu 2FA y tu captcha si los pide.
El perfil queda en `data/browser-profile/` y guarda la sesión durante semanas,
así que las siguientes veces basta con repetir el comando: ya no pide
contraseña. Las cookies se guardan en `data/cookies.json` con su fecha de
caducidad, y mandan sobre lo que pongas a mano en `.env`.

```bash
jobbot cookies         # qué sesiones hay y cuánto les queda
jobbot check-sources   # prueba cada fuente y dice cuántas devuelve
```

`jobbot cookies` nunca imprime el valor de una cookie, solo su estado.

Si prefieres no guardar contraseñas en un fichero, deja `*_USER` y
`*_PASSWORD` vacíos y usa `jobbot login` sin `--auto`. Funciona igual, solo
que entras tú.

### Dónde se guarda todo esto

`data/` contiene el historial, las cookies y el perfil del navegador con tus
cuentas abiertas. Copiar esa carpeta equivale a copiar tus sesiones: quien la
tenga entra sin contraseña y sin segundo factor. Está entera en `.gitignore`.

Consecuencia práctica para el cron: **las fuentes con sesión no funcionan bien
en GitHub Actions**. El runner sale por una IP de centro de datos que sí
dispara verificación por email, y el perfil del navegador no sobrevive entre
ejecuciones. Dos opciones sensatas:

- Dejar en Actions solo lo que no necesita cuenta, que es la mayoría: Manfred,
  LinkedIn de invitado, Tecnoempleo, RemoteOK y We Work Remotely.
- O ejecutar todo en tu máquina con el Programador de tareas, que es donde tus
  sesiones valen.

### Sobre InfoJobs

Devolvió ofertas en la primera pasada y dejó de hacerlo después de encadenar
varias búsquedas: sirve una página de 29 KB sin tarjetas en vez de un 403, y
tarda un buen rato en soltar la IP. El parser está testeado contra su HTML
real, así que cuando responde funciona.

Mitigaciones ya aplicadas: solo dos consultas amplias (`python`, `backend`) en
vez de las seis generales, y 1,5 s entre peticiones al mismo dominio. Desde una
IP doméstica normal, con el bot corriendo cada 4 horas, debería ir bien; si ves
`infojobs 0` una y otra vez, súbele el intervalo o déjale una sola consulta.

### Sobre Glassdoor

El parser funciona y está testeado, pero Glassdoor devuelve 403 tras unas pocas
peticiones desde la misma IP. Está en `config.yaml` con `enabled: false`.
Enciéndela si sales por otra IP o si te da igual que falle a menudo.

### Sobre Otta

Otta es ahora Welcome to the Jungle, y tiene dos barreras encima:

```
x-amzn-waf-action: challenge
```

Un reto de AWS WAF que solo se pasa ejecutando JavaScript, y un listado de
ofertas que está detrás del alta de cuenta: el botón "find a job" lleva a
`/en/get-started/job-title`, no a resultados.

Por eso copiar la cookie a mano no sirve aquí. Comprobado: el token de WAF que
acompaña a la sesión caducaba en poco más de una hora. Lo que sí funciona es
el modo navegador, que resuelve el reto solo y mantiene la sesión viva:

```bash
pip install -e ".[browser]"
playwright install chromium
jobbot login otta
# y en config.yaml: sources.otta.enabled: true
```

**Aviso importante sobre Otta.** Su botón de siguiente no es un "ver la
siguiente oferta": marca la actual como vista y la saca de tus matches. El bot
navega con tu sesión, así que consume tu cola igual que si la recorrieras tú.
Las ofertas te llegan por Telegram con su enlace, pero ya no las verás al
entrar en la web de Otta.

Es la única fuente con este efecto; las otras seis solo leen. Si prefieres
revisar Otta a mano, baja `sources.otta.max_jobs` a 5 para que quede cola, o
ponla en `enabled: false`.

Verificado que el navegador entra y devuelve 598 KB de contenido real donde
`httpx` recibía una página de 2 KB. Lo que **no** he podido verificar es el
parseo del listado logueado, porque hace falta tu cuenta. Si `check-sources`
te da 0 en Otta, el listado estará en otra ruta: ponla en
`sources.otta.search_url`.

Queda también el modo Algolia, apuntando al buscador que usa su propia web
(`algolia_app_id` y `algolia_api_key` en `config.yaml`), pero esas claves rotan
y hay que renovarlas a mano. RemoteOK y We Work Remotely cubren el mismo hueco
de remoto internacional sin ningún mantenimiento.

---

## Cómo decide qué mandarte

Cuatro filtros en orden, del más barato al más caro:

1. **Filtros duros** (`config.yaml`, sección `exclude`). Descartan sin discutir:
   junior o becario en el título, presencial obligatorio, salario por debajo del
   mínimo, oferta caducada, ninguna tecnología del perfil, o un título de otro
   perfil (`Senior .NET Full-stack`, `React Native Developer`) que no nombre
   Python, Node o backend.

2. **Deduplicación**. La misma oferta en LinkedIn y en InfoJobs colapsa en una:
   la huella normaliza empresa y puesto, quitando sufijos societarios, ciudades
   y coletillas de modalidad. Segunda huella por URL canónica para los reposts.

3. **Scoring por reglas**, sobre 100 puntos repartidos así:

   | Bloque | Peso |
   |---|---|
   | Stack coincidente | 45 |
   | Salario | 25 |
   | Modalidad | 20 |
   | Seniority | 10 |

   El resultado se convierte a una nota del 1 al 10. Es una función pura, sin
   red ni estado: misma oferta, misma nota.

4. **Segunda opinión de Claude**, solo para las que ya pasaron el corte. Devuelve
   la nota final y la frase de "por qué encaja" que ves en Telegram. Va en lotes
   de seis ofertas por llamada y con tope por ejecución
   (`scoring.llm_max_offers_per_run`), en lotes de seis ofertas por llamada.

El salario mínimo está en 40.000 € y el objetivo en 50.000 €: por debajo del
mínimo se descarta, y a partir del objetivo el bloque de salario puntúa al
máximo. Las ofertas sin salario publicado se aceptan pero puntúan menos, porque
si no te quedas casi sin nada.

---

## Coste

El scraping y el scoring por reglas son gratis. Lo único que cuesta es Claude,
que se usa en dos sitios:

- **Puntuar** las ofertas que pasaron el corte, en lotes de seis. Con los topes
  de `config.yaml` son 2 o 3 llamadas por ejecución.
- **Escribir** una cover letter y un summary, solo cuando se lo pides tú.

Con `claude-opus-5` a 5 $/M de entrada y 25 $/M de salida, una ejecución sale
por céntimos. `jobbot run --no-llm` lo deja a cero.

No hace falta estimarlo a ojo: el bot apunta cada llamada y `jobbot usage`, o
`/usage` en Telegram, te da el gasto de hoy, del mes y total, más el desglose
entre puntuar ofertas y escribir candidaturas. Guarda el importe calculado en
el momento de la llamada, así que un cambio de precios no reescribe el pasado.

---

## Ejecución periódica

El propio bot la lleva. Mientras `jobbot bot` está escuchando, lanza la
búsqueda cada 4 horas por su cuenta. Se configura en `config.yaml`:

```yaml
schedule:
  enabled: true
  every_hours: 4
  first_run_after_minutes: 3
```

Un solo proceso, y eso importa más de lo que parece: los botones de las
alertas solo responden si el bot está vivo, así que atar las búsquedas a ese
mismo proceso garantiza que nunca recibas una alerta con botones muertos.
`/proxima` te dice cuándo toca la siguiente.

En Windows, un acceso directo en la carpeta de Inicio lo arranca al encender.
El lanzador se relanza solo si el proceso se cae.

La alternativa era una tarea programada llamando a `jobbot run`. Funciona,
pero son dos cosas que mantener vivas en vez de una, y el `.bat` termina en
`pause` para que puedas leer el resumen al ejecutarlo a mano, lo que deja una
ventana abierta en cada disparo automático.

`.github/workflows/job-search.yml` existe pero **con el cron desactivado**, solo
disparo manual. La razón es que dos fuentes dependen de tu máquina: Otta usa el
perfil de navegador con tu sesión, que no sobrevive entre ejecuciones de un
runner, e InfoJobs corta las IPs de centro de datos. Si aun así lo quieres en
Actions, descomenta el `schedule`, añade los tres secrets (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`) y cuenta con perder esas dos fuentes.

El historial de SQLite viaja en la caché del runner. Si se pierde, la primera
pasada repite ofertas que ya viste una vez y luego vuelve a la normalidad.

---

## Estructura

Arquitectura hexagonal, la misma que usas en AscendGate:

```
src/jobbot/
  domain/          reglas puras: modelos, salario, huella, scoring, perfil
  ports.py         qué necesita el dominio del exterior
  adapters/
    sources/       una clase por portal, todas tras la misma interfaz
    http.py        cliente compartido con throttle por dominio y reintentos
    persistence.py historial en SQLite
    telegram_notifier.py
    llm/           Claude: scoring y redacción
    offer_reader.py  URL suelta → oferta (modo manual)
  application/     casos de uso: buscar, redactar
  container.py     raíz de composición
  bot.py           comandos de Telegram
  cli.py           línea de comandos
```

El dominio no importa nada de `adapters`. Los tests de `domain` y `application`
corren sin red.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

52 tests, todos sin red. Los parsers se prueban contra fixtures copiados del
HTML real de cada portal, incluidos los casos raros: el salario de InfoJobs
partido por comentarios HTML, el "Salario:35000 a 38000" pegado de Tecnoempleo,
y el aviso legal que RemoteOK cuela como primer elemento del array.

Aviso honesto: estos tests validan la lógica de parseo, no que el portal siga
sirviendo ese HTML. Cuando un portal cambia el marcado, los tests siguen verdes
y la fuente devuelve cero. Por eso el resumen de cada pasada desglosa por fuente.

### Qué está verificado contra los servicios reales y qué no

Verificado con peticiones en vivo: las seis fuentes activas (94 ofertas en una
pasada), la deduplicación entre portales, el scoring y el historial en SQLite.

Sin verificar, porque hacen falta credenciales que no están puestas: las
llamadas a la API de Claude (`scoring.use_llm`, `jobbot apply`, `/carta`,
`/summary`) y la entrega real de mensajes de Telegram. El código está escrito
contra la API de Mensajes con salidas estructuradas y contra python-telegram-bot
v21, y ambos caminos están cubiertos por tests con dobles, pero la primera vez
que pongas las claves conviene probar con `jobbot apply <url>` antes de dejarlo
en el cron.

---

## Ajustar el criterio

Casi todo está en `config.yaml`:

- `salary.minimum` y `salary.target`, si cambias de idea sobre el suelo.
- `keywords.weighted`, para subir o bajar el peso de una tecnología.
- `exclude.off_profile_titles`, si se cuela algún tipo de puesto que no quieres.
- `scoring.notify_threshold`, si te llegan demasiadas o demasiado pocas.
- `sources.<nombre>.queries`, para darle a un portal frágil menos búsquedas.

Y en `profile/cv.yaml` está lo que ve Claude al escribir: el summary actual, la
experiencia con sus highlights, y `emphasis_rules`, que decide qué empresa sale
en primer plano según lo que pida la oferta. Si actualizas el CV en docx,
actualiza también ese fichero.
