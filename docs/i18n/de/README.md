# BACH - Deutsch

[English](../en/README.md) | [Deutsch](../de/README.md) | [Español](../es/README.md) | [Русский](../ru/README.md) | [日本語](../ja/README.md) | [中文](../zh/README.md)

BACH ist ein textbasiertes Betriebssystem für Large Language Models (LLMs): strukturierte Erinnerung, Aufgabenverwaltung, Automatisierung, Agenten, Werkzeuge, Workflows und Multi-LLM-Orchestrierung.

Dieser Spracheinstieg ist für Nutzer und Crawler gedacht. Die kanonische deutsche README ist [../../../README.de.md](../../../README.de.md).

## Mehrsprachigkeit

Der aktuelle Release aktiviert sechs Sprachen: `de`, `en`, `es`, `ru`, `ja` und `zh`. Das ist in [../../../system/exports/translations/languages_config.release.json](../../../system/exports/translations/languages_config.release.json) und [../../../system/exports/translations/manifest.release.json](../../../system/exports/translations/manifest.release.json) verifiziert.

## Start

```bash
git clone https://github.com/ellmos-ai/bach.git
cd bach
pip install -e .
bach setup preflight
```

Mehr: [Schnellstart](../../../QUICKSTART.md), [Benutzerhandbuch](../../../BACH_USER_MANUAL.md), [Agenten](../../../AGENTS.md), [Skills](../../../SKILLS.md), [Workflows](../../../WORKFLOWS.md).
