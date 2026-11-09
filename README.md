# Pizza Agent 🍕🤖

An intelligent, multi-agent WhatsApp pizza ordering assistant.

## Architecture

The project is decoupled into two independent services:
- **`gateway/`**: Node.js microservice running [Baileys](https://github.com/WhiskeySockets/Baileys) strictly handling WhatsApp I/O (sockets, QR login, event handlers, media). No AI logic.
- **`brain/`**: Python FastAPI microservice containing all AI logic, multi-agent orchestration, RAG knowledge retrieval, session management, and speech synthesis/transcription.

```
pizza-agent/
├── gateway/                    # Node.js: Baileys (WhatsApp I/O only, no AI)
│   ├── src/
│   │   ├── index.js            # socket, QR login, event handlers
│   │   ├── config.js
│   │   ├── brainClient.js      # HTTP client to Python
│   │   └── media.js            # (Phase 6) voice note download/send
│   ├── auth_state/             # Baileys session (git-ignored, back this up)
│   ├── package.json
│   └── .env
│
├── brain/                      # Python: all AI logic
│   ├── app/
│   │   ├── main.py             # FastAPI app
│   │   ├── schemas.py          # request/response models
│   │   ├── config.py
│   │   ├── state/
│   │   │   └── session.py      # per-customer session (memory → Redis later)
│   │   ├── agents/             # (Phase 4-7)
│   │   │   ├── orchestrator.py
│   │   │   ├── menu_agent.py
│   │   │   ├── order_agent.py
│   │   │   ├── delivery_agent.py
│   │   │   ├── promo_agent.py
│   │   │   ├── escalation_agent.py
│   │   │   └── post_order_agent.py
│   │   ├── tools/              # functions the agents call
│   │   ├── rag/                # (Phase 3) ingest.py, retriever.py
│   │   ├── voice/              # (Phase 6) stt.py, tts.py
│   │   └── db/                 # orders, menu (Postgres/SQLite)
│   ├── data/
│   │   ├── menu.json           # exact prices/availability
│   │   └── knowledge/          # FAQs, policies, allergens (for RAG)
│   ├── tests/
│   ├── requirements.txt
│   └── .env
│
├── docker-compose.yml          # (later) gateway + brain + redis + qdrant
├── .gitignore
└── README.md
```

---

## Getting Started

### 1. Python Brain Setup

The Python virtual environment is located inside `brain/.venv`.

```bash
cd brain

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# Windows (Command Prompt):
.\.venv\Scripts\activate.bat

# Install / update dependencies:
pip install -r requirements.txt

# Run the FastAPI brain server:
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Node Gateway Setup

```bash
cd gateway

# Dependencies are already in gateway/node_modules, or run:
npm install

# Start the gateway:
npm start
```

Scan the terminal QR code using WhatsApp to establish the connection.

### 3. Docker Compose (Later Phases)

To bring up all services (brain, gateway, redis, qdrant):

```bash
docker-compose up --build
```
