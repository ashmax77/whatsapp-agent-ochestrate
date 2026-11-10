# Pizza Agent 🍕🤖

An intelligent, multi-agent WhatsApp assistant for Pizza Hut (operating across multiple branches: Colombo 07, Nugegoda, and Kandy). The assistant handles customer inquiries about menus, dietary details, branches, offers, and policies grounded in a curated knowledge base, alongside managing food orders in Sri Lankan Rupees (LKR).

---

## Implementation Status & Roadmap

| Phase | Milestone | Status |
|---|---|---|
| **Phase 1** | Baileys WhatsApp Gateway (Node.js) | ✅ Completed |
| **Phase 2** | FastAPI Brain Skeleton & Session State | ✅ Completed |
| **Phase 3** | Knowledge Base, Validator & Commercialized Hybrid RAG Pipeline | ✅ Completed |
| **Phase 4** | Deterministic Tools & Agents (Branch, Order, Delivery, Promo, SQLite) | ⏳ Next |
| **Phase 5** | Central Orchestrator Agent, State Machine & Redis Sessions | 🔜 Planned |
| **Phase 6** | Voice Notes (Audio Conversion & Faster-Whisper STT) | 🔜 Planned |
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
    │   ├── main.py                 # FastAPI entrypoint (/health, /message) with chat history wiring
    │   ├── config.py               # Pydantic settings (LLM, RAG, RBAC, chunking, thresholds)
    │   ├── schemas.py              # Request/response models (IncomingMessage, BrainReply)
    │   ├── llm/
    │   │   └── client.py           # Unified LLM completion & embedding facade (retries, timeouts)
    │   ├── services/
    │   │   └── menu_repo.py        # Structured menu item, combo & availability repository
    │   ├── state/
    │   │   └── session.py          # Per-customer session state & conversation history
    │   ├── agents/                 # Multi-agent orchestrator & specialists
    │   │   ├── base.py             # BaseAgent interface
    │   │   ├── knowledge_agent.py  # Commercial RAG agent (rewriting, deterministic routing, citations)
    │   │   ├── orchestrator.py     # Central intent router and coordinator
    │   │   ├── menu_agent.py       # Menu inquiries, pricing, customization
    │   │   ├── order_agent.py      # Cart operations & validation
    │   │   ├── delivery_agent.py   # Address resolution & delivery estimation
    │   │   ├── promo_agent.py      # Promo codes & discount validation
    │   │   ├── escalation_agent.py # Complaint detection & staff handoff
    │   │   └── post_order_agent.py # Order status tracking
    │   ├── tools/
    │   │   └── kb_tools.py         # Agent tools (kb_ask, kb_search, menu_get_item, menu_list_items)
    │   ├── rag/                    # Commercialized Hybrid RAG Pipeline
    │   │   ├── text.py             # Tokenizer, stopword removal, and word stemmer
    │   │   ├── kb_loader.py        # Safe loader, text cleaner, smart header chunker & summary tables
    │   │   ├── validate_kb.py      # Front-matter validator, PII checker & pre-flight chunk gate
    │   │   ├── embeddings.py       # API & deterministic local embedding service with backend tracking
    │   │   ├── ingest.py           # Zero-downtime blue/green index builder, manifest swap & pruning
    │   │   └── retriever.py        # Dynamic manifest hot-swap, RBAC, hybrid BM25 + vector & reranker
    │   ├── voice/                  # (Phase 6) STT and TTS handlers (stt.py, tts.py)
    │   └── db/                     # Database persistence (SQLite / PostgreSQL)
    ├── data/
    │   ├── branches.json           # Outlet coordinates, hours, cutoffs, delivery zones & area aliases
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
    ├── tests/
    │   ├── helpers.py              # Hermetic TempIndex & OfflineLLM test fixtures
    │   ├── test_api.py             # API schema, session state & /message route tests
    │   ├── test_kb_loader.py       # Slug rules, text cleaning, safe loading & summary chunk tests
    │   ├── test_ingest.py          # Blue/green builds, atomic manifest, pruning & rollback tests
    │   ├── test_menu_repo.py       # Structured menu item, combo & availability tests
    │   ├── test_rag_retrieval.py   # Hybrid search, leak probes, RBAC, manifest hot-swap & BM25 tests
    │   └── test_rag_exam.py        # Automated Golden Set Exam (accuracy, memory, routing, leak guards)
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
    "push_name": "Ashen"
  }
  ```
- **Response (`BrainReply`)**:
  ```json
  {
    "reply_text": "We have 3 vegetarian pizzas: Margherita, Veggie Delight and Cheese Lover. 🍕",
    "reply_audio_url": null
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

### 3. Running Automated Tests & Golden Set Evaluation

Run the full 42-test suite (unit tests, blue/green ingestion tests, RBAC leak probes, and the Golden Set RAG Exam) inside `brain/`:

```powershell
cd brain

# Run all unit tests and hermetic Golden Set exam
.\.venv\Scripts\python.exe -m unittest discover tests

# Run only the Golden Set RAG Exam (set RAG_EXAM_LIVE=1 to test against the live LLM)
.\.venv\Scripts\python.exe -m unittest tests/test_rag_exam.py
```
