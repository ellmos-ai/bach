---
name: bach
version: 3.10.0
type: skill
author: BACH Team
created: 2025-12-01
updated: 2026-10-25
anthropic_compatible: true

description: >
  BACHの中央管理システム。Claudeにアップロードする必要がある唯一のスキルである。
  すべてのローカルスキルを把握し、
  必要に応じてバージョンチェックを行い、より新しいローカルバージョンを読み込む。
  スキルの利用時に自動的に有効化される。
---

# オープンなタスクを処理するエージェントとして（Claude、Codex、Kimi、Geminiの入口）

> **v3.10.0（2026-10-25）の新機能。** あなたの依頼が「SKILL.mdを読んでオープンなタスクを処理せよ」というものであれば、**まずこのセクション**が適用される。このファイルのその他の内容はリファレンスであり、必要な場合にのみ読むこと。
> 詳細でコピー可能な版: `Desktop\OCEAN\EINWEISUNG-EXTERNE-WORKER.md` (LukasのOneDrive、リポジトリには含まれない)。リース契約: `docs/architecture/TASKDB-SALT-LEASE-VERTRAG-v1.md`、クライアント: `docs/architecture/TASKDB-SALT-LEASE-CLIENTS-v1.md`。ローカルWorker-Harness (Buddha): `docs/architecture/LOKALER-WORKER-HARNESS.md` (PR #520)。

**一文で表した流れ:** 起動 → タスクを選択 → **リースを取得してから作業** → 専用ワークツリー → テスト → PR → 結果を提出 → 次のタスク。Lukasからの明示的な停止指示がない限り、作業を止めないこと。

### 1. 起動とモード
- 用意されたSSHアクセスを介してMac Studioに接続すること。独自のアクセス情報は作成しないこと。プロジェクトは `$BACH_ROOT` 配下（Mac Studioでは `~/services/bach`）、Pythonはそのvenvのものを使う。`AGENTS.md` と、自分が作業する部分プロジェクトの指示を読むこと。
- **モードB（ミックス）** は積極的に協働するエージェントにとっての標準である。**モードA（ライブラリ）** は、タスクの処理のみを行いBACHをセッションとして利用しない場合に十分である。以下のリースの経路はリードサービス経由で動作し、セッション開始を必要としない。モードC（セッション）は明示的な要望がある場合のみ。
- 最初のタスクの前に、現在の計画 `Desktop\OCEAN\AKTUELLER-PLAN.md` と `MODUL-ZUORDNUNG.md`（構築場所）を読むこと。
### 2. 空きタスクの検索
- **ネイティブ:** `TaskLeaseClient.task_candidates(limit=100, offset=…)`（最初のページだけでなく、すべてのページを読む）、その後 `task_snapshot(task_id)` で完全な説明を取得。`bach task list` は同じタスクの閲覧専用。
- **選択ルール:**
  1. 依存関係が満たされ、他人の有効なリースがなく、自分のツールで対応できるタスクのみ。
  2. **最も高い優先度を優先**（P0 を P1 より、P1 を P2 より優先）。優先度が同じ場合はアジェンダの重点に合うものを先に（2026-10-25 時点：Förderplaner、エージェントテンプレート／制御、Running & Living、GUI 改修、ワーカーの信頼性。基準は `AKTUELLER-PLAN.md`）。
  3. **`OLLAMA`-タスクは不可。** これはローカルワーカー（Buddha、Ollama Cloud、OpenRouter）のバックグラウンド待ち行列。`USER`/`HUMAN`/`LUKAS` 向けタスクや他人が予約したタスクもそのまま残す。`BACH` は共同編集可能を意味する。追加のスロット義務をでっち上げないこと。
  4. 他の作成者によるレビュー・検証タスクは明示的に適している。
  5. タスクが未解決のユーザー判断に依存している場合や自分の能力に合わない場合：質問、または理由を（タスクメモに）記録し、次のタスクへ。タスクを受け取るためだけにルールや保護ゲートを変更しないこと。
### 3. 作業前にリースを取得
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
- ワーカーID **`<agent>@<host>`**、独自のRequest-IDと世代は、他のワーカーと決して共有しない。承認された確定後に初めて作業を開始する。
- `renew` が拒否された場合、リースの有効期限が切れた場合、またはフェンスが変更された場合：**このタスクへのすべての書き込み操作を停止する。** 確認済みの内容変更の後は、保存されたタスクバージョンを更新する。
- **使用しないこと：** `bach task claim`（フェンス/リースIDなしの古いクレーム）と `~/compute/luna-gui/task_tool.py claim`（`assigned_to` のみを設定し、リースはない）。どちらもネイティブな引き受けではなく、二重処理を防げない。`task_tool.py note`（説明へのテキスト追加）と `list` は、ネイティブな代替が存在するまで暫定的に利用できる。
- シグネチャはこの例ではなく、`system/hub/_services/task_lease_client.py` から必ず確認すること。
### 4. 作業
- **タスクごとに専用ワークツリー**を `origin/main` から作成: `git worktree add ~/services/bach-worktrees/<zweig> -b <zweig> origin/main`。ブランチ名は `<agent>/<task>-<kurz>-<datum>`。メインチェックアウト `~/services/bach` は占有中（他人のコミットされていない変更）: そこでは作業も計測もビルドも行わない。
- **ビルド場所:** 新しい専門ロジックは `MODUL-ZUORDNUNG.md` に従って該当する Ocean モジュールリポジトリに入れる。BACH コアには入れない。
- タスクの受け入れ基準に照らして結果を検証する。変更した領域のテストを実行し、裏付けできることだけを主張する。ドイツ語のエンドユーザーテキストは本物のウムラウトで書く。
- コミット前: シークレットスキャン、Diff を読む、自分のファイルだけをコミット（まとめコミット禁止）。
- ブランチを push し、**`main` に対する PR を作成**してタスクに記録する。コミット、push、PR、マージ、デプロイ、業務的な受け入れをそれぞれ個別に明示する。ブランチはまだ納品された状態ではない。

### 5. 結果の提出
- **完了:** `client.submit_result(task_id, lease_id=…, fence=…, task_version=…, generation="<neue-Generation>", result="<Text>")`。`result` は **最大 3000 文字** の具体的なテキスト（達成した基準、変更、PR リンク、コミット SHA、実際の検証結果、限界）。単なる完了報告（„done“）は拒否される。提出するとタスクは `review` に移り、リースは解放される。その後 `task_result_snapshot(task_id)` を読み、結果 ID/ハッシュを確認する。チャットのテキストだけでは提出にならない。
- **部分状態または停滞:** WIP ブランチを push し、その後 `client.release(task_id, lease_id=…, fence=…, outcome="return" | "blocked", note="<Branch, SHA, nächster Schritt>")`。一律の `done` は不可。人を待つ間にリースを人為的に延長しない。（`complete=false` はローカル Buddha 実行のタスクツールにのみ存在（ハーネス文書参照）。SDK にはない。）
- その後 **すぐに次のタスク**（ステップ 2）。現時点で引き受けられるものがない場合: 根拠を報告し、短く待ち、再度確認する。自分の依頼を自分で終了しない。
- タスクごとの短い報告: タスク ID、作業、根拠、コミット/リモート SHA、PR、読み戻したタスク/結果/リースの状態。自分の作業のレビューは独立していないものとして明示する。
### 6. 制限（常に有効）
- **マージしない**こと：`main` にプッシュしない、何もロールアウトしない、サービスを再起動しない、ワーカー構成を変更しない、他のジョブ／ワーカーを停止しない、`.SYNC` 実行を開始しない。マージは二次検証を経て行われ、ロールアウトは検証後に行われる。
- **`bach.db` に直接書き込まない**こと：独自の SQL 変更をしない、コピーされたデータベースを権威として扱わない。常にネイティブ API／SDK を使う。
- **`OneDrive\.TOPICS` や `.TOPICS\.AI` にロックを作らない**こと：それらは Mac 上でバックグラウンドワーカー Buddha とあらゆるロールアウトを止める。ロックは自分のワークツリーパスに対してのみ。
- 他者のアクティブなリース、他のエージェントの実行中の作業、ロックされたパスは保護されたままにする。トークンとアクセス情報は決して出力またはコミットしない。

### 7. 既知の欠落（2026-10-25時点）
- **ネイティブの短縮コマンドはまだ存在しない** `bach task take|renew|submit|return|block`；これは計画されている（`ANFORDERUNGEN-DETAIL.md` のセクション „Tasksystem, Leases und Locks“）。現時点で恒久的なネイティブ経路は Python-SDK `TaskLeaseClient`（上記）。`bach_api.task` は `lease_acquire`/`lease_read`/`lease_renew`/`lease_release`/`lease_decompose` のみを提供し、候補リストも `submit_result` もない。
- `task_tool.py` はリポジトリの外にある（`~/compute/luna-gui/`）。その `list` は `bach.db` を直接（読み取り専用）読み、その `claim` はリースではない。
- 引き継ぎ指示、計画、`MODUL-ZUORDNUNG.md` は Lukas の OneDrive デスクトップにあり、リポジトリにはない。Mac 上で稼働するエージェントは、コピーがなければそれらに到達できない。
- 外部成果物の由来契約：#2339 はネイティブに受領済み、Main へのマージとリリースは未実施（PR #507）。それまでは成果物を誠実に提出済みまたは部分状態として扱うこと。
> **残りのファイル内容に関する現状の注意:** このセクションより下は、内容面で最後に 2026-03-12（v3.8.0）に見直された。数値（ハンドラー、テーブル、フック、テーマ）、アーキテクチャ概要 v2.6、タスク計画（5）はそれ以降**新たに測定されていない**。矛盾する場合は、コードまたは実測が優先される。タスクの引き受けはもはや `bach task claim` 経由ではなく、上記の方法で行われる。

---

# バージョンに関する注意

# このスキルの新しいバージョンが存在するか確認する（ローカルまたは中央）

# 常に最も高いバージョン番号のバージョンを使用する

# Versions-Check: bach skills version bach

# Bach へようこそ

---

## ルール - ガイドライン - 規範

---

### 常に（他の何よりも先に）

**(1) バージョン・チェック:** このSKILL.mdに複数のバージョン（ローカル、中央）が存在する場合、バージョン番号を比較し、必要に応じて最新版へ切り替えて、そこから読み続ける。
```bash
bach skills version bach   # Prueft ob aktuellere Version existiert
```

**(2) OSチェック:** 自分がWindows、Mac、Linuxのどれで動いているかを確認する。
- Windows: `/dev/null` は存在せず、`NUL:` も使わない。代わりに出力を省略するか `2>&1` を利用する。`&&` は避け、コマンドは個別に実行
- nulファイルがある場合: `python tools/c_nul_cleaner.py --dir <pfad> --delete`

---

### その後：アクセス方法／セッション・モードを明確にする

自分の状況に合うモードを選ぶ：

| モード | 使用場面 | スタートアップ | アクセス |
|-------|------|---------|--------|
| **A) ライブラリ** | ゲスト、読み取り、個別の問い合わせ、BACHを道具として利用 | スタートアップなし | `from bach_api import task; task.list()` |
| **B) ミックス** | ユーザーからBACH起動を求められた、能動的な協力 | APIスタートアップ | `session.startup()` + API + `session.shutdown()` |
| **C) セッション** | 従来型、自動起動、詳細なプロトコル | CLIスタートアップ | `python bach.py --startup --partner=claude` |

- モードCはいつでもBに切り替え可能（CLIの代わりにAPIを利用）
- モードBとCはいつでもAに切り替え可能（セッションなしの個別の問い合わせ）
- 迷ったら：**モードB**（LLMセッション向けに推奨）
---

### モードBおよびC：能動的利用のためのルール

**(1) 読み書き -- BACHの利用は共同開発である:**

BACHを利用する者は、BACHを共に発展させている。すべてのアクセスは、システムを改善する機会である。

- **(a) Handler First:** すべての機能は`hub/`内のHandlerとして実装すること。HandlerはCLI**と**APIの両方から自動的に利用できる。アクセス経路ごとに別々のコードは書かない。
- **(b) 隙間を埋める:** Handler、APIモジュール、Skills、Tools、Workflowsやその他のコンポーネントが不足している場合は、それを作成すること。不足しているHandlerが最優先。すべてのアクセス経路の基盤となるためである。
- **(c) 自作歓迎:** 自作のSkills、Workflows、Tools、MCPsの作成は明確に歓迎される。既存のものを扱う際はUserと相談すること。
- **(d) Fix-or-Task:** 問題は、即時修正（小規模）またはQueue内のタスク（大規模）のいずれかで対処する。判断基準は労力 vs. 効果。その後、本来の作業に戻ること。
- **(e) Self-Healing:** BACHにエラー（パス、コマンド、古い参照、壊れたImport）を見つけたら、すぐに修正してUserに報告すること。BACHは利用者によって自らを修復する。
- **(f) Self-Extension:** 必要な能力がなければ、自分に与えよう！新しいTools、Handler、Agents、Experts、Servicesの雛形作成には`bach skills create`を使うこと。`bach skills reload`の後ですぐに利用可能になる。参照: `bach help self-extension`

**(2) スタートアップ手順を実行すること**（下記参照）。必須パッケージを読み、必要に応じて（`-->`）任意の参照を読むこと。パッケージにはモード標識が付されている：
- `[C]` → セッション・モードでのみ読む
- `[B]` → 混合モードでのみ読み、セッション・モードでは読み飛ばす
- `[B/C]` → 両方のモードで読む
- 標識なし → 常に必要に応じて読む

**(3) 必要に応じて追加パッケージを読むこと**（主題パッケージは下記参照）。

---
### モードA：ゲスト・ツール利用のルール

必要に応じて追加パッケージを読む。スタートアップは不要、シャットダウンも想定されない。

```python
from bach_api import task, memory, tools, steuer
task.list()         # Sofort nutzbar
tools.search("ocr") # Werkzeug finden
```

---

### ドキュメント構成（ナビゲーションマップ）

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

### スキルアーキテクチャ v2.0（NEU）

#### バージョンチェックの原則

**常に最新のバージョンを使用する** — ローカルでも中央でも、保存場所は問わない：

```bash
bach skills version <name>    # Prüfe Versionen
bach tools version <name>     # Prüfe Tool-Versionen
```

#### スキル構造: 1スキル = 1フォルダ

各スキル、エージェント、エキスパートは**固有のフォルダ内で完全に自己完結**している：

```
agents/entwickler/
├── SKILL.md              # Definition mit Standard-Header
├── tool_xyz.py           # Spezifische Tools (flat)
├── protocol_abc.md       # Spezifische Protokolle (flat)
└── config.json           # Optional
```

**ルール:**

- 5ファイル未満: フラット（すべてルート直下）
- >= 5ファイル: サブフォルダー `tools/`、`protocols/` が許可
- **迷った場合はツールを二重に持つ**（汎用 + スキル固有）
- エクスポート後はBACHなしで動作すること

#### 標準ヘッダー（すべてのコンポーネントで必須）

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

**テンプレート:** `system/skills/_templates/TEMPLATE_*.md`

#### 拡張段階

BACHは3つの段階で存在する：**USMC**（メモリ核心）、**Rinnsal**（+ LLMオーケストレーション）、**BACH**（完全なシステム）。詳細：[README.md](README.md#ausbaustufen)

#### 3つのアクセスモード

BACHは**2つの並行アクセス経路**（CLI + ライブラリAPI）を提供し、それらは**3つのモード**に組み合わせられる。両経路とも同じHandlerと同じDBを利用する。

##### モード1: セッション・モード (CLI -- 従来型)

コマンドライン経由の完全なStartup/Shutdownプロトコル。対話型ターミナルセッション向け。

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
# ... arbeiten ...
python bach.py --shutdown "Zusammenfassung"
```

##### モード2: ライブラリ・モード (API -- 軽量)

セッションのオーバーヘッドなしでのHandlerへの直接アクセス。スクリプト、素早い照会、または個々の操作のみを必要とするLLM向け。

```python
from bach_api import task, memory, steuer, partner, tools, injector

task.list()                              # Tasks abfragen
memory.write("Wichtige Notiz")           # Memory schreiben
steuer.status()                          # Steuer-Status
partner.list()                           # Partner auflisten
injector.process("ich bin blockiert")    # Kognitive Hilfe
```

##### モード3: 混合モード (API と Session-Lifecycle)

API経由の完全なStartup/Shutdown。**LLMセッションに推奨** -- セッション管理と扱いやすいAPIアクセスを組み合わせる。

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
##### 利用可能なAPIモジュール

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

    # Plugin-API (動的拡張)
    plugins,     # register_tool(), register_hook(), register_handler(), load_plugin()

    # Raw-Zugriff (任意のハンドラ)
    app,         # app().execute("handler", "operation", ["args"])
)
```

##### どれをいつ使うか

| 状況 | 推奨 |
|-----------|------------|
| LLM セッション (推奨) | 混合モード: `session.startup()` + API |
| 高速な単発照会 | ライブラリモード: 直接 `task.list()` |
| ターミナルの人間 | セッションモード: `python bach.py --startup` |
| ファイル読取・コード検索 | 直接 (Glob/Grep/Read) |
| ハンドラが bach_api にない | `app().execute("handler", "op", ["args"])` |

**アーキテクチャ:** `core/registry.py` は 113+ のハンドラを自動認識する (Auto-Discovery)。新しいハンドラは `hub/` に `.py` ファイルを 1 つ置くだけでよい -- 手動マッピングは不要。ホットリロード: `app().reload_registry()`

#### コンポーネントの種類

| 種別 | フォルダ | 特徴 |
|-----|--------|----------------|
| **Agent** | `agents/<name>/` | エキスパートを編成、専用フォルダ |
| **Expert** | `agents/_experts/<name>/` | 深いドメイン知識、専用フォルダ |
| **Service** | `hub/_services/<name>/` | 汎用、ハンドラ寄り、専用フォルダ |
| **Protocol** | `skills/workflows/` | 1 ファイル = 1 プロトコル (旧 Workflow)、カテゴリ別サブフォルダ可 |
| **Connector** | `connectors/` | 外部接続 (MCP, API) |
| **Tool (汎用)** | `tools/` | 再利用可能 |
| **Tool (専用)** | スキルフォルダ内 | このスキル専用 |

#### スキルソースと安全性

| クラス | ソース | 対応 |
|--------|---------|----------|
| **ゴールドスタンダード** | 自作 | 最良の統合 |
| **信頼できる** | anthropics/skills, anthropics/claude-cookbooks | 審査後 1:1 で採用可能 |
| **不確実** | その他の GitHub リポジトリ | 新規に書き直すことのみ |
| **ブラックリスト** | `data/skill_blacklist.json` | 禁止 |

---

## 起動手順 [B/C]: (1) → (2) → (3) → (4) → (5) → (6)

*モード B (混合) と C (セッション) のみ。モード A はこのセクションを省略する。*

---

### (1) 今すぐ Bach を起動する [B/C]

**モード C (セッション/CLI):**

```bash
cd system
python bach.py --startup --partner=claude --mode=silent --watch
```

**モード B (混合/API -- 推奨):**

```python
from bach_api import session
session.startup(partner="claude", mode="silent")
```

**Gemini の場合:**

```python
# モード B (API)
session.startup(partner="gemini", mode="silent")
# モード C (CLI)
# python bach.py --startup --partner=gemini --mode=silent --watch
```

---

### (2) SYSTEM: システム知識を読み込む [B/C]

```bash
bach help cli
bach help bach_info
bach help features
bach help naming
bach help guidelines
bach help architecture
# --> bach help injectors
```

または API 経由: `help.run("cli")`, `help.run("features")` など。

#### ハンドラの検出と検索

BACH には `hub/` に 113+ のハンドラがある。**すべてのハンドラは CLI コマンドである。** ハンドラ、ツール、スキル、ヘルプトピックを見つけるには:

```bash
# ヘルプトピックのファジー検索 (187+ トピック、ファジーマッチ!)
bach help <検索語>                # 例: bach help web → web_scrape, web_parse を提案

# ハンドラを一覧表示
bach help list                    # すべての 187+ ヘルプトピック
bach help cli                     # CLI コマンド一覧

# ツールを検索
bach tools list                   # すべての Python ツール
bach tools search <keyword>       # ツール名と内容の全文検索

# スキルとエージェントを検索
bach skills list                  # DB 内のすべてのスキル
bach skills search <keyword>      # スキルをキーワードで絞り込み
bach agent list                   # すべてのエージェント

# 任意のハンドラを直接呼び出す
bach <handler-name> <operation>   # 例: bach web-scrape get <url>
```

**重要:** どのハンドラが存在するか分からない場合は `bach help <検索語>` を使う -- ファジー検索が適切なトピックを提案する。不正確な語でも機能する。

#### 参照すべきファイル

- `system/CHANGELOG.md` - バージョン履歴
- `system/ROADMAP.md` - 計画中の機能とアーキテクチャ概要

#### ルート文書 (DB から生成、`bach --shutdown` 時に更新)

- `AGENTS.md` - すべてのボスエージェントとエキスパート (状態とパス付き)
- `PARTNERS.md` - LLM パートナーと委任
- `SKILLS.md` - スキルインデックス
- `WORKFLOWS.md` - プロトコルインデックス
- `CHAINS.md` - ツールチェーン
- `USECASES.md` - ユースケース
- `USER.md` - ユーザープロフィール
- `MEMORY.md` - メモリースナップショット
- `BACH_HELP_REFERENCE.md` - ヘルプリファレンス全体

#### 中核原則

- **BACH は有機体**: Connectors/Bridge は**感覚と声** (外界の知覚とコミュニケーション)。LLM は**理性** (思考、理解、決定)。データベースとテキストファイルは**記憶**。GUI は**顔**。API、CLI、ツール、エージェント、スキル、ワークフローは**手** (行動の可能性)。
- **ハンドラファースト**: すべての機能は `hub/` 内のハンドラとして実装 -- CLI **と** API の両方から自動的に到達可能
- **API 優先**: LLM は CLI ではなく `bach_api` を使う。人間は CLI または GUI を使う。
- **システム的**: すべてのユーザーにとって再利用可能
- **dist_type**: 0=USER (個人)、1=TEMPLATE (適応可能)、2=CORE (システム)
- **冪等**: インポートは重複なく繰り返し可能
- **バージョンチェック**: 常に最新バージョンを使用する

> **中核原則:** BACH は主として単一のユーザーのために開発されるのではなく、再利用可能なシステムとして開発される。

#### 作業原則

すべての BACH パートナー (LLM、エージェント、エキスパート) のための 6 つの基本ルール:

1. **まず自身のリソース** — ユーザーに尋ねる前に、メモリー、Wiki、ツール、DB を確認する
2. **プロセスより結果** — 評価されるのは手法ではなく結果である
3. **告知ではなく行動** — 何をするかを説明せず、ただ実行する
4. **意見を持つ** — 反論し、独自の提案をしてよい
5. **コンパクトに保つ** — システムプロンプトは 1000 トークン未満、インジェクションは簡潔に
6. **知識を保存する** — 文脈が失われる前に気づきを記憶に書き込む

**パートナー固有の指示:**
- **Claude**: ルートディレクトリの `CLAUDE.md` を読む (Knowledge Capture ルール、統合)
- **Gemini**: ルートディレクトリの `GEMINI.md` を読む (Knowledge Capture ルール、統合)
- **Ollama**: ルートディレクトリの `OLLAMA.md` を読む (Knowledge Capture ルール、統合)

これらのファイルには詳細な Knowledge-Capture ルールとパートナー固有の設定が含まれている。

#### データベーススキーマ (bach.db 内の 138 テーブル)

| # | 領域 | 主要テーブル |
|---|---------|---------------------|
| 1 | システム | `system_identity`, `system_config`, `instance_identity` |
| 2 | タスク | `tasks` |
| 3 | メモリー | `memory_working`, `memory_facts`, `memory_lessons`, `memory_sessions` |
| 4 | ツール | `tools` (550+ エントリ) |
| 5 | スキル | `skills` (1870+ エントリ) |
| 6 | エージェント | `bach_agents`, `bach_experts`, `agent_synergies` |
| 7 | ファイル | `files_truth`, `files_trash`, `dist_files` |
| 8 | 自動化 | `automation_triggers`, `automation_routines`, `automation_injectors` |
| 9 | 監視 | `monitor_tokens`, `monitor_success`, `monitor_processes`, `monitor_pricing` |
| 10 | 接続 | `connections`, `connector_messages`, `partner_presence` |
| 11 | 言語 | `languages_config`, `languages_translations` |
| 12 | 配布 | `distribution_manifest`, `dist_type_defaults`, `releases`, `snapshots` |
| 13 | Wiki | `wiki` (87 記事) |
| 14 | ユースケース | `usecases`, `toolchains` |

完全なスキーマ: `system/data/schema/schema.sql` (138 テーブル + ビュー + FTS)

---

### BACH v2.6 全体アーキテクチャ

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

### (3) MEMORY: エピソード記憶のコンテキストをロードする [B/C]

```bash
bach help memory
bach help lessons
bach help consolidation
```

#### 認知メモリーモデル (5 つのタイプ)

| タイプ | 対応 | 機能 | コマンド |
|-----|--------------|----------|--------|
| **Working** | 短期 | 現在のセッション | `bach mem write` |
| **Episodic** | 日記 | 完了したセッション | `bach --memory session` |
| **Semantic** | 世界知識 | 事実、Wiki、ヘルプ | `bach --memory fact "key:value"` |
| **Procedural** | 技能 | ツール、スキル、ワークフロー | `bach help tools` |
| **Associative** | 連結 | 統合、トリガー | `bach consolidate` |

---

### (4) 能力: 自分の能力に関する知識をロードする [B/C]

```bash
bach help skills
bach help tools
```

**階層:**

- **エージェント**: 複数の領域をオーケストレートする。専用フォルダを持つ
- **エキスパート**: 深いドメイン知識。専用フォルダを持つ
- **サービス**: 汎用サービス。ハンドラーに近い

**重要なディレクトリ:**

- `system/agents/` - エージェント (各専用フォルダ)
- `system/agents/_experts/` - エキスパート (各専用フォルダ)
- `system/hub/_services/` - サービス (各専用フォルダ)
- `system/skills/workflows/` - プロトコル (単一ファイル、旧 _workflows)
- `system/skills/_templates/` - 標準テンプレート
- `system/connectors/` - 外部接続 (MCP、API)
- `system/partners/` - マルチ LLM 構成

---

### (5) タスク計画 [B/C]

#### (5.1) ユーザーの要望を認識する

- プロンプトで明示された具体的なユーザー要望をタスクとして認識する
- タスクを確定し、自分の進め方を計画する
- 具体的な要望がない場合は 5.2 に進む

#### (5.2) タスクコンテキストをロードする

```python
# API (優先)
from bach_api import task
task.list()
```

```bash
# CLI
bach help tasks
bach task list
```

- タスクは自分で選ぶ。**2026-10-25 以降: 引き受けと引き渡しはリース経由で行う。冒頭の「エージェントとして未処理タスクを処理する」セクションを参照。** `bach task claim` は非推奨 (フェンス/リース ID なしのクレーム)。

---

### (6) 手続き的知識とプロトコル [C]

*モード B では任意 -- プロトコルはドキュメントであり、コードではない。*

```bash
bach help protocol
bach help between-tasks
bach help practices
```

**パス:** `system/skills/workflows/`

---

## トピックパッケージ (必要に応じて読む -- すべてのモード)

### トピック: 協働 (パッケージ: チームワーク)

*いつ読むか:* システム内のパートナーと協働するとき。

```bash
bach help partners
bach help multi_llm
bach help delegate
```

**チャットシステム:**

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

**ロックシステム:**

```bash
bach llm lock <datei>           # 書き込み前にロック
bach llm unlock [datei]         # ロックを解除
bach llm status                 # 誰がどのロックを保持しているか
```

---

### トピック: 問題解決 (パッケージ: PROBLEMLÖSUNG)

*いつ読むか:* 問題や行き詰まりに遭遇したとき。

```bash
bach help operatoren
bach help planning
bach help problemloesung
bach help strategien
```

---

### トピック: コーディング作業 (パッケージ: CODING)

*いつ読むか:* コードを扱う、またはバグを修正するとき。

```bash
bach help ati
bach help coding
bach help bugfix
```

---

### トピック: 保守 (パッケージ: WARTUNG)

*いつ読むか:* 保守タスクを処理するとき。

```bash
bach help maintain
bach help wartung
bach help recurring
bach daemon status
```

---

### トピック: ファイル管理 (パッケージ: DATEIVERWALTUNG)

*いつ読むか:* ファイル操作を実行するとき。

```bash
bach help trash
bach help migrate
bach help distribution
```

---

### トピック: Web ページを読む (パッケージ: WEB)

*いつ読むか:* Web ページを取得し、内容を抽出する、または Web 分析を行う必要があるとき。

```bash
bach help web_parse
bach help web_scrape
```

**異なる目的を持つ 2 つのハンドラー:**

| ハンドラー | コマンド | 目的 | 技術 |
|---------|--------|-------|---------|
| `web_parse` | `bach web-parse url/clean <url>` | **コンテンツ抽出** (本文を Markdown として) | trafilatura/html2text |
| `web_scrape` | `bach web-scrape get/links/forms/headers <url>` | **構造分析** (リンク、フォーム、ヘッダー) | requests + Regex |

**推奨:** テキスト内容には `web-parse clean <url>` (ナビ/ヘッダー/フッターを除去)。生データやリンク一覧には `web-scrape`。どちらも HTTP リクエストを使用する -- JS レンダリングされたページはサーバー側の HTML 部分のみを返す。

**スキル:** `skills/workflows/webseiten-lesen.md` -- 意思決定ツリー付きの詳細な手順。

---

### テーマ: 自己拡張 (パッケージ: SELF-EXTENSION) [B/C]

*いつ読むか:* 機能が欠けている場合、または BACH を拡張したい場合。

```bash
bach help self-extension
bach help hooks
bach help skills
```

**新しい機能を作成する (5 タイプ):**

```bash
bach skills create voice-processor --type tool       # 新しいツールをスキャフォールド
bach skills create email-agent --type agent           # 新しいエージェントをスキャフォールド
bach skills create tax-expert --type expert            # 新しいエキスパートをスキャフォールド
bach skills create api-gateway --type handler          # 新しい CLI コマンドをスキャフォールド
bach skills create data-sync --type service            # 新しいサービスをスキャフォールド
```

**作成後: ホットリロード (再起動不要!)**

```bash
bach skills reload
```

**フックフレームワーク (14 イベント):**

```python
from core.hooks import hooks

# 独自のロジックをシステムイベントに接続する
hooks.on('after_task_create', meine_funktion, name='mein_plugin')
hooks.on('after_startup', startup_check, name='mein_plugin')

# イベントを表示する
# bach hooks events
```

**プラグイン API (実行時の動的拡張):**

```python
from bach_api import plugins

# ツールを登録する (即座に使用可能)
plugins.register_tool("mein_tool", meine_funktion, "Beschreibung")

# フックを登録する (イベントを購読する)
plugins.register_hook("after_task_done", callback, plugin="mein-plugin")

# ハンドラを登録する (新しい CLI コマンド!)
plugins.register_handler("mein_cmd", MeinHandler)

# マニフェストからプラグインを読み込む
plugins.load_plugin("plugins/mein-plugin/plugin.json")
```

```bash
# CLI: プラグイン管理
bach plugins list          # 読み込み済みプラグイン
bach plugins create name   # プラグインをスキャフォールド
bach plugins load pfad     # プラグインを読み込む
bach plugins unload name   # プラグインをアンロード
```

**自己拡張ループ:**
1. 認識 → 不足している機能を特定する
2. 作成 → `bach skills create <name> --type <typ>` または `plugins.register_tool()`
3. 実装 → コードを書く
4. 登録 → `bach skills reload` または `plugins.load_plugin()`
5. 使用 → 即座に利用可能
6. 省察 → `bach lesson add "何を学んだか"`

---

### テーマ: シャットダウン (パッケージ: SHUTDOWN) [B/C]

*いつ読むか:* セッションが終了するとき。モード B と C でのみ関連する。

**モード B (API -- 推奨):**
```python
from bach_api import session, memory
memory.session("THEMA: 何をしたか。NAECHSTE: 次に何が来るか。", session_id="SESSION_ID", partner="claude")
session.shutdown("要約", partner="claude", session_id="SESSION_ID")
# または手早く:
session.shutdown_quick("短いメモ", partner="claude", session_id="SESSION_ID")
```

`SESSION_ID` はスタートアップレポートにある自身の ID。複数のセッションが開いている
場合は常に ID とパートナーを指定すること。不明確な選択は拒否される。

**モード C (CLI):**
```bash
bach help shutdown
bach --memory session "THEMA: 何をしたか。NAECHSTE: 次に何が来るか。"
bach --shutdown
```

---

## フックとインジェクター

### フックフレームワーク (技術的イベントシステム)

フックを使うと、既存のコードを変更せずに、独自のロジックを 14 のライフサイクルイベントに接続できる。

```python
from core.hooks import hooks

# リスナーを登録する
hooks.on('after_task_done', auto_backup, name='backup_plugin')
hooks.on('after_startup', health_check, priority=10, name='health')

# CLI
# bach hooks status    → すべてのフックを表示
# bach hooks events    → 14 のイベントをすべて一覧表示
# bach hooks log       → 直近の実行
```

**イベント:** `before_startup`, `after_startup`, `before_shutdown`, `after_shutdown`, `before_command`, `after_command`, `after_task_create`, `after_task_done`, `after_task_delete`, `after_memory_write`, `after_lesson_add`, `after_skill_create`, `after_skill_reload`, `after_email_send`

> フックは**技術的なフレームワーク**である。インジェクターは**認知サブシステム**である。両者は互いに独立して動作する。

---

### インジェクター (認知的オーケストレーション)

6 つのインジェクターは**思考と連想**を**中央実行系**としてシミュレートする。CLI と API の両方から利用可能。

| インジェクター | 部分機能 | API 対応 |
|----------|----------------|:---:|
| **strategy_injector** | メタ認知、意思決定支援、エラー分析 | はい |
| **context_injector** | ツール推薦、メモリー取得、要件分析 | 一部* |
| **between_injector** | 品質管理、タスク移行、結果検証 | はい |
| **time_injector** | 時間感覚 (タイムビート)、メッセージチェック | はい |
| **tool_injector** | ツールリマインダー、重複警告 | はい |
| **task_assigner** | 自動割り当て、タスク分解 | はい |

*\*context_injector は CLI コマンドをヒントとして含む。API モードではフィルタ可能。*

**CLI:**
```bash
bach --inject status            # すべてのインジェクターの状態
bach --inject toggle <name>     # オン/オフを切り替える
```

**API:**
```python
from bach_api import injector

injector.process("text")              # すべてのインジェクターをテキストに適用
injector.check_between("task done")   # タスク完了後の品質チェック
injector.tool_reminder()              # 利用可能なツール (1 回のみ)
injector.assign_task()                # 次のタスクを自動的に割り当てる
injector.time_check()                 # 時刻 + メッセージ
injector.status()                     # すべてのインジェクターの状態
injector.toggle("strategy_injector")  # 個別にオン/オフ
injector.set_mode("api")              # コンテキストから CLI ヒントをフィルタする
```

---

## CHANGELOG

### v3.10.0 (2026-10-25)

- **エージェントの入口**: 冒頭に新しいセクション「ALS AGENT OFFENE TASKS ABARBEITEN」を追加 (ブート、タスク選択、リース取得、Worktree、テスト、PR、結果提出、次のタスク。限界。既知のギャップ)。目的: エージェント (Claude、Codex、Kimi、Gemini) がこのファイルだけで自律的にブートできるようにすること。
- **非推奨の表示**: `bach task claim` および (5.2) の „weise sie dir zu“; 新しいセクションより下の数値とアーキテクチャ概要は 2026-03-12 時点のものであり、再計測されていない。
- 内容は削除していない。モード A、B、C は変更なし。

### v3.8.0 (2026-03-12)

- **ハンドラのディスカバリー**: セクション (2) に新しい段落 -- `bach help <検索語>` を 109+ ハンドラの主要なディスカバリー機構として文書化
- **検索リファレンス**: `bach help list`、`bach tools search`、`bach skills search` を検索の入口として提示
- **テーマパッケージ WEB**: `web_parse` と `web_scrape` ハンドラを参照する新しいパッケージ
- **スキル `webseiten-lesen`**: Web コンテンツ抽出のための決定木を備えた新しいワークフロースキル
- **ドキュメント**: ハンドラは CLI 経由だけでなく SKILL.md 内でも見つけられるようになった

### v3.2.0-butternut (2026-02-28)

- **エージェント CLI**: `AgentLauncherHandler` -- `bach agent start/stop/list` によるエージェントの直接制御
- **プロンプトシステム**: `PromptHandler` -- `bach prompt list/add/edit/show/board-create` による集中プロンプト管理
- **SharedMemory の拡張**: `current-task`、`generate-context`、`conflict-resolution`、`decay`、`changes-since`
- **USMC ブリッジ**: United Shared Memory Client (`hub/_services/usmc_bridge.py`)
- **llmauto チェーン**: Claude プロンプトを Chain ステップとして使用 + `bach://` URL 解決
- **スケジューラ**: `job_type='chain'` + `daemon_jobs` → `scheduler_jobs` への改名
- **新 API モジュール**: `bach_api` の `agent`、`prompt`
- **移植**: SharedMemoryHandler、ApiProberHandler、N8nManagerHandler、UserSyncHandler、Stigmergy サービス
- **テーブル**: 4 つの新規 DB テーブル: `prompt_templates`、`prompt_versions`、`prompt_boards`、`prompt_board_items`
- **109+ ハンドラ** (従来: 75+)

### v2.6.0 (2026-02-13)

- **ディレクトリ再構成**: エージェント、スキル、コネクター、パートナーの明確な分離
  - `skills/_agents/` → `agents/` (system/ 直下のトップレベル)
  - `skills/_experts/` → `agents/_experts/` (エキスパートはエージェントに属する)
  - `skills/_workflows/` → `skills/workflows/` (ワークフローは現在プロトコルと呼ばれる)
  - `skills/_connectors/` → `connectors/` (system/ 直下のトップレベル)
  - `skills/_partners/` → `partners/` (system/ 直下のトップレベル)
- **PathHealer**: 影響を受けるすべてのファイルでパスを自動修正
- **コンポーネント型 `protocol`**: 型階層で `workflow` を置き換え
- **コンポーネント型 `connector`**: 外部接続 (MCP、API) 用の新設
- **アーキテクチャ図**: AGENTS LAYER と CONNECTORS & PARTNERS を独立セクションとして追加
- **SKILL.md v2.6**: すべての参照、テーブル、図を新構造に適合

### v2.5.0 (2026-02-13)

- **自己拡張システム**: AI パートナーが自ら新しい能力を獲得できる
  - `bach skills create <name> --type <typ>` (5 つの型: tool、agent、expert、handler、service)
  - `bach skills reload` (ホットリロード: レジストリ + ツール + スキル DB)
  - 自己拡張ループ: 認識 → 作成 → 登録 → 使用 → 振り返り
- **フックフレームワーク**: 14 のライフサイクルイベントを持つ拡張可能なイベントシステム
  - `core/hooks.py` - HookRegistry シングルトン、優先度、イベントログ
  - `hub/hooks.py` - CLI: `bach hooks status/events/log/test`
  - 統合先: 起動、終了、タスク、メモリー、レッスン、スキル、アプリ
  - フック ≠ インジェクター: 技術的フレームワーク 対 認知サブシステム
- **メールハンドラ**: ドラフト安全機構付き Gmail API (send、draft、confirm、cancel)
- **レジストリのホットリロード**: `app().reload_registry()` を再起動なしで実行
- **ルール (f) 自己拡張**: 「能力が足りなければ、自分に与えよ!」
- **ドキュメント**: hooks.txt、self-extension.txt、cli.txt、skills.txt、ROADMAP.md

### v2.4.0 (2026-02-08)

- **MCP サーバー v2.2**: 23 ツール、8 リソース、3 プロンプト - MCP の 3 プリミティブすべて
- **メールアダプター**: notify.py 内の SMTP_SSL (BachForelle から移植)
- **BachFliege + BachForelle**: 分析してアーカイブ済み (`docs/_archive/con5_BACHFLIEGE_BACHFORELLE_ARCHIV.md`)

### v2.3.0 (2026-02-06)

- **ルール体系を全面的に改訂**: IMMER → アクセス種別 → モード別
- **3 つのモード**: A (ライブラリ)、B (混在)、C (セッション) に [B]、[C]、[B/C] タグを付与
- **共同開発の原則**: 「BACH の利用は共同開発である」を中核ルールとして明記
- **bach_api.py の拡張**: session、partner、logs、msg、tools、help、injector
- **14 の API モジュール**: すべてのハンドラへの完全なプログラム的アクセス
- **API 経由のインジェクター**: 6 つのインジェクターすべてをライブラリから利用可能 + CLI フィルタ
- **API によるセッションライフサイクル**: `session.startup()` / `session.shutdown()`
- アーキテクチャ図を更新 (Core Layer + bach_api)
- すべてのセクションにモード表示を付与

### v2.2.0 (2026-02-06)

- 2 つのアクセス経路 (CLI + ライブラリ API) を文書化
- bach_api.py の基本モジュール: task、memory、backup、steuer、lesson、status

### v2.1.0 (2026-02-04)

- スキルアーキテクチャ v2.0 を統合
- バージョンチェックの原則を導入
- 標準ヘッダーを文書化
- スキルソースの分類を追加
- インジェクターの部分機能を文書化

### v2.0.2 (2026-01-01)

- 初版

---

**BACH スキルアーキテクチャ v2.0**