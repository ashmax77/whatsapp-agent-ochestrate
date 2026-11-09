# Pizza Agent 🍕🤖

An intelligent, multi-agent WhatsApp assistant for Pizza Hut (operating across multiple branches: Colombo 07, Nugegoda, and Kandy). The assistant handles customer inquiries about menus, dietary details, branches, and policies grounded in a curated knowledge base, alongside managing food orders in Sri Lankan Rupees (LKR).

---

## Architecture Overview

The system is decoupled into two primary services:

- **`gateway/` (Node.js + Baileys)**: Strictly handles WhatsApp I/O (WebSocket protocol, QR code pairing, connection management, voice call auto-rejection, message normalization, and media downloads). Contains zero business or AI logic.
- **`brain/` (Python + FastAPI)**: Microservice containing all AI logic, multi-agent orchestration, RAG retrieval over curated markdown knowledge, session state management, order calculation, and audio transcription.

```
pizza-agent/
├── .gitignore
├── docker-compose.yml          # Multi-container orchestration (gateway, brain, redis, qdrant)
├── plan.md                     # Comprehensive phase-by-phase implementation plan
├── README.md                   # Project documentation
├── architecture.jpg            # Architecture diagram
│
├── gateway/                    # Node.js: Baileys WhatsApp I/O service
│   ├── auth_state/             # Baileys session credentials (git-ignored)
│   ├── src/
│   │   ├── index.js            # Baileys socket, QR login, event handlers
│   │   ├── config.js           # Gateway environment configuration
│   │   ├── brainClient.js      # Resilient HTTP client communicating with Brain (/message)
│   │   └── media.js            # (Phase 6) Voice note download/send helpers
│   ├── package.json
│   ├── package-lock.json
│   └── .env
│
└── brain/                      # Python: FastAPI AI backend & multi-agent system
    ├── app/
    │   ├── main.py             # FastAPI entrypoint (/health, /message)
    │   ├── config.py           # Settings and environment configuration
    │   ├── schemas.py          # Pydantic request/response models (IncomingMessage, BrainReply)
    │   ├── state/
    │   │   └── session.py      # Per-customer session state machine
    │   ├── agents/             # Multi-agent orchestrator & specialists
    │   │   ├── orchestrator.py # Central intent router and coordinator
    │   │   ├── menu_agent.py   # Menu inquiries, pricing, customization
    │   │   ├── order_agent.py  # Cart operations & validation
    │   │   ├── delivery_agent.py # Address resolution & delivery estimation
    │   │   ├── promo_agent.py  # Promo codes & discount validation
    │   │   ├── escalation_agent.py # Complaint detection & staff handoff
    │   │   └── post_order_agent.py # Order status tracking
    │   ├── tools/              # Functions callable by agents
    │   ├── rag/                # RAG pipeline (ingest.py, retriever.py)
    │   ├── voice/              # (Phase 6) STT and TTS handlers (stt.py, tts.py)
    │   └── db/                 # Database persistence (SQLite / PostgreSQL)
    ├── data/
    │   └── knowledge/          # Curated multi-folder knowledge base (Customer & Internal)
    │       ├── README.md       # Knowledge base authoring rules
    │       ├── branches/       # Branch directory, Colombo 07, Nugegoda, Kandy
    │       ├── company/        # About Us, service standards
    │       ├── faq/            # General customer FAQs
    │       ├── internal/       # Staff-only documents (NEVER indexed for customers)
    │       │   ├── README.md
    │       │   ├── employees/  # Roles, shift schedules, staff directory
    │       │   └── hr/         # Escalation rules, code of conduct, leave policies
    │       ├── menu/           # Pizzas & pricing (LKR), sides, beverages, customization, allergens
    │       ├── offers/         # Current offers, expired offers, loyalty program
    │       └── policies/       # Ordering & delivery, payment & refunds, cancellation, food safety
    ├── tests/
    │   └── test_api.py         # Unit tests
    ├── start.bat               # Windows CMD startup script
    ├── start.ps1               # Windows PowerShell startup script
    ├── requirements.txt
    ├── pyproject.toml
    ├── uv.lock
    ├── .python-version
    └── .env
```

---

## Knowledge Base & Data Details

The system relies on a structured, modular knowledge base located in `brain/data/knowledge/`:

- **Currency**: All prices, charges, and minimum order values are in **Sri Lankan Rupees (LKR)**.
- **Customer Knowledge**:
  - `menu/`: Detailed items, portion sizes, prices in LKR, allergen declarations, and customization rules.
  - `branches/`: Specific branch addresses, operating hours, delivery radii (Colombo 07: 8 km, Nugegoda: 8 km, Kandy: 6 km), and cutoff times.
  - `offers/`: Discount criteria (e.g. `FRIDAY10`, `STUDENT15`), minimum spend requirements, and valid days.
  - `policies/`: Minimum order amounts (LKR 1,500 for delivery), accepted payment methods (Cash/Card on delivery), refund conditions, and delivery timeframes.
- **Internal Knowledge Isolation**:
  - `internal/`: Contains confidential employee records, shift schedules, and HR guidelines.
  - **Strict Security Rule**: Excluded from customer vector indexing and shielded by audience filters (`where={"audience": "customer"}`).

---

## Inter-Service Contract

The Gateway communicates with the Brain via HTTP JSON:

- **Endpoint**: `POST http://127.0.0.1:8000/message`
- **Request (`IncomingMessage`)**:
  ```json
  {
    "user_id": "9470000000",
    "type": "text",
    "content": "What vegetarian pizzas do you have?",
    "message_id": "ABC123XYZ",
    "push_name": "Ashen"
  }
  ```
- **Response (`BrainReply`)**:
  ```json
  {
    "reply_text": "We offer Classic Margherita, Veggie Delight, and Cheese Lover pizzas! 🍕",
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

**Option A: Using the Quick Start Scripts (Recommended for Windows)**
```powershell
# In PowerShell:
.\start.ps1

# In Command Prompt (CMD):
start.bat
```

**Option B: Manual Activation & Startup**
```powershell
# Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# Start the server with Uvicorn
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

### 3. Running Automated Tests

Run unit tests inside the `brain` directory:

```powershell
cd brain
.\.venv\Scripts\python.exe -m unittest tests/test_api.py
```
