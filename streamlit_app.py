import pandas as pd
import requests
import streamlit as st

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
    'From "bro, same order" to confirmed order.'
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

    st.subheader("Demo Customer")

    st.write("**Apex Engineering Pte Ltd**")
    st.write("Syahmul Aziz")
    st.write("GOLD Account")
    st.write("Sales Rep: Marcus")

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
            "Apex Engineering"
        )


    with metric_2:

        st.metric(
            "Account Tier",
            "GOLD"
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


        # -------------------------------------------------
        # CUSTOMER
        # -------------------------------------------------

        with st.container(
            border=True
        ):

            st.markdown(
                "### Apex Engineering Pte Ltd"
            )

            customer_col, status_col = (
                st.columns([2, 1])
            )


            with customer_col:

                st.write(
                    "**Contact:** Syahmul Aziz"
                )

                st.write(
                    "**WhatsApp:** +65 8165 8457"
                )

                st.write(
                    "**Sales Rep:** Marcus"
                )


            with status_col:

                st.success(
                    "GOLD"
                )

                if status == "ORDER_CONFIRMED":

                    st.success(
                        "✓ CONFIRMED"
                    )

                elif status == "HUMAN_APPROVAL":

                    st.error(
                        "APPROVAL"
                    )

                elif status == "AWAITING_CUSTOMER":

                    st.warning(
                        "CUSTOMER"
                    )

                elif status == "AI_HANDLING":

                    st.info(
                        "AI ACTIVE"
                    )

                else:

                    st.write(
                        "WAITING"
                    )


        # -------------------------------------------------
        # DEAL ITEMS
        # -------------------------------------------------

        st.markdown(
            "#### Current Deal"
        )


        deal_data = pd.DataFrame([
            {
                "SKU": "CBL-210",
                "Product":
                    "Industrial Cable",
                "Qty": 300,
                "Unit Price":
                    "S$12.00",
                "Subtotal":
                    "S$3,600",
            },
            {
                "SKU": "ADP-120",
                "Product":
                    "Industrial Adapter",
                "Qty": 50,
                "Unit Price":
                    "S$18.00",
                "Subtotal":
                    "S$900",
            },
            {
                "SKU": "TIE-100",
                "Product":
                    "Heavy Duty Cable Tie",
                "Qty": 100,
                "Unit Price":
                    "S$2.00",
                "Subtotal":
                    "S$200",
            },
        ])


        st.dataframe(
            deal_data,
            use_container_width=True,
            hide_index=True,
        )


        # -------------------------------------------------
        # BASE COMMERCIAL VALUES
        # -------------------------------------------------

        deal_metric_1, deal_metric_2 = (
            st.columns(2)
        )


        with deal_metric_1:

            st.metric(
                "Product Subtotal",
                "S$4,700.00"
            )


        with deal_metric_2:

            st.metric(
                "Delivery",
                "S$35.00"
            )


        # -------------------------------------------------
        # APPROVED DISCOUNT
        # -------------------------------------------------

        if (
            sales_state[
                "discount_percent"
            ]
            is not None
        ):

            approved_discount = (
                sales_state[
                    "discount_percent"
                ]
            )

            discount_amount = (
                4700
                * approved_discount
                / 100
            )

            st.success(
                f"✓ Approved Discount: "
                f"{approved_discount:.0f}% "
                f"(−S${discount_amount:,.2f})"
            )


        # -------------------------------------------------
        # LIVE TOTAL
        # -------------------------------------------------

        if quote_amount is not None:

            st.metric(
                "Current Deal Value",
                f"S${quote_amount:,.2f}"
            )


        # -------------------------------------------------
        # DELIVERY
        # -------------------------------------------------

        st.info(
            "🚚 Jurong · Tuesday, "
            "15 September 2026"
        )


        # -------------------------------------------------
        # VERIFIED BUSINESS FACTS
        # -------------------------------------------------

        if status != "READY":

            st.success(
                "✓ Inventory verified  "
                "✓ Contract pricing verified  "
                "✓ Delivery verified"
            )


        # -------------------------------------------------
        # CONFIRMED ORDER
        # -------------------------------------------------

        if status == "ORDER_CONFIRMED":

            st.divider()

            st.success(
                "🎉 Sale completed successfully"
            )

            st.write(
                "**Order Number:** "
                f"{sales_state['order_id']}"
            )

            st.write(
                "**Confirmed Value:** "
                f"S${sales_state['quote_amount']:,.2f}"
            )


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

                    st.write(
                        "**Revised Offer:** "
                        f"S${sales_state['quote_amount']:,.2f}"
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

                with st.container(
                    border=True
                ):

                    st.error(
                        "🔥 APPROVAL REQUIRED"
                    )

                    st.markdown(
                        "### Discount Request"
                    )

                    st.write(
                        "**Company:** "
                        "Apex Engineering Pte Ltd"
                    )

                    st.write(
                        f"**Customer:** "
                        f"{request['phone']}"
                    )


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
    ) = st.tabs([
        "📦 Inventory",
        "👥 Customers",
        "🧾 Orders",
        "🚚 Delivery",
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

        st.subheader("Update Inventory")

        selected_sku = st.selectbox(
            "Product",
            inventory_view["SKU"].tolist(),
            key="inventory_product",
        )

        current_stock = int(
            inventory_view.loc[
                inventory_view["SKU"]
                == selected_sku,
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

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)

    with metric_1:
        st.metric(
            "Sales Conversations",
            metrics["conversations"]
        )

    with metric_2:
        st.metric(
            "Human Escalations",
            metrics["human_escalations"]
        )

    with metric_3:
        st.metric(
            "Orders Confirmed",
            metrics["orders_confirmed"]
        )

    with metric_4:
        st.metric(
            "Revenue Generated",
            f"S${metrics['revenue']:,.2f}"
        )


    st.divider()


    # =====================================================
    # AI AUTOMATION
    # =====================================================

    st.subheader("🤖 AI Automation")

    automation_col_1, automation_col_2 = st.columns(2)

    with automation_col_1:
        st.metric(
            "Customer Messages Handled",
            metrics["customer_messages"]
        )

    with automation_col_2:
        st.metric(
            "Human Decisions Required",
            metrics["human_escalations"]
        )


    if (
        metrics["customer_messages"] > 0
        and metrics["human_escalations"] == 0
    ):

        st.success(
            "Routine customer interaction is being "
            "handled autonomously."
        )

    elif metrics["human_escalations"] > 0:

        st.warning(
            "The AI handled the conversation until "
            "a commercial authority boundary required "
            "human judgement."
        )

    else:

        st.info(
            "Waiting for WhatsApp sales activity."
        )


    st.caption(
        "Human intervention is triggered only when "
        "business policy requires a human decision."
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

    elif metrics["human_escalations"] > 0:

        st.warning(
            "A commercial decision currently "
            "requires human attention."
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