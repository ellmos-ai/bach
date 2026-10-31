# -*- coding: utf-8 -*-
"""Pickup-Category-Runner: Identifiziert die gültige pickup_category für eine BACH-Task.

Dieses Modul implementiert den Pickup mit den 14 pickup_category-Ausschlüssen
und der Prioritätsregel. Es wird von agent_runners.py als Runner "pickup_category"
aufgerufen.

Ziel: Für eine Free/Cloud-qualifizierte BACH-Task eine gültige pickup_category
und Priorität ermitteln. agent_router.py (Rollenzuordnung) und cloud.py (Cloud-Sync)
werden nicht berührt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

#: Die 14 pickup_category-Ausschlüsse (Kategorien, die von der Pickup-Logik ausgeschlossen sind).
PICKUP_CATEGORY_EXCLUSIONS: list[str] = [
    "food",
    "clothing",
    "electronics",
    "toys",
    "books",
    "media",
    "health",
    "finance",
    "utilities",
    "home",
    "gardening",
    "travel",
    "automotive",
    "construction",
]

#: Gültige pickup_category-Werte (die nicht ausgeschlossen sind).
VALID_PICKUP_CATEGORIES: list[str] = [
    "general",
    "office",
    "education",
    "entertainment",
    "social",
    "sports",
    "outdoor",
    "pets",
    "beauty",
    "tools",
    "kitchen",
    "garden",
    "kids",
    "senior",
]

#: Prioritätsregel: Höhere Priorität = wichtiger. Standardpriorität = "normal".
PRIORITY_LEVELS: dict[str, int] = {
    "critical": 5,
    "high": 4,
    "important": 3,
    "normal": 2,
    "low": 1,
    "trivial": 0,
}

#: Standard-Priorität für Free/Cloud-qualifizierte Tasks.
DEFAULT_PRIORITY = "normal"


def is_excluded(category: str) -> bool:
    """Prüft, ob eine pickup_category ausgeschlossen ist."""
    return category.lower() in PICKUP_CATEGORY_EXCLUSIONS


def resolve_category(task_category: str) -> Optional[str]:
    """Ermittelt die gültige pickup_category für eine Task.

    Wenn die Kategorie ausgeschlossen ist, wird die erste gültige nicht-exkludierte
    Kategorie zurückgegeben.
    """
    cat = (task_category or "").lower()
    if cat in VALID_PICKUP_CATEGORIES and not is_excluded(cat):
        return cat
    # Fallback: erste gültige Kategorie
    for valid in VALID_PICKUP_CATEGORIES:
        if not is_excluded(valid):
            return valid
    return None


def resolve_priority(task_priority: str = "") -> str:
    """Ermittelt die Priorität für eine Task basierend auf der Prioritätsregel."""
    prio = (task_priority or "").lower()
    if prio in PRIORITY_LEVELS:
        return prio
    return DEFAULT_PRIORITY


def main(argv: list[str]) -> int:
    """Haupt-Einstiegspunkt für den pickup_category-Runner."""
    args = list(argv[1:])
    configured_priority = ""
    idx = 0
    positional: list[str] = []
    while idx < len(args):
        token = args[idx]
        if token == "--exclude" and idx + 1 < len(args):
            idx += 2
            continue
        if token == "--priority" and idx + 1 < len(args):
            configured_priority = args[idx + 1]
            idx += 2
            continue
        if token in ("--dangerously-skip-permissions",):
            idx += 1
            continue
        if token == "--allowed_tools" and idx + 1 < len(args):
            idx += 2
            continue
        positional.append(token)
        idx += 1

    if not positional:
        print("Usage: pickup_category [--exclude ...] [--priority ...] <task_category> [task_priority]", file=sys.stderr)
        return 2

    task_category = positional[0]
    task_priority = positional[1] if len(positional) > 1 else configured_priority

    category = resolve_category(task_category)
    priority = resolve_priority(task_priority)

    if category is None:
        print(json.dumps({"error": "Keine gültige pickup_category"}, ensure_ascii=False))
        return 1

    result = {
        "pickup_category": category,
        "priority": priority,
        "priority_level": PRIORITY_LEVELS.get(priority, 2),
        "excluded": is_excluded(task_category),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))