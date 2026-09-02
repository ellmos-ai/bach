# BACH - Sistema operativo basado en texto para LLMs

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [Русский](README.ru.md) | [日本語](README.ja.md) | [中文](README.zh.md)

**Versión:** v3.13.0-bluesky  
**Estado:** Production-Ready  
**Licencia:** MIT

## Resumen

**BACH** es un sistema operativo basado en texto para Large Language Models (LLMs). Ayuda a los modelos a trabajar de forma autónoma, aprender, coordinar tareas y organizar conocimiento persistente.

BACH forma parte de la familia **ellmos** y ofrece infraestructura para gestión de tareas, memoria estructurada, automatización, agentes especializados, herramientas, flujos de trabajo y orquestación multi-LLM.

## Soporte multilingüe

El snapshot actual de BACH activa seis idiomas: alemán (`de`), inglés (`en`), español (`es`), ruso (`ru`), japonés (`ja`) y chino (`zh`).

Verificado en `system/exports/translations/languages_config.release.json` y `system/exports/translations/manifest.release.json`: el release exporta 17.407 entradas de traducción y archivos de locale para los seis idiomas. Parte del material traducido se genera automáticamente y debe revisarse antes de usarlo como documentación pública final.

## Funciones principales

- **113+ handlers** para CLI y API
- **550+ herramientas** para archivos, análisis y automatización
- **1870+ skills** reutilizables
- **59 plantillas de workflow**
- **4100+ tests**
- **Memoria estructurada** con facts, lessons y varios niveles de contexto
- **Agentes y expertos** para orquestar tareas complejas
- **Chat service** con bot de Telegram, Control API, Web Dashboard y System Tray

## Instalación

```bash
git clone https://github.com/ellmos-ai/bach.git
cd bach
pip install -e .
bach setup preflight
bach setup full-install
```

## Inicio rápido

```bash
python bach.py --startup
python bach.py task add "Analizar la estructura del proyecto"
python bach.py agent list
python bach.py scheduler status
python bach.py --shutdown
```

## Documentación

- **[Quickstart](QUICKSTART.md)** - Primer flujo de trabajo
- **[Manual de usuario](BACH_USER_MANUAL.md)** - Manual completo
- **[Catálogo de skills](SKILLS.md)** - Skills disponibles
- **[Catálogo de agentes](AGENTS.md)** - Agentes y expertos
- **[Workflows](WORKFLOWS.md)** - Plantillas de procesos
- **[SKILL.md](SKILL.md)** - Instrucciones operativas para LLMs

## Licencia

MIT License - véase [LICENSE](LICENSE).
