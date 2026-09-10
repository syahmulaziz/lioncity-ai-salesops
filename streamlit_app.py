import pandas as pd
import requests
import streamlit as st

from app.database import (
    get_pending_approvals,
    approve_request,
    get_table_data,
    update_inventory,
    update_delivery_capacity,
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

    st.divider()

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
        st.metric(
            "Current Quote",
            "S$4,735"
        )

    with metric_4:
        st.metric(
            "Human Decisions",
            len(pending_requests)
        )


    st.divider()


    # =====================================================
    # TWO-COLUMN EMPLOYEE CONSOLE
    # =====================================================

    activity_column, approval_column = st.columns(
        [1.2, 1]
    )


    # -----------------------------------------------------
    # LEFT — LIVE DEAL
    # -----------------------------------------------------

    with activity_column:

        st.subheader("📱 Live WhatsApp Deal")

        with st.container(border=True):

            st.markdown(
                "### Apex Engineering Pte Ltd"
            )

            customer_col, status_col = st.columns(
                [2, 1]
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
                    "🔥 HIGH INTENT"
                )

                st.write(
                    "**GOLD Account**"
                )

        st.markdown("#### Current Deal")

        deal_data = pd.DataFrame([
            {
                "SKU": "CBL-210",
                "Product": "Industrial Cable",
                "Qty": 300,
                "Unit Price": "S$12.00",
                "Subtotal": "S$3,600",
            },
            {
                "SKU": "ADP-120",
                "Product": "Industrial Adapter",
                "Qty": 50,
                "Unit Price": "S$18.00",
                "Subtotal": "S$900",
            },
            {
                "SKU": "TIE-100",
                "Product": "Heavy Duty Cable Tie",
                "Qty": 100,
                "Unit Price": "S$2.00",
                "Subtotal": "S$200",
            },
        ])

        st.dataframe(
            deal_data,
            use_container_width=True,
            hide_index=True,
        )

        deal_metric_1, deal_metric_2 = st.columns(2)

        with deal_metric_1:

            st.metric(
                "Product Subtotal",
                "S$4,700"
            )

        with deal_metric_2:

            st.metric(
                "Delivery",
                "S$35"
            )

        st.info(
            "🚚 Jurong · Tuesday, 15 September 2026"
        )

        st.success(
            "✓ Inventory verified  "
            "✓ Contract pricing verified  "
            "✓ Delivery verified"
        )


    # -----------------------------------------------------
    # RIGHT — HUMAN DECISIONS
    # -----------------------------------------------------

    with approval_column:

        st.subheader("🧑‍💼 Human Decisions")

        if not pending_requests:

            st.success(
                "✓ No approvals currently require attention."
            )

            st.caption(
                "The AI is operating within its "
                "authorised business rules."
            )

        else:

            for request in pending_requests:

                with st.container(border=True):

                    st.error(
                        "🔥 APPROVAL REQUIRED"
                    )

                    st.markdown(
                        "### Discount Request"
                    )

                    st.write(
                        f"**Customer:** {request['phone']}"
                    )

                    st.write(
                        "**Company:** Apex Engineering Pte Ltd"
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
                        "The requested discount exceeds "
                        "the AI Sales Agent's commercial "
                        "authority."
                    )

                    st.write(
                        "**Current deal:** S$4,735"
                    )

                    st.write(
                        "**Customer tier:** GOLD"
                    )

                    st.write(
                        "**Assigned sales rep:** Marcus"
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

                    # -------------------------------------------------
                    # STEP 1
                    # Record Marcus's decision in shared SQLite.
                    # -------------------------------------------------

                    result = approve_request(
                        approval_id=
                            request["approval_id"],
                        approved_percent=7,
                    )

                    if not result["success"]:

                        st.error(
                            "Approval could not be recorded."
                        )

                    else:

                        # ---------------------------------------------
                        # STEP 2
                        # Tell FastAPI that a human decision is ready.
                        #
                        # FastAPI owns the live WhatsApp SalesAgent,
                        # so FastAPI must resume that conversation.
                        # ---------------------------------------------

                        try:

                            with st.spinner(
                                "Applying approval and "
                                "updating customer on WhatsApp..."
                            ):

                                api_response = requests.post(
                                    "http://localhost:8000/process-approvals",
                                    timeout=90,
                                )

                            api_response.raise_for_status()

                            api_result = api_response.json()

                            approval_id = request[
                                "approval_id"
                            ]

                            # -----------------------------------------
                            # STEP 3
                            # Verify FastAPI actually processed THIS
                            # approval.
                            # -----------------------------------------

                            if approval_id in api_result.get(
                                "processed",
                                []
                            ):

                                st.success(
                                    "✓ 7% approved and customer "
                                    "updated on WhatsApp."
                                )

                            else:

                                skipped = api_result.get(
                                    "skipped",
                                    []
                                )

                                st.error(
                                    "The approval was recorded, "
                                    "but FastAPI did not apply it."
                                )

                                if skipped:

                                    st.write(
                                        "FastAPI response:"
                                    )

                                    st.json(
                                        skipped
                                    )

                        except requests.exceptions.ConnectionError:

                            st.error(
                                "Approval was saved, but the "
                                "WhatsApp service could not be reached. "
                                "Check that FastAPI is running on port 8000."
                            )

                        except requests.exceptions.Timeout:

                            st.error(
                                "Approval was saved, but the "
                                "WhatsApp service timed out."
                            )

                        except Exception as error:

                            st.error(
                                "Approval was saved, but an error "
                                "occurred while updating WhatsApp."
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

        if not customers_df.empty:

            customers_df = customers_df.rename(
                columns={
                    "customer_id":
                        "Customer ID",
                    "company_name":
                        "Company",
                    "contact_name":
                        "Contact",
                    "phone":
                        "Phone",
                    "account_tier":
                        "Tier",
                    "delivery_area":
                        "Delivery Area",
                    "assigned_sales_rep":
                        "Sales Rep",
                }
            )

        st.dataframe(
            customers_df,
            use_container_width=True,
            hide_index=True,
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

        delivery_display = delivery_df.rename(
            columns={
                "delivery_area":
                    "Area",
                "delivery_date":
                    "Date",
                "delivery_fee":
                    "Delivery Fee",
                "remaining_capacity":
                    "Remaining Capacity",
            }
        )

        st.dataframe(
            delivery_display,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()

        st.subheader(
            "Update Delivery Capacity"
        )

        areas = sorted(
            delivery_df[
                "delivery_area"
            ].unique()
        )

        selected_area = st.selectbox(
            "Delivery Area",
            areas,
            key="delivery_area",
        )

        available_dates = (
            delivery_df[
                delivery_df[
                    "delivery_area"
                ] == selected_area
            ]["delivery_date"]
            .tolist()
        )

        selected_date = st.selectbox(
            "Delivery Date",
            available_dates,
            key="delivery_date",
        )

        current_capacity = int(
            delivery_df[
                (
                    delivery_df[
                        "delivery_area"
                    ] == selected_area
                )
                &
                (
                    delivery_df[
                        "delivery_date"
                    ] == selected_date
                )
            ]["remaining_capacity"]
            .iloc[0]
        )

        new_capacity = st.number_input(
            "Remaining Capacity",
            min_value=0,
            value=current_capacity,
            step=1,
            key="delivery_capacity",
        )

        if st.button(
            "Update Delivery Capacity",
            key="update_delivery",
        ):

            result = (
                update_delivery_capacity(
                    selected_area,
                    selected_date,
                    int(new_capacity),
                )
            )

            if result["success"]:

                st.success(
                    "Delivery capacity updated."
                )

                st.rerun()

            else:

                st.error(
                    result["error"]
                )


# =========================================================
# TAB 3 — SALESOPS
# =========================================================

with dashboard_tab:

    st.header(
        "📊 SalesOps Command Center"
    )

    st.caption(
        "Management visibility across AI-assisted "
        "sales activity."
    )

    dashboard_1, dashboard_2, dashboard_3, dashboard_4 = (
        st.columns(4)
    )

    with dashboard_1:

        st.metric(
            "WhatsApp Enquiries",
            "47"
        )

    with dashboard_2:

        st.metric(
            "AI Resolved",
            "34",
            "72%"
        )

    with dashboard_3:

        st.metric(
            "Orders Confirmed",
            "7"
        )

    with dashboard_4:

        st.metric(
            "Revenue Generated",
            "S$18,420"
        )

    st.divider()

    st.subheader(
        "Today's Sales Activity"
    )

    activity_df = pd.DataFrame([
        {
            "Customer":
                "Apex Engineering",
            "Intent":
                "Repeat Order",
            "Value":
                "S$4,735",
            "AI Status":
                "Human Approval",
            "Owner":
                "Marcus",
        },
        {
            "Customer":
                "BrightWorks Services",
            "Intent":
                "Product Enquiry",
            "Value":
                "S$1,850",
            "AI Status":
                "Quoted",
            "Owner":
                "Sarah",
        },
        {
            "Customer":
                "Nova M&E",
            "Intent":
                "Availability",
            "Value":
                "S$820",
            "AI Status":
                "AI Resolved",
            "Owner":
                "Marcus",
        },
    ])

    st.dataframe(
        activity_df,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Dashboard metrics are seeded prototype data. "
        "Live order and conversation analytics can be "
        "persisted as the next implementation step."
    )