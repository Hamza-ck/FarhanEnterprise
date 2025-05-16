import streamlit as st
import gspread
import pandas as pd
import numpy as np
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# -------------------- Google Sheets Auth --------------------
scope = ["https://spreadsheets.google.com/feeds", 
         "https://www.googleapis.com/auth/drive",
         "https://www.googleapis.com/auth/spreadsheets"]

def get_google_sheets_client():
    """Authenticate with Google Sheets using Streamlit secrets"""
    try:
        if 'gcp_service_account' not in st.secrets:
            st.error("Google Sheets credentials not found in Streamlit secrets!")
            st.info("""
                Please add your Google Service Account credentials to your Streamlit secrets.
                
                Here's how:
                1. Go to your Streamlit app's settings (when deployed) or create a `.streamlit/secrets.toml` file locally
                2. Add your service account info in this format:
                
                ```
                [gcp_service_account]
                type = "service_account"
                project_id = "your-project-id"
                private_key_id = "your-private-key-id"
                private_key = "-----BEGIN PRIVATE KEY-----\nyour-private-key\n-----END PRIVATE KEY-----"
                client_email = "your-service-account-email@your-project-id.iam.gserviceaccount.com"
                client_id = "your-client-id"
                auth_uri = "https://accounts.google.com/o/oauth2/auth"
                token_uri = "https://oauth2.googleapis.com/token"
                auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
                client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-service-account-email%40your-project-id.iam.gserviceaccount.com"
                ```
                
                3. Make sure to share your Google Sheet with your service account email!
                """)
            return None

        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            st.secrets["gcp_service_account"],
            scope
        )
        client = gspread.authorize(creds)
        return client
    
    except Exception as e:
        st.error(f"Failed to authenticate with Google Sheets: {e}")
        return None

# Initialize the client
client = get_google_sheets_client()
if client is None:
    st.stop()  # Stop execution if we can't authenticate

# The rest of your existing code continues unchanged...

# -------------------- Sheet Setup --------------------
sheet = client.open("InventoryTracker")

def get_or_create_worksheet(name, headers):
    try:
        ws = sheet.worksheet(name)
        # Check if we need to update headers for existing worksheets (to add new columns)
        if name == "stock_data":
            first_row = ws.row_values(1)
            if "Last Supplier" not in first_row:
                # We need to update the worksheet with new columns
                all_data = ws.get_all_values()
                ws.clear()
                
                # Add new headers
                ws.append_row(headers)
                
                # Add existing data with empty values for new columns
                if len(all_data) > 1:  # If there's data beyond the header
                    for row in all_data[1:]:  # Skip header
                        # Extend row to match new headers length
                        extended_row = row + [''] * (len(headers) - len(row))
                        ws.append_row(extended_row)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=name, rows="100", cols="20")
        ws.append_row(headers)
    return ws

purchase_sheet = get_or_create_worksheet("purchase_data", ["Date", "Product", "Quantity", "Unit Price", "Supplier Name", "Total Purchase"])
sales_sheet = get_or_create_worksheet("sales_data", ["Date", "Product", "Quantity", "Sale Price", "Customer Name", "Total Sale"])
expense_sheet = get_or_create_worksheet("expense_data", ["Date", "Category", "Amount", "Notes"])
stock_sheet = get_or_create_worksheet("stock_data", ["Product", "Stock In", "Stock Out", "Current Stock", "Last Supplier", "Last Stock In Date", "Last Stock Out Date"])

# -------------------- Utility Functions --------------------
def get_df(worksheet):
    try:
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df.columns = df.columns.map(str).str.strip()
        return df
    except Exception as e:
        st.error(f"⚠️ Failed to load data: {e}")
        return pd.DataFrame()

def to_numeric(df, columns):
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df

def write_row(worksheet, row):
    try:
        worksheet.append_row(row)
    except Exception as e:
        st.error(f"Failed to write row: {e}")

def update_stock(product=None, supplier=None, action_type=None, action_date=None):
    try:
        purchases = get_df(purchase_sheet)
        sales = get_df(sales_sheet)
        
        if (purchases.empty and sales.empty and not product) or not product:
            st.warning("No purchase or sales data found to update stock")
            return
            
        # Get existing stock data
        existing_stock_df = get_df(stock_sheet)
        product_row = None
        
        if not existing_stock_df.empty and 'Product' in existing_stock_df.columns:
            product_row = existing_stock_df[existing_stock_df['Product'] == product].iloc[0] if not existing_stock_df[existing_stock_df['Product'] == product].empty else None
            
        if not purchases.empty and 'Quantity' in purchases.columns:
            purchases['Quantity'] = pd.to_numeric(purchases['Quantity'], errors='coerce').fillna(0)
        
        if not sales.empty and 'Quantity' in sales.columns:
            sales['Quantity'] = pd.to_numeric(sales['Quantity'], errors='coerce').fillna(0)
        
        if product and ((purchases.empty or 'Product' not in purchases.columns) and 
                        (sales.empty or 'Product' not in sales.columns)):
            all_products = [product]
        else:
            purchase_products = purchases['Product'].unique() if not purchases.empty and 'Product' in purchases.columns else []
            sales_products = sales['Product'].unique() if not sales.empty and 'Product' in sales.columns else []
            all_products = list(set(purchase_products) | set(sales_products))
            
            if product and product not in all_products:
                all_products.append(product)
            elif product:
                all_products = [p for p in all_products if p == product]
        
        existing_stock_df = get_df(stock_sheet)
        existing_stock_dict = {}
        
        if not existing_stock_df.empty and 'Product' in existing_stock_df.columns:
            for _, row in existing_stock_df.iterrows():
                try:
                    product_key = row['Product']
                    existing_stock_dict[product_key] = {
                        'Stock In': row.get('Stock In', 0) if 'Stock In' in row else 0,
                        'Stock Out': row.get('Stock Out', 0) if 'Stock Out' in row else 0,
                        'Current Stock': row.get('Current Stock', 0) if 'Current Stock' in row else 0,
                        'Last Supplier': row.get('Last Supplier', '') if 'Last Supplier' in row else '',
                        'Last Stock In Date': row.get('Last Stock In Date', '') if 'Last Stock In Date' in row else '',
                        'Last Stock Out Date': row.get('Last Stock Out Date', '') if 'Last Stock Out Date' in row else ''
                    }
                except Exception as e:
                    st.error(f"Error processing existing stock: {e}")
        
        if not all_products and product:
            all_products = [product]
            
        stock_data = []
        
        for prod in all_products:
            if not prod or pd.isna(prod) or prod == '':
                continue
                
            if not purchases.empty and 'Product' in purchases.columns and 'Quantity' in purchases.columns:
                stock_in = purchases[purchases['Product'] == prod]['Quantity'].sum()
            else:
                stock_in = 0
                
            if not sales.empty and 'Product' in sales.columns and 'Quantity' in sales.columns:
                stock_out = sales[sales['Product'] == prod]['Quantity'].sum()
            else:
                stock_out = 0
                  # Only update the specific product that was purchased/sold
            if prod == product:
                if action_type == 'in':
                    # For purchases, add to existing stock in
                    existing_stock_in = existing_stock_dict.get(prod, {}).get('Stock In', 0)
                    stock_in = existing_stock_in + int(qty) if 'qty' in locals() else int(stock_in)
                    stock_out = existing_stock_dict.get(prod, {}).get('Stock Out', 0)
                else:
                    # For sales, add to existing stock out
                    existing_stock_out = existing_stock_dict.get(prod, {}).get('Stock Out', 0)
                    stock_out = existing_stock_out + int(qty) if 'qty' in locals() else int(stock_out)
                    stock_in = existing_stock_dict.get(prod, {}).get('Stock In', 0)
                
                current_stock = stock_in - stock_out
                
                existing_data = existing_stock_dict.get(prod, {})
                last_supplier = supplier if action_type == 'in' and supplier else existing_data.get('Last Supplier', '')
                last_stock_in_date = action_date if action_type == 'in' else existing_data.get('Last Stock In Date', '')
                last_stock_out_date = action_date if action_type == 'out' else existing_data.get('Last Stock Out Date', '')
                
            stock_data.append([
                prod, 
                int(stock_in), 
                int(stock_out), 
                int(current_stock),
                last_supplier,
                last_stock_in_date,
                last_stock_out_date
            ])
        
        stock_df = pd.DataFrame(
            stock_data, 
            columns=["Product", "Stock In", "Stock Out", "Current Stock", 
                    "Last Supplier", "Last Stock In Date", "Last Stock Out Date"]
        )
        
        if not stock_df.empty:
            stock_sheet.clear()
            stock_sheet.append_row(stock_df.columns.tolist())
            
            for row in stock_df.values.tolist():
                formatted_row = []
                for item in row:
                    if isinstance(item, (np.int64, int, float)) and not np.isnan(item):
                        formatted_row.append(int(item))
                    else:
                        formatted_row.append(item)
                stock_sheet.append_row(formatted_row)
    except Exception as e:
        st.error(f"Error updating stock: {e}")
        import traceback
        st.error(traceback.format_exc())

def get_product_stock():
    df = get_df(stock_sheet)
    if "Product" in df.columns and "Current Stock" in df.columns:
        return df.set_index("Product")["Current Stock"].to_dict()
    return {}

def get_product_details():
    df = get_df(stock_sheet)
    if df.empty:
        return {}
    
    product_details = {}
    for _, row in df.iterrows():
        try:
            product = row['Product']
            product_details[product] = {
                'Current Stock': row.get('Current Stock', 0) if 'Current Stock' in row else 0,
                'Last Supplier': row.get('Last Supplier', '') if 'Last Supplier' in row else '',
                'Last Stock In Date': row.get('Last Stock In Date', '') if 'Last Stock In Date' in row else '',
                'Last Stock Out Date': row.get('Last Stock Out Date', '') if 'Last Stock Out Date' in row else ''
            }
        except Exception as e:
            continue
    
    return product_details

def filter_data_by_date(df, start_date, end_date):
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)
        return df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
    return df

def calculate_total(df, column):
    """
    Safely calculate total for a given column, handling empty dataframes and non-numeric values.
    Returns 0 if there are no records or if column doesn't exist.
    """
    if df.empty or column not in df.columns:
        return 0
    
    # Convert column to numeric, invalid values become NaN
    df[column] = pd.to_numeric(df[column], errors='coerce')
    # Sum up all valid numeric values, NaN values are ignored
    return df[column].sum()

def calculate_total_expenses(expenses_df):
    """
    Safely calculate total expenses, handling empty dataframes and non-numeric values.
    Returns 0 if there are no expenses or if Amount column doesn't exist.
    """
    return calculate_total(expenses_df, 'Amount')

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="Inventory Tracker", layout="wide")
st.title("📦 Inventory Tracker")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Dashboard", "🛒 Purchase", "💸 Sales", "📁 Expense", "📦 Stock"])

# -------------------- Tab 1: Dashboard --------------------
with tab1:
    st.header("Overview Dashboard")
    start_date = st.date_input("Start Date", value=datetime.today().replace(day=1))
    end_date = st.date_input("End Date", value=datetime.today())

    start_date = datetime.combine(start_date, datetime.min.time())
    end_date = datetime.combine(end_date, datetime.min.time())    
    purchases = filter_data_by_date(get_df(purchase_sheet), start_date, end_date)
    sales = filter_data_by_date(get_df(sales_sheet), start_date, end_date)
    expenses = filter_data_by_date(get_df(expense_sheet), start_date, end_date)
    
    # Convert numeric columns
    purchases = to_numeric(purchases, ['Total Purchase', 'Unit Price', 'Quantity'])
    sales = to_numeric(sales, ['Total Sale', 'Sale Price', 'Quantity'])

    # Calculate totals safely
    total_purchase = calculate_total(purchases, 'Total Purchase')
    total_sales = calculate_total(sales, 'Total Sale')
    total_expense = calculate_total_expenses(expenses)
    total_qty_sold = calculate_total(sales, 'Quantity')

    total_profit = 0
    product_metrics = {}
    
    if not sales.empty and not purchases.empty:
        for _, sale in sales.iterrows():
            product = sale['Product']
            if product not in product_metrics:
                product_metrics[product] = {
                    'qty_sold': 0,
                    'total_sales': 0,
                    'total_profit': 0,
                    'last_purchase_price': 0,
                    'last_sale_price': 0
                }
            
            relevant_purchases = purchases[
                (purchases['Product'] == sale['Product']) & 
                (pd.to_datetime(purchases['Date']) <= pd.to_datetime(sale['Date']))
            ]
            if not relevant_purchases.empty:
                unit_price = relevant_purchases.iloc[-1]['Unit Price']
                sale_profit = (sale['Sale Price'] - unit_price) * sale['Quantity']
                total_profit += sale_profit
                
                product_metrics[product]['qty_sold'] += sale['Quantity']
                product_metrics[product]['total_sales'] += sale['Total Sale']
                product_metrics[product]['total_profit'] += sale_profit
                product_metrics[product]['last_purchase_price'] = unit_price
                product_metrics[product]['last_sale_price'] = sale['Sale Price']

    net_profit = total_profit - total_expense    
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("💰 Total Sales", f"₹{total_sales:.2f}")
    col2.metric("🛒 Total Purchase", f"₹{total_purchase:.2f}")
    col3.metric("💸 Expenses", f"₹{total_expense:.2f}")
    col4.metric("📈 Net Profit", f"₹{net_profit:.2f}")
    col5.metric("📦 Total Qty Sold", f"{int(total_qty_sold)}")

    st.subheader("Product Profitability Analysis")
    if product_metrics:
        metrics_df = pd.DataFrame.from_dict(product_metrics, orient='index')
        metrics_df = metrics_df.reset_index()
        metrics_df.columns = ['Product', 'Qty Sold', 'Total Sales', 'Total Profit', 'Purchase Price', 'Sale Price']
        metrics_df = metrics_df.sort_values('Total Profit', ascending=False)
        
        for col in ['Total Sales', 'Total Profit', 'Purchase Price', 'Sale Price']:
            metrics_df[col] = metrics_df[col].apply(lambda x: f"₹{x:.2f}")
        
        st.dataframe(metrics_df)

# -------------------- Tab 2: Purchase --------------------
with tab2:
    st.header("Add Purchase Entry")
    with st.form("purchase_form"):
        date = st.date_input("Date", value=datetime.today())
        product = st.text_input("Product Name")
        qty = st.number_input("Quantity", min_value=1)
        unit_price = st.number_input("Unit Price (₹)", min_value=1)
        supplier_name = st.text_input("Supplier Name")
        total_purchase = qty * unit_price
        submit = st.form_submit_button("Add Purchase")
        
        if submit:
            if not product or not supplier_name:
                st.error("⚠️ Product name and supplier name cannot be empty")            
            else:
                try:
                    # First record the purchase
                    write_row(purchase_sheet, [str(date), product, qty, unit_price, supplier_name, total_purchase])
                    
                    # Get current stock status
                    current_stock_df = get_df(stock_sheet)
                    current_row = None if current_stock_df.empty else current_stock_df[current_stock_df['Product'] == product]
                    
                    if current_row is None or current_row.empty:
                        # New product - add initial stock entry
                        write_row(stock_sheet, [product, qty, 0, qty, supplier_name, str(date), ""])
                    else:
                        # Existing product - update stock
                        current_stock_in = current_row['Stock In'].iloc[0]
                        current_stock_out = current_row['Stock Out'].iloc[0]
                        new_stock_in = current_stock_in + qty
                        new_current_stock = new_stock_in - current_stock_out
                        
                        # Update existing row
                        idx = current_row.index[0]
                        current_stock_df.loc[idx, 'Stock In'] = new_stock_in
                        current_stock_df.loc[idx, 'Current Stock'] = new_current_stock
                        current_stock_df.loc[idx, 'Last Supplier'] = supplier_name
                        current_stock_df.loc[idx, 'Last Stock In Date'] = str(date)
                        
                        # Save updated stock data
                        stock_sheet.clear()
                        stock_sheet.append_row(current_stock_df.columns.tolist())
                        for row in current_stock_df.values.tolist():
                            stock_sheet.append_row([str(item) for item in row])
                        
                    st.success("✅ Purchase recorded!")
                except Exception as e:
                    st.error(f"Error recording purchase: {e}")
                    import traceback
                    st.error(traceback.format_exc())

# -------------------- Tab 3: Sales --------------------
with tab3:
    st.header("Add Sale Entry")
    
    # Get fresh product details
    stock_df = get_df(stock_sheet)
    
    if not stock_df.empty:
        # Make sure Current Stock is numeric
        stock_df['Current Stock'] = pd.to_numeric(stock_df['Current Stock'], errors='coerce').fillna(0)
        
        # Filter products with stock > 0
        available_products = stock_df[stock_df['Current Stock'] > 0]
        
        if not available_products.empty:
            product_list = available_products['Product'].tolist()
            
            # Format function to show stock and supplier info
            def format_func(p):
                row = available_products[available_products['Product'] == p].iloc[0]
                stock = int(row['Current Stock'])
                supplier = row['Last Supplier'] if pd.notna(row['Last Supplier']) else 'Unknown'
                return f"{p} (Stock: {stock}, Supplier: {supplier})"
            
            # Product selection
            selected_product = st.selectbox(
                "Select Product",
                product_list,
                format_func=format_func
            )
            
            if selected_product:
                # Get current product details
                product_data = available_products[available_products['Product'] == selected_product].iloc[0]
                current_stock = int(product_data['Current Stock'])
                supplier = product_data['Last Supplier'] if pd.notna(product_data['Last Supplier']) else 'Unknown'
                last_stock_date = product_data['Last Stock In Date'] if pd.notna(product_data['Last Stock In Date']) else 'N/A'
                
                # Display product details
                st.info(f"""
                Product: {selected_product}
                Current Stock: {current_stock}
                Last Supplier: {supplier}
                Last Stocked: {last_stock_date}
                """)
                
                with st.form("sales_form"):
                    qty = st.number_input("Quantity", min_value=1, max_value=current_stock)
                    price = st.number_input("Price (₹)", min_value=0.0)
                    date = st.date_input("Date", datetime.now())
                    customer_name = st.text_input("Customer Name")
                    
                    total_sale = qty * price
                    st.write(f"Total Sale Amount: ₹{total_sale:.2f}")
                    
                    submit = st.form_submit_button("Submit Sale")
                    if submit:
                        if not customer_name:
                            st.error("Please enter customer name")
                        else:
                            # Record the sale
                            write_row(sales_sheet, [str(date), selected_product, qty, price, customer_name, total_sale])
                            
                            # Update stock
                            update_stock(product=selected_product, action_type='out', action_date=str(date))
                            st.success("Sale recorded successfully!")
                            st.rerun()
        else:
            st.warning("No products with available stock found.")
    else:
        st.info("No products available. Please add stock first.")

# -------------------- Tab 4: Expense --------------------
with tab4:
    st.header("Add Expense Entry")
    with st.form("expense_form"):
        date = st.date_input("Date", value=datetime.today(), key="expense_date")
        category = st.text_input("Expense Category")
        amount = st.number_input("Amount (₹)", min_value=1)
        notes = st.text_input("Notes")
        submit = st.form_submit_button("Add Expense")
        if submit:
            if not category:
                st.error("⚠️ Expense category cannot be empty")
            else:
                write_row(expense_sheet, [str(date), category, amount, notes])
                st.success("✅ Expense recorded!")

# -------------------- Tab 5: Stock (Edit/Delete) --------------------
with tab5:
    st.header("Stock Overview + Edit/Delete")
    stock_df = get_df(stock_sheet)

    if not stock_df.empty:
        stock_df["Current Stock"] = pd.to_numeric(stock_df["Current Stock"], errors="coerce").fillna(0)

        edited_df = st.data_editor(
            stock_df,
            num_rows="dynamic",
            use_container_width=True,
            key="stock_editor"
        )

        if st.button("💾 Save Changes"):
            original_products = set(stock_df["Product"])
            edited_products = set(edited_df["Product"])
            deleted_products = original_products - edited_products

            if deleted_products:
                edited_df = edited_df[~edited_df["Product"].isin(deleted_products)]

            stock_sheet.clear()
            stock_sheet.append_row(edited_df.columns.tolist())
            for row in edited_df.values.tolist():
                stock_sheet.append_row([str(item) for item in row])

            st.success("✅ Stock updated successfully!")

        low_stock = stock_df[stock_df["Current Stock"] <= 5]
        if not low_stock.empty:
            st.warning("⚠️ Low Stock Alert")
            st.dataframe(low_stock[["Product", "Current Stock", "Last Supplier"]])
            
        st.subheader("Stock Movement History")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("Recent Purchases")
            recent_purchases = get_df(purchase_sheet)
            if not recent_purchases.empty:
                recent_purchases = recent_purchases.sort_values(by="Date", ascending=False).head(100)
                display_purchases = recent_purchases[["Date", "Product", "Quantity", "Unit Price", "Total Purchase", "Supplier Name"]]
                display_purchases["Unit Price"] = display_purchases["Unit Price"].apply(lambda x: f"₹{x:.2f}")
                display_purchases["Total Purchase"] = display_purchases["Total Purchase"].apply(lambda x: f"₹{x:.2f}")
                st.dataframe(display_purchases)
            else:
                st.info("No purchase history yet")
                
        with col2:
            st.write("Recent Sales")
            recent_sales = get_df(sales_sheet)
            if not recent_sales.empty:
                recent_sales = recent_sales.sort_values(by="Date", ascending=False).head(100)
                display_sales = recent_sales[["Date", "Product", "Quantity", "Sale Price", "Total Sale", "Customer Name"]]
                display_sales["Sale Price"] = display_sales["Sale Price"].apply(lambda x: f"₹{x:.2f}")
                display_sales["Total Sale"] = display_sales["Total Sale"].apply(lambda x: f"₹{x:.2f}")
                st.dataframe(display_sales)
            else:
                st.info("No sales history yet")
    else:
        st.info("📭 No stock data yet. Add purchase or sales entries first.")