"""
Structured enquiry state for a single LionCity sales conversation.

WHY THIS MODULE EXISTS
----------------------
The existing SalesAgent already keeps the full natural-language conversation
in ``self.messages``. That history is great for context, but it is NOT a
reliable, validated source of *current facts* for deterministic decisions
(like triage scoring).

``EnquiryState`` is that validated-facts layer. It COMPLEMENTS the message
history; it does not replace it:

    self.messages   -> natural-language context (what was said)
    EnquiryState    -> validated current workflow facts (what is true now)

THE A / B / C TRUST BOUNDARY (very important)
---------------------------------------------
Fields fall into three trust categories:

  A - CUSTOMER-SUPPLIED / INTERPRETED
      Proposed by the customer/LLM, but VALIDATED by Python before they are
      stored. Examples: product_query, quantity, business_customer,
      company_name, quotation_requested, urgent, discount_requested,
      current_intent, human_requested.
      -> updated ONLY through apply_candidate() (the untrusted signal path).

  B - VERIFIED BUSINESS
      Must originate from a trusted business tool result. Examples:
      customer_id, existing_customer, customer_tier, verified product/SKU,
      verified_unit_price, verified_subtotal.
      -> updated ONLY through the dedicated trusted setters
         (set_customer_from_tool / set_verified_product /
          set_verified_value). The LLM signal path must NEVER touch these.

  C - DERIVED APPLICATION
      Calculated deterministically by Python (app/triage.py). Examples:
      customer_value_score, opportunity_value_score, total_priority_score,
      priority_band, priority_reasons.
      -> stored here only as a result object (last_triage). The LLM signal
         path must NEVER touch these.

NULL / UNKNOWN SEMANTICS
------------------------
For the "tri-state" boolean signals we deliberately distinguish:

    None  -> unknown / the customer has not expressed this yet
    True  -> customer expressed yes
    False -> customer explicitly expressed no

So ``quotation_requested = None`` (unknown) is NOT the same as
``quotation_requested = False`` (explicitly declined).

Batch 1 scope: this module is pure data + validation. It does NOT import or
call any business tool, the database, Claude, or WhatsApp. Trusted setters
exist as clean entry points for LATER batches to feed real tool results in.
"""

from dataclasses import dataclass, field


# -------------------------------------------------------------------------
# Allowed values for current_intent (Category A).
# Kept small and explicit for the hackathon. Unknown intent stays None.
# -------------------------------------------------------------------------
ALLOWED_INTENTS = {
    "FAQ_GENERAL",
    "PRODUCT_DISCOVERY",
    "SALES_ENQUIRY",
    "HUMAN_REQUEST",
}


# -------------------------------------------------------------------------
# The set of fields the untrusted signal path (apply_candidate) is allowed
# to touch. This is an ALLOW-LIST: anything not in here is rejected, which
# is how we block attempts to set Category B or C fields via the LLM path.
# -------------------------------------------------------------------------
CATEGORY_A_FIELDS = {
    "product_query",
    "quantity",
    "business_customer",
    "company_name",
    "quotation_requested",
    "urgent",
    "discount_requested",
    "current_intent",
    "human_requested",
}


@dataclass
class EnquiryState:
    """
    Validated, current facts for one ongoing enquiry (one phone / one
    SalesAgent instance). Session-scoped; not persisted across process
    restarts in this hackathon MVP (documented limitation).
    """

    # ------------------------------------------------------------------
    # CATEGORY A - customer-supplied / interpreted (via apply_candidate)
    # ------------------------------------------------------------------
    product_query: str = None            # what the customer called the product
    quantity: int = None                 # requested quantity (positive int)
    business_customer: bool = None       # None=unknown, True=business, False=personal
    company_name: str = None             # stated company (if any)
    quotation_requested: bool = None     # tri-state
    urgent: bool = None                  # tri-state
    discount_requested: bool = None      # tri-state
    current_intent: str = None           # one of ALLOWED_INTENTS or None
    human_requested: bool = None         # tri-state: explicit "talk to a person"

    # ------------------------------------------------------------------
    # CATEGORY B - verified business facts (via trusted setters ONLY)
    # ------------------------------------------------------------------
    existing_customer: bool = False      # True only after a successful find_customer
    customer_id: str = None
    customer_tier: str = None            # verbatim verified tier, e.g. "GOLD"
    product_sku: str = None              # verified SKU from find_product
    product_name: str = None             # verified product name
    verified_unit_price: float = None    # trusted unit price from pricing tool ONLY
    verified_subtotal: float = None      # from a successful pricing tool ONLY

    # Verified inventory (Category B), from a successful check_inventory tool
    # result ONLY. Bound to the SKU + requested quantity it was verified for,
    # so readiness checks can confirm the verification still matches the
    # CURRENT product/quantity (and is invalidated when either changes).
    verified_inventory_sku: str = None            # SKU the stock was checked for
    verified_inventory_quantity: int = None       # requested quantity checked
    verified_inventory_available: int = None      # available_quantity returned
    verified_inventory_can_fulfil: bool = None    # trusted can_fulfil result

    # ------------------------------------------------------------------
    # CATEGORY C - derived application result (set by triage.py ONLY)
    # ------------------------------------------------------------------
    last_triage: object = None           # a TriageResult, or None

    # ==================================================================
    # CATEGORY A UPDATE PATH  (UNTRUSTED - validate everything)
    # ==================================================================

    def apply_candidate(self, candidate):
        """
        Apply LLM/customer-proposed signals to Category A fields ONLY.

        This is the strict trust boundary. It:
          * accepts a dict of proposed field -> value,
          * ignores/rejects any field that is not an approved Category A
            field (this blocks attempts to set Category B or C fields),
          * validates the type / range / allowed values of each field,
          * applies valid fields using last-valid-update-wins semantics,
          * leaves unrelated fields untouched.

        Returns a small report dict so callers/tests can see exactly what
        was accepted and what was rejected:

            {
              "applied":  {field: value, ...},   # fields actually changed
              "rejected": {field: reason, ...},  # fields refused
            }
        """
        applied = {}
        rejected = {}

        if not isinstance(candidate, dict):
            return {"applied": applied, "rejected": {"__all__": "NOT_A_DICT"}}

        for field_name, raw_value in candidate.items():

            # --- Trust boundary: only Category A fields may pass. ---
            if field_name not in CATEGORY_A_FIELDS:
                rejected[field_name] = "NOT_AN_UPDATABLE_FIELD"
                continue

            ok, cleaned, reason = self._validate_field(field_name, raw_value)

            if not ok:
                rejected[field_name] = reason
                continue

            previous = getattr(self, field_name)

            # last-valid-update-wins: simply overwrite the field.
            setattr(self, field_name, cleaned)
            applied[field_name] = cleaned

            # Invalidate any verified (Category B) fact that depended on this
            # customer-supplied input once the input actually CHANGES. This
            # keeps trusted data from going stale after a correction. See
            # _invalidate_dependent_verified_state() for the small ruleset.
            if cleaned != previous:
                self._invalidate_dependent_verified_state(field_name, cleaned)

        return {"applied": applied, "rejected": rejected}

    def _invalidate_dependent_verified_state(self, field_name, new_value):
        """
        Clear verified (Category B) facts that no longer represent the current
        enquiry after a Category A correction. Deliberately minimal - no quote
        versioning, no dependency graph:

        - product_query changed  -> the verified SKU/name may no longer match
          the corrected product, so clear them UNLESS the new query still
          refers to the already-verified product (by name or SKU). Re-discovery
          (find_product) will re-populate the verified identity.
        - quantity changed        -> a previously verified subtotal was computed
          for the old quantity, so clear verified_subtotal. Re-pricing will
          re-populate it for the new quantity.
        """
        if field_name == "product_query":
            if self.product_sku is None and self.product_name is None:
                return
            # Keep verification only if the new query clearly still refers to
            # the currently verified product.
            candidate = "" if new_value is None else str(new_value).strip().lower()
            verified_name = (self.product_name or "").lower()
            verified_sku = (self.product_sku or "").lower()
            still_matches = candidate != "" and (
                candidate == verified_name
                or candidate == verified_sku
                or candidate in verified_name
                or verified_name in candidate
            )
            if not still_matches:
                self.product_sku = None
                self.product_name = None
                # Pricing (subtotal AND unit price) verified for the OLD
                # product no longer represents the corrected enquiry, so
                # invalidate both. (Only when the product verification is
                # genuinely cleared - a harmless rephrasing of the same
                # product keeps them.)
                self.verified_subtotal = None
                self.verified_unit_price = None
                # Inventory verified for the OLD product must not authorise a
                # DIFFERENT product; clear it whenever the verified product is
                # cleared. Re-running check_inventory repopulates it.
                self._clear_verified_inventory()

        elif field_name == "quantity":
            # A change in quantity invalidates the subtotal verified for the
            # previous quantity. The trusted pricing result delivered subtotal
            # and unit price together as one snapshot, so we clear the unit
            # price with it; re-pricing repopulates both for the new quantity.
            self.verified_subtotal = None
            self.verified_unit_price = None
            # Inventory sufficiency was verified for the OLD requested
            # quantity; a new quantity may exceed available stock, so the old
            # verification must not authorise it. Re-running check_inventory
            # repopulates it for the new quantity.
            self._clear_verified_inventory()

    def _clear_verified_inventory(self):
        """Reset all verified-inventory (Category B) fields to unknown."""
        self.verified_inventory_sku = None
        self.verified_inventory_quantity = None
        self.verified_inventory_available = None
        self.verified_inventory_can_fulfil = None

    def _validate_field(self, field_name, value):
        """
        Validate a single Category A field.

        Returns (ok, cleaned_value, reason).
        A field that is proposed as None is treated as an explicit "reset to
        unknown" and is allowed (tri-state semantics support True/False/None).
        """
        # Allow explicit reset to unknown for any Category A field.
        if value is None:
            return True, None, None

        # Integer field: quantity must be a positive whole number.
        if field_name == "quantity":
            # Reject booleans explicitly (bool is a subclass of int in Python).
            if isinstance(value, bool) or not isinstance(value, int):
                return False, None, "QUANTITY_NOT_INT"
            if value <= 0:
                return False, None, "QUANTITY_NOT_POSITIVE"
            return True, value, None

        # Boolean tri-state fields.
        if field_name in (
            "business_customer",
            "quotation_requested",
            "urgent",
            "discount_requested",
            "human_requested",
        ):
            if not isinstance(value, bool):
                return False, None, "NOT_A_BOOLEAN"
            return True, value, None

        # String fields.
        if field_name in ("product_query", "company_name"):
            if not isinstance(value, str):
                return False, None, "NOT_A_STRING"
            trimmed = value.strip()
            if trimmed == "":
                return False, None, "EMPTY_STRING"
            return True, trimmed, None

        # Enum field.
        if field_name == "current_intent":
            if not isinstance(value, str):
                return False, None, "NOT_A_STRING"
            normalized = value.strip().upper()
            if normalized not in ALLOWED_INTENTS:
                return False, None, "UNKNOWN_INTENT"
            return True, normalized, None

        # Should be unreachable because field_name is in CATEGORY_A_FIELDS.
        return False, None, "UNHANDLED_FIELD"

    # ==================================================================
    # CATEGORY B TRUSTED SETTERS  (application-owned entry points)
    # ==================================================================
    #
    # These are the ONLY sanctioned way to populate verified business facts.
    # In Batch 1 they are not wired to real tools yet; later batches will
    # call them with actual find_customer / find_product / pricing results.
    # The LLM signal path (apply_candidate) can never reach these.

    def set_customer_from_tool(self, tool_result):
        """
        Populate verified identity fields from a find_customer result.

        Only a successful result ({"success": True, ...}) sets an existing
        customer. Anything else is treated as a guest / new customer:
        existing_customer=False, customer_id=None, customer_tier=None.
        """
        if not isinstance(tool_result, dict) or not tool_result.get("success"):
            # Guest / new customer (e.g. CUSTOMER_NOT_FOUND). Not an error state.
            self.existing_customer = False
            self.customer_id = None
            self.customer_tier = None
            return

        self.existing_customer = True
        self.customer_id = tool_result.get("customer_id")
        self.customer_tier = tool_result.get("account_tier")
        # company_name from the account can seed the display name, but note
        # that the Category A business_customer flag is a SEPARATE, explicit
        # signal and is not inferred here.
        if tool_result.get("company_name") and self.company_name is None:
            self.company_name = tool_result.get("company_name")

    def set_verified_product(self, tool_result):
        """
        Populate verified product identity from a find_product result.
        Only a successful single-match result sets a SKU. Never invents one.
        """
        if not isinstance(tool_result, dict) or not tool_result.get("success"):
            return
        self.product_sku = tool_result.get("sku")
        self.product_name = tool_result.get("product_name")

    def set_verified_value(self, tool_result):
        """
        Populate the verified subtotal AND verified unit price from a
        successful pricing result.

        This is the ONLY way verified_subtotal / verified_unit_price become
        non-None. A monetary amount merely claimed by the customer/LLM must
        never reach this path, which is exactly why large-value triage points
        (subtotal) and the quotation-preview unit price key off these
        trusted fields only. The unit price is taken directly from the
        trusted pricing result - it is NOT reconstructed from subtotal.
        """
        if not isinstance(tool_result, dict) or not tool_result.get("success"):
            return
        subtotal = tool_result.get("subtotal")
        if isinstance(subtotal, (int, float)) and not isinstance(subtotal, bool):
            self.verified_subtotal = float(subtotal)
        unit_price = tool_result.get("unit_price")
        if isinstance(unit_price, (int, float)) and not isinstance(unit_price, bool):
            self.verified_unit_price = float(unit_price)

    def set_verified_inventory(self, tool_result):
        """
        Populate the verified inventory snapshot from a successful
        check_inventory result, binding it to the SKU + requested quantity it
        was actually checked for.

        This is the ONLY way the verified_inventory_* fields become non-None.
        A stock level merely claimed by the customer/LLM must never reach this
        path. An unsuccessful result (e.g. PRODUCT_NOT_FOUND) CLEARS any prior
        verification, so a failed lookup never leaves stale sufficiency behind.

        The stored values are later matched against the CURRENT product_sku +
        quantity by the readiness check, so a verification for a different
        SKU/quantity can never authorise the current transaction.
        """
        if not isinstance(tool_result, dict) or not tool_result.get("success"):
            self._clear_verified_inventory()
            return

        sku = tool_result.get("sku")
        requested_quantity = tool_result.get("requested_quantity")
        available_quantity = tool_result.get("available_quantity")
        can_fulfil = tool_result.get("can_fulfil")

        # Store only well-typed trusted values; otherwise clear (never guess).
        if not isinstance(sku, str) or sku.strip() == "":
            self._clear_verified_inventory()
            return
        if isinstance(requested_quantity, bool) or not isinstance(
            requested_quantity, int
        ):
            self._clear_verified_inventory()
            return

        self.verified_inventory_sku = sku
        self.verified_inventory_quantity = requested_quantity
        self.verified_inventory_available = (
            available_quantity
            if isinstance(available_quantity, int)
            and not isinstance(available_quantity, bool)
            else None
        )
        self.verified_inventory_can_fulfil = can_fulfil is True

    def reset_after_order_completion(self):
        """
        End the CURRENT transaction after an order has been SUCCESSFULLY
        created, so a reused EnquiryState (one per SalesAgent, shared across
        every message from the customer) cannot let the just-completed
        order's state authorise or block the NEXT order.

        Clears ONLY transaction-specific, order-readiness facts:
          - verified product identity (product_sku / product_name);
          - the Category A product_query + quantity that defined the order;
          - verified pricing (verified_subtotal / verified_unit_price);
          - verified inventory (all verified_inventory_* fields).

        A genuinely new order must therefore re-establish product, quantity
        and a FRESH check_inventory before it is considered order-ready -
        even when it happens to request the same SKU and quantity.

        Deliberately PRESERVES long-lived, non-transaction customer context
        (existing_customer, customer_id, customer_tier, company_name,
        business_customer, and the derived triage result). This is a targeted
        cleanup, NOT a full conversation/enquiry reset and NOT a transaction
        state machine.

        Must be called ONLY after a trusted successful order creation, never
        on a failed/blocked order and never on a discount rejection.
        """
        # Category A order inputs.
        self.product_query = None
        self.quantity = None
        # Category B verified product + pricing for the completed order.
        self.product_sku = None
        self.product_name = None
        self.verified_subtotal = None
        self.verified_unit_price = None
        # Category B verified inventory for the completed order.
        self._clear_verified_inventory()

    def inventory_ready_for(self, sku, quantity):
        """
        Return True ONLY when the persisted verified inventory EXACTLY matches
        the given CURRENT sku + quantity AND can_fulfil is True. Any mismatch
        (different SKU, different quantity, missing verification, or
        insufficient stock) returns False. Reads only trusted stored values.
        """
        if self.verified_inventory_sku is None:
            return False
        if self.verified_inventory_can_fulfil is not True:
            return False
        if not sku or self.verified_inventory_sku != sku:
            return False
        if (
            not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or self.verified_inventory_quantity != quantity
        ):
            return False
        return True

    # ==================================================================
    # CATEGORY C RESULT STORAGE  (set by triage only)
    # ==================================================================

    def set_triage_result(self, triage_result):
        """
        Store the deterministic triage result. Called by the application
        after running app.triage.evaluate(); never by the LLM signal path.
        """
        self.last_triage = triage_result
