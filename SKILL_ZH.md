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
- **尚无原生短命令** `bach task take|renew|submit|return|block`；已在计划中（`ANFORDERUNGEN-DETAIL.md` 的 „Tasksystem, Leases und Locks“ 章节）。目前持久的原生途径是 Python-SDK `TaskLeaseClient`（见上文）；`bach_api.task` 仅提供 `lease_acquire`/`lease_read`/`lease_renew`/`lease_release`/`lease_decompose`，没有候选列表，也没有 `submit_result`。
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
<!-- T2619-CONT -->