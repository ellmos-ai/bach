# BACH - 日本語

[English](../en/README.md) | [Deutsch](../de/README.md) | [Español](../es/README.md) | [Русский](../ru/README.md) | [日本語](../ja/README.md) | [中文](../zh/README.md)

BACH は Large Language Models (LLMs) のためのテキストベースOSです。構造化メモリ、タスク管理、自動化、エージェント、ツール、workflows、multi-LLM orchestration を提供します。

このページはユーザーと crawlers のための言語別エントリです。主要な日本語READMEはこちらです: [../../../README.ja.md](../../../README.ja.md)。

## 多言語対応

現在の release では6言語が有効です: `de`, `en`, `es`, `ru`, `ja`, `zh`。これは [../../../system/exports/translations/languages_config.release.json](../../../system/exports/translations/languages_config.release.json) と [../../../system/exports/translations/manifest.release.json](../../../system/exports/translations/manifest.release.json) で確認できます。

## 開始

```bash
git clone https://github.com/ellmos-ai/bach.git
cd bach
pip install -e .
bach setup preflight
```

詳細: [Quickstart](../../../QUICKSTART.md), [User Manual](../../../BACH_USER_MANUAL.md), [Agents](../../../AGENTS.md), [Skills](../../../SKILLS.md), [Workflows](../../../WORKFLOWS.md).
