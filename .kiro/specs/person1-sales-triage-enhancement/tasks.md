# Person 1 — Sales Triage Enhancement — Tasks

**Spec:** `person1-sales-triage-enhancement`
**Stage:** 3 — Tasks (for approval)
**Repository baseline:** `syahmulaziz/lioncity-ai-salesops` @ commit `c6ae82f` (branch `main`)
**Requirements:** approved (R1–R10)
**Design:** approved (§1–26) with Stage-3 Decisions 1–6 + trust-model requirement

---

## 0. Trust Model (applies to every task)

All tasks must respect the three source-of-truth categories. Nothing may move
from A → B or A → C without verification/calculation.

| Cat | Name | Examples | Set by |
|---|---|---|---|
| **A** | Customer-supplied / interpreted | `product_query`, `quantity`, `business_customer`, `company_name`, `quotation_requested`, `urgent`, `discount_requested`, `current_intent`, `human_requested` | LLM proposes → **Python validates** in `update_enquiry_signals` |
| **B** | Verified business | `customer_id`, `existing_customer`, `customer_tier`, verified SKU/identity, inventory, verified price/`verified_subtotal`, delivery availability/fee, discount authority | **Trusted business tools only** |
| **C** | Derived application | `customer_value_score`, `opportunity_value_score`, `total_priority_score`, `priority_band`, `priority_reasons` | **Deterministic Python only** (`triage.py`) |

**Hard rule enforced across tasks:** the LLM signal mechanism must reject/ignore
any attempt to set B or C fields (Task 3 + Task 20 prove this). `HIGH_PRIORITY`
is an internal classification only — it never implies order/quote/discount
approval or customer acceptance.

---

# FOUNDATION

## Task 1 — Triage configuration
- **PURPOSE:** Central, editable weights/thresholds/bands for triage; keep it
  separate from discount policy.
- **REQUIREMENTS:** R7 (AC7.3, AC7.4); Decision 4.
- **DESIGN REFERENCES:** §13; Cat C.
- **FILES TO CREATE:** `app/triage_config.py`
- **FILES TO MODIFY:** none.
- **DEPENDENCIES:** none.
- **IMPLEMENTATION SCOPE:**
  - `TriageConfig` (dataclass or module constants) with: customer-value weights
    (`existing_customer=1`, tier map `GOLD=2, SILVER=1, PREFERRED=1, STANDARD=0`),
    opportunity weights (`business_customer=1, bulk_quantity=2, verified_value=2,
    quotation_requested=2, urgent=1, discount_requested=1`),
    `bulk_quantity_threshold=20`, `value_threshold_sgd=5000`,
    band thresholds (`sales_opportunity_min=3`, `high_priority_min=6`),
    band labels (`ROUTINE`/`SALES_OPPORTUNITY`/`HIGH_PRIORITY`).
  - Helper `tier_points(tier)` returning 0 for unknown/unmapped/None tiers.
- **OUT OF SCOPE:** discount authority (`AI_DISCOUNT_LIMIT` stays in
  `tools/discount.py`); any DB/seed change for SILVER/PREFERRED.
- **COMPLETION CRITERIA:** all weights/thresholds/labels readable from one place;
  unknown tier → 0; module imports with no side effects.
- **TESTS / VERIFICATION:** covered by Task 14 (config-driven change) + Task 15’s
  tier cases.

## Task 2 — EnquiryState model
- **PURPOSE:** Structured, validated per-conversation state that complements
  `self.messages`.
- **REQUIREMENTS:** R2 (AC2.1, AC2.2, AC2.4); Decision 2; trust-model A/B/C.
- **DESIGN REFERENCES:** §4, §5; Cat A + B fields (C stored as a result object).
- **FILES TO CREATE:** `app/enquiry_state.py`
- **FILES TO MODIFY:** none.
- **DEPENDENCIES:** none.
- **IMPLEMENTATION SCOPE:**
  - `EnquiryState` dataclass with A fields (`product_query`, `quantity`,
    `business_customer` default `None`, `company_name`, `quotation_requested`,
    `urgent`, `discount_requested`, `current_intent`, `human_requested`) and B
    fields (`customer_found`/`existing_customer`, `customer_id`, `account_tier`,
    verified `product_sku`/`product_name`, `verified_subtotal`,
    `verified_value_sgd`, `value_is_verified`).
  - A `last_triage` slot (Cat C result object) — populated only by triage.
  - Trusted setters for B fields (`set_customer_from_tool(result)`,
    `set_verified_product(result)`, `set_verified_value(result)`) that accept
    only **successful** tool results.
  - `business_customer` null-semantics: starts `None`, never auto-`False`.
- **OUT OF SCOPE:** validation of A candidates (Task 3); scoring (Task 4);
  persistence across restarts (documented out of P0, §Design Clarification 3).
- **COMPLETION CRITERIA:** state instantiable with safe defaults; B setters reject
  unsuccessful tool results; inspectable without LLM.
- **TESTS / VERIFICATION:** Task 13.

## Task 3 — Enquiry-signal validation / update mechanism
- **PURPOSE:** The single strict boundary that turns LLM candidate signals (Cat A)
  into validated `EnquiryState`, while rejecting B/C fields.
- **REQUIREMENTS:** R2 (AC2.3); Decision 2; trust-model (A→validate; block A→B/C).
- **DESIGN REFERENCES:** §6, §7; Cat A trust boundary.
- **FILES TO MODIFY:** `app/enquiry_state.py` (add `apply_candidate`).
- **FILES TO CREATE:** none (kept with the state it mutates).
- **DEPENDENCIES:** Task 2.
- **IMPLEMENTATION SCOPE:**
  - `apply_candidate(candidate: dict) -> dict` (returns accepted/ignored report).
  - **Allow-list only** the A fields listed in Cat A. Any other key (incl.
    `customer_id`, `existing_customer`, `customer_tier`, `verified_subtotal`,
    `priority_band`, scores) is **ignored/rejected** and reported.
  - Type/range/enum validation: `quantity` positive int; booleans are booleans;
    `company_name` non-empty string; `current_intent` in an allowed set;
    malformed fields dropped (valid ones still applied).
  - Correction/replacement = last-write-wins per field.
  - Precedence (Decision 2): explicit personal-use sets `business_customer=False`
    even after an earlier company mention; explicit company/company-purpose sets
    `True`; absence leaves `None`.
  - Cancellation semantics: `quotation_requested=False` (and other booleans) can
    be turned off by a later explicit statement.
- **OUT OF SCOPE:** setting any B/C field; deriving verified value.
- **COMPLETION CRITERIA:** only A fields mutate state; B/C keys rejected & reported;
  last-write-wins + precedence + cancellation behave per rules.
- **TESTS / VERIFICATION:** Task 13, Task 18, Task 20 (rejection of B/C).

## Task 4 — Deterministic triage evaluator
- **PURPOSE:** Pure Python scoring producing scores, band, and reasons (Cat C).
- **REQUIREMENTS:** R7 (AC7.1, AC7.2, AC7.5, AC7.6).
- **DESIGN REFERENCES:** §14, §15; Cat C.
- **FILES TO CREATE:** `app/triage.py`
- **FILES TO MODIFY:** none.
- **DEPENDENCIES:** Task 1, Task 2 (+ Task 3 for realistic inputs, but evaluator
  only reads state).
- **IMPLEMENTATION SCOPE:**
  - `TriageResult` (customer_value_score, opportunity_value_score,
    total_priority_score, priority_band, priority_reasons).
  - `evaluate(state, config) -> TriageResult`: pure, side-effect free, no LLM.
  - Customer-value: existing(+1), tier via `config.tier_points`.
  - Opportunity: `business_customer is True`(+1), `quantity>=threshold`(+2),
    `value_is_verified and verified_value_sgd>=threshold`(+2),
    `quotation_requested`(+2), `urgent`(+1), `discount_requested`(+1).
  - Subtotals kept separately visible; band from total via config thresholds;
    `priority_reasons` explainable list.
- **OUT OF SCOPE:** deciding when to evaluate (Task 7/9); routing.
- **COMPLETION CRITERIA:** deterministic; subtotals separate; bands exact.
- **TESTS / VERIFICATION:** Task 14 (incl. mandatory 2/3/5/6 boundaries).

---

# TRUSTED INFORMATION

## Task 5 — FAQ data + provider/tool
- **PURPOSE:** Controlled static FAQ lookup; no invented business facts.
- **REQUIREMENTS:** R3 (AC3.1, AC3.3); Decision 4 (placeholders); R9.
- **DESIGN REFERENCES:** §9; Cat B (controlled data).
- **FILES TO CREATE:** `app/data/faq.json`, `app/tools/faq.py`
- **FILES TO MODIFY:** none (tool registered later in Task 9/10).
- **DEPENDENCIES:** none.
- **IMPLEMENTATION SCOPE:**
  - `faq.json` topics: `operating_hours`, `location`, `payment_methods`,
    `delivery_policy`, `quotation_process`, `contact_info`, `company_info`.
  - Each value carries a **confirmed** flag (or clearly-marked
    `"UNCONFIRMED — ..."` sentinel) so unconfirmed values are distinguishable.
  - `lookup_faq(topic)`:
    - confirmed value → return it;
    - unconfirmed/missing → `{"success": False, "error":
      "FAQ_UNCONFIRMED"|"FAQ_TOPIC_NOT_FOUND"}` (agent then responds safely, never
      sends placeholder text as fact — Decision 4).
- **OUT OF SCOPE:** RAG/embeddings/DB; real business values (team supplies later).
- **COMPLETION CRITERIA:** confirmed topics return text; unconfirmed never returned
  as a real fact.
- **TESTS / VERIFICATION:** Task 15.

## Task 6 — Product discovery
- **PURPOSE:** Map customer product language to a **verified** SKU without
  invention.
- **REQUIREMENTS:** R6 (AC6.2); Decision 3; R9.
- **DESIGN REFERENCES:** §11; Cat B.
- **FILES TO CREATE:** `app/tools/products.py`
- **FILES TO MODIFY:** none.
- **DEPENDENCIES:** none (reads existing `products` table).
- **IMPLEMENTATION SCOPE:**
  - `find_product(query)`: case-insensitive match over existing fields (SKU,
    name, description, category via `LIKE`).
    - exactly one clear match → return verified `{sku, product_name, category}`;
    - multiple plausible → return list → agent asks concise clarification;
    - none → `{"success": False, "error": "PRODUCT_NOT_FOUND"}`.
  - Optional `list_products()` → catalog names/categories (no stock).
  - Never returns a fabricated SKU.
- **OUT OF SCOPE:** search infra/embeddings; schema change; stock/price (existing
  `check_inventory`/`get_customer_price` used after SKU is known).
- **COMPLETION CRITERIA:** single/multi/none behaviours correct against seed data.
- **TESTS / VERIFICATION:** Task 16.

---

# AGENT INTEGRATION

## Task 7 — Integrate EnquiryState + triage post-step into SalesAgent
- **PURPOSE:** Wire state + evaluator into the agent without changing the loop.
- **REQUIREMENTS:** R1 (AC1.1, AC1.4), R2, R7.
- **DESIGN REFERENCES:** §2, §3, §16; Cat B ingestion + Cat C output.
- **FILES TO MODIFY:** `app/agent.py`
- **DEPENDENCIES:** Tasks 2, 3, 4.
- **IMPLEMENTATION SCOPE:**
  - Add `self.enquiry = EnquiryState()` and `self.last_triage = None` in
    `__init__`.
  - In `execute_tool()`, after **successful** trusted tools, ingest into B fields
    (`find_customer`→identity/tier/existing; `find_product`→verified SKU;
    `get_customer_price`→`verified_subtotal`/`verified_value_sgd` +
    `value_is_verified=True`). Failures ingest nothing.
  - Register `update_enquiry_signals` dispatch → `self.enquiry.apply_candidate`.
  - Add `_evaluate_triage()` post-step in `send()` (after final text) that runs
    only for sales intents (Task 9 supplies intent); stores `TriageResult` to
    `self.enquiry.last_triage`/`self.last_triage`; logs `activity_log` +
    `log_sales_event("PRIORITY_EVALUATED", ...)`.
  - Discount `pending_approval` path and `apply_human_approval` UNCHANGED.
- **OUT OF SCOPE:** intent rules (Task 9); handoff (Task 11); prompt wording for
  tool selection (Tasks 9/10/12).
- **COMPLETION CRITERIA:** state populates from trusted tools; triage stored
  internally; existing loop/discount behaviour intact; nothing triage-related
  leaks to customer text (Decision 1/5).
- **TESTS / VERIFICATION:** Task 21 (mocked end-to-end).

## Task 8 — Guest / new-customer handling
- **PURPOSE:** Treat `CUSTOMER_NOT_FOUND` as a valid guest, not a dead-end.
- **REQUIREMENTS:** R4 (AC4.1–AC4.4).
- **DESIGN REFERENCES:** §10; Cat B (absent identity) + Cat A (guest signals).
- **FILES TO MODIFY:** `app/agent.py` (identity ingestion branch), `SYSTEM_PROMPT`
  (guest guidance, additive).
- **DEPENDENCIES:** Task 7.
- **IMPLEMENTATION SCOPE:**
  - On `CUSTOMER_NOT_FOUND`: `customer_found=False`, `customer_id=None`,
    `account_tier=None`; conversation continues normally.
  - Ensure guest still accrues opportunity signals and can reach
    `SALES_OPPORTUNITY`/`HIGH_PRIORITY`; customer-value stays 0.
- **OUT OF SCOPE:** creating guest records in DB.
- **COMPLETION CRITERIA:** guest flows continue; guest can escalate on
  opportunity-only signals; known customers unaffected.
- **TESTS / VERIFICATION:** Task 17.

## Task 9 — Intent-first agent behaviour
- **PURPOSE:** Decide FAQ vs product-discovery vs sales vs human-request; ensure
  FAQ never triggers triage/handoff on customer-value alone.
- **REQUIREMENTS:** R1 (AC1.2), R3 (AC3.2, AC3.4), R6; Decision 6; FAQ/priority
  rule.
- **DESIGN REFERENCES:** §8, §16; Cat A `current_intent`.
- **FILES TO CREATE:** `app/intent.py`
- **FILES TO MODIFY:** `app/agent.py` (call intent in `_evaluate_triage` gate),
  `SYSTEM_PROMPT` (additive: use `lookup_faq` for general questions; set
  `current_intent`).
- **DEPENDENCIES:** Tasks 5, 7 (+ Task 3 for `current_intent`).
- **IMPLEMENTATION SCOPE:**
  - Lightweight deterministic classifier from tools invoked + `EnquiryState`
    (+ keyword fallback), categories `FAQ_GENERAL`, `PRODUCT_DISCOVERY`,
    `SALES_ENQUIRY`, `HUMAN_REQUEST`. No ML classifier (Decision 6).
  - Gate: triage runs only for `SALES_ENQUIRY` (or `PRODUCT_DISCOVERY` that has
    opportunity signals). `FAQ_GENERAL`/pure `HUMAN_REQUEST` → **no triage**.
- **OUT OF SCOPE:** large intent subsystem.
- **COMPLETION CRITERIA:** Gold+FAQ answered as FAQ with no triage/handoff (AC3.2).
- **TESTS / VERIFICATION:** Task 19 (+ mandatory Gold+FAQ, Task 21).

## Task 10 — Correct tool-selection behaviour
- **PURPOSE:** Reinforce right-tool routing; no sales/order tools for non-sales
  intents; product questions use discovery not imagination.
- **REQUIREMENTS:** R6 (AC6.1, AC6.3, AC6.4).
- **DESIGN REFERENCES:** §12.
- **FILES TO MODIFY:** `app/agent.py` (`TOOLS` add `find_product`/`list_products`
  + `lookup_faq` schemas; `execute_tool` dispatch), `SYSTEM_PROMPT` (additive
  selection guidance).
- **DEPENDENCIES:** Tasks 5, 6, 9.
- **IMPLEMENTATION SCOPE:** register the new tools; keep existing MUST-use rules
  (inventory/pricing/delivery/date/discount) verbatim; add guidance to prefer
  `find_product` for product questions and `lookup_faq` for general questions.
- **OUT OF SCOPE:** changing existing tool implementations.
- **COMPLETION CRITERIA:** general Q → no sales tools; product Q → discovery;
  existing MUST-use rules intact.
- **TESTS / VERIFICATION:** Task 19.

## Task 11 — Explicit human-request / handoff behaviour
- **PURPOSE:** Score-independent handoff to a salesperson; separate from
  discount approvals.
- **REQUIREMENTS:** R8 (AC8.1–AC8.5); Decision 3.
- **DESIGN REFERENCES:** §17; Cat B context, `sales_events` reuse.
- **FILES TO CREATE:** `app/handoff.py`
- **FILES TO MODIFY:** `app/agent.py` (`TOOLS` add `request_human_handoff`;
  dispatch), `SYSTEM_PROMPT` (additive: detect explicit handoff → call tool,
  brief truthful ack).
- **DEPENDENCIES:** Task 7.
- **IMPLEMENTATION SCOPE:**
  - `handoff.record_handoff(phone, enquiry_context, trigger)`: builds validated
    context from `EnquiryState` (not raw LLM text); calls
    `log_sales_event("HUMAN_HANDOFF_REQUESTED", ...)`; returns success.
  - Works at any band (incl. `ROUTINE`). Distinct event type from any
    `HIGH_PRIORITY` triage marker (AC8.5).
  - Sets `EnquiryState.human_requested=True` via validated candidate.
- **OUT OF SCOPE:** reusing `approval_requests`; console redesign; new handoff
  DB table (leave clean integration seam per Decision 3/5).
- **COMPLETION CRITERIA:** explicit request logs handoff regardless of score;
  discount HITL untouched; truthful ack, no fabricated downstream action.
- **TESTS / VERIFICATION:** Task 21 (handoff-at-ROUTINE scenario).

## Task 12 — WhatsApp response-quality rules
- **PURPOSE:** Ensure new paths obey WhatsApp style and never leak internal
  triage/tool info.
- **REQUIREMENTS:** R5 (AC5.1–AC5.3); Decision 1/5; FAQ/priority rule.
- **DESIGN REFERENCES:** §20; Cat C stays internal.
- **FILES TO MODIFY:** `app/agent.py` (`SYSTEM_PROMPT` additive rules only).
- **DEPENDENCIES:** Tasks 9, 10, 11.
- **IMPLEMENTATION SCOPE:** extend style rules to FAQ/guest/handoff/triage-adjacent
  replies; explicitly forbid exposing band/score/reasons/tool names; escalation
  acks brief + truthful; `HIGH_PRIORITY` never implies order/quote/discount
  approval in wording.
- **OUT OF SCOPE:** `send_whatsapp_message` changes; Streamlit.
- **COMPLETION CRITERIA:** no internal artefacts in any customer-facing reply.
- **TESTS / VERIFICATION:** asserted where deterministic in Task 21 (response must
  not contain band/score strings).

---

# TESTING (pytest, offline, assertion-based; existing script tests preserved)

## Task 13 — Unit tests: EnquiryState + validation boundary
- **PURPOSE:** Prove Cat A validation and null semantics.
- **REQUIREMENTS:** R2, R10 (AC10.3); Decision 2; trust-model.
- **FILES TO CREATE:** `tests/test_enquiry_state.py`
- **DEPENDENCIES:** Tasks 2, 3.
- **SCOPE / CASES:** defaults (`business_customer=None`); last-write-wins quantity;
  quotation cancellation (`"I don't need a quotation anymore."` → `False`);
  business/personal-use correction & precedence; malformed candidate dropped;
  customer-provided fake stock in a signal → ignored (not a trusted field).
- **COMPLETION / VERIFICATION:** all cases pass offline.

## Task 14 — Unit tests: triage scoring + boundaries + config
- **PURPOSE:** Prove exact bands and config-driven behaviour.
- **REQUIREMENTS:** R7, R10 (AC10.1, AC10.2).
- **FILES TO CREATE:** `tests/test_triage.py`, `tests/test_triage_config.py`
- **DEPENDENCIES:** Tasks 1, 4.
- **SCOPE / CASES (mandatory):** total **2 → ROUTINE**, **3 → SALES_OPPORTUNITY**,
  **5 → SALES_OPPORTUNITY**, **6 → HIGH_PRIORITY**; each opportunity signal
  independently; customer-value: existing(+1), GOLD(+2), SILVER/PREFERRED(+1 via
  config), STANDARD(0), unknown tier(0); subtotals visible separately; changing a
  weight/threshold in config changes band with no evaluator code change.
- **COMPLETION / VERIFICATION:** all pass offline.

## Task 15 — Tests: FAQ
- **PURPOSE:** Confirmed vs unconfirmed FAQ behaviour.
- **REQUIREMENTS:** R3, R9, R10; Decision 4.
- **FILES TO CREATE:** `tests/test_faq.py`
- **DEPENDENCIES:** Task 5.
- **SCOPE / CASES:** confirmed topic returns text; **unconfirmed FAQ → no invented
  business fact** (returns failure sentinel, not placeholder-as-fact); unknown
  topic → not found.

## Task 16 — Tests: product discovery
- **PURPOSE:** single/multi/none matching; no invented SKU.
- **REQUIREMENTS:** R6, R9, R10; Decision 3.
- **FILES TO CREATE:** `tests/test_products.py`
- **DEPENDENCIES:** Task 6.
- **SCOPE / CASES:** exact single match → verified SKU; **ambiguous → clarification
  list**; **unknown product → no invented SKU** (PRODUCT_NOT_FOUND).

## Task 17 — Tests: guest / new-customer
- **PURPOSE:** guest handling + guest escalation.
- **REQUIREMENTS:** R4, R10.
- **FILES TO CREATE:** `tests/test_guest_customer.py`
- **DEPENDENCIES:** Tasks 4, 8.
- **SCOPE / CASES:** `new customer + routine enquiry → safe guest handling`
  (ROUTINE, cv=0); `new business customer + bulk + quote + urgent → HIGH_PRIORITY`
  (ov=6, cv=0).

## Task 18 — Tests: multi-turn accumulation + corrections
- **PURPOSE:** state accumulation and corrections re-triage correctly.
- **REQUIREMENTS:** R2, R7, R10.
- **FILES TO CREATE:** `tests/test_multiturn.py`
- **DEPENDENCIES:** Tasks 3, 4.
- **SCOPE / CASES:** multi-turn state accumulation (Product A → 30 units → ABC
  Construction → quotation urgently → band rises to HIGH_PRIORITY);
  **quantity correction** ("Actually make that 50"); **business/personal-use
  correction**; **quotation cancellation** lowers score.

## Task 19 — Tests: intent + tool-selection
- **PURPOSE:** FAQ-not-triaged; correct routing.
- **REQUIREMENTS:** R1, R3, R6, R10.
- **FILES TO CREATE:** `tests/test_intent.py`
- **DEPENDENCIES:** Tasks 9, 10.
- **SCOPE / CASES:** pure FAQ (incl. **Gold customer + FAQ**) classified
  `FAQ_GENERAL` and **not** triaged/handed-off; product question routes to
  discovery; sales signals route to `SALES_ENQUIRY`.

## Task 20 — Tests: trust boundary + tool-failure
- **PURPOSE:** Prove A/B/C enforcement and safe degradation.
- **REQUIREMENTS:** R9, R10; trust-model.
- **FILES TO CREATE:** `tests/test_trust_boundary.py`
- **DEPENDENCIES:** Tasks 3, 7.
- **SCOPE / CASES (mandatory):**
  - **LLM attempt to set `customer_tier` → rejected** (state unchanged).
  - **LLM attempt to set `verified_subtotal` → rejected.**
  - **LLM attempt to set `priority_band` → rejected.**
  - **customer-provided fake stock → ignored as trusted data.**
  - **inventory failure → no invented stock**; **pricing failure → no invented
    price** and no `value_is_verified` → no value point.
- **VERIFICATION:** assertions on `EnquiryState` + evaluator output.

## Task 21 — End-to-end mocked SalesAgent scenarios
- **PURPOSE:** Wire-level behaviour with a **mocked Claude client** (offline), no
  live LLM/WhatsApp/network.
- **REQUIREMENTS:** R1, R5, R8, R10 (AC10.5).
- **FILES TO CREATE:** `tests/test_agent_scenarios.py`
- **DEPENDENCIES:** Tasks 7–12.
- **SCOPE / CASES (mandatory):**
  - Gold customer + FAQ → automated FAQ response, no triage/handoff, **no
    band/score string in reply text**.
  - **explicit salesperson request → handoff regardless of score** (ROUTINE).
  - **10% discount → existing HITL remains independent of triage** (discount path
    unchanged; `discount_requested` still adds its point).
  - **HIGH_PRIORITY → does NOT create an order automatically** (no `create_order`
    call from triage).
  - guest bulk/quote/urgent → HIGH_PRIORITY internally, normal customer reply.
- **VERIFICATION:** mock returns scripted `tool_use`/text; assert tool calls,
  `sales_events`, `EnquiryState`, and reply hygiene.

---

## Task → Requirement → Mandatory-Case Coverage Map

| Mandatory case | Task(s) |
|---|---|
| score 2→ROUTINE, 3→SALES_OPPORTUNITY, 5→SALES_OPPORTUNITY, 6→HIGH_PRIORITY | 14 |
| Gold + FAQ → automated FAQ response | 19, 21 |
| new customer + routine → safe guest handling | 17 |
| new business + bulk + quote + urgent → HIGH_PRIORITY | 17 |
| multi-turn accumulation | 18 |
| quantity correction | 18 |
| business/personal-use correction | 13, 18 |
| quotation cancellation | 13, 18 |
| ambiguous product → clarification | 16 |
| unknown product → no invented SKU | 16 |
| unconfirmed FAQ → no invented fact | 15 |
| inventory failure → no invented stock | 20 |
| pricing failure → no invented price | 20 |
| customer-provided fake stock → ignored | 13, 20 |
| LLM set customer_tier → rejected | 20 |
| LLM set verified_subtotal → rejected | 20 |
| LLM set priority_band → rejected | 20 |
| explicit salesperson request → handoff regardless of score | 11, 21 |
| 10% discount → HITL independent of triage | 21 |
| HIGH_PRIORITY → no automatic order | 21 |

---

## Proposed Implementation Batches (for Stage 4, one at a time, stop+report after each)

- **Batch 1 — Foundation:** Tasks 1–4 (+ unit tests 13, 14). No agent wiring yet.
- **Batch 2 — Trusted information:** Tasks 5, 6 (+ tests 15, 16).
- **Batch 3 — Agent integration core:** Tasks 7, 8 (+ test 17).
- **Batch 4 — Intent, tools, handoff, WhatsApp:** Tasks 9, 10, 11, 12
  (+ tests 18, 19).
- **Batch 5 — Trust + end-to-end:** Tasks 20, 21; full suite run.

---

## Files Summary

**To create (new):**
`app/triage_config.py`, `app/enquiry_state.py`, `app/triage.py`, `app/intent.py`,
`app/handoff.py`, `app/tools/faq.py`, `app/tools/products.py`, `app/data/faq.json`,
`tests/test_enquiry_state.py`, `tests/test_triage.py`, `tests/test_triage_config.py`,
`tests/test_faq.py`, `tests/test_products.py`, `tests/test_guest_customer.py`,
`tests/test_multiturn.py`, `tests/test_intent.py`, `tests/test_trust_boundary.py`,
`tests/test_agent_scenarios.py`.

**To modify (existing):**
`app/agent.py` (state field, new tool schemas + dispatch, triage post-step,
additive `SYSTEM_PROMPT`).
*Possibly minimal:* `app/whatsapp_api.py` — only if implementation proves a very
small integration change strictly necessary (Decision 1); default is no change.

**Deliberately unchanged:**
`app/claude_client.py`, `app/bedrock_client.py`, `app/tools/discount.py`
(incl. `AI_DISCOUNT_LIMIT`), `app/tools/{customer,orders,inventory,pricing,`
`delivery,date_tools,order_creation}.py`, `app/database.py` schema & seed,
`data/lioncity.db`, `streamlit_app.py`, all existing `tests/*.py` script files.



---

## REVISION 1 — Corrective/enhancement tasks (post-commit 37c4332, pre-push)

### Task R1 — HIGH_PRIORITY automatic sales handoff (idempotent)
- **PURPOSE:** HIGH_PRIORITY auto-routes to human sales, once per enquiry.
- **REQUIREMENTS:** R8-REV (ACR1.1–ACR1.6).
- **FILES:** `app/agent.py` (`__init__` flag, `_create_handoff` helper,
  `_evaluate_triage` trigger). Reuses `app/handoff.py`.
- **SCOPE:** shared handoff helper; idempotency via `_auto_handoff_done`;
  `trigger="high_priority"` vs `"explicit_request"`; referral-only wording.
- **OUT OF SCOPE:** downstream HITL/console (Person 3); order/discount changes.
- **COMPLETION:** ROUTINE/SALES_OPPORTUNITY no auto-handoff; HIGH_PRIORITY one
  handoff; no duplicates; explicit request still works; no order/approval.
- **TESTS:** Gate 1 (`tests/test_revision_handoff.py`).

### Task R2 — Quotation preview
- **PURPOSE:** non-final quotation PREVIEW from trusted/current data.
- **REQUIREMENTS:** R11 (ACR11.1–ACR11.7).
- **FILES:** new `app/quotation.py`; `app/agent.py` (tool schema + dispatch +
  prompt).
- **SCOPE:** read current EnquiryState only; TBC for unverified; PREVIEW marker;
  WhatsApp format; unit price derived only from verified_subtotal/quantity.
- **OUT OF SCOPE:** official quotation/order subsystem; applying discount/delivery.
- **COMPLETION:** verified product/qty/price used; nothing invented; stale-safe.
- **TESTS:** Gate 2 (`tests/test_quotation_preview.py`).

### Task R3 — Combined/multi-turn + regression
- **PURPOSE:** prove quotation + HIGH_PRIORITY handoff together; stale-safety;
  no duplicate handoff; guest high-value works.
- **TESTS:** Gate 3 (`tests/test_revision_combined.py`) + full regression (>156).

### Docs
- Updated `requirements.md`, `design.md`, `tasks.md` (this revision section).
