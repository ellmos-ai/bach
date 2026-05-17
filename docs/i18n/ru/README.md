# BACH - Русский

[English](../en/README.md) | [Deutsch](../de/README.md) | [Español](../es/README.md) | [Русский](../ru/README.md) | [日本語](../ja/README.md) | [中文](../zh/README.md)

BACH - это текстовая операционная система для Large Language Models (LLMs): структурированная память, управление задачами, автоматизация, агенты, инструменты, workflows и multi-LLM orchestration.

Эта страница создана как входная точка для пользователей и crawlers. Основная русская README находится здесь: [../../../README.ru.md](../../../README.ru.md).

## Многоязычность

Текущий release включает шесть языков: `de`, `en`, `es`, `ru`, `ja` и `zh`. Это проверено в [../../../system/exports/translations/languages_config.release.json](../../../system/exports/translations/languages_config.release.json) и [../../../system/exports/translations/manifest.release.json](../../../system/exports/translations/manifest.release.json).

## Старт

```bash
git clone https://github.com/ellmos-ai/bach.git
cd bach
pip install -e .
bach setup preflight
```

Подробнее: [Quickstart](../../../QUICKSTART.md), [User Manual](../../../BACH_USER_MANUAL.md), [Agents](../../../AGENTS.md), [Skills](../../../SKILLS.md), [Workflows](../../../WORKFLOWS.md).
