# TODOS

## Postgres migration path
**What:** Migrate from SQLite to PostgreSQL for multi-instance deployment on Fly.io.
**Why:** SQLite doesn't support concurrent writes across multiple processes/instances. Single instance = no failover, no horizontal scaling.
**Pros:** Enables multi-instance deployment, proper connection pooling, better concurrent write handling.
**Cons:** Adds operational complexity (managed Postgres on Fly.io ~$7/mo), connection string management, migration tooling.
**Context:** V1 uses SQLite and runs single-instance. This becomes necessary when traffic exceeds what one instance can handle, or when you need zero-downtime deploys. Use SQLAlchemy or similar ORM so the switch is a connection string change, not a rewrite.
**Depends on:** V1 launch + traffic growth signal.
