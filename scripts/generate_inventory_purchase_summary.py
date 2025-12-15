#!/usr/bin/env python3
"""
Generate Inventory Purchase Summary Report for October 2025
Focuses on products, quantities, vendors, and dates for inventory management
"""

import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import pandas as pd
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def get_inventory_purchase_data():
    """Get purchase data with inventory-relevant information"""
    conn = connect_to_database()
    if not conn:
        raise Exception("Could not connect to database")
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get purchase order lines with product and inventory info
            cur.execute("""
                SELECT 
                    pol.id as line_id,
                    po.id as po_id,
                    po.name as po_name,
                    po.date_order,
                    rp.name as vendor_name,
                    pol.product_id,
                    pt.name::text as product_name,
                    pt.default_code as product_code,
                    pol.product_qty,
                    pol.price_unit,
                    pol.price_subtotal,
                    pol.product_uom,
                    uom.name::text as uom_name,
                    pt.categ_id as l2_category_id,
                    c2.name::text as l2_category_name,
                    c2.parent_id as l1_category_id,
                    c1.name::text as l1_category_name,
                    pt.type as product_type,
                    pt.purchase_ok as purchase_ok,
                    pt.sale_ok as sale_ok
                FROM purchase_order_line pol
                JOIN purchase_order po ON pol.order_id = po.id
                LEFT JOIN res_partner rp ON po.partner_id = rp.id
                LEFT JOIN product_product pp ON pol.product_id = pp.id
                LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pol.product_uom = uom.id
                LEFT JOIN product_category c2 ON pt.categ_id = c2.id
                LEFT JOIN product_category c1 ON c2.parent_id = c1.id
                WHERE po.date_order >= '2025-10-01' 
                  AND po.date_order < '2025-11-01'
                  AND pol.display_type IS NULL  -- Exclude section headers
                  AND (pt.type IN ('product', 'consu') OR pt.type IS NULL)  -- Physical products and consumables (exclude services)
                ORDER BY pt.name::text, po.date_order
            """)
            
            lines = cur.fetchall()
            return [dict(line) for line in lines]
    finally:
        conn.close()


def get_product_stock_levels(product_ids):
    """Get current stock levels for products"""
    if not product_ids:
        return {}
    
    conn = connect_to_database()
    if not conn:
        return {}
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get stock levels from stock_quant
            cur.execute("""
                SELECT 
                    product_id,
                    SUM(quantity) as qty_available,
                    SUM(reserved_quantity) as qty_reserved
                FROM stock_quant
                WHERE product_id = ANY(%s)
                GROUP BY product_id
            """, (list(product_ids),))
            
            results = cur.fetchall()
            stock_levels = {}
            for row in results:
                stock_levels[row['product_id']] = {
                    'qty_available': float(row['qty_available'] or 0),
                    'qty_reserved': float(row['qty_reserved'] or 0),
                    'qty_on_hand': float(row['qty_available'] or 0) - float(row['qty_reserved'] or 0)
                }
            return stock_levels
    finally:
        conn.close()


def extract_english_text(value):
    """Extract English text from JSON field like {"en_US": "Text"} or return as-is if already string"""
    if pd.isna(value) or value is None:
        return ''
    if isinstance(value, str):
        # Try to parse as JSON
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                # Try en_US first, then en, then first value
                return parsed.get('en_US') or parsed.get('en') or (list(parsed.values())[0] if parsed else '')
            return str(parsed)
        except (json.JSONDecodeError, ValueError):
            # Not JSON, return as-is
            return value
    return str(value)


def generate_inventory_summary(lines):
    """Generate inventory-focused purchase summary"""
    
    if not lines:
        print("No purchase order lines found for October 2025")
        return
    
    # Convert to DataFrame
    df = pd.DataFrame(lines)
    
    # Extract English text from JSON fields
    df['product_name'] = df['product_name'].apply(extract_english_text)
    df['uom_name'] = df['uom_name'].apply(extract_english_text)
    
    # Convert numeric columns
    df['product_qty'] = pd.to_numeric(df['product_qty'], errors='coerce').fillna(0)
    df['price_unit'] = pd.to_numeric(df['price_unit'], errors='coerce').fillna(0)
    df['price_subtotal'] = pd.to_numeric(df['price_subtotal'], errors='coerce').fillna(0)
    
    # Get stock levels for all products
    product_ids = df['product_id'].unique().tolist()
    print(f"Fetching stock levels for {len(product_ids)} products...")
    stock_levels = get_product_stock_levels(product_ids)
    
    # Add stock information to dataframe
    df['qty_available'] = df['product_id'].map(lambda x: stock_levels.get(x, {}).get('qty_available', 0))
    df['qty_reserved'] = df['product_id'].map(lambda x: stock_levels.get(x, {}).get('qty_reserved', 0))
    df['qty_on_hand'] = df['product_id'].map(lambda x: stock_levels.get(x, {}).get('qty_on_hand', 0))
    
    # Convert date_order to date
    df['date'] = pd.to_datetime(df['date_order']).dt.date
    
    # Fill nulls in groupby columns
    df['product_code'] = df['product_code'].fillna('')
    df['l1_category_name'] = df['l1_category_name'].fillna('Unknown')
    
    # Product Summary - aggregated by product
    print("\nGenerating product summary...")
    product_summary = df.groupby(['product_id', 'product_name', 'product_code', 'uom_name', 
                                   'l1_category_name', 'l2_category_name']).agg({
        'product_qty': ['sum', 'count'],
        'price_subtotal': 'sum',
        'price_unit': 'mean',
        'vendor_name': lambda x: ', '.join(x.unique()),
        'date': ['min', 'max'],
        'qty_available': 'first',
        'qty_reserved': 'first',
        'qty_on_hand': 'first'
    }).round(2)
    
    # Flatten column names
    product_summary.columns = ['Total_Qty_Purchased', 'Purchase_Orders', 'Total_Amount', 
                               'Avg_Unit_Price', 'Vendors', 'First_Purchase_Date', 
                               'Last_Purchase_Date', 'Qty_Available', 'Qty_Reserved', 'Qty_On_Hand']
    product_summary = product_summary.reset_index()
    product_summary = product_summary.sort_values('Total_Qty_Purchased', ascending=False)
    
    # Vendor Summary - by product
    print("Generating vendor summary...")
    vendor_product_summary = df.groupby(['vendor_name', 'product_name', 'uom_name']).agg({
        'product_qty': 'sum',
        'price_subtotal': 'sum',
        'price_unit': 'mean',
        'date': ['min', 'max'],
        'po_id': 'nunique'
    }).round(2)
    vendor_product_summary.columns = ['Total_Qty', 'Total_Amount', 'Avg_Unit_Price', 
                                      'First_Purchase', 'Last_Purchase', 'Orders']
    vendor_product_summary = vendor_product_summary.reset_index()
    vendor_product_summary = vendor_product_summary.sort_values(['vendor_name', 'Total_Qty'], ascending=[True, False])
    
    # Category Summary
    print("Generating category summary...")
    category_summary = df.groupby(['l1_category_name', 'l2_category_name']).agg({
        'product_id': 'nunique',
        'product_qty': 'sum',
        'price_subtotal': 'sum',
        'line_id': 'count'
    }).round(2)
    category_summary.columns = ['Unique_Products', 'Total_Qty', 'Total_Amount', 'Total_Lines']
    category_summary = category_summary.reset_index()
    category_summary = category_summary.sort_values('Total_Amount', ascending=False)
    
    # Daily Purchase Summary
    print("Generating daily summary...")
    daily_summary = df.groupby('date').agg({
        'product_id': 'nunique',
        'product_qty': 'sum',
        'price_subtotal': 'sum',
        'po_id': 'nunique',
        'line_id': 'count'
    }).round(2)
    daily_summary.columns = ['Unique_Products', 'Total_Qty', 'Total_Amount', 'Orders', 'Items']
    daily_summary = daily_summary.reset_index()
    
    # Low Stock Alert (products with low on-hand quantity)
    print("Generating low stock analysis...")
    # Ensure numeric types
    product_summary['Qty_On_Hand'] = pd.to_numeric(product_summary['Qty_On_Hand'], errors='coerce').fillna(0)
    product_summary['Total_Qty_Purchased'] = pd.to_numeric(product_summary['Total_Qty_Purchased'], errors='coerce').fillna(0)
    
    low_stock = product_summary[
        (product_summary['Qty_On_Hand'] < product_summary['Total_Qty_Purchased'] * 0.2) &
        (product_summary['Total_Qty_Purchased'] > 0)
    ].copy()
    low_stock['Stock_Ratio'] = (low_stock['Qty_On_Hand'] / low_stock['Total_Qty_Purchased'].replace(0, 1)).round(2)
    low_stock = low_stock.sort_values('Stock_Ratio')
    
    # Save to Excel
    output_file = Path('data/inventory_purchase_summary.xlsx')
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"\nSaving report to {output_file}...")
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Product Summary (main inventory view)
        product_summary.to_excel(writer, sheet_name='Product Summary', index=False)
        
        # All Purchase Details
        df_export = df[[
            'date', 'po_name', 'vendor_name', 'product_name', 'product_code',
            'product_qty', 'uom_name', 'price_unit', 'price_subtotal',
            'l1_category_name', 'l2_category_name'
        ]].copy()
        df_export = df_export.sort_values(['product_name', 'date'])
        df_export.to_excel(writer, sheet_name='All Purchases', index=False)
        
        # Vendor-Product Summary
        vendor_product_summary.to_excel(writer, sheet_name='By Vendor & Product', index=False)
        
        # Category Summary
        category_summary.to_excel(writer, sheet_name='By Category', index=False)
        
        # Daily Summary
        daily_summary.to_excel(writer, sheet_name='Daily Summary', index=False)
        
        # Low Stock Alert
        if len(low_stock) > 0:
            low_stock.to_excel(writer, sheet_name='Low Stock Alert', index=False)
        
        # Product Reorder Analysis (products purchased multiple times)
        reorder_analysis = product_summary[product_summary['Purchase_Orders'] > 1].copy()
        reorder_analysis = reorder_analysis.sort_values('Purchase_Orders', ascending=False)
        reorder_analysis.to_excel(writer, sheet_name='Reorder Analysis', index=False)
    
    # Print summary statistics
    print("\n" + "=" * 80)
    print("INVENTORY PURCHASE SUMMARY - OCTOBER 2025")
    print("=" * 80)
    print(f"\nTotal Products Purchased: {len(product_summary)}")
    print(f"Total Quantity Purchased: {product_summary['Total_Qty_Purchased'].sum():,.2f}")
    print(f"Total Amount: ${product_summary['Total_Amount'].sum():,.2f}")
    print(f"Products with Low Stock: {len(low_stock)}")
    print(f"Products Reordered (2+ times): {len(reorder_analysis)}")
    
    print(f"\n{'=' * 80}")
    print("TOP 10 PRODUCTS BY QUANTITY PURCHASED")
    print(f"{'=' * 80}")
    top_products = product_summary.head(10)[['product_name', 'Total_Qty_Purchased', 'uom_name', 
                                              'Total_Amount', 'Qty_On_Hand', 'Vendors']]
    print(top_products.to_string(index=False))
    
    if len(low_stock) > 0:
        print(f"\n{'=' * 80}")
        print("LOW STOCK ALERT (Top 10)")
        print(f"{'=' * 80}")
        low_stock_top = low_stock.head(10)[['product_name', 'Total_Qty_Purchased', 'Qty_On_Hand', 
                                            'Stock_Ratio', 'uom_name']]
        print(low_stock_top.to_string(index=False))
    
    print(f"\n{'=' * 80}")
    print(f"✓ Report saved to: {output_file}")
    print(f"{'=' * 80}")


def main():
    """Main function"""
    print("Generating Inventory Purchase Summary for October 2025...")
    print("Querying database...")
    
    lines = get_inventory_purchase_data()
    generate_inventory_summary(lines)


if __name__ == "__main__":
    main()

