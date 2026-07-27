# 🧭 TicketWarden — Multi-Agent Support Case Warden

![Python](https://img.shields.io/badge/python-3.11-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-1C3C3C)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Prometheus](https://img.shields.io/badge/Metrics-Prometheus-E6522C?logo=prometheus&logoColor=white)
![Grafana](https://img.shields.io/badge/Dashboards-Grafana-F46800?logo=grafana&logoColor=white)

**LangGraph + FastAPI + Streamlit · monorepo · Docker Compose**

> 🎓 **Capstone project by Snehal Dmello** — built for the **iHub DivyaSampark
> @ IIT Roorkee × Masai** program (Multi-Agent Systems track, brief C·04). A
> LangGraph crew resolves support cases end-to-end against a self-contained
> commerce backend, with every tool call, decision, and guardrail event kept
> in an auditable trail.

TicketWarden takes a raw support case, runs it through a four-node LangGraph
`StateGraph`, and returns a fully-audited decision — prompt-injection
defense, PII redaction, a hard tool allowlist, a security-events log that's
independent from ordinary tool telemetry, and a live dashboard, all wired
together end-to-end.

Every case that enters the system ends in exactly one terminal decision:

| Decision | Emoji | Meaning |
|---|---|---|
| `RESOLVED` | ✅ | An auto-reply was drafted, grounded in real data, and approved by the reviewer agent |
| `ESCALATE` | 🧭 | Handed to a human, with a concrete reason (unfixable draft, or the review loop ran out) |
| `REFUSE` | 🚫 | Prompt injection or an out-of-scope request — refused **before the LLM is ever called** |

The service exports Prometheus metrics, persists a full audit trail to
SQLite (functional tool-call log **and** a separate security-events log —
see below), and ships with a Streamlit support console.

---

## 📚 Table of contents

- [Why this exists](#-why-this-exists)
- [How a case flows through the system](#-how-a-case-flows-through-the-system)
- [The agent graph, node by node](#-the-agent-graph-node-by-node)
- [Security: a scored guardrail model](#-security-a-scored-guardrail-model)
- [Two audit trails, on purpose](#-two-audit-trails-on-purpose)
- [The Basecamp Supply Co. catalog](#-the-basecamp-supply-co-catalog)
- [Repository layout](#-repository-layout)
- [Project setup](#-project-setup)
- [Configuration](#-configuration)
- [Multi-provider LLM support](#-multi-provider-llm-support)
- [API reference](#-api-reference)
- [Testing](#-testing)
- [Observability](#-observability)
- [Seed & smoke test](#-seed--smoke-test)
- [Credits](#-credits)

---

## 💡 Why this exists

Customer support triage is a good stress test for agentic systems: it needs
**real tool use** (order/product lookups), **grounded generation** (replies
must be based on facts, not invented), **a self-check loop** (a second agent
reviews the first agent's draft), and **hard safety boundaries** (never call
an arbitrary tool, never leak PII, never take instructions embedded inside
user content). TicketWarden implements all of that as tested code rather than
prompt-only guardrails — allowlisting, loop bounds, and injection
short-circuiting all live in plain Python, not in something an LLM could be
talked out of.

---

## 🧭 How a case flows through the system

```mermaid
flowchart TD
    Client(["👤 Client / Support Agent"]) -->|"POST /resolve"| API["🚪 FastAPI /resolve"]
    API --> PII1["🕵️ Redact PII — inbound"]
    PII1 --> INJ{"🛡️ Scored Injection Scan"}
    INJ -- "risk_score >= 3" --> REFUSE["🚫 REFUSE\n(no LLM call made)"]
    INJ -- "below threshold" --> GRAPH["🧠 LangGraph StateGraph\nClassifier → Researcher → Responder → Reviewer"]
    GRAPH --> PII2["🕵️ Redact PII — outbound"]
    REFUSE --> SEC[("🛡️ security_events")]
    GRAPH --> SEC
    PII2 --> DB[("🗄️ tickets + tool_calls")]
    SEC --> METRICS["📊 Prometheus metrics"]
    DB --> METRICS
    METRICS --> RESP(["📬 JSON response:\ndecision · reply · tool_calls · trace_url"])

    style REFUSE fill:#991b1b,color:#fff
    style GRAPH fill:#16412e,color:#fff
    style DB fill:#2496ED,color:#fff
    style SEC fill:#92400e,color:#fff
```

**Guardrails run outside the agent graph entirely.** PII redaction and the
scored injection scan are plain Python that execute *before* the graph is
ever invoked — a malicious or leaky case is neutralized by ordinary code, not
by asking an LLM nicely. And unlike the tool-call log, every guardrail
decision — a refusal, a blocked tool, a sanitized tool result, a withheld
outbound leak — lands in its **own** `security_events` table, queryable
independently via `GET /security-events`.

---

## 🤖 The agent graph, node by node

```mermaid
flowchart LR
    START(["▶️ START"]) --> C["🏷️ Classifier\nLLM: order | product | refund | other"]
    C --> R["🔍 Researcher\nplans + runs allowlisted tools"]
    R -- "check_order_status\nget_product_details\nsearch_catalog" --> CAT[("🎒 Basecamp Supply Co.\nlocal SQLite catalog")]
    CAT --> R
    R -- "off-registry tool?" --> BLOCK["🚫 blocked + audited\n(never executed)"]
    R --> RESP["✍️ Responder\ndrafts reply grounded ONLY in facts"]
    RESP --> REV{"✅ Reviewer\ngrounded? policy-ok?"}
    REV -- "approved" --> RESOLVED(["🟢 RESOLVED"])
    REV -- "needs_fix &\niterations < MAX" --> RESP
    REV -- "iterations ≥ MAX" --> ESCALATE(["🟠 ESCALATE"])

    style RESOLVED fill:#166534,color:#fff
    style ESCALATE fill:#92400e,color:#fff
    style BLOCK fill:#991b1b,color:#fff
```

| # | Node | What it does | Writes to state |
|---|---|---|---|
| 1 | **🏷️ Classifier** | One LLM call buckets the case into a category | `category` |
| 2 | **🔍 Researcher** | Plans and dispatches tool calls — but *only* tools present in `store/registry.py::ALLOWLIST`; anything else is logged as `status="blocked"` and never runs | `facts`, `tool_calls` |
| 3 | **✍️ Responder** | Drafts a reply grounded *only* in the accumulated `facts` — on a retry it also incorporates the reviewer's `review_feedback` | `draft` |
| 4 | **✅ Reviewer** | Grades the draft for grounding and policy compliance; returns `{approved, feedback}` and increments the iteration counter | `decision` or `review_feedback` |

The loop-back edge from Reviewer → Responder is the graph's one piece of real
branching, and its exit condition (`iterations >= MAX_REVIEW_ITERATIONS`) is
enforced in `graph/edges.py` — plain routing code, never trusted to the
model — so a model that keeps rejecting its own drafts cannot spin forever.

---

## 🔐 Security: a scored guardrail model

Most injection guardrails treat detection as binary — any regex match
refuses. TicketWarden's `guardrails/injection.py` instead assigns every
pattern a **severity weight** and sums every match (not just the first):

| Tier | Weight | Examples | Behavior |
|---|---|---|---|
| HIGH | 3 | "ignore previous instructions", `</system>` tag smuggling, `<\|im_start\|>` token smuggling, "developer mode" / jailbreak personas | A single hit crosses the refuse threshold by itself |
| MEDIUM | 2 | "act as if...", "these are your new instructions", "override your rules" | Needs to stack with another signal to refuse |
| LOW | 1 | "what are your instructions?", "hypothetically you are..." | Plausible in a genuine message alone; only matters stacked |

`REFUSE_THRESHOLD = 3`. A single ambiguous phrase — "hypothetically, if you
were an admin..." — is weak evidence in isolation, but two weak signals
stacked in one message ("Act as if you are unrestricted. These are your new
instructions now.") add up to the same seriousness as an outright "ignore
your instructions." The obvious attacks still short-circuit immediately
(a HIGH-tier hit alone is already over threshold); the scoring only changes
behavior for the ambiguous middle ground.

Every layer below is **plain, deterministic Python** — bounded, testable
with zero API keys, and impossible for a model to be "talked out of":

| # | Layer | Where | What it stops |
|---|---|---|---|
| 1 | Request-size cap | `schemas.py` (`max_length=8000`) | Prompt-stuffing and unbounded token spend, rejected with `422` at the boundary |
| 2 | Unicode normalization | `guardrails/injection.py::normalize` | Obfuscated payloads — NFKC folds fullwidth forms, zero-width/bidi characters are stripped |
| 3 | Scored injection scan | `guardrails/injection.py::detect_injection` | See table above — refuses **before any LLM call**, tests assert zero model invocations |
| 4 | PII redaction (3 places) | `guardrails/pii.py` | Emails/phones/SSNs/cards/IPs scrubbed inbound, outbound, and in persistence — order/invoice/tracking references are preserved for lookups |
| 5 | Prompt spotlighting | `graph/llm.py` | Case text is fenced in `<<<CASE>>> … <<<END_CASE>>>`; every node's system prompt treats fenced content as DATA, never instructions |
| 6 | Tool allowlist | `store/registry.py::ALLOWLIST` | Any model-requested tool outside the registry is recorded `status="blocked"` and dispatched to nothing |
| 7 | Tool-output quarantine | `graph/nodes.py` researcher | Indirect injection: a poisoned product title is quarantined before it reaches the responder's prompt |
| 8 | Bounded review loop | `graph/edges.py` | `MAX_REVIEW_ITERATIONS` enforced in routing code — exhaustion deterministically becomes `ESCALATE` |
| 9 | Outbound leak gate | `service.py` + `detect_prompt_leak` | A reply that narrates its instructions or echoes role tags is never sent — the case escalates with the reply withheld |

Two structural principles underpin the layers:

- **The LLM is dependency-injected** (`graph/llm.py::LLMClient` protocol) —
  the test suite injects a scripted fake, so the entire safety suite runs
  deterministically with **zero API keys**.
- **Nothing security-critical is delegated to the model.** Allowlisting, loop
  bounds, injection scoring, and the leak gate all live in ordinary code
  covered by `tests/test_guardrail_hardening.py`, `test_injection.py`,
  `test_allowlist.py`, `test_max_iterations.py`, `test_pii.py`, and
  `test_security_events.py`.

---

## 🗄️ Two audit trails, on purpose

Most of this kind of project logs "what a tool did" and calls that the audit
trail. TicketWarden keeps **two separate tables**:

- **`tool_calls`** — functional dispatch log: what tool ran, with what
  arguments, and what it returned (`ok` / `error` / `blocked` / `sanitized`).
- **`security_events`** — a narrower security narrative: an `injection_refused`,
  `tool_blocked`, `tool_output_sanitized`, or `outbound_leak_blocked` row,
  independent of ordinary tool telemetry. A `REFUSE` has no tool call at all
  (the LLM is never invoked), but it always produces a `security_events` row.

This means "what did the guardrails actually do across every case" is a
direct query (`GET /security-events`, or the `ticketwarden_security_events_total`
Prometheus counter) instead of something you'd have to reconstruct by
filtering the functional tool log for suspicious-looking statuses.

---

## 🎒 The Basecamp Supply Co. catalog

Rather than calling out to a public demo API and repurposing an unrelated
resource as a stand-in "order" (a fun trick, but a hack — the mapping has to
be documented and the derived status is synthetic), TicketWarden ships its
own small commerce backend in `store/`:

- `store/seed.py` — a hand-authored catalog (12 products across `outdoor`,
  `electronics`, `apparel`) and 10 orders, **each with a real `status` column**
  (`processing | shipped | in_transit | delivered | returned`), a carrier, and
  a tracking number — seeded idempotently into local SQLite tables at
  startup. Order 5 is seeded `returned`, so the refund category has an actual
  backing record instead of a status that's merely absent.
- `store/catalog.py` — `check_order_status`, `get_product_details`,
  `search_catalog`: plain SQL reads, no HTTP client, no timeout/outage
  handling to plan for.
- `store/registry.py` — the allowlist; unchanged in spirit from the security
  model above, just pointed at the local functions.

One side effect: the whole system, including every tool the Researcher can
call, runs with **zero network egress** other than the LLM provider itself —
useful for the fully offline `make test` run and for anyone who wants to
demo this without any external dependency but the model.

---

## 🗂️ Repository layout

```
ticketwarden/
├── apps/
│   ├── api/            🚪 FastAPI service — the deployable unit
│   │   └── src/
│   │       ├── graph/          🧠 state.py · nodes.py · edges.py · build.py · llm.py
│   │       ├── store/          🎒 registry.py (allowlist) · catalog.py · seed.py
│   │       ├── guardrails/     🛡️ injection.py (scored model) · pii.py
│   │       ├── storage/        🗄️ db.py · repo.py (tickets, tool_calls, security_events, catalog)
│   │       ├── observability/  📊 metrics.py · costing.py · usage.py · tracing.py
│   │       ├── schemas.py      📋 Pydantic request/response models
│   │       ├── service.py      🔁 orchestration: guardrails → graph → persist → metrics
│   │       └── main.py         🌐 FastAPI app factory + routes
│   └── ui/              🖥️ Streamlit support console
├── packages/shared/     📦 shared constants (decision enum, categories)
├── infra/               📈 Prometheus scrape config + provisioned Grafana dashboard
├── tests/               ✅ deterministic safety + contract suite — no API keys, no network
├── scripts/             🌱 seed_tickets.py · smoke_test.sh
└── docker-compose.yml   🐳 API + UI + Prometheus + Grafana
```

---

## 🚀 Project setup

### Prerequisites

| Requirement | Version | Needed for |
|---|---|---|
| Python | 3.11+ | API, UI, tests |
| Docker + Docker Compose | any recent | full-stack run (API + UI + Prometheus + Grafana) |
| An LLM API key | — | **optional** — live resolution only; the whole test suite and the `REFUSE` path work with no key |

### Step 1 — Install

```bash
python -m venv .venv && source .venv/bin/activate     # recommended
python -m pip install -r requirements-dev.txt          # API + dev/test deps
python -m pip install -r apps/ui/requirements.txt      # Streamlit UI deps
```

### Step 2 — Configure environment

```bash
cp .env.example .env
```

Open `.env` and (optionally) set an LLM provider key:

```dotenv
LLM_PROVIDER=openai          # or groq / gemini / nvidia / anthropic / ollama
OPENAI_API_KEY=sk-...        # the selected provider's key
```

Everything else has safe defaults — see [Configuration](#-configuration).

### Step 3 — Verify the install (no key needed)

```bash
make test     # full suite, all green with zero API keys and zero network
make lint     # ruff check .
```

### Step 4 — Run it

**Option A — local Python processes:**

```bash
make api    # FastAPI on http://localhost:8080   (/health, /docs, /metrics)
make ui     # Streamlit on http://localhost:8501  (in a second shell)
```

**Option B — full stack with Docker Compose:**

```bash
docker compose up --build
```

| Service | URL | What you'll see |
|---|---|---|
| 🚪 API | http://localhost:8080 | `/docs` (OpenAPI), `/health`, `/metrics` |
| 🖥️ Streamlit UI | http://localhost:8501 | The chat support console |
| 📈 Prometheus | http://localhost:9090 | Raw metrics + query explorer |
| 📊 Grafana (`admin`/`admin`) | http://localhost:3000 | Auto-provisioned **TicketWarden Overview** dashboard |

### Step 5 — Try it

```bash
curl -X POST localhost:8080/resolve -H 'content-type: application/json' \
  -d '{"ticket":"Where is my order 3?","order_id":"3"}'
```

Without a configured LLM key, `/health` reports `llm_configured: false`;
injection cases still `REFUSE` (the guardrail needs no model) and live cases
degrade gracefully to `ESCALATE` with a clear reason — the service never 500s.

---

## ⚙️ Configuration

All configuration flows through `apps/api/src/config.py` (pydantic-settings)
— no module reads `os.environ` directly. See `.env.example` for every
variable; the notable ones:

| Var | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` \| `groq` \| `gemini` \| `nvidia` \| `anthropic` \| `ollama` |
| `LLM_MODEL` | `gpt-4o-mini` | provider-specific chat model id |
| `OPENAI_API_KEY` … | — | per-provider credential (only the selected provider's key is required) |
| `LLM_BASE_URL` | — | optional endpoint override for OpenAI-compatible providers |
| `MAX_REVIEW_ITERATIONS` | `2` | review-loop bound (enforced in code, see above) |
| `MAX_TOOL_ROUNDS` | `3` | researcher tool-call cap per case |
| `SQLITE_PATH` | `./ticketwarden.db` | audit + catalog database path |
| `LANGCHAIN_TRACING_V2` | `false` | enable LangSmith tracing (also needs a real `LANGCHAIN_API_KEY`) |
| `LANGCHAIN_API_KEY` | — | LangSmith credential; the `lsv2_...` placeholder counts as unset |
| `LANGCHAIN_PROJECT` | `ticketwarden` | LangSmith project the traces land in |

---

## 🔀 Multi-provider LLM support

Switching providers is a two-line edit in `.env` — no code changes. Graph
nodes receive the model through `build_chat_model()` (`graph/llm.py`) and
never know which provider is active.

| `LLM_PROVIDER` | Example `LLM_MODEL` | Key var | Extra install |
|---|---|---|---|
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` | — |
| `groq` | `llama-3.3-70b-versatile` | `GROQ_API_KEY` | — |
| `nvidia` | `meta/llama-3.1-70b-instruct` | `NVIDIA_API_KEY` | — |
| `ollama` | `llama3.1:8b` | none (`OLLAMA_BASE_URL`) | [Ollama](https://ollama.com) + `ollama pull llama3.1:8b` |
| `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | `pip install -r apps/api/requirements-providers.txt` |
| `gemini` | `gemini-2.0-flash` | `GOOGLE_API_KEY` | `pip install -r apps/api/requirements-providers.txt` |

Groq, NVIDIA NIM, and Ollama ride the OpenAI-compatible lane
(`langchain-openai` with a `base_url` swap). Anthropic and Gemini use their
native LangChain integrations. Boot fails fast with a clear message if the
selected provider's key is missing.

---

## 🌐 API reference

| Endpoint | Behavior |
|---|---|
| `POST /resolve` | `{ticket, order_id?}` → `{decision, reply, category, tool_calls, escalation_reason, iterations, langsmith_trace_url, latency_ms, cost_usd}` |
| `GET /health` | liveness probe; also reports `llm_configured` |
| `GET /metrics` | Prometheus scrape endpoint |
| `GET /tickets?limit=N` | last N resolved cases from SQLite |
| `GET /security-events?limit=N` | last N guardrail events (refusals, blocked tools, sanitized output, withheld leaks) — independent of the tool-call log |

```bash
curl -X POST localhost:8080/resolve -H 'content-type: application/json' \
  -d '{"ticket":"Where is my order 3?","order_id":"3"}'
```

---

## ✅ Testing

```bash
make test         # pytest tests/ -v   — NO API key, NO network required
make lint         # ruff check .
```

| Test | Guarantees |
|---|---|
| `test_allowlist` | Off-registry tool call is blocked, logged, **never executed** |
| `test_max_iterations` | Loop ends at `ESCALATE` after exactly `MAX_REVIEW_ITERATIONS` |
| `test_injection` | HIGH-tier signals refuse alone; ambiguous LOW/MEDIUM signals only refuse once stacked; zero LLM invocations on refusal |
| `test_guardrail_hardening` | Obfuscation (zero-width/fullwidth) detected, poisoned tool output quarantined, leaky drafts escalated with reply withheld, oversized cases rejected |
| `test_pii` | Email/phone/SSN/card/IP redacted in the API response **and** in the DB |
| `test_security_events` | Each guardrail decision lands its own row, independent of the tool-call log |
| `test_catalog` | Local commerce backend (orders/products/search) — pure SQLite, no stubbing needed |
| `test_api` | `/resolve`, `/tickets`, `/security-events` schemas, `422` on empty ticket, `/health`, `/metrics` |
| `test_llm_provider` | Provider routing, missing-key errors, per-provider costing |

---

## 📊 Observability

- **Prometheus** — `ticketwarden_cases_total{decision}`,
  `ticketwarden_case_latency_seconds` (histogram), `ticketwarden_tokens_total`,
  `ticketwarden_cost_usd_total`, `ticketwarden_llm_calls_total`,
  `ticketwarden_security_events_total{event_type}`, tool-call counters.
- **Grafana** — provisioned **TicketWarden Overview** dashboard: throughput,
  P50/P99 latency, decision breakdown, cumulative spend, escalation rate,
  and security events over time.
- **LangSmith** (optional) — set `LANGCHAIN_TRACING_V2=true` and a real
  `LANGCHAIN_API_KEY` to trace every node/tool call; the root run's URL comes
  back as `langsmith_trace_url`.

### Token accounting

Cost is computed from the **provider's own reported token counts**,
accumulated across every LLM call the graph makes per case (classify,
research, and one draft/review pair per review iteration), via a
`UsageCollector` callback threaded through the graph config. When a provider
reports no usage, the service falls back to a tiktoken estimate over the
case text and reply — `ticketwarden_token_source_total{source="estimated"}`
tracks how often that fallback fires.

---

## 🌱 Seed & smoke test

```bash
make api                       # in one shell
python scripts/seed_tickets.py # 5 sample cases vs. expected decisions
bash scripts/smoke_test.sh     # curl /health + /resolve + /tickets + /security-events
```

The seed cases cover the full decision space: an order-status query →
`RESOLVED`, a refund against a `returned` order → `RESOLVED`, a
prompt-injection attempt → `REFUSE`, an out-of-scope rant → `ESCALATE`, and a
product question → `RESOLVED`.

---

## 🎓 Credits

**TicketWarden** is the capstone project of **Snehal Dmello**, built for the
**iHub DivyaSampark @ IIT Roorkee × Masai** program — Multi-Agent Systems
track (brief C·04). The brief called for a LangGraph crew
(Classifier → Researcher → Responder → Reviewer) that resolves real cases
end-to-end against an order-data backend, with bounded tools, injection and
PII guardrails, observability, and a test suite gated on agent-safety
guarantees.

Built with: [LangGraph](https://langchain-ai.github.io/langgraph/) ·
[FastAPI](https://fastapi.tiangolo.com/) · [Streamlit](https://streamlit.io/) ·
[Prometheus](https://prometheus.io/) · [Grafana](https://grafana.com/).
