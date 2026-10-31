---
name: bach
version: 3.10.0
type: skill
author: BACH Team
created: 2025-12-01
updated: 2026-10-25
anthropic_compatible: true

description: >
  Sistema de gestión central para BACH. Esta es la ÚNICA skill
  que necesita subirse a Claude. Conoce todas las skills locales,
  realiza comprobaciones de versión y carga versiones locales más nuevas cuando es necesario.
  Se activa automáticamente con cada uso de skill.
---

# COMO AGENTE TRABAJAR TAREAS ABIERTAS (Entrada para Claude, Codex, Kimi, Gemini)

> **Nuevo desde v3.10.0 (2026-10-25).** Si tu orden es "lee la SKILL.md y trabaja en tareas abiertas", esta sección se aplica primero. Todo lo demás en este archivo es referencia y solo se lee cuando se necesita.
> Versión detallada, copiable: `Desktop\OCEAN\EINWEISUNG-EXTERNE-WORKER.md` (OneDrive de Lukas, no en el repo). Contrato de lease: `docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md`, Clientes: `docs/architecture/TASKDB-SALT-LEASE-CLIENTS-v1.md`. Harness de worker local (Buddha): `docs/architecture/LOKALER-WORKER-HARNESS.md` (PR #520).

**Flujo en una frase:** arrancar → seleccionar tarea → **lease, luego trabajar** → worktree propio → tests → PR → entregar resultado → siguiente tarea. Sin orden de parada explícita de Lukas, no te detienes.

### 1. Arranque y modo
- Acceso al Mac Studio a través del SSH proporcionado; no configures tus propias credenciales. Proyecto bajo `$BACH_ROOT` (en el Mac Studio `~/services/bach`), Python de su venv. Lee `AGENTS.md` e instrucciones del subproyecto en el que trabajas.
- **Modo B (Mixto)** es para agentes que colaboran activamente; el caso normal. **Modo A (Biblioteca)** basta si solo trabajas en tareas y no usas BACH como sesión: el método lease abajo corre vía el servicio lead y no requiere inicio de sesión. Modo C (Sesión) solo bajo petición expresa.
- Antes de la primera tarea, lee el plan actual `Desktop\OCEAN\AKTUELLER-PLAN.md` y `MODUL-ZUORDNUNG.md` (sitios de construcción).

### 2. Encontrar tareas libres
- **Nativo:** `TaskLeaseClient.task_candidates(limit=100, offset=…)` (leer todas las páginas, no solo la primera), luego `task_snapshot(task_id)` para la descripción completa. `bach task list` muestra las mismas tareas solo para vista.
- **Regla de selección:**
  1. Solo tareas cuyas dependencias están satisfechas, sin lease activo externo, y para las que tus herramientas bastan.
  2. **Prioridad más alta primero** (P0 antes P1 antes P2). Si misma prioridad, primero lo que encaja en prioridades de agenda (actual 25.10.2026: planificador de proyectos, plantillas/control de agentes, Running & Living, rediseño GUI, fiabilidad workers; decisivo es `AKTUELLER-PLAN.md`).
  3. **Sin tareas OLLAMA.** Es la cola de fondo de workers locales (Buddha, Ollama Cloud, OpenRouter). También tareas para `USER`/`HUMAN`/`LUKAS` y tareas reservadas externamente se quedan. `BACH` significa editable conjuntamente. No inventes obligaciones de slot adicionales.
  4. Tareas de revisión y test de otros autores son explícitamente adecuadas.
  5. Si una tarea depende de una decisión de usuario abierta o no encaja en tus capacidades: pregunta o anota en nota de tarea y toma la siguiente. Nunca cambies reglas o gates de protección solo para poder tomar una tarea.

### 3. Tomar control antes de trabajar
```python
import os, sys
os.environ["BACH_NO_AUTO_MIGRATE"] = "1"
sys.path.insert(0, os.path.join(os.environ["BACH_ROOT"], "system"))
from hub._services.task_lease_client import TaskLeaseClient
# BACH_ROOT y BACH_DEVICE_TOKEN los proporciona el acceso; nunca saques el token
client = TaskLeaseClient(lead_url="http://127.0.0.1:8000", timeout=35)  # lee BACH_DEVICE_TOKEN
snap = client.task_snapshot(task_id)                      # descripción completa y versión de tarea
ack = client.acquire(task_id, worker_id="<agent>@<host>", host="<host>", ttl_profile="S")
# nueva request_id se genera; la versión de tarea del snapshot puede pasarse como task_version=…
# ack.lease_id, ack.fence, ack.task_version: guardar para esta ejecución, nunca en informes
client.renew(task_id, lease_id=ack.lease_id, fence=ack.fence)   # a tiempo, también en trabajos largos
```
- Worker ID **`<agent>@<host>`**, request ID propia y generación, nunca compartas con otro worker. Empieza solo tras aceptación confirmada.
- Rechaza `renew` si lease expirado o fence cambiado: **para todas las operaciones de escritura para esta tarea.** Tras cambios de contenido confirmados, actualiza versión de tarea guardada.
- **No usar:** `bach task claim` (claim antiguo sin fence/lease-id) y `~/compute/luna-gui/task_tool.py claim` (solo pone `assigned_to`, sin lease). Ambos no son toma de control nativa y no protegen contra trabajo duplicado. `task_tool.py note` (añadir texto a descripción) y `list` sirven de apaño hasta que exista contrapartida nativa.
- Firmas vinculantes leer de `system/hub/_services/task_lease_client.py`, no de este ejemplo.

### 4. Trabajar
- **Worktree propio por tarea** desde `origin/main`: `git worktree add ~/services/bach-worktrees/<rama> -b <rama> origin/main`. Nombre de rama `<agent>/<task>-<corto>-<fecha>`. Checkout principal `~/services/bach` está ocupado (cambios sin commitear externos): no se trabaja, mide ni construye ahí.
- **Sitio de construcción:** nueva lógica de dominio va en el repo de módulo Ocean apropiado según `MODUL-ZUORDNUNG.md`, no en el núcleo BACH.
- Verifica resultado contra criterios de aceptación de la tarea. Ejecuta tests de áreas cambiadas y solo afirma lo que puedas probar. Textos de usuario final en alemán con umlauts reales.
- Antes del commit: secrets-scan, leer diff, solo commitear archivos propios (no commit colectivo).
- Pushea rama, **crea PR contra `main`** y anota en tarea. Commit, push, PR, merge, deploy y aceptación de dominio individualmente reportados. Una rama no es un estado entregado aún.

### 5. Entregar
- **Hecho:** `client.submit_result(task_id, lease_id=…, fence=…, task_version=…, generation="<nueva-generación>", result="<texto>")`. `result` es texto concreto con **máx 3000 caracteres** (criterios alcanzados, cambios, link PR, commit SHA, resultados de test reales, límites); un mensaje puro de finalización ("done") se rechaza. El submit pone la tarea en `review` y libera el lease. Después `task_result_snapshot(task_id)` leer y comprobar result-id/hash; solo texto de chat no es entrega.
- **Parcial o bloqueo:** Pushea rama WIP, luego `client.release(task_id, lease_id=…, fence=…, outcome="return" | "blocked", note="<rama, sha, siguiente paso>")`. No `done` global, no lease prolongado artificialmente mientras esperas humanos. (`complete=false` solo en harness de herramienta Buda local, ver doc Harness, no en SDK.)
- Después **inmediatamente la siguiente tarea** (paso 2). Si ahora no hay ninguna asumible: reportar razones ocupadas, esperar breve, volver a comprobar. No termines tu encargo tú mismo.
- Informe breve por tarea: Task-ID, trabajo, evidencias, commit/remote SHA, PR, estado task/result/lease leído. Revisión de trabajo propio marcar como no independiente.

### 6. Límites (siempre válidos)
- **No mergear**, no pushear a `main`, no desplegar, no reiniciar servicios, no cambiar config de worker, no parar jobs/workers externos, no iniciar corrida `.SYNC`. Merge vía segunda revisión, deploy tras aceptación.
- **`bach.db` nunca describir directamente**, no cambios SQL propios, no base de datos copiada como autoridad. Siempre API/SDK nativa.
- **Sin locks en `OneDrive\.TOPICS` o `.TOPICS\.AI`:** paran en el Mac el worker de fondo Buddha y cualquier rollout. Locks solo para ruta de worktree propia.
- Leases activos externos, trabajo en curso de otros agentes y rutas bloqueadas siguen protegidos. Tokens y credenciales de acceso nunca sacar ni commitear.

### 7. Gaps conocidos (estado 25.10.2026)
- **Aún no hay comando corto nativo** `bach task take|renew|submit|return|block`; está planeado (`ANFORDERUNGEN-DETAIL.md`, sección "Sistema de tareas, leases y locks"). El camino nativo permanente hoy es Python SDK `TaskLeaseClient` (arriba); `bach_api.task` ofrece solo `lease_acquire`/`lease_read`/`lease_renew`/`lease_release`/`lease_decompose` sin lista de candidatos y sin `submit_result`.
- `task_tool.py` está fuera del repo (`~/compute/luna-gui/`); su `list` lee `bach.db` directamente (solo lectura) y su `claim` no es lease.
- Instrucción, plan y `MODUL-ZUORDNUNG.md` están en OneDrive Desktop de Lukas, no en repo; un agente corriendo en el Mac no los alcanza sin copia.
- Contrato de origen para resultados externos: #2339 aceptado nativamente, Main-merge y release pendientes (PR #507). Resultados hasta entonces honestamente como entregados o parciales.

> **Nota de estado para el resto del archivo:** Todo lo debajo de esta sección se actualizó por contenido por última vez el 2026-03-12 (v3.8.0). Números (handlers, tablas, hooks, temas), vista de arquitectura v2.6 y planificación de tareas (5) **no se han re-medido** desde entonces; en caso de conflicto prevalece el código o la medición. La toma de control de tareas ya no corre vía `bach task claim` sino como se describe arriba.

---

# AVISO DE VERSION

# Comprobar si existe una versión más nueva de esta skill (local o central)

# SIEMPRE usar la versión con el número de versión más alto

# Comprobación de versión: bach skills version bach

# Bienvenido a Bach

---

## REGLAS - DIRECTRICES - ESTANDARES

---

### SIEMPRE (antes que nada)

**(1) COMPROBACIÓN DE VERSIÓN:** Si hay varias versiones de este SKILL.md disponibles (local, central), comparar números de versión y cambiar a la más nueva si es necesario, luego seguir leyendo ahí.
```bash
bach skills version bach   # Comprueba si existe versión más nueva
```

**(2) COMPROBACIÓN DE SISTEMA OPERATIVO:** Detectar si trabajas en Windows, Mac o Linux.
- Windows: No `/dev/null` Y no `NUL:`. En su lugar, omitir salida o usar `2>&1`. Evitar `&&`, ejecutar comandos individualmente
- Para archivos nul: `python tools/c_nul_cleaner.py --dir <ruta> --delete`

---

### LUEGO: Determinar tipo de acceso / modo de sesión

Elige el modo que encaja en tu situación:

| Modo | Cuándo | Startup | Acceso |
|------|--------|---------|--------|
| **A) Biblioteca** | Invitado, solo lectura, consultas individuales, BACH como herramienta | Sin startup | `from bach_api import task; task.list()` |
| **B) Mixto** | Solicitado por usuario para iniciar BACH, colaboración activa | API Startup | `session.startup()` + API + `session.shutdown()` |
| **C) Sesión** | Clásico, inicio automático, protocolo detallado | CLI Startup | `python bach.py --startup --partner=claude` |

- Modo C puede cambiar a B en cualquier momento (usar API en vez de CLI)
- Modos B y C pueden cambiar a A en cualquier momento (consulta única sin sesión)
- En duda: **Modo B** (recomendado para sesiones LLM)

---

### EN MODO B y C: Reglas para uso activo

**(1) Leer y Escribir -- Usar BACH significa co-desarrollar BACH:**

Quien usa BACH co-desarrolla BACH. Cada acceso es una oportunidad para mejorar el sistema.

- **(a) Handler First:** Cada función pertenece como Handler en `hub/`. Un Handler es automáticamente accesible vía CLI **y** API. Sin código separado para distintos caminos de acceso.
- **(b) Rellenar huecos:** Si faltan Handlers, módulos API, Skills, Tools, Workflows u otros componentes -- créalos. Handlers faltantes tienen la máxima prioridad; son la base para todos los caminos de acceso.
- **(c) Contribuciones propias bienvenidas:** Crear tus propias Skills, Workflows, Tools, MCPs es explícitamente bienvenido. Al modificar existentes, coordinar con el usuario.
- **(d) Fix-o-Task:** Los problemas llevan o a una corrección inmediata (pequeña) o a una tarea en la cola (grande). Factor decisivo: esfuerzo vs. beneficio. Luego volver a la tarea real.
- **(e) Self-Healing:** Si encuentras errores en BACH (rutas, comandos, referencias obsoletas, imports rotos), corrígelos inmediatamente e informa al usuario. BACH se repara a sí mismo a través de sus usuarios.
- **(f) Self-Extension:** ¡Si te falta una capacidad, dátela tú mismo! Usa `bach skills create` para scaffoldear nuevas tools, handlers, agents, experts o services. Tras `bach skills reload` están disponibles inmediatamente. Ver: `bach help self-extension`

**(2) Ejecutar el procedimiento de inicio** (ver abajo). Leer paquetes obligatorios y opcionalmente (`-->`) referencias voluntarias. Los paquetes llevan etiquetas de modo:
- `[C]` -> Leer solo en modo Sesión
- `[B]` -> Leer solo en modo Mixto, saltar en modo Sesión
- `[B/C]` -> Leer en ambos modos
- Sin etiqueta -> Leer siempre cuando se necesite

**(3) Leer paquetes adicionales cuando se necesiten** (paquetes de temas más abajo).

---

### EN MODO A: Reglas para uso invitado/herramienta

Leer paquetes adicionales cuando se necesiten. Sin startup necesario, sin shutdown esperado.

```python
from bach_api import task, memory, tools, steuer
task.list()         # Inmediatamente usable
tools.search("ocr") # Encontrar una tool
```

---

### Estructura del documento (Mapa de navegación)

```
SIEMPRE (antes que nada)
+-- (1) COMPROBACIÓN DE VERSIÓN
+-- (2) COMPROBACIÓN DE SISTEMA OPERATIVO

ACLARAR TIPO DE ACCESO
+-- A) Biblioteca       -> Invitado, solo lectura, herramienta
+-- B) Mixto            -> Guiado por usuario, API + Startup (recomendado)
+-- C) Sesión           -> Clásico, CLI + protocolo completo

EN MODO B y C
+-- (1) Lectura = Co-desarrollo
|   +-- (a) Handler First
|   +-- (b) Rellenar huecos
|   +-- (c) Contribuciones propias bienvenidas
|   +-- (d) Fix-o-Task
|   +-- (e) Self-Healing
+-- (2) Ejecutar procedimiento de inicio
|   +-- (1) Inicio              [B/C]
|   +-- (2) Conocimiento sistema   [B/C]
|   +-- (3) Memory              [B/C]
|   +-- (4) Capacidades         [B/C]
|   +-- (5) Planificación tareas [B/C]
|   +-- (6) Protocolos           [C]
+-- (3) Paquetes adicionales cuando se necesiten

EN MODO A
+-- Paquetes adicionales cuando se necesiten

PAQUETES DE TEMAS (todos los modos, cuando se necesiten)
+-- Trabajo en equipo
+-- Resolución de problemas
+-- Programación
+-- Mantenimiento
+-- Gestión de archivos
+-- Auto-extensión              [B/C]
+-- Apagado                     [B/C]

REFERENCIA
+-- Arquitectura de Skill
+-- Tres modos de acceso (módulos API, cuándo-qué-usar)
+-- Diagrama de arquitectura general
+-- Hooks & Inyectores
+-- Changelog
```

---

### Arquitectura de Skill v2.0 (NUEVA)

#### Principio de comprobación de versión

**SIEMPRE usar la versión más nueva** - independientemente de si está guardada local o centralmente:

```bash
bach skills version <name>    # Comprobar versiones
bach tools version <name>     # Comprobar versiones de tools
```

#### Estructura de Skill: Un Skill = Una Carpeta

Cada skill, agent, expert es **completamente autónomo** en su propia carpeta:

```
agents/entwickler/
+-- SKILL.md              # Definición con header estándar
+-- tool_xyz.py           # Tools específicas (flat)
+-- protocol_abc.md       # Protocolos específicos (flat)
+-- config.json           # Opcional
```

**Reglas:**

- < 5 archivos: Flat (todo en root)
- >= 5 archivos: Subcarpetas `tools/`, `protocols/` permitidas
- **En duda, duplicar tools** (general + skill-específica)
- Tras export debe funcionar sin BACH

#### Header estándar (obligatorio para todos los componentes)

```yaml
---
name: [name]
version: X.Y.Z
type: skill | agent | expert | service | protocol
author: [author]
created: YYYY-MM-DD
updated: YYYY-MM-DD
anthropic_compatible: true
dependencies:
  tools: []
  services: []
  protocols: []
description: >
  [Description]
---
```

Plantillas: `system/skills/_templates/TEMPLATE_*.md`

#### Etapas de expansión

BACH existe en tres etapas: **USMC** (núcleo Memory), **Rinnsal** (+ orquestación LLM), **BACH** (sistema completo). Detalles: [README.md](README.md#etapas-expansión)

#### Tres modos de acceso

BACH ofrece **dos vías de acceso paralelas** (CLI + Library-API), que se pueden combinar en **tres modos**. Ambas vías usan los mismos handlers y la misma DB.

##### Modo 1: Modo Sesión (CLI -- clásico)

Logging completo de inicio/apagado sobre la línea de comandos. Para sesiones de terminal interactivas.

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
# ... trabajar ...
python bach.py --shutdown "Resumen"
```

##### Modo 2: Modo Biblioteca (API -- ligero)

Acceso directo a handlers sin overhead de sesión. Para scripts, consultas rápidas, o LLMs que solo necesitan operaciones individuales.

```python
from bach_api import task
task.list()       # Inmediatamente usable
```

##### Modo 3: Modo Mixto (API con Lifecycle de Sesión)

Inicio/apagado completo vía API. **Recomendado para sesiones LLM** -- combina gestión de sesión con acceso API ergonómico.

```python
from bach_api import session, task, memory, injector

# Inicio de sesión (= python bach.py --startup --partner=claude --mode=silent)
session.startup(partner="claude", mode="silent")

# Trabajar con API
task.list()
memory.write("Nota")
injector.process("tarea compleja")

# Fin de sesión (= python bach.py --shutdown "Qué se hizo. Siguiente: Qué viene.")
session.shutdown("Qué se hizo. Siguiente: Qué viene.")
```

##### Módulos API disponibles

```python
from bach_api import (
    # Session-Lifecycle
    session,     # startup(), shutdown(), shutdown_quick(), shutdown_emergency()

    # Core handlers
    task,        # add(), list(), done(), assign(), ...
    memory,      # write(), read(), status(), fact(), search(), ...
    backup,      # create(), list(), info()
    status,      # run()

    # Domain handlers
    steuer,      # status(), beleg(), posten(), export()
    lesson,      # add(), last(), list(), search()
    partner,     # list(), status(), delegate(), info()
    logs,        # status(), tail(), show()
    msg,         # send(), unread(), read()
    email,       # send(), draft(), drafts(), confirm(), setup()

    # Cognitive injectors
    injector,    # process(), check_between(), tool_reminder(), status(), toggle()

    # Hook-Framework
    hooks,       # on(), off(), emit(), status(), list_events()

    # Plugin-API (extensión dinámica)
    plugins,     # register_tool(), register_hook(), register_handler(), load_plugin()

    # Raw access (any handler)
    app,         # app().execute("handler", "operation", ["args"])
)
```

##### Cuándo usar qué

| Situación | Recomendación |
|-----------|---------------|
| Sesión LLM (recomendado) | Modo mixto: `session.startup()` + API |
| Consulta única rápida | Modo biblioteca: directamente `task.list()` |
| Humano en terminal | Modo sesión: `python bach.py --startup` |
| Leer archivos, buscar código | Directo (glob/grep/read) |
| Handler no en bach_api | `app().execute("handler", "op", ["args"])` |

**Arquitectura:** `core/registry.py` reconoce 113+ handlers automáticamente (Auto-Discovery). Nuevos handlers solo necesitan un archivo `.py` en `hub/` -- sin mapeo manual. Hot-Reload: `app().reload_registry()`.

#### Tipos de componentes

| Tipo | Carpeta | Características |
|------|---------|-----------------|
| **Agent** | `agents/<name>/` | Orquesta varios dominios, carpeta propia |
| **Expert** | `agents/_experts/<name>/` | Conocimiento profundo de dominio, carpeta propia |
| **Service** | `hub/_services/<name>/` | Servicios generales, cerca de handlers |
| **Protocol** | `skills/workflows/` | 1 archivo = 1 protocolo (antes workflow), subdirectorios de categoría permitidos |
| **Connector** | `connectors/` | Conexiones externas (MCP, APIs) |
| **Tool (general)** | `tools/` | Reutilizable |
| **Tool (específica)** | En carpeta skill | Solo para este skill |

#### Fuentes de Skill y seguridad

| Clase | Fuentes | Enfoque |
|-------|---------|---------|
| **Gold standard** | Autoescrito | Mejor integración |
| **Serio** | anthropics/skills, anthropics/claude-cookbooks | Tras revisión 1:1 tomable |
| **Inseguro** | Otros repos GitHub | SOLO reescribir |
| **Blacklist** | `data/skill_blacklist.json` | PROHIBIDO |

---

### (1) INICIA ahora BACH [B/C]: (1) → (2) → (3) → (4) → (5) → (6)

*Solo en Modo B (Mixto) y C (Sesión). Modo A salta esta sección.*

---

### (1) INICIA ahora BACH [B/C]

**Modo C (Sesión/CLI):**

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
```

**Modo B (Mixto/API -- recomendado):**

```python
from bach_api import session
session.startup(partner="claude", mode="silent")
```

**Para Gemini:**

```python
# Modo B (API)
session.startup(partner="gemini", mode="silent")
# Modo C (CLI)
# python bach.py --startup --partner=gemini --mode=silent --watch
```

---

### (2) SISTEMA: Carga tu conocimiento de sistema [B/C]

```bash
bach help cli
bach help bach_info
bach help features
bach help naming
bach help guidelines
bach help architecture
# --> bach help injectors
```

O por API: `help.run("cli")`, `help.run("features")`, etc.

#### Descubrimiento y búsqueda de Handlers

BACH tiene 113+ handlers en `hub/`. **Cada handler es un comando CLI.** Para encontrar handlers, tools, skills o temas de ayuda:

```bash
# Búsqueda fuzzy en temas de ayuda (187+ temas, fuzzy match!)
bach help <término-búsqueda>           # ej. bach help web → sugiere web_scrape, web_parse

# Listar handlers
bach help list                    # Todos los 187+ temas de ayuda
bach help cli                     # Vista general de comandos CLI

# Buscar tools
bach tools list                   # Todas las tools Python
bach tools search <keyword>       # Búsqueda full-text en nombres y contenidos de tools

# Buscar skills & agents
bach skills list                  # Todas las skills en DB
bach skills search <keyword>      # Skills filtradas por keyword
bach agent list                   # Todos los agents

# Llamar cualquier handler directamente
bach <handler-name> <operation>   # ej. bach web-scrape get <url>
```

**Importante:** Si no sabes qué handler existe, usa `bach help <término-búsqueda>` -- la búsqueda fuzzy sugiere temas coincidentes, incluso con términos imprecisos.

#### Archivos para inspeccionar

- `system/CHANGELOG.md` - Historial de versiones
- `system/ROADMAP.md` - Features planificadas & vista de arquitectura

#### Documentos root (generados de DB, actualizados en `bach --shutdown`)

- `AGENTS.md` - Todos los boss-agents y experts con estado y rutas
- `PARTNERS.md` - Partners LLM y delegación
- `SKILLS.md` - Índice de skills
- `WORKFLOWS.md` - Índice de protocolos
- `CHAINS.md` - Toolchains
- `USECASES.md` - Casos de aplicación
- `USER.md` - Perfil de usuario
- `MEMORY.md` - Snapshot de memoria
- `BACH_HELP_REFERENCE.md` - Referencia completa de ayuda

#### Principios fundamentales

- **BACH como organismo:** Connectors/Bridge son los **sentidos & voz** (percepción + comunicación con mundo exterior). LLMs son la **mente** (pensar, entender, decidir). La base de datos y archivos de texto son la **memoria**. La GUI es la **cara**. API, CLI, tools, agentes, skills y workflows son las **manos** (potencial de acción).
- **Handler First:** Cada función como Handler en `hub/` -- automáticamente accesible vía CLI **y** API
- **API preferida:** LLMs usan `bach_api` en vez de CLI. Humanos usan CLI o GUI.
- **Sistémico:** Reutilizable para cualquier usuario
- **dist_type:** 0=USER (personal), 1=TEMPLATE (personalizable), 2=CORE (sistema)
- **Idempotente:** Imports repetibles sin duplicados
- **Comprobación de versión:** Siempre usar versión más nueva

> **PRINCIPIO FUNDAMENTAL:** BACH NO se desarrolla principalmente para un solo usuario, sino como sistema reutilizable.

#### Principios de trabajo

Seis reglas base para todos los partners de BACH (LLMs, agents, experts):

1. **Recursos propios primero** — Comprobar memory, wiki, tools y DB antes de preguntar al usuario
2. **Resultados antes que proceso** — Lo que cuenta es el resultado, no el método
3. **Hacer en vez de anunciar** — No expliques qué vas a hacer, simplemente hazlo
4. **Tener opinión** — Puedes discrepar y hacer propias propuestas
5. **Mantener compacto** — System prompts bajo 1000 tokens, mantener inyecciones esbeltas
6. **Asegurar conocimiento** — Escribir insights a memoria antes de perder el contexto

**Instrucciones específicas por partner:**
- **Claude:** Lee `CLAUDE.md` en directorio root (regla knowledge capture, integración)
- **Gemini:** Lee `GEMINI.md` en directorio root (regla knowledge capture, integración)
- **Ollama:** Lee `OLLAMA.md` en directorio root (regla knowledge capture, integración)

Estos archivos contienen reglas detalladas de knowledge capture y ajustes específicos por partner.

#### Esquema de base de datos (138 tablas en bach.db)

| # | Área | Tablas importantes |
|---|---------|---------------------|
| 1 | Sistema | `system_identity`, `system_config`, `instance_identity` |
| 2 | Tareas | `tasks` |
| 3 | Memory | `memory_working`, `memory_facts`, `memory_lessons`, `memory_sessions` |
| 4 | Tools | `tools` (550+ entradas) |
| 5 | Skills | `skills` (1870+ entradas) |
| 6 | Agents | `bach_agents`, `bach_experts`, `agent_synergies` |
| 7 | Archivos | `files_truth`, `files_trash`, `dist_files` |
| 8 | Automatización | `automation_triggers`, `automation_routines`, `automation_injectors` |
| 9 | Monitorización | `monitor_tokens`, `monitor_success`, `monitor_processes`, `monitor_pricing` |
| 10 | Conexiones | `connections`, `connector_messages`, `partner_presence` |
| 11 | Idiomas | `languages_config`, `languages_translations` |
| 12 | Distribución | `distribution_manifest`, `dist_type_defaults`, `releases`, `snapshots` |
| 13 | Wiki | `wiki` (87 artículos) |
| 14 | Casos de uso | `usecases`, `toolchains` |

Esquema completo: `system/data/schema/schema.sql` (138 tablas + Views + FTS)

---

### ARQUITECTURA GENERAL BACH v2.6

```text
  +=====================================================================+
  |                             USER-INTERFACES                         |
  |  +-----------+  +-----------+  +-----------+  +-------------------+ |
  |  |    CLI    |  | Lib-API   |  |    GUI    |  |  MCP v2.2 (IDE)   | |
  |  |  bach.py  |  | bach_api  |  | server.py |  |  mcp_server.py   | |
  |  |  +-----+-----+  +-----+-----+  +-----+-----+  +--------+--------+ |
  |  +========|==============|==============|==================|===========+
  |            |              |              |                  |
  |  +========v==============v==============v==================v===========+
  |  |                    CORE LAYER (core/*.py)                           |
  |  |  app.py → registry.py → Auto-Discovery of 75+ handlers            |
  |  |  base.py (BaseHandler) | db.py (Schema-First) | hooks.py (Events)  |
  |  +=========|==============|=======================================+====+
  |             |              |                                       |
  |  +==========v==============v=======================================v===+
  |  |                          HUB LAYER (hub/*.py)                       |
  |  |  System: startup, shutdown, status, backup, tokens, inject, hooks   |
  |  |  Domain: steuer, abo, haushalt, gesundheit, contact, calendar, email|
  |  |  Data: task, memory, db, session, logs, wiki, docs, inbox           |
  |  |  Multi-AI: agents, partner, daemon, ollama, ati                     |
  |  |  Extension: skills (create/reload), hooks (status/events/log/test)  |
  |  +====|======================|======================|=================+
  |        |                      |                      |
  |  +----v------------------+   |   +------------------v-----------------+
  |  |   AGENTS LAYER        |   |   |   CONNECTORS & PARTNERS           |
  |  |                       |   |   |                                    |
  |  | agents/ (folders)      |   |   | connectors/ (MCP, APIs)           |
  |  | agents/_experts/       |   |   | partners/ (Multi-LLM config)      |
  |  +-----------------------+   |   +------------------------------------+
  |                               |
  |  +---------------------------v----------------------------------------+
  |  |   SKILLS & TOOLS LAYER                     |    DATA LAYER         |
  |  |                                            |                       |
  |  | skills/workflows/ (formerly _workflows)    | bach.db (Unified)     |
  |  | skills/_templates/ (Standard templates)    | File system            |
  |  | hub/_services/ (folders)                   | inbox/outbox/          |
  |  | tools/*.py | c_*.py | injectors.py         |                       |
  |  +--------------------------------------------+-----------------------+
  |               |
  |  +-----------v-----------+
  |  | SELF-EXTENSION LAYER  |
  |  |                       |
  |  | skills create (6 typ) |
  |  | skills reload (Hot)   |
  |  | hooks.on/emit (14 Ev) |
  |  | Plugin API (planned)  |
  |  +-----------------------+
  ```

---

### (3) MEMORY: Carga tu contexto episódico [B/C]

```bash
bach help memory
bach help lessons
bach help consolidation
```

#### El modelo cognitivo de memoria (5 tipos)

| Tipo | Equivalente | Función | Comando |
|------|-------------|---------|---------|
| **Working** | Corto plazo | Sesión actual | `bach mem write` |
| **Episodic** | Diario | Sesiones completadas | `bach --memory session` |
| **Semantic** | Conocimiento mundo | Hechos, wiki, ayuda | `bach --memory fact "key:value"` |
| **Procedural** | Saber hacer | Tools, skills, workflows | `bach help tools` |
| **Associative** | Conexión | Consolidación, trigger | `bach consolidate` |

---

### (4) CAPACIDADES: Carga conocimiento sobre tus capacidades [B/C]

```bash
bach help skills
bach help tools
```

**Jerarquía:**

- **Agentes:** Orquestan varias áreas, carpeta propia
- **Experts:** Conocimiento profundo de dominio, carpeta propia
- **Services:** Servicios generales, cerca de handlers

**Directorios importantes:**

- `system/agents/` - Agentes (cada uno carpeta propia)
- `system/agents/_experts/` - Experts (cada uno carpeta propia)
- `system/hub/_services/` - Services (cada uno carpeta propia)
- `system/skills/workflows/` - Protocolos (archivos individuales, antes _workflows)
- `system/skills/_templates/` - Plantillas estándar
- `system/connectors/` - Conexiones externas (MCP, APIs)
- `system/partners/` - Configuraciones Multi-LLM

---

### (5) PLANIFICACIÓN DE TAREAS [B/C]

#### (5.1) Detectar deseos de usuario

- Detectar deseos concretos de usuario mencionados en prompt como tareas
- Definir tareas y planear tu enfoque
- Si no hay deseos concretos, ir a 5.2

#### (5.2) Cargar contexto de tareas

```python
# API (preferido)
from bach_api import task
task.list()
```

```bash
# CLI
bach help tasks
bach task list
```

- Seleccionar tareas independientemente. **Desde 2026-10-25: Toma de control y entrega corren vía Lease, ver sección "COMO AGENTE TRABAJAR TAREAS ABIERTAS" arriba.** `bach task claim` está obsoleto (claim sin fence/lease-id).

---

### (6) CONOCIMIENTO PROCESAL & PROTOCOLOS [C]

*En Modo B opcional -- los protocolos son documentación, no código.*

```bash
bach help protocol
bach help between-tasks
bach help practices
```

**Ruta:** `system/skills/workflows/`

---

## PAQUETES DE TEMAS (leer cuando se necesiten -- todos los modos)

### TEMA: Trabajo en equipo (PAQUETE: TRABAJO EN EQUIPO)

*Cuándo leer:* Trabajas con partners en el sistema.

```bash
bach help partners
bach help multi_llm
bach help delegate
```

**Sistema de chat:**

```python
# API
from bach_api import msg, partner
msg.send("gemini", "Por favor investiga...")
msg.unread()
partner.delegate("Investigación", "--to=gemini")
```

```bash
# CLI
bach msg send claude "Texto"
bach msg unread
```

**Sistema de locks:**

```bash
bach llm lock <archivo>           # Lock ANTES de escribir
bach llm unlock [archivo]         # Liberar lock
bach llm status                 # Quién tiene qué locks?
```

---

### TEMA: Resolución de problemas (PAQUETE: RESOLUCIÓN DE PROBLEMAS)

*Cuándo leer:* Te encuentras con problemas o bloqueos.

```bash
bach help operators
bach help planning
bach help problem_solving
bach help strategies
```

---

### TEMA: Tareas de programación (PAQUETE: PROGRAMACIÓN)

*Cuándo leer:* Editas código o arreglas bugs.

```bash
bach help ati
bach help coding
bach help bugfix
```

---

### TEMA: Mantenimiento (PAQUETE: MANTENIMIENTO)

*Cuándo leer:* Editas tareas de mantenimiento.

```bash
bach help maintain
bach help maintenance
bach help recurring
bach daemon status
```

---

### TEMA: Gestión de archivos (PAQUETE: GESTIÓN DE ARCHIVOS)

*Cuándo leer:* Realizas operaciones de archivos.

```bash
bach help trash
bach help migrate
bach help distribution
```

---

### TEMA: Lectura web (PAQUETE: WEB)

*Cuándo leer:* Necesitas recuperar páginas web, extraer contenidos o hacer análisis web.

```bash
bach help web_parse
bach help web_scrape
```

**Dos handlers para propósitos distintos:**

| Handler | Comando | Propósito | Técnica |
|---------|--------|-----------|---------|
| `web_parse` | `bach web-parse url/clean <url>` | **Extracción de contenido** (contenido principal como Markdown) | trafilatura/html2text |
| `web_scrape` | `bach web-scrape get/links/forms/headers <url>` | **Análisis de estructura** (links, formularios, headers) | requests + Regex |

**Recomendación:** Para contenidos de texto usar `web-parse clean <url>` (quita nav/header/footer). Para datos brutos o listas de links usar `web-scrape`. Ambos usan HTTP requests -- páginas renderizadas con JS entregan solo HTML del lado servidor.

**Skill:** `skills/workflows/webseiten-lesen.md` -- Procedimiento detallado con árbol de decisiones.

---

### TEMA: Auto-extensión (PAQUETE: AUTO-EXTENSIÓN) [B/C]

*Cuándo leer:* Te falta una capacidad o quieres extender BACH.

```bash
bach help self-extension
bach help hooks
bach help skills
```

**Crear nuevas capacidades (5 tipos):**

```bash
bach skills create voice-processor --type tool       # Nueva tool scaffolded
bach skills create email-agent --type agent           # Nuevo agent scaffolded
bach skills create tax-expert --type expert            # Nuevo expert scaffolded
bach skills create api-gateway --type handler          # Nuevo comando CLI scaffolded
bach skills create data-sync --type service            # Nuevo service scaffolded
```

**Tras creación: Hot-Reload (¡sin reinicio!)**

```bash
bach skills reload
```

**Hook-framework (14 eventos):**

```python
from core.hooks import hooks

# Adjuntar lógica propia a eventos del sistema
hooks.on('after_task_create', mi_funcion, name='mi_plugin')
hooks.on('after_startup', startup_check, name='mi_plugin')

# Mostrar eventos
# bach hooks events
```

**Eventos:** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> Los hooks son el **marco técnico**. Los inyectores son el **subsistema cognitivo**. Trabajan independientemente entre sí.

---

### TEMA: Apagado (PAQUETE: APAGADO) [B/C]

*Cuándo leer:* La sesión termina. Solo relevante en Modo B y C.

**Modo B (API -- recomendado):**
```python
from bach_api import session, memory
memory.session("TEMA: Qué se hizo. SIGUIENTE: Qué viene.", session_id="SESSION_ID", partner="claude")
session.shutdown("Resumen", partner="claude", session_id="SESSION_ID")
# O rápido:
session.shutdown_quick("Nota corta", partner="claude", session_id="SESSION_ID")
```

`SESSION_ID` es la ID propia del reporte de inicio. Para varias sesiones abiertas siempre especificar ID y partner; una selección ambigua se rechaza.

**Modo C (CLI):**
```bash
bach help shutdown
bach --memory session "TEMA: Qué se hizo. SIGUIENTE: Qué viene."
bach --shutdown
```

---

## HOOKS & INYECTORES

### Hook-framework (sistema de eventos técnico)

Los hooks permiten adjuntar lógica propia a 14 eventos de lifecycle -- sin cambiar código existente.

```python
from core.hooks import hooks

# Registrar listeners
hooks.on('after_task_done', auto_backup, name='backup_plugin')
hooks.on('after_startup', health_check, priority=10, name='health')

# CLI
# bach hooks status    → Muestra todos los hooks
# bach hooks events    → Lista los 14 eventos
# bach hooks log       → Últimas ejecuciones
```

**Eventos:** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> Los hooks son el **marco técnico**. Los inyectores son el **subsistema cognitivo**. Trabajan independientemente entre sí.

---

### Inyectores (orquestación cognitiva)

Los 6 inyectores simulan **pensar y asociaciones** como **Ejecutiva Central**. Disponibles vía CLI y API.

| Inyector | Subfunciones | API-capaz |
|----------|-------------|-------------|
|----------|-------------|-------------|
| **strategy_injector** | Metacognición, apoyo a decisión, análisis de errores | Sí |
| **context_injector** | Recomendación de tools, recuperación de memoria, análisis de requisitos | Parcial* |
| **between_injector** | Control de calidad, transición de tareas, validación de resultados | Sí |
| **time_injector** | Sensación de tiempo (Timebeat), comprobación de noticias | Sí |
| **tool_injector** | Recordatorio de tools, aviso de duplicados | Sí |
| **task_assigner** | Auto-asignación, descomposición de tareas | Sí |

***context_injector contiene comandos CLI como pistas. En modo API filtrable.*

**CLI:**
```bash
bach --inject status            # Estado de todos los inyectores
bach --inject toggle <name>     # Encender/apagar
```

**API:**
```python
from bach_api import injector

injector.process("text")              # Aplicar todos los inyectores a texto
injector.check_between("task done")   # Control de calidad tras fin de tarea
injector.tool_reminder()              # Tools disponibles (una vez)
injector.assign_task()                # Próxima tarea auto-asignación
injector.time_check()                 # Hora + noticias
injector.status()                      # Estado de todos los inyectores
injector.toggle("strategy_injector")  # Individualmente on/off
injector.set_mode("api")              # Filtrar pistas CLI del contexto
```

---

## CHANGELOG

### v3.10.0 (2026-10-25)

- **Entrada de agente**: Nueva sección arriba "COMO AGENTE TRABAJAR TAREAS ABIERTAS" (arranque, selección de tarea, tomar lease, worktree, tests, PR, entregar resultado, siguiente tarea; límites; gaps conocidos). Meta: un agente (Claude, Codex, Kimi, Gemini) arranca solo con este archivo.
- **Marcado obsoleto:** `bach task claim` y (5.2) "asignarte"; números y vista de arquitectura debajo de la nueva sección son de 2026-03-12 y no re-medidos.
- Sin contenidos borrados. Modos A, B, C sin cambios.

### v3.8.0 (2026-03-12)

- **Descubrimiento de handlers:** Nueva sección en (2) -- `bach help <término-búsqueda>` como mecanismo principal de descubrimiento para 109+ handlers documentado
- **Referencia de búsqueda:** `bach help list`, `bach tools search`, `bach skills search` como puntos de entrada de búsqueda
- **Paquete de temas WEB:** Nuevo paquete con referencia a handlers `web_parse` y `web_scrape`
- **Skill `webseiten-lesen`:** Nuevo skill de workflow con árbol de decisiones para extracción de contenido web
- **Documentación:** Handlers ahora encontrables en SKILL.md en vez de solo vía CLI

### v3.2.0-butternut (2026-02-28)

- **Agent CLI:** `AgentLauncherHandler` -- `bach agent start/stop/list` para control directo de agentes
- **Sistema de prompts:** `PromptHandler` -- `bach prompt list/add/edit/show/board-create` para gestión central de prompts
- **Extensiones SharedMemory:** `current-task`, `generate-context`, `conflict-resolution`, `decay`, `changes-since`
- **USMC Bridge:** United Shared Memory Client (`hub/_services/usmc_bridge.py`)
- **Cadenas llmauto:** Prompts de Claude como Chain-steps + resolución URL `bach://`
- **Scheduler:** `job_type='chain'` + renombrado `daemon_jobs` → `scheduler_jobs`
- **Nuevos módulos API:** `agent`, `prompt` en `bach_api`
- **Portes:** SharedMemoryHandler, ApiProberHandler, N8nManagerHandler, UserSyncHandler, Stigmergy-service
- **Tablas:** 4 nuevas tablas DB: `prompt_templates`, `prompt_versions`, `prompt_boards`, `prompt_board_items`
- **109+ handlers** (antes: 75+)

### v2.6.0 (2026-02-13)

- **Reestructuración de directorios:** Separación clara de Agents, Skills, Connectors y Partners
  - `skills/_agents/` → `agents/` (Top-level bajo system/)
  - `skills/_experts/` → `agents/_experts/` (Experts pertenecen a Agents)
  - `skills/_workflows/` → `skills/workflows/` (Workflows ahora se llaman Protocols)
  - `skills/_connectors/` → `connectors/` (Top-level bajo system/)
  - `skills/_partners/` → `partners/` (Top-level bajo system/)
- **PathHealer:** Corrección automática de rutas en todos los archivos afectados
- **Tipo de componente `protocol`:** Reemplaza `workflow` en jerarquía de tipos
- **Tipo de componente `connector`:** Nuevo para conexiones externas (MCP, APIs)
- **Diagrama de arquitectura:** AGENTS LAYER y CONNECTORS & PARTNERS como secciones propias
- **SKILL.md v2.6:** Todas las referencias, tablas y diagramas ajustados a nueva estructura

### v2.5.0 (2026-02-13)

- **Sistema Auto-Extensión:** Partners AI pueden darse nuevas capacidades
  - `bach skills create <name> --type <typ>` (5 tipos: tool, agent, expert, handler, service)
  - `bach skills reload` (Hot-Reload: Registry + Tools + Skills-DB)
  - Bucle Auto-Extensión: DETECTAR → CREAR → REGISTRAR → USAR → REFLEXIONAR
- **Hook-framework:** Sistema de eventos extensible con 14 eventos de lifecycle
  - `core/hooks.py` - HookRegistry singleton, prioridades, log de eventos
  - `hub/hooks.py` - CLI: `bach hooks status/events/log/test`
  - Integración en: Startup, Shutdown, Task, Memory, Lesson, Skills, App
  - Hooks != Inyectores: marco técnico vs. subsistema cognitivo
- **Email handler:** Gmail API con draft safety (send, draft, confirm, cancel)
- **Registry Hot-Reload:** `app().reload_registry()` sin reinicio
- **Regla (f) Auto-Extensión:** "¡Si te falta una capacidad, dátela tú mismo!"
- **Documentación:** hooks.txt, self-extension.txt, cli.txt, skills.txt, ROADMAP.md

### v2.4.0 (2026-02-08)

- **MCP Server v2.2:** 23 tools, 8 resources, 3 prompts - los tres primitivos MCP
- **Email adapter:** SMTP_SSL en notify.py (portado de BachForelle)
- **BachFliege + BachForelle:** Analiza y archiva (`docs/_archive/con5_BACHFLIEGE_BACHFORELLE_ARCHIVE.md`)

### v2.3.0 (2026-02-06)

- **Reglamento completamente revisado:** SIEMPRE → Determinar tipo de acceso → Específico de modo
- **Tres modos:** A (Biblioteca), B (Mixto), C (Sesión) con etiquetas [B], [C], [B/C]
- **Principio co-desarrollo:** "Usar BACH significa co-desarrollar BACH" como regla central
- **bach_api.py extendido:** session, partner, logs, msg, tools, help, injector
- **14 módulos API:** Acceso programático completo a todos los handlers
- **Inyectores vía API:** Los 6 inyectores usables vía Library + filtros CLI
- **Lifecycle de sesión vía API:** `session.startup()` / `session.shutdown()`
- **Diagrama de arquitectura actualizado** (Core Layer + bach_api)
- **Todas las secciones etiquetadas con modo** [B], [C] o [B/C]

### v2.2.0 (2026-02-06)

- Dos vías de acceso (CLI + Library-API) documentadas
- bach_api.py módulos base: task, memory, backup, steuer, lesson, status

### v2.1.0 (2026-02-04)

- Arquitectura de Skill v2.0 integrada
- Principio de comprobación de versión introducido
- Header estándar
  completado.