---
name: database-admin
description: |
  Use for database schema design, migrations, query optimization, and data modeling.
  Trigger phrases: "schema", "migration", "database", "query", "table", "model"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, TodoWrite
---

# Database Administration Skill

## Conventions
- UUID primary keys: `id = Column(UUID, primary_key=True, default=uuid4)`
- Timestamps: `created_at`, `updated_at` on every table
- Soft delete: `deleted_at` nullable timestamp
- JSONB for flexible metadata columns
- Indexes on all foreign keys and frequently queried columns

## SQLAlchemy Model Template
```python
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from uuid import uuid4
from app.core.database import Base

class Course(Base):
    __tablename__ = "courses"
    
    id = Column(UUID, primary_key=True, default=uuid4)
    title = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(String, nullable=True)
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)
```

## Migration Workflow
```bash
# Create migration after model change
uv run alembic revision --autogenerate -m "add courses table"
# Review generated migration in alembic/versions/
# Apply migration
uv run alembic upgrade head
# Rollback if needed
uv run alembic downgrade -1
```

## Rules
- Never modify a migration after it's been applied to staging/production
- Always review auto-generated migrations — they can miss things
- Add indexes for columns used in WHERE clauses
- Use `select()` with explicit columns for large tables (avoid SELECT *)
- All queries must be async using `AsyncSession`
