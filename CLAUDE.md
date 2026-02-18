# Repository Guidelines (Python / FastAPI Version)

> Main repository contains the backend service and related infrastructure.
> 
> **Important**: GitHub Issues, PRs and comments should use real multiline messages (not escaped `\n`).
> 
> All automation and examples must assume a Python stack.

---

## Project Structure & Module Organization

### Recommended Layout for a FastAPI Backend

```
.
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── v1/
│   │   │   ├── routes/
│   │   │   └── dependencies.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── security.py
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── repositories/
│   └── infra/
│       ├── db.py
│       └── redis.py
├── tests/
│   ├── unit/
│   └── integration/
├── scripts/
├── docker/
├── alembic/
├── pyproject.toml
└── README.md
```

### Guidelines

- **`app/main.py`** is the FastAPI entrypoint
- **`api/`** contains only HTTP layer (routers, request/response wiring)
- **`services/`** contains business logic
- **`repositories/`** contains persistence logic (ORM or external services)
- **`models/`** contains ORM models
- **`schemas/`** contains Pydantic schemas (DTOs)
- **`infra/`** contains low-level adapters (database engine, queues, caches, object storage, etc)

> **⚠️ Important**: Do not place business logic inside routers.

---

## Modular / Plugin-like Features

If the project grows:

```
app/modules/<module_name>/
    api.py
    service.py
    models.py
    schemas.py
    repository.py
```

> All modules must be wired in `app/api/v1/router.py`.

---

## Docker

All services must be runnable through Docker.

A `docker/` folder should contain:

- `Dockerfile`
- `docker-compose.yml` (local/dev orchestration only)

**VM Operations** → generalized to Python service operations

Production and staging environments must be accessed through SSH or a managed runner.

---

## Operational Conventions

### Rules

- Long-running operations must be executed inside `tmux`
- Application must run via a process manager or container (recommended: Docker)

### Typical Operations

1. Pull new code
2. Rebuild container
3. Restart service
4. Inspect logs

### Service Health

Service health must be exposed via:
```
GET /health
```

---

## Build, Test and Development Commands (Python Stack)

### Runtime

**Python 3.11+**

### Dependency Management

Python counterpart of `pnpm` / `bun`:

**Poetry** (recommended and production-grade)

```bash
poetry install
poetry add <pkg>
poetry run <command>
```

### Local Development

```bash
poetry run uvicorn app.main:app --reload
```

### Production Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> (or via Docker / container entrypoint)

---

## Type Checking (TypeScript → Python Equivalent)

| Original | Python Counterpart |
|----------|-------------------|
| TypeScript strict checking | **mypy** |

```bash
poetry run mypy app
```

---

## Linting and Formatting

| Original | Python Counterpart |
|----------|-------------------|
| Oxlint / Oxfmt | **ruff**<br>**black** |

```bash
poetry run ruff check app
poetry run black app
```

---

## Tests

| Original | Python Counterpart |
|----------|-------------------|
| vitest | **pytest** |

```bash
poetry run pytest
```

### Coverage

```bash
poetry run pytest --cov=app
```

---

## Coding Style & Naming Conventions

- **Language**: Python 3.11+
- **Framework**: FastAPI
- Use type annotations everywhere (public functions and service boundaries)
- Do not use untyped dictionaries as implicit DTOs — always define Pydantic schemas

### Rules

**API layer must only:**
- parse input
- call services
- map responses

**Business rules** must live in `services/`.

**Persistence logic** must live in `repositories/`.

### File Size Guideline

Prefer files under ~400–500 lines.
Split by responsibility, not by technical convenience.

### Naming

| Element | Style |
|---------|-------|
| Packages and modules | `snake_case` |
| Classes | `PascalCase` |

**Pydantic schemas must be suffixed with:**
- `Create`
- `Update`
- `Read`
- `Response` (when applicable)

---

## Testing Guidelines

### Framework

**pytest**

### Structure

```
tests/
  unit/
  integration/
```

### Naming

`test_<module>.py`

### Integration Testing

Use:
- `httpx.AsyncClient` with FastAPI test app
- real DB containers for integration tests (Docker compose profile)

### Coverage Expectations

Minimum 70% line coverage on services and repositories.

---

## Live / External Integrations

External services must be mocked in unit tests.

Only integration tests may access:
- databases
- queues
- object storage

---

## Commit & Pull Request Guidelines

### Commits

- Small and focused
- One logical change per commit
- Message format: `<scope>: <short description>`

**Examples:**
- `auth: add refresh token rotation`
- `users: validate email uniqueness`

### Pull Requests

PRs must:
- describe scope
- describe testing performed
- mention breaking changes

### Changelog

Only required for:
- API breaking changes
- public endpoint changes
- data model changes

### Before Opening a PR

```bash
poetry run ruff check app
poetry run mypy app
poetry run pytest
```

---

## Shorthand Commands

You may define project helpers in `scripts/` (bash or python).

**Example:** `scripts/sync.sh`

**Purpose:**
- commit changes
- pull with rebase
- push

---

## Security & Configuration Tips

### Configuration

Python counterpart of Node runtime config:
- **environment variables**
- **Pydantic Settings** (`pydantic-settings`)

All configuration must be loaded through:
`app/core/config.py`

### Secrets

- Never committed
- Injected only via environment variables or secret managers

### Sensitive Data Rules

- Never place real credentials in tests
- Never commit real URLs, tokens, phone numbers or API keys
- Database credentials, storage credentials and API tokens must be isolated per environment

---

## Troubleshooting

### Mandatory Diagnostics

- Application logs
- Container logs
- Health endpoint: `GET /health`

### When Investigating Failures

- Reproduce using integration tests when possible
- Inspect structured logs

---

## Agent-Specific Notes (Generalized for Python Backend Teams)

- Do not modify installed site-packages
- Do not patch dependencies without explicit approval
- Avoid introducing runtime monkey-patching

### Multi-Agent / Multi-Developer Safety

- Do not reformat or refactor unrelated files
- Keep commits scoped strictly to the change you are responsible for
- Do not alter CI, deployment or infrastructure unless explicitly requested

---

## Schema and API Stability

Never change request/response schemas without:
1. **versioning the endpoint**, or
2. **explicitly documenting the breaking change**