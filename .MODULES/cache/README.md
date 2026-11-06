# cache - BACH Standalone Module

Self-contained key-value and function result cache with TTL support, namespace isolation, eviction metrics, and persistence.

## Features
- In-memory key-value store with time-to-live (TTL) expiration.
- Namespace partitioning (`cache.namespace("templates")`).
- Transparent `@cached` decorator with argument hashing.
- Hit/miss and eviction metrics.
- Optional JSON-backed disk persistence.
