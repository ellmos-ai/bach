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
- **Нативного короткого ярлыка пока нет** `bach task take|renew|submit|return|block`; он запланирован (`ANFORDERUNGEN-DETAIL.md`, раздел „Tasksystem, Leases und Locks“). Постоянный нативный путь сегодня — Python-SDK `TaskLeaseClient` (выше); `bach_api.task` даёт только `lease_acquire`/`lease_read`/`lease_renew`/`lease_release`/`lease_decompose`, без списка кандидатов и без `submit_result`.
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
<!-- T2619-CONT -->