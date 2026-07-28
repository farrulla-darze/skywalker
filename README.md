# Skywalker — Multi-Agent Customer Support Platform

Solução evoluída do desafio **Agent Swarm** (CloudWalk): um monorepo com backend **FastAPI + PydanticAI**
e frontend **React**, onde agentes são **registros de banco** criados/editados pela interface, com
RAG local (**Qdrant**), knowledge graph (**Neo4j**), golden dataset com avaliação versionada,
guardrails no caminho de produção e escalação humana real via **Telegram**.

> O diagnóstico técnico da v1 e o plano que originou esta versão estão em
> [REVIEW_AND_ROADMAP.md](REVIEW_AND_ROADMAP.md). O enunciado original está em
> [cloudwalk_challenge.md](cloudwalk_challenge.md).

---

## Visão geral

```
frontend/ (React + Vite + TS + Tailwind)          app/ (FastAPI)
┌────────────────────────────────┐                ┌──────────────────────────────────────┐
│ Login/Registro (JWT)           │   /api/v1/*    │ api/v1/router.py  (wiring central)   │
│ Chat (steps do agente,         │ ─────────────▶ │ modules/                             │
│       feedback 👍/👎)          │                │   auth/  agents/  chat/  tools/      │
│ Agentes (CRUD + tools)         │                │   knowledge/  evaluation/            │
│ Integrações (Telegram + QR)    │                │   integrations/  guardrails/         │
│ Avaliação (golden + runs)      │                │ core/ (config, db, security, ...)    │
└────────────────────────────────┘                └──────────┬───────────────────────────┘
                                                             │
                                    ┌──────────┬─────────────┼──────────────┬───────────┐
                                    ▼          ▼             ▼              ▼           ▼
                                PostgreSQL   Qdrant       Neo4j       Telegram API   OpenAI
                                (estado)    (vetores)    (grafo)      (canal+escalação)
```

**Fluxo de uma mensagem:** `input guardrail → (handoff check) → router agent (PydanticAI) →
tools / specialists → output guardrail → persistência (mensagem + steps + tokens reais)`.

Enquanto uma sessão está em atendimento humano (FSM `bot → pending_human → human → bot`),
**o LLM não é chamado** — as mensagens são encaminhadas ao atendente no Telegram.

---

## Quickstart

### Docker (stack completa)

```bash
cp .env.example .env       # preencha OPENAI_API_KEY e JWT_SECRET
docker compose --env-file .env -f docker/docker-compose.yml up --build
```

| Serviço | URL |
|---|---|
| Frontend | http://localhost:3001 |
| API + docs | http://localhost:8000/docs |
| Qdrant dashboard | http://localhost:6333/dashboard |
| Neo4j browser | http://localhost:7474 |
| Langfuse (opcional) | `--profile observability` → http://localhost:3000 |

### Local (dev)

```bash
# Backend
poetry install --extras dev
cp .env.example .env
poetry run uvicorn app.main:app --reload --port 8000

# Frontend (em outro terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173 (proxy p/ :8000)

# Infra local mínima (vetores/grafo), se não usar o compose completo:
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/skywalker-graph neo4j:5-community
```

No primeiro boot o backend cria as tabelas, **seeda os agentes de sistema**
(`sky-router`, `customer-support`), o **golden dataset** (8 cenários do desafio + adversariais)
e o banco de suporte mock (`db/support_db/support.db`).

---

## Mapeamento do desafio

| Requisito | Implementação |
|---|---|
| Router Agent | `sky-router` (registro em banco, prompt completo de roteamento/escopo/idiomas) |
| Knowledge Agent + RAG | tools `rag_search` (Qdrant) + `graph_search` (Neo4j) + `web_search` (ddgs), diretas no router |
| Customer Support Agent (2+ tools) | specialist `customer-support` com 3 tools de suporte |
| Comunicação entre agentes | agent-as-tool in-process; steps aninhados persistidos |
| `POST /chat` `{message, user_id}` | **aceita ambos os formatos** (`{message,user_id}` e `{question,userId}`) via alias |
| Docker | imagem self-contained (sem bind mounts) + compose completo |
| Bonus: 4º agente / canal | Telegram: front-end de chat + canal de escalação |
| Bonus: Guardrails | input/output no caminho de produção, structured output, fail-closed p/ dados sensíveis |
| Bonus: Redirect para humano | tool `escalate_to_human` + FSM de handoff + tickets com botões no Telegram |

**Segurança das tools de suporte:** o identificador do cliente vem **sempre** da sessão
autenticada (`ToolRunContext.user_ref`), nunca de parâmetro escolhido pelo LLM — prompt
injection não consegue ler dados de outro cliente.

---

## API (resumo)

| Área | Endpoints |
|---|---|
| Auth | `POST /api/v1/auth/register` · `login` · `logout` (revoga JWT) · `GET me` |
| Agents | `GET/POST /api/v1/agents` · `GET/PATCH/DELETE /api/v1/agents/{id}` |
| Tools | `GET /api/v1/tools` (catálogo p/ o builder de agentes) |
| Chat | `GET/POST /api/v1/chat/sessions` · `GET/POST .../{id}/messages` · `POST /api/v1/chat/messages/{id}/feedback` |
| Knowledge | `POST /api/v1/knowledge/ingest` · `GET jobs` · `POST query` |
| Evaluation | `GET/POST golden-items` · `POST golden-items/promote` · `GET/POST runs` |
| Integrations | `GET catalog` · Telegram: `connect`, `pairing-link`, `webhook`, `tickets` |
| Legado | `POST /chat` (contrato do desafio) · `GET /health` |

Segurança: JWT com denylist no logout, rate limit no login (sliding window por IP+email),
CORS restrito por configuração, senhas bcrypt, acesso a dados 100% via ORM/bound params.

---

## Telegram (demo com celular real)

1. Crie um bot no **@BotFather** (grátis) e copie o token.
2. Frontend → **Integrações** → cole o token → **Conectar**
   (o webhook exige `PUBLIC_BASE_URL` acessível — em dev, use `ngrok http 8000` ou `cloudflared`).
3. **Parear meu Telegram** → escaneie o **QR code** com o celular → `/start` automático.
4. Converse com o agente pelo Telegram. Envie `/support_here` no chat que deve receber escalações.
5. Quando o agente escala (`escalate_to_human`), chega um ticket com botões
   **Assumir / Resolver**; ao assumir, o bot silencia e suas respostas (reply no ticket)
   vão direto ao cliente.

Slack aparece na biblioteca de integrações como stub declarado — mesmo contrato de canal,
cliente diferente.

---

## Avaliação (Golden Dataset + Langfuse)

- Dataset seedado com os **10 cenários do enunciado Getnet** + itens adversariais; expandível
  pelo frontend. Feedback 👎 no chat pode ser **promovido a item golden**
  (`provenance=production_trace`) — o ciclo produção → dataset → regressão.
- **Runs de retrieval** (`layer=retrieval`) são determinísticos (recall@k, hit@k, MRR contra
  `gold_source_urls`), baratos e comparáveis entre versões da modelagem RAG.
- **Experimentos RAGAS** (`layer=full`): o golden dataset é sincronizado como Langfuse Dataset
  (`getnet-qa-v1`, botão "Sync → Langfuse"); o experimento roda RAG ponta a ponta sobre cada
  item via `langfuse.run_experiment` — um Dataset Run no Langfuse com um trace por item e
  scores **ragas-faithfulness** e **ragas-answer-relevancy** anexados. Itens `general_web` e
  `adversarial` ficam fora (testam roteamento/guardrails, não RAG).

## Observabilidade e feedback (Langfuse)

Stack Langfuse v3 completa no compose (UI em `http://localhost:3000`, login
`admin@skywalker.local` / `skywalker-admin-123`; chaves provisionadas headless).

- **Traces**: cada turno é um trace `chat_turn` com `session_id`/`user_id`/tags propagados a
  todos os spans (modelo, tools, guardrails) via `propagate_attributes`; tokens reais por geração.
- **Scores a partir do chat**: 👍/👎 → score `user-feedback` no trace exato da resposta
  (`trace_id` persistido por mensagem); "Avaliar conversa" (1–5 ★) → score `session-rating`
  na sessão inteira; ambos visíveis e editáveis no Langfuse.
- **Revisão humana**: "revisar" numa resposta envia o trace para a annotation queue
  `chat-review` (score config `review-quality` 1–5) — o revisor anota na UI do Langfuse.
- **Prompt management**: os prompts dos agentes vivem no Langfuse (`agent-{slug}`, label
  `production`; baseline do banco é seed + fallback). Edite/promova uma versão na UI do
  Langfuse e o app passa a servi-la em ~60s **sem redeploy**; cada geração fica linkada à
  versão de prompt usada (tracking de qualidade/custo por versão).

---

## Testes

```bash
poetry run pytest tests/unit -v     # 42 testes, sem serviços externos
poetry run ruff check app tests
```

Cobertura por camada: security (bcrypt/JWT/denylist), rate limiter, chunker
(header-context embutido no texto, overlap por seção), métricas de eval, APIs de auth/agents
(CRUD + validação de catálogo), e o **pipeline de chat ponta-a-ponta** com o `TestModel` do
PydanticAI — incluindo os dois formatos do `POST /chat`, continuidade de sessão, steps,
feedback e isolamento entre usuários.

---

## Estrutura

```
app/
  main.py                 # app factory + lifespan (DB, seeds, stores, rate limiter)
  api/v1/{router,dependencies}.py
  core/{config,db,security,rate_limit,logging}.py
  modules/<nome>/{api,service,repository,models,schemas,enums}.py
    auth/ agents/ chat/ tools/ knowledge/ evaluation/ integrations/ guardrails/
frontend/                 # React + Vite + TS + Tailwind
docker/                   # Dockerfile (api), Dockerfile.frontend, nginx.conf, docker-compose.yml
db/support_db/            # sistema de suporte mock (SQLite, seedado no boot)
tests/unit/               # pytest, tudo mockado/in-memory
```
