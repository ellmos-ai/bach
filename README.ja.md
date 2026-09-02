# BACH - LLMのためのテキストベースOS

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)

**バージョン:** v3.13.0-bluesky  
**ステータス:** Production-Ready  
**ライセンス:** MIT

## 概要

**BACH** は Large Language Models (LLMs) のためのテキストベースOSです。LLMが自律的に作業し、学習し、タスクを整理し、知識を永続的に扱えるようにするための基盤を提供します。

BACH は **ellmos** ファミリーの一部であり、タスク管理、構造化メモリ、自動化、専門エージェント、ツール、ワークフロー、複数LLMのオーケストレーションを支えます。

## 多言語対応

現在のBACH snapshotでは、6つの言語が有効です: ドイツ語 (`de`)、英語 (`en`)、スペイン語 (`es`)、ロシア語 (`ru`)、日本語 (`ja`)、中国語 (`zh`)。

これは `system/exports/translations/languages_config.release.json` と `system/exports/translations/manifest.release.json` で確認できます。releaseには17,407件の翻訳エントリと、6言語すべてのlocaleファイルが含まれます。一部の翻訳は自動生成なので、最終的な公開ドキュメントとして使う前にレビューが必要です。

## 主な機能

- CLI/API用の **113+ handlers**
- ファイル処理、分析、自動化のための **550+ tools**
- 再利用可能な **1870+ skills**
- **59 workflow templates**
- **4100+ tests**
- facts、lessons、複数レベルのcontextを扱う構造化メモリ
- 複雑なタスクを調整するagentsとexperts
- Telegram bot、Control API、Web Dashboard、System Trayを備えたChat service

## インストール

```bash
git clone https://github.com/ellmos-ai/bach.git
cd bach
pip install -e .
bach setup preflight
bach setup full-install
```

## クイックスタート

```bash
python bach.py --startup
python bach.py task add "Analyze project structure"
python bach.py agent list
python bach.py scheduler status
python bach.py --shutdown
```

## ドキュメント

- **[Quickstart](QUICKSTART.md)** - 最初のworkflow
- **[User Manual](BACH_USER_MANUAL.md)** - 完全なハンドブック
- **[Skills Catalog](SKILLS.md)** - 利用可能なskills
- **[Agents Catalog](AGENTS.md)** - agentsとexperts
- **[Workflows](WORKFLOWS.md)** - プロセステンプレート
- **[SKILL.md](SKILL.md)** - LLM向け運用指示

## ライセンス

MIT License - [LICENSE](LICENSE) を参照してください。
