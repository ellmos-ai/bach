"""Stable IDs for bundled portraits and the existing Ticket-Master symbols."""

TICKET_SYMBOL_IDS = frozenset({
    "githubbot", "office", "scripts", "server", "sync", "topics", "topics_ai",
    "topics_gesim", "topics_hardware", "topics_research", "topics_roblox",
    "topics_software", "topics_umbruch", "topics_uni", "usr", "wissen",
})


def validate_symbol(value):
    if not isinstance(value, str) or (value and value not in TICKET_SYMBOL_IDS):
        raise ValueError("Unbekanntes Ticket-Master-Symbol")
    return value
