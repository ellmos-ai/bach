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
<!-- T2619-CONT -->