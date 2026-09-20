# Person 1 — Sales Triage Enhancement — Design

**Spec:** `person1-sales-triage-enhancement`
**Stage:** 2 — Design (for approval)
**Repository baseline:** `syahmulaziz/lioncity-ai-salesops` @ commit `c6ae82f` (branch `main`)
**Requirements:** `.kiro/specs/person1-sales-triage-enhancement/requirements.md` (approved with Decisions 1–5 + Clarifications 1–7)

---

## 0. Design Principles (from approved decisions)

1. **Targeted enhancement, not replacement.** The existing `SalesAgent`,
   `TOOLS`/`execute_tool()`, WhatsApp integration, discount HITL, and SQLite
   layer are reused as-is wherever possible.
2. **Deterministic triage in Python.** The LLM only *interprets* language into
   candidate signals; Python validates state and computes all scores/bands.
3. **Structured state complements history.** `SalesAgent.messages` is kept.
   `EnquiryState` is added alongside it (Clarification 1).
4. **Separation of concerns.** Triage config (weights/thresholds/bands) is
   **separate** from discount policy (`AI_DISCOUNT_LIMIT`) (Decision 4).
   Human handoff is **separate** from `approval_requests` (Decision 3).
5. **No invented data.** FAQ uses a small static file with clearly-marked
   placeholders where real LionCity values are unknown (Decision 5).
6. **Every new module is justified** below with a "why not an existing module?"
   answer.
7. **Session-scoped state.** `EnquiryState` lives in the per-phone `SalesAgent`
   instance; cross-restart persistence is explicitly out of P0 scope
   (Clarification 3) — documented, not engineered.

---

## 1. Existing End-to-End Flow (as it works today)

```
WhatsApp (Meta Cloud API)
        │  POST /webhook
        ▼
app/whatsapp_api.py : receive_webhook()
   • parse Meta payload, idempotency (processed_messages)
   • text-only, extract sender + body
   • log_sales_event(CUSTOMER_MESSAGE)
   • agent = get_customer_agent(sender)     ← customer_agents[phone] : SalesAgent
        │
        ▼
app/agent.py : SalesAgent.send(customer_message)
   • append user turn to self.messages
   • LOOP (max_iterations):
       response = Claude(messages, TOOLS, SYSTEM_PROMPT)
       if stop_reason != tool_use: return final text
       else: for each tool_use block:
              execute_tool(name, input)  → app/tools/*
              (special-case: check_discount_authority → self.pending_approval)
              append tool_result to self.messages
        │
        ▼
back in whatsapp_api:
   • if agent.pending_approval: create_approval_request(...) + log HUMAN_APPROVAL_REQUIRED
   • send_whatsapp_message(reply)
   • mark_message_processed(message_id)

Human decision (Streamlit) → approval_requests row (APPROVED)
        │  POST /process-approvals
        ▼
   agent.apply_human_approval(approved_percent) → _continue_after_human_action()
   → send_whatsapp_message(revised offer)
```

**Key facts preserved by this design:**
- One `SalesAgent` per phone in `customer_agents` (session memory).
- Full conversation is in `self.messages`.
- Discount is the *only* existing escalation; it flows through
  `approval_requests` + `/process-approvals`.

---

## 2. Proposed Enhanced End-to-End Flow

The enhancement inserts an **intent-first pre-step** and a **deterministic
triage post-step** around the existing Claude tool-loop. The Claude loop itself
is largely unchanged; it gains a few new tools and a light instruction to emit
structured signals.

```
WhatsApp → whatsapp_api.receive_webhook()            (UNCHANGED plumbing)
        ▼
SalesAgent.send(customer_message)
   1. append user turn to self.messages              (UNCHANGED)
   2. run Claude tool-loop                            (existing loop + new tools)
        • existing business tools (find_customer, inventory, pricing, ...)
        • NEW tools: lookup_faq, list_products/find_product,
                     update_enquiry_signals, request_human_handoff
        • Claude interprets language → calls update_enquiry_signals(...)
          with CANDIDATE signals (qty, quotation_requested, urgent,
          discount_requested, business_customer, product interest)
        • Python validates candidate signals → EnquiryState              (§6)
   3. after loop, DETERMINISTIC post-step (Python):                      (§14)
        • intent = classify(EnquiryState, signals)                       (§8)
        • if intent is FAQ/general only → NO triage                      (§9, R3)
        • else → triage.evaluate(EnquiryState, TriageConfig)
                 → customer_value_score, opportunity_value_score,
                   total_priority_score, priority_band, priority_reasons
        • store triage result on EnquiryState + activity_log + sales_events
        • if band == HIGH_PRIORITY → flag (score-based) for human attention
   4. if explicit human request detected → request_human_handoff()       (§17)
   5. return final WhatsApp-styled text                                  (§20)
        ▼
whatsapp_api: discount HITL unchanged; send reply; mark processed
```

**Important:** triage is a *Python post-step on validated state*, not a thing the
LLM decides. FAQ/general intents skip triage entirely (Clarification 4).

---

## 3. SalesAgent Changes

`app/agent.py` — **targeted additions, no rewrite.**

| Change | Detail |
|---|---|
| New field `self.enquiry` | An `EnquiryState` instance created in `__init__` (per-phone, session-scoped). |
| New field `self.last_triage` | Latest `TriageResult` (for activity log / tests / reporting). |
| `TOOLS` additions | Append 4 tool schemas: `lookup_faq`, `find_product` (+ optional `list_products`), `update_enquiry_signals`, `request_human_handoff`. Existing 8 tool schemas unchanged. |
| `execute_tool()` additions | Add dispatch branches for the 4 new tools. Existing branches unchanged. The `update_enquiry_signals` branch calls `self.enquiry.apply_candidate(...)` (validation in EnquiryState). |
| `send()` post-loop hook | After the existing loop returns final text, call the deterministic `_evaluate_triage()` helper (intent-first; may skip). This does **not** change the loop's control flow or the existing discount special-case. |
| New helper `_evaluate_triage()` | Pure orchestration: reads `self.enquiry`, calls `triage.evaluate(...)`, stores result, logs `PRIORITY_EVALUATED` sales_event, sets HIGH_PRIORITY flag. No LLM call. |
| `SYSTEM_PROMPT` additions | Additive guidance only: (a) call `lookup_faq` for general questions and do not treat them as sales; (b) call `update_enquiry_signals` when the customer states qty / quotation / urgency / discount / business-vs-personal / product interest; (c) call `request_human_handoff` on explicit "talk to a person" requests; (d) never state a numeric priority/score to the customer. No existing safety rule removed. |
| `pending_approval` / discount flow | **UNCHANGED.** |
| `apply_human_approval` / `_continue_after_human_action` | **UNCHANGED.** |

Because `execute_tool()` already returns `UNKNOWN_TOOL` for unrecognised names
and wraps execution in try/except at the call site, adding tools is low-risk and
consistent with the existing dispatch pattern.

---

## 4. Structured EnquiryState Design

**New file:** `app/enquiry_state.py`
**Why a new module (not inside agent.py):** it is pure data + validation logic
with no LLM/HTTP dependency; isolating it keeps it unit-testable offline (R10)
and keeps `agent.py` focused on the conversation loop. It is small and cohesive.

**Shape (conceptual — plain Python, stdlib only; dataclass):**

```
EnquiryState:
  # identity (validated from find_customer tool result only)
  customer_found: bool = False
  customer_id: str | None = None
  account_tier: str | None = None        # e.g. "GOLD", "STANDARD" (verbatim from DB)
  company_name: str | None = None

  # business context (Decision 2 — lives in enquiry state, not DB)
  business_customer: bool | None = None   # None = unknown (NOT false)

  # product / opportunity signals
  product_sku: str | None = None
  product_name: str | None = None
  quantity: int | None = None
  quotation_requested: bool = False
  urgent: bool = False
  discount_requested: bool = False

  # verified commercial value (only from successful pricing tool)
  verified_value_sgd: float | None = None
  value_is_verified: bool = False

  # triage output (populated by Python, never by LLM)
  last_triage: TriageResult | None = None
```

**Invariants enforced by EnquiryState methods (not by the LLM):**
- `business_customer` starts `None` and only becomes `True`/`False` from explicit
  current-enquiry context (Decision 2). Unknown stays `None`.
- `account_tier` is only set from a **successful** `find_customer` result and is
  stored verbatim; scoring maps it via config (unknown tiers score 0).
- `verified_value_sgd` / `value_is_verified` are only set from a **successful**
  pricing tool result (R9) — never from a failed/absent tool.
- `apply_candidate(signals)` performs last-write-wins updates with type/҂range
  validation (e.g. quantity must be a positive int) and precedence rules
  (explicit personal use overrides an earlier company mention → Decision 2).

---

## 5. How Conversation History and EnquiryState Interact

They are **complementary layers**, not alternatives:

| Layer | Owns | Source of truth for |
|---|---|---|
| `self.messages` (existing) | Full natural-language dialogue, tool calls/results | Context/nuance the LLM needs to converse |
| `self.enquiry` (new) | Validated, current workflow facts | Deterministic decisions (triage, routing, handoff) |

- The LLM reads history to converse and to *propose* candidate signals.
- Python reads `EnquiryState` to *decide* (score/band/route/handoff).
- History is append-only; `EnquiryState` is mutable/current (last-write-wins).
- If they ever disagree, **`EnquiryState` is authoritative for decisions**, and
  it is only updated through validated tool results or validated candidate
  signals — so the LLM cannot silently corrupt decision state.

---

## 6. Candidate → Validated Application State

The pathway that turns LLM interpretation into trusted state:

```
Customer text
   │  (Claude interprets)
   ▼
Claude calls update_enquiry_signals(candidate)      ← CANDIDATE (untrusted)
   │
   ▼
execute_tool("update_enquiry_signals", candidate)
   │
   ▼
EnquiryState.apply_candidate(candidate)             ← VALIDATION GATE
   • type checks (qty int > 0, booleans are booleans)
   • precedence rules (explicit personal use wins → business_customer=False)
   • ignores malformed/contradictory fields (returns what was accepted)
   • does NOT set verified_value here (that needs a pricing tool)
   │
   ▼
Validated EnquiryState                              ← TRUSTED (used by triage)
```

- **Identity, price, stock, delivery** facts bypass `update_enquiry_signals` and
  come only from their existing dedicated tools (`find_customer`,
  `get_customer_price`, `check_inventory`, `check_delivery`). `EnquiryState`
  ingests those results directly in `execute_tool()` (e.g. after a successful
  `get_customer_price`, set `verified_value_sgd`).
- `update_enquiry_signals` is limited to *language-derived* signals the LLM is
  best placed to interpret (quotation intent, urgency, discount intent,
  business-vs-personal, product interest, quantity as stated).

This keeps the trust boundary explicit: **LLM proposes, Python disposes.**

---

## 7. Correction / Update Behaviour

- `apply_candidate` is **last-write-wins** per field. "Actually make that 50"
  → Claude calls `update_enquiry_signals(quantity=50)` → `EnquiryState.quantity`
  becomes 50 → triage re-evaluates (§16) → band may change.
- Business-vs-personal precedence (Decision 2): a later explicit "it's for
  personal use" sets `business_customer=False` even if a company name appeared
  earlier; a later explicit company/company-purpose statement sets `True`.
- Verified value is recomputed only when a new **successful** pricing result
  arrives (e.g. after quantity change, if pricing is re-fetched). If pricing is
  not re-fetched, `value_is_verified` remains tied to the last verified figure
  and the reason string notes the quantity it was verified at (R9 safety).

---

## 8. Intent-First Routing

**New file:** `app/intent.py` (small, deterministic classifier + light LLM assist
via the tools already invoked).
**Why a new module:** routing policy is decision logic reused by the agent and
directly unit-tested (R10). It is not tool execution and not conversation
management, so it does not belong in `tools/` or in the loop body.

Intent categories (MVP): `FAQ_GENERAL`, `PRODUCT_DISCOVERY`, `SALES_ENQUIRY`,
`HUMAN_REQUEST`. Classification is primarily driven by **which tools the LLM
chose** plus `EnquiryState` contents (deterministic), with keyword fallbacks:

- If `request_human_handoff` was invoked or explicit handoff phrasing → `HUMAN_REQUEST`.
- If only `lookup_faq` was invoked and no opportunity signals present → `FAQ_GENERAL`.
- If product interest without commercial signals → `PRODUCT_DISCOVERY`.
- If any opportunity signal (qty/quotation/urgent/discount/value) → `SALES_ENQUIRY`.

**Rule (Clarification 4 / AC3.2):** `FAQ_GENERAL` never triggers triage, even for
a high customer-value account. Triage runs only for `SALES_ENQUIRY` (and
`PRODUCT_DISCOVERY` may accumulate signals that later promote it to
`SALES_ENQUIRY`).

---

## 9. FAQ Flow

**New files:** `app/tools/faq.py` (provider/tool) + `app/data/faq.json` (content).
**Why:** Decision 5 mandates a small static, editable source with a lightweight
lookup — no DB/RAG/embeddings. Content in JSON keeps it editable without code
changes; the tool wraps lookup so the LLM can't fabricate answers.

- `faq.json` keys (MVP): `operating_hours`, `location`, `payment_methods`,
  `delivery_policy`, `quotation_process`, `contact_info`, `company_info`.
- Values that are **not known from the repo are placeholders** clearly marked,
  e.g. `"operating_hours": "PLACEHOLDER — confirm with LionCity team"` (no
  invented facts, per Decision 5).
- `lookup_faq(topic)` returns the stored answer or `{"success": False,
  "error": "FAQ_TOPIC_NOT_FOUND"}`; the agent then asks a concise clarification
  rather than inventing (R9).

Flow: general question → Claude calls `lookup_faq` → answer rendered in WhatsApp
style → intent `FAQ_GENERAL` → **no triage**.

---

## 10. New / Guest Customer Flow

- `find_customer` returning `CUSTOMER_NOT_FOUND` is treated as a **valid guest**
  (R4). `EnquiryState.customer_found=False`, `customer_id=None`, `account_tier=None`.
- The conversation proceeds normally (discovery, quotation, triage).
- In triage, customer-value points that need an account
  (existing/tier/business-from-account) evaluate to 0; **opportunity-value
  points still apply**, so a guest can reach `SALES_OPPORTUNITY`/`HIGH_PRIORITY`.
- `business_customer` for a guest can still become `True` from explicit context
  (Decision 2) and contributes its opportunity point.

---

## 11. Product-Discovery Flow

**New file:** `app/tools/products.py`.
**Why:** there is currently no way to answer "what do you sell / do you have
product X" without fabrication (R6/AC6.2). Existing `check_inventory` needs a SKU;
customers speak in names. A discovery tool bridges names→SKUs against the
existing `products` table. It is a business tool → belongs in `tools/`.

- `find_product(query)` → looks up `products` by name/description (LIKE match) →
  returns matching `{sku, product_name, category}` list (no fabricated products).
- Optional `list_products()` → returns the catalog (names/categories, not stock).
- After a SKU is identified, existing `check_inventory` / `get_customer_price`
  are used for verified stock/price (no change to those tools).
- Reads the existing schema only; **no schema change**.

---

## 12. Tool-Selection Flow

```
                 ┌─────────────────────────────────────────┐
customer text →  │ Claude (SYSTEM_PROMPT: intent-first)     │
                 └───────────────┬─────────────────────────┘
     general Q ────────────────► lookup_faq                (FAQ path, no triage)
     "what do you sell / have X" ► find_product / list_products
     identity needed ───────────► find_customer            (guest-aware)
     stock claim ───────────────► check_inventory          (MUST, existing)
     price quote ───────────────► get_customer_price       (MUST, existing)
     delivery date ─────────────► resolve_date → check_delivery (existing)
     discount request ──────────► check_discount_authority (existing HITL)
     states qty/quote/urgent/    ► update_enquiry_signals   (candidate→validate)
       discount/business/product
     "talk to a human" ─────────► request_human_handoff     (new, §17)
     final confirmation ────────► create_order              (existing)
```

Existing MUST-use rules (inventory/pricing/delivery/discount/date) are retained
verbatim; the new tools are added without weakening them (AC6.3/AC6.4).

---

## 13. Triage Configuration Structure

**New file:** `app/triage_config.py` (or `app/config.py` holding a `TriageConfig`).
**Why separate from discount policy:** Decision 4 — triage config owns
scoring/thresholds/bands only; `AI_DISCOUNT_LIMIT` stays in `tools/discount.py`.

```
TriageConfig (dataclass / plain constants, centrally editable):

  customer_value_weights = {
      "existing_customer": 1,
      "tier": { "GOLD": 2, "SILVER": 1, "PREFERRED": 1, "STANDARD": 0 },
      # unknown/unmapped tier → 0 (Decision 1: no auto points)
  }

  opportunity_value_weights = {
      "business_customer": 1,
      "bulk_quantity": 2,       # applies when quantity >= bulk_quantity_threshold
      "verified_value": 2,      # applies when verified_value_sgd >= value_threshold
      "quotation_requested": 2,
      "urgent": 1,
      "discount_requested": 1,
  }

  bulk_quantity_threshold = 20
  value_threshold_sgd = 5000

  band_thresholds = { "sales_opportunity_min": 3, "high_priority_min": 6 }
  band_labels = { "routine": "ROUTINE",
                  "sales_opportunity": "SALES_OPPORTUNITY",
                  "high_priority": "HIGH_PRIORITY" }
```

All weights/thresholds/labels are read from here (AC7.3). Future SILVER/PREFERRED
are already supported by config **without touching the DB/seed** (Decision 1).

---

## 14. Deterministic Triage Algorithm

**New file:** `app/triage.py` — pure function `evaluate(state, config) -> TriageResult`.
**Why:** the deterministic core (R7/R10). No LLM, no I/O → trivially testable.

```
evaluate(state, config):
    cv = 0; reasons = []
    # --- customer value ---
    if state.customer_found:
        cv += w.existing_customer;        reasons.append(("existing_customer", +1))
    tier_pts = config.tier_points(state.account_tier)   # unknown → 0
    if tier_pts: cv += tier_pts;          reasons.append(("tier:"+tier, +tier_pts))

    ov = 0
    # --- opportunity value ---
    if state.business_customer is True:
        ov += w.business_customer;        reasons.append(("business_customer", +1))
    if state.quantity is not None and state.quantity >= cfg.bulk_quantity_threshold:
        ov += w.bulk_quantity;            reasons.append(("bulk>=20", +2))
    if state.value_is_verified and state.verified_value_sgd >= cfg.value_threshold_sgd:
        ov += w.verified_value;           reasons.append(("value>=5000", +2))
    if state.quotation_requested:  ov += w.quotation_requested; reasons.append(...)
    if state.urgent:               ov += w.urgent;              reasons.append(...)
    if state.discount_requested:   ov += w.discount_requested;  reasons.append(...)

    total = cv + ov
    band  = ROUTINE
    if total >= cfg.high_priority_min:      band = HIGH_PRIORITY
    elif total >= cfg.sales_opportunity_min: band = SALES_OPPORTUNITY

    return TriageResult(
        customer_value_score=cv,
        opportunity_value_score=ov,
        total_priority_score=total,
        priority_band=band,
        priority_reasons=reasons,     # explainable, per Clarification 5
    )
```

- Deterministic & side-effect free (AC7.5).
- `priority_reasons` gives an auditable breakdown (Clarification 5).
- `business_customer is True` guard ensures `None` (unknown) contributes 0
  (Decision 2).

---

## 15. Customer-Value vs Opportunity-Value Calculation

`TriageResult` keeps the two subtotals **separately visible before the total**
(AC7.1): `customer_value_score` and `opportunity_value_score` are distinct fields
and each is explainable via `priority_reasons`. The total is their sum; the band
derives from the total. This makes a guest's zero customer-value transparent
(AC4.3) and lets the console/tests show *why* a band was reached.

---

## 16. When Triage Is Evaluated / Re-Evaluated

- Triage runs once **per customer turn**, in the deterministic post-step of
  `send()` — but **only** when intent resolves to `SALES_ENQUIRY` (or a
  `PRODUCT_DISCOVERY` turn that has acquired opportunity signals). FAQ/general
  and pure human-request turns skip it (Clarification 4).
- Because `EnquiryState` is last-write-wins, each turn re-evaluates against the
  latest validated facts (so the multi-turn scenario E and correction F naturally
  escalate/adjust the band).
- The latest `TriageResult` is stored on `self.enquiry.last_triage` and
  `self.last_triage`, logged to `activity_log` and `sales_events`
  (`PRIORITY_EVALUATED`).

---

## 17. Explicit Human-Request Flow (score-independent)

**New file:** `app/handoff.py` (minimal) + **new tool** `request_human_handoff`.
**Why separate from `approval_requests` (Decision 3):** approval (discount
authority) and handoff (talk to a person) are different business concepts.
Reusing the approval table would conflate them. `handoff.py` is intentionally
minimal and defines a small interface a teammate's console can later consume.

```
Customer: "I want to speak to a salesperson."
   │  Claude → request_human_handoff(reason="explicit_request")
   ▼
execute_tool → handoff.record_handoff(phone, enquiry_context, trigger)
   • builds validated context from EnquiryState (customer_id/tier/product/qty/
     band if any) — NOT from raw LLM text
   • log_sales_event(HUMAN_HANDOFF_REQUESTED, phone, details=trigger+summary)
     ← reuses existing sales_events (Decision 3: smallest suitable mechanism)
   • returns {"success": True, "handoff": "recorded"}
   ▼
Agent replies briefly & truthfully (R5): "I've flagged this for our sales team."
```

- **Score-independent (AC8.1):** works even when band is `ROUTINE`.
- **Distinguishable (AC8.5):** `HUMAN_HANDOFF_REQUESTED` (explicit) vs a
  `HIGH_PRIORITY` triage flag are separate `sales_events` types.
- **No console redesign, no large subsystem** (Decision 3). Later integration
  point: the teammate-owned HITL/console can read `sales_events` of type
  `HUMAN_HANDOFF_REQUESTED` (and, if desired, a future handoff table). Documented
  as an extension seam, not built now.

---

## 18. Integration with Existing Discount HITL

- **Unchanged.** `check_discount_authority` → `pending_approval` →
  `create_approval_request` → `/process-approvals` → `apply_human_approval`
  all remain exactly as today (Decision 4, AC8.4).
- Triage runs independently; a discount request also sets
  `EnquiryState.discount_requested=True` (via `update_enquiry_signals` or by the
  agent recognising the discount tool call), contributing its +1 opportunity
  point — but it does **not** alter discount authority or the 5% limit.
- The two escalation types coexist: a message can both trigger discount HITL and
  be triaged; they are logged as distinct events.

---

## 19. Safe Tool-Failure Behaviour

- Existing `try/except` around `execute_tool` and the "never claim unverified
  facts" prompt rules are retained (R9).
- New rule for triage: signals derived from tools require **success**:
  - failed/absent `get_customer_price` → `value_is_verified` stays `False` →
    no "value ≥ SGD5000" point (AC9.2).
  - failed `find_customer` → guest (not an error dead-end), customer-value = 0.
  - failed `find_product` → agent asks for clarification, no fabricated SKU.
  - `lookup_faq` miss → concise clarification, no invented policy.
- `update_enquiry_signals` validation drops malformed candidate fields silently
  (keeps valid ones); it never fabricates verified value.
- Triage never raises on partial state; unknown fields simply contribute 0.

---

## 20. WhatsApp Response-Generation Behaviour

- Existing WhatsApp style rules in `SYSTEM_PROMPT` are retained and extended to
  new paths (R5): no Markdown tables, concise, mobile-friendly bullets, sparing
  `*bold*`.
- The agent **must not** reveal internal scores, band names, tool names, or
  reasons to the customer (AC5.2). Triage output is for internal
  logs/console/tests only.
- Escalation/handoff acknowledgements are brief and truthful (AC5.3): they state
  only that the request was flagged/sent for review, never a fabricated
  downstream action.
- `send_whatsapp_message()` is unchanged.

---

## 21. Automated Testing Architecture

**New files:** `tests/test_triage.py`, `tests/test_enquiry_state.py`,
`tests/test_intent.py`, `tests/test_triage_config.py` (pytest, assertion-based,
offline). Existing script-style tests are preserved (AC10.6).
**Why pytest:** `pytest` is already a declared dependency; the new logic is
deterministic and LLM-free, so it is directly assertable without network.

Coverage:
- **Triage bands** at boundaries: total 2→`ROUTINE`, 3→`SALES_OPPORTUNITY`,
  5→`SALES_OPPORTUNITY`, 6→`HIGH_PRIORITY` (AC10.1).
- **Each opportunity signal** independently (bulk, value, quotation, urgent,
  discount, business) and each customer-value signal (existing, GOLD=+2,
  SILVER/PREFERRED=+1 via config, STANDARD=+0, unknown tier=0).
- **Guest scenarios:** opportunity-only escalation (AC4.2), customer-value 0
  (AC4.3).
- **Config-driven change:** editing a weight/threshold changes band with no
  evaluator code change (AC10.2).
- **EnquiryState transitions:** last-write-wins on quantity; personal-use
  precedence over company mention (AC10.3, Decision 2).
- **Intent:** pure-FAQ input classified `FAQ_GENERAL` and proven **not** to
  produce a sales band, including for a high-value account (AC10.4/AC3.2).
- LLM-dependent behaviour (actual Claude calls) is **not** unit-tested here;
  the deterministic seams (`EnquiryState`, `triage`, `intent`, `TriageConfig`)
  are what tests target (AC10.5).

---

## 22. Exact Existing Files to Modify

| File | Change |
|---|---|
| `app/agent.py` | Add `self.enquiry`/`self.last_triage`; append 4 tool schemas to `TOOLS`; add 4 dispatch branches in `execute_tool()`; add `_evaluate_triage()` post-step in `send()`; additive `SYSTEM_PROMPT` guidance. Discount HITL untouched. |
| `app/whatsapp_api.py` | Minimal: allow the handoff/priority `sales_events` to flow (may need to surface `agent.last_triage` / handoff result in the webhook response for observability). No change to idempotency, discount approval, or `/process-approvals`. |

*(Whether `whatsapp_api.py` needs any edit at all is a small open question — see
§25. Triage/handoff already log via `sales_events` from within the agent/tools,
so the webhook may need no change beyond optional response fields.)*

---

## 23. Exact New Files Proposed

| File | Purpose | Justification |
|---|---|---|
| `app/enquiry_state.py` | `EnquiryState` dataclass + validation | Pure, testable state layer; keeps agent.py lean (§4) |
| `app/triage.py` | `evaluate(state, config)` deterministic scorer | Core R7 logic; offline-testable (§14) |
| `app/triage_config.py` | Central weights/thresholds/bands | R7 configurability; separate from discount policy (Decision 4, §13) |
| `app/intent.py` | Intent classifier (deterministic + tool-driven) | Intent-first routing reused/tested (§8) |
| `app/handoff.py` | Minimal `record_handoff()` interface | Separate from approvals (Decision 3, §17) |
| `app/tools/faq.py` | `lookup_faq` provider/tool | Controlled FAQ lookup (Decision 5, §9) |
| `app/data/faq.json` | Static FAQ content w/ placeholders | Editable, no DB/RAG (Decision 5, §9) |
| `app/tools/products.py` | `find_product`/`list_products` | Product discovery, no fabrication (§11) |
| `tests/test_triage.py` | Triage/band tests | R10 (§21) |
| `tests/test_enquiry_state.py` | State transition tests | R10 (§21) |
| `tests/test_intent.py` | Intent routing tests | R10 (§21) |
| `tests/test_triage_config.py` | Config-driven tests | R10 (§21) |

*(Filenames are the proposed set; exact names can be adjusted at Task stage.)*

---

## 24. Existing Files Deliberately Left Unchanged

- `app/claude_client.py` (active Anthropic integration — Clarification 2).
- `app/bedrock_client.py` (out of scope — Clarification 2).
- `app/tools/discount.py` incl. `AI_DISCOUNT_LIMIT` (Decision 4).
- `app/tools/customer.py`, `orders.py`, `inventory.py`, `pricing.py`,
  `delivery.py`, `date_tools.py`, `order_creation.py` (reused as-is; discovery
  builds on top, not inside).
- `app/database.py` schema & seed (no new columns/tables — Decisions 1, 2, 3, 5).
  Only existing `log_sales_event` is *called* (not modified).
- `data/lioncity.db` (no migration).
- `streamlit_app.py` (no console redesign — Decision 3).
- All existing `tests/*.py` script-style files (preserved — AC10.6).

---

## 25. Scenario Walkthroughs

**A. "What time do you close?" (unknown/any customer)**
Claude → `lookup_faq("operating_hours")` → returns stored value (or clearly-marked
placeholder). Intent = `FAQ_GENERAL` → **triage skipped**. Reply: concise hours in
WhatsApp style. No score, no escalation.

**B. Unknown customer: "Do you have 5 units of Product A?"**
`find_customer` → `CUSTOMER_NOT_FOUND` → guest. `find_product("Product A")` → SKU.
`check_inventory(sku, 5)`. Signals: quantity=5 (<20 → no bulk), no quotation/urgent.
Intent = `SALES_ENQUIRY` (opportunity present but small). Triage: cv=0, ov=0 →
total 0 → `ROUTINE`. Truthful stock answer.

**C. Existing customer: "I need 30 units of Product A for my company."**
`find_customer` → found (say GOLD). `update_enquiry_signals(quantity=30,
business_customer=True, product="Product A")`. `find_product`→SKU,
`check_inventory(30)`. Triage: cv = existing(+1)+GOLD(+2)=3; ov = business(+1)+
bulk≥20(+2)=3; total 6 → `HIGH_PRIORITY`. (If STANDARD: cv=1, ov=3, total 4 →
`SALES_OPPORTUNITY`.) Internal flag set; customer sees only a normal quote reply.

**D. Unknown: "We're ABC Construction. We need 100 units of Product A and need a
quotation urgently."**
Guest (`CUSTOMER_NOT_FOUND`). `update_enquiry_signals(business_customer=True,
company_name="ABC Construction", quantity=100, quotation_requested=True,
urgent=True, product="Product A")`. Triage: cv=0; ov = business(+1)+bulk(+2)+
quotation(+2)+urgent(+1)=6 → **`HIGH_PRIORITY`** despite being a guest (AC4.2).
Concise quotation-process reply.

**E. Multi-turn build-up**
Turn1 "I need Product A" → `find_product`; intent `PRODUCT_DISCOVERY`; ov=0 →
`ROUTINE`. Turn2 "30 units" → quantity=30 → bulk(+2); now `SALES_ENQUIRY`; total
2 (guest) → still `ROUTINE`? (2 < 3) → `ROUTINE`. Turn3 "For ABC Construction" →
business=True → +1 → total 3 → `SALES_OPPORTUNITY`. Turn4 "quotation urgently" →
quotation(+2)+urgent(+1) → ov=6 → `HIGH_PRIORITY`. Each turn re-evaluates on
last-write-wins state (§16).

**F. Correction: "Actually make that 50."**
`update_enquiry_signals(quantity=50)` → last-write-wins. Still ≥20 so bulk point
unchanged; band recomputed. If pricing re-fetched successfully, verified_value
recomputed (may cross SGD5000 → +2). Demonstrates §7 correction behaviour.

**G. "I want to speak to a salesperson."**
Intent = `HUMAN_REQUEST`. Claude → `request_human_handoff(reason="explicit")` →
`handoff.record_handoff` builds validated context + `log_sales_event(
HUMAN_HANDOFF_REQUESTED)`. **Score-independent** (works at `ROUTINE`). Reply:
"I've flagged this for our sales team." No discount-approval involvement (§17).

**H. "Can I get 10% off?"**
Existing discount HITL: `check_discount_authority(10)` → 10 > 5 →
`requires_human_approval=True` → `pending_approval` → `create_approval_request` →
`/process-approvals` (UNCHANGED, Decision 4). Also sets
`discount_requested=True` → +1 opportunity point in triage. Customer told the
request was sent for review (existing behaviour).

**I. Inventory/pricing tool failure**
`check_inventory`/`get_customer_price` returns `success:False` or raises →
existing `try/except` returns structured error to Claude. `value_is_verified`
stays `False` → **no** value point (AC9.2); no fabricated stock/price claim.
Agent asks for clarification or states it can't confirm right now (R9).

**J. Gold customer: "What time do you close?"**
Same as A: `lookup_faq` → intent `FAQ_GENERAL` → **triage skipped** even though
the account would score high on customer-value. The valuable account does **not**
turn a closing-time question into a sales escalation (Clarification 4 / AC3.2).

---

## 26. Remaining Design Decisions (for the team before Task planning)

1. **`whatsapp_api.py` edit scope (§22):** Preference is **zero functional
   change** — triage/handoff already log via `sales_events` inside the agent/tools.
   Confirm whether you want triage band / handoff status surfaced in the webhook
   JSON response (observability) or kept purely in logs/activity_log.
2. **Where the triage post-step lives:** inside `SalesAgent.send()` (proposed) vs
   a thin wrapper. Proposed keeps it in `send()` for a single call path.
3. **`update_enquiry_signals` granularity:** one flexible tool (proposed) vs
   several tiny tools. Proposed reduces tool-count churn and keeps validation in
   one place.
4. **Product matching strategy in `find_product`:** case-insensitive `LIKE`
   substring match on `product_name`/`description` (proposed, no schema change).
   Confirm acceptable for the 3-product demo catalog.
5. **FAQ placeholders:** confirm the team will supply real operating hours /
   location / payment / contact values later; until then they remain clearly
   marked placeholders (Decision 5).
6. **HIGH_PRIORITY internal flag consumption:** for MVP it is logged to
   `sales_events` (`PRIORITY_EVALUATED` / a `HIGH_PRIORITY` marker). Confirm no
   Streamlit surfacing is required now (console redesign is out of scope).
7. **Intent classification confidence:** MVP uses deterministic tool-driven +
   keyword rules. Confirm this is sufficient (no ML classifier) for the hackathon.
```



---

## REVISION 1 — Design for HIGH_PRIORITY auto-handoff + quotation preview

### 27. HIGH_PRIORITY automatic sales handoff (revises §14/§16/§17)

The deterministic evaluator in `app/triage.py` stays **pure** (no side effects).
The *action on the band* lives in the orchestration layer (`SalesAgent`):

- `SalesAgent.__init__` gains `self._auto_handoff_done = False`.
- `_evaluate_triage()` (already run after every state change) now, after storing
  the result, checks: `if band == HIGH_PRIORITY and not self._auto_handoff_done:`
  → set the flag `True` → `self._create_handoff(trigger="high_priority", …)`.
- `_create_handoff(trigger, reason)` is a shared helper used by BOTH the explicit
  `request_human_handoff` tool (`trigger="explicit_request"`) and the automatic
  path (`trigger="high_priority"`). It calls `app/handoff.record_handoff` →
  `log_sales_event("HUMAN_HANDOFF_REQUESTED", …)` and logs an `activity_log`
  entry that includes the handoff result.

**Idempotency:** the boolean `self._auto_handoff_done` guarantees exactly one
automatic handoff per enquiry regardless of how many later re-evaluations remain
HIGH_PRIORITY. Explicit requests are independent of this flag.

**Safety:** no order creation, no discount approval; the customer-facing message
is referral-only (prompt guidance forbids claiming a salesperson has
accepted/processed the enquiry). `record_handoff` returns a deterministic
`{status: RECORDED|ERROR}` contract; a failure is logged and does not fabricate
success.

### 28. Quotation preview (new — `app/quotation.py`)

**Why a new module:** it is pure presentation/derivation over trusted state,
kept out of `agent.py` so the agent stays an orchestrator. Small and cohesive.

- `build_quotation_preview(state)` / `generate_quotation_preview(state)` read
  ONLY current `EnquiryState`: `product_name`, `product_sku` (Category B),
  `quantity` (validated A), `verified_subtotal` (Category B).
- Unit price is derived only as `verified_subtotal / quantity` when both exist;
  otherwise "To be confirmed". Delivery/discount are "To be confirmed" (not
  verified/applied at preview time). Estimated total surfaces the verified
  subtotal basis only; never fabricated from unverified delivery/discount.
- Returns a structured dict (`fields`, `missing`, `disclaimer`, `status:
  PREVIEW`, `is_final: False`) plus a WhatsApp-formatted `message` (no tables,
  short lines, sparing `*bold*`).
- **Stale-safety:** because it reads CURRENT state and keeps no cached copy, the
  existing invalidation (quantity change → `verified_subtotal` cleared; genuine
  product change → product + subtotal cleared) means the preview can never show
  a stale amount.

New tool `generate_quotation_preview` (no args) dispatched in `_handle_tool`.
Additive SYSTEM_PROMPT sections: QUOTATIONS + HIGH_PRIORITY referral wording.

### 29. Trust boundary (unchanged)

A/B/C boundary preserved. Customer/Claude still cannot set `verified_subtotal`,
verified SKU/identity, priority score/band, or a handoff-completed state. The
quotation tool derives nothing from customer/LLM text.

### 30. Files (revision)

- Modify: `app/agent.py` (idempotency flag, shared `_create_handoff`, auto-handoff
  in `_evaluate_triage`, quotation tool schema + dispatch, prompt sections).
- New: `app/quotation.py`.
- Unchanged: `triage.py` stays pure; `handoff.py` reused as-is; discount HITL,
  database schema, teammate files untouched.



---

## REVISION 2 — Trusted unit price + documented idempotency limitation

### 31. verified_unit_price (Category B)

`get_customer_price` already returns a trusted `unit_price` (from the
`customer_prices` contract, else `products.list_price`). We surface it as a
first-class verified fact instead of reconstructing it:

- New `EnquiryState.verified_unit_price` (Category B). Populated ONLY by
  `set_verified_value(pricing_result)` from the result's `unit_price`.
- Not in `CATEGORY_A_FIELDS`, so `apply_candidate` rejects any customer/LLM
  attempt to set it (trust boundary preserved).
- The quotation preview displays `verified_unit_price` directly and NEVER
  computes `subtotal / quantity`. If it is absent, Unit Price shows
  "To be confirmed".

**Invalidation:** the trusted pricing result delivers `unit_price` and
`subtotal` together as one snapshot. Therefore both are cleared together when:
(a) the product genuinely changes, and (b) the quantity changes. The existing
pricing tool computes `subtotal = unit_price * quantity` and the unit price is
looked up per (customer, sku) — it is not tiered/volume-dependent — but we
still clear the unit price with the subtotal on a quantity change to avoid
presenting a unit price from a superseded pricing snapshot; re-pricing
repopulates both.

### 32. Documented limitation — HIGH_PRIORITY handoff idempotency scope

The automatic HIGH_PRIORITY handoff is de-duplicated via agent-instance state
(`SalesAgent._auto_handoff_done`). This prevents duplicate
`HUMAN_HANDOFF_REQUESTED` events during the active in-memory SalesAgent
conversation. It is **NOT restart-persistent**: if the process restarts and a
new SalesAgent is created for the same phone, a new automatic handoff could be
emitted. Restart-persistent handoff de-duplication is intentionally OUT OF
SCOPE for this corrective change (consistent with the session-scoped
EnquiryState limitation). Downstream de-duplication/workflow remains Person 3's
HITL/sales-console responsibility.
