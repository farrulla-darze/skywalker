# Skywalker — Plataforma Multi-Agente de Suporte (desafio Getnet)

Solução para o desafio técnico **"AI Hardcore Engineer — Multi-Agent Support System"** da Getnet
([enunciado completo](getnet_challenge.md)). É um monorepo **FastAPI + PydanticAI** (backend) e **React**
(frontend) onde um agente roteador orquestra três especialistas, com RAG local (**Qdrant**), knowledge
graph opcional (**Neo4j**), golden dataset com avaliação versionada (**Langfuse**), guardrails no caminho
de produção e escalação humana real via **Telegram** — sem ngrok, sem túnel, funcionando no `localhost`.


---

## Sumário

- [Visão geral](#visão-geral)
- [Quickstart](#quickstart)
- [Mapeamento do desafio](#mapeamento-do-desafio)
- [Arquitetura de agentes](#arquitetura-de-agentes)
- [Pipeline RAG](#pipeline-rag-ingestão--storage--retrieval--geração)
- [Customer Support Agent — tools](#customer-support-agent--tools)
- [Escalação humana (`consult_human`)](#escalação-humana-consult_human)
- [Telegram](#telegram-canal-de-chat-e-escalação)
- [API](#api)
- [Autenticação e segurança](#autenticação-e-segurança)
- [Avaliação e Observabilidade (Langfuse)](#avaliação-e-observabilidade-langfuse)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Configuração (.env)](#configuração-env)
- [Limitações conhecidas e roadmap](#limitações-conhecidas-e-roadmap)

---

## Visão geral

```
frontend/ (React + Vite + TS)              app/ (FastAPI)
┌──────────────────────────┐               ┌─────────────────────────────────────────┐
│ Login/Registro (JWT)      │  /api/v1/*   │ api/v1/router.py  (wiring central)       │
│ Chat (steps do agente,    │ ───────────▶ │ modules/                                 │
│   feedback 👍/👎)         │               │   auth · agents · chat · tools           │
│ Agentes (CRUD + tools)    │               │   knowledge · evaluation                 │
│ Integrações (Telegram+QR) │               │   integrations · guardrails              │
│ Avaliação (golden + runs) │               │ core/ (config, security, db, tracing)    │
└──────────────────────────┘               └──────────┬────────────────────────────────┘
                                                        │
                     ┌───────────┬──────────────┬──────┼──────────┬──────────────┐
                     ▼           ▼              ▼      ▼          ▼              ▼
                PostgreSQL    Qdrant         Neo4j   Telegram   Langfuse       OpenAI
                (estado)     (vetores)     (grafo,   (chat +   (traces,      (chat +
                                            opcional) escalação) evals,       embeddings +
                                                                 prompts)     RAGAS judge)
```

**Fluxo de uma mensagem:**
`input guardrail → handoff check (bot vs. humano) → Get (agente roteador) → delegação para
especialistas (tool call in-process) → consult_human quando necessário → output guardrail →
persistência (mensagem, steps intermediários, tokens reais, trace_id)`.

Enquanto uma sessão está sob atendimento humano assumido (Telegram), o LLM não é chamado — ver
[Escalação humana](#escalação-humana-consult_human).

---

## Quickstart

### Docker (stack completa — recomendado)

```bash
cp .env.example .env       # preencha OPENAI_API_KEY (obrigatório — veja Configuração abaixo)
docker compose --env-file .env -f docker/docker-compose.yml up --build
```

> `--env-file .env` é obrigatório: o compose vive em `docker/` e resolve o `.env` padrão relativo a
> essa pasta, não à raiz do repo. Sem a flag, as variáveis substituem por vazio e a API não sobe.

| Serviço | URL | Observação |
|---|---|---|
| Frontend | http://localhost:3001 | React + nginx |
| API + docs (Swagger) | http://localhost:8000/docs | |
| Qdrant dashboard | http://localhost:6333/dashboard | vetores |
| Neo4j browser | http://localhost:7474 | grafo (`neo4j` / `skywalker-graph`) — desabilitado por padrão, ver §RAG |
| Langfuse | http://localhost:3000 | login `admin@skywalker.local` / `skywalker-admin-123`; sobe sempre junto (não há profile separado) |

O compose usa `postgres` como banco de aplicação (o `.env.example` traz SQLite como default para uso
**local sem Docker**; dentro do compose a `DATABASE_URL` é sobrescrita para Postgres automaticamente).

### Local (dev, sem Docker)

```bash
# Backend
poetry install --extras dev
cp .env.example .env
poetry run uvicorn app.main:app --reload --port 8000

# Frontend (outro terminal)
cd frontend && npm install && npm run dev   # http://localhost:5173 (proxy para :8000)

# Infra mínima (se não usar o compose completo):
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/skywalker-graph neo4j:5-community
```

### O que já vem pronto no primeiro boot (sem nenhum passo manual)

No `startup` do FastAPI (`app/main.py`), a aplicação:

1. Cria as tabelas (`create_all` + migrações leves idempotentes).
2. **Seeda os 4 agentes de sistema** — Get (Router), Knowledge Specialist, Customer Support Specialist,
   Account Operations — com os prompts completos descritos em [Arquitetura de agentes](#arquitetura-de-agentes).
3. **Seeda o golden dataset** com os 10 cenários literais do enunciado Getnet + 2 itens adversariais
   (ver [Golden Dataset](#golden-dataset)).
4. **Seeda o banco de suporte mock** (`db/support_db/support.db`, ~50 clientes/merchants/transferências/
   incidentes) — o arquivo já vem commitado e é copiado para dentro da imagem Docker, então funciona em
   `docker build && docker run` puro, sem bind mount.
5. Sincroniza os prompts dos agentes para o Langfuse (baseline = seed do banco).

### O único passo manual: ingerir a base de conhecimento (RAG)

O Qdrant (e o Neo4j, se habilitado) começam **vazios** — ninguém ingere URLs automaticamente no boot.
Para popular a base com as páginas da Getnet usadas no golden dataset:

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "getnet",
    "urls": [
      "https://site.getnet.com.br/maquininha/get-classica/",
      "https://site.getnet.com.br/maquininha/get-smart/",
      "https://site.getnet.com.br/todas-as-maquininhas/",
      "https://site.getnet.com.br/pix/",
      "https://site.getnet.com.br/conta-digital/",
      "https://site.getnet.com.br/duvidas/",
      "https://site.getnet.com.br/get-ajuda-antecipacao-de-venda/",
      "https://site.getnet.com.br/crediario/",
      "https://site.getnet.com.br/link-de-pagamento/"
    ]
  }'
```
(Se estiver autenticado via frontend, o mesmo pode ser feito pela tela **Base de Conhecimento** —
UI para colar URLs e acompanhar o job.) Acompanhe com `GET /api/v1/knowledge/jobs/{job_id}`. Isso não
está automatizado em CI/cloud hoje — ver [Limitações conhecidas](#limitações-conhecidas-e-roadmap).

---

## Mapeamento do desafio

| Requisito do enunciado | Implementação | Status |
|---|---|---|
| **Agent 1 — Router** | Agente `sky-router` ("Get"), prompt completo de roteamento/escopo/idioma/política de consulta humana (`app/modules/agents/seeds.py`) | ✅ |
| **Agent 2 — Knowledge** (RAG + web search) | `Knowledge Specialist`: `graph_search` (Neo4j, fees) → `rag_search` (Qdrant) → `web_search` (perguntas gerais) | ✅ |
| **Agent 3 — Customer Support** (2+ tools) | `Customer Support Specialist`: 3 tools de leitura (`get_customer_overview`, `get_recent_operations`, `get_active_incidents`) | ✅ |
| Mecanismo de comunicação entre agentes | Agent-as-tool in-process (PydanticAI `tool_plain`); router mantém a conversa, especialistas são stateless por chamada; steps aninhados persistidos e exibidos no frontend | ✅ |
| `POST` `{message, user_id}` → JSON | `POST /chat` aceita **ambos** `{message, user_id}` (spec literal) e `{question, userId}` via `AliasChoices` do Pydantic | ✅ |
| Dockerização | `Dockerfile` copia `app/` e `db/` — builda e roda sem bind mount; `docker-compose.yml` para a stack completa | ✅ |
| Testes descritos | Ver [Testes](#testes) — 12 arquivos, tudo mockado/in-memory, sem serviços externos | ✅ |
| **Bônus: 4º agente** | `Account Operations` — executa mudanças de conta (liberar transferência, habilitar/desabilitar produto) **somente** após autorização humana explícita na conversa | ✅ |
| **Bônus: Guardrails** | Input/output guardrails no caminho real de produção (`chat/service.py`), veredito estruturado (Pydantic `output_type`), política fail-open na entrada / fail-closed na saída sensível | ✅ |
| **Bônus: Redirect/handoff humano** | `consult_human`: o agente consulta um humano no Telegram e aguarda a resposta, permanecendo no controle da conversa (ver seção dedicada) | ✅ (padrão síncrono; ver nota abaixo) |
| **Bônus: avaliação/observabilidade** | Golden dataset + Langfuse (traces, scores, prompt management, RAGAS) — ver seção dedicada | ✅ |

**Nota sobre o handoff:** existe também, no modelo de dados, um fluxo de **handoff completo** (ticket com
botões "Assumir/Resolver", máquina de estados `bot → pending_human → human → bot`) — mas hoje o caminho
realmente exercitado pelo sistema é o `consult_human` síncrono descrito abaixo, que é intencionalmente
mais simples: o agente nunca solta a conversa, só pausa para perguntar. O ticket completo fica como
próximo passo natural (ver [roadmap](#limitações-conhecidas-e-roadmap)).

**Segurança das tools de suporte:** o identificador do cliente vem **sempre** do `ToolRunContext.user_ref`
(a sessão autenticada), nunca de um parâmetro que o LLM escolhe — prompt injection não consegue pedir
dados de outro cliente (`app/modules/tools/service.py`, `app/modules/tools/definitions/support_db.py`).

### RAG / Graph / Web Search — hiperparâmetros atuais

| Camada | Configuração atual |
|---|---|
| Chunking | `chunk_size=1024`, `chunk_overlap=150`, overlap **restrito à mesma seção** (nunca atravessa headers); o header hierárquico ("Maquininha Smart > Taxas") é **prependado ao texto embeddado**, não só guardado em metadata (`app/modules/knowledge/chunker.py`) |
| Embeddings | OpenAI `text-embedding-3-large`, `dimensions=1024`, lote de 100 |
| Vector store | Qdrant, coleção `skywalker_kb`, distância cosseno, filtro obrigatório por `namespace` (payload) |
| Retrieval | **Denso puro** — `top_k=5`, sem BM25/híbrido, sem reranking, sem filtro por `source_url`/produto |
| Graph search | Neo4j, schema de domínio fixo `(Product)-[HAS_FEE]->(Fee)`, `-[HAS_FEATURE]->(Feature)`; fatos extraídos por LLM com `output_type` tipado a partir dos chunks já ingeridos (`POST /knowledge/graph/extract`); **desabilitado por padrão** (`GRAPH_ENABLED=false`) — a tool retorna aviso explícito quando desligado |
| Web search | `ddgs` (DuckDuckGo), timeout de 20s, até 2 tentativas com backoff; sem limite de concorrência (sem semáforo) |
| Ingestão | Job assíncrono persistido em tabela (`ingestion_jobs`) — sobrevive a restart/múltiplos workers; scrape (`trafilatura`) → chunk → embed → upsert, progresso salvo por URL |

---

## Arquitetura de agentes

Framework: **PydanticAI**. Agentes são **registros de banco** (`app/modules/agents/models.py`), editáveis
via CRUD pelo frontend (Agentes → tools disponíveis no catálogo `GET /api/v1/tools`). Os 4 agentes de
sistema são re-sincronizados do código a cada boot (prompts evoluem com o repositório), mas continuam
editáveis em runtime — e o Langfuse pode sobrepor a versão servida sem redeploy (ver
[Gestão de prompts](#gestão-e-versionamento-de-prompts)).

```
                              POST /chat, /api/v1/chat/...
                                        │
                                Input Guardrail (fail-open)
                                        │
                         ┌──────────────▼───────────────┐
                         │        Get (Router)          │  ← dono da conversa e do histórico
                         │  tools: consult_human         │
                         └──┬───────────┬───────────┬────┘
                            │           │           │  (agent-as-tool, in-process)
                  ┌─────────▼──┐ ┌──────▼───────┐ ┌─▼────────────────┐
                  │ Knowledge  │ │  Customer     │ │ Account          │
                  │ Specialist │ │  Support      │ │ Operations       │
                  │            │ │  Specialist   │ │ (WRITES)         │
                  │ graph_search│ │ get_customer_ │ │ release_transfer │
                  │ rag_search │ │  overview     │ │ set_transfers_   │
                  │ web_search │ │ get_recent_   │ │  enabled         │
                  │            │ │  operations   │ │ set_product_     │
                  │            │ │ get_active_   │ │  enabled         │
                  │            │ │  incidents    │ │ (só após humano  │
                  │            │ │ consult_human │ │  autorizar)      │
                  └────────────┘ └───────────────┘ └──────────────────┘
                                        │
                                Output Guardrail (fail-closed em dado sensível)
                                        │
                              Resposta + steps + trace_id
```

- **Comunicação entre agentes:** cada especialista é registrado como uma *tool* do agente roteador
  (`pydantic_agent.tool_plain`, `app/modules/agents/runner.py`). Uma chamada de delegação instancia um
  `PydanticAgent` novo por request — especialistas são stateless; **o roteador é quem carrega o histórico
  da conversa** e decide quando delegar de novo.
- **Memória real de conversa:** o histórico é convertido para `ModelRequest`/`ModelResponse` do PydanticAI
  e passado via `message_history=` a cada turno — não é um histórico "achatado" em texto no prompt.
- **Tokens reais:** contados via `result.usage()`/`stream.usage()` do PydanticAI (custo/latência
  auditáveis por trace no Langfuse), não uma estimativa por `len(texto)//4`.
- **Guardrails de produção** (`app/modules/guardrails/`): veredito **estruturado** (`output_type=
  GuardrailVerdict`, sem parsing de string). Entrada checa prompt injection, pedido de dados de outro
  cliente, abuso — política **fail-open** (erro no guardrail não trava o atendimento). Saída checa
  vazamento de credencial/PII/invenção de taxa — política **fail-closed** apenas quando o texto de saída
  bate com marcadores sensíveis (cpf/cnpj/senha/token), senão também fail-open. Guardrails são
  desabilitados por padrão localmente (`GUARDRAILS_ENABLED=true` no `.env.example` do compose) e podem
  ser ligados/desligados por config sem redeploy de código.
- **Modelo de guardrail e timeouts:** `GUARDRAIL_MODEL` (default `openai:gpt-4.1-mini`) é
  deliberadamente um modelo **não-reasoning** — um modelo de reasoning (ex. `gpt-5-mini`) pode "pensar"
  por vários minutos num veredito ALLOW/BLOCK trivial (chegamos a observar uma chamada única de guardrail
  travando um turno inteiro do Telegram por mais de 10 minutos antes desse ajuste). Todo request a modelo
  (router, especialistas e guardrails) tem timeout configurável (`LLM_REQUEST_TIMEOUT_SECONDS`,
  `GUARDRAIL_TIMEOUT_SECONDS`) via `ModelSettings(timeout=...)`, que cai nos mesmos caminhos de
  fail-open/fail-closed acima em vez de travar indefinidamente.

---

## Pipeline RAG (ingestão → storage → retrieval → geração)

```
URLs → scrape (trafilatura, markdown limpo)
     → chunk (header-aware, 1024/150, overlap intra-seção)
     → embed (text-embedding-3-large, 1024d, lote de 100)
     → upsert (Qdrant, namespace = "getnet" por padrão)
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  rag_search (top_k=5,      graph_search (Neo4j; fatos tipados
  denso, cosine)            Product/Fee/Feature com source_url —
                             opcional, ver hiperparâmetros acima)
        │                        │
        └───────────┬────────────┘
                     ▼
       Knowledge Specialist compõe a resposta:
       taxas/preços → graph_search primeiro; produto/how-to → rag_search;
       fora do domínio Getnet → web_search. Cita SEMPRE a source_url —
       exigido pelo prompt, não validado programaticamente hoje.
```

A trilha de grafo existe porque taxas são **dados estruturados presos em prosa de marketing**
("12,40% no crédito parcelado em 12x") — recuperar por similaridade de cosseno nesse caso tem risco de
trazer o chunk da taxa errada. O grafo responde com um fato tipado e sua URL de origem em vez de um
trecho de texto reconstruído. Está desligado por padrão (`GRAPH_ENABLED=false`) porque exige o passo
extra de extração (`POST /knowledge/graph/extract`) sobre conteúdo já ingerido.

---

## Customer Support Agent — tools

| Tool | Tipo | O que faz |
|---|---|---|
| `get_customer_overview` | leitura | Perfil, merchant, produtos habilitados, status da conta (saldo, bloqueios de transferência e motivo, última liquidação), status de login |
| `get_recent_operations` | leitura | Transferências/liquidações recentes (incluindo falhas, com id), dispositivos registrados e conectividade |
| `get_active_incidents` | leitura | Incidentes ativos na plataforma — usado para não assumir "é problema da conta" quando é falha geral |
| `release_transfer` | **escrita** (Account Operations) | Libera uma transferência bloqueada — só após autorização humana explícita na conversa |
| `set_transfers_enabled` | **escrita** (Account Operations) | Bloqueia/desbloqueia transferências da conta |
| `set_product_enabled` | **escrita** (Account Operations) | Habilita/desabilita um produto do merchant |

Todas as seis operam **exclusivamente sobre o cliente autenticado** — o identificador vem do contexto de
sessão (`ToolRunContext.user_ref`), nunca de um argumento que o modelo escolhe, o que fecha a classe de
falha "IDOR via prompt injection" por construção. As tools de escrita não têm enforcement de autorização
no código (são chamadas por function-calling do LLM); a barreira é o próprio prompt do `Account
Operations`, que se recusa a agir sem uma instrução afirmando que um humano já autorizou aquela mudança
específica nesta conversa.

---

## Escalação humana (`consult_human`)

Não existe um "4º agente de escalação" separado — a escalação é uma **tool única e síncrona**,
`consult_human`, disponível para o Router e para o Customer Support Specialist. O desenho é deliberado:
**o agente nunca larga a conversa**. Ele posta UMA pergunta precisa (com contexto já levantado pelas
outras tools) para o time de suporte no Telegram, **bloqueia aquele turno** até a resposta (ou timeout),
e usa a resposta para responder ao cliente com suas próprias palavras — o cliente nunca vê o canal
interno.

**Quando o agente aciona `consult_human`** (conforme o prompt do Router,
`app/modules/agents/seeds.py`):

1. **Mudança de conta que exige permissão humana** — editar dados do cliente, verificar informação
   extra-privada, mudar tier/plano, aplicar desconto ou exceção de taxa, ou **liberar transferência
   retida por compliance/antifraude/bloqueio** (o agente nunca promete uma liberação sozinho).
2. **Baixa confiança em uma resposta complexa e de alto impacto** — fontes conflitantes, dado faltando,
   impacto financeiro relevante.
3. **Pedido explícito do cliente por um humano** — o agente consulta o especialista e retransmite a
   resposta, permanecendo como "voz" da conversa.

Depois que o humano autoriza uma mudança, o Router delega a execução ao **Account Operations**,
declarando explicitamente o que foi autorizado, por quem e o alvo exato (ex.: id da transferência) —
nunca promete uma ação que ainda não executou.

Isso é o que os 12 itens do golden dataset (10 cenários do enunciado + 2 adversariais) e o prompt do
Router cobrem como "cenários que escalam": qualquer coisa que toque autorização, exceção comercial ou
liberação de dinheiro. Perguntas de produto, taxa pública ou status de conta **não** escalam — são
resolvidas por retrieval/consulta direta.

**Resiliência do turno em stream:** enquanto o turno aguarda o humano, a conexão SSE (`/stream`) não fica
muda — o backend emite um evento `consultation` (`waiting` com segundos decorridos a cada poll de 2s,
depois `answered`/`timeout`) e um `ping` de keepalive a cada 15s sempre que não há evento natural (mesmo
mecanismo cobre esperas em specialists não-streaming e chamadas de guardrail). O frontend renderiza esse
progresso em vez de congelar a tela (`ToolRail` mostra "aguardando especialista no Telegram · Ns"); se a
conexão cair mesmo assim (proxy, rede instável), o cliente volta a fazer polling em
`GET .../messages` até a resposta persistir — o turno em si nunca é cancelado no servidor (`ChatService.
run_turn_streaming` já rodava em background de forma independente da conexão; o que faltava era o cliente
não ficar mudo ou travado quando isso acontecia). `docker/nginx.conf` desliga buffering e sobe
`proxy_read_timeout` para acomodar o keepalive.

---

## Telegram (canal de chat e escalação)

O bot serve dois papéis: (1) **front-end de chat** alternativo ao frontend web — qualquer pessoa pode
conversar com o agente pelo celular; (2) **canal de escalação humana** — onde o `consult_human` posta
suas perguntas e recebe respostas.

### Por que não precisa de ngrok/Cloudflare (e como funciona hoje)

A versão anterior deste projeto exigia expor a API publicamente (`PUBLIC_BASE_URL` https + ngrok/
cloudflared) para o Telegram entregar mensagens via *webhook*. Isso **mudou**: o backend detecta se
`PUBLIC_BASE_URL` é um host público em `https://` (não `localhost`/`127.0.0.1`); se não for — o caso
padrão em dev e no `docker compose` local — ele **não tenta configurar webhook nenhum** e cai
automaticamente em **long-polling** (`getUpdates`), com uma tarefa `asyncio` fazendo polling contínuo por
integração conectada (`app/modules/integrations/polling.py`). O mesmo código de tratamento de mensagem
(`handle_update`) atende os dois modos — o comportamdo do agente é idêntico, só muda o transporte. Ou
seja: **hoje, testar o bot não exige nenhuma URL pública, túnel ou deploy** — funciona 100% com
`localhost:8000`.

### Passo a passo para quem for testar (leva ~3 minutos)

O **@BotFather** não é um site de busca — é o próprio bot oficial do Telegram para criar outros bots,
te-lo é literalmente uma conversa dentro do app do Telegram:

1. **Abra o Telegram** (app ou web) e procure por `@BotFather` na busca (é o bot verificado oficial).
2. Envie `/newbot`, escolha um nome de exibição e um `username` terminado em `bot` (ex.:
   `getnet_eval_bot`). O BotFather responde com um **token** (`123456:ABC-...`) — copie-o.
3. No frontend do Skywalker, vá em **Integrações** → cole o token em Telegram → **Conectar**. Com o
   `.env` local padrão, a conexão cai automaticamente em modo *polling* (sem nenhuma configuração extra
   sua).
4. Clique em **"Parear meu Telegram"** — aparece um QR code. Escaneie com a câmera do celular (ou abra o
   link direto que aparece na tela). Isso abre o Telegram e envia `/start <código>` automaticamente,
   vinculando seu chat do Telegram à sua conta no Skywalker.
5. **Converse com o bot normalmente** — mande qualquer uma das perguntas de exemplo do enunciado (ex.:
   *"What's the difference between the Get Clássica and the Get Smart?"*). Em ~1s o polling entrega a
   mensagem, o agente processa (router → especialista → resposta) e a resposta chega no seu Telegram —
   é o mesmo agente e o mesmo backend do chat web, só por outro canal. O Telegram mostra "digitando…"
   enquanto o turno roda; se o turno estourar `TELEGRAM_TURN_TIMEOUT_SECONDS`, o bot responde com uma
   mensagem de fallback em vez de deixar o cliente sem retorno.
6. **Para testar a escalação humana:** em qualquer chat do Telegram (pode ser o mesmo ou outro), envie
   `/support_here` — esse chat vira o "chat de suporte" que recebe as consultas do `consult_human`. Peça
   algo que force uma consulta (ex.: *"preciso de um desconto na taxa"* ou *"libera minha transferência
   bloqueada"*). O agente pausa, uma mensagem chega no chat de suporte com a pergunta e o contexto; para
   responder, **basta usar "Responder" (reply) na mensagem do Telegram** — a resposta é entregue de volta
   ao agente, que retoma a conversa com o cliente usando essa informação. Enquanto isso, quem estiver no
   chat web vê o passo `consult_human` ativo com o tempo de espera ao vivo, em vez da tela congelar até o
   fim do turno.

Slack aparece na biblioteca de integrações (`GET /api/v1/integrations/catalog`) como canal declarado —
mesmo contrato de integração, cliente diferente — mas sem implementação hoje; o Telegram foi escolhido
porque um avaliador consegue criar um bot e testar a demo completa em minutos, sem workspace corporativo.

---

## API

Prefixo `/api/v1` para os módulos versionados; `/chat` (contrato do desafio) e `/health` ficam fora do
prefixo.

| Área | Endpoints | Observação |
|---|---|---|
| Auth | `POST auth/register` · `login` · `logout` · `GET auth/me` | logout revoga o JWT (denylist em banco) |
| Agents | `GET/POST agents` · `GET/PATCH/DELETE agents/{id}` | CRUD dos agentes (sistema + customizados) |
| Tools | `GET tools` | catálogo para o builder de agentes no frontend |
| Chat | `GET/POST chat/sessions` · `GET/POST .../{id}/messages` (+ `/stream` SSE) · `POST messages/{id}/feedback` · `POST messages/{id}/review` · `POST sessions/{id}/score` | sessão versionada, com feedback e revisão humana ligados ao Langfuse |
| Knowledge | `POST knowledge/ingest` · `GET knowledge/jobs[/{id}]` · `POST knowledge/query` · `POST knowledge/graph/extract` · `GET knowledge/graph/products` | ingestão assíncrona + RAG query + extração de grafo |
| Evaluation | `GET/POST evaluation/golden-items` · `PATCH .../{id}` · `POST golden-items/promote` · `POST langfuse/sync-dataset` · `GET/POST evaluation/runs` · `GET runs/{id}[/results]` | golden dataset + runs de avaliação |
| Integrations | `GET integrations/catalog` · Telegram: `GET/POST/DELETE telegram`, `GET telegram/pairing-link`, `POST telegram/webhook/{id}` (validado por secret token, oculto do OpenAPI) · `GET integrations/tickets` | |
| Legado / infra | `POST /chat` (contrato literal do desafio: `{message, user_id}`, também aceita `{question, userId}`) · `GET /health` | `/chat` é público por padrão (`ALLOW_ANONYMOUS_CHAT=true`); todo o resto exige JWT |

Todos os endpoints acima de "Legado / infra" exigem `Authorization: Bearer <jwt>`. `/chat` é a exceção
proposital — é o contrato exato pedido pelo enunciado, e um avaliador deve conseguir chamá-lo com `curl`
sem se autenticar primeiro.

---

## Autenticação e segurança

- **Senha:** hash com `bcrypt` (custo padrão da lib), nunca texto plano em lugar nenhum.
- **Login:** `POST auth/login` retorna um JWT (`HS256`, `exp` configurável via `JWT_EXPIRES_MINUTES`,
  60 min por padrão). Mensagem de erro genérica tanto para e-mail inexistente quanto senha errada (não
  vaza qual das duas falhou).
- **Rate limit de login:** sliding window em memória, chave `IP + email`, `5` tentativas por `300s`
  (`LOGIN_RATE_LIMIT_ATTEMPTS`/`_WINDOW_SECONDS` no `.env`) — `429` com `Retry-After` ao estourar; uma
  janela é limpa após um login bem-sucedido. É por processo (não distribuído) — suficiente para o escopo
  do desafio, mas precisaria de um backend compartilhado (Redis) para múltiplas instâncias em produção.
- **Logout real:** não é apenas "esquecer o token no cliente" — o `jti` do JWT é gravado numa tabela de
  denylist (`revoked_tokens`) no logout, e **toda** rota autenticada checa essa tabela antes de aceitar o
  token. Um JWT usado após logout é rejeitado mesmo que ainda não tenha expirado.
- **CORS:** restrito à lista configurada em `CORS_ORIGINS` (não é wildcard `*`).
- **Acesso a dados:** 100% via SQLAlchemy ORM com parâmetros vinculados — nenhuma concatenação de SQL
  com input do usuário em nenhum repositório.
- **`/chat` anônimo é intencional:** o contrato do desafio não prevê autenticação nesse endpoint
  específico; `ALLOW_ANONYMOUS_CHAT=false` desliga esse acesso público se necessário, sem afetar a API
  versionada (que sempre exigiu JWT).

---

## Avaliação e Observabilidade (Langfuse)

O Langfuse v3 completo sobe junto no `docker compose` (Postgres, ClickHouse, Redis, MinIO, web + worker),
com organização/projeto/usuário admin e chaves de API **provisionados de forma headless** no primeiro
boot — nenhum passo manual de setup. UI em `http://localhost:3000`
(`admin@skywalker.local` / `skywalker-admin-123`).

### Golden Dataset

Cada item é um registro tipado (`app/modules/evaluation/models.py`) com: `question`, `locale`
(`pt-BR`/`en-US`), `category`, `difficulty`, `expected_answer`, `expected_facts`, `gold_source_urls`
(ground truth de retrieval), `expected_route` / `expected_tools` (ground truth de roteamento),
`provenance` e `reviewed_by`.

O seed atual (`seed:getnet-v1`) tem **12 itens**:

| Categoria | Qtd | Exemplo |
|---|---|---|
| `product_howto` | 3 | Get Clássica vs. Get Smart; Pix sem conta bancária; Payment Link no WhatsApp |
| `account_issue` | 3 | Prazo de depósito de vendas; maquininha sem internet; erro de transação recusada |
| `fees` | 2 | Antecipação de recebíveis; parcelamento do crediário (até 48x) |
| `general_web` | 2 | Previsão do tempo em Porto Alegre; cotação do euro |
| `adversarial` | 2 | Extração de system prompt; pedido de dados de outro cliente |

São **exatamente os 10 cenários literais do enunciado** (nada inventado) + 2 adversariais próprios.
Gerações anteriores de seed (de um domínio antigo, InfinitePay) são arquivadas, nunca apagadas, para
runs de avaliação antigos continuarem interpretáveis.

**Ciclo de produção → dataset:** um feedback 👎 numa resposta pode ser **promovido** a item golden
(`POST evaluation/golden-items/promote`) — cria um `GoldenItem` com `provenance=production_trace`,
recuperando a pergunta do turno anterior na mesma sessão. É uma promoção manual, item a item, não um
pipeline automático reagindo a todo 👎.

### Scores

| Score | Origem | Como chega no Langfuse |
|---|---|---|
| `user-feedback` | 👍/👎 numa resposta do chat | número 0/1, anexado ao `trace_id` daquela mensagem específica |
| `session-rating` | "Avaliar conversa" (1–5 ★) | anexado à sessão inteira |
| `review-flag` | "Marcar para revisão" numa resposta | envia o trace para a fila de anotação `chat-review` |
| `review-quality` | Revisor humano, na própria UI do Langfuse | 1–5, preenchido manualmente na annotation queue, não pelo app |
| `ragas-faithfulness` / `ragas-answer-relevancy` | Experimento RAGAS (camada `full`) | calculado pela lib `ragas`, anexado ao Dataset Run |

### Runs de avaliação — duas camadas

- **`layer=retrieval`** (barata, determinística, sem LLM): consulta o Qdrant para cada item do golden
  dataset e calcula `recall@k`, `hit@k` e `MRR` contra `gold_source_urls`. Roda em segundos, comparável
  entre versões de chunking/embedding.
- **`layer=full`** (RAGAS ponta a ponta): o golden dataset é sincronizado como um **Langfuse Dataset**
  (`getnet-qa-v1`, botão "Sync → Langfuse" — itens `adversarial`/`general_web` ficam de fora porque não
  medem qualidade de RAG) e o experimento roda via `langfuse.run_experiment(...)`: cada item vira um
  trace dentro de um **Dataset Run**, com as métricas RAGAS calculadas como evaluators e anexadas como
  scores. RAGAS exige `python < 3.13`, então só roda dentro da imagem Docker (import é feito de forma
  lazy/guardado — em Python 3.14 local ele é pulado silenciosamente com aviso no log).

### Métricas de RAG (RAGAS) — o que cada uma mede

O sistema hoje calcula **`faithfulness`** e **`answer_relevancy`** de cada resposta gerada. A família
completa de métricas do "RAG triad" do RAGAS é:

| Métrica | O que mede | Avalia |
|---|---|---|
| **Faithfulness** | Proporção de afirmações da resposta que são de fato sustentadas pelo contexto recuperado (fração de claims verificáveis / total de claims) — a métrica clássica anti-alucinação | qualidade da **geração** |
| **Answer Relevancy** | Quão diretamente a resposta responde à pergunta feita (não é sobre correção factual, é sobre foco/pertinência) | qualidade da **geração** |
| **Context Precision** | Dos chunks recuperados, quantos são de fato relevantes/úteis para responder — retrieval "sujo" (muito ruído) penaliza aqui | qualidade do **retrieval** |
| **Context Recall** | Se o contexto recuperado contém informação suficiente para cobrir a resposta esperada — retrieval "incompleto" penaliza aqui | qualidade do **retrieval** |

Faithfulness/Answer Relevancy isolam problema de **geração** (o LLM inventou ou divagou mesmo tendo bom
contexto?); Context Precision/Recall isolariam problema de **retrieval** (o RAG não trouxe o chunk certo?)
— essas duas últimas ainda não estão conectadas neste projeto (ver
[roadmap](#limitações-conhecidas-e-roadmap)); hoje esse diagnóstico é coberto de forma mais barata pela
camada `retrieval` (recall@k/hit@k/MRR determinísticos contra `gold_source_urls`), que já responde "o
chunk certo foi recuperado?" sem precisar de um LLM-judge.

*(Definições consolidadas a partir da documentação oficial do RAGAS —
[docs.ragas.io/concepts/metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/) —
e de um comparativo recente de métricas de avaliação de RAG:
[confident-ai.com — RAG Evaluation Metrics](https://www.confident-ai.com/blog/rag-evaluation-metrics-answer-relevancy-faithfulness-and-more).)*

### LLM-as-Judge

O julgamento hoje é inteiramente delegado à biblioteca `ragas`, configurada com `gpt-4.1-mini` como
modelo-juiz (`RAGAS_MODEL`). Não há um judge customizado próprio (ex.: para `fact_coverage` ou
`citation_validity`) — é um próximo passo natural de evolução, não uma peça faltando por descuido: RAGAS
com um bom juiz já cobre a fração mais cara (faithfulness/relevancy) e a camada determinística cobre o
resto sem custo de LLM.

### Gestão e versionamento de prompts

Os prompts de cada agente vivem no Langfuse (`agent-{slug}`, label `production`), com **fallback** para o
`instructions` gravado no banco caso o Langfuse esteja indisponível ou o prompt ainda não exista lá. No
boot, o app cria no Langfuse os prompts que faltarem a partir do baseline do banco — mas **nunca
sobrescreve** uma versão que já existe lá. Ou seja: depois do primeiro boot, editar e promover uma nova
versão para o label `production` **na própria UI do Langfuse** é a forma canônica de mudar o
comportamento de um agente — o app passa a servir a nova versão em até **60 segundos** (cache com TTL),
**sem redeploy**. Cada geração do modelo fica linkada à versão de prompt usada (`propagate_attributes`),
então dá para comparar qualidade/custo por versão de prompt diretamente nos traces.

### Granularidade do tracing

Cada turno de chat gera um trace raiz `chat_turn`, com `session_id`, `user_id` e tags (ex.: canal:
`web`/`telegram`) propagados a **todos** os spans filhos automaticamente. Chamadas de modelo e de tools
viram spans aninhados nativamente via `Agent.instrument_all()` do PydanticAI — isso vale tanto para o
roteador quanto para cada especialista delegado quanto para o agente de guardrail (quando habilitado), de
forma que uma única árvore de trace mostra o turno inteiro: guardrail de entrada → decisão de roteamento
→ tool calls do especialista → guardrail de saída. O `trace_id` de cada resposta fica persistido na
própria mensagem, o que é o que permite o feedback 👍/👎 e "marcar para revisão" apontarem para o trace
exato.

---

## Testes

```bash
poetry run pytest              # 12 arquivos em tests/unit, tudo mockado/in-memory
poetry run ruff check app tests
poetry run mypy app
```

Nenhum teste depende de serviço externo: banco é SQLite in-memory, `graph_enabled`/`langfuse_enabled`
ficam fixados em `False` no `conftest.py`, e o LLM é substituído pelo `TestModel` do PydanticAI (sem
custo, sem chave de API, determinístico). `tests/integration/` existe como diretório reservado mas está
vazio hoje — a estratégia de integração real (LLM de verdade, Qdrant/Neo4j/Langfuse reais) está descrita
no [roadmap](#limitações-conhecidas-e-roadmap).

Cobertura por área: segurança (bcrypt/JWT/denylist), rate limiter (sliding window), chunker
(header-context embutido, overlap intra-seção), métricas de avaliação (hit@k/MRR/normalização de URL),
migração de seeds do golden dataset, persistência de jobs de ingestão, tools de operações de conta
(escopo/guarda de autorização), consulta humana (`consult_human`, persistência/handshake), CRUD de
agentes + seeding, e o **`AgentRunner`** e o **pipeline de chat ponta-a-ponta** com modelo mockado —
incluindo os dois formatos aceitos por `POST /chat`, continuidade de sessão, steps intermediários,
feedback e isolamento entre usuários.

**Estratégia para testes de integração mais completos** (não implementados, descrição conforme pedido no
enunciado): subir a stack real via `docker compose` num ambiente de CI, rodar os 10 cenários do enunciado
contra `POST /chat` com um LLM real (modelo barato, ex. `gpt-5-mini`), e validar: (1) `expected_route`/
`expected_tools` do golden dataset batem com o trace produzido; (2) a camada `retrieval` do harness de
avaliação (`recall@k`/`hit@k`) não regride abaixo de um baseline congelado; (3) os 2 itens adversariais
resultam em recusa (nenhum vazamento de system prompt ou dado de outro cliente); (4) round-trip completo
do Telegram em modo polling (enviar `/start`, mandar mensagem, checar resposta) contra um bot de teste
dedicado.

---

## Estrutura do projeto

```
app/
  main.py                    # app factory + lifespan (DB, seeds, stores, rate limiter, polling)
  api/v1/{router,dependencies}.py
  core/{config,db,security,rate_limit,logging,tracing}.py
  modules/<nome>/{api,service,repository,models,schemas,enums}.py
    auth/ agents/ chat/ tools/ knowledge/ evaluation/ integrations/ guardrails/
frontend/
  src/pages/          # Login, Register, Chat, Agents, Integrations, Evaluation
  src/components/ src/context/ src/api/
docker/               # Dockerfile (api), Dockerfile.frontend, nginx.conf, docker-compose.yml
db/support_db/        # SQLite mock de suporte, seedado no boot, commitado no repo
tests/unit/           # pytest, tudo mockado/in-memory
tests/integration/    # reservado, vazio hoje
```

---

## Configuração (.env)

`cp .env.example .env` e ajuste. Praticamente tudo já vem com um valor de desenvolvimento local seguro e
funcional — **a única credencial que você precisa obter fora do repositório é a da OpenAI**:

| Variável | Obrigatório? | Onde conseguir / observação |
|---|---|---|
| `OPENAI_API_KEY` | **Sim** | https://platform.openai.com/api-keys — usada para chat, embeddings e o modelo-juiz do RAGAS. Sem ela, agentes e ingestão não funcionam. |
| `JWT_SECRET` | Recomendado trocar em produção | Qualquer string longa e aleatória; o placeholder do `.env.example` só serve para dev local |
| `NEO4J_PASSWORD`, `QDRANT_URL`, `LANGFUSE_*` | Não | Já vêm com defaults que batem com os serviços do `docker-compose.yml` — nada a obter externamente |
| Token do bot do Telegram | Só se for testar essa integração | Não vai no `.env` — é colado na tela **Integrações** do frontend, por usuário. Ver [Telegram](#telegram-canal-de-chat-e-escalação) para como conseguir um em minutos via `@BotFather` |
| `GRAPH_ENABLED` | Não (default `false`) | Ligue para habilitar `graph_search`/extração de fatos; requer Neo4j de pé (já incluso no compose) |
| `GUARDRAILS_ENABLED` | Não | Liga/desliga guardrails sem redeploy |
| `GUARDRAIL_MODEL` | Não (default `openai:gpt-4.1-mini`) | Modelo não-reasoning para os vereditos de guardrail — reasoning models podem travar minutos num veredito trivial |
| `LLM_REQUEST_TIMEOUT_SECONDS` / `GUARDRAIL_TIMEOUT_SECONDS` | Não (default `120` / `30`) | Timeout por chamada de modelo (router/especialistas / guardrails); estoura para os caminhos fail-open/fail-closed existentes |
| `TELEGRAM_TURN_TIMEOUT_SECONDS` | Não (default `300`, elevado em runtime para `CONSULTATION_TIMEOUT_SECONDS + 120` se for maior) | Teto máximo de um turno no Telegram; ao estourar, envia uma mensagem de fallback em vez de deixar o cliente sem resposta |
| `LANGFUSE_ENABLED` | Não | Liga/desliga toda a instrumentação de tracing/scores/prompt management |
| `ALLOW_ANONYMOUS_CHAT` | Não (default `true`) | Desligue para exigir JWT também no endpoint `/chat` legado |

---

## Limitações conhecidas e roadmap

Transparência sobre o que ainda não está feito, para não sobre-vender o que existe:

- **CI não implementado** — não há `.github/workflows/`. `poetry run ruff check`, `mypy` e `pytest` estão
  configurados e passam localmente, mas não rodam automaticamente em PR.
- **Ingestão do RAG é manual** — Qdrant/Neo4j começam vazios; é preciso chamar `POST /knowledge/ingest`
  uma vez (comando pronto na seção [Quickstart](#o-único-passo-manual-ingerir-a-base-de-conhecimento-rag)).
  Agentes, golden dataset e banco de suporte, por outro lado, já vêm seedados automaticamente no boot.
- **Handoff completo (ticket com "Assumir/Resolver") existe no modelo de dados mas não é o caminho
  ativo** — o mecanismo realmente usado é o `consult_human` síncrono (ver
  [Escalação humana](#escalação-humana-consult_human)).
- **RAGAS hoje cobre só faithfulness/answer_relevancy** — context_precision/context_recall (qualidade do
  retrieval via LLM-judge) não estão conectados; a camada `retrieval` (recall@k/hit@k/MRR) cobre esse
  diagnóstico de forma determinística e mais barata, mas não é a mesma coisa.
- **Retrieval é denso puro** — sem híbrido (BM25), sem reranking, sem filtro por produto/URL. É o
  próximo ganho de qualidade mais barato de medir e aplicar, usando a própria camada `retrieval` do
  harness de avaliação como baseline antes/depois.
- **Rate limiter de login é por processo** — não hostilizaria uma única instância, mas precisaria de um
  backend compartilhado (Redis) antes de rodar com múltiplos workers/réplicas.
- **`tests/integration/` está vazio** — a estratégia está descrita em [Testes](#testes), mas a
  implementação (stack real em CI) ainda não existe.
- **`consult_human` disparado a partir de uma conversa no Telegram pode travar até o timeout** — o loop
  de long-polling (`app/modules/integrations/polling.py`) despacha updates serialmente numa única task;
  se o cliente que aciona `consult_human` está nesse mesmo canal, a task que precisaria processar a
  resposta do humano (outro update) fica bloqueada esperando o próprio turno terminar. O chat web é
  isento — lá a espera roda numa task por request. Corrigir exigiria despachar updates do Telegram em
  tasks concorrentes em vez de sequenciais.
