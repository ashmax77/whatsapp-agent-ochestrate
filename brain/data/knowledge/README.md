# Pizza Hut Multi-Branch Knowledge Base

[![Chunks](https://img.shields.io/badge/Customer%20Chunks-128-blue.svg)](#directory-map--audience-segregation)
[![Validation](https://img.shields.io/badge/KB%20Validation-Passing-brightgreen.svg)](#quick-start-verification--ingestion)
[![Audience](https://img.shields.io/badge/Audience-Customer%20%7C%20Internal-orange.svg)](#directory-map--audience-segregation)
[![Data Notice](https://img.shields.io/badge/Data-Fictional%20Sample-lightgrey.svg)](#disclaimer--notice)

The curated knowledge base subsystem powering grounded Retrieval-Augmented Generation (RAG) for the Pizza Hut Sri Lanka WhatsApp multi-agent ordering system (covering Colombo 07, Nugegoda, and Kandy outlets). It provides factual, descriptive grounding for customer inquiries regarding menus, dietary guidance, branch operations, promotional offers, and company policies.

---

## Table of Contents

- [Directory Map & Audience Segregation](#directory-map--audience-segregation)
- [Authoring & Chunking Guidelines (RAG Constraints)](#authoring--chunking-guidelines-rag-constraints)
- [Single Source of Truth Rules](#single-source-of-truth-rules)
- [Prerequisites & Tooling](#prerequisites--tooling)
- [Quick Start: Verification & Ingestion](#quick-start-verification--ingestion)
- [Contributing & Authoring Workflow](#contributing--authoring-workflow)
- [Security & PII Protection](#security--pii-protection)
- [Disclaimer & Notice](#disclaimer--notice)

---

## Directory Map & Audience Segregation

The knowledge base organizes 29 Markdown files across 7 domain directories. Documents are classified by audience to guarantee strict data privacy:

| Domain | Audience | Customer Indexed? | Description | Sample Files |
|---|---|---|---|---|
| [`company/`](./company/) | `customer` | ✅ Yes | Brand history, service standards, and contact details | [`about-us.md`](./company/about-us.md) |
| [`branches/`](./branches/) | `customer` | ✅ Yes | Branch directory, operating hours, delivery radius, and zones | [`colombo-07.md`](./branches/colombo-07.md), [`kandy.md`](./branches/kandy.md) |
| [`menu/`](./menu/) | `customer` | ✅ Yes | Descriptions, ingredients, customization, and allergen information | [`pizzas.md`](./menu/pizzas.md), [`allergens-and-dietary.md`](./menu/allergens-and-dietary.md) |
| [`offers/`](./offers/) | `customer` | ✅ Yes | Active marketing deals, expired offer apologies, and loyalty FAQ | [`current-offers.md`](./offers/current-offers.md), [`expired-offers.md`](./offers/expired-offers.md) |
| [`policies/`](./policies/) | `customer` | ✅ Yes | Ordering rules, payment terms, cancellations, and food hygiene | [`ordering-and-delivery.md`](./policies/ordering-and-delivery.md), [`privacy-policy.md`](./policies/privacy-policy.md) |
| [`faq/`](./faq/) | `customer` | ✅ Yes | Quick answers to common customer questions | [`general-faq.md`](./faq/general-faq.md) |
| [`internal/`](./internal/) | `internal` | ❌ **NEVER** | Staff shift schedules, employee directory, and bot escalation rules | [`staff-directory.md`](./internal/employees/staff-directory.md), [`bot-escalation-rules.md`](./internal/hr/bot-escalation-rules.md) |

> [!IMPORTANT]
> **Zero-Leak Isolation (Decision D17)**:
> Documents inside [`internal/`](./internal/) are strictly for human branch staff. They are **never indexed** into the customer vector database. The ingestion engine explicitly skips `internal/`, Docker container builds exclude it via `.dockerignore`, and every customer retrieval query enforces `where={"audience": "customer"}`.

---

## Authoring & Chunking Guidelines (RAG Constraints)

Every customer-facing markdown file must adhere to these technical constraints to ensure accurate retrieval and prevent embedding model truncation:

### 1. YAML Front Matter
Every `.md` document must begin with a valid YAML front matter block:
```yaml
---
audience: customer # or internal (mandatory)
last_updated: 2026-11-14 # ISO-8601 date (mandatory)
---
```

### 2. Section Chunking Boundary
- **Heading Structure**: Each section headed by `## ` constitutes exactly **one standalone chunk**.
- **Word Count Limits**: Each `## ` chunk must be between **20 and 120 words**. Sections exceeding 150 words fail automated validation.
- **Self-Contained Content**: Always repeat the subject name (e.g., pizza name, branch name, or promo code) in the section text so the vector representation does not lose context when retrieved in isolation.

### 3. Allergen & Safety Tone
- Never describe an item as unconditionally "safe" or "guaranteed free of allergens".
- State declared allergens factually and direct customers with severe allergies to human staff handoff.

---

## Single Source of Truth Rules

To prevent silent drift between what the agent says and what the ordering system charges, knowledge is decoupled by function:

| Knowledge Type | Authoritative Source | RAG Markdown Role | Validation Rule |
|---|---|---|---|
| **Menu Items & Flavour Profiles** | [`menu/*.md`](./menu/) | Descriptive grounding, ingredients, dietary notes | Headings must match item names in `menu.json` |
| **Prices, Sizes & Surcharges** | `../../data/menu.json` | ❌ **PROHIBITED in Markdown** | `validate_kb` fails if `LKR` or `Rs` appears in `menu/*.md` |
| **Promotional Offers & Codes** | `../../data/promos.json` | Explain terms, day restrictions, and student ID rules | Codes and minimum spend must match `promos.json` |
| **Branch Hours, Radii & Cutoffs** | `../../data/branches.json` | Explain operating hours, delivery radius, and dine-in times | Hours and delivery km must match `branches.json` |

> [!WARNING]
> **No Hardcoded Prices in Menu Markdown**:
> Money and prices are computed exclusively in code ([`pricing.py`](../../app/services/pricing.py)). Placing price figures in `knowledge/menu/` documents will cause immediate build and CI failure.

---

## Prerequisites & Tooling

To validate, index, and test the knowledge base locally, ensure you have:
- Python 3.12+ installed
- Virtual environment activated with required packages (`fastembed`, `pyyaml`, `sentence-transformers`)

```bash
# Navigate to the brain directory and activate virtualenv
cd brain
.\.venv\Scripts\Activate.ps1 # On Windows PowerShell
source .venv/bin/activate    # On Linux / macOS
```

---

## Quick Start: Verification & Ingestion

Run the following copy-pasteable commands to test and index the knowledge base:

### 1. Validate Consistency & Integrity
Executes pre-flight chunk verification, PII scanning, front-matter syntax, and cross-checks against `menu.json`, `promos.json`, and `branches.json`:
```bash
python -m app.rag.validate_kb
```

### 2. Build or Rebuild the Vector Index
Performs atomic blue/green vector indexing using FastEmbed (`BAAI/bge-small-en-v1.5`):
```bash
python -m app.rag.ingest --local
```

### 3. Run Offline Retrieval Evaluation
Verifies Recall@4 (>= 0.90), Hit@1 (>= 0.75), and confirms zero internal leakage across 61 evaluation probes:
```bash
python -m eval.run --suite retrieval --offline
```

### Common CLI Flags

| Tool | Flag | Purpose |
|---|---|---|
| `app.rag.ingest` | `--local` | Uses local FastEmbed ONNX transformer without calling external APIs |
| `app.rag.ingest` | `--rebuild` | Drops existing vector storage and builds a fresh collection from scratch |
| `eval.run` | `--suite retrieval` | Runs only the L1 RAG retrieval evaluation dataset (`retrieval.yaml`) |
| `eval.run` | `--offline` | Forces deterministic evaluation without incurring LLM inference costs |

---

## Contributing & Authoring Workflow

When adding new menu items, updating branch details, or publishing new promotional campaigns, follow this standard workflow:

- [ ] **1. Create Branch**: Create a feature branch for your content update (`git checkout -b content/new-offer`).
- [ ] **2. Edit Synchronously**:
  - Updating a menu item? Update [`knowledge/menu/*.md`](./menu/) and `../../data/menu.json` together.
  - Adding a promo? Update [`knowledge/offers/current-offers.md`](./offers/current-offers.md) and `../../data/promos.json` together.
  - Changing hours? Update [`knowledge/branches/*.md`](./branches/) and `../../data/branches.json` together.
- [ ] **3. Update Timestamp**: Set `last_updated: YYYY-MM-DD` in the front matter of all modified `.md` files.
- [ ] **4. Run Validator**: Run `python -m app.rag.validate_kb` and verify `0 error(s)`.
- [ ] **5. Rebuild Index**: Run `python -m app.rag.ingest --local` and ensure `internal chunks indexed: 0`.
- [ ] **6. Run Retrieval Suite**: Run `python -m eval.run --suite retrieval --offline` and verify all quality gates pass.
- [ ] **7. Commit & PR**: Submit a pull request for review.

---

## Security & PII Protection

The automated validator executes regular expression pattern scans on every file in this directory to enforce strict privacy standards:
- **No Real Phone Numbers**: Only fictional sample ranges (`+94 11 000 xxxx`, `+94 81 000 xxxx`) are permitted.
- **No National Identity Card (NIC) Patterns**: Formats like `#########V` or 12-digit numbers are blocked.
- **No Email Addresses**: Plaintext email addresses are prohibited in customer-facing markdown.
- **Staff Privacy**: Employee IDs (`EMP-###`), individual shift assignments, and personal salaries reside strictly under [`internal/`](./internal/) and are blocked from customer retrieval.

---

## Disclaimer & Notice

All business entity names, employee profiles, physical outlet locations, contact telephone numbers, and individual staff rosters contained within this knowledge base are **fictional sample assets** constructed exclusively for demonstration, automated testing, and evaluation purposes.
