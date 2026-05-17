# BACH - 中文

[English](../en/README.md) | [Deutsch](../de/README.md) | [Español](../es/README.md) | [Русский](../ru/README.md) | [日本語](../ja/README.md) | [中文](../zh/README.md)

BACH 是面向 Large Language Models (LLMs) 的文本操作系统，提供结构化记忆、任务管理、自动化、agents、tools、workflows 和 multi-LLM orchestration。

此页面是为用户和 crawlers 准备的语言入口。主要中文 README 在这里: [../../../README.zh.md](../../../README.zh.md)。

## 多语言支持

当前 release 启用六种语言: `de`, `en`, `es`, `ru`, `ja`, `zh`。这一点可在 [../../../system/exports/translations/languages_config.release.json](../../../system/exports/translations/languages_config.release.json) 和 [../../../system/exports/translations/manifest.release.json](../../../system/exports/translations/manifest.release.json) 中验证。

## 开始

```bash
git clone https://github.com/ellmos-ai/bach.git
cd bach
pip install -e .
bach setup preflight
```

更多: [Quickstart](../../../QUICKSTART.md), [User Manual](../../../BACH_USER_MANUAL.md), [Agents](../../../AGENTS.md), [Skills](../../../SKILLS.md), [Workflows](../../../WORKFLOWS.md).
