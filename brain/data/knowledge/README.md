# Knowledge Base: Pizza Hut Outlet (SAMPLE DATA)

All names, addresses, phone numbers, and staff are **fictional sample data**. Replace with real data before use.

## Folder map

| Folder | Audience | Indexed for customer bot? | Contents |
|---|---|---|---|
| `company/` | Customer | Yes | About us, service standards |
| `branches/` | Customer | Yes | Branch directory, one file per branch (address, hours, delivery area) |
| `menu/` | Customer | Yes | Pizzas, sides, desserts, drinks, customization, allergens |
| `offers/` | Customer | Yes | Current offers, expired offers, loyalty program |
| `policies/` | Customer | Yes | Ordering, payment, refunds, cancellation, privacy, food safety, complaints |
| `faq/` | Customer | Yes | Quick answers |
| `internal/` | Staff only | **NO** | Employee directory, roles, HR rules, bot escalation rules |

## Authoring rules (important for RAG)

1. Every file starts with a small YAML front matter block (`audience`, `last_updated`). The ingest script must **strip it** and store `audience` and the folder name as chunk metadata.
2. Chunking: **one `## ` section = one chunk.** Each section must make sense on its own, so the item/branch/policy name is repeated inside the section.
3. **Currency & Prices in menu files.** Prices and currency details are maintained in Sri Lankan Rupees (LKR) inside the menu knowledge documents.
4. Offer rules (codes, minimum spend, valid days) must match `brain/data/promos.json`. If they disagree, the JSON wins; fix the markdown.
5. `internal/` must never be indexed into the customer-facing collection. A future staff assistant must use a **separate collection with authentication**.
6. Update `last_updated` whenever a file changes, then re-run `python -m app.rag.ingest --rebuild`.
