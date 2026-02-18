# CloudWalk Challenge — Agent Swarm Solution

This repository contains my implementation for the **Agent Swarm** challenge.

The solution is a **FastAPI + PydanticAI** backend named **Skywalker** where a main router/orchestrator agent coordinates specialized sub-agents through in-process tool delegation. It features session persistence, RAG retrieval via Pinecone, customer support data tools backed by SQLite, and optional observability via Langfuse.

---

## Table of Contents

1. [Setup and Run](#1-setup-and-run)
2. [Challenge Mapping](#2-challenge-mapping)
3. [API Surface](#3-api-surface)
4. [Architecture and Design Patterns](#4-architecture-and-design-patterns)
5. [RAG Pipeline](#5-rag-pipeline)
6. [Stack](#6-stack)
7. [How I Used LLM Tools During Development](#7-how-i-used-llm-tools-during-development)
8. [Testing Strategy](#8-testing-strategy)
9. [Agent Session Tests — Deep Dive](#9-agent-session-tests--deep-dive)
10. [Project Structure](#10-project-structure)
11. [Improvement Ideas](#11-improvement-ideas)

---

## 1) Setup and Run

### Prerequisites

- Python 3.11+
- Docker + Docker Compose (for containerized run and optional Langfuse observability stack)
- API keys:
  - `OPENAI_API_KEY` — required (LLM + embeddings)
  - `PINECONE_API_KEY` + `PINECONE_INDEX_HOST` — required for RAG
  - `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` — optional, for alternative model providers
  - `SLACK_BOT_TOKEN` + `SLACK_ESCALATION_CHANNEL` — optional, for Slack escalation

### Environment configuration

```bash
cp .env.example .env
```

Minimum required values:

```env
OPENAI_API_KEY=...
PINECONE_API_KEY=...
PINECONE_INDEX_HOST=...
```

### Install dependencies (local)

```bash
# Using Poetry (recommended)
poetry install

# Or pip editable install
pip install -e .
```

### Initialize the support database

```bash
python db/support_db/init_db.py
```

This creates `db/support_db/support.db` with seeded customer, merchant, product, account, auth, device, transfer, and incident records.

### Run API locally

```bash
uvicorn src.modules.api.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- **API docs**: `http://localhost:8000/docs`
- **Health**: `http://localhost:8000/health`

### Run with Docker Compose

```bash
docker-compose up --build
```

This starts:
- `skywalker-app` — FastAPI application on port `8000`
- `langfuse-web` — Langfuse UI on port `3000`
- `langfuse-worker` — async event processor
- `langfuse-postgres` — PostgreSQL for Langfuse metadata
- `langfuse-clickhouse` — ClickHouse for OLAP observability data
- `langfuse-redis` — Redis for cache/queue
- `langfuse-minio` — S3-compatible blob storage for Langfuse events/media

---

## 2) Challenge Mapping

### Agent 1 — Router Agent (entry point)

- Implemented as `BaseAgent` in `src/modules/agents/agent_executor.py`, orchestrated by `AgentRuntime`.
- Receives requests on `POST /chat`, manages session continuity, and executes the primary agent loop.
- Discovers sub-agents from `.skywalker/agents/*.yml` at startup via `AgentLoader` → `AgentRegistry`.
- Exposes each discovered sub-agent as a callable tool (agent-as-tool pattern), enabling dynamic delegation without hardcoded routing logic.
- Has access to all **native file tools** (`find`, `grep`, `read`, `write`, `edit`) scoped to the session workspace.

### Agent 2 — Knowledge Agent

- Defined as a YAML sub-agent discovered at startup.
- Tools available to this agent:
  - `rag_search` — semantic search against Pinecone (`infinitepay` namespace)
  - `web_search` — real-time web search via DuckDuckGo (`ddgs`)
- Grounds responses in InfinitePay product content ingested into Pinecone.
- The knowledge base ingestion/query API (`/knowledge-bases/*`) supports loading new URLs at runtime.

### Agent 3 — Customer Support Agent

- Defined as a YAML sub-agent discovered at startup.
- Tools available to this agent (backed by local SQLite `db/support_db/support.db`):
  - `get_customer_overview` — fetches user, merchant, products enabled, account status, and auth status
  - `get_recent_operations` — fetches recent transfers and registered devices with a configurable limit
  - `get_active_incidents` — fetches all currently active platform incidents

### Agent communication mechanism

Communication is **in-process function/tool invocation** — no message queues or HTTP hops between agents:

1. `AgentRuntime` discovers YAML agent configs at startup.
2. Each sub-agent config is wrapped into an `AgentTool` with an async `execute` function.
3. When the router agent decides to delegate, it calls the sub-agent tool like any other tool.
4. The tool creates a scoped `AgentExecutor` for the sub-agent, runs it, and returns the result as a `ToolResult`.
5. All agents share one session workspace (`sessionDir`) and write to per-agent `conversations/*.jsonl` files.

---

## 3) API Surface

### Chat endpoint

`POST /chat`

```json
{
  "userId": "client789",
  "question": "What are the fees of Maquininha Smart?",
  "sessionId": "optional-existing-session-id"
}
```

Response:

```json
{
  "sessionId": "...",
  "response": "...",
  "metadata": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  }
}
```

- If `sessionId` is omitted or invalid, a new session is created automatically.
- Reuse `sessionId` across requests to maintain conversation history.

### Knowledge base endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/knowledge-bases/ingest` | Submit URLs for async background ingestion |
| `GET` | `/knowledge-bases/jobs/{job_id}` | Poll ingestion job status |
| `POST` | `/knowledge-bases/query` | Direct semantic retrieval (bypasses agent) |

### Health

`GET /health` → `{"status": "ok"}`

---

## 4) Architecture and Design Patterns

### High-level architecture

```
POST /chat
    │
    ▼
FastAPI  (src/modules/api/main.py)
    │  lifespan: Config.load → AgentRuntime → discover agents → register tools
    │
    ▼
AgentRuntime
    │  session_manager : creates/loads ~/.skywalker/sessions/{sessionId}/
    │  agent_registry  : discovers .skywalker/agents/*.yml
    │  tools dict      : web_search, rag_search, get_customer_overview,
    │                    get_recent_operations, get_active_incidents
    │
    ▼
BaseAgent.run(question)
    │  builds ToolRegistry for session (native tools + sub-agent tools)
    │  creates PydanticAgent via AgentFactory
    │  loads conversation history from main.jsonl
    │
    ▼
PydanticAI Agent loop
    │  tool call → sub-agent tool (e.g. kb_agent, customer_data)
    │                  └─ AgentExecutor.get_response()
    │                       └─ scoped PydanticAgent with sub-agent tools
    │                            └─ rag_search / web_search / support_db tools
    │
    ▼
Response persisted to conversations/main.jsonl
    │
    ▼
ChatResponse { sessionId, response, metadata }
```

### Layers

- **API layer** (`src/modules/api/`): HTTP routing, request/response schemas, lifespan bootstrapping.
- **Agent runtime** (`AgentRuntime`): session management, YAML agent discovery, tool registration.
- **Execution layer**:
  - `BaseAgent` — the active path used by `/chat`; builds tools, runs the PydanticAI loop, persists history.
  - `AgentExecutor` — reusable execution engine used by both `BaseAgent` and sub-agent delegation.
  - `AgentManager` — extended orchestration path with guardrails, dependency injection, and delegation (used in integration tests and for future expansion).
- **Tools layer** (`src/modules/tools/`): registry/factory-driven tool composition; all tools implement `AgentTool` with a typed `parameters_schema` and async `execute`.
- **Knowledge base layer** (`src/modules/knowledge_bases/`): scrape → chunk → embed → upsert → query pipeline.
- **Persistence layer**: session `jsonl` transcripts + `session.json` metadata, Pinecone vectors, SQLite support DB.

### Design patterns

1. **Agent-as-Tool delegation** — YAML sub-agent configs are wrapped into `AgentTool` instances at runtime, making delegation transparent to the router agent.
2. **Registry + Factory for tools** — `ToolRegistry` centralizes tool registration and filtering; `ToolsetFactory` creates per-agent toolsets.
3. **Orchestrator / Executor split** — `AgentManager` owns orchestration (guardrails, dependency hydration, delegation); `AgentExecutor` owns LLM execution.
4. **Schema-first contracts** — all tool parameters and API schemas are Pydantic models; no untyped dicts at boundaries.
5. **Observability-first hooks** — Langfuse spans wrap every major execution branch when enabled via `config/skywalker.json`.
6. **YAML-driven agent discovery** — adding a new sub-agent requires only a `.yml` file in `.skywalker/agents/`; no code changes needed.

### Guardrails

`AgentGuardrailManager` (`src/modules/agents/guardrail_manager.py`) provides LLM-based input and output validation:

- **Input guardrails**: detect prompt injection, off-topic queries, and malicious content before the main agent runs.
- **Output guardrails**: validate agent responses before returning to the user; revise or replace unsafe outputs.
- Uses a fast model (`gpt-4o-mini` by default) to keep latency low.
- When an input is rejected, the guardrail returns a pre-composed response and short-circuits the agent loop.

### Session file layout

```text
~/.skywalker/sessions/{sessionId}/
  sessionDir/               # shared file workspace (scoped to native tools)
  conversations/
    main.jsonl              # router agent conversation history
    {agentName}.jsonl       # per-sub-agent conversation history
  session.json              # metadata (user_id, created_at, token counters)
```

The root path is configurable in `config/skywalker.json` → `session.sessionsRoot`.

---

## 5) RAG Pipeline

### Ingestion flow

1. Submit a URL batch to `POST /knowledge-bases/ingest` → returns a `job_id` immediately.
2. Background pipeline runs per URL:
   - **Scrape** — `WebScraper` (powered by `crawl4ai`) fetches the page and converts it to Markdown.
   - **Chunk** — `MarkdownChunker` splits content with header-aware, overlapping chunking to preserve context.
   - **Embed** — OpenAI `text-embedding-3-large` (1024 dims) generates dense vectors per chunk.
   - **Upsert** — `PineconeVectorStore` upserts vectors with metadata (source URL, chunk index, text) into the target namespace.
3. Poll `GET /knowledge-bases/jobs/{job_id}` for status (`pending` / `running` / `completed` / `failed`).

### Retrieval flow

1. Agent calls the `rag_search` tool with `query`, `top_k` (default 5), and optional `namespace`.
2. The query is embedded with the same model and searched in Pinecone.
3. Top-k matches return chunk text + source URL + similarity score.
4. The agent uses those chunks to ground its response.

### InfinitePay knowledge base

The challenge data sources (InfinitePay product pages) are ingested into the `infinitepay` Pinecone namespace. The `rag_search` tool defaults to this namespace when not overridden.

---

## 6) Stack

| Layer | Technology |
|-------|-----------|
| Backend / API | FastAPI, Uvicorn |
| Agent framework | PydanticAI |
| LLM providers | OpenAI (primary), Anthropic, Google Gemini |
| Validation / config | Pydantic v2, pydantic-settings, python-dotenv |
| RAG — vector store | Pinecone |
| RAG — embeddings | OpenAI `text-embedding-3-large` |
| RAG — web scraping | crawl4ai |
| Web search | ddgs (DuckDuckGo) |
| Support data | SQLite + aiosqlite |
| Observability | Langfuse v3 |
| Testing | pytest, pytest-asyncio |
| Containerization | Docker, Docker Compose |
| Dependency management | Poetry |

---

## 7) How I Used LLM Tools During Development

I used **Claude Code** and **Windsurf** as development copilots throughout the project.

My workflow:

1. **Define architecture and constraints first** — I started from the challenge requirements and established the target architecture (router/orchestrator, knowledge/RAG, customer support tools, API, guardrails, observability) before writing any code.

2. **Create supporting docs before coding** — I maintain reference docs by tech stack and design pattern (agent orchestration, tool contracts, RAG pipeline). These serve as grounding material for the coding agent to follow reliable, up-to-date patterns.

3. **Implement incrementally with agent assistance** — I used Claude Code/Windsurf to scaffold and refine modules (agents, tools, knowledge base services, tests) in small, reviewable iterations. After each iteration I reviewed structure, naming, and contracts before moving on.

4. **Validate with tests and live checks** — I used the test suite and live integration scripts (RAG, web search, support DB tools, agent session runner) to validate behavior and refine prompts and tool usage.

LLM tools acted as a structured pair-programming layer. Architecture decisions, guardrail design, and final quality control remained human-driven.

---

## 8) Testing Strategy

### Test layout

```text
tests/
  unit/
    modules/
      agents/       # loader, YAML schema, sub-agent tool bridge, tool bridge
      api/          # chat schema validation
      core/         # config, session manager
      tools/        # tool registry, tool factory, individual tools
  agent_session/
    test_cases.json                  # declarative test case definitions
    run_agent_session_tests.py       # CLI runner for end-to-end /chat tests
    test_agent_manager_main_loop.py  # pytest integration tests for AgentManager
    test_rag_search_live.py          # live RAG tool integration test
    test_support_db_tools_live.py    # live support DB tools integration test
    test_web_search_live.py          # live web search tool integration test
    results/                         # auto-generated Markdown reports per test run
```

### Running tests

```bash
# All unit tests
pytest tests/unit -v

# AgentManager integration tests (no credentials needed — mocked LLM)
pytest tests/agent_session/test_agent_manager_main_loop.py -v -s

# Live tool tests (require real credentials)
pytest tests/agent_session/test_rag_search_live.py -v -s
pytest tests/agent_session/test_support_db_tools_live.py -v -s
pytest tests/agent_session/test_web_search_live.py -v -s

# All tests
pytest -v
```

### Environment requirements per test group

| Test group | Requires |
|-----------|---------|
| Unit tests | Nothing (fully mocked) |
| `test_agent_manager_main_loop.py` | Nothing (mocked LLM via `unittest.mock`) |
| `test_rag_search_live.py` | `PINECONE_API_KEY`, `PINECONE_INDEX_HOST`, `OPENAI_API_KEY` |
| `test_support_db_tools_live.py` | `db/support_db/support.db` (run `init_db.py` first) |
| `test_web_search_live.py` | Internet access (no API key needed) |
| Agent session runner | Running API on `http://localhost:8000` |

---

## 9) Agent Session Tests — Deep Dive

The `tests/agent_session/` directory contains a dedicated end-to-end testing framework for validating the full agent capabilities against a live running API. This is separate from the pytest suite and is purpose-built for exploratory, scenario-based testing of the complete agent swarm.

### Overview

```
test_cases.json              ← defines what to test (declarative, no code)
run_agent_session_tests.py   ← sends real HTTP requests, collects results
results/{test_name}.md       ← auto-generated Markdown report per run
```

---

### `test_cases.json` — Declarative test definitions

Each entry in the `tests` array defines one scenario:

```json
{
  "name": "unique_test_name",
  "description": "Human-readable description of what is being tested",
  "default_question": "The message sent to POST /chat",
  "default_user_id": "client001",
  "default_session_id": null,
  "default_chat_url": "http://localhost:8000/chat",
  "sessions_root": "~/.skywalker/sessions"
}
```

The three built-in test cases cover the three core agent capabilities:

| Name | What it validates |
|------|------------------|
| `01_base_agent_native_tools` | Router agent using native file tools (`write`, `read`, `find`) inside the session workspace |
| `02_customer_data_active_incidents` | Router agent delegating to `customer_data` sub-agent → `get_active_incidents` tool |
| `03_knowledge_agent_compare_stone_vs_infinitepay` | Router agent delegating to `knowledge_base_agent` → `web_search` + `rag_search`, writing a comparison file |

**Adding a new test case** requires only appending a JSON object to `test_cases.json` — no code changes needed.

---

### `run_agent_session_tests.py` — CLI runner

Sends real HTTP `POST /chat` requests to the running API and produces structured Markdown reports.

**Prerequisite:** The API must be running on `http://localhost:8000`.

#### Usage

```bash
# Run all test cases
python tests/agent_session/run_agent_session_tests.py

# Run a single test case by name
python tests/agent_session/run_agent_session_tests.py --test 01_base_agent_native_tools

# Override the question at runtime
python tests/agent_session/run_agent_session_tests.py \
  --test 02_customer_data_active_incidents \
  --question "Show me the recent transfers for client789"

# Override user ID
python tests/agent_session/run_agent_session_tests.py \
  --test 01_base_agent_native_tools \
  --user-id myuser123

# Continue an existing session (multi-turn conversation)
python tests/agent_session/run_agent_session_tests.py \
  --test 01_base_agent_native_tools \
  --session-id <sessionId-from-previous-run>

# Force a new session even if default_session_id is set
python tests/agent_session/run_agent_session_tests.py \
  --test 01_base_agent_native_tools \
  --session-id none
```

#### Timeout control

The HTTP timeout defaults to 180 seconds. Override with:

```bash
CHAT_TIMEOUT=300 python tests/agent_session/run_agent_session_tests.py
```

#### What the runner does per test case

1. Sends `POST /chat` with the configured (or overridden) payload.
2. Prints the full JSON response to stdout.
3. Reads the session directory (`~/.skywalker/sessions/{sessionId}/`) from the response.
4. Collects all files created in `sessionDir/` (agent workspace artifacts).
5. Parses all `conversations/*.jsonl` files to extract the structured message history (role, content, tool calls, metadata).
6. Writes a complete Markdown report to `tests/agent_session/results/{test_name}.md`.

---

### `results/` — Auto-generated reports

Each run produces a `results/{test_name}.md` file with the following sections:

```markdown
# Agent Session Test Result: {test_name}

Generated: 2025-02-18 14:07:00 UTC

## Description (human)
...

## Request
- chat_url, user_id, session_id, question

## Response
(full JSON from /chat)

## Session Files (name + first 100 chars)
(files created by the agent in sessionDir/)

## Conversations (structured)
### Conversation: `main.jsonl`
1. **user** (timestamp)
   question text...
2. **assistant** (timestamp)
   response text...
   tool_calls:
     - name: customer_data
       args: {"query": "..."}
       result: ...

### Conversation: `customer_data.jsonl`
(sub-agent conversation history)
```

These reports let you verify:
- Which tools the agent called and in what order
- What arguments were passed to each tool and what each tool returned
- What files the agent created in the workspace
- The full conversation history for both the router and each sub-agent

---

### `test_agent_manager_main_loop.py` — pytest integration tests

Tests the `AgentManager` orchestration layer in isolation using mocked LLM calls. Does **not** require a running API or real credentials.

| Test group | What it covers |
|-----------|---------------|
| Initialization | `AgentManager` wires config, session manager, guardrails, and YAML agents correctly |
| Toolset preparation | `_prepare_toolsets_and_dependencies` assembles native + specialized tools |
| Guardrails | Input/output approval and rejection paths (mocked `validate_input`/`validate_output`) |
| Executor caching | `_get_or_create_executor` returns the same instance for the same `(session_id, agent_name)` key |
| Agent config lookup | `_find_agent_config` resolves YAML agent by name |
| Main loop | `run_main_agent` success, guardrail short-circuit, output revision paths |
| Delegation | `delegate_to_agent` success and non-existent agent error paths |
| Error handling | Executor exception propagation and graceful failure |
| Full integration | Complete flow with only `pydantic_ai.Agent.run` mocked |

```bash
pytest tests/agent_session/test_agent_manager_main_loop.py -v -s
```

---

### Live tool tests (dual-mode: pytest + standalone script)

Each live test file can be run as a pytest test **or** as a standalone script with custom arguments:

#### `test_rag_search_live.py`

```bash
# pytest mode
pytest tests/agent_session/test_rag_search_live.py -v -s

# standalone mode
python tests/agent_session/test_rag_search_live.py "What are the InfinitePay fees?"
python tests/agent_session/test_rag_search_live.py "Query" --namespace infinitepay --top-k 5
```

Validates that `rag_search` returns real results from Pinecone in the expected format.

#### `test_support_db_tools_live.py`

```bash
# pytest mode
pytest tests/agent_session/test_support_db_tools_live.py -v -s

# standalone mode
python tests/agent_session/test_support_db_tools_live.py
python tests/agent_session/test_support_db_tools_live.py --user-id client789 --limit 5
```

Validates all three support DB tools against the local SQLite database.

#### `test_web_search_live.py`

```bash
# pytest mode
pytest tests/agent_session/test_web_search_live.py -v -s

# standalone mode
python tests/agent_session/test_web_search_live.py "CloudWalk payment solutions"
python tests/agent_session/test_web_search_live.py "Python async" --max-results 10
```

Validates that `web_search` returns real DuckDuckGo results in the expected format.

---

### Recommended testing workflow

```bash
# 1. Fast feedback (no external deps)
pytest tests/unit -v
pytest tests/agent_session/test_agent_manager_main_loop.py -v -s

# 2. Tool-level live validation (credentials required)
pytest tests/agent_session/test_support_db_tools_live.py -v -s
pytest tests/agent_session/test_web_search_live.py -v -s
pytest tests/agent_session/test_rag_search_live.py -v -s

# 3. Full end-to-end agent session (API must be running)
uvicorn src.modules.api.main:app --reload --host 0.0.0.0 --port 8000 &
python tests/agent_session/run_agent_session_tests.py
# Inspect results/
```

---

## 10) Project Structure

```text
.
├── config/
│   └── skywalker.json          # global config (models, session root, Langfuse, DB)
├── db/
│   └── support_db/
│       ├── init_db.py          # seeds the SQLite support database
│       ├── schema.sql          # table definitions
│       └── support.db          # SQLite database (generated)
├── src/
│   └── modules/
│       ├── agents/
│       │   ├── agent_executor.py    # AgentRuntime, AgentExecutor, BaseAgent
│       │   ├── agent_factory.py     # PydanticAgent creation + tool binding
│       │   ├── agent_manager.py     # AgentManager (guardrails, delegation)
│       │   ├── agent_registry.py    # AgentRegistry (YAML agent lookup)
│       │   ├── guardrail_manager.py # LLM-based input/output guardrails
│       │   ├── loader.py            # AgentLoader (YAML discovery)
│       │   ├── schemas.py           # YAMLAgentConfig, BasicDependencies, etc.
│       │   └── context_manager/
│       │       ├── prompts.py           # system prompt templates
│       │       └── guardrail_prompts.py # guardrail prompt templates
│       ├── api/
│       │   ├── main.py          # FastAPI app, lifespan, /chat, /health
│       │   └── schemas.py       # ChatRequest, ChatResponse
│       ├── core/
│       │   ├── config.py        # Config, SessionConfig, ModelsConfig, etc.
│       │   └── session.py       # SessionManager, Message
│       ├── knowledge_bases/
│       │   ├── chunker.py       # MarkdownChunker
│       │   ├── router.py        # /knowledge-bases/* FastAPI routes
│       │   ├── schemas.py       # ingest/query request/response models
│       │   ├── scraper.py       # WebScraper (crawl4ai)
│       │   ├── service.py       # KnowledgeBaseService (pipeline orchestration)
│       │   └── vector_store.py  # PineconeVectorStore
│       └── tools/
│           ├── registry.py      # ToolRegistry
│           ├── tool_factory.py  # ToolsetFactory
│           ├── schema.py        # AgentTool, ToolResult, parameter schemas
│           ├── enums.py         # tool type enums
│           ├── find.py          # find tool (file search)
│           ├── grep.py          # grep tool (content search)
│           ├── read.py          # read tool (file read)
│           ├── write.py         # write tool (file write)
│           ├── edit.py          # edit tool (file edit)
│           ├── web_search.py    # web_search tool (DuckDuckGo)
│           ├── rag_search.py    # rag_search tool (Pinecone)
│           └── support_db.py    # get_customer_overview, get_recent_operations,
│                                #   get_active_incidents
├── tests/
│   ├── unit/modules/            # unit tests (fully mocked)
│   └── agent_session/           # integration + e2e tests
│       ├── test_cases.json
│       ├── run_agent_session_tests.py
│       ├── test_agent_manager_main_loop.py
│       ├── test_rag_search_live.py
│       ├── test_support_db_tools_live.py
│       ├── test_web_search_live.py
│       └── results/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── config/skywalker.json
```

---

## 11) Improvement Ideas

### A) RAG performance

1. Add reranking (cross-encoder) after Pinecone retrieval.
2. Use hybrid retrieval (dense + sparse/BM25) and metadata filtering by product/intent.
3. Introduce chunk quality scoring and adaptive chunking per page type.
4. Cache frequent embeddings/queries and add retrieval latency dashboards.

### B) Agent tracking and observability

1. Standardize trace IDs across API → manager → executor → tools.
2. Persist structured tool-call telemetry (duration, success/failure, token cost).
3. Add agent-routing analytics (which agent/tool resolved each intent).
4. Create quality feedback loops (human ratings linked to traces).

### C) Testing maturity

1. Add contract tests for every tool schema and response shape.
2. Add replay tests from real conversation transcripts in `results/`.
3. Add load tests for concurrent sessions and long-running conversations.
4. Add CI matrix separating fast unit tests vs live integration tests.

### D) Safety with real user data

1. Enforce PII masking/redaction before logs, traces, and vector storage.
2. Add encryption at rest for session files and support DB snapshots.
3. Add strict data retention/TTL and deletion workflows per user.
4. Make guardrails stricter for sensitive operations (auth/account/block reasons) and fail-closed for high-risk paths.
5. Add authentication/authorization and per-tool access controls by role/scope.
