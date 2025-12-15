#!/usr/bin/env python3
"""
Generate October 2025 Purchase Item Analysis Report
Analyzes all purchase orders from October 2025
"""

import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def get_october_purchase_data():
    """Get all purchase order lines from October 2025"""
    conn = connect_to_database()
    if not conn:
        raise Exception("Could not connect to database")
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get all purchase order lines from October 2025
            cur.execute("""
                SELECT 
                    pol.id as line_id,
                    pol.sequence,
                    po.id as po_id,
                    po.name as po_name,
                    po.date_order,
                    po.partner_id,
                    rp.name as vendor_name,
                    pol.product_id,
                    pt.name::text as product_name,
                    pol.name as line_name,
                    pol.product_qty,
                    pol.price_unit,
                    pol.price_subtotal,
                    pol.price_total,
                    pol.product_uom,
                    uom.name::text as uom_name,
                    pt.categ_id as l2_category_id,
                    c2.name::text as l2_category_name,
                    c2.parent_id as l1_category_id,
                    c1.name::text as l1_category_name
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
                ORDER BY po.date_order, po.id, pol.sequence
            """)
            
            lines = cur.fetchall()
            return [dict(line) for line in lines]
    finally:
        conn.close()


def generate_analysis_report(lines):
    """Generate comprehensive analysis report"""
    
    if not lines:
        print("No purchase order lines found for October 2025")
        return
    
    # Convert to DataFrame
    df = pd.DataFrame(lines)
    
    # Calculate totals
    total_amount = df['price_total'].sum()
    total_items = len(df)
    total_quantity = df['product_qty'].sum()
    unique_products = df['product_id'].nunique()
    unique_vendors = df['vendor_name'].nunique()
    unique_orders = df['po_id'].nunique()
    
    print("=" * 80)
    print("OCTOBER 2025 PURCHASE ITEM ANALYSIS REPORT")
    print("=" * 80)
    print(f"\nSummary Statistics:")
    print(f"  Total Purchase Orders: {unique_orders}")
    print(f"  Total Vendors: {unique_vendors}")
    print(f"  Total Items Purchased: {total_items:,}")
    print(f"  Unique Products: {unique_products}")
    print(f"  Total Quantity: {total_quantity:,.2f}")
    print(f"  Total Amount: ${total_amount:,.2f}")
    
    # Analysis by Vendor
    print(f"\n{'=' * 80}")
    print("ANALYSIS BY VENDOR")
    print(f"{'=' * 80}")
    vendor_stats = df.groupby('vendor_name').agg({
        'po_id': 'nunique',
        'product_qty': 'sum',
        'price_total': 'sum',
        'line_id': 'count'
    }).round(2)
    vendor_stats.columns = ['Orders', 'Total Qty', 'Total Amount', 'Items']
    vendor_stats = vendor_stats.sort_values('Total Amount', ascending=False)
    print(vendor_stats.to_string())
    
    # Analysis by Category (L1)
    print(f"\n{'=' * 80}")
    print("ANALYSIS BY L1 CATEGORY")
    print(f"{'=' * 80}")
    l1_stats = df.groupby('l1_category_name').agg({
        'product_qty': 'sum',
        'price_total': 'sum',
        'line_id': 'count',
        'product_id': 'nunique'
    }).round(2)
    l1_stats.columns = ['Total Qty', 'Total Amount', 'Items', 'Unique Products']
    l1_stats = l1_stats.sort_values('Total Amount', ascending=False)
    print(l1_stats.to_string())
    
    # Analysis by Category (L2)
    print(f"\n{'=' * 80}")
    print("ANALYSIS BY L2 CATEGORY (Top 20)")
    print(f"{'=' * 80}")
    l2_stats = df.groupby('l2_category_name').agg({
        'product_qty': 'sum',
        'price_total': 'sum',
        'line_id': 'count',
        'product_id': 'nunique'
    }).round(2)
    l2_stats.columns = ['Total Qty', 'Total Amount', 'Items', 'Unique Products']
    l2_stats = l2_stats.sort_values('Total Amount', ascending=False).head(20)
    print(l2_stats.to_string())
    
    # Top Products by Amount
    print(f"\n{'=' * 80}")
    print("TOP 20 PRODUCTS BY TOTAL AMOUNT")
    print(f"{'=' * 80}")
    product_stats = df.groupby('product_name').agg({
        'product_qty': 'sum',
        'price_total': 'sum',
        'line_id': 'count',
        'vendor_name': lambda x: ', '.join(x.unique()[:3])  # First 3 vendors
    }).round(2)
    product_stats.columns = ['Total Qty', 'Total Amount', 'Orders', 'Vendors']
    product_stats = product_stats.sort_values('Total Amount', ascending=False).head(20)
    print(product_stats.to_string())
    
    # Top Products by Quantity
    print(f"\n{'=' * 80}")
    print("TOP 20 PRODUCTS BY QUANTITY")
    print(f"{'=' * 80}")
    product_qty_stats = df.groupby('product_name').agg({
        'product_qty': 'sum',
        'price_total': 'sum',
        'price_unit': 'mean',
        'line_id': 'count'
    }).round(2)
    product_qty_stats.columns = ['Total Qty', 'Total Amount', 'Avg Unit Price', 'Orders']
    product_qty_stats = product_qty_stats.sort_values('Total Qty', ascending=False).head(20)
    print(product_qty_stats.to_string())
    
    # Daily spending
    print(f"\n{'=' * 80}")
    print("DAILY SPENDING ANALYSIS")
    print(f"{'=' * 80}")
    df['date'] = pd.to_datetime(df['date_order']).dt.date
    daily_stats = df.groupby('date').agg({
        'po_id': 'nunique',
        'price_total': 'sum',
        'line_id': 'count'
    }).round(2)
    daily_stats.columns = ['Orders', 'Total Amount', 'Items']
    daily_stats = daily_stats.sort_index()
    print(daily_stats.to_string())
    
    # Save detailed Excel report
    output_file = Path('data/october_purchase_analysis.xlsx')
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        # Summary sheet
        summary_data = {
            'Metric': [
                'Total Purchase Orders',
                'Total Vendors',
                'Total Items Purchased',
                'Unique Products',
                'Total Quantity',
                'Total Amount'
            ],
            'Value': [
                unique_orders,
                unique_vendors,
                total_items,
                unique_products,
                f"{total_quantity:,.2f}",
                f"${total_amount:,.2f}"
            ]
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
        
        # All items detail
        df.to_excel(writer, sheet_name='All Items', index=False)
        
        # By vendor
        vendor_stats.to_excel(writer, sheet_name='By Vendor')
        
        # By L1 category
        l1_stats.to_excel(writer, sheet_name='By L1 Category')
        
        # By L2 category
        l2_stats_all = df.groupby('l2_category_name').agg({
            'product_qty': 'sum',
            'price_total': 'sum',
            'line_id': 'count',
            'product_id': 'nunique'
        }).round(2)
        l2_stats_all.columns = ['Total Qty', 'Total Amount', 'Items', 'Unique Products']
        l2_stats_all = l2_stats_all.sort_values('Total Amount', ascending=False)
        l2_stats_all.to_excel(writer, sheet_name='By L2 Category')
        
        # Top products by amount
        product_stats_all = df.groupby('product_name').agg({
            'product_qty': 'sum',
            'price_total': 'sum',
            'line_id': 'count',
            'vendor_name': lambda x: ', '.join(x.unique()[:5])
        }).round(2)
        product_stats_all.columns = ['Total Qty', 'Total Amount', 'Orders', 'Vendors']
        product_stats_all = product_stats_all.sort_values('Total Amount', ascending=False)
        product_stats_all.to_excel(writer, sheet_name='Top Products by Amount')
        
        # Top products by quantity
        product_qty_stats_all = df.groupby('product_name').agg({
            'product_qty': 'sum',
            'price_total': 'sum',
            'price_unit': 'mean',
            'line_id': 'count'
        }).round(2)
        product_qty_stats_all.columns = ['Total Qty', 'Total Amount', 'Avg Unit Price', 'Orders']
        product_qty_stats_all = product_stats_all.sort_values('Total Qty', ascending=False)
        product_qty_stats_all.to_excel(writer, sheet_name='Top Products by Qty')
        
        # Daily spending
        daily_stats.to_excel(writer, sheet_name='Daily Spending')
    
    print(f"\n{'=' * 80}")
    print(f"✓ Detailed Excel report saved to: {output_file}")
    print(f"{'=' * 80}")


def main():
    """Main function"""
    print("Generating October 2025 Purchase Item Analysis Report...")
    print("Querying database...")
    
    lines = get_october_purchase_data()
    generate_analysis_report(lines)


if __name__ == "__main__":
    main()

