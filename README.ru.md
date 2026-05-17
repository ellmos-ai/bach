# BACH - текстовая операционная система для LLM

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)

**Версия:** v3.12.4-earth  
**Статус:** Production-Ready  
**Лицензия:** MIT

## Обзор

**BACH** - это текстовая операционная система для Large Language Models (LLMs). Она помогает моделям работать автономно, учиться, координировать задачи и хранить знания в устойчивой структуре.

BACH входит в семейство **ellmos** и предоставляет инфраструктуру для управления задачами, структурированной памяти, автоматизации, специализированных агентов, инструментов, рабочих процессов и orchestration для нескольких LLM.

## Многоязычность

Текущий snapshot BACH включает шесть языков: немецкий (`de`), английский (`en`), испанский (`es`), русский (`ru`), японский (`ja`) и китайский (`zh`).

Это проверено по `system/exports/translations/languages_config.release.json` и `system/exports/translations/manifest.release.json`: release экспортирует 17.407 переводческих записей и locale-файлы для всех шести языков. Часть переводов создана автоматически и должна пройти проверку перед использованием как финальная публичная документация.

## Основные возможности

- **113+ handlers** для CLI и API
- **550+ инструментов** для файлов, анализа и автоматизации
- **1870+ reusable skills**
- **59 шаблонов workflow**
- **4100+ tests**
- **Структурированная память** с facts, lessons и несколькими уровнями контекста
- **Агенты и эксперты** для сложной оркестрации
- **Chat service** с Telegram bot, Control API, Web Dashboard и System Tray

## Установка

```bash
git clone https://github.com/ellmos-ai/bach.git
cd bach
pip install -e .
bach setup preflight
bach setup full-install
```

## Быстрый старт

```bash
python bach.py --startup
python bach.py task add "Analyze project structure"
python bach.py agent list
python bach.py scheduler status
python bach.py --shutdown
```

## Документация

- **[Quickstart](QUICKSTART.md)** - первый workflow
- **[User Manual](BACH_USER_MANUAL.md)** - полный справочник
- **[Skills Catalog](SKILLS.md)** - доступные skills
- **[Agents Catalog](AGENTS.md)** - агенты и эксперты
- **[Workflows](WORKFLOWS.md)** - шаблоны процессов
- **[SKILL.md](SKILL.md)** - операционные инструкции для LLM

## Лицензия

MIT License - см. [LICENSE](LICENSE).
