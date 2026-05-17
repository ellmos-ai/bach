# BACH - 面向 LLM 的文本操作系统

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)

**版本:** v3.12.4-earth  
**状态:** Production-Ready  
**许可证:** MIT

## 概览

**BACH** 是面向 Large Language Models (LLMs) 的文本操作系统。它帮助模型自主工作、学习、组织任务，并以持久结构管理知识。

BACH 是 **ellmos** 系列的一部分，提供任务管理、结构化记忆、自动化、专业代理、工具、工作流以及多 LLM 编排的基础设施。

## 多语言支持

当前 BACH snapshot 启用了六种语言: 德语 (`de`)、英语 (`en`)、西班牙语 (`es`)、俄语 (`ru`)、日语 (`ja`) 和中文 (`zh`)。

这一点已通过 `system/exports/translations/languages_config.release.json` 和 `system/exports/translations/manifest.release.json` 验证: release 导出 17,407 条翻译记录，并为六种语言提供对应的 locale 文件。部分翻译为自动生成，在作为最终公开文档使用前仍需要人工审阅。

## 核心功能

- 面向 CLI 和 API 的 **113+ handlers**
- 用于文件处理、分析和自动化的 **550+ tools**
- 可复用的 **1870+ skills**
- **59 workflow templates**
- **4100+ tests**
- 支持 facts、lessons 和多层上下文的结构化记忆
- 用于复杂任务编排的 agents 和 experts
- 带 Telegram bot、Control API、Web Dashboard 和 System Tray 的 Chat service

## 安装

```bash
git clone https://github.com/ellmos-ai/bach.git
cd bach
pip install -e .
bach setup preflight
bach setup full-install
```

## 快速开始

```bash
python bach.py --startup
python bach.py task add "Analyze project structure"
python bach.py agent list
python bach.py scheduler status
python bach.py --shutdown
```

## 文档

- **[Quickstart](QUICKSTART.md)** - 第一个 workflow
- **[User Manual](BACH_USER_MANUAL.md)** - 完整手册
- **[Skills Catalog](SKILLS.md)** - 可用 skills
- **[Agents Catalog](AGENTS.md)** - agents 与 experts
- **[Workflows](WORKFLOWS.md)** - 流程模板
- **[SKILL.md](SKILL.md)** - 面向 LLM 的运行指令

## 许可证

MIT License - 见 [LICENSE](LICENSE)。
