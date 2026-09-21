import pandas as pd
import requests
import streamlit as st

# HAFIZAH ADDED GET_COMMERCIAL_POLICIES AND UPDATE_COMMERCIAL_POLICY TO BE IMPORT
from app.database import (
    get_pending_approvals,
    approve_request,
    get_table_data,
    update_inventory,
    update_delivery_capacity,
    get_sales_metrics,
    get_sales_events,
    get_latest_sales_state,
    add_customer,
    update_customer,
    remove_customer,
    add_delivery_slot,
    remove_delivery_slot,
    get_commercial_policies,
    update_commercial_policy,
    add_product_with_inventory,
)


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="LionCity AI SalesOps",
    page_icon="🤖",
    layout="wide",
)


# =========================================================
# HEADER
# =========================================================

st.title("🤖 LionCity AI SalesOps")

st.caption(
    'From "bro, same order" to confirmed order. • AWS Staging'
)


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:

    st.header("System Status")

    st.success("● WhatsApp Connected")
    st.success("● AI Sales Agent Online")
    st.success("● Business Data Connected")

    st.divider()

st.subheader("Demo Controls")

if st.button(
    "↻ Reset Demo",
    use_container_width=True,
    type="secondary",
):

    try:

        with st.spinner(
            "Resetting LionCity..."
        ):

            response = requests.post(
                "http://localhost:8000/reset-demo",
                timeout=30,
            )

        response.raise_for_status()

        result = response.json()

        if result.get("success"):

            st.success(
                "✓ Demo reset successfully."
            )

            st.rerun()

        else:

            st.error(
                "Demo reset failed."
            )

    except Exception as error:

        st.error(
            "Could not reach LionCity FastAPI."
        )

        st.code(
            str(error)
        )

    st.divider()

    st.caption(
        "Customer conversations occur through "
        "real WhatsApp. This console is used by "
        "LionCity sales and operations staff."
    )


# =========================================================
# MAIN TABS
# =========================================================

sales_tab, data_tab, dashboard_tab = st.tabs([
    "💼 Sales Console",
    "🗃 Business Data",
    "📊 SalesOps",
])

# =========================================================
# TAB 1 — SALES CONSOLE
# =========================================================

with sales_tab:

    st.header("💼 Sales Console")

    st.caption(
        "AI handles routine WhatsApp sales enquiries. "
        "Human attention is surfaced only when required."
    )

    # =====================================================
    # LOAD LIVE SALES STATE
    # =====================================================

    sales_state = get_latest_sales_state()

    pending_requests = get_pending_approvals()


    # =====================================================
    # TOP METRICS
    # =====================================================

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)


    with metric_1:

        st.metric(
            "Active Customer",
            "—"
        )


    with metric_2:

        st.metric(
            "Account Tier",
            "—"
        )


    with metric_3:

        quote_amount = sales_state[
            "quote_amount"
        ]

        if quote_amount is None:

            quote_display = "—"

        else:

            quote_display = (
                f"S${quote_amount:,.2f}"
            )

        st.metric(
            "Current Quote",
            quote_display
        )


    with metric_4:

        st.metric(
            "Human Decisions",
            len(pending_requests)
        )


    # =====================================================
    # LIVE DEAL STATUS
    # =====================================================

    status = sales_state["status"]


    if status == "READY":

        st.info(
            "⚪ READY — Waiting for WhatsApp "
            "customer enquiry"
        )


    elif status == "AI_HANDLING":

        st.success(
            "🤖 AI HANDLING — Routine sales "
            "conversation is being handled "
            "autonomously"
        )


    elif status == "HUMAN_APPROVAL":

        st.error(
            "🔥 HUMAN APPROVAL REQUIRED — "
            "Commercial authority boundary reached"
        )


    elif status == "AWAITING_CUSTOMER":

        approved_discount = sales_state[
            "discount_percent"
        ]

        st.warning(
            f"🟡 AWAITING CUSTOMER — "
            f"{approved_discount:.0f}% discount "
            f"approved and revised offer sent"
        )


    elif status == "ORDER_CONFIRMED":

        st.success(
            "🟢 ORDER CONFIRMED — "
            f"{sales_state['order_id']}"
        )


    st.divider()


    # =====================================================
    # MAIN SALES CONSOLE
    # =====================================================

    activity_column, approval_column = st.columns(
        [1.2, 1]
    )


    # =====================================================
    # LEFT COLUMN — LIVE WHATSAPP DEAL
    # =====================================================

    with activity_column:

        st.subheader(
            "📱 Live WhatsApp Deal"
        )

        if status == "READY":

            st.info(
                "No active WhatsApp deal. "
                "Waiting for a customer enquiry."
            )

        else:

            st.info(
                "WhatsApp sales activity is in progress."
            )

        # -------------------------------------------------
        # CUSTOMER
        # -------------------------------------------------



    # =====================================================
    # RIGHT COLUMN — HUMAN DECISIONS
    # =====================================================

    with approval_column:

        st.subheader(
            "🧑‍💼 Human Decisions"
        )


        # -------------------------------------------------
        # NO PENDING APPROVAL
        # -------------------------------------------------

        if not pending_requests:

            if status == "AWAITING_CUSTOMER":

                with st.container(
                    border=True
                ):

                    st.success(
                        "✓ HUMAN DECISION COMPLETED"
                    )

                    st.write(
                        "**Approved Discount:** "
                        f"{sales_state['discount_percent']:.0f}%"
                    )

                    if sales_state["quote_amount"] is not None:

                        st.write(
                            "**Revised Offer:** "
                            f"S${sales_state['quote_amount']:,.2f}"
                        )

                    else:

                        st.write(
                            "**Revised Offer:** "
                            "Sent to customer on WhatsApp"
                        )

                    st.info(
                        "Revised offer has been sent "
                        "to the customer on WhatsApp."
                    )


            elif status == "ORDER_CONFIRMED":

                with st.container(
                    border=True
                ):

                    st.success(
                        "✓ DEAL COMPLETED"
                    )

                    st.write(
                        "No further human action "
                        "is required."
                    )

                    st.write(
                        "**Order:** "
                        f"{sales_state['order_id']}"
                    )


            else:

                st.success(
                    "✓ No approvals currently "
                    "require attention."
                )

                st.caption(
                    "The AI is operating within "
                    "its authorised business rules."
                )


        # -------------------------------------------------
        # PENDING APPROVALS
        # -------------------------------------------------

        else:

            for request in pending_requests:

                # HAFIZAH: DISTINGUISH COMMERCIAL AUTHORITY
                # APPROVALS FROM LEGACY DISCOUNT APPROVALS
                approval_type = request.get(
                    "approval_type",
                    "DISCOUNT"
                )

                with st.container(
                    border=True
                ):

                    st.error(
                        "🔥 APPROVAL REQUIRED"
                    )

                    if approval_type == "COMMERCIAL_AUTHORITY":
                        st.markdown("### Commercial Authority Request")
                    else:
                        st.markdown("### Discount Request")

                    st.write(
                        "**Company:** "
                        "Apex Engineering Pte Ltd"
                    )

                    st.write(
                        f"**Customer:** "
                        f"{request['phone']}"
                    )

                    # HAFIZAH: SHOW COMMERCIAL AUTHORITY DETAILS
                    if approval_type == "COMMERCIAL_AUTHORITY":

                        st.write(
                            "**SKU:** "
                            f"{request.get('sku') or 'N/A'}"
                        )

                        st.write(
                            "**Requested Quantity:** "
                            f"{request.get('requested_quantity') or 0:,}"
                        )

                        st.write(
                            "**Order Value:** "
                            f"S${(request.get('order_value') or 0):,.2f}"
                        )

                        st.write(
                            "**Requested Discount:** "
                            f"{(request.get('requested_percent') or 0):.0f}%"
                        )

                        reason_labels = {
                            "HIGH_QUANTITY": "Quantity exceeds AI authority",
                            "HIGH_VALUE": "Order value exceeds AI authority",
                            "EXCESSIVE_DISCOUNT": "Discount exceeds AI authority",
                        }

                        reasons = [
                            reason.strip()
                            for reason in (
                                request.get("reason") or ""
                            ).split(",")
                            if reason.strip()
                        ]

                        if reasons:

                            st.write("**Escalation Reasons:**")

                            for reason in reasons:
                                st.write(
                                    f"- {reason_labels.get(reason, reason)}"
                                )

                    # HAFIZAH: COMMERCIAL AUTHORITY HUMAN DECISION
                    if approval_type == "COMMERCIAL_AUTHORITY":

                        st.warning(
                            "This transaction exceeds one or more "
                            "configured AI commercial authority limits "
                            "and requires human approval."
                        )

                        if st.button(
                            "✓ Approve Commercial Transaction",
                            type="primary",
                            use_container_width=True,
                            key=(
                                f"approve_commercial_"
                                f"{request['approval_id']}"
                            ),
                        ):

                            result = approve_request(
                                approval_id=request["approval_id"],
                                approved_percent=(
                                    request.get("requested_percent") or 0
                                ),
                            )

                            if not result["success"]:

                                st.error(
                                    "Commercial approval could not "
                                    "be recorded."
                                )

                            else:

                                # Resume the same WhatsApp SalesAgent after the
                                # commercial authority decision has been recorded.
                                try:

                                    with st.spinner(
                                        "Applying commercial approval "
                                        "and resuming customer conversation..."
                                    ):

                                        api_response = requests.post(
                                            "http://localhost:8000/process-approvals",
                                            timeout=90,
                                        )

                                    api_response.raise_for_status()

                                    api_result = api_response.json()

                                    approval_id = request["approval_id"]

                                    if approval_id in api_result.get(
                                        "processed",
                                        [],
                                    ):

                                        st.success(
                                            "✓ Commercial transaction approved "
                                            "and customer conversation resumed."
                                        )

                                    else:

                                        st.error(
                                            "Commercial approval was recorded, "
                                            "but FastAPI did not apply it."
                                        )

                                        skipped = api_result.get(
                                            "skipped",
                                            [],
                                        )

                                        if skipped:
                                            st.json(skipped)

                                except requests.exceptions.ConnectionError:

                                    st.error(
                                        "Commercial approval was saved, "
                                        "but FastAPI could not be reached."
                                    )

                                except requests.exceptions.Timeout:

                                    st.error(
                                        "Commercial approval was saved, "
                                        "but FastAPI timed out."
                                    )

                                except Exception as error:

                                    st.error(
                                        "Commercial approval was saved, "
                                        "but an error occurred while "
                                        "resuming the customer conversation."
                                    )

                                    st.code(str(error))

                                st.rerun()

                    # Commercial authority requests use the
                    # dedicated approval UI above.
                    # Do not render the legacy discount controls.
                    if approval_type == "COMMERCIAL_AUTHORITY":
                        continue

                    requested_col, authority_col = (
                        st.columns(2)
                    )


                    with requested_col:

                        st.metric(
                            "Customer Requested",
                            f"{request['requested_percent']:.0f}%"
                        )


                    with authority_col:

                        st.metric(
                            "AI Authority",
                            "5%"
                        )


                    st.warning(
                        "The requested discount "
                        "exceeds the AI Sales Agent's "
                        "commercial authority."
                    )


                    st.write(
                        "**Current Deal:** S$4,735.00"
                    )

                    st.write(
                        "**Customer Tier:** GOLD"
                    )

                    st.write(
                        "**Assigned Sales Rep:** Marcus"
                    )


                    st.divider()


                    if st.button(
                        "✓ Approve 7% Discount",
                        type="primary",
                        use_container_width=True,
                        key=(
                            f"approve_"
                            f"{request['approval_id']}"
                        ),
                    ):

                        # ---------------------------------
                        # Record human decision in SQLite.
                        # ---------------------------------

                        result = approve_request(
                            approval_id=
                                request[
                                    "approval_id"
                                ],
                            approved_percent=7,
                        )


                        if not result["success"]:

                            st.error(
                                "Approval could not "
                                "be recorded."
                            )


                        else:

                            # -----------------------------
                            # Ask FastAPI to resume the
                            # SAME WhatsApp SalesAgent.
                            # -----------------------------

                            try:

                                with st.spinner(
                                    "Applying approval "
                                    "and updating customer "
                                    "on WhatsApp..."
                                ):

                                    api_response = (
                                        requests.post(
                                            "http://localhost:8000/"
                                            "process-approvals",
                                            timeout=90,
                                        )
                                    )


                                api_response.raise_for_status()

                                api_result = (
                                    api_response.json()
                                )

                                approval_id = (
                                    request[
                                        "approval_id"
                                    ]
                                )


                                # -------------------------
                                # Verify THIS approval
                                # was processed.
                                # -------------------------

                                if (
                                    approval_id
                                    in api_result.get(
                                        "processed",
                                        []
                                    )
                                ):

                                    st.success(
                                        "✓ 7% approved "
                                        "and revised offer "
                                        "sent to customer."
                                    )


                                else:

                                    st.error(
                                        "Approval was "
                                        "recorded, but "
                                        "FastAPI did not "
                                        "apply it."
                                    )

                                    skipped = (
                                        api_result.get(
                                            "skipped",
                                            []
                                        )
                                    )

                                    if skipped:

                                        st.json(
                                            skipped
                                        )


                            except (
                                requests.exceptions
                                .ConnectionError
                            ):

                                st.error(
                                    "Approval was saved, "
                                    "but FastAPI could not "
                                    "be reached."
                                )


                            except (
                                requests.exceptions
                                .Timeout
                            ):

                                st.error(
                                    "Approval was saved, "
                                    "but FastAPI timed out."
                                )


                            except Exception as error:

                                st.error(
                                    "Approval was saved, "
                                    "but an error occurred "
                                    "while updating WhatsApp."
                                )

                                st.code(
                                    str(error)
                                )


                            st.rerun()

# =========================================================
# TAB 2 — BUSINESS DATA
# =========================================================
# HAFIZAH: ADDED POLICY TAB
with data_tab:

    st.header("🗃 Business Data")

    st.caption(
        "Live business data used by the AI Sales Agent. "
        "Changes made here affect subsequent agent decisions."
    )

    (
        inventory_tab,
        customer_tab,
        orders_tab,
        delivery_tab,
        policy_tab,
    ) = st.tabs([
        "📦 Inventory",
        "👥 Customers",
        "🧾 Orders",
        "🚚 Delivery",
        "🛡️ AI Authority",
    ])


    # =====================================================
    # INVENTORY
    # =====================================================

    with inventory_tab:

        st.subheader("Current Inventory")

        inventory_df = pd.DataFrame(
            get_table_data("inventory")
        )

        products_df = pd.DataFrame(
            get_table_data("products")
        )

        inventory_view = inventory_df.merge(
            products_df[
                [
                    "sku",
                    "product_name",
                    "list_price",
                ]
            ],
            on="sku",
            how="left",
        )

        inventory_view = inventory_view[
            [
                "sku",
                "product_name",
                "list_price",
                "available_quantity",
            ]
        ]

        inventory_view.columns = [
            "SKU",
            "Product",
            "List Price",
            "Available Stock",
        ]

        st.dataframe(
            inventory_view,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        st.subheader("Manage Inventory")

        inventory_action = st.radio(
            "Action",
            [
                "Add New Product",
                "Update Existing Inventory",
            ],
            horizontal=True,
            key="inventory_action",
        )

        # =================================================
        # ADD NEW PRODUCT
        # =================================================

        if inventory_action == "Add New Product":

            st.markdown("#### Add New Product")

            add_product_col_1, add_product_col_2 = st.columns(2)

            with add_product_col_1:

                new_sku = st.text_input(
                    "SKU",
                    placeholder="CBL-300",
                    key="new_product_sku",
                )

                new_product_name = st.text_input(
                    "Product Name",
                    placeholder="Outdoor Cable",
                    key="new_product_name",
                )

                new_description = st.text_area(
                    "Description",
                    placeholder="Outdoor-rated electrical cable",
                    key="new_product_description",
                )

            with add_product_col_2:

                new_category = st.text_input(
                    "Category",
                    placeholder="Electrical",
                    key="new_product_category",
                )

                new_list_price = st.number_input(
                    "List Price (S$)",
                    min_value=0.0,
                    value=0.0,
                    step=1.0,
                    format="%.2f",
                    key="new_product_price",
                )

                new_initial_stock = st.number_input(
                    "Initial Stock",
                    min_value=0,
                    value=0,
                    step=1,
                    key="new_product_stock",
                )

            if st.button(
                "Add Product",
                type="primary",
                use_container_width=True,
                key="add_product_button",
            ):

                if (
                    not new_sku.strip()
                    or not new_product_name.strip()
                ):

                    st.error(
                        "SKU and Product Name are required."
                    )

                else:

                    result = add_product_with_inventory(
                        sku=new_sku,
                        product_name=new_product_name,
                        description=new_description,
                        category=new_category,
                        list_price=float(new_list_price),
                        available_quantity=int(new_initial_stock),
                    )

                    if result["success"]:

                        st.success(
                            f"{result['sku']} — "
                            f"{result['product_name']} added "
                            f"with {result['available_quantity']} "
                            f"units of inventory."
                        )

                        st.rerun()

                    else:

                        if result["error"] == "SKU_ALREADY_EXISTS":

                            st.error(
                                f"SKU {result['sku']} already exists."
                            )

                        else:

                            st.error(
                                f"Could not add product: "
                                f"{result['error']}"
                            )

        # =================================================
        # UPDATE EXISTING INVENTORY
        # =================================================

        elif inventory_action == "Update Existing Inventory":

            st.markdown("#### Update Existing Inventory")

            if inventory_view.empty:

                st.info(
                    "There are no inventory items to update."
                )

            else:

                selected_sku = st.selectbox(
                    "Product",
                    inventory_view["SKU"].tolist(),
                    key="inventory_product",
                )

                current_stock = int(
                    inventory_view.loc[
                        inventory_view["SKU"] == selected_sku,
                        "Available Stock",
                    ].iloc[0]
                )

                new_stock = st.number_input(
                    "Available Quantity",
                    min_value=0,
                    value=current_stock,
                    step=1,
                    key="inventory_quantity",
                )

                if st.button(
                    "Update Inventory",
                    type="primary",
                    key="update_inventory",
                ):

                    result = update_inventory(
                        selected_sku,
                        int(new_stock),
                    )

                    if result["success"]:

                        st.success(
                            f"{selected_sku} updated to "
                            f"{int(new_stock)} units."
                        )

                        st.rerun()

                    else:

                        st.error(
                            result["error"]
                        )

        


            # =====================================================
# CUSTOMERS
# =====================================================

    with customer_tab:

        st.subheader("Customer Accounts")

        customers_df = pd.DataFrame(
            get_table_data("customers")
        )

        # -------------------------------------------------
        # CURRENT CUSTOMER TABLE
        # -------------------------------------------------

        if not customers_df.empty:

            customer_display = customers_df.rename(
                columns={
                    "customer_id": "Customer ID",
                    "company_name": "Company",
                    "contact_name": "Contact",
                    "phone": "Phone",
                    "account_tier": "Tier",
                    "delivery_area": "Delivery Area",
                    "assigned_sales_rep": "Sales Rep",
                }
            )

            st.dataframe(
                customer_display,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.info(
                "No customer accounts currently exist."
            )


        st.divider()


        # =================================================
        # CUSTOMER MANAGEMENT
        # =================================================

        st.subheader("Manage Customer")

        customer_action = st.radio(
            "Action",
            [
                "Add Customer",
                "Update Customer",
                "Remove Customer",
            ],
            horizontal=True,
            key="customer_action",
        )


        # =================================================
        # ADD CUSTOMER
        # =================================================

        if customer_action == "Add Customer":

            st.markdown("#### Add New Customer")

            add_col_1, add_col_2 = st.columns(2)

            with add_col_1:

                new_customer_id = st.text_input(
                    "Customer ID",
                    placeholder="CUST-003",
                    key="new_customer_id",
                )

                new_company = st.text_input(
                    "Company Name",
                    placeholder="Nova Engineering Pte Ltd",
                    key="new_customer_company",
                )

                new_contact = st.text_input(
                    "Contact Name",
                    placeholder="Alex Tan",
                    key="new_customer_contact",
                )

                new_phone = st.text_input(
                    "WhatsApp / Phone",
                    placeholder="+6591234567",
                    key="new_customer_phone",
                )


            with add_col_2:

                new_tier = st.selectbox(
                    "Account Tier",
                    [
                        "STANDARD",
                        "GOLD",
                    ],
                    key="new_customer_tier",
                )

                new_area = st.text_input(
                    "Delivery Area",
                    placeholder="Jurong",
                    key="new_customer_area",
                )

                new_sales_rep = st.text_input(
                    "Assigned Sales Rep",
                    placeholder="Marcus",
                    key="new_customer_rep",
                )


            if st.button(
                "Add Customer",
                type="primary",
                use_container_width=True,
                key="add_customer_button",
            ):

                if (
                    not new_customer_id.strip()
                    or not new_company.strip()
                    or not new_contact.strip()
                    or not new_phone.strip()
                    or not new_area.strip()
                    or not new_sales_rep.strip()
                ):

                    st.error(
                        "Please complete all customer fields."
                    )

                else:

                    result = add_customer(
                        customer_id=
                            new_customer_id.strip(),
                        company_name=
                            new_company.strip(),
                        contact_name=
                            new_contact.strip(),
                        phone=
                            new_phone.strip(),
                        account_tier=
                            new_tier,
                        delivery_area=
                            new_area.strip(),
                        assigned_sales_rep=
                            new_sales_rep.strip(),
                    )

                    if result["success"]:

                        st.success(
                            f"Customer "
                            f"{new_customer_id.strip()} "
                            f"added successfully."
                        )

                        st.rerun()

                    else:

                        st.error(
                            f"Could not add customer: "
                            f"{result['error']}"
                        )


        # =================================================
        # UPDATE CUSTOMER
        # =================================================

        elif customer_action == "Update Customer":

            st.markdown("#### Update Customer")

            if customers_df.empty:

                st.info(
                    "There are no customers to update."
                )

            else:

                customer_ids = (
                    customers_df[
                        "customer_id"
                    ].tolist()
                )

                selected_customer_id = st.selectbox(
                    "Select Customer",
                    customer_ids,
                    key="update_customer_select",
                )

                selected_customer = (
                    customers_df[
                        customers_df[
                            "customer_id"
                        ] == selected_customer_id
                    ]
                    .iloc[0]
                )


                update_col_1, update_col_2 = st.columns(2)


                with update_col_1:

                    updated_company = st.text_input(
                        "Company Name",
                        value=str(
                            selected_customer[
                                "company_name"
                            ]
                        ),
                        key=(
                            "update_company_"
                            f"{selected_customer_id}"
                        ),
                    )

                    updated_contact = st.text_input(
                        "Contact Name",
                        value=str(
                            selected_customer[
                                "contact_name"
                            ]
                        ),
                        key=(
                            "update_contact_"
                            f"{selected_customer_id}"
                        ),
                    )

                    updated_phone = st.text_input(
                        "WhatsApp / Phone",
                        value=str(
                            selected_customer[
                                "phone"
                            ]
                        ),
                        key=(
                            "update_phone_"
                            f"{selected_customer_id}"
                        ),
                    )


                with update_col_2:

                    current_tier = str(
                        selected_customer[
                            "account_tier"
                        ]
                    )

                    tier_options = [
                        "STANDARD",
                        "GOLD",
                    ]

                    tier_index = (
                        tier_options.index(
                            current_tier
                        )
                        if current_tier
                        in tier_options
                        else 0
                    )

                    updated_tier = st.selectbox(
                        "Account Tier",
                        tier_options,
                        index=tier_index,
                        key=(
                            "update_tier_"
                            f"{selected_customer_id}"
                        ),
                    )

                    updated_area = st.text_input(
                        "Delivery Area",
                        value=str(
                            selected_customer[
                                "delivery_area"
                            ]
                        ),
                        key=(
                            "update_area_"
                            f"{selected_customer_id}"
                        ),
                    )

                    updated_rep = st.text_input(
                        "Assigned Sales Rep",
                        value=str(
                            selected_customer[
                                "assigned_sales_rep"
                            ]
                        ),
                        key=(
                            "update_rep_"
                            f"{selected_customer_id}"
                        ),
                    )


                if st.button(
                    "Save Customer Changes",
                    type="primary",
                    use_container_width=True,
                    key=(
                        "save_customer_"
                        f"{selected_customer_id}"
                    ),
                ):

                    result = update_customer(
                        customer_id=
                            selected_customer_id,
                        company_name=
                            updated_company.strip(),
                        contact_name=
                            updated_contact.strip(),
                        phone=
                            updated_phone.strip(),
                        account_tier=
                            updated_tier,
                        delivery_area=
                            updated_area.strip(),
                        assigned_sales_rep=
                            updated_rep.strip(),
                    )

                    if result["success"]:

                        st.success(
                            f"{selected_customer_id} "
                            f"updated successfully."
                        )

                        st.rerun()

                    else:

                        st.error(
                            f"Could not update customer: "
                            f"{result['error']}"
                        )


        # =================================================
        # REMOVE CUSTOMER
        # =================================================

        elif customer_action == "Remove Customer":

            st.markdown("#### Remove Customer")

            st.warning(
                "Removing a customer is intended for "
                "prototype administration. Customers with "
                "dependent transactional records may not "
                "be removable."
            )


            if customers_df.empty:

                st.info(
                    "There are no customers to remove."
                )

            else:

                customer_ids = (
                    customers_df[
                        "customer_id"
                    ].tolist()
                )

                selected_remove_id = st.selectbox(
                    "Select Customer",
                    customer_ids,
                    key="remove_customer_select",
                )

                selected_remove_customer = (
                    customers_df[
                        customers_df[
                            "customer_id"
                        ] == selected_remove_id
                    ]
                    .iloc[0]
                )

                st.write(
                    "**Company:** "
                    f"{selected_remove_customer['company_name']}"
                )

                st.write(
                    "**Contact:** "
                    f"{selected_remove_customer['contact_name']}"
                )

                confirm_remove = st.checkbox(
                    "I confirm that I want to remove "
                    "this customer.",
                    key=(
                        "confirm_remove_"
                        f"{selected_remove_id}"
                    ),
                )


                if st.button(
                    "Remove Customer",
                    type="primary",
                    use_container_width=True,
                    disabled=not confirm_remove,
                    key=(
                        "remove_customer_"
                        f"{selected_remove_id}"
                    ),
                ):

                    result = remove_customer(
                        selected_remove_id
                    )

                    if result["success"]:

                        st.success(
                            f"{selected_remove_id} removed."
                        )

                        st.rerun()

                    else:

                        st.error(
                            f"Could not remove customer: "
                            f"{result['error']}"
                        )


    # =====================================================
    # ORDERS
    # =====================================================

    with orders_tab:

        st.subheader("Historical Orders")

        orders_df = pd.DataFrame(
            get_table_data("orders")
        )

        if not orders_df.empty:

            orders_df = orders_df.rename(
                columns={
                    "order_id":
                        "Order ID",
                    "customer_id":
                        "Customer ID",
                    "order_date":
                        "Order Date",
                    "delivery_area":
                        "Delivery Area",
                    "status":
                        "Status",
                }
            )

        st.dataframe(
            orders_df,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            'This is where "same order as last month" '
            "comes from."
        )

        with st.expander(
            "View Order Line Items"
        ):

            items_df = pd.DataFrame(
                get_table_data(
                    "order_items"
                )
            )

            st.dataframe(
                items_df,
                use_container_width=True,
                hide_index=True,
            )


    # =====================================================
# DELIVERY
# =====================================================

    with delivery_tab:

        st.subheader("Delivery Capacity")

        delivery_df = pd.DataFrame(
            get_table_data(
                "delivery_slots"
            )
        )


        # -------------------------------------------------
        # CURRENT DELIVERY TABLE
        # -------------------------------------------------

        if not delivery_df.empty:

            delivery_display = delivery_df.rename(
                columns={
                    "delivery_area": "Area",
                    "delivery_date": "Date",
                    "delivery_fee": "Delivery Fee",
                    "remaining_capacity":
                        "Remaining Capacity",
                }
            )

            st.dataframe(
                delivery_display,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.info(
                "No delivery slots currently exist."
            )


        st.divider()


        # =================================================
        # DELIVERY MANAGEMENT
        # =================================================

        st.subheader("Manage Delivery Slots")

        delivery_action = st.radio(
            "Action",
            [
                "Add Slot",
                "Update Capacity",
                "Remove Slot",
            ],
            horizontal=True,
            key="delivery_action",
        )


        # =================================================
        # ADD DELIVERY SLOT
        # =================================================

        if delivery_action == "Add Slot":

            st.markdown("#### Add Delivery Slot")

            add_delivery_col_1, add_delivery_col_2 = (
                st.columns(2)
            )


            with add_delivery_col_1:

                new_delivery_area = st.text_input(
                    "Delivery Area",
                    placeholder="Tuas",
                    key="new_delivery_area",
                )

                new_delivery_date = st.date_input(
                    "Delivery Date",
                    key="new_delivery_date",
                )


            with add_delivery_col_2:

                new_delivery_fee = st.number_input(
                    "Delivery Fee",
                    min_value=0.0,
                    value=35.0,
                    step=5.0,
                    key="new_delivery_fee",
                )

                new_delivery_capacity = (
                    st.number_input(
                        "Initial Capacity",
                        min_value=0,
                        value=5,
                        step=1,
                        key="new_delivery_capacity",
                    )
                )


            if st.button(
                "Add Delivery Slot",
                type="primary",
                use_container_width=True,
                key="add_delivery_slot_button",
            ):

                if not new_delivery_area.strip():

                    st.error(
                        "Please enter a delivery area."
                    )

                else:

                    result = add_delivery_slot(
                        delivery_area=
                            new_delivery_area.strip(),
                        delivery_date=
                            new_delivery_date.isoformat(),
                        delivery_fee=
                            float(new_delivery_fee),
                        remaining_capacity=
                            int(new_delivery_capacity),
                    )

                    if result["success"]:

                        st.success(
                            "Delivery slot added "
                            "successfully."
                        )

                        st.rerun()

                    else:

                        st.error(
                            f"Could not add delivery slot: "
                            f"{result['error']}"
                        )


        # =================================================
        # UPDATE DELIVERY CAPACITY
        # =================================================

        elif delivery_action == "Update Capacity":

            st.markdown(
                "#### Update Delivery Capacity"
            )


            if delivery_df.empty:

                st.info(
                    "There are no delivery slots to update."
                )

            else:

                slot_labels = []

                slot_lookup = {}


                for _, row in delivery_df.iterrows():

                    label = (
                        f"{row['delivery_area']} — "
                        f"{row['delivery_date']}"
                    )

                    slot_labels.append(
                        label
                    )

                    slot_lookup[label] = row


                selected_slot_label = st.selectbox(
                    "Delivery Slot",
                    slot_labels,
                    key="update_delivery_slot_select",
                )

                selected_slot = slot_lookup[
                    selected_slot_label
                ]


                st.write(
                    "**Delivery Fee:** "
                    f"S${float(selected_slot['delivery_fee']):,.2f}"
                )


                updated_capacity = st.number_input(
                    "Remaining Capacity",
                    min_value=0,
                    value=int(
                        selected_slot[
                            "remaining_capacity"
                        ]
                    ),
                    step=1,
                    key=(
                        "update_capacity_"
                        f"{selected_slot_label}"
                    ),
                )


                if st.button(
                    "Update Capacity",
                    type="primary",
                    use_container_width=True,
                    key="update_delivery_capacity_button",
                ):

                    result = (
                        update_delivery_capacity(
                            selected_slot[
                                "delivery_area"
                            ],
                            selected_slot[
                                "delivery_date"
                            ],
                            int(
                                updated_capacity
                            ),
                        )
                    )

                    if result["success"]:

                        st.success(
                            "Delivery capacity updated."
                        )

                        st.rerun()

                    else:

                        st.error(
                            f"Could not update capacity: "
                            f"{result['error']}"
                        )


        # =================================================
        # REMOVE DELIVERY SLOT
        # =================================================

        elif delivery_action == "Remove Slot":

            st.markdown(
                "#### Remove Delivery Slot"
            )


            if delivery_df.empty:

                st.info(
                    "There are no delivery slots to remove."
                )

            else:

                slot_labels = []

                slot_lookup = {}


                for _, row in delivery_df.iterrows():

                    label = (
                        f"{row['delivery_area']} — "
                        f"{row['delivery_date']}"
                    )

                    slot_labels.append(
                        label
                    )

                    slot_lookup[label] = row


                selected_remove_slot_label = (
                    st.selectbox(
                        "Delivery Slot",
                        slot_labels,
                        key="remove_delivery_slot_select",
                    )
                )

                selected_remove_slot = (
                    slot_lookup[
                        selected_remove_slot_label
                    ]
                )


                st.write(
                    "**Area:** "
                    f"{selected_remove_slot['delivery_area']}"
                )

                st.write(
                    "**Date:** "
                    f"{selected_remove_slot['delivery_date']}"
                )

                st.write(
                    "**Remaining Capacity:** "
                    f"{selected_remove_slot['remaining_capacity']}"
                )


                confirm_remove_slot = st.checkbox(
                    "I confirm that I want to remove "
                    "this delivery slot.",
                    key=(
                        "confirm_remove_delivery_"
                        f"{selected_remove_slot_label}"
                    ),
                )


                if st.button(
                    "Remove Delivery Slot",
                    type="primary",
                    use_container_width=True,
                    disabled=not confirm_remove_slot,
                    key="remove_delivery_slot_button",
                ):

                    result = remove_delivery_slot(
                        delivery_area=
                            selected_remove_slot[
                                "delivery_area"
                            ],
                        delivery_date=
                            selected_remove_slot[
                                "delivery_date"
                            ],
                    )

                    if result["success"]:

                        st.success(
                            "Delivery slot removed."
                        )

                        st.rerun()

                    else:

                        st.error(
                            f"Could not remove delivery slot: "
                            f"{result['error']}"
                        )
# HAFIZAH: ADDED AI COMMERCIAL AUTHORITY
# =========================================================
# AI COMMERCIAL AUTHORITY
# =========================================================

    with policy_tab:
        st.subheader("🛡️ AI Commercial Authority")
        st.caption(
            "Configure the commercial limits that the AI Sales "
            "Agent may approve without human intervention."
        )
        policies = get_commercial_policies()

        policy_lookup = {
            policy["policy_key"]: policy
            for policy in policies
        }

        max_quantity= float(policy_lookup["MAX_QUANTITY_PER_SKU"]["policy_value"])

        max_order_value = float(policy_lookup["MAX_ORDER_VALUE"]["policy_value"])

        max_discount = float(policy_lookup["MAX_DISCOUNT_PERCENT"]["policy_value"])

        st.info(
            "Transactions exceeding any of these limits "
            "require human approval."
        )

        st.markdown("#### Current Authority Limits")

        quantity_col, value_col, discount_col = st.columns(3)

        with quantity_col:
            st.metric(
                "Maximum Quantity / SKU",
                f"{max_quantity:,.0f}"
            )

        with value_col:
            st.metric(
                "Maximum Order Value",
                f"S${max_order_value:,.2f}"
            )

        with discount_col:
            st.metric(
                "Maximum Discount",
                f"{max_discount:.1f}"
            )

        st.divider()

        st.markdown("#### Update Authority Limits")

        new_max_quantity = st.number_input(
            "Maximum Quantity per SKU",
            min_value=1,
            value=int(max_quantity),
            step=1,
            help=(
                "Orders above this quantity require "
                "human approval."
            ),
        )

        new_max_order_value = st.number_input(
            "Maximum Order Value (S$)",
            min_value=0.0,
            value=max_order_value,
            step=500.0,
            help=(
                "Orders above this value require "
                "human approval."
            )
        )

        new_max_discount = st.number_input(
            "Maximum Discount (%)",
            min_value=0.0,
            max_value=100.0,
            value=max_discount,
            step=1.0,
            help=(
                "Discounts above this percentage require "
                "human approval."
            ),
        )

        if st.button(
            "Save Authority Limits",
            type="primary",
            use_container_width=True,
            key="save_commercial_authority"
        ):
            results = [
                update_commercial_policy(
                    "MAX_QUANTITY_PER_SKU",
                    float(new_max_quantity),
                ),
                update_commercial_policy(
                    "MAX_ORDER_VALUE",
                    float(new_max_order_value),
                ),
                update_commercial_policy(
                    "MAX_DISCOUNT_PERCENT",
                    float(new_max_discount),
                ),
            ]

            if all(result["success"] for result in results):
                st.success(
                    "AI commercial authority updated successfully."
                )
                st.rerun()

            else:
                st.error(
                    "One or more commercial authority "
                    "settings could not be updated."
                )

    # =========================================================
# TAB 3 — SALESOPS
# =========================================================

with dashboard_tab:

    st.header("📊 SalesOps Command Center")

    st.caption(
        "Live management visibility across "
        "AI-assisted WhatsApp sales activity."
    )

    # =====================================================
    # LOAD LIVE DATA
    # =====================================================

    metrics = get_sales_metrics()
    events = get_sales_events()


    # =====================================================
    # KPI CARDS
    # =====================================================

    metric_1, metric_2, metric_3, metric_4, metric_5 = st.columns(5)

    with metric_1:
        st.metric(
            "Sales Conversations",
            metrics["conversations"]
        )

    with metric_2:
        st.metric(
            "Approvals Required",
            metrics["approvals_required"]
        )

    with metric_3:
        st.metric(
            "Salesperson Requested",
            metrics["salesperson_requested"]
        )

    with metric_4:
        st.metric(
            "Orders Confirmed",
            metrics["orders_confirmed"]
        )

    with metric_5:
        st.metric(
            "Revenue Generated",
            f"S${metrics['revenue']:,.2f}"
        )


    st.divider()


    # =====================================================
    # AI AUTOMATION
    # =====================================================

    st.subheader("🤖 AI Automation")

    st.metric(
        "Customer Messages Handled",
        metrics["customer_messages"]
    )

    if metrics["approvals_required"] > 0:

        st.warning(
            "One or more commercial approvals "
            "require attention."
        )

    elif metrics["salesperson_requested"] > 0:

        st.info(
            "A customer has requested follow-up "
            "from a salesperson."
        )

    elif metrics["customer_messages"] > 0:

        st.success(
            "Customer interactions are being "
            "handled autonomously."
        )

    else:

        st.info(
            "Waiting for WhatsApp sales activity."
        )

    st.divider()


    # =====================================================
    # LIVE SALES ACTIVITY
    # =====================================================

    st.subheader("⚡ Live Sales Activity")


    if not events:

        st.info(
            "No sales activity yet. "
            "Send a WhatsApp message to begin."
        )


    else:

        for event in events:

            event_type = event["event_type"]

            phone = (
                event.get("phone")
                or "-"
            )

            timestamp = (
                event.get("created_at")
                or ""
            )

            details = (
                event.get("details")
                or ""
            )

            amount = event.get("amount")


            # =============================================
            # CONVERSATION STARTED
            # =============================================

            if event_type == "CONVERSATION_STARTED":

                with st.container(border=True):

                    st.markdown(
                        "### 🟢 Sales Conversation Started"
                    )

                    st.caption(timestamp)

                    st.write(
                        f"**Customer:** {phone}"
                    )

                    if details:
                        st.write(details)


            # =============================================
            # CUSTOMER MESSAGE
            # =============================================

            elif event_type == "CUSTOMER_MESSAGE":

                with st.container(border=True):

                    st.markdown(
                        "### 💬 Customer Message"
                    )

                    st.caption(timestamp)

                    st.write(
                        f"**Customer:** {phone}"
                    )

                    if details:
                        st.write(details)


            # =============================================
            # SALESPERSON REQUESTED
            # =============================================

            elif (
                event_type
                == "HUMAN_HANDOFF_REQUESTED"
            ):

                with st.container(border=True):

                    st.markdown(
                        "### 👤 Salesperson Requested"
                    )

                    st.caption(timestamp)

                    st.write(
                        f"**Customer:** {phone}"
                    )

                    if details:
                        st.info(details)


            # =============================================
            # HUMAN APPROVAL REQUIRED
            # =============================================

            elif (
                event_type
                == "HUMAN_APPROVAL_REQUIRED"
            ):

                with st.container(border=True):

                    st.markdown(
                        "### 🔥 Human Approval Required"
                    )

                    st.caption(timestamp)

                    st.write(
                        f"**Customer:** {phone}"
                    )

                    if details:
                        st.warning(details)


            # =============================================
            # HUMAN APPROVAL COMPLETED
            # =============================================

            elif (
                event_type
                == "HUMAN_APPROVAL_APPROVED"
            ):

                with st.container(border=True):

                    st.markdown(
                        "### 🧑‍💼 Human Decision"
                    )

                    st.caption(timestamp)

                    st.write(
                        f"**Customer:** {phone}"
                    )

                    if details:
                        st.success(details)


            # =============================================
            # ORDER CONFIRMED
            # =============================================

            elif event_type == "ORDER_CONFIRMED":

                with st.container(border=True):

                    st.markdown(
                        "### 🎉 Order Confirmed"
                    )

                    st.caption(timestamp)

                    if event.get("customer_id"):

                        st.write(
                            f"**Customer:** "
                            f"{event['customer_id']}"
                        )

                    if details:

                        st.write(
                            f"**Order:** {details}"
                        )

                    if amount is not None:

                        st.metric(
                            "Order Value",
                            f"S${amount:,.2f}"
                        )

            # =============================================
            # ORDER CREATION FAILED
            # =============================================
            elif event_type == "ORDER_CREATION_FAILED":

                st.error("🚨 ORDER CREATION FAILED — HUMAN ACTION REQUIRED")

                if event.get("customer_id"):
                    st.write(f"**Customer:** {event['customer_id']}")

                if event.get("phone"):
                    st.write(f"**Phone:** {event['phone']}")

                if event.get("amount") is not None:
                    st.write(
                        f"**Order value:** "
                        f"S${event['amount']:,.2f}"
                    )

                if event.get("details"):
                    st.write(f"**Failure details:** {event['details']}")

                if event.get("created_at"):
                    st.caption(f"Failure recorded: {event['created_at']}")

    st.divider()


    # =====================================================
    # MANAGEMENT VIEW
    # =====================================================

    st.subheader("💡 Management View")


    if metrics["orders_confirmed"] > 0:

        st.success(
            f"AI-assisted sales have generated "
            f"S${metrics['revenue']:,.2f} "
            f"in confirmed orders during this demo."
        )

    elif metrics["approvals_required"] > 0:

        st.warning(
            "A commercial approval currently "
            "requires human attention."
        )

    elif metrics["salesperson_requested"] > 0:

        st.info(
            "A customer has requested follow-up "
            "from a salesperson."
        )

    elif metrics["conversations"] > 0:

        st.info(
            "The AI Sales Agent is currently "
            "handling an active sales conversation."
        )

    else:

        st.info(
            "Waiting for WhatsApp sales activity."
        )