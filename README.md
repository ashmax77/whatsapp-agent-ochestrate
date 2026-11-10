# Pizza Agent 🍕🤖

An intelligent, multi-agent WhatsApp assistant for Pizza Hut (operating across multiple branches: Colombo 07, Nugegoda, and Kandy). The assistant handles customer inquiries about menus, dietary details, branches, offers, and policies grounded in a curated knowledge base, alongside managing food orders in Sri Lankan Rupees (LKR).

---

## Implementation Status & Roadmap

| Phase | Milestone | Status |
|---|---|---|
| **Phase 1** | Baileys WhatsApp Gateway (Node.js) | ✅ Completed |
| **Phase 2** | FastAPI Brain Skeleton & Session State | ✅ Completed |
| **Phase 3** | Knowledge Base, Validator & Commercialized Hybrid RAG Pipeline | ✅ Completed |
| **Phase 4** | Deterministic Tools & Agents (Branch, Order, Delivery, Promo, SQLite) | ✅ Completed |
| **Phase 5** | Central Orchestrator Agent, State Machine & Redis Sessions | ✅ Completed |
| **Phase 6** | Voice Notes (Audio Conversion & Faster-Whisper STT) | ⏳ Next |
| **Phase 7** | Escalation Agent, Post-Order Tracking & Staff Notifications | 🔜 Planned |
| **Phase 8** | Multi-Layer Evaluation Pipeline (L0–L5) | 🔜 Planned |
| **Phase 9** | Production Hardening & Cloud Deployment | 🔜 Planned |

---

## Architecture Overview

The system is decoupled into two primary services:

- **`gateway/` (Node.js + Baileys)**: Strictly handles WhatsApp I/O (WebSocket protocol, QR code pairing, connection management, voice call auto-rejection, message normalization, and media downloads). Contains zero business or AI logic.
- **`brain/` (Python + FastAPI)**: Microservice containing all AI logic, multi-agent orchestration, hybrid RAG retrieval over curated markdown knowledge, deterministic menu/pricing queries, session state management, order calculation, and audio transcription.

```
pizza-agent/
├── .gitignore
├── docker-compose.yml              # Multi-container orchestration (gateway, brain, redis, qdrant)
├── docker-compose.dev.yml          # Local development stack (Redis 7 on port 6379)
├── plan.md                         # Comprehensive phase-by-phase implementation plan
├── README.md                       # Project documentation
├── architecture.jpg                # Architecture diagram
│
├── gateway/                        # Node.js: Baileys WhatsApp I/O service
│   ├── auth_state/                 # Baileys session credentials (git-ignored)
│   ├── src/
│   │   ├── index.js                # Baileys socket, QR login, event handlers
│   │   ├── config.js               # Gateway environment configuration
│   │   ├── brainClient.js          # Resilient HTTP client communicating with Brain (/message)
│   │   └── media.js                # (Phase 6) Voice note download/send helpers
│   ├── package.json
│   ├── package-lock.json
│   └── .env
│
└── brain/                          # Python: FastAPI AI backend & multi-agent system
    ├── app/
    │   ├── main.py                 # Async FastAPI entrypoint (/health, /message) routed through orchestrator
    │   ├── config.py               # Pydantic settings (LLM, Redis, TTLs, rate limits, RAG, thresholds)
    │   ├── schemas.py              # Request/response models (IncomingMessage, BrainReply, BrainReplyMeta)
    │   ├── llm/
    │   │   └── client.py           # Unified LLM completion & embedding facade (retries, timeouts)
    │   ├── services/
    │   │   ├── clock.py            # Injectable Asia/Colombo clock for opening-hours & date tests
    │   │   ├── menu_repo.py        # Structured menu item, option, crust, topping & combo repo
    │   │   ├── branch_repo.py      # Haversine pin & fuzzy alias branch/zone resolver + hours check
    │   │   ├── promo_repo.py       # Deterministic promo validator (days, dates, branches, min spend)
    │   │   ├── pricing.py          # Pure integer-LKR pricing engine & WhatsApp receipt formatter
    │   │   ├── language.py         # Script-based language detector (Sinhala, Tamil, English/Singlish)
    │   │   └── post_processor.py   # Reply price verification & hallucination defense
    │   ├── state/
    │   │   ├── session.py          # Per-customer Session, CartLine, summary_hash & singleton store factory
    │   │   ├── session_store.py    # Abstract async SessionStore base class
    │   │   ├── memory_store.py     # In-memory thread/asyncio-safe store with lock, dedupe & rate-limiting
    │   │   └── redis_store.py      # Redis session store with JSON serialization, TTL & memory fallback
    │   ├── agents/                 # Multi-agent orchestrator & specialists
    │   │   ├── base.py             # BaseAgent interface
    │   │   ├── prompts/
    │   │   │   └── orchestrator_v1.md # Versioned orchestrator prompt (pricing integrity, confirmation rules)
    │   │   ├── orchestrator.py     # Central orchestrator (session locking, dedupe, stage-aware tool loop)
    │   │   ├── knowledge_agent.py  # Commercial RAG agent (rewriting, deterministic routing, citations)
    │   │   ├── menu_agent.py       # Menu inquiries, pricing, customization
    │   │   ├── order_agent.py      # Deterministic agent owning cart, fulfilment, summary & place_order
    │   │   ├── delivery_agent.py   # Deterministic agent owning branch.list, set_address & quote
    │   │   ├── promo_agent.py      # Deterministic agent owning promo.apply & promo.remove
    │   │   ├── escalation_agent.py # Complaint detection & staff handoff
    │   │   └── post_order_agent.py # Order status tracking
    │   ├── tools/
    │   │   ├── registry.py         # Tool registry with Pydantic schemas & state-machine stage guards
    │   │   ├── kb_tools.py         # Knowledge & menu tools (kb.ask, kb.search, menu.get_item, etc.)
    │   │   ├── branch_tools.py     # Branch listing tool (branch.list)
    │   │   ├── cart_tools.py       # Cart CRUD & combo validation (cart.add_item, add_combo, etc.)
    │   │   ├── delivery_tools.py   # Address/pin resolution & delivery quote (delivery.set_address, quote)
    │   │   ├── promo_tools.py      # Promo code application & removal (promo.apply, promo.remove)
    │   │   ├── order_tools.py      # Fulfilment, pickup, summary & two-step place_order tools
    │   │   └── cli.py              # Zero-LLM CLI tool harness (python -m app.tools.cli --demo)
    │   ├── rag/                    # Commercialized Hybrid RAG Pipeline
    │   │   ├── text.py             # Tokenizer, stopword removal, and word stemmer
    │   │   ├── kb_loader.py        # Safe loader, text cleaner, smart header chunker & summary tables
    │   │   ├── validate_kb.py      # Front-matter, PII, pre-flight & menu/offer/branch consistency validator
    │   │   ├── embeddings.py       # API & deterministic local embedding service with backend tracking
    │   │   ├── ingest.py           # Zero-downtime blue/green index builder, manifest swap & pruning
    │   │   └── retriever.py        # Dynamic manifest hot-swap, RBAC, hybrid BM25 + vector & reranker
    │   ├── voice/                  # (Phase 6) STT and TTS handlers (stt.py, tts.py)
    │   └── db/                     # SQLite / PostgreSQL persistence
    │       ├── models.py           # Customer, Order, OrderItem, Handoff, MessageLog models
    │       └── order_repo.py       # SQLite repository with PH-YYYYMMDD-NNNN order numbering
    ├── data/
    │   ├── branches.json           # Outlet coordinates, hours, cutoffs, delivery zones & area aliases
    │   ├── promos.json             # Structured promo rules (FRIDAY10, STUDENT15, expired offers)
    │   ├── menu.json               # Structured source of truth for LKR prices, sizes & combos (git-ignored)
    │   ├── chroma/                 # Versioned blue/green vector builds & index_info.json (git-ignored)
    │   └── knowledge/              # Curated multi-folder knowledge base (29 Markdown files)
    │       ├── README.md           # Knowledge base authoring rules
    │       ├── branches/           # Branch directory, Colombo 07, Nugegoda, Kandy
    │       ├── company/            # About Us, service standards
    │       ├── faq/                # General customer FAQs
    │       ├── internal/           # Staff-only documents (NEVER indexed for customers)
    │       │   ├── README.md
    │       │   ├── employees/      # Roles, shift schedules, staff directory
    │       │   └── hr/             # Escalation rules, code of conduct, leave policies
    │       ├── menu/               # Pizzas, sides, desserts, beverages, customization, allergens
    │       ├── offers/             # Current offers, expired offers, loyalty program
    │       └── policies/           # Ordering & delivery, payment & refunds, cancellation, food safety
    ├── eval/
    │   └── datasets/
    │       └── tools.yaml          # Deterministic tool-trajectory & state-machine evaluation cases
    ├── tests/
    │   ├── helpers.py              # Hermetic TempIndex & OfflineLLM test fixtures
    │   ├── test_api.py             # API schema, session state & /message route tests
    │   ├── test_kb_loader.py       # Slug rules, text cleaning, safe loading & summary chunk tests
    │   ├── test_ingest.py          # Blue/green builds, atomic manifest, pruning & rollback tests
    │   ├── test_menu_repo.py       # Structured menu item, combo & availability tests
    │   ├── test_rag_retrieval.py   # Hybrid search, leak probes, RBAC, manifest hot-swap & BM25 tests
    │   ├── test_rag_exam.py        # Automated Golden Set Exam (accuracy, memory, routing, leak guards)
    │   ├── test_phase4_orders.py   # Pricing, branch/zone, hours, promos, state-machine & DB order tests
    │   └── test_phase5_orchestrator.py # Session dedupe, rate limits, stage filtering & prompt safety tests
    ├── start.bat                   # Windows CMD startup script
    ├── start.ps1                   # Windows PowerShell startup script
    ├── requirements.txt
    ├── pyproject.toml
    ├── uv.lock
    ├── .python-version
    └── .env
```

---

## Commercialized RAG & Knowledge Base Architecture

### 1. Ingestion Pipeline (`brain/app/rag/`)
- **Fault-Tolerant Document Loading (`kb_loader.py`)**: Scans `*.md` files recursively while catching `UnicodeDecodeError` and OS read errors so a single corrupted file is logged and skipped without crashing the build.
- **Text Sanitization (`clean_text`)**: Strips signature underscore blocks (`_{5,}`), standalone horizontal dividers (`---`), and redundant blank lines (`\n{3,}`) before chunking.
- **Context-Preserving Hierarchical Chunking**: Splits documents along `#`, `##`, and `###` Markdown headings, sub-splits oversized sections (>1,000 characters with 100-character overlap), drops title-only micro-sections (<40 characters), and prepends an explicit context header (`Document: {folder} - {doc_title}\nSection: {heading}`) to every chunk.
- **Cross-Document Summary Tables**: Automatically synthesizes global overview chunks (`menu/_summary#all-items`, `branches/_summary#all-outlets`, `offers/_summary#current-offers`) and exports `menu_summary.csv` so holistic questions are answerable in a single lookup.
- **Pre-Flight Validation Gate (`validate_kb.py`)**: Checks YAML front-matter, PII patterns, section word counts, character ceilings, mandatory metadata keys, and verifies zero `internal/` chunks before spending embedding calls.
- **Zero-Downtime Blue/Green Builds (`ingest.py`)**: Writes every new index into a timestamped folder (`data/chroma/build_YYYYMMDD_HHMMSS/`), verifies saved chunk counts, atomically swaps `index_info.json` via a `.tmp` rename, and prunes older builds while keeping `BUILDS_TO_KEEP = 2` (live + backup).

### 2. Retrieval & Knowledge Agent Pipeline (`retriever.py` & `knowledge_agent.py`)
- **Dynamic Manifest Hot-Swap**: Checks `index_info.json` before each query and atomically reloads new builds in memory without restarting the FastAPI server. Pins the query embedding backend to match the build's vector space.
- **Defense-in-Depth RBAC Isolation**: Enforces role-based folder whitelists (`ROLE_ACCESS`) at search time in addition to excluding `internal/` during ingestion. Customer queries can only search `["menu", "branches", "offers", "policies", "company", "faq"]`.
- **Hybrid Search (Dense Vectors + Okapi BM25)**: Combines semantic cosine similarity with a built-in, zero-dependency `BM25Okapi` lexical index (with stopword removal and stemming) to capture both meaning and exact alphanumeric codes (`STUDENT15`, `FRIDAY10`).
- **Reranking & Relevance Gate**: Scores candidate pools using semantic-keyword fusion (or an optional `sentence-transformers` Cross-Encoder) and drops hits below `MIN_RELEVANCE_SCORE`. Off-topic questions return zero hits and immediately trigger a polite staff handoff without calling the LLM.
- **Conversational Query Rewriting**: Resolves pronouns and follow-up references (*"Is it spicy?"*, *"What about Kandy?"*) into standalone search queries using recent session history.
- **Deterministic Menu Routing**: Intercepts counting, listing, and price-threshold questions (*"How many vegetarian pizzas do you have?"*, *"Which pizzas are under LKR 2,000?"*) and computes exact answers in Python from `menu.json`—ensuring the LLM never guesses counts or prices.
- **Strict Grounding & Verified Citations**: Formats retrieved chunks as numbered sources `[1]`, `[2]`, enforces availability notes from `menu_repo`, maps cited markers back to source chunk IDs for audit logs, and strips bracket markers from the customer's WhatsApp reply.

---

## Deterministic Order Engine, State Machine & Tools (Phase 4)

All order, cart, branch, delivery, and promo calculations run in 100% deterministic Python code—never inside an LLM:

- **Pure Integer-LKR Pricing (`app/services/pricing.py`)**: Computes unit prices, crust/topping surcharges, food subtotals, zone delivery fees, and `ROUND_HALF_UP` promo discounts in integer LKR. Promo discounts apply strictly to the food subtotal and never reduce the delivery fee.
- **Multi-Branch & Zone Resolution (`app/services/branch_repo.py`)**:
  - **Location Pins**: Uses Haversine distance to select the nearest outlet within its `max_km` radius (Colombo 07: 8 km, Nugegoda: 8 km, Kandy: 6 km) and assigns Zone 1 (0–3 km, free delivery) or Zone 2 (LKR 250 fee).
  - **Address Text**: Matches against each branch's `area_aliases` (exact + fuzzy matching $\ge 85$), returning `NEEDS_CLARIFICATION` on ambiguous text or `OUT_OF_AREA` for out-of-coverage towns.
  - **Opening Hours & Cutoffs**: Validates `Asia/Colombo` time against `last_delivery_order` (22:30 Colombo/Nugegoda, 22:00 Kandy) and `last_dine_in_order` (22:15 Colombo/Nugegoda, 21:45 Kandy).
- **Deterministic Promo Validation (`app/services/promo_repo.py`)**: Enforces day-of-week (`FRIDAY10` on Fridays, `STUDENT15` on Tuesdays), expiration dates (`MONSOON` and `AVURUDU` flagged as expired), minimum food subtotals, branch restrictions (`STUDENT15` valid at Nugegoda and Kandy only), and student ID reminders.
- **Two-Step Confirmation State Machine (`app/tools/registry.py` & `order_tools.py`)**:
  - Enforces stage transitions (`browsing` $\to$ `building_cart` $\to$ `collecting_fulfilment` $\to$ `confirming` $\to$ `placed`).
  - Rejects zone-restricted items outside their allowed zone (e.g. `ds_ice_cream_cup` in Zone 2) and enforces the LKR 1,500 minimum delivery subtotal.
  - `order.show_summary` computes a cryptographic `summary_hash` and records `summary_msg_no`. Any subsequent edit to cart, branch, address, or promo immediately invalidates `summary_hash`.
  - `order.place_order` requires a matching `cart_hash` on a **later** message turn (`message_count > summary_msg_no`) and persists the order to SQLite (`app/db/order_repo.py`) with a human-friendly order number (`PH-YYYYMMDD-NNNN`).

---

## Central Orchestrator Agent, State Machine & Redis Sessions (Phase 5)

Phase 5 introduces the central conversational orchestrator that glues together natural language understanding, stage-aware tool calling, resilient multi-session storage, and hallucination post-processing:

- **Asynchronous SessionStore Abstraction (`app/state/session_store.py`)**:
  - `MemorySessionStore`: Thread and asyncio-safe in-memory store featuring per-user `asyncio.Lock()`, message deduplication cache, and sliding-window rate limiting.
  - `RedisSessionStore`: Distributed session store with JSON serialization, configurable TTL (`SESSION_TTL_SECONDS = 86400`), and automated graceful fallback to in-memory mode if Redis is offline or unconfigured.
  - Local Redis dev environment pre-configured in `docker-compose.dev.yml` (`docker compose -f docker-compose.dev.yml up -d`).
- **Stage-Aware Tool Filtering (`app/tools/registry.py`)**:
  - Dynamically filters tool schemas exposed to the orchestrator model based on current `session.stage`.
  - While `browsing`, cart mutations and order placement tools are concealed.
  - While `building_cart` or `collecting_fulfilment`, cart updates and address resolution tools are active, but `order.place_order` remains strictly concealed.
  - Only when the session enters `confirming` is `order.place_order` exposed to the model, preventing premature order placement.
- **Prompt Versioning & System Rules (`app/agents/prompts/orchestrator_v1.md`)**:
  - Versioned prompt template (`orchestrator_v1`) enforcing single-turn tool calling, concise WhatsApp formatting, strict pricing integrity (never calculate money in text), and refusing customer access to internal employee information.
  - Incorporates dynamic session state block (cart items, branch hours, delivery zone, current stage, summary hash).
- **Post-Processor Reply Verification (`app/services/post_processor.py`)**:
  - Automatically verifies all price figures mentioned in the assistant's reply against deterministic tool outputs and cart totals.
  - If a discrepancy or hallucinated price is detected, the post-processor corrects the text to the verified integer LKR amount or replaces it with the authentic receipt.
- **Language Detection (`app/services/language.py`)**:
  - Native script detection for Sinhala (`\u0D80-\u0DFF`) and Tamil (`\u0B80-\u0BFF`), defaulting to English / Singlish with matched language output.

---

## Inter-Service Contract

The Gateway communicates with the Brain via HTTP JSON:

- **Endpoint**: `POST http://127.0.0.1:8000/message`
- **Request (`IncomingMessage`)**:
  ```json
  {
    "user_id": "9470000000",
    "type": "text",
    "content": "How many vegetarian pizzas do you have?",
    "message_id": "ABC123XYZ",
    "push_name": "Ashen",
    "timestamp": "2026-11-10T12:00:00Z"
  }
  ```
- **Response (`BrainReply`)**:
  ```json
  {
    "reply_text": "We have 3 vegetarian pizzas: Margherita, Veggie Delight and Cheese Lover. 🍕",
    "reply_audio_b64": null,
    "reply_audio_mime": null,
    "meta": {
      "stage": "browsing",
      "branch_id": "colombo07",
      "trace_id": "a1b2c3d4",
      "latency_ms": 124.5,
      "usage": {
        "prompt_tokens": 420,
        "completion_tokens": 45,
        "total_tokens": 465
      }
    }
  }
  ```

---

## Getting Started

### 1. Python Brain Setup

Navigate to the `brain` folder:

```powershell
cd brain
```

**Validate Knowledge Base & Build the Vector Index:**
```powershell
# 1. Validate KB front-matter, PII rules, and pre-flight chunk gates
.\.venv\Scripts\python.exe -m app.rag.validate_kb

# 2. Build a zero-downtime blue/green customer index (add --local for offline builds)
.\.venv\Scripts\python.exe -m app.rag.ingest
```

**Start the Brain Server:**

- **Option A: Using the Quick Start Scripts (Recommended for Windows)**
  ```powershell
  # In PowerShell:
  .\start.ps1

  # In Command Prompt (CMD):
  start.bat
  ```

- **Option B: Manual Activation & Startup**
  ```powershell
  .\.venv\Scripts\Activate.ps1
  uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
  ```

Verify the server is running:
- Health Check: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`
- Interactive Docs: Open `http://127.0.0.1:8000/docs` in your browser.

---

### 2. Node.js Gateway Setup

In a separate terminal window:

```powershell
cd gateway

# Install dependencies (if not already installed)
npm install

# Start the Baileys gateway
npm start
```

Scan the terminal QR code using WhatsApp (**Linked Devices > Link a Device**) to establish connection.

---

### 3. Running Automated Tests, CLI Tool Harness & Golden Set Evaluation

Run the full 60-test suite (unit tests, Phase 4 order/pricing/branch/promo tests, Phase 5 orchestrator/session tests, blue/green ingestion tests, RBAC leak probes, and the Golden Set RAG Exam) inside `brain/`:

```powershell
cd brain

# Run the zero-LLM deterministic order flow CLI demo
.\.venv\Scripts\python.exe -m app.tools.cli --demo

# Run all 60 unit & integration tests
.\.venv\Scripts\python.exe -m unittest discover tests

# Run Phase 5 orchestrator, session deduplication & state-machine filtering tests
.\.venv\Scripts\python.exe -m unittest tests/test_phase5_orchestrator.py

# Run Phase 4 deterministic order & pricing engine tests
.\.venv\Scripts\python.exe -m unittest tests/test_phase4_orders.py

# Run only the Golden Set RAG Exam (set RAG_EXAM_LIVE=1 to test against the live LLM)
.\.venv\Scripts\python.exe -m unittest tests/test_rag_exam.py
```
