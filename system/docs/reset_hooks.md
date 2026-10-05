# Reset Hooks

Das System bietet vier Reset-Hooks, über die sich Code vor oder nach dem
Zurücksetzen einer Skill- oder Plugin-Instanz ausführen lassen kann.

## Übersicht

| Event                 | Auslöser                                   | Verteilt |
|-----------------------|--------------------------------------------|----------|
| `before_skill_reset`  | Direkt vor dem Reset einer Skill-Instanz   | ja       |
| `after_skill_reset`   | Direkt nach dem Reset einer Skill-Instanz  | ja       |
| `before_plugin_reset` | Direkt vor dem Reset eines Plugins         | ja       |
| `after_plugin_reset`  | Direkt nach dem Reset eines Plugins        | ja       |

Diese Events sind in `HookRegistry.KNOWN_EVENTS` und
`HookRegistry.DISTRIBUTED_EVENTS` registriert.

## Context-Payloads

Alle Reset-Hooks erhalten einen `dict`-Context, der mindestens den Namen der
betroffenen Komponente enthält:

### Skill-Reset

- `before_skill_reset`
  - `name`: Name der Skill-Instanz, die zurückgesetzt wird.
- `after_skill_reset`
  - `name`: Name der Skill-Instanz.
  - `status`: Ergebnis des Resets – `"ok"` bei Erfolg, `"error"` bei Fehler.

### Plugin-Reset

- `before_plugin_reset`
  - `name`: Name des Plugins, das zurückgesetzt wird.
- `after_plugin_reset`
  - `name`: Name des Plugins.
  - `status`: Ergebnis des Resets – `"ok"` bei Erfolg, `"error"` bei Fehler.

Der Context wird von `core/hooks.py` über `HookRegistry.emit(event, context)`
an alle registrierten Handler übergeben.

## Registrierung

Hooks werden typischerweise über `register_hook` in `core/plugin_api.py`
oder direkt über `HookRegistry.register(event, callback)` angemeldet:

```python
from core.hooks import HookRegistry

HookRegistry.register("before_skill_reset", my_callback)
```

Alternativ über die Plugin-API:

```python
from core.plugin_api import register_hook

register_hook("after_plugin_reset", my_callback)
```

Handler-Signatur:

```python
def my_callback(context):
    ...
```

Bei verteilten (distributed) Events werden Handler auf verschiedenen
Prozess-/Maschinenknoten benachrichtigt, sofern das Backend verteiltes
Emitting unterstützt.

## Skill-Beispiel

```python
from core.hooks import HookRegistry

def log_before_skill_reset(ctx):
    name = ctx.get("name")
    print(f"Resetting skill: {name}")

def log_after_skill_reset(ctx):
    name = ctx.get("name")
    status = ctx.get("status")
    print(f"Skill {name} reset finished with status={status}")

HookRegistry.register("before_skill_reset", log_before_skill_reset)
HookRegistry.register("after_skill_reset", log_after_skill_reset)
```

## Plugin-Beispiel

```python
from core.plugin_api import register_hook

def cleanup_after_plugin_reset(ctx):
    name = ctx.get("name")
    status = ctx.get("status")
    if status == "ok":
        print(f"Plugin {name} reset successfully")
    else:
        print(f"Plugin {name} reset failed")

register_hook("after_plugin_reset", cleanup_after_plugin_reset)
```

## Hinweise

- `HookRegistry.emit` prüft, ob das Event in `KNOWN_EVENTS` eingetragen ist.
- Die Events sind Teil von `DISTRIBUTED_EVENTS`, damit sie bei Bedarf
  auch an externe Knoten weitergereicht werden können.
- Reset-Logik findet sich in `hub/skills.py` (`_reset_skill`) und
  `core/plugin_api.py` (`reset_plugin`).
