---
name: bach
version: 3.10.0
type: skill
author: BACH Team
created: 2025-12-01
updated: 2026-10-25
anthropic_compatible: true

description: >
  Центральная система управления BACH. Это ЕДИНСТВЕННЫЙ навык,
  который нужно загрузить в Claude. Он знает все локальные навыки,
  выполняет проверки версий и при необходимости подгружает более новые локальные версии.
  Активируется автоматически при каждом использовании навыка.
---

# КАК АГЕНТ, ОБРАБАТЫВАЮЩИЙ ОТКРЫТЫЕ ЗАДАЧИ (вход для Claude, Codex, Kimi, Gemini)

> **Новое с версии v3.10.0 (2026-10-25).** Если твой заказ звучит «прочитай SKILL.md и обработай открытые задачи», то **сначала действует этот раздел**. Всё остальное в этом файле — справочник и читается только по мере необходимости.
> Подробная версия, пригодная для копирования: `Desktop\OCEAN\EINWEISUNG-EXTERNE-WORKER.md` (OneDrive Лукаса, не в репозитории). Договор аренды: `docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md`, клиенты: `docs/architecture/TASKDB-SALT-LEASE-CLIENTS-v1.md`. Локальный каркас воркера (Buddha): `docs/architecture/LOKALER-WORKER-HARNESS.md` (PR #520).

**Порядок в одном предложении:** загрузка → выбор задачи → **сначала захват аренды, затем работа** → собственный ворктри → тесты → PR → сдача результата → следующая задача. Без явного указания Лукаса на остановку не прекращай работу.

### 1. Загрузка и режим
- Доступ к Mac Studio через предоставленный SSH-доступ; собственные учётные данные не создавай. Проект в `$BACH_ROOT` (на Mac Studio `~/services/bach`), Python из его venv. Прочитай `AGENTS.md` и инструкции подпроекта, в котором ты работаешь.
- **Режим B (Смешанный)** — нормальный случай для агентов, которые активно соучаствуют. **Режима A (Библиотека)** достаточно, если ты только обрабатываешь задачи и не используешь BACH как сессию: путь аренды ниже идёт через lead-службу и не требует запуска сессии. Режим C (Сессия) — только по явной просьбе.
- Перед первой задачей прочитай текущий план `Desktop\OCEAN\AKTUELLER-PLAN.md` и `MODUL-ZUORDNUNG.md` (места сборки).
### 2. Поиск свободных задач
- **Нативно:** `TaskLeaseClient.task_candidates(limit=100, offset=…)` (читай все страницы, а не только первую), затем `task_snapshot(task_id)` для полного описания. `bach task list` показывает те же задачи только для просмотра.
- **Правило выбора:**
  1. Только задачи, у которых выполнены зависимости, нет чужой активной аренды и для которых достаточно твоих инструментов.
  2. **Сначала самый высокий приоритет** (P0 перед P1 перед P2). При равном приоритете сначала то, что соответствует фокусам повестки (на 25.10.2026: Förderplaner, шаблоны/управление агентов, Running & Living, перестройка GUI, надёжность воркеров; определяющим является `AKTUELLER-PLAN.md`).
  3. **Никаких задач `OLLAMA`.** Это фоновая очередь локальных воркеров (Buddha, Ollama Cloud, OpenRouter). Задачи для `USER`/`HUMAN`/`LUKAS` и зарезервированные чужие задачи тоже оставляй лежать. `BACH` означает «доступно для совместной работы». Не выдумывай дополнительной обязанности слота.
  4. Задачи по ревью и проверке от других авторов прямо подходят.
  5. Если задача зависит от открытого решения пользователя или не соответствует твоим возможностям: зафиксируй вопрос или причину (заметка в задаче) и возьми следующую. Никогда не меняй правила или защитные гейты только ради возможности взять задачу.
### 3. Захват задачи до начала работы
```python
import os, sys
os.environ["BACH_NO_AUTO_MIGRATE"] = "1"
sys.path.insert(0, os.path.join(os.environ["BACH_ROOT"], "system"))
from hub._services.task_lease_client import TaskLeaseClient
# BACH_ROOT und BACH_DEVICE_TOKEN stellt der bereitgestellte Zugang; den Token nie ausgeben
client = TaskLeaseClient(lead_url="http://127.0.0.1:8000", timeout=35)  # liest BACH_DEVICE_TOKEN
snap = client.task_snapshot(task_id)                      # vollständige Beschreibung und Taskversion
ack = client.acquire(task_id, worker_id="<agent>@<host>", host="<host>", ttl_profile="S")
# neue request_id wird erzeugt; die Taskversion aus dem Snapshot kann als task_version=… mitgegeben werden
# ack.lease_id, ack.fence, ack.task_version: für diesen Lauf aufbewahren, nie in Berichte schreiben
client.renew(task_id, lease_id=ack.lease_id, fence=ack.fence)   # rechtzeitig, auch bei langen Arbeiten
```
- Идентификатор воркера **`<agent>@<host>`**, собственные request-ID и поколение никогда не передавать другому воркеру. Начинай работу только после подтверждённого согласия.
- Если `renew` отказывает, аренда истекла или fence изменилась: **прекратить все операции записи по этой задаче.** После подтверждённых изменений содержания обновить сохранённую версию задачи.
- **Не использовать:** `bach task claim` (устаревший claim без fence/lease-ID) и `~/compute/luna-gui/task_tool.py claim` (задаёт только `assigned_to`, без аренды). Оба варианта — не нативный захват, они не защищают от параллельной обработки. `task_tool.py note` (добавить текст к описанию) и `list` можно использовать как временное решение, пока нет нативного аналога.
- Сигнатуры обязательно читать из `system/hub/_services/task_lease_client.py`, а не из этого примера.
### 4. Работа
- **Свой ворктри на каждую задачу** от `origin/main`: `git worktree add ~/services/bach-worktrees/<zweig> -b <zweig> origin/main`. Имя ветки `<agent>/<task>-<kurz>-<datum>`. Основной чекаут `~/services/bach` занят (чужие незафиксированные изменения): там не работают, не измеряют и не собирают.
- **Место сборки:** новая предметная логика относится в подходящий модульный репозиторий Ocean согласно `MODUL-ZUORDNUNG.md`, а не в ядро BACH.
- Проверь результат по критериям приёмки задачи. Запусти тесты изменённых областей и утверждай только то, что можешь подтвердить. Немецкие тексты для конечных пользователей — с настоящими умлаутами.
- Перед коммитом: сканирование секретов, чтение диффа, коммитить только свои файлы (без сводного коммита).
- Отправь ветку, **создай PR в `main`** и зафиксируй это в задаче. Коммит, push, PR, слияние, развёртывание и предметную приёмку указывай по отдельности. Ветка — это ещё не поставленное состояние.

### 5. Сдача результата
- **Готово:** `client.submit_result(task_id, lease_id=…, fence=…, task_version=…, generation="<neue-Generation>", result="<Text>")`. `result` — конкретный текст **не более 3000 знаков** (достигнутые критерии, изменения, ссылка на PR, SHA коммита, реальные результаты проверки, ограничения); чистое сообщение об исполнении („done“) отклоняется. Сдача переводит задачу в `review` и освобождает аренду. Затем прочитай `task_result_snapshot(task_id)` и проверь ID/хеш результата; один чат-текст сдачей не является.
- **Частичный результат или блокада:** отправь WIP-ветку, затем `client.release(task_id, lease_id=…, fence=…, outcome="return" | "blocked", note="<Branch, SHA, nächster Schritt>")`. Без общего `done`, без искусственно продлённой аренды, пока ждёшь людей. (`complete=false` есть только в задаче-инструменте локального запуска Buddha, см. документ харнеса; в SDK его нет.)
- Затем **сразу же следующую задачу** (шаг 2). Если сейчас нечего взять: сообщи обоснованные причины, подожди недолго, проверь снова. Не завершай свой заказ самостоятельно.
- Краткий отчёт по каждой задаче: ID задачи, работа, подтверждения, SHA коммита/удалённого репозитория, PR, считанное обратно состояние задачи/результата/аренды. Ревью собственной работы помечай как не независимое.
### 6. Ограничения (действуют всегда)
- **Не мержить**, не пушить в `main`, ничего не раскатывать, не перезапускать сервисы, не менять конфигурацию воркеров, не останавливать чужие задачи/воркеры, не запускать `.SYNC`. Мерж идёт через вторичную проверку, раскат — после проверки.
- **`bach.db` никогда не писать напрямую**, без собственных SQL-изменений, копия базы данных — не авторитет. Всегда только нативный API/SDK.
- **Никаких блокировок в `OneDrive\.TOPICS` или `.TOPICS\.AI`:** они останавливают на Mac фонового воркера Buddha и любой раскат. Блокировки — только для собственного пути ворктри.
- Чужие активные аренды, текущая работа других агентов и заблокированные пути остаются защищёнными. Токены и учётные данные никогда не выводить и не коммитить.

### 7. Известные пробелы (на 25.10.2026)
- **Нативного короткого ярлыка пока нет** `bach task take|renew|submit|return|block`; он запланирован (`TASKDB-SALT-LEASE-VERTRAG-v1.md`, раздел „Tasksystem, Leases und Locks“). Постоянный нативный путь сегодня — Python-SDK `TaskLeaseClient` (выше); `bach_api.task` даёт только `lease_acquire`/`lease_read`/`lease_renew`/`lease_release`/`lease_decompose`, без списка кандидатов и без `submit_result`.
- `task_tool.py` лежит вне репозитория (`~/compute/luna-gui/`); его `list` читает `bach.db` напрямую (только чтение), а его `claim` — не аренда.
- Вводный инструктаж, план и `MODUL-ZUORDNUNG.md` лежат на рабочем столе OneDrive у Lukas, а не в репозитории; агент, работающий на Mac, не доберётся до них без копии.
- Договор о происхождении внешних результатов: #2339 нативно принят, мерж в Main и релиз ещё впереди (PR #507). До тех пор результаты честно трактовать как сданные либо как частичный результат.
> **Указание о состоянии остальной части файла:** Всё ниже этого раздела последний раз содержательно переработано 2026-03-12 (v3.8.0). Числа (обработчики, таблицы, хуки, темы), обзор архитектуры v2.6 и планирование задач (5) с тех пор **заново не замерялись**; при противоречии решают код и замеры. Приём задач больше не идёт через `bach task claim`, а выполняется как описано выше.

---

# УКАЗАНИЕ ПО ВЕРСИЯМ

# Проверь, существует ли более новая версия этого навыка (локально или централизованно)

# ВСЕГДА используй версию с самым высоким номером

# Versions-Check: bach skills version bach

# Добро пожаловать в Bach

---

## ПРАВИЛА - РУКОВОДСТВА - СТАНДАРТЫ

---

### ВСЕГДА (прежде всего остального)

**(1) ПРОВЕРКА ВЕРСИИ:** Если доступно несколько версий этого SKILL.md (локально, централизованно), сравни номера версий и при необходимости переключись на новейшую версию и продолжай чтение оттуда.
```bash
bach skills version bach   # Prueft ob aktuellere Version existiert
```

**(2) ПРОВЕРКА ОПЕРАЦИОННОЙ СИСТЕМЫ:** Определи, работаешь ли ты на Windows, Mac или Linux.
- Windows: Нет `/dev/null` И никакого `NUL:`. Вместо этого опускай вывод или используй `2>&1`. Избегай `&&`, выполняй команды по отдельности
- При nul-файлах: `python tools/c_nul_cleaner.py --dir <pfad> --delete`

---

### ЗАТЕМ: Уточни способ доступа / режим сессии

Выбери режим, который подходит твоей ситуации:

| Режим | Когда | Запуск | Доступ |
|-------|------|---------|--------|
| **A) Библиотека** | Гость, чтение, отдельные запросы, BACH как инструмент | Без запуска | `from bach_api import task; task.list()` |
| **B) Смешанный** | Пользователь просил запустить BACH, активное участие | Запуск API | `session.startup()` + API + `session.shutdown()` |
| **C) Сессия** | Классический, автоматический запуск, подробный протокол | Запуск CLI | `python bach.py --startup --partner=claude` |

- Режим C можно в любой момент переключить на B (использовать API вместо CLI)
- Режимы B и C можно в любой момент переключить на A (отдельный запрос без сессии)
- При сомнениях: **Режим B** (рекомендуется для LLM-сессий)
---

### В РЕЖИМАХ B и C: Правила активного использования

**(1) Чтение и запись -- использование BACH означает соучастие в разработке:**

Кто пользуется BACH, тот участвует в его развитии. Каждое обращение — возможность улучшить систему.

- **(a) Handler First:** Каждая функция должна быть Handler в `hub/`. Handler автоматически доступен через CLI **и** API. Отдельный код для разных способов доступа не пишется.
- **(b) Заполняй пробелы:** Если не хватает Handler, API-модулей, Skills, Tools, Workflows или других компонентов -- создай их. Отсутствующие Handler имеют наивысший приоритет: они — основа всех способов доступа.
- **(c) Своё приветствуется:** Создание собственных Skills, Workflows, Tools, MCPs всячески приветствуется. При работе над существующими согласуй с User.
- **(d) Fix-or-Task:** Проблема ведёт либо к немедленному исправлению (мелкое), либо к задаче в Queue (крупное). Решает соотношение: затраты vs. польза. Затем — назад к основной задаче.
- **(e) Self-Healing:** Найдёшь ошибки в BACH (пути, команды, устаревшие ссылки, сломанные импорты), исправь их сразу и сообщи User. BACH ремонтирует себя руками своих пользователей.
- **(f) Self-Extension:** Если тебе не хватает способности, дай её себе сам! Используй `bach skills create`, чтобы создать каркас новых Tools, Handler, Agents, Experts или Services. После `bach skills reload` они сразу доступны. См.: `bach help self-extension`

**(2) Выполни стартовую процедуру** (см. ниже). Прочитай обязательные пакеты и при необходимости (`-->`) добровольные ссылки. Пакеты снабжены маркировкой режима:
- `[C]` → Читать только в режиме сессии
- `[B]` → Читать только в смешанном режиме, в режиме сессии пропустить
- `[B/C]` → Читать в обоих режимах
- Без маркировки → Читать всегда по мере надобности

**(3) Читай дополнительные пакеты при необходимости** (тематические пакеты ниже).

---
### В РЕЖИМЕ A: Правила для гостевого и инструментального использования

Читайте дополнительные пакеты при необходимости. Запуск не требуется, завершение работы не предполагается.

```python
from bach_api import task, memory, tools, steuer
task.list()         # Sofort nutzbar
tools.search("ocr") # Werkzeug finden
```

---

### Структура документа (навигационная карта)

```
IMMER (vor allem anderen)
├── (1) VERSIONS-CHECK
└── (2) BETRIEBSSYSTEM-CHECK

ZUGRIFFSART klaeren
├── A) Bibliothek    → Gast, lesend, Werkzeug
├── B) Gemischt      → User-gefuehrt, API + Startup (empfohlen)
└── C) Session       → Klassisch, CLI + volles Protokoll

IM MODUS B und C
├── (1) Lesen = Mitentwicklung
│   ├── (a) Handler First
│   ├── (b) Luecken fuellen
│   ├── (c) Eigenes erwuenscht
│   ├── (d) Fix-or-Task
│   └── (e) Self-Healing
├── (2) Startprozedur durchfuehren
│   ├── (1) Start              [B/C]
│   ├── (2) Systemwissen       [B/C]
│   ├── (3) Memory             [B/C]
│   ├── (4) Faehigkeiten       [B/C]
│   ├── (5) Aufgabenplanung    [B/C]
│   └── (6) Protokolle          [C]
└── (3) Zusatzpakete bei Bedarf

IM MODUS A
└── Zusatzpakete bei Bedarf

THEMEN-PAKETE (alle Modi, bei Bedarf)
├── Teamarbeit
├── Problemloesung
├── Coding
├── Wartung
├── Dateiverwaltung
├── Self-Extension              [B/C]
└── Shutdown                    [B/C]

REFERENZ
├── Skill-Architektur
├── Drei Zugriffsmodi (API-Module, Wann-was-nutzen)
├── Gesamtarchitektur-Diagramm
├── Hooks & Injektoren
└── Changelog
```

---

### Архитектура навыков v2.0 (NEU)

#### Принцип проверки версий

**ВСЕГДА используйте новейшую версию** — независимо от того, хранится она локально или централизованно:

```bash
bach skills version <name>    # Prüfe Versionen
bach tools version <name>     # Prüfe Tool-Versionen
```

#### Структура навыка: один навык = одна папка

Каждый навык, агент, эксперт **полностью автономен** в собственной папке:

```
agents/entwickler/
├── SKILL.md              # Definition mit Standard-Header
├── tool_xyz.py           # Spezifische Tools (flat)
├── protocol_abc.md       # Spezifische Protokolle (flat)
└── config.json           # Optional
```

**Правила:**

- < 5 файлов: плоская структура (всё в корне)
- >= 5 файлов: вложенные папки `tools/`, `protocols/` разрешены
- **В случае сомнений дублируйте инструменты** (общие + специфичные для навыка)
- после экспорта всё должно работать без BACH

#### Стандартный заголовок (обязателен для всех компонентов)

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
  [Beschreibung]
---
```

**Шаблоны:** `system/skills/_templates/TEMPLATE_*.md`

#### Ступени расширения

BACH существует в трёх ступенях: **USMC** (ядро памяти), **Rinnsal** (+ оркестрация LLM), **BACH** (полная система). Подробнее: [README.md](README.md#ausbaustufen)

#### Три режима доступа

BACH предлагает **два параллельных пути доступа** (CLI + Library-API), которые комбинируются в **три режима**. Оба пути используют одни и те же Handler и одну и ту же DB.

##### Режим 1: Режим сессии (CLI -- классический)

Полный протокол Startup/Shutdown через командную строку. Для интерактивных терминальных сессий.

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
# ... arbeiten ...
python bach.py --shutdown "Zusammenfassung"
```

##### Режим 2: Режим библиотеки (API -- лёгкий)

Прямой доступ к Handler без накладных расходов сессии. Для скриптов, быстрых запросов или LLM, которым нужны лишь отдельные операции.

```python
from bach_api import task, memory, steuer, partner, tools, injector

task.list()                              # Tasks abfragen
memory.write("Wichtige Notiz")           # Memory schreiben
steuer.status()                          # Steuer-Status
partner.list()                           # Partner auflisten
injector.process("ich bin blockiert")    # Kognitive Hilfe
```

##### Режим 3: Смешанный режим (API с жизненным циклом сессии)

Полный Startup/Shutdown через API. **Рекомендуется для LLM-сессий** -- сочетает управление сессией с эргономичным доступом к API.

```python
from bach_api import session, task, memory, injector

# Session starten (= python bach.py --startup --partner=claude --mode=silent)
session.startup(partner="claude", mode="silent")

# Arbeiten mit API
task.list()
memory.write("Notiz")
injector.process("komplexe aufgabe")

# Session beenden (= python bach.py --shutdown "Zusammenfassung")
session.shutdown("Was gemacht wurde. Naechste: Was kommt.")
```
##### Доступные API-модули

```python
from bach_api import (
    # Session-Lifecycle
    session,     # startup(), shutdown(), shutdown_quick(), shutdown_emergency()

    # Kern-Handler
    task,        # add(), list(), done(), assign(), ...
    memory,      # write(), read(), status(), fact(), search(), ...
    backup,      # create(), list(), info()
    status,      # run()

    # Domain-Handler
    steuer,      # status(), beleg(), posten(), export()
    lesson,      # add(), last(), list(), search()
    partner,     # list(), status(), delegate(), info()
    logs,        # status(), tail(), show()
    msg,         # send(), unread(), read()
    email,       # send(), draft(), drafts(), confirm(), setup()

    # Kognitive Injektoren
    injector,    # process(), check_between(), tool_reminder(), status(), toggle()

    # Hook-Framework
    hooks,       # on(), off(), emit(), status(), list_events()

    # Plugin-API (Dynamische Erweiterung)
    plugins,     # register_tool(), register_hook(), register_handler(), load_plugin()

    # Raw-Zugriff (beliebiger Handler)
    app,         # app().execute("handler", "operation", ["args"])
)
```
    # Plugin-API (Dynamische Erweiterung)
    plugins,     # register_tool(), register_hook(), register_handler(), load_plugin()

    # Raw-Zugriff (beliebiger Handler)
    app,         # app().execute("handler", "operation", ["args"])
)
```

##### Когда что использовать

| Ситуация | Рекомендация |
|-----------|------------|
| LLM-сессия (рекомендуется) | Смешанный режим: `session.startup()` + API |
| Быстрый одиночный запрос | Режим библиотеки: напрямую `task.list()` |
| Человек за терминалом | Режим сессии: `python bach.py --startup` |
| Чтение файлов, поиск по коду | Напрямую (Glob/Grep/Read) |
| Обработчик отсутствует в bach_api | `app().execute("handler", "op", ["args"])` |

**Архитектура:** `core/registry.py` автоматически распознаёт 113+ обработчиков (Auto-Discovery). Новым обработчикам нужен только `.py`-файл в `hub/` -- никакого ручного маппинга. Горячая перезагрузка: `app().reload_registry()`

#### Типы компонентов

| Тип | Папка | Характеристика |
|-----|--------|----------------|
| **Agent** | `agents/<name>/` | Оркестрирует экспертов, собственная папка |
| **Expert** | `agents/_experts/<name>/` | Глубокие предметные знания, собственная папка |
| **Service** | `hub/_services/<name>/` | Общего назначения, рядом с обработчиками, собственная папка |
| **Protocol** | `skills/workflows/` | 1 файл = 1 протокол (ранее Workflow), подпапки по категориям разрешены |
| **Connector** | `connectors/` | Внешние подключения (MCP, APIs) |
| **Tool (allg.)** | `tools/` | Многоразовый |
| **Tool (spez.)** | В папке навыка | Только для этого навыка |

#### Источники навыков и безопасность

| Класс | Источники | Порядок действий |
|--------|---------|----------|
| **Золотой стандарт** | Написано самостоятельно | Лучшая интеграция |
| **Надёжные** | anthropics/skills, anthropics/claude-cookbooks | После проверки переносимы 1:1 |
| **Ненадёжные** | Прочие GitHub-репозитории | ТОЛЬКО писать заново |
| **Чёрный список** | `data/skill_blacklist.json` | ЗАПРЕЩЕНО |

---

## ПРОЦЕДУРА ЗАПУСКА [B/C]: (1) → (2) → (3) → (4) → (5) → (6)

*Только в режимах B (смешанный) и C (сессия). Режим A пропускает этот раздел.*

---

### (1) Запусти Bach сейчас [B/C]

**Режим C (сессия/CLI):**

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
```

**Режим B (смешанный/API -- рекомендуется):**

```python
from bach_api import session
session.startup(partner="claude", mode="silent")
```

**Для Gemini:**

```python
# Modus B (API)
session.startup(partner="gemini", mode="silent")
# Modus C (CLI)
# python bach.py --startup --partner=gemini --mode=silent --watch
```

---

### (2) СИСТЕМА: Загрузи свои системные знания [B/C]

```bash
bach help cli
bach help bach_info
bach help features
bach help naming
bach help guidelines
bach help architecture
# --> bach help injectors
```

Или через API: `help.run("cli")`, `help.run("features")` и т.д.

#### Обнаружение обработчиков и поиск

У BACH 113+ обработчиков в `hub/`. **Каждый обработчик — это CLI-команда.** Чтобы найти обработчики, инструменты, навыки или темы справки:

```bash
# Fuzzy-Suche in Help-Themen (187+ Themen, Fuzzy-Match!)
bach help <suchbegriff>           # z.B. bach help web → schlaegt web_scrape, web_parse vor

# Handler auflisten
bach help list                    # Alle 187+ Help-Themen
bach help cli                     # CLI-Befehlsuebersicht

# Tools durchsuchen
bach tools list                   # Alle Python-Tools
bach tools search <keyword>       # Volltextsuche in Tool-Namen und -Inhalten

# Skills & Agents durchsuchen
bach skills list                  # Alle Skills in der DB
bach skills search <keyword>      # Skills nach Keyword filtern
bach agent list                   # Alle Agenten

# Beliebigen Handler direkt aufrufen
bach <handler-name> <operation>   # z.B. bach web-scrape get <url>
```

**Важно:** Если ты не знаешь, какой обработчик существует, используй `bach help <suchbegriff>` -- нечёткий поиск предложит подходящие темы даже при неточных терминах.

#### Файлы для ознакомления

- `system/CHANGELOG.md` - история версий
- `system/ROADMAP.md` - запланированные функции и обзор архитектуры

#### Корневые документы (генерируются из БД, обновляются при `bach --shutdown`)

- `AGENTS.md` - все босс-агенты и эксперты со статусом и путями
- `PARTNERS.md` - LLM-партнёры и делегирование
- `SKILLS.md` - индекс навыков
- `WORKFLOWS.md` - индекс протоколов
- `CHAINS.md` - цепочки инструментов
- `USECASES.md` - сценарии применения
- `USER.md` - профиль пользователя
- `MEMORY.md` - снимок памяти
- `BACH_HELP_REFERENCE.md` - полный справочник Help

#### Основные принципы

- **BACH как организм**: Connectors/Bridge — это **чувства и голос** (восприятие + коммуникация с внешним миром). LLM — это **разум** (мышление, понимание, решение). База данных и текстовые файлы — это **память**. GUI — это **лицо**. API, CLI, инструменты, агенты, навыки и рабочие процессы — это **руки** (потенциал действия).
- **Handler First**: Каждая функция как обработчик в `hub/` -- автоматически доступна через CLI **и** API
- **API в приоритете**: LLM используют `bach_api` вместо CLI. Люди используют CLI или GUI.
- **Системно**: Переиспользуемо для любого пользователя
- **dist_type**: 0=USER (персонально), 1=TEMPLATE (настраиваемо), 2=CORE (система)
- **Идемпотентно**: Импорты повторяемы без дубликатов
- **Проверка версии**: Всегда использовать новейшую версию

> **КЛЮЧЕВОЙ ПРИНЦИП:** BACH разрабатывается НЕ в первую очередь для отдельного пользователя, а как переиспользуемая система.

#### Принципы работы

Шесть базовых правил для всех партнёров BACH (LLM, агенты, эксперты):

1. **Собственные ресурсы в первую очередь** — Проверь память, Wiki, инструменты и БД, прежде чем спрашивать пользователя
2. **Результаты важнее процесса** — Значение имеет результат, а не метод
3. **Действовать, а не анонсировать** — Не объясняй, что ты собираешься сделать, просто сделай это
4. **Иметь мнение** — Ты можешь возражать и вносить собственные предложения
5. **Оставаться компактным** — Системные промпты менее 1000 токенов, инъекции держать краткими
6. **Сохранять знания** — Записывай выводы в память, прежде чем контекст будет потерян

**Партнёр-специфичные инструкции:**
- **Claude**: Прочитай `CLAUDE.md` в корневом каталоге (правило Knowledge Capture, интеграция)
- **Gemini**: Прочитай `GEMINI.md` в корневом каталоге (правило Knowledge Capture, интеграция)
- **Ollama**: Прочитай `OLLAMA.md` в корневом каталоге (правило Knowledge Capture, интеграция)

Эти файлы содержат детальные правила Knowledge Capture и партнёр-специфичные настройки.

#### Схема базы данных (138 таблиц в bach.db)

| # | Область | Важнейшие таблицы |
|---|---------|---------------------|
| 1 | System | `system_identity`, `system_config`, `instance_identity` |
| 2 | Tasks | `tasks` |
| 3 | Memory | `memory_working`, `memory_facts`, `memory_lessons`, `memory_sessions` |
| 4 | Tools | `tools` (550+ записей) |
| 5 | Skills | `skills` (1870+ записей) |
| 6 | Agents | `bach_agents`, `bach_experts`, `agent_synergies` |
| 7 | Files | `files_truth`, `files_trash`, `dist_files` |
| 8 | Automation | `automation_triggers`, `automation_routines`, `automation_injectors` |
| 9 | Monitoring | `monitor_tokens`, `monitor_success`, `monitor_processes`, `monitor_pricing` |
| 10 | Connections | `connections`, `connector_messages`, `partner_presence` |
| 11 | Languages | `languages_config`, `languages_translations` |
| 12 | Distribution | `distribution_manifest`, `dist_type_defaults`, `releases`, `snapshots` |
| 13 | Wiki | `wiki` (87 статей) |
| 14 | Usecases | `usecases`, `toolchains` |

Полная схема: `system/data/schema/schema.sql` (138 таблиц + Views + FTS)

---

### ОБЩАЯ АРХИТЕКТУРА BACH v2.6

```text
  +=====================================================================+
  |                             USER-INTERFACES                         |
  |  +-----------+  +-----------+  +-----------+  +-------------------+ |
  |  |    CLI    |  | Lib-API   |  |    GUI    |  |  MCP v2.2 (IDE)   | |
  |  |  bach.py  |  | bach_api  |  | server.py |  |  mcp_server.py   | |
  |  +-----+-----+  +-----+-----+  +-----+-----+  +--------+--------+ |
  +========|==============|==============|==================|===========+
           |              |              |                  |
  +========v==============v==============v==================v===========+
  |                    CORE LAYER (core/*.py)                           |
  |  app.py → registry.py → Auto-Discovery von 75+ Handlern            |
  |  base.py (BaseHandler) | db.py (Schema-First) | hooks.py (Events)  |
  +=========|==============|=======================================+====+
            |              |                                       |
  +==========v==============v=======================================v===+
  |                          HUB LAYER (hub/*.py)                       |
  |  System: startup, shutdown, status, backup, tokens, inject, hooks   |
  |  Domain: steuer, abo, haushalt, gesundheit, contact, calendar, email|
  |  Data: task, memory, db, session, logs, wiki, docs, inbox           |
  |  Multi-AI: agents, partner, daemon, ollama, ati                     |
  |  Extension: skills (create/reload), hooks (status/events/log/test)  |
  +====|======================|======================|=================+
       |                      |                      |
  +----v------------------+   |   +------------------v-----------------+
  |   AGENTS LAYER        |   |   |   CONNECTORS & PARTNERS           |
  |                       |   |   |                                    |
  | agents/ (Ordner)      |   |   | connectors/ (MCP, APIs)           |
  | agents/_experts/      |   |   | partners/ (Multi-LLM-Konfig)      |
  +-----------------------+   |   +------------------------------------+
                              |
  +---------------------------v----------------------------------------+
  |   SKILLS & TOOLS LAYER                     |    DATA LAYER         |
  |                                            |                       |
  | skills/workflows/ (ehem. _workflows)      | bach.db (Unified)     |
  | skills/_templates/ (Standard-Templates)    | Dateisystem            |
  | hub/_services/ (Ordner)                    | inbox/outbox/          |
  | tools/*.py | c_*.py | injectors.py         |                       |
  +--------------------------------------------+-----------------------+
              |
  +-----------v-----------+
  | SELF-EXTENSION LAYER  |
  |                       |
  | skills create (6 Typ) |
  | skills reload (Hot)   |
  | hooks.on/emit (14 Ev) |
  | Plugin-API (geplant)  |
  +-----------------------+
```

---

### (3) ПАМЯТЬ: Загрузи свой эпизодический контекст [B/C]

```bash
bach help memory
bach help lessons
bach help consolidation
```

#### Когнитивная модель памяти (5 типов)

| Тип | Соответствие | Функция | Команда |
|-----|--------------|----------|--------|
| **Working** | Кратковременная | Текущая сессия | `bach mem write` |
| **Episodic** | Дневник | Завершённые сессии | `bach --memory session` |
| **Semantic** | Знания о мире | Факты, Wiki, Help | `bach --memory fact "key:value"` |
| **Procedural** | Умение | Tools, Skills, Workflows | `bach help tools` |
| **Associative** | Связывание | Консолидация, триггеры | `bach consolidate` |

---

### (4) ВОЗМОЖНОСТИ: Загрузи знания о своих возможностях [B/C]

```bash
bach help skills
bach help tools
```

**Иерархия:**

- **Агенты**: оркестрируют несколько областей, собственная папка
- **Эксперты**: глубокое знание домена, собственная папка
- **Сервисы**: общие службы, близки к обработчикам

**Важные каталоги:**

- `system/agents/` - агенты (каждый в своей папке)
- `system/agents/_experts/` - эксперты (каждый в своей папке)
- `system/hub/_services/` - сервисы (каждый в своей папке)

- `system/skills/workflows/` - Протоколы (отдельные файлы, бывш. _workflows)
- `system/skills/_templates/` - Стандартные шаблоны
- `system/connectors/` - Внешние подключения (MCP, APIs)
- `system/partners/` - Конфигурации мульти-LLM

---

### (5) ПЛАНИРОВАНИЕ ЗАДАЧ [B/C]

#### (5.1) Распознавание пожеланий пользователя

- Распознавай конкретные пожелания пользователя, названные в промпте, как задачи
- Фиксируй задачи и планируй свои действия
- Если конкретных пожеланий нет, переходи к 5.2

#### (5.2) Загрузка контекста задач

```python
# API (предпочтительно)
from bach_api import task
task.list()
```

```bash
# CLI
bach help tasks
bach task list
```

- Выбирай задачи самостоятельно. **С 2026-10-25: приём и сдача идут через Lease, см. раздел «КАК АГЕНТ ОБРАБАТЫВАЕТ ОТКРЫТЫЕ ЗАДАЧИ» в самом начале.** `bach task claim` устарел (Claim без Fence/Lease-ID).

---

### (6) ПРОЦЕДУРНЫЕ ЗНАНИЯ И ПРОТОКОЛЫ [C]

*В режиме B опционально -- протоколы это документация, не код.*

```bash
bach help protocol
bach help between-tasks
bach help practices
```

**Путь:** `system/skills/workflows/`

---

## ТЕМАТИЧЕСКИЕ ПАКЕТЫ (читать по необходимости -- все режимы)

### ТЕМА: Сотрудничество (ПАКЕТ: КОМАНДНАЯ РАБОТА)

*Когда читать:* Ты работаешь с партнёрами в системе.

```bash
bach help partners
bach help multi_llm
bach help delegate
```

**Чат-система:**

```python
# API
from bach_api import msg, partner
msg.send("gemini", "Bitte recherchiere...")
msg.unread()
partner.delegate("Recherche", "--to=gemini")
```

```bash
# CLI
bach msg send claude "Text"
bach msg unread
```

**Система блокировок:**

```bash
bach llm lock <datei>           # Lock ДО записи
bach llm unlock [datei]         # Снять Lock
bach llm status                 # У кого какие Locks?
```

---

### ТЕМА: Решение проблем (ПАКЕТ: РЕШЕНИЕ ПРОБЛЕМ)

*Когда читать:* Ты сталкиваешься с проблемами или блокировками.

```bash
bach help operatoren
bach help planning
bach help problemloesung
```

bach help strategien
```

---

### ТЕМА: Задачи по кодингу (ПАКЕТ: CODING)

*Когда читать:* Ты работаешь над кодом или исправляешь баги.

```bash
bach help ati
bach help coding
bach help bugfix
```

---

### ТЕМА: Обслуживание (ПАКЕТ: ОБСЛУЖИВАНИЕ)

*Когда читать:* Ты выполняешь задачи по обслуживанию.

```bash
bach help maintain
bach help wartung
bach help recurring
bach daemon status
```

---

### ТЕМА: Управление файлами (ПАКЕТ: УПРАВЛЕНИЕ ФАЙЛАМИ)

*Когда читать:* Ты выполняешь файловые операции.

```bash
bach help trash
bach help migrate
bach help distribution
```

---

### ТЕМА: Чтение веб-страниц (ПАКЕТ: WEB)

*Когда читать:* Тебе нужно запросить веб-страницы, извлечь содержимое или выполнить веб-анализ.

```bash
bach help web_parse
bach help web_scrape
```

**Два обработчика для разных целей:**

| Обработчик | Команда | Назначение | Техника |
|---------|--------|-------|---------|
| `web_parse` | `bach web-parse url/clean <url>` | **Извлечение содержимого** (основной контент как Markdown) | trafilatura/html2text |
| `web_scrape` | `bach web-scrape get/links/forms/headers <url>` | **Анализ структуры** (ссылки, формы, headers) | requests + Regex |

**Рекомендация:** Для текстового содержимого `web-parse clean <url>` (удаляет Nav/Header/Footer). Для сырых данных или списков ссылок `web-scrape`. Оба используют HTTP-запросы -- страницы, рендерящиеся через JS, отдают только серверную часть HTML.

**Навык:** `skills/workflows/webseiten-lesen.md` -- Подробный порядок действий с деревом решений.

---

### ТЕМА: Саморасширение (ПАКЕТ: SELF-EXTENSION) [B/C]

*Когда читать:* Тебе не хватает какой-то способности или ты хочешь расширить BACH.

```bash
bach help self-extension
bach help hooks
bach help skills
```

**Создание новых способностей (5 типов):**

```bash
bach skills create voice-processor --type tool       # Scaffold нового инструмента
bach skills create email-agent --type agent           # Scaffold нового агента
bach skills create tax-expert --type expert            # Scaffold нового эксперта
bach skills create api-gateway --type handler          # Scaffold новой CLI-команды
bach skills create data-sync --type service            # Scaffold нового сервиса
```

**После создания: Hot-Reload (без перезапуска!)**

```bash
bach skills reload
```

**Hook-фреймворк (14 событий):**

```python
from core.hooks import hooks

# Eigene Logik an System-Events haengen
hooks.on('after_task_create', meine_funktion, name='mein_plugin')
hooks.on('after_startup', startup_check, name='mein_plugin')

# Events anzeigen
# bach hooks events
```

**Plugin-API (динамическое расширение во время выполнения):**

```python
from bach_api import plugins

# Tool registrieren (sofort nutzbar)
plugins.register_tool("mein_tool", meine_funktion, "Beschreibung")

# Hook registrieren (Event abonnieren)
plugins.register_hook("after_task_done", callback, plugin="mein-plugin")

# Handler registrieren (neuer CLI-Befehl!)
plugins.register_handler("mein_cmd", MeinHandler)

# Plugin aus Manifest laden
plugins.load_plugin("plugins/mein-plugin/plugin.json")
```

```bash
# CLI: Plugin-Verwaltung
bach plugins list          # Geladene Plugins
bach plugins create name   # Plugin scaffolden
bach plugins load pfad     # Plugin laden
bach plugins unload name   # Plugin entladen
```

**Цикл саморасширения (Self-Extension Loop):**
1. ОБНАРУЖИТЬ → определить недостающую возможность
2. СОЗДАТЬ → `bach skills create <name> --type <typ>` или `plugins.register_tool()`
3. РЕАЛИЗОВАТЬ → написать код
4. ЗАРЕГИСТРИРОВАТЬ → `bach skills reload` или `plugins.load_plugin()`
5. ИСПОЛЬЗОВАТЬ → доступно сразу
6. ОТРЕФЛЕКСИРОВАТЬ → `bach lesson add "Was gelernt"`

---

### ТЕМА: Shutdown (ПАКЕТ: SHUTDOWN) [B/C]

*Когда читать:* сессия завершается. Актуально только в режимах B и C.

**Режим B (API — рекомендуется):**
```python
from bach_api import session, memory
memory.session("THEMA: Was gemacht. NAECHSTE: Was kommt.", session_id="SESSION_ID", partner="claude")
session.shutdown("Zusammenfassung", partner="claude", session_id="SESSION_ID")
# Oder schnell:
session.shutdown_quick("Kurze Notiz", partner="claude", session_id="SESSION_ID")
```

`SESSION_ID` — это собственный ID из отчёта о запуске. При нескольких открытых
сессиях всегда указывайте ID и партнёра; неоднозначный выбор отклоняется.

**Режим C (CLI):**
```bash
bach help shutdown
bach --memory session "THEMA: Was gemacht. NAECHSTE: Was kommt."
bach --shutdown
```

---

## ХУКИ И ИНЪЕКТОРЫ

### Hook-фреймворк (техническая система событий)

Хуки позволяют привязать собственную логику к 14 событиям жизненного цикла — без изменения существующего кода.

```python
from core.hooks import hooks

# Listener registrieren
hooks.on('after_task_done', auto_backup, name='backup_plugin')
hooks.on('after_startup', health_check, priority=10, name='health')

# CLI
# bach hooks status    → Zeigt alle Hooks
# bach hooks events    → Listet alle 14 Events
# bach hooks log       → Letzte Ausfuehrungen
```

**События:** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> Хуки — это **технический фреймворк**. Инъекторы — это **когнитивная подсистема**. Они работают независимо друг от друга.

---

### Инъекторы (когнитивная оркестрация)

6 инъекторов имитируют **мышление и ассоциации** как **центральная исполнительная функция**. Доступны через CLI и API.

| Инъектор | Подфункции | Совместим с API |
|----------|----------------|:---:|
| **strategy_injector** | Метакогниция, помощь в решениях, анализ ошибок | Да |
| **context_injector** | Рекомендация инструментов, обращение к памяти, анализ требований | Частично* |
| **between_injector** | Контроль качества, переход между задачами, валидация результата | Да |
| **time_injector** | Чувство времени (Timebeat), проверка сообщений | Да |
| **tool_injector** | Напоминание об инструментах, предупреждение о дубликатах | Да |
| **task_assigner** | Автоназначение, декомпозиция задач | Да |

*\*context_injector содержит CLI-команды как подсказки. В режиме API фильтруется.*

**CLI:**
```bash
bach --inject status            # Status aller Injektoren
bach --inject toggle <name>     # An/Aus schalten
```

**API:**
```python
from bach_api import injector

injector.process("text")              # Alle Injektoren auf Text anwenden
injector.check_between("task done")   # Quality-Check nach Task-Abschluss
injector.tool_reminder()              # Verfuegbare Tools (einmalig)
injector.assign_task()                # Naechste Aufgabe automatisch zuweisen
injector.time_check()                 # Uhrzeit + Nachrichten
injector.status()                     # Status aller Injektoren
injector.toggle("strategy_injector")  # Einzeln an/aus
injector.set_mode("api")              # CLI-Hinweise aus Kontext filtern
```

---

## CHANGELOG

### v3.10.0 (2026-10-25)

- **Вход для агентов**: новый раздел в самом начале «КАК АГЕНТ ОБРАБАТЫВАЕТ ОТКРЫТЫЕ ЗАДАЧИ» (запуск, выбор задачи, получение lease, worktree, тесты, PR, сдача результата, следующая задача; границы; известные пробелы). Цель: агент (Claude, Codex, Kimi, Gemini) запускается самостоятельно по одному этому файлу.
- **Помечено как устаревшее**: `bach task claim` и (5.2) «назначьте её себе»; цифры и обзор архитектуры ниже нового раздела относятся к состоянию 2026-03-12 и не пересчитывались.
- Ничего не удалено. Режимы A, B, C без изменений.

### v3.8.0 (2026-03-12)

- **Обнаружение обработчиков**: новый раздел в секции (2) — `bach help <suchbegriff>` документирован как основной механизм обнаружения для 109+ обработчиков
- **Поисковая справка**: `bach help list`, `bach tools search`, `bach skills search` как точки входа для поиска
- **Тематический пакет WEB**: новый пакет со ссылкой на обработчики `web_parse` и `web_scrape`
- **Навык `webseiten-lesen`**: новый workflow-навык с деревом решений для извлечения веб-контента
- **Документация**: обработчики теперь находятся в SKILL.md, а не только через CLI

### v3.2.0-butternut (2026-02-28)

- **Agent-CLI**: `AgentLauncherHandler` — `bach agent start/stop/list` для прямого управления агентами
- **Prompt-система**: `PromptHandler` — `bach prompt list/add/edit/show/board-create` для централизованного управления промптами
- **Расширения SharedMemory**: `current-task`, `generate-context`, `conflict-resolution`, `decay`, `changes-since`
- **USMC Bridge**: United Shared Memory Client (`hub/_services/usmc_bridge.py`)
- **Цепочки llmauto**: промпты Claude как шаги цепочки + разрешение `bach://`-URL
- **Планировщик**: `job_type='chain'` + переименование `daemon_jobs` → `scheduler_jobs`
- **Новые API-модули**: `agent`, `prompt` в `bach_api`
- **Портирования**: SharedMemoryHandler, ApiProberHandler, N8nManagerHandler, UserSyncHandler, Stigmergy-Service
- **Таблицы**: 4 новые таблицы БД: `prompt_templates`, `prompt_versions`, `prompt_boards`, `prompt_board_items`
- **109+ обработчиков** (ранее: 75+)

### v2.6.0 (2026-02-13)

- **Реструктуризация каталогов**: чёткое разделение Agents, Skills, Connectors и Partners
  - `skills/_agents/` → `agents/` (верхний уровень внутри system/)
  - `skills/_experts/` → `agents/_experts/` (эксперты принадлежат агентам)
  - `skills/_workflows/` → `skills/workflows/` (workflows теперь называются protocols)
  - `skills/_connectors/` → `connectors/` (верхний уровень внутри system/)
  - `skills/_partners/` → `partners/` (верхний уровень внутри system/)
- **PathHealer**: автоматическая коррекция путей во всех затронутых файлах
- **Тип компонента `protocol`**: заменяет `workflow` в иерархии типов
- **Тип компонента `connector`**: новый для внешних подключений (MCP, APIs)
- **Схема архитектуры**: AGENTS LAYER и CONNECTORS & PARTNERS как отдельные секции
- **SKILL.md v2.6**: все ссылки, таблицы и схемы приведены к новой структуре

### v2.5.0 (2026-02-13)

- **Система саморасширения**: AI-партнёры могут добавлять себе новые способности
  - `bach skills create <name> --type <typ>` (5 типов: tool, agent, expert, handler, service)
  - `bach skills reload` (hot-reload: реестр + инструменты + БД навыков)
  - Цикл саморасширения: ОБНАРУЖИТЬ → СОЗДАТЬ → ЗАРЕГИСТРИРОВАТЬ → ИСПОЛЬЗОВАТЬ → ОТРЕФЛЕКСИРОВАТЬ
- **Hook-фреймворк**: расширяемая система событий с 14 событиями жизненного цикла
  - `core/hooks.py` — синглтон HookRegistry, приоритеты, журнал событий
  - `hub/hooks.py` — CLI: `bach hooks status/events/log/test`
  - Интеграция в: Startup, Shutdown, Task, Memory, Lesson, Skills, App

  - Хуки != инъекторы: технический фреймворк vs. когнитивная подсистема
- **Обработчик Email**: Gmail API с Draft-Safety (send, draft, confirm, cancel)
- **Горячая перезагрузка реестра**: `app().reload_registry()` без перезапуска
- **Правило (f) Self-Extension**: «Не хватает возможности — создай её себе сам!»
- **Документация**: hooks.txt, self-extension.txt, cli.txt, skills.txt, ROADMAP.md

### v2.4.0 (2026-02-08)

- **MCP Server v2.2**: 23 инструмента, 8 ресурсов, 3 промпта — все три примитива MCP
- **Email-адаптер**: SMTP_SSL в notify.py (перенесено из BachForelle)
- **BachFliege + BachForelle**: проанализированы и заархивированы (`docs/_archive/con5_BACHFLIEGE_BACHFORELLE_ARCHIV.md`)

### v2.3.0 (2026-02-06)

- **Свод правил полностью переработан**: ВСЕГДА → вид доступа → специфично для режима
- **Три режима**: A (Библиотека), B (Смешанный), C (Сессия) с тегами [B], [C], [B/C]
- **Принцип соразработки**: «Использование BACH — это соразработка» как ключевое правило
- **bach_api.py расширен**: session, partner, logs, msg, tools, help, injector
- **14 API-модулей**: полный программный доступ ко всем обработчикам
- **Инъекторы через API**: все 6 инъекторов доступны через библиотеку + фильтр CLI
- **Жизненный цикл сессии через API**: `session.startup()` / `session.shutdown()`
- Схема архитектуры обновлена (Core Layer + bach_api)
- Все разделы снабжены маркировкой режима

### v2.2.0 (2026-02-06)

- Задокументированы два пути доступа (CLI + Library-API)
- Базовые модули bach_api.py: task, memory, backup, steuer, lesson, status

### v2.1.0 (2026-02-04)

- Интегрирована архитектура навыков v2.0
- Введён принцип проверки версии
- Задокументирован стандартный заголовок
- Добавлена классификация источников навыков
- Задокументированы частичные функции инъекторов

### v2.0.2 (2026-01-01)

- Начальная версия

---

**BACH Skill-Architektur v2.0**