# Proyecto 3 — sentinel-memory

**Documento de aprendizaje pedagógico** — para leerlo despacio y entender qué se construyó, por qué, y qué significa cada palabra nueva.

> Si en algún momento aparece un término que no conoces, busca el **Glosario** al final. Está hecho para que vuelvas a él tantas veces como necesites.

---

## 0. Para qué sirve este documento

Este es el "manual del autor" del Proyecto 3 — el documento que **yo (Cristian) leo** para entender lo que se hizo y poder explicarlo en una entrevista, en LinkedIn, o a alguien del equipo.

Está escrito para que se entienda **sin necesitar conocimiento previo** de agentes IA, embeddings, vectores, ni bases de datos vectoriales. Cada concepto se introduce con una analogía simple antes de mostrar cómo se aplicó.

Si lo lees de principio a fin tardas **45 minutos a 1 hora**. Si lo usas como referencia, te puedes saltar directamente a la sección que te interese.

---

## 1. ¿Qué construimos? — versión de un minuto

Construimos un **sistema de memoria** para un agente de IA que ayuda a un analista de seguridad.

Cuando el analista escribe algo como *"estoy viendo 47 logins fallidos desde una sola IP, ¿qué hago?"*, el sistema:

1. **Entiende qué significa la pregunta** (no solo qué palabras tiene).
2. **Recuerda conversaciones anteriores** del mismo analista en la misma sesión.
3. **Recuerda preferencias del analista** ("a este le importan solo las alertas críticas").
4. **Busca en una biblioteca de procedimientos (playbooks)** el más parecido.
5. **Busca incidentes pasados parecidos** ya resueltos.
6. **Le pasa todo eso a Claude (un LLM)** para que responda con contexto rico.
7. **Guarda la conversación** para futuras consultas.
8. **Registra todo en un log inmutable** que ni un administrador puede modificar.
9. **Acepta retroalimentación** ("este playbook era irrelevante") y **aprende de ella sin reentrenar ningún modelo**.

Todo esto sobre **un solo motor de base de datos**: PostgreSQL 16 con la extensión pgvector. Sin Pinecone, sin Redis, sin Kafka, sin TiDB.

Y tiene una **interfaz web minimalista** para que el analista no tenga que usar `curl`.

---

## 2. Conceptos nuevos — explicados como si fuera la primera vez

Antes de entrar a los detalles del proyecto, conviene fijar bien estos conceptos. Léelos en orden — cada uno depende del anterior.

### 2.1 ¿Qué es un *agente* IA? (y por qué no es un chatbot)

Un **chatbot** responde una pregunta y olvida. Le preguntas dos cosas seguidas y trata cada una como si fuera la primera.

Un **agente** hace tres cosas más:

1. **Recuerda** — sabe lo que dijimos hace 5 turnos en la misma conversación.
2. **Consulta herramientas** — antes de responder puede buscar en bases de datos, llamar APIs, leer archivos.
3. **Se adapta** — sus respuestas cambian según el usuario, sus preferencias, su historia.

Un agente sin memoria es solo un chatbot caro. Por eso este proyecto se llama **sentinel-memory**: la memoria *es* el agente.

### 2.2 ¿Qué es un *LLM*?

LLM = *Large Language Model* (Modelo de Lenguaje Grande).

Es un modelo de IA entrenado con cantidades enormes de texto que aprende a **predecir la siguiente palabra**. Esa habilidad simple, cuando se entrena a esa escala, produce un sistema capaz de escribir, resumir, traducir y razonar de forma sorprendentemente buena.

Ejemplos: **Claude** (Anthropic), GPT-4 (OpenAI), Gemini (Google), Llama (Meta).

En este proyecto usamos **Claude Haiku 4.5**, que es el modelo más barato y rápido de Anthropic ($1 por millón de tokens de entrada). Para nuestro caso —contestar a un analista con 3-4 párrafos basados en contexto— es más que suficiente.

### 2.3 ¿Qué es un *embedding*?

Un **embedding** es **un vector** (una lista de números) que representa el *significado* de un texto.

Imagina que cada texto se proyecta sobre un mapa de 384 dimensiones (sí, 384 — los humanos solo manejamos 3). En ese mapa, textos con significados parecidos terminan **cerca** unos de otros, y textos con significados distintos terminan **lejos**.

Ejemplo:
- `"alguien intentando entrar al SSH con contraseñas malas"` → embedding A
- `"brute force login attempt against ssh"` → embedding B
- `"receta de pan casero"` → embedding C

En el mapa, A y B están muy cerca (significan casi lo mismo aunque las palabras sean diferentes y estén en otro idioma). C está lejísimos.

Quien convierte el texto en embedding es un **modelo de embeddings**. En este proyecto usamos `sentence-transformers/all-MiniLM-L6-v2`, un modelo pequeño (90 MB) que corre en CPU.

> 🧠 **Analogía**: piensa en cada texto como un punto en un mapa. Dos textos que dicen cosas parecidas terminan en barrios cercanos, aunque usen vocabulario diferente.

### 2.4 ¿Qué es *similitud por coseno*? (y por qué no euclidiana)

Si dos embeddings son vectores (puntos en el espacio), ¿cómo medimos qué tan parecidos son?

La opción intuitiva sería **distancia euclidiana** — la línea recta entre los dos puntos. Pero hay una mejor: **similitud por coseno**.

- Se mide el **ángulo** entre los dos vectores (no la distancia entre los puntos).
- Si los dos vectores apuntan en la **misma dirección** → ángulo cero → similitud máxima.
- Si apuntan en direcciones **opuestas** → ángulo 180° → similitud mínima.

¿Por qué se prefiere coseno para embeddings? Porque el **tamaño** del vector suele depender de detalles irrelevantes (qué tan largo es el texto, por ejemplo), pero la **dirección** captura el significado. Coseno ignora el tamaño y solo mira la dirección.

En pgvector, el operador `<=>` calcula la *distancia* del coseno (que es `1 - similitud_coseno`). Cuanto más pequeño, más parecidos son los textos.

```sql
SELECT embedding <=> '[0.1, 0.2, ...]'::vector AS distance
FROM alerts ORDER BY distance LIMIT 5;
```

Eso es básicamente todo el truco del proyecto.

### 2.5 ¿Qué es *RAG*?

RAG = *Retrieval-Augmented Generation* (Generación Aumentada por Recuperación).

Es una técnica que mezcla dos cosas:

1. **Recuperación**: cuando llega una pregunta, primero buscamos los documentos más relevantes en una biblioteca propia (en nuestro caso, los playbooks).
2. **Generación**: le pasamos esos documentos al LLM como contexto, y el LLM responde basándose en ellos.

¿Por qué es importante?

- **Los LLM no saben de tu empresa**. Claude no conoce tus playbooks. Pero si se los pasas en el prompt, los puede usar.
- **Reduce alucinaciones**. Sin RAG, el LLM se inventa cosas que suenan bien. Con RAG, basa la respuesta en información real.
- **Es actualizable sin reentrenar**. Cambias los playbooks, y el sistema responde con el nuevo contenido la próxima vez.

En este proyecto, RAG vive en el endpoint `/search/playbooks` y en la primera parte de `/chat`.

### 2.6 ¿Qué es *memoria episódica*?

Cuando hablamos con alguien, recordamos lo que se dijo **en esta conversación**. Si después de "tengo 47 logins fallidos desde una IP" pregunto "¿y si las IPs rotan?", el otro entiende que "las IPs" se refiere al ataque del turno anterior.

Eso es **memoria episódica**: el agente almacena cada turno (`user` o `assistant`) en una tabla y, en cada turno nuevo, le pasa al LLM los últimos N turnos para que reconstruya el contexto.

En este proyecto vive en la tabla `episodic_memory` y en el archivo `app/memory/episodic.py`.

### 2.7 ¿Qué es *LTM* (Long-Term Memory)?

Memoria episódica = lo que se dijo **en esta sesión**.

LTM = preferencias y atributos del usuario **que persisten entre sesiones**.

Ejemplos:
- `cristian` → `severity_filter` → `["high", "critical"]` (solo le interesan estas severidades)
- `cristian` → `timezone` → `"America/Bogota"`
- `cristian` → `role` → `"senior_analyst"`

Lo interesante: estas preferencias **se aplican automáticamente** en cada búsqueda. Si Cristian pone `severity_filter` a `["critical"]`, la próxima búsqueda solo le devolverá alertas críticas — sin que él tenga que pasar ese filtro en cada llamada.

LTM es **política declarativa**: cambias datos, cambia el comportamiento. Sin redeploy. Vive en la tabla `ltm` y en `app/memory/ltm.py`.

### 2.8 ¿Qué es *SCD2* (Slowly Changing Dimension Type 2)?

Imagina que una alerta empezó marcada `severity = "high"` y dos horas después la marcamos como `"critical"`. Si la próxima semana alguien pregunta *"¿con qué severidad estaba esta alerta cuando tomamos la decisión X?"*, necesitamos saber el estado **en ese momento**, no el actual.

**SCD2** = guardar **una fila nueva por cada cambio**, con dos timestamps:
- `valid_from` — desde cuándo es válida esta versión
- `valid_to` — hasta cuándo fue válida (o `NULL` si es la actual)

Esto da una **línea de tiempo** completa de cada alerta. Y permite preguntas como *"dame el estado de la alerta X en el instante T"* — algo que llamamos *"time travel"* o *"AS OF query"*.

En este proyecto vive en la tabla `alerts_history` y se mantiene automáticamente con un **trigger** (ver siguiente concepto).

### 2.9 ¿Qué es un *trigger* de base de datos?

Un **trigger** es código (escrito en PL/pgSQL en nuestro caso) que la base de datos ejecuta **automáticamente** cuando ocurre un evento (INSERT, UPDATE, DELETE) en una tabla.

Ejemplos del proyecto:
- **`alerts_capture_change`**: cada vez que se hace UPDATE a una fila de `alerts`, copia la versión vieja a `alerts_history` antes de sobrescribirla. **Así implementamos SCD2 sin que la app tenga que recordar hacerlo**.
- **`alerts_notify_insert`**: cada vez que se inserta una alerta nueva, emite un evento `NOTIFY` que el worker está escuchando. **Así implementamos CDC sin que la app tenga que avisar al worker**.
- **`audit_log_block_modify`**: si alguien intenta hacer UPDATE o DELETE sobre `audit_log`, lanza una excepción. **Así el log es inmutable a nivel motor — ni la app puede borrarlo**.

> 🧠 **Idea importante**: cuando una regla **debe** cumplirse pase lo que pase, ponerla en un trigger es más fuerte que ponerla en la app. La app puede tener bugs; el trigger no se puede saltar.

### 2.10 ¿Qué es *CDC* (Change Data Capture)?

CDC = capturar cambios en una base de datos y **propagarlos** a otros sistemas en tiempo real.

El uso típico: cuando se inserta una fila nueva en `alerts`, el worker necesita calcular su embedding. Hay dos formas:

1. **Polling**: el worker consulta cada N segundos *"¿hay alguna alerta sin embedding?"*. Funciona pero es lento y desperdicia consultas.
2. **Push**: la DB **avisa** al worker apenas hay un cambio, y el worker reacciona.

Postgres tiene un sistema de pub/sub nativo: `pg_notify('canal', 'payload')`. Cualquier sesión que esté ejecutando `LISTEN canal` recibe el mensaje en menos de 5ms.

En este proyecto:
- Un trigger en `alerts` emite `NOTIFY alerts_changed` cuando hay una fila sin embedding.
- El worker (`workers/embedding_worker.py`) escucha ese canal y embeb e las alertas a medida que llegan.

**Es CDC real, sin Kafka, sin Debezium, sin Connect.** Todo dentro del mismo motor.

### 2.11 ¿Qué es un *audit log* inmutable?

Un registro de **todo lo que pasó** en el sistema: qué analista consultó qué, cuándo, con qué resultado, cuánto tardó.

Es **inmutable** porque tiene triggers que bloquean UPDATE y DELETE. Solo se permite INSERT. Eso lo hace válido para compliance (SOC 2, ISO 27001).

En este proyecto vive en la tabla `audit_log` y se invoca desde `app/governance/audit.py`.

### 2.12 ¿Qué es *RBAC*?

RBAC = *Role-Based Access Control*. Asignas **roles** a los usuarios (`analyst`, `senior_analyst`, `auditor`) y **permisos** a los roles (`chat`, `search`, `read_audit`).

Cuando llega una petición, el sistema:
1. Lee el `X-Analyst-Id` del header.
2. Busca el rol del analista en LTM.
3. Mira si ese rol tiene permiso para la operación que se pidió.
4. Si no, responde 403 Forbidden.

Lo elegante: el rol vive en **datos** (LTM), no en código. "Subir a un analista a senior por una guardia de fin de semana" es un `UPDATE` de una fila.

En este proyecto vive en `app/governance/rbac.py`.

### 2.13 ¿Qué es un *living index*?

Un índice tradicional es **estático**: ordena los resultados según una fórmula fija (en nuestro caso, distancia coseno).

Un **living index** mezcla la fórmula estática con **retroalimentación humana**:

```
final_score = distancia_coseno - (rating_promedio * peso)
```

Si los analistas votan +1 sobre un playbook, ese playbook empieza a aparecer arriba en búsquedas similares. Si lo votan -1, baja.

**El sistema "aprende" del juicio humano sin reentrenar ningún modelo.** Solo SQL.

En este proyecto vive en la tabla `feedback`, la vista `feedback_scores`, y la fórmula está en `app/memory/retrieval.py`.

---

## 3. La arquitectura, vista desde arriba

El sistema tiene **tres servicios** que corren juntos con `docker compose up`:

```
┌──────────────────────────────────────────────────────────────────┐
│                       sentinel-memory                            │
│                                                                  │
│  ┌─────────────┐  ┌────────────────┐  ┌─────────────────────┐   │
│  │ Memory API  │  │  Embedding     │  │   Memory layer      │   │
│  │  (FastAPI)  │  │  worker (CDC)  │  │ (Postgres+pgvector) │   │
│  │             │  │                │  │                     │   │
│  │ + UI /ui/   │  │  LISTEN/NOTIFY │  │  5 tablas + 4 triggers │
│  └──────┬──────┘  └────────┬───────┘  └──────────▲──────────┘   │
│         │                  │                     │              │
│         └──────────────────┴─────────────────────┘              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
       │                                              ▲
       │ HTTP                                         │ Claude API
       ▼                                              │
   Analista                                       Anthropic
```

**Características clave de este diseño:**

1. **API y worker comparten la misma imagen Docker** (`sentinel-api:v5`). Solo cambia el comando. Reduce mantenimiento.
2. **Los tres servicios viven en una red privada de Docker** — solo el puerto 8000 está expuesto al host.
3. **El motor de DB es uno solo**. Toda la "magia" (audit, RBAC, history, vectores) está en Postgres.

---

## 4. Las cinco tablas

| Tabla | Patrón que implementa | Filas típicas |
|---|---|---|
| `playbook_chunks` | RAG (corpus de remediación) | ~50 |
| `alerts` | Join semántico-transaccional | ~10k al año |
| `episodic_memory` | Memoria de conversación | crece con uso |
| `ltm` | Preferencias persistentes | ~10 por analista |
| `audit_log` | Trazabilidad inmutable | una por operación |

Más dos tablas/vistas auxiliares:

| Objeto | Para qué |
|---|---|
| `alerts_history` | SCD2 — versiones anteriores de cada alerta |
| `feedback` | Ratings -1/0/+1 de los analistas |
| `feedback_scores` (view) | Agregación: avg_rating + n_ratings por target |

**Una tabla = un patrón del libro.** Esa correspondencia 1:1 es deliberada — hace que el diseño sea explicable en una sola hoja.

---

## 5. Recorrido por Actos

El proyecto se construyó en **seis actos**, cada uno con un patrón claro. Si pasas por la historia de commits, los actos están marcados en los mensajes.

### Acto 0 — Fundación

- Estructura del repo, `docker-compose.yml` con solo Postgres.
- `db-init/01_extensions.sql` activa `vector` y `pgcrypto`.
- `db-init/02_schema.sql` crea las 5 tablas (todas vacías).
- `db-init/03_seed.sql` inserta 5 playbooks + 5 alertas (sin embeddings todavía).
- `docs/adr/001-postgres-pgvector-vs-tidb.md` documenta **por qué Postgres y no TiDB**.

**Lo importante**: el ADR existe **antes** del código. Esa es la diferencia entre un Data Engineer y un Data Architect.

### Acto 1 — Embeddings

- Se añade el modelo `sentence-transformers/all-MiniLM-L6-v2` al `Dockerfile`.
- Se crea `scripts/embed_seed.py` para calcular embeddings de los playbooks y alertas iniciales.
- Verificamos con `SELECT` directo que los embeddings se guardaron.

### Acto 2 — RAG + Join semántico-transaccional

- Se crea el servicio `api` en `docker-compose.yml`.
- Se crean los endpoints:
  - `GET /health`
  - `POST /search/playbooks` — RAG puro
  - `POST /search/similar-incidents` — el join semántico-transaccional

**La query estrella** (la que justifica todo el proyecto):

```sql
SELECT alert_id, severity, raw_text,
       embedding <=> $1::vector AS distance
FROM alerts
WHERE embedding IS NOT NULL
  AND severity = ANY($2::text[])     -- filtro SQL
  AND detected_at >= $3              -- filtro SQL
ORDER BY embedding <=> $1::vector    -- ordenamiento vectorial
LIMIT $4;
```

En un stack separado (Postgres para datos + Pinecone para vectores), esto requiere:
1. Llamada a Pinecone → IDs por similitud.
2. Llamada a Postgres con esos IDs + filtros → algunos sobreviven.
3. Reordenar en cliente.

Aquí, **una sola query atómica**. Sin round-trips. Sin pérdida de precisión.

### Acto 3 — Memoria episódica + LTM + chat con contexto

- Se crea `app/memory/episodic.py` (grabar y recuperar turnos).
- Se crea `app/memory/ltm.py` (leer y actualizar preferencias).
- Se crea `app/llm/claude.py` (wrapper a la API de Anthropic).
- Se reescribe el endpoint `POST /chat`:
  1. Lee preferencias del analista (LTM).
  2. Embebe el mensaje.
  3. Busca playbooks parecidos (RAG).
  4. Busca alertas parecidas (join semántico-transaccional, aplicando el `severity_filter` de LTM).
  5. Recupera los últimos N turnos de la sesión (episodic).
  6. Construye un **system prompt** con todo el contexto.
  7. Llama a Claude.
  8. Guarda el turno del usuario y el del agente en `episodic_memory`.
  9. Devuelve la respuesta + las citaciones.

**Lo que demuestra**: el agente recuerda. Le dices "y si las IPs rotan" en el turno 2 sin mencionar "brute force", y entiende perfectamente.

### Acto 4 — Consistencia temporal + CDC real

- Se crea `db-init/04_temporal_and_cdc.sql`:
  - Tabla `alerts_history` (SCD2).
  - Trigger `alerts_capture_change` — copia OLD a history en cada UPDATE.
  - Trigger `alerts_notify_insert` — emite `NOTIFY alerts_changed` en INSERT.
  - Trigger `alerts_notify_update` — emite `NOTIFY` también si el `raw_text` cambia.
  - Trigger `alerts_invalidate_embedding` — pone `embedding = NULL` si el texto cambió.

- Se crea `workers/embedding_worker.py`:
  - Hace `LISTEN alerts_changed`.
  - Bloquea esperando eventos con `select.select()`.
  - Cuando llega un NOTIFY, calcula el embedding y lo guarda.
  - Al arrancar, hace un *backfill* de todas las alertas con `embedding IS NULL`.

- Se añaden los endpoints:
  - `POST /alerts` — crear alerta.
  - `PATCH /alerts/{id}` — modificar (dispara SCD2).
  - `GET /alerts/{id}/history` — ver todas las versiones.
  - `GET /alerts/{id}/as-of?at=T` — estado en un instante.

**Lo que demuestra**: forense reproducible + CDC nativa, sin Kafka.

### Acto 5 — Gobernanza embebida

- Se crea `db-init/05_governance.sql`:
  - Tabla `feedback` (ratings).
  - Vista `feedback_scores` (agregación).
  - Inserta dos roles iniciales: `cristian → senior_analyst`, `audit_bot → auditor`.

- Se crea `app/governance/audit.py` (helper para loggear).
- Se crea `app/governance/rbac.py` (dependency de FastAPI que rechaza con 403 si no hay permiso).

- Se modifica `app/memory/retrieval.py` para incluir el feedback en el ranking:
  ```python
  final_score = distance - 0.2 * avg_rating
  ```

- Se añaden los endpoints:
  - `POST /feedback` — analista valora una recomendación.
  - `GET /audit` — leer el audit log (solo auditor o senior).

- Se aplica `Depends(rbac.require_permission(...))` a `chat`, `search/*`, `alerts` (POST/PATCH), `feedback`, `audit`.

**Lo que demuestra**: el sistema aprende del juicio humano sin reentrenar, todo queda registrado, y el rol determina lo que cada quien puede hacer.

### Acto 6 — UI minimalista + documentación de cierre

- Se crea la carpeta `web/` con `index.html`, `styles.css`, `app.js` — UI dark, sin framework, vanilla JS.
- Se monta como static files en FastAPI: `app.mount("/ui", StaticFiles(...))`.
- Se crean `README.md` narrativo, `DEMO.md`, `docs/marketing/linkedin-carousel.md` (en inglés).
- Se escribe **este documento** (en español, para mí).

La UI tiene **cinco pestañas**:

1. **Chat** — hilo de conversación con citaciones y botones ▲▼ que graban feedback en vivo.
2. **Search** — búsqueda lado a lado: playbooks (RAG) + alertas (semántico + filtros SQL).
3. **Alerts** — lista de alertas; clic muestra la línea de tiempo SCD2.
4. **Audit log** — tabla con los últimos 50 eventos.
5. **Preferences** — leer y actualizar LTM (cambia el comportamiento del retrieval sin redeploy).

---

## 6. La query estrella, línea por línea

Esta es **la query** que justifica todo el proyecto. Vale la pena leerla con calma.

```sql
SELECT
    alert_id,
    severity,
    raw_text,
    embedding <=> $1::vector              AS distance,         -- ① ranking semántico
    COALESCE(fs.avg_rating, 0)::real      AS feedback_score,   -- ② living index
    (embedding <=> $1::vector)
      - (COALESCE(fs.avg_rating, 0) * 0.2) AS final_score      -- ③ híbrido
FROM alerts a
LEFT JOIN feedback_scores fs
  ON fs.target_kind = 'alert' AND fs.target_id = a.alert_id    -- ④ acumula feedback
WHERE embedding IS NOT NULL
  AND severity = ANY($2::text[])                               -- ⑤ filtro de LTM
  AND detected_at >= $3                                        -- ⑥ filtro temporal
ORDER BY final_score                                           -- ⑦ orden final
LIMIT $4;
```

**Línea por línea:**

- **①** Calcula la distancia coseno entre el embedding de la alerta y el embedding de la consulta del analista. Cuanto más cerca de 0, más parecida.
- **②** Saca el rating promedio del feedback acumulado. Si no hay feedback, vale 0.
- **③** Combina los dos: la distancia "pura" menos un bonus por buen feedback. El 0.2 es el "peso" del feedback — más alto = el feedback influye más; más bajo = casi no afecta.
- **④** Junta cada alerta con sus métricas de feedback (si las tiene).
- **⑤** Aplica el filtro de severidades que vino de la LTM del analista (sin que él lo pidiera explícitamente).
- **⑥** Filtra por ventana temporal.
- **⑦** Ordena por el score combinado, ascendente (los mejores primero).

**Qué es lo brillante:**

- **Atomicidad**: todo ocurre en una transacción.
- **Atomicidad de datos**: los datos no pueden cambiar entre los pasos.
- **Un solo plan de ejecución**: Postgres puede optimizar globalmente, no en piezas.
- **Sin código de orquestación**: no hay que "juntar" resultados de dos servicios en cliente.

Esto es exactamente lo que el libro pinta como el patrón estrella del Cap 3.

---

## 7. Cómo correr el proyecto, paso a paso

Lo que sigue es la receta completa. Si lo haces de cero en una máquina nueva, deberías tardar menos de 5 minutos.

### 7.1 Pre-requisitos

- Docker Desktop instalado (o Docker Engine + Compose).
- Una cuenta en Anthropic con un `ANTHROPIC_API_KEY`.

### 7.2 Clonar y configurar

```bash
git clone https://github.com/CristianCaro-portfolio/sentinel-memory.git
cd sentinel-memory
cp .env.example .env
# editar .env y poner tu ANTHROPIC_API_KEY real
```

### 7.3 Arrancar el stack

```bash
docker compose up -d --build
```

Esto:
- Construye la imagen `sentinel-api:v5` (incluye el modelo de embeddings pre-descargado).
- Levanta Postgres y ejecuta los 5 scripts SQL de inicialización **una sola vez** (la primera vez que el volumen está vacío).
- Levanta la API en el puerto 8000.
- Levanta el embedding worker.

### 7.4 Embebir los datos iniciales

```bash
docker compose exec api python scripts/embed_seed.py
```

Esto calcula los embeddings de los 5 playbooks y las 5 alertas del seed. Si ya están embedidos (porque ya lo corriste antes), no hace nada.

### 7.5 Abrir la UI

```bash
open http://localhost:8000/ui/
```

Deberías ver el dashboard. El identificador por defecto es `cristian`, que tiene rol `senior_analyst`.

### 7.6 Probar las cinco pestañas

- **chat** → escribe *"alguien atacando mi SSH con contraseñas malas, qué hago?"* → mira la respuesta y los botones ▲▼ junto a las citaciones.
- **search** → en playbooks escribe *"SSH brute force"*; en alertas activa el filtro `critical`.
- **alerts** → haz clic en una alerta para ver su timeline; usa "+ new alert" para crear una y observa cómo el worker la embebe en segundos.
- **audit log** → "↻ refresh" para ver las últimas 50 entradas.
- **preferences** → cambia `severity_filter` a `["critical"]` y repite el chat.

### 7.7 Apagar (sin perder datos)

```bash
docker compose down
```

### 7.8 Apagar (borrando todo)

```bash
docker compose down -v
```

El `-v` también borra el volumen → la próxima vez los datos se inicializan de nuevo.

---

## 8. Aprendizajes que un arquitecto se lleva

1. **Sustrato unificado > stack fragmentado** (al menos a este scope). Un solo motor para SQL + vectores + audit + history reduce latencia, complejidad operativa y superficie de inconsistencia.
2. **Una tabla, un patrón**. La correspondencia 1:1 entre tablas y patrones del libro hace el diseño explicable en una hoja.
3. **Gobernanza en la DB, no en la app**. Triggers de inmutabilidad, SCD2, NOTIFY. La app no puede saltarse esas reglas porque viven a nivel motor.
4. **LTM como política declarativa**. Cambias datos, cambia el comportamiento. Sin redeploy. Sin tocar código.
5. **Living index**. El feedback humano re-pondera sin reentrenar. Pura SQL.
6. **ADR primero, código después**. Antes de adoptar la tesis de un libro, evaluación formal por escrito de alternativas. Eso es lo que diferencia a un arquitecto.
7. **Imagen Docker compartida**. La API y el worker son dos consumidores legítimos de la misma capacidad. Una sola imagen, dos comandos.
8. **UI minimalista vale más que una compleja**. Vanilla HTML/CSS/JS, sin npm, sin framework. Se mantiene sola.

---

## 9. Conexión con el plan profesional

Este proyecto cierra la **Fase 1** del plan de aprendizaje de 34 semanas (modelado dimensional + Docker) y abre la **Fase 2** (dbt + Terraform).

| Fase | Cómo este proyecto la toca |
|---|---|
| 1 — Modelado dimensional + Docker | 5 tablas con propósito claro, SCD2, docker-compose con 3 servicios |
| 2 — dbt + Terraform | Preparado (Proyecto 4: dbt sobre `audit_log` + `feedback`) |
| 3 — Streaming | CDC con LISTEN/NOTIFY (Proyecto 5: Kafka real es la extensión) |
| 4 — Governance + EA | ADR-001, audit inmutable, RBAC, living index, C4 diagram |
| 5 — Demo / pitch | Video + carrusel + .docx + README narrativo + UI navegable |

Un solo proyecto te da material para mostrar **las decisiones que un Data Architect toma** en cualquier entrevista. Ese era el objetivo.

---

## 10. Próximos pasos naturales

Si quisieras extender el proyecto:

- **Async**: cambiar `psycopg2` por `asyncpg` para concurrencia bajo carga.
- **Tool use de Claude**: en lugar de inyectar el contexto a la fuerza, dejar que Claude llame `/search/*` cuando lo necesita.
- **Métricas Prometheus** (latencia P50/P95/P99) + Grafana en compose.
- **Embeddings más potentes**: `bge-large` o `multilingual-e5` y comparar.
- **Tests con pytest** contra un fixture de Postgres.
- **CI/CD con GitHub Actions**: build + tests + push de la imagen.
- **Deploy a Cloud Run** con Neon o Supabase como Postgres gestionado.
- **dbt** sobre el audit log y el feedback para marts operativos (Proyecto 4 del plan).

---

## Glosario rápido

| Término | Una línea para recordarlo |
|---|---|
| **Agente IA** | Chatbot + memoria + capacidad de usar herramientas. |
| **LLM** | Modelo grande que predice la siguiente palabra. |
| **Embedding** | Vector de 384 números que representa el significado de un texto. |
| **Similitud por coseno** | Mide el ángulo entre dos vectores; ignora el tamaño. |
| **pgvector** | Extensión de Postgres que añade el tipo `vector` y el operador `<=>`. |
| **RAG** | Buscar primero, generar después — con tu propia data como contexto. |
| **Episodic memory** | Lo que se dijo *en esta sesión*. |
| **LTM** | Preferencias del usuario *que persisten entre sesiones*. |
| **Trigger** | Código que la DB ejecuta automáticamente ante INSERT/UPDATE/DELETE. |
| **SCD2** | Guardar una fila por cada cambio, con `valid_from`/`valid_to`. |
| **AS OF query** | Pregunta por el estado de algo *en un instante pasado*. |
| **CDC** | Capturar cambios de la DB y notificarlos a otros sistemas. |
| **LISTEN/NOTIFY** | El pub/sub nativo de Postgres. |
| **Audit log** | Registro inmutable de todo lo que pasó. |
| **RBAC** | Asignar permisos por roles, no por usuarios. |
| **Living index** | Ranking que se ajusta con feedback humano sin reentrenar. |
| **ADR** | Architecture Decision Record — decisión documentada por escrito. |
| **System prompt** | Las instrucciones que le das al LLM antes de la conversación. |
| **Token** | La unidad mínima que cobra/procesa un LLM (~ 4 caracteres). |
| **FastAPI** | Framework Python para construir APIs con tipos. |
| **Dependency injection** | Pasarle "ingredientes" pre-armados a una función. |
| **Static files** | Archivos servidos tal cual (HTML, CSS, JS) por el servidor. |

---

*— Fin del documento de aprendizaje —*
