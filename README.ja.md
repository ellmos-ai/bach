<!-- worldset: {"translated_from_sha256": "baef5439fd109dda96de98527f6aa5a716025d9b1f22e231c25c7cc1a5ab1677", "translator": "gpt-6-luna", "translated_at": "2026-10-25T04:20:48.813077+00:00"} -->
<img src="assets/banner_v2.png" width="100%" alt="BACH Banner">

# ellmos BACH — LLM向けテキストベースのオペレーティングシステム

> すべてを結びつける流れ。

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![ライセンス：MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![バージョン](https://img.shields.io/badge/Version-v3.15.0-orange)](CHANGELOG.md)
[![ステータス](https://img.shields.io/badge/Status-Production--Ready-brightgreen)](ROADMAP.md)
[![テスト](https://img.shields.io/badge/Tests-4436%20collected-blue)](system/tests/)
[![最終確認](https://img.shields.io/badge/Last_Checked-2026--10--18-brightgreen)](CHANGELOG.md)
[![責任](https://img.shields.io/badge/Haftung-%C2%A7_521_BGB-blue)](https://www.gesetze-im-internet.de/bgb/__521.html)
[![セキュリティSLA](https://img.shields.io/badge/Security_Response-48h_dual_SLA-blue)](SECURITY.md)

**バージョン：** v3.15.0

## 🎬 デモ動画

ダッシュボード、Codexバックエンド、オペレーターによる操作を含む、BACHのライブ動作を2分22秒で紹介：

[![BACHのデモ — ローカルファーストのLLMオペレーティングシステム（2:22）](assets/bach-demo-preview.png)](https://youtu.be/Gv5nxF8HssU)

### スクリーンショット（近日公開）
BACH GUI 0.2.29の実際のスクリーンショットは近日公開。命名規則と最小範囲は画像規約を参照：[assets/gui/README.md](assets/gui/README.md)。

## OpenAI CodexとGPT-5.6で構築

BACHは、Codexを第一級のランタイムバックエンドとして、またリポジトリ開発のパートナーとして使用する。正確な自動化スケジュール、モデルルート、監査可能なセッションIDについては、以下の[検証済みBuild Week帰属情報](#openai-build-week--codex-and-gpt-56)を参照。

## 言語

README ドキュメントは 11 言語で利用できます。実行時翻訳の対応範囲は別途扱われ、現在のリリーススナップショットには de、en、es、ru、ja、zh が含まれます。

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [简体中文](README.zh.md) | **日本語** | [Русский](README.ru.md) | [Français](README.fr.md) | [हिन्दी](README.hi.md) | [العربية](README.ar.md) | [বাংলা](README.bn.md) | [Português](README.pt.md)

現在のリリーススナップショットでは、`system/exports/translations/languages_config.release.json`の`de`、`en`、`es`、`ru`、`ja`、`zh`が有効になっており、`system/exports/translations/locales/`に対応するロケールファイルを出力する。クローラーや各言語への直接アクセス向けに、`docs/i18n/<lang>/`には各言語専用の`README.md`も用意されている。

上記は利用可能なドキュメント翻訳の言語を示す。GUI、CLI、APIの実行時の言語サポートはリリース設定によって決まり、このREADMEを翻訳しても実行時サポートは拡張されない。

<p align="center">
  <img src="overview.jpg" alt="BACH Overview" width="700">
</p>

## 概要

**BACH**は、Large Language Models（LLM）が自律的に作業し、学習し、自らを組織化できるテキストベースのオペレーティングシステム。**ellmos**（Extra Large Language Model Operating Systems）ファミリーの一員として、タスク管理、ナレッジ管理、自動化、LLMオーケストレーションのための包括的な基盤を提供する。

## 🧭 コアガバナンス：アイデンティティと権限フロー、3要因ドキュメントモデル、透明な意思決定処理ルール

BACHとOceanは、**透明で検査可能、ユーザー設定可能な意思決定処理ルール（`decision_processing_rules`）**を通じて自律的な挙動を統治します。すべての権限チェック、ドキュメント乖離の分類、およびアクション分岐は、決定論的な監査レシート（`decision_rule_trace`）を出力します。

### 1. アイデンティティ、3層権限トンネリング、および「権限の砂漠」からの保護

- **アイデンティティ vs 権限：** **アイデンティティ**はOSアカウントと登録されたデバイス/チャネルに固定されます（秘密情報はローカルキーリング内に保持され不可視）。**権限**は、**オペレーターチャネル**（コンソール、Telegram、システムGUIチャット）を通じてユーザーから委任されたサブエージェントおよびバックグラウンドワーカーへと流れます。
- **自然（自動侵食とドリフト）vs テラフォーミング（意図的な変更）：** 侵食とドリフトはシステムの通常利用（コンテキスト圧縮、セッション境界、コードの進化）によって自然に発生します。有効な決定を期限切れにする人工的なCronジョブはありません。`DECISIONS.md`、`AKTUELLER-PLAN.md`、`USER.md`、またはコードに対する意図的な編集は**テラフォーミング**であり、古いエントリは元のソース内で直接 `superseded` とマークされます。
- **3層権限トンネリングと内向き優先カスケード（`open-ocean/tools/escalation_ladder.py`）：**
  1. **第1層 — セマンティック権限トンネリング（日常の可逆的な作業の約80%）：** アクティブな目標/計画（`authority_ref`, `active_goal_or_plan_id`）の範囲内で迅速に実行し、不必要なユーザー確認を防ぎます（**`error_authority_desert` / 権限の砂漠**）。
  2. **第2層 — 決定論的引用証拠トンネル（閾値移行の約15%、`ellmos-authority-evidence`）：** NemoFoldの `evidence.py` に由来し、渡された `literal_quote` が元のソース（`DECISIONS.md`, `transcript.jsonl`, `AKTUELLER-PLAN.md`）に**一字一句違わず**かつ `superseded` されていない状態で存在するかを1ミリ秒未満（`validate_quote_tunnel_evidence`）で検証します。
  3. **第3層 — ハードな暗号化およびロックゲート（不可逆または高リスクなアクションの約5%）：** `lock_status.py`（`LOCK.user.*`）、ソルト付き秘密の質問（`ellmos-installer`）、およびEd25519 `capability-grant.v1` 証明書によって強制されます。

```mermaid
flowchart TD
    classDef userLayer fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef cogLayer fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46
    classDef tunnelLayer fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e
    classDef errorLayer fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b

    subgraph L0["1. 起源：自然（ドリフト）vs テラフォーミング（意図的）"]
        U["オペレーターチャネルのユーザー
(コンソール、Telegram、GUIチャット)"]:::userLayer
        TF["テラフォーミング（意図的な形成）
DECISIONS.md, Plan, USER.md, policy-registry"]:::userLayer
        NAT["自然と地殻変動（自動ドリフト）
コンテキスト圧縮、セッション移行、時間経過"]
        U -->|"形成"| TF
    end

    subgraph L1["2. 認知システムと3層権限トンネリング"]
        COG["認知システム + WorkflowHookers
(メタ認知、目標、計画、スキル -> 行動への意欲)"]:::cogLayer
        T1["第1層 (~80% 可逆的)
セマンティック権限トンネリング"]:::tunnelLayer
        T2["第2層 (~15% 閾値)
決定論的引用トンネル (<1ms 一字一句検証)"]:::tunnelLayer
        T3["第3層 (~5% 不可逆)
ハードゲート (LOCK.user / セキュリティハッシュ / Ed25519)"]:::tunnelLayer
        U --> COG
        TF --> COG
        COG --> T1
        COG --> T2
        COG --> T3
        TF -.->|"一字一句一致"| T2
        NAT -.->|"侵食された引用は失敗"| T2
    end

    subgraph L2["3. 権限チェッカー、内向き優先カスケードと内省"]
        CHK{"権限チェッカー:
行動が許可されているか？"}:::tunnelLayer
        ACT["YES: 即座に実行する"]:::cogLayer
        ASK["NO: 内向き優先カスケード (Inward-First)
1. 目標/コンテキスト -> 2. DECISIONS/USER.md
-> 3. 親オーケストレーター -> 4. ユーザーゲート"]:::tunnelLayer
        REF["アクション後の内省と学習
権限の砂漠 (error_authority_desert) を防止"]:::errorLayer

        T1 --> CHK
        T2 --> CHK
        T3 --> CHK
        CHK -->|"Yes"| ACT
        CHK -->|"No"| ASK
        ASK -->|"解決済"| ACT
        ACT --> REF
    end
```

### 2. 3要因ドキュメントモデルと設定可能な意思決定処理ルール（`system/tools/llmauto/config.json`）

自動ドキュメント検証（`ellmos-doc-keeper` + NemoFoldクレーム検証）がドキュメント（`system/docs/help/*.txt`, `README.md`, `SKILL.md`, GUI `/help`）と測定されたコード実態との乖離を検出した際、**望まれる設計仕様を盲目的に上書きすることは決してありません**。代わりに、`classify_doc_reality_diff()` が乖離を**3つの決定論的要因**に分類し、`resolve_doc_machine_dispatch()` が透明で組み合わせ可能な**意思決定処理ルール**に従ってルーティングします：

| 要因 (`classify_doc_reality_diff`) | 意味 | 透明なアクション分岐（`selected_branches` — 単独または組み合わせ） |
|---|---|---|
| **1. `unintended_erosion`** *(意図しない侵食 / ドリフト)* | ドキュメントは本来の挙動を示しているが、コードやサービスが意図せず破損またはドリフトした。 | **ドキュメントのSOLL（あるべき姿）を維持** + IST（現状）警告を付与 + **`["local_taskplan", "user_notification"]`** をディスパッチ（バックグラウンドワーカー向けP1修復タスクを作成しユーザーに通知。必要に応じて `local_genie_marblerun` や `gitlab_wishes_come_true` と組み合わせ可能）。 |
| **2. `planned_terraforming_pending`** *(計画されたテラフォーミング未完了)* | ドキュメントはロードマップや `DECISIONS.md` からの計画された目標設計（SOLL）を記述しているが、コードがまだ未完成。 | 既存タスクを確認・調整、または **`["local_taskplan"]`** でP2実装タスクを作成 + ドキュメント内で **SOLL（タスクID付き）** と **IST** を明確に分離。 |
| **3. `completed_terraforming_doc_lag`** *(テラフォーミング完了とドキュメント遅延)* | コードは意図的に進められたが（コミット/PR/`task_status=done` で検証済み）、ドキュメントの更新が遅れている。 | **`["local_doc_update"]`** を実行：`.txt` CLIヘルプ、`.md` ドキュメント、CLI/APIリファレンス、および多言語翻訳（`de/en/es/ja/ru/zh`）をローカルで自動更新。 |

```mermaid
flowchart TD
    classDef probe fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e
    classDef c1 fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b
    classDef c2 fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef c3 fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46

    subgraph S1["1. クレーム検証と3要因分類"]
        CLAIM["ドキュメントの主張を抽出 (docs/help/*.txt, README, SKILL.md, GUI /help)
& コード/CLI/テストの実態をプローブ"]:::probe
        CLS{"3要因クラシファイア
(classify_doc_reality_diff)"}:::probe
        U1["要因1: 意図しない侵食
(コードが意図せず破損/ドリフト)"]:::c1
        U2["要因2: 計画されたテラフォーミング未完了
(ドキュメントはSOLL、コードは未完成)"]:::c2
        U3["要因3: テラフォーミング完了
(コードは意図的に更新済、ドキュメント遅延)"]:::c3
        CLAIM --> CLS
        CLS --> U1
        CLS --> U2
        CLS --> U3
    end

    subgraph S2["2. 透明で組み合わせ可能な意思決定処理ルール (config.json)"]
        RULE{"意思決定ルールエンジン
(resolve_doc_machine_dispatch)
要因、トリガー、または明示的な上書き"}:::probe
        B1["分岐A: local_taskplan (デフォルト)
バックグラウンドワーカー (Buddha / Cloud) 向けに
ローカルtaskplanにP1/P2修復・構築タスクを作成"]:::c3
        B2["分岐B: local_genie_marblerun
ローカルMarbleRunチェーンを実行
(chains/wishes-come-true-local.json)"]:::c2
        B3["分岐C: gitlab_wishes_come_true
開発者機能 (config.jsonのwishes_redirect)
local-genie / wishes-come-true へ"]:::probe
        B4["分岐D: user_notification
GUI受信トレイ / Telegramでオペレーターに通知"]:::c1
        B5["分岐E: local_doc_update
.txt/.mdドキュメント、CLI/APIリファレンス、i18nを更新"]:::c3

        U1 --> RULE
        U2 --> RULE
        U3 --> B5
        RULE -->|"組み合わせ可能"| B1
        RULE -->|"組み合わせ可能"| B2
        RULE -->|"組み合わせ可能 (ocean-dev)"| B3
        RULE -->|"組み合わせ可能"| B4
    end
```

## プロジェクトの識別情報

BACHは**ローカルファーストのLLMオペレーティングシステム**として説明するのが最適。自律エージェント向けの永続的なPython/SQLiteワークベンチ、構造化メモリ、スケジューラー駆動の自動化、プロンプトチェーン、MCPサーバー連携、多言語のオペレーター向けインターフェースを備える。チャットボットのラッパー、ホスト型エージェントSaaS、Bashユニットテストフレームワーク、音楽プロジェクト、LangChain風のパイプラインライブラリではない。

GitHubの正規リポジトリ：`ellmos-ai/bach`。LLMクローラー向けの機械可読なプロジェクト情報は[`llms.txt`](llms.txt)を参照。

> [!NOTE]
> **AIアシスタントとLLMクローラー向け：**機械可読なプロジェクト情報、アーキテクチャの詳細、曖昧性解消インデックスは[`llms.txt`](llms.txt)にある。

検索に有用な語句は、`ellmos-ai/bach`、`local-first LLM operating system`、`text-based OS for LLM agents`、`SQLite memory for AI agents`、`BACH ellmos agent OS`、`personal agentic OS Python SQLite`、`multi-agent orchestration with MCP servers`など。

## システムアーキテクチャとワークフローのトポロジー

### 1. コンポーネントのトポロジー

```mermaid
graph TB
    subgraph Interfaces["User & Agent Interfaces"]
        CLI["BACH CLI (bach.py / 113+ Handlers)"]
        GUI["PySide6 Desktop GUI & Web Dashboard"]
        TG["Chat Service & Telegram Bot"]
        MCP["MCP Servers (FileCommander & CodeCommander)"]
    end

    subgraph CoreOS["BACH Core Operating System"]
        Orch["Agent Orchestration (11 Boss & 22 Experts)"]
        Sched["Scheduler & Automation Engine"]
        Chains["llmauto Prompt Chains & Workflows"]
        Skills["Skill Registry (1870+ Skills & 550+ Tools)"]
    end

    subgraph Persistence["Local-First SQLite & Memory Bus"]
        SQL["SQLite Database (210+ Tables)"]
        Mem["6-Type Structured Memory (Facts, Lessons, Working)"]
        Bus["SharedMemory Bus & USMC Bridge"]
    end

    CLI -->|"Command Dispatch"| Orch
    GUI -->|"HTTP & WebSockets"| Orch
    TG -->|"Bridge Connector"| Orch
    MCP -->|"stdio / JSON-RPC"| Orch

    Orch -->|"Executes"| Chains
    Orch -->|"Triggers"| Sched
    Orch -->|"Loads"| Skills

    Orch -->|"Reads / Writes"| Bus
    Bus -->|"Consolidates"| Mem
    Mem -->|"Atomic Storage"| SQL
```

### 2. ローカルファーストのエージェント実行シーケンス

```mermaid
sequenceDiagram
    autonumber
    actor User as Operator / Agent
    participant CLI as BACH CLI / API Interface
    participant Hub as Core Orchestrator & Session Scope
    participant Mem as SQLite Memory & SharedMemory Bus
    participant LLM as Pluggable Backend (Local Ollama / CLI)
    participant Tool as Tool & Skill Execution Engine

    User->>CLI: Issue task or workflow command
    CLI->>Hub: Dispatch request with session token
    Hub->>Mem: Query context, lessons, and working memory
    Mem-->>Hub: Return relevant facts and active constraints
    Hub->>LLM: Formulate prompt with local context (zero egress)
    LLM-->>Hub: Stream plan and requested tool invocations
    Hub->>Tool: Execute vetted tool / handler locally
    Tool-->>Hub: Return tool execution output
    Hub->>Mem: Record new facts, lesson feedback, and audit log
    Hub-->>CLI: Format structured response (JSON / text)
    CLI-->>User: Present completed result to operator
```

<a id="openai-build-week--codex-and-gpt-56"></a>
## OpenAI Build Week — CodexとGPT-5.6

BACHはCodexを2つの異なる役割で使用する。

- **ランタイムバックエンド：**`codex-cli`は、差し替え可能な5つのチャットバックエンドの1つ。BACHエージェントは`codex exec`を通じてコーディングタスクを委任できる。
- **リポジトリ開発：**3つのCodex自動化が現在プロジェクトを保守している：`bach-daily-care-and-dev-check`、`bach-start-and-health-checks`、`bach-github-release-service`。2026年7月21日以降、すべてGPT-5.6（`gpt-5.6-terra`）に設定されている。最初の2つは毎日、リリースサービスは毎週実行される。
- **検証済みモデルルーティング：**Codexセッション`019f85c6-4339-7f13-b8e5-bf1823fd8432`で、GPT-5.6 Sol（高い推論レベル）が78件すべての自動化定義を監査し、BACHの開発・リリースジョブをTerra/highに、ヘルスチェックをTerra/mediumに振り分けた。
- **最終提出監査：**Codexセッション`019f8674-fe9a-7d91-a80f-7ee799e8ced0`でGPT-5.6 Solが保留中のBACH変更を確認・認証し、コンテストの帰属表記を修正して、ウェブスクレイピングの強化と回帰テストを完了した。

監査可能性を保つため、GPT-5.6という自動化の帰属は設定変更以降に適用される。それ以前の自動化実行では、当時のCodexモデルを使用していた。

### 主な機能

- **113以上のハンドラー**：すべてのシステム機能をCLIとAPIで完全にカバー
- **550以上のツール**：ファイル処理、分析、自動化のための豊富なライブラリ
- **1870以上のスキル**：再利用可能なワークフローとテンプレート
- **スキルソースレジストリ**：`bach skills version bach`は`system/data/skill_sources.json`を通じてリポジトリルートの正規スキルを解決し、ファイル名の曖昧な違いに左右されず、任意のCodex/Claudeユーザーコピーと比較できる
- **71のワークフローテンプレート**：すぐに使えるプロセスワークフロー
- **4400以上のテスト**：ハンドラー、サービス、GUI、MCPサーバーを対象とする包括的な自動テスト
- **ナレッジストア**：教訓、事実、マルチレベルのメモリシステム（6種類のメモリ）。新しい記録にはBACHセッションごとの来歴が追加され、旧記録の作成者は明示的に不明のまま
- **エージェントCLI**：`bach agent start/stop/list`によりエージェントを直接操作
- **エージェント診断**：`bach agent doctor [name] [--json]`は起動前にClaude CLIの可用性、ランタイムディレクトリ、スキルファイル、古いPID状態を検証する
- **エージェント運用コントロール**：`bach agent pause/resume/checkpoint/steer/clear-steer [name] [--json]`により、実行前または実行中に協調的な一時停止要求とガイダンスを設定し、安全なチェックポイントの確認を明示的に記録し、その状態を`OPERATOR_NOTES.md`に反映できる。次の`bach agent start`起動までキュー内のヒントを保持して、生成されたセッションの`CLAUDE.md`に注入し、ネストされた`operator_control`スナップショットと`queued_for_next_start`を公開して、自動化から安全にポーリングできる
- **エージェントのランタイムポリシー既定値**：`bach agent start`は`--permission-mode`、`--allowed-tools`、`--max-turns`を受け付けるようになり、エージェントごとのガードレールとしてSKILLフロントマターから同じ既定値を事前読み込みできる
- **スケジューラー診断**：`bach scheduler doctor [--json]`と`bach scheduler session doctor [--json]`は、バックグラウンドサービスの起動前に自動化スクリプト、PID状態、DB/設定/プロファイルの各サーフェスを検証し、復旧手順を提案する
- **セッション指示コントロール**：`bach scheduler session pause/resume/steer/clear-steer [--json]`により、デーモン設定を手動で編集せずに、次のプロファイル別自動セッションを保留または方向転換できる
- **スケジューラー実行コントロール**：`bach scheduler pause/resume/steer/clear-steer [--json]`は期限到来ジョブ向けにも同じ運用コントロールを提供する。グローバル一時停止や実行ガイダンスのキューイングを制御ファイル編集なしで行え、キュー内のスケジューラー指示を次回の安全なチェックポイント用プロンプト経路に載せる
- **機械可読な制御・ステータスサーフェス**：`bach agent list/start/stop/pause/resume/checkpoint/steer/clear-steer/status --json`、`bach scheduler status/jobs/session status --json`、`bach scheduler session pause/resume/steer/clear-steer --json`。キュー状態、`queued_for_next_start`、タイムスタンプ、チェックポイント確認、オペレーターノートのメタデータを含み、自動化から安全にポーリングできる
- **ワーカーキュー診断**：[選択状況の観測](docs/worker-queue.md)は、既存のワーカーAPIを通じて候補数を日付付きで示し、バインディング、カテゴリ、優先度、タグ、所有権、ネイティブなクレームによる却下理由を明らかにする。アイドル時のポーリングはモデルブロックに数えない。認証済み設定レスポンスには別個の読み取り専用選択ポリシーが含まれ、既存のGUIカードには読みやすい待機サマリーが表示される。これらの観測にタスクや結果を受け入れる権限はない
- **アップグレードのドリフトと修復**：`bach upgrade list <path> --json`、`bach upgrade status/check --json`、`bach upgrade repair [--dry-run] [--version <tag>]`により、壊れた配布メタデータに対する自動化安全なバージョン、状態、ドリフト、修復ヒント、復旧が利用できる
- **パスサーフェス**：`bach path`は正規のシステム/ワークスペース/DBパス、検証、解決ヘルパー、DB上書きをテキストまたはJSONで提示する
- **プロンプトシステム**：ボードシステムとバージョン管理を備えた一元的なプロンプト管理
- **インストールセキュリティゲート**：`skills install`/`plugins load`の際に静的な事前ロードスキャンが明らかなコードインジェクションパターンをブロックする。MCPセットアップは許可リストにあるパッケージと設定だけを検証し、不一致時は安全側で失敗する。プラグインセットアップ契約ではshell/desktop/MCPの明示的なチェックが必要になり、ブロックされたローカルインポートは隔離される
- **マニフェスト優先のプラグイン**：`bach plugins inspect`はプラグインのランタイムコードをインポートせず、アクティベーション、プロバイダー/モデル、セットアップ、機能メタデータをプレビューする
- **構造化された`bach_api`コア**：`task`と`memory`は`dir(...)`を通じて検出可能なメソッドを提供するようになり、一般的な読み書き操作にはPythonオブジェクトを返し、旧来のハンドラー形式の呼び出しには`raw(...)`を引き続き提供する
- **SharedMemoryバス**：競合検出と減衰を備えたマルチエージェント協調
- **USMCブリッジ**：エージェント間通信のためのUnited Shared Memory Communication
- **llmautoチェーン**：Claudeプロンプトをチェーンのステップとして扱い、`bach://` URLを解決する
- **チャットサービス**：複数バックエンド対応のTelegramボット（5バックエンド）、Control API、Webダッシュボード、クロスプラットフォームのシステムトレイ

## インストール

```bash
# Clone the repository
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Install dependencies and make `bach` CLI available
pip install -e .

# Pre-flight check
bach setup preflight

# Full install (MCP servers, hooks, secrets, user profile)
bach setup full-install
```

### オプションのオペレーターコンソール

既存の`ellmos-unified-gui`オペレーターコンソールは、別プロセスや別のUnified GUI設定を追加せずに、BACHダッシュボードへマウントできる。

```bash
pip install -e ".[console]"
BACH_GUI_CONSOLE_ENABLED=1 python system/gui/server.py
```

このマウントは既定で無効で、`/control`を使用する。別の絶対URLパスを指定するには`BACH_GUI_CONSOLE_PREFIX`を設定する。オプションパッケージがない、またはマウントできない場合でも、BACHダッシュボードはコンソールなしで動作を続ける。BACHは別のログイン機構を導入せず、BACHホストではUnified GUIの既存のケイパビリティベースの動作を維持する。BACHダッシュボードは現在`AUTH_ROLE`ホストセッションを提供しないため、このマウントは既定のループバックアドレス、または既存の信頼できるアクセス境界の内側で運用すること。

## MCPサーバー（Claude Code連携）

BACHには、Claude Code、Cursor、その他のIDEと連携するための組み込みPython MCPサーバーと2つのコンパニオンサーバーがある。

```bash
# Start the built-in BACH server (stdio)
bach mcp serve

# Install and configure MCP servers (recommended)
python system/bach.py setup mcp

# Or manually via npm:
npm install -g ellmos-codecommander-mcp ellmos-filecommander-mcp
```

- **BACH MCPサーバー**：ハンドラーAPIを通じてBACHのリソース、ツール、プロンプトを提供（`bach mcp serve`）
- **[ellmos-codecommander-mcp](https://www.npmjs.com/package/ellmos-codecommander-mcp)** v1.3.14：コード分析とリファクタリングのツール（21ツール）
- **[ellmos-filecommander-mcp](https://www.npmjs.com/package/ellmos-filecommander-mcp)** v1.9.1：ファイル管理と一括操作（46ツール）

## クイックスタート

```bash
# Fast, side-effect-free metadata
python bach.py --version
python bach.py --help

# Start BACH
python bach.py --startup

# Create a task
python bach.py task add "Analyze project structure"

# Manage agents
python bach.py agent list
python bach.py agent start bueroassistent

# Manage prompts
python bach.py prompt list
python bach.py prompt add "My Prompt" --content "..."

# Check scheduler status
python bach.py scheduler status

# Import versioned everyday-data exports (idempotent)
python bach.py abo import PATH/abotracker-export-v1.json
python bach.py versicherung import PATH/bach-fin-insurances-v1.json

# Register recurring imports only after a valid export file exists
python bach.py abo schedule-import PATH/abotracker-export-v1.json --interval 24h
python bach.py versicherung schedule-import PATH/bach-fin-insurances-v1.json --interval 24h

# Preview and refresh the current monthly/year-to-date finance summary
python bach.py haushalt financial-summary refresh --dry-run
python bach.py haushalt financial-summary refresh

# Shut down BACH
python bach.py --shutdown
```

### Pythonプログラムからのクイックスタート

```python
from bach_api import get_api

# Initialize the lightweight, side-effect-free BACH API client
api = get_api()

# Create a tracked task
task = api.task.add("Explore local agent environment")
print(f"Task created: {task.id} - {task.title}")

# Query system status
status = api.system.status()
print(f"BACH status: {status.state} (Active handlers: {status.handlers_count})")
```

`--version`、`--help`、コマンド別ヘルプ、グローバル`--dry-run`の起動経路では、AutoLogger、ProSync、アクティビティ追跡を実行しない。通常のコマンドはProSyncのpull開始前にその旨を通知し、起動時間を15秒以内に保つ。同期経路が遅く、明示的なローカル予算が必要な場合は`BACH_PROSYNC_STARTUP_TIMEOUT_SECONDS`を1から300の値に設定する。pullが失敗またはタイムアウトした場合、BACHは続行するが、そのプロセスの終了時pushは登録しない。

インポートコマンドには正確なスキーマ`abotracker-export-v1`と`bach.fin_insurances.v1`が必要。AboTrackerの請求サイクルを、次回の支払日の確定情報として扱うことはない。スケジュールジョブは実行中の冪等なファイルインポートであり、現在のソースファイルが検証に通った後にのみ作成される。

財務サマリーでは、メールから観測した支出と、現在の定期購読のランレートを分けている。計算とダッシュボードの読み取りでは、旧形式のサブスクリプション重複をプロバイダー単位で重複排除する。競合する重複は推測や削除を行わず、安全側で処理を停止する。

## コアコンポーネント

ローカル推論では、既存のモデル呼び出し境界で明示的なホスト予約ポリシーを適用できる。ネイティブなモデルID、設定されたコンテキストとメモリの余裕、タスク・スロット・ランタイム永続化用の空き容量を確認する。待機時には推論の所有者を返し、ツールを再実行せずに現在のセッションを保持する。この予約バリアは任意であり、モデルスロットコントローラーを置き換えたり、モデルの容量を保証したりするものではない。設定、検証、インストール時とランタイム時の別個のゲートについては、[ローカルモデル予約](docs/architecture/LOCAL-MODEL-RESERVE.md)を参照。
[モデルソケット契約](docs/architecture/MODEL-SOCKETS.md)は、ネイティブなダイアログとコネクターの呼び出しを安定したエージェントIDに結びつけ、明示的な移行中に設定済みコネクターのターゲットを投影し、既存のダイアログコンテキストを保つ。ソース検証だけで、ネイティブ移行やモデル容量が証明されるわけではない。


### 1. タスク管理
優先順位、期限、タグ、コンテキスト追跡を備えた完全なGTDシステム。

### 2. ナレッジシステム
事実、教訓、自動統合機能を備えた構造化メモリシステム（6種類のメモリ、210以上のDBテーブル）。

### 3. エージェントフレームワーク — Oceanロール、デュアルルーティング、柔軟なプロバイダーソケット (`ellmos.role-socket-catalog.v1`)
Ocean/BACHアーキテクチャでは、実績のあるBACHの**ボスエージェント（コーディネーター）**と**ドメインエキスパート**が完全に維持されつつ、**柔軟なプロバイダーソケット（`clutch` + `agents-heart` 経由の `model_sockets`）**に接続された**プロバイダー非依存のOceanロール（`roles[]`）**として動作します：

- **デュアルルーティング（セマンティック + 決定論的）：**
  - **セマンティックルーティング：** アンブレラスキル（`projekt-pipeline-umbrella`, `therapie-umbrella`, `selbstmanagement` など）と `semantic-persona-routing`（`persona_router.py`）がタスクを動的にルーティングし、適切なスキルバンドルとペルソナコンテキストをアクティブ化します。
  - **決定論的ルーティング：** `ellmos-controlcenter-mcp`（`controlcenter_resolve_semantic_route`, `controlcenter_switch_profile`, `controlcenter_find_skill`）が、ハルシネーションのない厳格なルールベースのルーティングとプロファイル切り替えを提供します。
- **柔軟なプロバイダーソケット（`reasoning_coordinator`, `domain_specialist`, `fast_worker`）：** ロールが特定のベンダーに固定されることはありません。各ロールは標準化されたソケットに接続され、実行時に **Claude (`claude`)**、**OpenAI/Codex (`codex`)**、**Gemini/Antigravity (`agy`)**、**Kimi (`kimi`)**、**ローカルOllama (`ollama`)**、または **OpenRouter (`openrouter`)** に解決されます。
- **3タブエージェントライブラリ（`/agenten/bibliothek`, `ellmos.agent-library.v1`）：** `discover_ocean_agent_library_templates()` が、BACHコーディネーター/エキスパートカタログ（`ati`, `bueroassistent`, `finanz-assistent`, `gesundheitsassistent`, `persoenlicher-assistent`, `produktivitaet` + 22エキスパート）および9つのOceanモジュールリポジトリ（`task-master`, `ticket-master`, `MarbleRun`, `system-auditor`, `compare-race`, `ellmos-installer`, `foerderplaner`, `ai-media-editor`, `clip-storyboard-director`）で宣言された**17の明示的モジュールロール（`roles[]`）**から、GUIとCLIのエージェントライブラリを自動的に構成します。
- **オペレーター制御：** `bach agent start/stop/list/pause/resume/checkpoint/steer` により、ライブ実行の管理、起動前の事前指示（`OPERATOR_NOTES.md`）、安全なチェックポイント確認を制御できます。

<p align="center">
  <img src="sketch_bach_boss_agents.jpg" alt="BACH Boss Agents" width="600"><br>
  <i>イラストは、BACHの元のコーディネーターロール（ati, bueroassistent, finanz-assistent, gesundheitsassistent, persoenlicher-assistent）が、17のモジュールマニフェストロールとともにOceanの柔軟なプロバイダーソケット上で動作している様子を示しています。</i>
</p>

```mermaid
flowchart TD
    classDef routeLayer fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef roleLayer fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46
    classDef socketLayer fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e

    subgraph R1["1. デュアルルーティング層 (セマンティック vs 決定論的)"]
        SEM["セマンティックルーティング
アンブレラスキル (*-umbrella) + semantic-persona-routing"]:::routeLayer
        DET["決定論的ルーティング
ellmos-controlcenter-mcp (resolve_semantic_route / switch_profile)"]:::routeLayer
    end

    subgraph R2["2. Oceanロール & 3タブエージェントライブラリ (ellmos.agent-library.v1)"]
        COORD["6つのコーディネーターロール (旧BACHボス)
ati, bueroassistent, finanz-assistent, gesundheitsassistent, persoenlicher-assistent, produktivitaet"]:::roleLayer
        EXP["22以上のドメインエキスパート & 17のモジュールロール (roles[])
tasksolver, ticket-master, ticket-writer, marble-controller, doc-keeper, race-starter, foerderplaner-expert, media-creator, storyboard-director"]:::roleLayer
        SEM --> COORD
        DET --> COORD
        COORD --> EXP
    end

    subgraph R3["3. 柔軟なプロバイダーソケット (model_sockets + clutch + agents-heart)"]
        SOCK["標準化されたモデルソケット
reasoning_coordinator | domain_specialist | fast_worker"]:::socketLayer
        PROV["プラグ可能LLMプロバイダー
Claude | Codex/GPT | Gemini/AGY | Kimi | ローカルOllama | OpenRouter"]:::socketLayer
        COORD --> SOCK
        EXP --> SOCK
        SOCK --> PROV
    end
```

### 4. プロンプトシステム
ボードコレクションと完全なバージョン管理を備えた、プロンプトテンプレートの一元管理（`bach prompt`）。

### 5. チャットサービスとブリッジシステム
Ollama、Claude CLI、Codex CLI、Claude API、OpenAI APIのLLMバックエンドを選択できるTelegramボット、Webダッシュボード付きHTTP Control API、クロスプラットフォームのシステムトレイを提供する。コネクターフレームワークでメール、WhatsAppなどの追加サービスを接続でき、USMCブリッジでエージェント間通信を行う。

### 6. 自動化
SchedulerServiceによる時刻ベースのジョブ（チェーン、タスク、スクリプト）と、フックフレームワークによるイベント駆動ワークフロー。

### 7. SharedMemory
コンテキスト生成、競合検出、減衰、差分クエリーを備えたマルチエージェント協調。

### 8. llmauto連携
チェーンのステップをLLMプロンプトとして扱い、`bach://` URLでコンテキストを動的に埋め込む。

## ellmosファミリー

すべてのellmosプロジェクトは、湧き水から大きな流れへと続く水の比喩を採用している。

| Tier | プロジェクト | 説明 | リポジトリ |
|------|------------|------|-------------|
| 1 | **USMC** | United Shared Memory Client — 共有メモリのみの泉 | [github.com/ellmos-ai/usmc](https://github.com/ellmos-ai/usmc) |
| 2 | **Rinnsal** | せせらぎ — USMC + llmauto（LLMオーケストレーション）の非常にコンパクトな構成 | [github.com/ellmos-ai/rinnsal](https://github.com/ellmos-ai/rinnsal) |
| 3 | **BACH** | すべてを結びつける流れ — 113以上のハンドラー、1870以上のスキル、エージェント、GUI、ブリッジ | [github.com/ellmos-ai/bach](https://github.com/ellmos-ai/bach) |

## ドキュメント

ネイティブなドキュメント保守、有効化、証拠の境界：
[DOCS-MAINTENANCE.md](docs/architecture/DOCS-MAINTENANCE.md)。

- **[共有GUIとエージェント制御](system/docs/help/gui-integration.txt)** — 利用側のリリース固定とアダプター確認
- **[学習ソースとレビュー候補](docs/architecture/LEARNING-SOURCE-CONTRACT.md)** — 範囲を限定したソースプレビューと非アクティブなドラフト、[コマンドヘルプ](system/docs/help/learning_en.txt)。公開や独立した再利用には別途承認が必要
- **[Ocean-BACH移行計画](OCEAN-TRANSFER-PLAN.md)** — インストーラーの境界と段階的なモジュール移行
- **[非推奨レジストリ](DEPRICATED.md)** — 置き換え、受け入れ、ロールバック

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [简体中文](README.zh.md) | **日本語** | [Русский](README.ru.md) | [Français](README.fr.md) | [हिन्दी](README.hi.md) | [العربية](README.ar.md) | [বাংলা](README.bn.md) | [Português](README.pt.md)
- **[クイックスタートガイド](QUICKSTART.md)** — 5分で最初のワークフローを起動
- **[ユーザーマニュアル](BACH_USER_MANUAL.md)** — 完全なハンドブック
- **[スキルカタログ](SKILLS.template.md)** — 利用可能なスキルのテンプレートと公開エントリーポイント
- **[エージェントカタログ](AGENTS.template.md)** — エージェントと専門家のテンプレートおよび公開エントリーポイント
- **[ワークフロー](WORKFLOWS.template.md)** — このリポジトリには42個のワークフローテンプレートが含まれる
- **[SKILLテンプレート](SKILL.template.md)** — Claude、Gemini、Ollama、Codex系エージェント向けLLM操作手順テンプレート

## 関連項目：OpenClaw

人気のオープンソースAIアシスタント[OpenClaw](https://github.com/openclaw/openclaw)とBACHはどう違うのか？

| | **BACH** | **OpenClaw** |
|---|---|---|
| **重点** | LLMオペレーティングシステム — 高い自律性、構造化メモリ、マルチエージェントオーケストレーション | パーソナルAIアシスタント — 幅広いメッセージングゲートウェイ、音声、コンパニオンアプリ |
| **ツール/スキル** | 550以上のツール、1870以上のスキル、42のワークフロー（ローカルで選定） | コミュニティ主導のスキル/プラグインエコシステム。最近のリリースではマニフェスト優先のプラグインメタデータとインストール安全性を重視 |
| **メモリ** | 減衰、競合検出、統合に対応した6種類のメモリ（210以上のDBテーブル） | `AGENTS.md`、`TOOLS.md`、`USER.md`などのブートストラップファイルと関連コンテキストファイルを含むセッション/ランタイムワークスペース |
| **エージェント** | ボス・専門家オーケストレーション（11のボスエージェントと22人の専門家）、SharedMemoryバス | マルチセッション/マルチチャンネル運用を備えたエージェントランタイム |
| **メッセージング** | Telegram、メール、WhatsApp（ブリッジシステム） | 20以上のプラットフォーム（WhatsApp、Telegram、Slack、Discord、Signal、Teams、Matrixなど） |
| **インターフェース** | CLI、Python API、PySide6 GUI、Web GUI、Telegramボット、Webチャット、システムトレイ | CLI、WebChat、macOS/iOS/Androidアプリ、音声 |
| **MCP** | 独自のMCPサーバー（FileCommander、CodeCommander） | ネイティブMCPレジストリ |
| **技術スタック** | Python 3.10以上、SQLite | TypeScript、Node.js 22以上 |
| **ライセンス** | MIT | MIT |

**要約：**BACHは構造化メモリ、自律エージェント、スケジューラー、210以上のDBテーブルなど、深さを追求する。OpenClawは20以上のメッセンジャー、ネイティブアプリ、音声、大規模なコミュニティなど、幅広さを追求する。両者は異なる思想を持ち、相互補完的。

### 競合動向

2026年10月8日時点で、OpenClawのバージョンは`v2026.9.8`（2026年10月8日リリース、ひとつ前は`v2026.9.7`）。最近の開発では、マルチエージェント応答の安定性、エージェント間のセッション割り当ての整合性、複数のCodex/ワーカープロセスにおけるメモリ使用量の削減、Windowsの起動と更新再試行の堅牢性、20言語のサイレンス設定が重視されている。BACHにも参考となるアーキテクチャ上の動きは、アトミックな復旧と更新境界（`bach update apply` / `rollback` / `upgrade repair`、`distribution_releases` v3.14.0）、監督下での再起動引き継ぎとセッション継続コンテキスト（OPS-RUN-001 / Task #1118）、シェルを使わない安全な実行（`safe_exec.py` / PR #137）、ローカルの低カーディナリティなテレメトリーカウンター（`system/core/telemetry.py` / Task #1315）。広範なモバイル/メッセージングゲートウェイとの同等機能は、引き続きBACHの中核設計の範囲外。

BACH側では、10月8日の保守・開発チェックでmain上のリポジトリ状態が検証された（origin/mainからfast-forwardし、PR #190–#253を反映：ネイティブシーケンスとmarblerunワーカーフェンシング、共有GUI v0.1.4、Astro静的アセットの許可リスト、エージェント工房とブループリント、生活ルーティンとカレンダー、ドメインカタログマニフェスト、リードタスクDBのsaltリース契約v1、CodeQLセキュリティ修正）。セッションライフサイクル管理では、パートナーGeminiの新しいセッション（`session_20261008_162204`）が完全な継続スナップショットとともに初期化された。テスト検証スイート（`test_setup_handler.py`、`test_maintain_handler.py`、`test_db_guard_hook.py`、`test_explorer_provider_wiring.py`）は138/138件が46.29秒ですべて成功した。Agent Doctor診断（`ati`、`entwickler`は7/7チェック成功、`ready: true`、`can_start: true`）、起動dry-run、Scheduler Doctor（7/7チェック成功、5件中4件のジョブが稼働）、50/50のユースケースdry-run（100%がワークフローにリンク）、ドキュメントの鮮度（`Doc_Update_Report_2026-10-08_16-25.md`で2,101文書を確認、30日レポート`2026-10_docs_report.md`）、レジストリ健全性（対応が必要な問題0件）、タスクDB監査（29件のタスクが整合）、スキル健全性（30/30スキル、10/10エージェント）、ワーキングメモリ監査（189エントリー、期限切れ0件）がすべて確認された。新しいバックアップ`userdata_2026-10-08_162846.zip`が作成された。

## ライセンス

MITライセンス。詳細は[LICENSE](LICENSE)を参照。

## サポート

- **課題：**[GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **ディスカッション：**[GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

## ドイツ語版

BACHは、大規模言語モデル（LLM）が自律的に作業し、学習し、組織化できるテキストベースのオペレーティングシステム。

ドイツ語の完全なドキュメントはこちら：**[README.de.md](README.de.md)**

---

*ellmos BACH v3.15.0 — LLM向けテキストベースのオペレーティングシステム*

---

## 責任 / 賠償責任

本プロジェクトは、ドイツ民法典（BGB）第516条以下にいう**無償のオープンソース贈与**。著作者の責任は、**BGB第521条**により、故意および重過失に限定される。選択したライセンスに応じて、GPL-3.0 / MIT / Apache-2.0の第15～16条に定める責任除外も適用される。

利用は自己責任。保守や可用性を約束せず、エラーがないことや特定目的への適合性も保証しない。

本プロジェクトは無償のオープンソース贈与である。責任は故意および重過失（ドイツ民法典第521条）に限定される。利用は自己責任。保証、保守の約束、特定目的への適合性の保証はない。

## ポータブルなエージェントスターターファイル

`start/agents/windows/`にはSTART、SYSTEM-AUDITOR、TICKET-MASTER、PINGPONG、MULTI-BOTの`.bat`ファイルが含まれ、`start/agents/posix/`には対応するシェル版が含まれる。wheelには`share/ellmos-bach/starters/`として収録される。既存のTASKPLAN Startcenterとモジュールのロール契約に処理を委譲する。Startcenterと任意のロールモジュールを含む、レビュー済みのTASKPLANバージョンを先にインストールすること。これらのファイルは個人用パス、アカウント、モデル、信頼済み自動化を設定しない。インストール時にバックグラウンドジョブを登録または起動することもない。STARTを実行してロールを選ぶ。PingPongには明示的な同期ルートと自分専用スロットが必要で、検証済みのCodex/Claudeアダプターをサポートする。MULTI-BOTは公開のgithubbot-coreパッケージを使用する。プレビューには`--dry-run --provider codex`を渡す。必要なモジュールがない場合はインストールの案内が表示される。
