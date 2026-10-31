---
name: bach
version: 3.10.0
type: skill
author: BACH Team
created: 2025-12-01
updated: 2026-10-25
anthropic_compatible: true

description: >
  BACH的中央管理系统。这是唯一需要上传到Claude的技能。
  它了解所有本地技能，
  执行版本检查，并在需要时加载更新的本地版本。
  每次使用技能时自动激活。
---

# 作为处理开放任务的代理（面向 Claude、Codex、Kimi、Gemini 的入口）

> **自 v3.10.0（2026-10-25）起新增。** 如果你的任务是「阅读 SKILL.md 并处理开放任务」，则**首先适用本节**。本文件中的其余内容均为参考资料，仅在需要时阅读。
> 详细、可复制的版本：`Desktop\OCEAN\EINWEISUNG-EXTERNE-WORKER.md`（Lukas 的 OneDrive，不在仓库中）。租约合同：`docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md`，客户端：`docs/architecture/TASKDB-SALT-LEASE-CLIENTS-v1.md`。本地 Worker 骨架（Buddha）：`docs/architecture/LOKALER-WORKER-HARNESS.md`（PR #520）。

**一句话流程：** 启动 → 选择任务 → **先认领，再工作** → 专属工作树 → 测试 → PR → 提交结果 → 下一个任务。除非 Lukas 明确指示停止，否则不要停止。

### 1. 启动与模式
- 通过提供的 SSH 访问连接 Mac Studio；不要自行设置访问凭据。项目位于 `$BACH_ROOT`（Mac Studio 上为 `~/services/bach`），Python 使用其 venv。阅读 `AGENTS.md` 以及你所工作的子项目的指示。
- **模式B（混合）** 是主动协作代理的常态。如果你只处理任务、不将 BACH 作为会话使用，**模式A（库）** 就已足够：下面的租约路径通过 lead 服务运行，无需启动会话。模式C（会话）仅在明确要求时使用。
- 在第一个任务之前阅读当前计划 `Desktop\OCEAN\AKTUELLER-PLAN.md` 和 `MODUL-ZUORDNUNG.md`（构建位置）。
### 2. 查找空闲任务
- **原生方式：** `TaskLeaseClient.task_candidates(limit=100, offset=…)`（读取所有页面，而不只第一页），随后用 `task_snapshot(task_id)` 获取完整描述。`bach task list` 仅用于查看同样的任务。
- **选择规则：**
  1. 只选择依赖已满足、没有他人有效租约、且你的工具能够胜任的任务。
  2. **优先处理最高优先级**（P0 先于 P1，P1 先于 P2）。优先级相同时，先做符合议程重点的（截至 2026-10-25：Förderplaner、代理模板/控制、Running & Living、GUI 改造、Worker 可靠性；以 `AKTUELLER-PLAN.md` 为准）。
  3. **禁止 `OLLAMA` 任务。** 这是本地 Worker（Buddha、Ollama Cloud、OpenRouter）的后台队列。面向 `USER`/`HUMAN`/`LUKAS` 的任务以及他人预留的任务同样不要动。`BACH` 表示可共同处理。不要虚构额外的槽位义务。
  4. 其他作者的评审与检验任务明确适合认领。
  5. 若任务依赖未决的用户决定或不符合你的能力：记下问题或原因（任务备注）并选下一个。绝不要为了能认领任务而更改规则或防护门。
### 3. 开始工作前先认领
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
- 工作者ID **`<agent>@<host>`**、自己的Request-ID和世代绝不要与其他工作者共享。仅在获得确认许可后才开始工作。
- 如果 `renew` 被拒绝、租约已过期或fence已变更：**立即停止对该任务的所有写入操作。** 在内容变更得到确认后，更新已保存的任务版本。
- **不要使用：** `bach task claim`（无fence/租约ID的旧式claim）和 `~/compute/luna-gui/task_tool.py claim`（仅设置 `assigned_to`，无租约）。两者都不是原生认领，无法防止重复处理。`task_tool.py note`（向描述追加文本）和 `list` 可作为临时手段使用，直到出现原生替代方案。
- 签名必须从 `system/hub/_services/task_lease_client.py` 读取，而不是以本示例为准。
### 4. 工作
- **每个任务使用独立工作树**，基于 `origin/main`：`git worktree add ~/services/bach-worktrees/<zweig> -b <zweig> origin/main`。分支名 `<agent>/<task>-<kurz>-<datum>`。主检出 `~/services/bach` 已被占用（他人的未提交更改）：不在那里工作、测量或构建。
- **构建位置：** 新的业务逻辑应按照 `MODUL-ZUORDNUNG.md` 放入对应的 Ocean 模块仓库，而不是 BACH 核心。
- 按照任务的验收标准检查结果。运行所改动区域的测试，只主张你能证明的内容。德语最终用户文本使用真实的变元音字符。
- 提交前：密钥扫描、阅读 Diff、只提交自己的文件（不做汇总提交）。
- 推送分支，**创建针对 `main` 的 PR** 并在任务中记录。提交、推送、PR、合并、部署和业务验收逐项单独列明。分支尚不等于已交付状态。

### 5. 提交结果
- **完成：** `client.submit_result(task_id, lease_id=…, fence=…, task_version=…, generation="<neue-Generation>", result="<Text>")`。`result` 是 **最多 3000 字符** 的具体文本（达成的标准、变更、PR 链接、提交 SHA、真实检查结果、局限）；纯完成声明（„done“）会被拒绝。提交后任务转为 `review` 并释放租约。随后读取 `task_result_snapshot(task_id)` 并核验结果 ID/哈希；仅聊天文本不构成提交。
- **部分状态或受阻：** 推送 WIP 分支，然后 `client.release(task_id, lease_id=…, fence=…, outcome="return" | "blocked", note="<Branch, SHA, nächster Schritt>")`。不做笼统的 `done`，等待人类时不人为延长租约。（`complete=false` 只存在于本地 Buddha 运行的任务工具中（见 Harness 文档），SDK 中没有。）
- 之后 **立即处理下一个任务**（步骤 2）。如果当前没有可接的任务：报告有依据的原因，稍等片刻，再次检查。不要自行结束你的委托。
- 每个任务的简短报告：任务 ID、工作、证据、提交/远程 SHA、PR、回读的任务/结果/租约状态。对自己工作的 Review 须标注为不独立。
### 6. 边界限制（始终有效）
- **不合并**、不推送到 `main`、不部署、不重启服务、不更改 Worker 配置、不停止他人的任务/Worker、不启动 `.SYNC` 运行。合并须经二次审查，部署须在审查之后。
- **绝不直接写入 `bach.db`**，不做自己的 SQL 修改，不以复制的数据库作为权威。始终只用原生 API/SDK。
- **不得在 `OneDrive\.TOPICS` 或 `.TOPICS\.AI` 中加锁**：它们会在 Mac 上停止后台 Worker Buddha 及一切部署。锁只允许用于自己的工作树路径。
- 他人的活动租约、其他代理的进行中工作以及已锁定路径始终受保护。绝不输出或提交令牌和访问凭证。

### 7. 已知缺口（截至 2026-10-25）
- **尚无原生短命令** `bach task take|renew|submit|return|block`；已在计划中（`TASKDB-SALT-LEASE-VERTRAG-v1.md` 的 „Tasksystem, Leases und Locks“ 章节）。目前持久的原生途径是 Python-SDK `TaskLeaseClient`（见上文）；`bach_api.task` 仅提供 `lease_acquire`/`lease_read`/`lease_renew`/`lease_release`/`lease_decompose`，没有候选列表，也没有 `submit_result`。
- `task_tool.py` 位于仓库之外（`~/compute/luna-gui/`）；其 `list` 直接读取 `bach.db`（仅只读），其 `claim` 不是租约。
- 入职说明、计划及 `MODUL-ZUORDNUNG.md` 位于 Lukas 的 OneDrive 桌面，而非仓库中；在 Mac 上运行的代理若无副本便无法访问它们。
- 外部成果的来源契约：#2339 已被原生验收，Main 合并与发布尚未进行（PR #507）。在此之前，成果须如实按已提交或部分状态处理。
> **关于文件其余内容的状态提示：** 本节以下内容最后一次在内容层面修订于 2026-03-12（v3.8.0）。其中的数字（处理器、表格、钩子、主题包）、架构概览 v2.6 以及任务规划（5）此后**未重新测量**；如有矛盾，以代码或实测为准。任务接管不再通过 `bach task claim` 进行，而是按上述方式执行。

---

# 版本提示

# 检查此技能是否存在更新的版本（本地或中央）

# 始终使用版本号最高的版本

# Versions-Check: bach skills version bach

# 欢迎使用 Bach

---

## 规则 - 指南 - 标准

---

### 始终（优先于其他一切）

**(1) 版本检查：** 如果存在多个版本的 SKILL.md（本地、中央），请比较版本号，必要时切换到最新版本并从那里继续阅读。
```bash
bach skills version bach   # Prueft ob aktuellere Version existiert
```

**(2) 操作系统检查：** 确认你在 Windows、Mac 还是 Linux 上运行。
- Windows：没有 `/dev/null`，也没有 `NUL:`。请省略输出或改用 `2>&1`。避免使用 `&&`，命令逐个执行
- 存在 nul 文件时：`python tools/c_nul_cleaner.py --dir <pfad> --delete`

---

### 之后：明确访问方式 / 会话模式

选择适合你情况的模式：

| 模式 | 适用场景 | 启动 | 访问 |
|-------|------|---------|--------|
| **A) 库** | 访客、只读、单个查询、将 BACH 作为工具 | 无启动 | `from bach_api import task; task.list()` |
| **B) 混合** | 应用户要求启动 BACH、积极参与 | API 启动 | `session.startup()` + API + `session.shutdown()` |
| **C) 会话** | 经典方式、自动启动、详细记录 | CLI 启动 | `python bach.py --startup --partner=claude` |

- 模式C可随时切换到B（用 API 代替 CLI）
- 模式B和C可随时切换到A（无会话的单个查询）
- 如有疑问：**模式B**（对 LLM 会话推荐）
---

### 在模式B和C下：主动使用的规则

**(1) 读写 -- 使用BACH就是共同开发：**

使用BACH的人，就是在共同开发BACH。每一次访问都是改进系统的机会。

- **(a) Handler First:** 每个功能都应作为Handler放在`hub/`中。Handler自动可通过CLI**和**API使用。不为不同的访问方式编写单独的代码。
- **(b) 填补缺口：** 如果缺少Handler、API模块、Skills、Tools、Workflows或其他组件，就创建它们。缺失的Handler优先级最高，因为它们是一切访问方式的基础。
- **(c) 欢迎自建：** 非常欢迎创建自己的Skills、Workflows、Tools、MCPs。处理已有内容时与User协商。
- **(d) Fix-or-Task:** 问题要么立即修正（小），要么作为任务放入Queue（大）。决定性标准：成本 vs. 收益。然后回到本职任务。
- **(e) Self-Healing:** 发现BACH中的错误（路径、命令、过时的引用、损坏的Import），立即修正并告知User。BACH通过其用户实现自我修复。
- **(f) Self-Extension:** 缺少什么能力，就自己补上！使用`bach skills create`为新的Tools、Handler、Agents、Experts或Services搭建骨架。运行`bach skills reload`后即可立即使用。参见：`bach help self-extension`

**(2) 执行启动步骤**（见下文）。阅读必读包，并按需（`-->`）阅读自愿引用。各包均带有模式标注：
- `[C]` → 仅在会话模式下阅读
- `[B]` → 仅在混合模式下阅读，在会话模式下跳过
- `[B/C]` → 在两种模式下都阅读
- 无标注 → 始终按需阅读

**(3) 按需阅读附加包**（主题包见下文）。

---
### 在模式A下：访客/工具使用规则

按需读取附加包。无需启动，也不预期关闭。

```python
from bach_api import task, memory, tools, steuer
task.list()         # Sofort nutzbar
tools.search("ocr") # Werkzeug finden
```

---

### 文档结构（导航图）

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

### 技能架构 v2.0（NEU）

#### 版本检查原则

**始终使用最新版本** — 无论是本地还是集中存放：

```bash
bach skills version <name>    # Prüfe Versionen
bach tools version <name>     # Prüfe Tool-Versionen
```

#### 技能结构：一个技能 = 一个文件夹

每个技能、代理、专家都在自己的文件夹中**完全自包含**：

```
agents/entwickler/
├── SKILL.md              # Definition mit Standard-Header
├── tool_xyz.py           # Spezifische Tools (flat)
├── protocol_abc.md       # Spezifische Protokolle (flat)
└── config.json           # Optional
```

**规则：**

- 少于5个文件：扁平结构（全部在根目录）
- >= 5个文件：允许子文件夹 `tools/`、`protocols/`
- **拿不准时，工具保留两份**（通用 + 技能专用）
- 导出后必须在没有BACH的情况下也能运行

#### 标准头（所有组件必填）

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

**模板：** `system/skills/_templates/TEMPLATE_*.md`

#### 扩展阶段

BACH 分为三个阶段：**USMC**（记忆核心）、**Rinnsal**（+ LLM 编排）、**BACH**（完整系统）。详情：[README.md](README.md#ausbaustufen)

#### 三种访问模式

BACH 提供**两条并行的访问路径**（CLI + 库 API），可组合成**三种模式**。两条路径使用相同的 Handler 和同一个 DB。

##### 模式 1：会话模式（CLI -- 传统）

通过命令行执行完整的 Startup/Shutdown 协议。适用于交互式终端会话。

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
# ... arbeiten ...
python bach.py --shutdown "Zusammenfassung"
```

##### 模式 2：库模式（API -- 轻量）

无需会话开销即可直接访问 Handler。适用于脚本、快速查询，或只需个别操作的 LLM。

```python
from bach_api import task, memory, steuer, partner, tools, injector

task.list()                              # Tasks abfragen
memory.write("Wichtige Notiz")           # Memory schreiben
steuer.status()                          # Steuer-Status
partner.list()                           # Partner auflisten
injector.process("ich bin blockiert")    # Kognitive Hilfe
```

##### 模式 3：混合模式（API 带会话生命周期）

通过 API 的完整 Startup/Shutdown。**推荐用于 LLM 会话** -- 将会话管理与便捷的 API 访问相结合。

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
##### 可用 API 模块

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

##### 何时使用哪种方式

| 场景 | 建议 |
|-----------|------------|
| LLM 会话（推荐） | 混合模式：`session.startup()` + API |
| 快速单次查询 | 库模式：直接 `task.list()` |
| 终端前的人类 | 会话模式：`python bach.py --startup` |
| 读取文件、搜索代码 | 直接（Glob/Grep/Read） |
| 处理器不在 bach_api 中 | `app().execute("handler", "op", ["args"])` |

**架构：** `core/registry.py` 自动识别 113+ 个处理器（自动发现）。新处理器只需在 `hub/` 里放一个 `.py` 文件 —— 无需手动映射。热重载：`app().reload_registry()`

#### 组件类型

| 类型 | 文件夹 | 特性 |
|-----|--------|----------------|
| **Agent** | `agents/<name>/` | 编排专家，独立文件夹 |
| **Expert** | `agents/_experts/<name>/` | 深厚的领域知识，独立文件夹 |
| **Service** | `hub/_services/<name>/` | 通用，贴近处理器，独立文件夹 |
| **Protocol** | `skills/workflows/` | 1 个文件 = 1 个协议（原 workflow），允许分类子文件夹 |
| **Connector** | `connectors/` | 外部接入（MCP、API） |
| **Tool（通用）** | `tools/` | 可复用 |
| **Tool（专用）** | 技能文件夹内 | 仅用于该技能 |

#### 技能来源与安全

| 类别 | 来源 | 处理方式 |
|--------|---------|----------|
| **黄金标准** | 自行编写 | 最佳集成 |
| **可靠** | anthropics/skills、anthropics/claude-cookbooks | 审查后可原样采用 |
| **不可靠** | 其他 GitHub 仓库 | 只能重写 |
| **黑名单** | `data/skill_blacklist.json` | 禁止使用 |

---

## 启动流程 [B/C]：(1) → (2) → (3) → (4) → (5) → (6)

*仅在模式 B（混合）和 C（会话）中。模式 A 跳过本节。*

---

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

**重要：** 如果你不知道存在哪个 Handler，请使用 `bach help <suchbegriff>` —— 模糊搜索会推荐合适的主题，即使术语不精确也能找到。

#### 用于查阅的文件

- `system/CHANGELOG.md` - 版本历史
- `system/ROADMAP.md` - 计划中的功能与架构概览

#### 根文档（从数据库生成，在 `bach --shutdown` 时更新）

- `AGENTS.md` - 所有 Boss-Agent 与专家及其状态和路径
- `PARTNERS.md` - LLM 伙伴与委派
- `SKILLS.md` - Skill 索引
- `WORKFLOWS.md` - 协议索引
- `CHAINS.md` - 工具链
- `USECASES.md` - 应用场景
- `USER.md` - 用户画像
- `MEMORY.md` - 记忆快照
- `BACH_HELP_REFERENCE.md` - 完整帮助参考

#### 核心原则

- **BACH 作为有机体**：Connector/Bridge 是**感官与声音**（对外界的感知与沟通）。LLM 是**理智**（思考、理解、决策）。数据库和文本文件是**记忆**。GUI 是**面孔**。API、CLI、工具、Agent、Skill 和工作流是**双手**（行动潜力）。
- **Handler First**：每项功能都作为 `hub/` 中的 Handler 实现——自动可经 CLI **和** API 访问
- **优先使用 API**：LLM 使用 `bach_api` 而非 CLI。人类使用 CLI 或 GUI。
- **系统性**：可复用于任何用户
- **dist_type**：0=USER（个人），1=TEMPLATE（可定制），2=CORE（系统）
- **幂等**：导入可重复执行而不产生重复项
- **版本检查**：始终使用最新版本

> **核心原则：** BACH 并非主要为单个用户开发，而是作为一个可复用的系统。

#### 工作原则

面向所有 BACH 伙伴（LLM、Agent、专家）的六条基本规则：

1. **自有资源优先** —— 在询问用户之前，先检查记忆、Wiki、工具和数据库
2. **结果优先于过程** —— 重要的是结果，而非方法
3. **行动而非宣告** —— 不要解释你将要做什么，直接去做
4. **拥有观点** —— 你可以反驳并提出自己的建议
5. **保持精简** —— 系统提示保持在 1000 token 以下，注入内容保持轻量
6. **沉淀知识** —— 在上下文丢失之前把认识写入记忆

**伙伴专属说明：**
- **Claude**：阅读根目录中的 `CLAUDE.md`（知识捕获规则、集成）
- **Gemini**：阅读根目录中的 `GEMINI.md`（知识捕获规则、集成）
- **Ollama**：阅读根目录中的 `OLLAMA.md`（知识捕获规则、集成）

这些文件包含详细的知识捕获规则和伙伴专属设置。

#### 数据库模式（bach.db 中 138 张表）

| # | 领域 | 最重要的表 |
|---|---------|---------------------|
| 1 | 系统 | `system_identity`, `system_config`, `instance_identity` |
| 2 | 任务 | `tasks` |
| 3 | 记忆 | `memory_working`, `memory_facts`, `memory_lessons`, `memory_sessions` |
| 4 | 工具 | `tools`（550+ 条记录） |
| 5 | Skill | `skills`（1870+ 条记录） |
| 6 | Agent | `bach_agents`, `bach_experts`, `agent_synergies` |
| 7 | 文件 | `files_truth`, `files_trash`, `dist_files` |
| 8 | 自动化 | `automation_triggers`, `automation_routines`, `automation_injectors` |
| 9 | 监控 | `monitor_tokens`, `monitor_success`, `monitor_processes`, `monitor_pricing` |
| 10 | 连接 | `connections`, `connector_messages`, `partner_presence` |
| 11 | 语言 | `languages_config`, `languages_translations` |
| 12 | 分发 | `distribution_manifest`, `dist_type_defaults`, `releases`, `snapshots` |
| 13 | Wiki | `wiki`（87 篇文章） |
| 14 | 使用场景 | `usecases`, `toolchains` |

完整模式：`system/data/schema/schema.sql`（138 张表 + 视图 + FTS）

---

### BACH v2.6 总体架构

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

### (3) MEMORY：加载你的情景上下文 [B/C]

```bash
bach help memory
bach help lessons
bach help consolidation
```

#### 认知记忆模型（5 种类型）

| 类型 | 对应 | 功能 | 命令 |
|-----|--------------|----------|--------|
| **Working** | 短期 | 当前会话 | `bach mem write` |
| **Episodic** | 日记 | 已结束的会话 | `bach --memory session` |
| **Semantic** | 世界知识 | 事实、Wiki、Help | `bach --memory fact "key:value"` |
| **Procedural** | 能力 | 工具、Skill、工作流 | `bach help tools` |
| **Associative** | 关联 | 巩固、触发器 | `bach consolidate` |

---

### (4) FÄHIGKEITEN：加载关于你能力的知识 [B/C]

```bash
bach help skills
bach help tools
```

**层级：**

- **Agent**：编排多个领域，拥有自己的文件夹
- **专家**：深厚的领域知识，拥有自己的文件夹
- **Services**：通用服务，贴近处理器

**重要目录：**

- `system/agents/` - Agent（各自独立文件夹）
- `system/agents/_experts/` - 专家（各自独立文件夹）
- `system/hub/_services/` - 服务（各自独立文件夹）
- `system/skills/workflows/` - 协议（单文件，原 _workflows）
- `system/skills/_templates/` - 标准模板
- `system/connectors/` - 外部接入（MCP、API）
- `system/partners/` - 多 LLM 配置

---

### (5) 任务规划 [B/C]

#### (5.1) 识别用户需求

- 把提示中明确提出的用户需求识别为任务
- 确定任务并规划你的做法
- 如果没有具体需求，继续到 5.2

#### (5.2) 加载任务上下文

```python
# API（优先）
from bach_api import task
task.list()
```

```bash
# CLI
bach help tasks
bach task list
```

- 自行挑选任务。**自 2026-10-25 起：接管与提交均通过 Lease 进行，参见最上方章节「作为代理处理开放任务」。** `bach task claim` 已过时（无 Fence/Lease-ID 的 Claim）。

---

### (6) 过程性知识与协议 [C]

*在模式 B 中为可选项 —— 协议是文档，不是代码。*

```bash
bach help protocol
bach help between-tasks
bach help practices
```

**路径：** `system/skills/workflows/`

## 主题包（按需阅读 —— 所有模式）

### 主题：协作（包：TEAMARBEIT）

*何时阅读：* 你与系统中的伙伴一起工作。

```bash
bach help partners
bach help multi_llm
bach help delegate
```

**聊天系统：**

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

**锁系统：**

```bash
bach llm lock <datei>           # Lock VOR Schreiben
bach llm unlock [datei]         # Lock freigeben
bach llm status                 # Wer hat welche Locks?
```

---

### 主题：问题解决（包：PROBLEMLÖSUNG）

*何时阅读：* 你遇到问题或阻塞。

```bash
bach help operatoren
bach help planning
bach help problemloesung
bach help strategien
```

---

### 主题：编码任务（包：CODING）

*何时阅读：* 你在处理代码或修复 Bug。

```bash
bach help ati
bach help coding
bach help bugfix
```

---

### 主题：维护（包：WARTUNG）

*何时阅读：* 你在处理维护任务。

```bash
bach help maintain
bach help wartung
bach help recurring
bach daemon status
```

---

### 主题：文件管理（包：DATEIVERWALTUNG）

*何时阅读：* 你执行文件操作。

```bash
bach help trash
bach help migrate
bach help distribution
```

---

### 主题：读取网页（包：WEB）

*何时阅读：* 你需要抓取网页、提取内容或执行 Web 分析。

```bash
bach help web_parse
bach help web_scrape
```

**两个用于不同目的的处理器：**

| 处理器 | 命令 | 用途 | 技术 |
|---------|--------|-------|---------|
| `web_parse` | `bach web-parse url/clean <url>` | **内容提取**（主内容为 Markdown） | trafilatura/html2text |
| `web_scrape` | `bach web-scrape get/links/forms/headers <url>` | **结构分析**（链接、表单、Headers） | requests + Regex |

**建议：** 文本内容用 `web-parse clean <url>`（移除导航/页眉/页脚）。原始数据或链接列表用 `web-scrape`。两者都使用 HTTP 请求 —— 由 JS 渲染的页面只提供服务器端生成的 HTML 部分。

**技能：** `skills/workflows/webseiten-lesen.md` —— 带有决策树的详细流程。

---

### 主题：自我扩展（包：SELF-EXTENSION）[B/C]

*何时阅读：* 你缺少某项能力，或想扩展 BACH。

```bash
bach help self-extension
bach help hooks
bach help skills
```

**创建新能力（5 种类型）：**

```bash
bach help trash
bach help migrate
bach help distribution
```

---

### 主题：读取网页（包：WEB）

*何时阅读：* 你需要抓取网页、提取内容或执行网页分析。

```bash
bach help web_parse
bach help web_scrape
```

**两个 Handler，用于不同目的：**

| Handler | 命令 | 目的 | 技术 |
|---------|--------|-------|---------|
| `web_parse` | `bach web-parse url/clean <url>` | **内容提取**（正文作为 Markdown） | trafilatura/html2text |
| `web_scrape` | `bach web-scrape get/links/forms/headers <url>` | **结构分析**（链接、表单、Headers） | requests + Regex |

**建议：** 文本内容用 `web-parse clean <url>`（移除 Nav/Header/Footer）。原始数据或链接列表用 `web-scrape`。两者都使用 HTTP 请求 —— JS 渲染的页面只会返回服务端 HTML 部分。

**技能：** `skills/workflows/webseiten-lesen.md` —— 带决策树的详细流程。

---

### 主题：自我扩展（包：SELF-EXTENSION）[B/C]

*何时阅读：* 你缺少某项能力，或者想扩展 BACH。

```bash
bach help self-extension
bach help hooks
bach help skills
```

**创建新能力（5 种类型）：**

```bash
bach skills create voice-processor --type tool       # Neues Tool scaffolden
bach skills create email-agent --type agent           # Neuen Agent scaffolden
bach skills create tax-expert --type expert            # Neuen Experten scaffolden
bach skills create api-gateway --type handler          # Neuen CLI-Befehl scaffolden
bach skills create data-sync --type service            # Neuen Service scaffolden
```

**创建之后：热重载（无需重启！）**

```bash
bach skills reload
```

**Hook 框架（14 个 Events）：**

```python
from core.hooks import hooks

# Eigene Logik an System-Events haengen
hooks.on('after_task_create', meine_funktion, name='mein_plugin')
hooks.on('after_startup', startup_check, name='mein_plugin')

# Events anzeigen
# bach hooks events
```

**Plugin-API（运行时动态扩展）：**

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
```
bach plugins create name   # Plugin scaffolden
bach plugins load pfad     # Plugin laden
bach plugins unload name   # Plugin entladen
```

**Self-Extension 循环：**
1. 识别 → 找出缺失的能力
2. 创建 → `bach skills create <name> --type <typ>` 或 `plugins.register_tool()`
3. 实现 → 编写代码
4. 注册 → `bach skills reload` 或 `plugins.load_plugin()`
5. 使用 → 立即可用
6. 反思 → `bach lesson add "Was gelernt"`

---

### 主题：Shutdown（包：SHUTDOWN）[B/C]

*何时阅读：* 会话即将结束。仅在模式 B 和 C 下相关。

**模式 B（API —— 推荐）：**
```python
from bach_api import session, memory
memory.session("THEMA: Was gemacht. NAECHSTE: Was kommt.", session_id="SESSION_ID", partner="claude")
session.shutdown("Zusammenfassung", partner="claude", session_id="SESSION_ID")
# Oder schnell:
session.shutdown_quick("Kurze Notiz", partner="claude", session_id="SESSION_ID")
```

`SESSION_ID` 是启动报告中你自己的 ID。在有多个打开的会话时，
始终给出 ID 和 Partner；不明确的选择会被拒绝。

**模式 C（CLI）：**
```bash
bach help shutdown
bach --memory session "THEMA: Was gemacht. NAECHSTE: Was kommt."
bach --shutdown
```

---

## HOOKS 与 INJEKTOREN

### Hook 框架（技术事件系统）

Hooks 允许把自有逻辑挂接到 14 个 Lifecycle-Events —— 而无需修改现有代码。

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

**Events：** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> Hooks 是**技术框架**。Injektoren 是**认知子系统**。两者彼此独立工作。

---

### Injektoren（认知编排）

6 个 Injektoren 作为**中央执行机构**模拟**思考与联想**。可通过 CLI 和 API 使用。

| Injektor | 子功能 | 适合 API |
|----------|----------------|:---:|
| **strategy_injector** | 元认知、决策辅助、错误分析 | 是 |
| **context_injector** | Tool 推荐、Memory 调取、需求分析 | 部分* |
| **between_injector** | 质量控制、Task 过渡、结果校验 | 是 |
| **time_injector** | 时间感（Timebeat）、消息检查 | 是 |
| **tool_injector** | Tool 提醒、重复警告 | 是 |
| **task_assigner** | 自动分配、Task 拆分 | 是 |

*\*context_injector 包含 CLI 命令作为提示。在 API 模式下可过滤。*

**CLI：**
```bash
bach --inject status            # Status aller Injektoren
bach --inject toggle <name>     # An/Aus schalten
```

**API：**
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

- **Agent 入口**：最上方新增章节“以 Agent 身份处理待办任务”（启动、选择 Task、接管 Lease、Worktree、测试、PR、提交结果、下一个 Task；边界；已知缺口）。目标：一个 Agent（Claude、Codex、Kimi、Gemini）仅凭此文件即可启动。
- **标记为过时**：`bach task claim` 以及（5.2）“将其分配给你自己”；新章节之下的数字与架构概览处于 2026-03-12 的状态且未重新测量。
- 未删除任何内容。模式 A、B、C 保持不变。

### v3.8.0 (2026-03-12)

- **Handler-Discovery**：第 (2) 节新增段落 —— 将 `bach help <suchbegriff>` 记录为 109+ Handler 的主要发现机制
- **搜索参考**：`bach help list`、`bach tools search`、`bach skills search` 作为搜索入口
- **主题包 WEB**：新增包，引用 `web_parse` 与 `web_scrape` Handler
- **技能 `webseiten-lesen`**：新增工作流技能，为 Web 内容提取提供决策树
- **文档**：Handler 现在可在 SKILL.md 中找到，而不再仅能通过 CLI

### v3.2.0-butternut (2026-02-28)

- **Agent-CLI**：`AgentLauncherHandler` —— `bach agent start/stop/list` 用于直接控制 Agent
- **Prompt 系统**：`PromptHandler` —— `bach prompt list/add/edit/show/board-create` 用于集中管理 Prompt
- **SharedMemory 扩展**：`current-task`、`generate-context`、`conflict-resolution`、`decay`、`changes-since`
- **USMC Bridge**：United Shared Memory Client (`hub/_services/usmc_bridge.py`)
- **llmauto 链**：Claude-Prompts 作为 Chain-Steps + `bach://`-URL-Resolution
- **Scheduler**：`job_type='chain'` + 重命名 `daemon_jobs` → `scheduler_jobs`
- **新增 API 模块**：`bach_api` 中的 `agent`、`prompt`
- **移植**：SharedMemoryHandler、ApiProberHandler、N8nManagerHandler、UserSyncHandler、Stigmergy-Service
- **数据表**：4 张新数据库表：`prompt_templates`、`prompt_versions`、`prompt_boards`、`prompt_board_items`
- **109+ Handler**（此前：75+）

### v2.6.0 (2026-02-13)

- **目录重构**：清晰分离 Agents、Skills、Connectors 与 Partners
  - `skills/_agents/` → `agents/`（system/ 下的顶层）
  - `skills/_experts/` → `agents/_experts/`（专家属于 Agents）
  - `skills/_workflows/` → `skills/workflows/`（Workflows 现在称为 Protocols）
  - `skills/_connectors/` → `connectors/`（system/ 下的顶层）
  - `skills/_partners/` → `partners/`（system/ 下的顶层）
- **PathHealer**：在所有受影响的文件中自动修正路径
- **组件类型 `protocol`**：在类型层级中取代 `workflow`
- **组件类型 `connector`**：新增，用于外部接入（MCP、APIs）
- **架构图**：AGENTS LAYER 与 CONNECTORS & PARTNERS 作为独立章节
- **SKILL.md v2.6**：所有引用、表格与图示均已适配新结构

### v2.5.0 (2026-02-13)

- **自扩展系统（Self-Extension System）**：AI 伙伴可以为自己创造新能力
  - `bach skills create <name> --type <typ>`（5 种类型：tool、agent、expert、handler、service）
  - `bach skills reload`（热重载：Registry + Tools + Skills-DB）
  - Self-Extension Loop：识别 → 创建 → 注册 → 使用 → 反思
- **Hook 框架**：可扩展的事件系统，包含 14 个生命周期事件
  - `core/hooks.py` - HookRegistry 单例、优先级、事件日志
  - `hub/hooks.py` - CLI：`bach hooks status/events/log/test`
  - 集成于：Startup、Shutdown、Task、Memory、Lesson、Skills、App
  - Hooks != 注入器：技术框架 vs. 认知子系统
- **Email-Handler**：Gmail API 带草稿保护（send、draft、confirm、cancel）
- **Registry 热重载**：`app().reload_registry()` 无需重启
- **规则 (f) 自扩展**：“缺少某项能力时，就自己给自己！”
- **文档**：hooks.txt、self-extension.txt、cli.txt、skills.txt、ROADMAP.md

### v2.4.0 (2026-02-08)

- **MCP Server v2.2**：23 个 Tools、8 个 Resources、3 个 Prompts —— 全部三种 MCP 原语
- **Email 适配器**：notify.py 中的 SMTP_SSL（从 BachForelle 移植）
- **BachFliege + BachForelle**：已分析并归档（`docs/_archive/con5_BACHFLIEGE_BACHFORELLE_ARCHIV.md`）

### v2.3.0 (2026-02-06)

- **规则体系彻底重做**：IMMER → 访问方式 → 模式专属
- **三种模式**：A（库）、B（混合）、C（会话），带 [B]、[C]、[B/C] 标记
- **共同开发原则**：“使用 BACH 即是共同开发”作为核心规则
- **bach_api.py 扩展**：session、partner、logs、msg、tools、help、injector
- **14 个 API 模块**：对所有 Handler 的完整程序化访问
- **通过 API 使用注入器**：全部 6 个注入器可在 Library 中使用 + CLI 过滤
- **通过 API 的会话生命周期**：`session.startup()` / `session.shutdown()`
- 架构图已更新（Core Layer + bach_api）
- 所有章节均附加模式标记

### v2.2.0 (2026-02-06)

- 记录了两种访问途径（CLI + Library-API）
- bach_api.py 基础模块：task、memory、backup、steuer、lesson、status

### v2.1.0 (2026-02-04)

- 整合技能架构 v2.0
- 引入版本检查原则
- 记录标准 Header
- 新增技能来源分类
- 记录注入器子功能

### v2.0.2 (2026-01-01)

- 初始版本

---

**BACH Skill-Architektur v2.0**
