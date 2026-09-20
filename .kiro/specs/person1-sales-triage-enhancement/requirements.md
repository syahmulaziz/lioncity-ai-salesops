# Person 1 — Sales Triage Enhancement — Requirements

**Spec:** `person1-sales-triage-enhancement`
**Stage:** 1 — Requirements (for approval)
**Repository baseline:** `syahmulaziz/lioncity-ai-salesops` @ commit `c6ae82f` (branch `main`)

---

## 0. Purpose and Framing

This is an **enhancement** specification for the existing LionCity AI SalesOps
codebase. It is **not** a greenfield rebuild. The existing `SalesAgent`,
`TOOLS`/`execute_tool()`, WhatsApp integration, business tools, discount HITL and
SQLite data layer are the authoritative baseline and are **reused**.

The goal is to strengthen Person 1's responsibilities:

1. Agent behaviour
2. Multi-turn conversation
3. FAQ / general enquiries
4. New / guest customer handling
5. WhatsApp response quality
6. Correct tool selection

plus a new **deterministic sales-triage / priority-scoring** capability with
configurable weights and score-independent human escalation.

Each requirement below explicitly separates **EXISTING CAPABILITY** (already in
the repo) from **REQUIRED ENHANCEMENT** (new work), so that nothing already
working is rebuilt unnecessarily.

### Baseline snapshot (verified against the actual code)

| Area | State in repo today |
|---|---|
| Agent | `app/agent.py` — `SalesAgent` (one instance per phone), `self.messages` conversation memory, agent loop in `send()`, `activity_log`, discount `pending_approval` |
| Tools | 8 tools in `TOOLS` + `execute_tool()`: `find_customer`, `get_previous_orders`, `check_inventory`, `get_customer_price`, `check_delivery`, `resolve_date`, `check_discount_authority`, `create_order` |
| LLM client | `app/claude_client.py` (Anthropic) is **active**; `app/bedrock_client.py` exists but is **unused** by the agent |
| WhatsApp | `app/whatsapp_api.py` — FastAPI webhook, `customer_agents` session map, idempotency, `/process-approvals`, `/reset-demo` |
| Data | `app/database.py` — SQLite `lioncity.db`; tables: `customers` (`account_tier`), `orders`, `order_items`, `customer_prices`, `delivery_slots`, `approval_requests`, `processed_messages`, `sales_events` |
| HITL escalation | **Discount-only**, via `check_discount_authority` → `pending_approval` → `create_approval_request` → `/process-approvals` |
| Triage / scoring | **Does not exist** |
| FAQ / general enquiry | **Does not exist** |
| Product discovery / catalog listing | **Does not exist** (no "list products" tool) |
| Structured enquiry state | **Does not exist** (only free-form `self.messages`) |
| Central config | **Does not exist** (constants are inline, e.g. `AI_DISCOUNT_LIMIT = 5.0` in `tools/discount.py`) |
| Intent-first routing | **Does not exist** (every message goes straight to Claude + tools) |
| Guest / new-customer path | Only the raw `CUSTOMER_NOT_FOUND` result from `find_customer`; no guest workflow |
| Explicit "talk to a human" escalation | **Does not exist** (only discount triggers HITL) |
| Tests | Script-style (`print`/`pprint`, run manually); **no assertion-based automated suite** despite `pytest` being in `requirements.txt` |
| Seed tiers | Only `GOLD` (CUST-001) and `STANDARD` (CUST-002); no `SILVER`/`PREFERRED`; no `is_business`/customer-type column |

---

## Cross-cutting Scoring Baseline (approved)

All triage requirements below reference this single approved baseline. All
weights, thresholds and band boundaries **must be centrally configurable**
(see R7). The numbers here are the approved *defaults*.

**Customer value**
| Signal | Points |
|---|---|
| Existing customer (found account) | +1 |
| Preferred / Silver tier | +1 |
| Gold / highest tier | +2 |

**Opportunity value**
| Signal | Points |
|---|---|
| Business customer | +1 |
| Bulk quantity ≥ 20 | +2 |
| Verified value ≥ SGD 5000 | +2 |
| Quotation requested | +2 |
| Urgent | +1 |
| Discount requested | +1 |

**Priority bands**
| Total score | Band |
|---|---|
| 0–2 | `ROUTINE` |
| 3–5 | `SALES_OPPORTUNITY` |
| 6+ | `HIGH_PRIORITY` |

**Rules that constrain all scoring:**
- Customer-value subtotal and opportunity-value subtotal **must remain
  separately visible** before the total is computed.
- The **score is calculated by deterministic Python logic**, not the LLM. The
  LLM may interpret natural language into signals, but must never invent or
  decide the numeric score or band.
- Scoring must **not** be applied to every message. Non-sales intents (FAQ /
  general enquiry) must not be scored as sales opportunities (see R3, R6).

---

## R1 — Agent Behaviour

**EXISTING CAPABILITY**
- `SalesAgent.send()` runs a bounded tool-use loop (`max_iterations`, default 10),
  appends assistant/tool turns to `self.messages`, and returns a final text reply.
- `SYSTEM_PROMPT` already encodes safety rules (identity, inventory, pricing,
  delivery, discount HITL, order creation, "never claim a downstream action
  without a tool confirmation").
- `activity_log` records observable actions for the Streamlit console.

**REQUIRED ENHANCEMENT**
- The agent must classify **intent first** (sales enquiry vs FAQ/general vs
  explicit human request vs product discovery) before deciding whether triage
  scoring applies (see R2, R3, R6).
- The agent must remain safe under the existing "no unverified claims" rules
  while gaining the new capabilities; no existing safety rule may be weakened.

**Acceptance criteria**
- AC1.1 The existing agent loop, `self.messages` memory, and `activity_log`
  remain functional and are not replaced.
- AC1.2 For a message with no sales signals (pure greeting/FAQ), the agent
  produces a helpful reply **without** producing a `SALES_OPPORTUNITY` or
  `HIGH_PRIORITY` triage outcome.
- AC1.3 No existing safety rule (inventory/pricing/delivery/discount/order) is
  removed or relaxed; enhancements are additive.
- AC1.4 The agent never emits a numeric priority score that it computed itself;
  any score present in output originates from the deterministic evaluator (R3/R7).

---

## R2 — Multi-turn Conversation and Structured Enquiry State

**EXISTING CAPABILITY**
- Multi-turn continuity already works: one `SalesAgent` per phone, full history
  in `self.messages`, WhatsApp `customer_agents` map keeps the session alive
  across messages.

**REQUIRED ENHANCEMENT**
- Introduce a **structured enquiry state** that holds validated, current
  workflow facts for the active enquiry (e.g. identified customer, requested
  SKU(s), quantity, whether a quotation was requested, urgency, discount
  requested, verified value, current triage result).
- Structured state **complements** conversation history; it does not replace it.
  Conversation history provides natural-language context; structured state
  provides validated/current facts used by deterministic logic (triage, routing).
- State must update as new confirmed facts arrive across turns (e.g. a quantity
  corrected in a later message overrides the earlier one).

**Acceptance criteria**
- AC2.1 A structured enquiry-state object exists per conversation and is
  populated from tool results and interpreted message signals.
- AC2.2 `self.messages` (natural-language history) is retained unchanged in role;
  structured state is stored **alongside** it, not instead of it.
- AC2.3 When a fact changes across turns (e.g. quantity 10 → 30), the structured
  state reflects the latest confirmed value, and triage re-evaluates against it.
- AC2.4 Structured state is inspectable (e.g. for tests and the activity log)
  without calling the LLM.

---

## R3 — FAQ / General Enquiries

**EXISTING CAPABILITY**
- None. There is no FAQ path or FAQ tool. General questions currently fall
  through to the generic tool-use loop.

**REQUIRED ENHANCEMENT**
- Add an FAQ / general-enquiry path for questions such as opening hours,
  location, contact, delivery-area coverage, general policy — answerable without
  triggering sales triage.
- FAQ content must come from a controlled source (tool/config/data), not be
  invented by the LLM.

**Acceptance criteria**
- AC3.1 A recognised general/FAQ enquiry is answered via the FAQ path and is
  **not** scored as a sales opportunity.
- AC3.2 Example: a Gold customer asking "What time do you close?" is handled as
  FAQ/general enquiry and does **not** become a sales escalation merely because
  the account is valuable. (Explicit intent rule from the master spec.)
- AC3.3 FAQ answers are sourced from controlled content; the agent does not
  fabricate hours/policies not present in that source.
- AC3.4 If an enquiry mixes FAQ + a genuine sales signal, the sales portion may
  still be triaged (per R6), but a pure FAQ never is.

---

## R4 — New / Guest Customer Handling

**EXISTING CAPABILITY**
- `find_customer` returns `{"success": False, "error": "CUSTOMER_NOT_FOUND"}`
  for unknown phone numbers. There is no downstream guest workflow.

**REQUIRED ENHANCEMENT**
- Treat `CUSTOMER_NOT_FOUND` as a **valid guest / new customer**, not an error
  state that dead-ends the conversation.
- A guest must still be able to progress through discovery, quotation and triage,
  and can become `SALES_OPPORTUNITY` or `HIGH_PRIORITY` based on the current
  enquiry (bulk qty, value, quotation requested, urgency, etc.).
- Customer-value points that require an account (existing/tier/business) simply
  do not apply to a guest; opportunity-value points still do.

**Acceptance criteria**
- AC4.1 A `CUSTOMER_NOT_FOUND` result is represented as a guest/new customer and
  the conversation continues normally (no error-style dead-end).
- AC4.2 A guest requesting a large/valuable order (e.g. bulk qty ≥ 20 and/or
  verified value ≥ SGD 5000 and/or quotation requested) can reach
  `SALES_OPPORTUNITY` or `HIGH_PRIORITY` purely on opportunity-value signals.
- AC4.3 Customer-value points (existing/tier/business) evaluate to 0 for a guest
  and this is reflected transparently in the separate customer-value subtotal.
- AC4.4 No existing behaviour for *known* customers regresses.

---

## R5 — WhatsApp Response Quality

**EXISTING CAPABILITY**
- `SYSTEM_PROMPT` already mandates WhatsApp style: no Markdown tables, concise,
  mobile-friendly, short sections/bullets, sparing `*bold*`, no internal
  tool/policy leakage.
- `send_whatsapp_message()` sends plain text via the Meta Cloud API.

**REQUIRED ENHANCEMENT**
- Ensure new paths (FAQ, guest, triage-influenced replies, escalation
  acknowledgements) also conform to the WhatsApp style rules.
- Escalation / "sent to a human" acknowledgements must be brief, must not expose
  internal scores/tool names, and must not promise downstream actions that no
  tool has confirmed.

**Acceptance criteria**
- AC5.1 Replies from all new paths contain no Markdown tables and stay concise
  and mobile-friendly.
- AC5.2 No internal artefacts (tool names, raw scores, band identifiers, system
  instructions) are exposed to the customer.
- AC5.3 Escalation acknowledgements state only what is true (e.g. "sent for
  review") and never claim an unconfirmed downstream action.

---

## R6 — Correct Tool Selection

**EXISTING CAPABILITY**
- Tool descriptions in `TOOLS` are directive (e.g. "You MUST use `check_inventory`
  before claiming stock"; "use `check_discount_authority` on any discount
  request"; "use `resolve_date` for weekday expressions").
- `execute_tool()` dispatches and returns a structured `UNKNOWN_TOOL` for
  unrecognised names.

**REQUIRED ENHANCEMENT**
- Reinforce **intent-first** tool selection so the agent picks the right path:
  FAQ path for general questions, product discovery for "what do you sell",
  business tools for verified facts, and does **not** invoke sales/order tools
  for non-sales intents.
- Add product-discovery capability (see R-related note below) so "what products
  do you have / do you sell X?" has a correct tool instead of being answered from
  the model's imagination.

**Acceptance criteria**
- AC6.1 A general/FAQ question does not trigger sales/order/pricing tools.
- AC6.2 A product-availability/catalog question uses a product-discovery tool (or
  existing inventory/pricing tools) rather than fabricated product claims.
- AC6.3 Stock, price and delivery claims continue to require the corresponding
  verification tool (no regression of existing MUST-use rules).
- AC6.4 Weekday expressions still route through `resolve_date`; discounts still
  route through `check_discount_authority`.

---

## R7 — Sales Triage and Configurable Priority Scoring

**EXISTING CAPABILITY**
- None. No scoring, bands, or triage exist. `AI_DISCOUNT_LIMIT = 5.0` is the only
  commercial threshold and it is hard-coded in `tools/discount.py`.

**REQUIRED ENHANCEMENT**
- Add a **deterministic triage evaluator** (Python) that computes customer-value
  and opportunity-value subtotals, a total, and a band using the approved
  baseline above.
- Add a **central configuration** for all weights, thresholds and band
  boundaries. The existing `AI_DISCOUNT_LIMIT` should be consolidated into (or
  referenced from) this central config so commercial constants live in one place.
- The evaluator consumes the structured enquiry state (R2); it must be callable
  and testable **without** the LLM.

**Acceptance criteria**
- AC7.1 Given a structured enquiry state, the evaluator returns
  `customer_value_score`, `opportunity_value_score`, `total_score`, and `band`,
  with the two subtotals visible separately before the total.
- AC7.2 Bands map exactly: 0–2 `ROUTINE`, 3–5 `SALES_OPPORTUNITY`, 6+
  `HIGH_PRIORITY`.
- AC7.3 All weights, both thresholds (3 and 6), and band labels are read from
  central config; changing a config value changes the outcome with no evaluator
  code change.
- AC7.4 Default weights equal the approved baseline (existing +1; Silver/Preferred
  +1; Gold +2; business +1; bulk≥20 +2; value≥5000 +2; quotation +2; urgent +1;
  discount +1).
- AC7.5 The evaluator is pure/deterministic: identical input state → identical
  output, no LLM call, no randomness.
- AC7.6 The LLM never overrides or invents the score; if the LLM's interpreted
  signals feed the evaluator, only the evaluator's numeric result is authoritative.

---

## R8 — Human-Request / Score-Independent Escalation Integration

**EXISTING CAPABILITY**
- Discount escalation exists end-to-end: `check_discount_authority` →
  `pending_approval` → `create_approval_request` (SQLite) → Streamlit decision →
  `/process-approvals` → `apply_human_approval()` resumes the agent.
- `approval_requests` currently models `approval_type` (used as `'DISCOUNT'`),
  `requested_percent`, `approved_percent`, `status`.

**REQUIRED ENHANCEMENT**
- Support **explicit customer requests to speak to a human / salesperson** as an
  escalation that is **independent of the triage score** (a `ROUTINE` customer
  can still demand a human).
- Integrate this with the existing approval/escalation plumbing rather than
  building a parallel mechanism (reuse `sales_events` logging and, where it fits,
  the approval/escalation queue and Streamlit console).

**Acceptance criteria**
- AC8.1 An explicit "I want to talk to a salesperson/human" triggers escalation
  regardless of triage band (including `ROUTINE`).
- AC8.2 Human-request escalation reuses existing escalation infrastructure
  (`sales_events` and the approval/queue mechanism) rather than a new parallel
  store.
- AC8.3 The customer receives a brief, truthful acknowledgement (per R5) and no
  fabricated downstream action.
- AC8.4 Discount HITL behaviour is unchanged and does not regress.
- AC8.5 `HIGH_PRIORITY` triage may also flag for human attention, but score-based
  and explicit-request escalations are distinguishable in the logged event.

---

## R9 — Trust, Safety and Tool-Failure Behaviour

**EXISTING CAPABILITY**
- Agent wraps tool execution in `try/except`, returning a structured
  `TOOL_EXECUTION_ERROR` result to the model instead of crashing.
- Strong "never claim unverified facts / downstream actions" rules exist in
  `SYSTEM_PROMPT`. `apply_human_approval` guards against approving more than the
  customer requested (`APPROVAL_EXCEEDS_REQUEST`).

**REQUIRED ENHANCEMENT**
- New paths (triage, FAQ, product discovery, guest, human-request) must degrade
  safely on tool failure: the agent asks for clarification or acknowledges an
  inability rather than inventing data or a score.
- Triage must not fabricate signals from a failed tool (e.g. a failed
  `get_customer_price` must not produce a "verified value ≥ SGD 5000" signal).

**Acceptance criteria**
- AC9.1 When a tool returns `success: False` / raises, the agent does not assert
  the unverified fact and does not derive a triage signal from the missing data.
- AC9.2 Verified-value and stock/price/delivery signals require a successful tool
  result; otherwise the corresponding opportunity-value points are not awarded.
- AC9.3 Existing error handling and approval guards remain intact.
- AC9.4 On unrecoverable tool failure the customer gets a safe, concise message
  and (where relevant) a clarification request.

---

## R10 — Automated Testing

**EXISTING CAPABILITY**
- `tests/` contains script-style checks (`print`/`pprint`, run manually, e.g.
  `test_approval_reliability.py`, `test_business_admin.py`). `pytest` is listed in
  `requirements.txt` but there is no assertion-based suite.

**REQUIRED ENHANCEMENT**
- Add **deterministic, assertion-based automated tests** (pytest-style) for the
  new, LLM-independent logic: triage evaluator, config-driven weights/bands,
  structured enquiry state transitions, guest scoring, and intent classification
  where it is deterministic.
- Tests must run without network / LLM / live WhatsApp access.

**Acceptance criteria**
- AC10.1 Triage evaluator has tests covering: each band boundary (2/3 and 5/6),
  guest vs Gold vs Silver/Preferred, and each opportunity signal independently.
- AC10.2 Config tests prove that changing a weight/threshold changes the band
  without changing evaluator code.
- AC10.3 Structured-state tests prove last-write-wins on changed facts (AC2.3).
- AC10.4 A pure-FAQ input (e.g. "what time do you close?") is proven **not** to
  yield a sales band (AC3.1/AC3.2) at whatever layer is deterministic.
- AC10.5 The new tests are runnable via `pytest` and pass offline (no live LLM/API).
- AC10.6 Existing script-style tests are preserved (not deleted/rewritten as part
  of this requirement).

---

## Traceability Summary

| Req | Reuses (existing) | Adds (enhancement) |
|---|---|---|
| R1 | agent loop, `self.messages`, `activity_log`, `SYSTEM_PROMPT` safety | intent-first behaviour |
| R2 | one-agent-per-phone, `self.messages` | structured enquiry state alongside history |
| R3 | agent loop | FAQ/general-enquiry path + controlled content |
| R4 | `find_customer` `CUSTOMER_NOT_FOUND` | guest workflow + guest-eligible triage |
| R5 | WhatsApp style rules, `send_whatsapp_message` | style on new paths + truthful escalation acks |
| R6 | directive tool descriptions, `execute_tool` | intent-first selection + product discovery |
| R7 | (none) | deterministic evaluator + central config |
| R8 | discount HITL, `approval_requests`, `sales_events`, `/process-approvals` | explicit human-request, score-independent |
| R9 | `try/except` tool wrapping, approval guards | safe degradation for new paths/signals |
| R10 | `tests/` layout, `pytest` dependency | assertion-based offline tests |



---

## REVISION 1 — Post-implementation business-requirement change

The following supersede/extend the originally approved requirements. Unrelated
requirements above are unchanged.

### R8-REV — HIGH_PRIORITY auto-routes to human sales (supersedes prior "no auto handoff")

Previously, HIGH_PRIORITY produced no automatic handoff. This is changed:

- **ROUTINE** — AI handles normally; no automatic handoff.
- **SALES_OPPORTUNITY** — AI may keep qualifying/responding; no automatic
  handoff purely because of this band.
- **HIGH_PRIORITY** — the system automatically creates ONE human **sales**
  handoff and the customer receives a concise WhatsApp message that the enquiry
  has been referred to the sales team.
- **Explicit human request** — still creates a handoff regardless of band.

Constraints (unchanged safety):
- HIGH_PRIORITY must NOT auto-create an order.
- HIGH_PRIORITY must NOT auto-approve a discount.
- Must NOT claim a salesperson has accepted/processed the enquiry unless a
  downstream system confirms it (referral wording only).

**Idempotency (AC):** once an enquiry has generated its automatic HIGH_PRIORITY
handoff, subsequent messages/re-evaluations that remain HIGH_PRIORITY must NOT
create duplicate `HUMAN_HANDOFF_REQUESTED` events.

**Acceptance criteria**
- ACR1.1 ROUTINE / SALES_OPPORTUNITY produce no automatic handoff.
- ACR1.2 Reaching HIGH_PRIORITY creates exactly one automatic sales handoff
  (`trigger="high_priority"`), logged via `sales_events`.
- ACR1.3 Re-evaluating the same HIGH_PRIORITY enquiry creates no further handoff.
- ACR1.4 Explicit request creates a handoff at any band (`trigger="explicit_request"`).
- ACR1.5 Handoff failure does not cause a false "success" claim to the customer.
- ACR1.6 HIGH_PRIORITY never auto-creates an order or approves a discount.
- Person 3 still owns the downstream HITL/sales-console workflow.

### R11 — Quotation preview (new)

Add a customer-facing, **non-final** quotation PREVIEW for quotation requests,
built only from trusted/verified application data.

- Claude must NOT invent/independently calculate SKU, verified product name,
  unit price, subtotal, delivery charge, discount, estimated total, customer
  tier, or approval status.
- Preview may show: Product, SKU, Quantity, Unit Price, Subtotal, Delivery
  status/charge if verified, Discount status if verified, Estimated Total only
  if safely derivable from verified data, and `Status: PREVIEW`.
- Unavailable values are shown as "To be confirmed" (or omitted) — never invented.
- Must include a statement that final pricing/delivery/discounts are subject to
  confirmation. Not an official quotation/order-management subsystem.

**Acceptance criteria**
- ACR11.1 Preview uses the verified product/SKU and the customer-requested quantity.
- ACR11.2 Unit price/subtotal come from trusted pricing (`verified_subtotal`) only.
- ACR11.3 Missing/unverified fields are shown "To be confirmed", not invented.
- ACR11.4 Unapproved discount and unverified delivery are not represented as confirmed.
- ACR11.5 Customer/Claude cannot inject verified quotation values.
- ACR11.6 Preview is clearly marked PREVIEW / non-final and WhatsApp-formatted.
- ACR11.7 Preview consumes CURRENT state, so quantity/product corrections never
  surface stale amounts (ties to existing stale-data invalidation).
