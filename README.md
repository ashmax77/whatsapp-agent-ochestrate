# Pizza Hut Multi-Agent WhatsApp Ordering System 🍕🤖

[![CI Quality Gates](https://img.shields.io/badge/CI%20Gates-Passing-brightgreen.svg)](./.github/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](./brain/)
[![Node Version](https://img.shields.io/badge/Node.js-20%2B-green.svg)](./gateway/)
[![Phases Complete](https://img.shields.io/badge/Phases%201--9-Complete-success.svg)](./plan.md)
[![License](https://img.shields.io/badge/License-Proprietary%20%2F%20Sample-lightgrey.svg)](#license--disclaimer)

An enterprise-grade, multi-agent conversational commerce assistant for Pizza Hut Sri Lanka operating across multiple branches (Colombo 07, Nugegoda, and Kandy). The system handles customer inquiries grounded in a curated knowledge base, builds food carts with combo rules, resolves delivery zones and operating hours, verifies cryptographic order confirmations, processes multilingual voice notes, and escalates complaints to human staff.

![Architecture Diagram](./architecture.jpg)

---

## Table of Contents

- [Overview & Key Features](#overview--key-features)
- [Implementation Status & Roadmap](#implementation-status--roadmap)
- [System Architecture](#system-architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
  - [Option A: Containerized Stack (Docker Compose)](#option-a-containerized-stack-docker-compose)
  - [Option B: Local Development Stack](#option-b-local-development-stack)
- [Inter-Service Contract](#inter-service-contract)
- [Evaluation Framework & Quality Gates (L1–L7)](#evaluation-framework--quality-gates-l1l7)
- [Observability, Telemetry & Health Checks](#observability-telemetry--health-checks)
- [Privacy Policy & Data Retention Enforcement](#privacy-policy--data-retention-enforcement)
- [Meta WhatsApp Cloud API Migration Path](#meta-whatsapp-cloud-api-migration-path)
- [Project Directory Structure](#project-directory-structure)
- [Unified Makefile Reference](#unified-makefile-reference)
- [Contributing](#contributing)
- [License & Disclaimer](#license--disclaimer)

---

## Overview & Key Features

- **Strict Arithmetic Integrity (Decision D3)**: The LLM **never** calculates prices, fees, or discounts. All monetary calculations are performed in deterministic Python code ([`pricing.py`](./brain/app/services/pricing.py)) using integer Sri Lankan Rupees (LKR).
- **Grounded Hybrid RAG (Decision D4 & D21)**: Customer Q&A is grounded in 29 curated Markdown documents using local FastEmbed (`BAAI/bge-small-en-v1.5`), BM25 keyword matching, and cross-encoder reranking.
- **Zero-Leak Data Isolation (Decision D17)**: Staff directories, employee records, and internal escalation policies (`knowledge/internal/`) are completely un-indexed and inaccessible to customers.
- **Code-Enforced Order State Machine (Decision D7 & D8)**: Orders require a 2-step confirmation (`order.show_summary` followed by `order.place_order(cart_hash)`). Unbacked order numbers or premature confirmations are blocked by deterministic action guards.
- **Multilingual Support**: Communicates naturally in English, Sinhala, Tamil, and Singlish with automatic script and language detection.
- **Voice Note Processing (Faster-Whisper)**: Ingests WhatsApp voice notes, converts audio via `ffmpeg`, transcribes using Faster-Whisper, and enforces a mandatory confirmation rule for low-confidence transcriptions.
- **Multi-Branch Operations**: Haversine location pin resolution and fuzzy alias matching across Colombo 07, Nugegoda, and Kandy, with strict opening hours and delivery cutoff validation.
- **Human Escalation & Staff Pushes**: Automatic keyword and intent classification for complaints, refund requests, or severe allergies, routing alerts to branch managers via outbound WhatsApp notifications.

---

## Implementation Status & Roadmap

| Phase | Milestone | Focus Areas | Status |
|---|---|---|---|
| **Phase 1** | Baileys WhatsApp Gateway | WebSocket pairing, connection persistence, call rejection, message normalization | ✅ Completed |
| **Phase 2** | FastAPI Brain Skeleton | Async `/message` pipeline, session state, and baseline contracts | ✅ Completed |
| **Phase 3** | Knowledge Base & RAG | Blue/green index builder, manifest swap, BM25 + vector search, KB validator | ✅ Completed |
| **Phase 4** | Deterministic Tools & Agents | Pricing engine, cart management, branch resolution, promos, SQLite persistence | ✅ Completed |
| **Phase 5** | Orchestrator & State Machine | Stage-based tool filtering, session locking, anti-hallucination guards, deduplication | ✅ Completed |
| **Phase 6** | Voice Notes & Audio Pipeline | Audio conversion, Faster-Whisper STT, transcript confirmation rules | ✅ Completed |
| **Phase 7** | Escalation & Staff Alerts | Rule-based handoff triggers, per-branch notification pushes, staff status commands | ✅ Completed |
| **Phase 8** | 7-Layer Evaluation Framework | 32 E2E conversation scenarios, retrieval gates, tools eval, baseline regression CI | ✅ Completed |
| **Phase 9** | Production Hardening & Cloud API | Dockerization, Prometheus metrics, privacy retention, 20-client load test, Cloud API guide | ✅ Completed |

---

## System Architecture

The solution is decoupled into two independent microservices interacting over HTTP JSON:

```
                      +---------------------------------------+
                      |         Customer (WhatsApp)           |
                      +-------------------+-------------------+
                                          |
                        Baileys Socket / Meta Cloud Webhook
                                          v
                      +---------------------------------------+
                      |     gateway/ (Node.js 20 / Baileys)   |
                      |   - WebSocket / Webhook Normalization |
                      |   - Audio Download & Media Decoding   |
                      |   - Internal Push Server (POST /send) |
                      +-------------------+-------------------+
                                          |
                            POST /message | POST /send
                                          v
                      +---------------------------------------+
                      |         brain/ (Python 3.12 FastAPI)  |
                      |   - Central Orchestrator Agent        |
                      |   - Hybrid RAG (BM25 + FastEmbed)     |
                      |   - Deterministic Pricing & State     |
                      |   - Action Guard & Price Verifier     |
                      +---------+-------------------+---------+
                                |                   |
                 +--------------+                   +-------------+
                 v                                                v
      +--------------------+                           +--------------------+
      |  data/knowledge/   |                           |  data/orders.db    |
      |  Customer RAG Chunks|                          |  SQLite WAL Mode   |
      +--------------------+                           +--------------------+
```

---

## Prerequisites

- **Python**: Version 3.12 or higher
- **Node.js**: Version 20 LTS or higher (with `npm`)
- **System Audio Utilities**: `ffmpeg` installed and available in system `PATH` (required for voice-note processing)
- **Docker**: Docker Engine 24+ and Docker Compose v2 (optional, for containerized run)
- **Redis**: Redis 7+ (optional, in-memory session store is used by default)

---

## Quick Start

### Option A: Containerized Stack (Docker Compose)

Spin up the entire system (Python Brain, Node Gateway, and Redis) with a single command:

```bash
docker compose up --build
```

- **Brain API**: `http://localhost:8000`
- **Gateway Server**: `http://localhost:3000`
- **Gateway Notification Endpoint**: `http://localhost:3001`
- **Prometheus Metrics**: `http://localhost:8000/metrics`

---

### Option B: Local Development Stack

#### 1. Setup & Start the Python Brain

```bash
# Navigate to the brain directory
cd brain

# Create and activate virtual environment (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Create and activate virtual environment (Linux / macOS)
# python3 -m venv .venv && source .venv/bin/activate

# Install dependencies (CPU-optimized PyTorch + Brain requirements)
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# Validate Knowledge Base and build local vector index
python -m app.rag.validate_kb
python -m app.rag.ingest --local

# Start the Brain server using startup script
start.bat
# Or run uvicorn directly:
# uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

#### 2. Setup & Start the Node.js Gateway

In a separate terminal window:

```bash
# Navigate to the gateway directory
cd gateway

# Install dependencies
npm ci

# Start the Baileys gateway service
npm start
```

Scan the terminal QR code using WhatsApp (**Settings > Linked Devices > Link a Device**) to authenticate.

---

## Inter-Service Contract

The Gateway communicates with the Brain via HTTP JSON:

- **Endpoint**: `POST http://127.0.0.1:8000/message`
- **Request (`IncomingMessage`)**:
  ```json
  {
    "user_id": "94771234567",
    "type": "text",
    "content": "Can I get 1 medium Supreme pizza for delivery to Cinnamon Gardens?",
    "message_id": "wamid.HBgM...",
    "push_name": "Kasun",
    "timestamp": 1731100000
  }
  ```
- **Response (`BrainReply`)**:
  ```json
  {
    "reply_text": "Added 1 Medium Supreme Pizza (LKR 2,890) to your cart. Delivering to Cinnamon Gardens (Colombo 07 branch). Would you like to add any drinks or sides? 🍕",
    "reply_audio_b64": null,
    "reply_audio_mime": null,
    "meta": {
      "stage": "building_cart",
      "branch_id": "colombo07",
      "trace_id": "8fc446b1",
      "latency_ms": 142.0
    }
  }
  ```

---

## Evaluation Framework & Quality Gates (L1–L7)

The system includes a 7-layer evaluation framework with automated regression detection:

| Layer | Suite | Description | Quality Gate | Primary Files |
|---|---|---|---|---|
| **L1** | `retrieval` | 61 queries (41 menu/policy/hours in EN/SI/TA/Singlish, 10 out-of-scope, 10 leak probes) | `Recall@4 >= 0.90`<br>`Hit@1 >= 0.75`<br>`Leaks == 0` | [`eval/datasets/retrieval.yaml`](./brain/eval/datasets/retrieval.yaml) |
| **L2** | `tools` | 15 tool trajectories (cart CRUD, promo logic, cutoffs, out-of-area checks) | `Selection >= 0.92`<br>`Args >= 0.92`<br>`Forbidden == 0` | [`eval/datasets/tools.yaml`](./brain/eval/datasets/tools.yaml) |
| **L3** | `conversation` | 32 end-to-end multi-turn simulated customer conversations | `Pass@3 >= 0.90`<br>`Invariants == 0` | [`eval/datasets/conversations/`](./brain/eval/datasets/conversations/) |
| **L4** | `judge` | LLM-as-Judge scoring groundedness, price integrity, tone, and brevity | `Score >= 4.2 / 5.0`<br>`Price override active` | [`eval/runners/judge.py`](./brain/eval/runners/judge.py) |
| **L5** | `safety` | 42 adversarial cases (prompt injections, PII extraction, fake discounts, severe allergies) | `Escalation == 1.00`<br>`Violations == 0` | [`eval/datasets/safety.yaml`](./brain/eval/datasets/safety.yaml) |
| **L6** | `voice` | Multilingual STT WER, slot recognition, and low-confidence confirmation triggers | `Slot Acc >= 0.90`<br>`Confirm Recall == 1.00` | [`eval/datasets/voice.yaml`](./brain/eval/datasets/voice.yaml) |
| **L7** | `isolation` | Hermetic sandbox execution (temp SQLite, mock notifier, frozen clock) | `p50 <= 4s, p95 <= 10s`<br>`Regression <= 3%` | [`eval/isolation.py`](./brain/eval/isolation.py) |

### Executing Evaluation Suites

```bash
cd brain

# Run complete evaluation suite offline
python -m eval.run --suite all --offline

# Run specific evaluation layers
python -m eval.run --suite retrieval --offline
python -m eval.run --suite tools --offline
python -m eval.run --suite conversation --offline
```

---

## Observability, Telemetry & Health Checks

- **Prometheus Metrics (`GET /metrics`)**:
  Exposes real-time request counters, turn latency percentiles (p50, p95, p99), tool execution counts, error rates, handoffs, and branch order distribution:
  ```bash
  curl http://127.0.0.1:8000/metrics
  # Or request JSON format:
  curl http://127.0.0.1:8000/metrics?format=json
  ```
- **Extended Health Probes (`GET /health/extended`)**:
  Verifies SQLite database connectivity, session store status, and system uptime:
  ```bash
  curl http://127.0.0.1:8000/health/extended
  ```

---

## Privacy Policy & Data Retention Enforcement

In strict compliance with [`data/knowledge/policies/privacy-policy.md`](./brain/data/knowledge/policies/privacy-policy.md):

- **Chat Log Retention Pruning (`brain/app/db/retention.py`)**:
  Purges customer chat logs (`MessageLog`) older than 30 days while retaining anonymized orders for 12 months.
  ```bash
  cd brain
  python -m app.db.retention --days 30
  ```
- **Right-to-be-Forgotten API (`POST /admin/forget`)**:
  Allows staff to instantly erase customer chat history, anonymize delivery addresses on past orders, and reset active sessions:
  ```bash
  curl -X POST http://127.0.0.1:8000/admin/forget \
    -H "Content-Type: application/json" \
    -H "X-Internal-Secret: change-me" \
    -d '{"user_id": "94771234567"}'
  ```

---

## Meta WhatsApp Cloud API Migration Path

To eliminate account ban risks inherent to web automation libraries, a clean migration path to the official **Meta WhatsApp Business Cloud API** is built into the architecture:

- **Zero Brain Modifications**: The Brain communicates strictly via `IncomingMessage` and `BrainReply`. Switching to Meta Cloud API is done entirely at the Gateway layer.
- **Reference Adapter**: Review [`gateway/meta_cloud_adapter_example.js`](./gateway/meta_cloud_adapter_example.js) for an Express.js implementation handling Meta Webhook HMAC SHA-256 signatures, Graph API media fetching, and outbound messaging.
- **Dual-Run Coexistence**: Baileys remains the active local development gateway while Meta Cloud API can be staged independently.
- **Detailed Runbook**: See [`docs/cloud_api_migration.md`](./docs/cloud_api_migration.md) for full setup instructions, System User tokens, and template guidelines.

---

## Project Directory Structure

```
pizza-agent/
├── .github/
│   └── workflows/
│       └── ci.yml                      # Multi-job CI workflow (Brain gates, Gateway lint, Docker config)
├── Makefile                            # Unified targets (make test, make eval, make validate-kb, make load-test)
├── .gitignore                          # Excludes local environments, DBs, caches, and docs/
├── docker-compose.yml                  # Production stack (Brain + Gateway + Redis)
├── plan.md                             # Phase-by-phase engineering specification
├── README.md                           # Master project documentation
├── architecture.jpg                    # Architecture schematic
│
├── gateway/                            # Node.js: Baileys WhatsApp I/O Service
│   ├── Dockerfile                      # Node 20-alpine container with curl health check
│   ├── .dockerignore                   # Build exclusions (node_modules, auth_state)
│   ├── auth_state/                     # Baileys session credentials (volume mounted)
│   ├── src/
│   │   ├── index.js                    # Baileys socket, QR login, event handlers
│   │   ├── config.js                   # Gateway configuration loader
│   │   ├── brainClient.js              # Resilient HTTP client communicating with Brain
│   │   ├── internalServer.js           # Internal push server (POST /send) for staff notifications
│   │   ├── sender.js                   # WhatsApp outbound messaging helper
│   │   └── media.js                    # Voice note download and decoding utilities
│   ├── meta_cloud_adapter_example.js   # Reference Meta Cloud API Express adapter
│   ├── package.json
│   └── package-lock.json
│
└── brain/                              # Python: FastAPI Multi-Agent Engine
    ├── Dockerfile                      # Python 3.12-slim container with system ffmpeg
    ├── .dockerignore                   # Excludes .venv and internal staff knowledge (Decision D17)
    ├── app/
    │   ├── main.py                     # FastAPI entrypoint (/health, /metrics, /message, /admin/forget)
    │   ├── config.py                   # Pydantic settings with runtime .env hot-reloading
    │   ├── schemas.py                  # Pydantic request/response models
    │   ├── llm/
    │   │   └── client.py               # Unified LLM completion facade with fallback cascades
    │   ├── services/
    │   │   ├── pricing.py              # Pure integer-LKR pricing engine & WhatsApp receipt formatter
    │   │   ├── branch_repo.py          # Haversine pin & alias resolver with operating hours check
    │   │   ├── menu_repo.py            # Structured menu items, colloquial aliases & combo rules
    │   │   ├── promo_repo.py           # Deterministic promo validator (days, dates, branches)
    │   │   ├── action_guard.py         # Action claim and order number verification guard
    │   │   ├── post_processor.py       # Anti-hallucination price verification guard
    │   │   ├── metrics.py              # Prometheus metrics collector
    │   │   └── notifier.py             # Staff & customer outbound notification dispatcher
    │   ├── state/
    │   │   ├── session.py              # Customer Session, CartLine & summary hash models
    │   │   ├── memory_store.py         # In-memory session store with mutex locks
    │   │   └── redis_store.py          # Distributed Redis session store
    │   ├── agents/
    │   │   ├── orchestrator.py         # Central orchestrator with stage-aware tool loops
    │   │   ├── knowledge_agent.py      # Grounded RAG agent with query rewriting
    │   │   ├── order_agent.py          # Deterministic cart and order lifecycle agent
    │   │   ├── delivery_agent.py       # Branch and zone resolution agent
    │   │   ├── promo_agent.py          # Promo code application agent
    │   │   └── escalation_agent.py     # Complaint detection and staff handoff agent
    │   ├── tools/
    │   │   ├── registry.py             # Tool registry with state machine stage guards
    │   │   └── cli.py                  # Zero-LLM CLI demo harness (python -m app.tools.cli --demo)
    │   ├── rag/
    │   │   ├── validate_kb.py          # Knowledge base consistency and PII validator
    │   │   ├── ingest.py               # Blue/green vector index builder
    │   │   └── retriever.py            # Hybrid BM25 + vector search and reranker
    │   ├── voice/
    │   │   ├── audio.py                # ffmpeg audio converter (OGG/Opus -> 16kHz WAV)
    │   │   └── stt.py                  # Faster-Whisper speech-to-text service
    │   └── db/
    │       ├── models.py               # SQLAlchemy/Pydantic customer, order, and log models
    │       ├── order_repo.py           # SQLite repository with WAL mode and busy timeouts
    │       └── retention.py            # Privacy data retention pruner
    ├── data/
    │   ├── branches.json               # Outlet coordinates, operating hours, and zone radii
    │   ├── promos.json                 # Active promo rules (FRIDAY10, STUDENT15)
    │   ├── menu.json                   # Single source of truth for LKR prices and sizes
    │   └── knowledge/                  # Curated multi-folder knowledge base (29 Markdown files)
    │       ├── README.md               # Knowledge base subsystem documentation
    │       ├── branches/               # Colombo 07, Nugegoda, Kandy branch documents
    │       ├── menu/                   # Pizzas, sides, desserts, beverages, allergens
    │       ├── offers/                 # Current and expired marketing offers
    │       ├── policies/               # Ordering, refunds, privacy, food safety
    │       └── internal/               # Staff directories and HR rules (NEVER customer-indexed)
    └── eval/
        ├── isolation.py                # Sandbox isolation fixtures (temp DB, frozen clock)
        ├── run.py                      # Unified evaluation runner CLI
        ├── simulator.py                # Customer simulator for multi-turn evaluations
        ├── load_test.py                # 20-concurrent customer load testing harness
        ├── datasets/                   # Test datasets (retrieval, tools, safety, voice, c001-c032)
        └── reports/
            └── baseline.json           # Tracked evaluation regression baseline
```

---

## Unified Makefile Reference

All primary administrative, evaluation, and operational tasks can be executed via the root `Makefile`:

| Target | Command | Purpose |
|---|---|---|
| `make test` | `python -m unittest discover -s tests -v` | Runs all unit and integration test suites |
| `make validate-kb` | `python -m app.rag.validate_kb` | Validates KB front-matter, chunk limits, and zero PII leaks |
| `make ingest` | `python -m app.rag.ingest --rebuild` | Drops and rebuilds the customer vector index |
| `make eval` | `python -m eval.run --suite all --offline` | Executes the complete 7-layer offline evaluation suite |
| `make load-test` | `python -m eval.load_test --concurrency 20` | Runs 20-concurrent user stress test against Brain API |
| `make retention` | `python -m app.db.retention` | Prunes customer message logs older than 30 days |
| `make docker-build`| `docker compose build` | Builds production Docker container images |

---

## Contributing

1. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. **Adhere to System Invariants**:
   - Never compute prices in prompts or LLM output; always use [`pricing.py`](./brain/app/services/pricing.py).
   - Never index or expose files from `knowledge/internal/` to customers (Decision D17).
   - If updating menu or branch facts, update Markdown and structured JSON synchronously.
3. **Verify Quality Gates**:
   ```bash
   make validate-kb
   make test
   make eval
   ```
4. **Submit a Pull Request**: Submit your PR with a clear summary of changes and evaluation results.

---

## License & Disclaimer

All customer identities, staff rosters, physical branch addresses, telephone numbers, and order histories within this repository are **fictional sample assets** constructed strictly for demonstration, automated testing, and research purposes.
