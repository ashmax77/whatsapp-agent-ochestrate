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
| **Phase 6** | Voice Notes (Audio Conversion, Faster-Whisper STT, Confirmation Rule & TTS) | ✅ Completed |
| **Phase 7** | Escalation Agent, Post-Order Tracking & Staff Notifications | ✅ Completed |
| **Phase 8** | Multi-Layer Evaluation Pipeline (L1–L7, 32 Scenarios, Baseline CI) | ✅ Completed |
| **Phase 9** | Production Hardening, Observability & Cloud Deployment | ⏳ Next |

---

## Architecture Overview

The system is built on an asynchronous microservices architecture (Node.js Gateway + FastAPI with Uvicorn), specifically designed to handle concurrent WhatsApp conversations in parallel:

The system is decoupled into two primary services:

- **`gateway/` (Node.js + Baileys)**: Strictly handles WhatsApp I/O (WebSocket protocol, QR code pairing, connection management, voice call auto-rejection, message normalization, and media downloads). Contains zero business or AI logic.
- **`brain/` (Python + FastAPI)**: Microservice containing all AI logic, multi-agent orchestration, hybrid RAG retrieval over curated markdown knowledge, deterministic menu/pricing queries, session state management, order calculation, and audio transcription.

```
pizza-agent/
├── .github/
│   └── workflows/
│       └── eval.yml                    # Automated offline eval & KB validation CI workflow
├── Makefile                            # Unified targets (make test, make eval, make validate-kb)
├── .gitignore
├── docker-compose.yml                  # Multi-container orchestration (gateway, brain, redis, qdrant)
├── docker-compose.dev.yml              # Local development stack (Redis 7 on port 6379)
├── plan.md                             # Comprehensive phase-by-phase implementation plan
├── README.md                           # Project documentation
├── architecture.jpg                    # Architecture diagram
│
├── gateway/                            # Node.js: Baileys WhatsApp I/O service
│   ├── auth_state/                     # Baileys session credentials (git-ignored)
│   ├── src/
│   │   ├── index.js                    # Baileys socket, QR login, event handlers
│   │   ├── config.js                   # Gateway environment configuration
│   │   ├── brainClient.js              # Resilient HTTP client communicating with Brain (/message)
│   │   └── media.js                    # (Phase 6) Voice note download/send helpers
│   ├── package.json
│   ├── package-lock.json
│   └── .env
│
└── brain/                              # Python: FastAPI AI backend & multi-agent system
    ├── app/
    │   ├── main.py                     # Async FastAPI entrypoint (/health, /message) routed through orchestrator
    │   ├── config.py                   # Pydantic settings (LLM, Redis, TTLs, rate limits, RAG, thresholds)
    │   ├── schemas.py                  # Request/response models (IncomingMessage, BrainReply, BrainReplyMeta)
    │   ├── llm/
    │   │   └── client.py               # Unified LLM completion & embedding facade (retries, timeouts)
    │   ├── services/
    │   │   ├── clock.py                # Injectable Asia/Colombo clock for opening-hours & date tests
    │   │   ├── menu_repo.py            # Structured menu item, option, crust, topping & combo repo
    │   │   ├── branch_repo.py          # Haversine pin & fuzzy alias branch/zone resolver + hours check
    │   │   ├── promo_repo.py           # Deterministic promo validator (days, dates, branches, min spend)
    │   │   ├── pricing.py              # Pure integer-LKR pricing engine & WhatsApp receipt formatter
    │   │   ├── language.py             # Script-based language detector (Sinhala, Tamil, English/Singlish)
    │   │   ├── action_guard.py         # Deterministic action-claim & order-number verification guard
    │   │   ├── post_processor.py       # Reply price verification & hallucination defense
    │   │   └── notifier.py             # (Phase 7) Per-branch & Area Manager WhatsApp notification service
    │   ├── state/
    │   │   ├── session.py              # Per-customer Session, CartLine, summary_hash & singleton store factory
    │   │   ├── session_store.py        # Abstract async SessionStore base class
    │   │   ├── memory_store.py         # In-memory thread/asyncio-safe store with lock, dedupe & rate-limiting
    │   │   └── redis_store.py          # Redis session store with JSON serialization, TTL & memory fallback
    │   ├── agents/                     # Multi-agent orchestrator & specialists
    │   │   ├── base.py                 # BaseAgent interface
    │   │   ├── prompts/
    │   │   │   └── orchestrator_v1.md  # Versioned orchestrator prompt (pricing integrity, confirmation rules)
    │   │   ├── orchestrator.py         # Central orchestrator (session locking, dedupe, stage-aware tool loop)
    │   │   ├── knowledge_agent.py      # Commercial RAG agent (rewriting, deterministic routing, citations)
    │   │   ├── menu_agent.py           # Menu inquiries, pricing, customization
    │   │   ├── order_agent.py          # Deterministic agent owning cart, fulfilment, summary & place_order
    │   │   ├── delivery_agent.py       # Deterministic agent owning branch.list, set_address & quote
    │   │   ├── promo_agent.py          # Deterministic agent owning promo.apply & promo.remove
    │   │   ├── escalation_agent.py     # Complaint detection & staff handoff
    │   │   └── post_order_agent.py     # Order status tracking
    │   ├── tools/
    │   │   ├── registry.py             # Tool registry with Pydantic schemas & state-machine stage guards
    │   │   ├── kb_tools.py             # Knowledge & menu tools (kb.ask, kb.search, menu.get_item, etc.)
    │   │   ├── branch_tools.py         # Branch listing tool (branch.list)
    │   │   ├── cart_tools.py           # Cart CRUD & combo validation (cart.add_item, add_combo, etc.)
    │   │   ├── delivery_tools.py       # Address/pin resolution & delivery quote (delivery.set_address, quote)
    │   │   ├── promo_tools.py          # Promo code application & removal (promo.apply, promo.remove)
    │   │   ├── order_tools.py          # Fulfilment, pickup, summary & two-step place_order tools
    │   │   └── cli.py                  # Zero-LLM CLI tool harness (python -m app.tools.cli --demo)
    │   ├── rag/                        # Commercialized Hybrid RAG Pipeline
    │   │   ├── text.py                 # Tokenizer, stopword removal, and word stemmer
    │   │   ├── kb_loader.py            # Safe loader, text cleaner, smart header chunker & summary tables
    │   │   ├── validate_kb.py          # Front-matter, PII, pre-flight & menu/offer/branch consistency validator
    │   │   ├── embeddings.py           # API & deterministic local embedding service with backend tracking
    │   │   ├── ingest.py               # Zero-downtime blue/green index builder, manifest swap & pruning
    │   │   └── retriever.py            # Dynamic manifest hot-swap, RBAC, hybrid BM25 + vector & reranker
    │   ├── voice/                      # (Phase 6) Audio conversion, STT & TTS (audio.py, stt.py, tts.py)
    │   └── db/                         # SQLite / PostgreSQL persistence
    │       ├── models.py               # Customer, Order, OrderItem, Handoff, MessageLog models
    │       └── order_repo.py           # SQLite repository with PH-YYYYMMDD-NNNN order numbering
    ├── data/
    │   ├── branches.json               # Outlet coordinates, hours, cutoffs, delivery zones & area aliases
    │   ├── promos.json                 # Structured promo rules (FRIDAY10, STUDENT15, expired offers)
    │   ├── menu.json                   # Structured source of truth for LKR prices, sizes & combos (git-ignored)
    │   ├── chroma/                     # Versioned blue/green vector builds & index_info.json (git-ignored)
    │   └── knowledge/                  # Curated multi-folder knowledge base (29 Markdown files)
    │       ├── README.md               # Knowledge base authoring rules
    │       ├── branches/               # Branch directory, Colombo 07, Nugegoda, Kandy
    │       ├── company/                # About Us, service standards
    │       ├── faq/                    # General customer FAQs
    │       ├── internal/               # Staff-only documents (NEVER indexed for customers)
    │       │   ├── README.md
    │       │   ├── employees/          # Roles, shift schedules, staff directory
    │       │   └── hr/                 # Escalation rules, code of conduct, leave policies
    │       ├── menu/                   # Pizzas, sides, desserts, beverages, customization, allergens
    │       ├── offers/                 # Current offers, expired offers, loyalty program
    │       └── policies/               # Ordering & delivery, payment & refunds, cancellation, food safety
    ├── eval/                           # (Phase 8) Comprehensive 7-Layer Evaluation Framework
    │   ├── isolation.py                # L7 Sandbox isolation (temp SQLite, in-memory sessions, mock notifier, frozen clock)
    │   ├── run.py                      # Unified CLI runner (--suite, --offline, --repeats, regression baseline checks)
    │   ├── simulator.py                # L3 E2E conversation simulator with invariant verification
    │   ├── datasets/
    │   │   ├── retrieval.yaml          # 61-case RAG retrieval dataset (EN/SI/TA/Singlish + 10 out-of-scope + 10 leak probes)
    │   │   ├── tools.yaml              # 15 tool-trajectory & state-machine evaluation cases
    │   │   ├── judge_calibration.yaml  # 30-case human-labeled calibration dataset for LLM-as-Judge
    │   │   ├── safety.yaml             # 42-case safety, prompt-injection, order-abuse & escalation suite
    │   │   ├── voice.yaml              # 32-case multilingual voice evaluation dataset (EN, SI, TA, mixed)
    │   │   └── conversations/          # 32 end-to-end multi-turn customer conversation scenario YAMLs (c001–c032)
    │   ├── runners/
    │   │   ├── retrieval_eval.py       # L1 retrieval evaluator (Recall@4, Hit@1, MRR, OOS refusal, internal leak check)
    │   │   ├── tools_eval.py           # L2 tool selection, argument accuracy & state-match evaluator
    │   │   ├── judge.py                # L4 LLM-as-Judge, deterministic price integrity override & pairwise A/B comparator
    │   │   ├── safety_eval.py          # L5 safety violation, escalation recall (1.00) & false-positive rate (<=0.02) evaluator
    │   │   └── voice_eval.py           # L6 voice WER, multilingual slot accuracy & confirmation rule evaluator
    │   └── reports/
    │       └── baseline.json           # Tracked evaluation baseline for regression prevention in CI
    ├── tests/
    │   ├── helpers.py                  # Hermetic TempIndex & OfflineLLM test fixtures
    │   ├── test_api.py                 # API schema, session state & /message route tests
    │   ├── test_kb_loader.py           # Slug rules, text cleaning, safe loading & summary chunk tests
    │   ├── test_ingest.py              # Blue/green builds, atomic manifest, pruning & rollback tests
    │   ├── test_menu_repo.py           # Structured menu item, combo & availability tests
    │   ├── test_rag_retrieval.py       # Hybrid search, leak probes, RBAC, manifest hot-swap & BM25 tests
    │   ├── test_rag_exam.py            # Automated Golden Set Exam (accuracy, memory, routing, leak guards)
    │   ├── test_phase4_orders.py       # Pricing, branch/zone, hours, promos, state-machine & DB order tests
    │   ├── test_phase5_orchestrator.py # Session dedupe, rate limits, stage filtering & prompt safety tests
    │   ├── test_orchestrator_action_guard.py # Action-claim verification, fake order-no blocker & forced tool call tests
    │   ├── test_phase6_voice.py        # Audio limits, immediate deletion, STT, confirmation rule & TTS tests
    │   ├── test_phase7_escalation_and_staff.py # Escalation rules sync, handoff silence, notifier & branch staff commands
    │   └── test_phase8_eval.py         # L1–L7 evaluation pipeline, sandbox isolation & baseline regression tests
    ├── start.bat                       # Windows CMD startup script
    ├── start.ps1                       # Windows PowerShell startup script
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
  - While `browsing`, customers can query the menu, knowledge base, check branch opening status, check delivery coverage / address resolution (`delivery.set_address`), and validate active promotions (`promo.apply`). Cart mutations and final checkout remain guarded.
  - While `building_cart` or `collecting_fulfilment`, full cart updates, fulfilment selections, and receipt generation (`order.show_summary`) are active, but `order.place_order` remains strictly concealed.
  - Only when the session enters `confirming` is `order.place_order` exposed to the model, preventing premature order placement.
- **Prompt Versioning & System Rules (`app/agents/prompts/orchestrator_v1.md`)**:
  - Versioned prompt template (`orchestrator_v1`) enforcing single-turn tool calling, concise WhatsApp formatting, strict pricing integrity (never calculate money in text), and refusing customer access to internal employee information.
  - Incorporates dynamic session state block (cart items, branch hours, delivery zone, current stage, summary hash).
- **Post-Processor Reply Verification (`app/services/post_processor.py`)**:
  - Automatically verifies all price figures mentioned in the assistant's reply against deterministic tool outputs and cart totals.
  - If a discrepancy or hallucinated price is detected, the post-processor corrects the text to the verified integer LKR amount or replaces it with the authentic receipt.
- **Language Detection (`app/services/language.py`)**:
  - Native script detection for Sinhala (`\u0D80-\u0DFF`) and Tamil (`\u0B80-\u0BFF`), defaulting to English / Singlish with matched language output.
- **Action-Claim Guard & Forced Tool Calling (`app/services/action_guard.py`)**:
  - **Deterministic Claim Audit**: Verifies affirmative model claims (*"Added garlic bread"*, *"Updated to 1 Margherita"*, *"Applied promo STUDENT15"*, *"Order placed"*) against actual successful tool calls in the current turn.
  - **Fabricated Order Number Blocker**: Catches hallucinated order numbers (`PH-YYYYMMDD-NNNN`, `Order No: X`) and blocks confirmation unless backed by a genuine `order.place_order` SQLite record.
  - **Forced Tool-Choice Self-Correction Loop**: When an unbacked action is asserted, the orchestrator triggers a corrective turn with `tool_choice="required"`, forcing the model to emit the necessary tool call rather than silently failing.
  - **Indexed Cart State**: Injects zero-indexed cart lines (`[0] 2 x Margherita (large)...`) into the state block so `cart.update_item` and `cart.remove_item` precisely target the intended line.
  - **Honest Safe Fallback**: If the model fails to emit a valid tool call after correction retries, an honest fallback is returned to the user, ensuring the conversation and cart state never desynchronize.

---

## Voice Notes: Audio Conversion, STT, Transcript Confirmation & TTS (Phase 6)

- **Gateway Media Pipeline (`gateway/src/media.js` & `index.js`)**:
  - Rejects voice notes exceeding 60 seconds (`MAX_AUDIO_SECONDS`) or 2 MB (`MAX_AUDIO_BYTES`) before downloading or calling the Brain.
  - Downloads OGG/Opus voice notes via Baileys `downloadMediaMessage`, base64-encodes them, and sends optional `reply_audio_b64` responses back as WhatsApp push-to-talk (`ptt: true`) voice notes.
- **Audio Normalization & Ephemeral Deletion (`app/voice/audio.py`)**:
  - Converts incoming audio to **16 kHz mono 16-bit PCM WAV** via `ffmpeg` with subprocess timeouts and guarantees **immediate deletion of temporary audio files** inside a `finally` block (strictly enforcing `policies/privacy-policy.md`).
- **Domain-Biased STT (`app/voice/stt.py`)**:
  - Supports local `faster-whisper` (int8 CPU) with automatic fallback to OpenAI-compatible audio transcription (`/v1/audio/transcriptions`) and deterministic stubbing for unit tests.
  - Injects a Sri Lankan & Pizza Hut domain vocabulary prompt (*Devilled Chicken, Chicken Tikka, Veggie Delight, Colombo 07, Nugegoda, Kandy, Delkanda, Katugastota, Bambalapitiya, LKR*) for higher entity recognition accuracy.
- **Transcript Confirmation Rule (`app/agents/orchestrator.py`)**:
  - Whenever a voice note has low STT confidence (`< 0.75`) or contains order-mutating entities (menu items, sizes, quantities, or delivery addresses), the orchestrator holds the transcript in `session.pending_voice_transcript` and asks: `'I heard: "<transcript>". Correct? Reply YES to confirm.'` before mutating the cart.
- **Optional TTS (`app/voice/tts.py`)**:
  - When `TTS_ENABLED=true`, synthesizes OGG/Opus voice replies only when the customer sent a voice note, automatically falling back to text-only for Sinhala/Tamil (`si`/`ta`) while always keeping text receipts alongside audio.

---

## Escalation Agent, Post-Order Tracking & Per-Branch Staff Flow (Phase 7)

- **Escalation Agent (`app/agents/escalation_agent.py`)**:
  - Mirrors every trigger category in `internal/hr/bot-escalation-rules.md` (`complaint`, `refund_or_compensation`, `severe_allergy`, `food_safety_or_illness`, `abusive_or_frustrated`, `manager_or_human_request`, and `repeated_failures` when `consecutive_failures >= 3`), verified by an automated markdown-sync unit test.
  - Transitions the session into `stage="handoff"` for 2 hours, persists a `Handoff` record in SQLite (`app/db/order_repo.py`), and returns an **opening-hours-aware** response (promising a reply within 30 minutes during opening hours, or by 11:00 the next morning when outlets are closed).
  - While in `stage="handoff"`, the bot stays silent to the customer (`reply_text=None`) and forwards customer follow-up messages directly to staff.
- **Per-Branch & Area Manager Notifier (`app/services/notifier.py` & `gateway/src/internalServer.js`)**:
  - Pushes outbound WhatsApp notifications to `gateway/src/internalServer.js` (`POST /send` protected by `X-Internal-Secret`) with automatic retries; failures are logged and never block customer replies or order placement.
  - Routes handoff alerts (with customer ID, reason, last 5 messages, and cart summary) to `STAFF_NOTIFY_JIDS[branch_id]` if known, or `STAFF_NOTIFY_JIDS["area"]`. Critical cases (`severe_allergy`, `food_safety_or_illness`) notify **both** the branch manager and the Area Manager.
- **Post-Order Agent & Branch-Scoped Staff Commands (`app/agents/post_order_agent.py`)**:
  - Generates a one-line order summary and notifies the order's branch staff **exactly once** upon `order.place_order`.
  - Authenticates staff senders against `STAFF_NOTIFY_JIDS` and enforces strict branch scoping (e.g., a Kandy staff number cannot modify a Nugegoda order, whereas the `area` manager number can act on all branches):
    - `/orders`: Lists recent orders for the staff member's branch scope.
    - `/status <order_no> <status>`: Updates order status in SQLite and sends a formatted status update message to the customer (`accepted`, `preparing`, `out_for_delivery`, `ready_for_pickup`, `completed`, `cancelled`).
    - `/resume <user_id>`: Resolves open handoff records and returns the customer session to `stage="browsing"`.

---

## Automated Evaluation Pipeline & Quality Gates (Phase 8)

The system includes an enterprise-grade 7-layer evaluation framework (`brain/eval/`) supporting both hermetic offline CI (`--offline`) and live LLM regression runs:

### Evaluation Layers & Responsibilities

| Layer | Suite | Target / Responsibility | Quality Gate | Primary Files |
|---|---|---|---|---|
| **L1** | `retrieval` | 61 queries (41 menu/branch/offer/policy in EN/SI/TA/Singlish, 10 out-of-scope, 10 internal leak probes) | `Recall@4 >= 0.90`<br>`Hit@1 >= 0.75`<br>`OOS Refusal >= 0.95`<br>`Internal Leaks == 0` | `eval/datasets/retrieval.yaml`<br>`eval/runners/retrieval_eval.py` |
| **L2** | `tools` | 15 single-turn & short trajectories (cart mutations, branch resolution, promo validation, ice cream zone rules, cutoff hours) | `Tool selection accuracy >= 0.92`<br>`Argument accuracy >= 0.92`<br>`Forbidden tool calls == 0` | `eval/datasets/tools.yaml`<br>`eval/runners/tools_eval.py` |
| **L3** | `conversation` | 32 end-to-end multi-turn customer scenarios across all branches, pickup/delivery, promo edge cases, mind changes, and language variants | `Pass@3 >= 0.90`<br>`Zero invariant violations`<br>(no unbacked order numbers or prices) | `eval/datasets/conversations/*.yaml`<br>`eval/simulator.py` |
| **L4** | `judge` | LLM-as-Judge scoring 6 dimensions (groundedness, price integrity, instruction adherence, language match, tone/brevity, safety) | `Mean score >= 4.2 / 5.0`<br>`Calibration within-1 >= 0.85`<br>`Deterministic price override` | `eval/datasets/judge_calibration.yaml`<br>`eval/runners/judge.py` |
| **L5** | `safety` | 42 adversarial cases (prompt injection, PII leak probes, order quantity abuse, fake discounts, severe allergy & complaint handoffs) | `Escalation recall == 1.00`<br>`False positive rate <= 0.02`<br>`Safety violations == 0` | `eval/datasets/safety.yaml`<br>`eval/runners/safety_eval.py` |
| **L6** | `voice` | Multilingual STT WER, slot recognition across items/quantities/addresses, and 100% low-confidence confirmation trigger | `Slot accuracy >= 0.90 / lang`<br>`Low-conf recall == 1.00` | `eval/datasets/voice.yaml`<br>`eval/runners/voice_eval.py` |
| **L7** | `isolation` | Hermetic sandbox (temporary SQLite DB, in-memory sessions, mock notifier, frozen clock) + latency/token/cost telemetry | `p50 <= 4000 ms`<br>`p95 <= 10000 ms`<br>`Zero regression > 3% from baseline` | `eval/isolation.py`<br>`eval/run.py`<br>`eval/reports/baseline.json` |

### Running the Evaluation Suite

You can execute the entire suite or individual layers using Python or the root `Makefile`:

```powershell
cd brain

# 1. Run the entire offline evaluation suite against baseline.json
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe -m eval.run --suite all --offline

# 2. Run specific individual evaluation suites
.\.venv\Scripts\python.exe -m eval.run --suite retrieval --offline
.\.venv\Scripts\python.exe -m eval.run --suite tools --offline
.\.venv\Scripts\python.exe -m eval.run --suite conversation --offline
.\.venv\Scripts\python.exe -m eval.run --suite judge --offline
.\.venv\Scripts\python.exe -m eval.run --suite safety --offline
.\.venv\Scripts\python.exe -m eval.run --suite voice --offline

# 3. Run live online LLM evaluations (requires active API key)
.\.venv\Scripts\python.exe -m eval.run --suite all --repeats 3
```

### Baseline Regression Protection (`baseline.json`)
Every evaluation run is automatically checked against [brain/eval/reports/baseline.json](file:///f:/Noob%20Dev/CAAEP/WhatsApp-agent/brain/eval/reports/baseline.json):
- If any accuracy or recall metric drops by more than **3.0%**, the runner flags a regression and exits with code `1`.
- Any non-zero count in zero-tolerance gates (`internal_leaks`, `forbidden_tool_violations`, `invariant_violations`, `safety_violations`) causes immediate failure.
- Generated artifacts in `brain/eval/reports/<timestamp>/`:
  - `summary.md`: Scoreboard, quality gates, and telemetry summary.
  - `results.json`: Full structured JSON metrics.
  - `failures.md`: Detailed failure log and baseline diffs.
  - `costs.json`: Turn latencies (p50/p95), tokens, and estimated USD cost.

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

### 3. Running Automated Tests, Evaluation Pipeline & Makefile Targets

The workspace provides both granular Python test runners and unified `Makefile` targets:

#### A. Unified Makefile Commands (Root Directory)
```bash
# Validate knowledge base front-matter, chunk word counts, and zero PII leaks
make validate-kb

# Run all unit and integration tests across tests/
make test

# Run the complete offline evaluation suite (all 6 layers) against baseline.json
make eval

# Run a specific evaluation layer (e.g. retrieval, tools, conversation, judge, safety, voice)
make eval SUITE=retrieval
make eval SUITE=tools
make eval SUITE=conversation
make eval SUITE=judge
make eval SUITE=safety
make eval SUITE=voice

# Rebuild the zero-downtime blue/green vector index
make ingest
```

#### B. Direct Python Execution (inside `brain/`)
```powershell
cd brain
$env:HF_HUB_OFFLINE="1"

# 1. Run the Phase 8 evaluation pipeline integration test suite
.\.venv\Scripts\python.exe -m unittest tests/test_phase8_eval.py -v

# 2. Run the full unit & integration test suite (Phase 4, 5, 6, 7 & 8)
.\.venv\Scripts\python.exe -m unittest discover tests

# 3. Run the zero-LLM deterministic order flow CLI demo
.\.venv\Scripts\python.exe -m app.tools.cli --demo

# 4. Run Phase 8 unified evaluation runner
.\.venv\Scripts\python.exe -m eval.run --suite all --offline
```

#### C. Running Evaluations While Agents Are Online (Live Server Mode)
All evaluation runs use `eval_sandbox()`, which provisions:
- An isolated in-memory session store (leaving active WhatsApp conversations untouched)
- A temporary SQLite database (leaving `orders.db` clean)
- A mock notifier (preventing real WhatsApp notifications to branch staff)
- A frozen `Asia/Colombo` clock for deterministic cutoff and opening-hours verification

Therefore, you can run evaluations **at any time without stopping the running FastAPI server or Baileys Gateway**. To run evaluations against live LLM models instead of offline heuristics, simply omit the `--offline` flag:
```powershell
cd brain
.\.venv\Scripts\python.exe -m eval.run --suite all --repeats 3
```
