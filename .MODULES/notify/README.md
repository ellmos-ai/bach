# notify Module

Standalone module for multi-channel notification routing, tag serialization, and queued notification persistence.

## Exports
- `NotificationRouter`: Dispatches messages across channels (desktop, console, sqlite queue, webhook).
- `tag_notification`: Serializes and formats tags into notification headers.
- Queue querying and lifecycle tracking (`get_pending`, `mark_delivered`).
