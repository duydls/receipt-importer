#!/usr/bin/env python3
"""
Generate Inventory Purchase Summary from Odoo Database
Summarizes October 2025 purchase orders by product:
- Product name
- Total purchased quantity
- UoM
- Average cost (mathematical mean)
- Vendors that supply this item
"""

import sys
from pathlib import Path
import json
from collections import defaultdict
from decimal import Decimal

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor
import pandas as pd


def extract_english_text(value):
    """Extract English text from JSON-encoded values"""
    if not value:
        return ''
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed.get('en_US') or parsed.get('en') or (list(parsed.values())[0] if parsed else '')
            return str(parsed)
        except (json.JSONDecodeError, ValueError):
            return value
    return str(value)


def generate_inventory_summary(output_path: Path = None):
    """
    Generate inventory purchase summary from Odoo October purchase orders
    
    Args:
        output_path: Path to save the summary (CSV and Excel). If None, saves to project root.
    """
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to Odoo database")
        return None
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query October 2025 purchase orders with product details
            cur.execute("""
                SELECT 
                    pt.name::text as product_name,
                    pol.product_qty,
                    pol.price_unit,
                    pol.price_subtotal,
                    uom.name::text as uom_name,
                    rp.name as vendor_name,
                    po.name as po_name,
                    po.date_order
                FROM purchase_order po
                LEFT JOIN res_partner rp ON po.partner_id = rp.id
                LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
                LEFT JOIN product_product pp ON pol.product_id = pp.id
                LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pol.product_uom = uom.id
                WHERE po.date_order >= '2025-10-01' 
                  AND po.date_order < '2025-11-01'
                  AND pol.display_type IS NULL
                  AND (pt.type IN ('product', 'consu', 'service') OR pt.type IS NULL)
                  AND pol.product_qty > 0
                ORDER BY pt.name::text, po.date_order
            """)
            
            rows = cur.fetchall()
            
            if not rows:
                print("No purchase order lines found for October 2025")
                return None
            
            # Aggregate by product
            product_summary = defaultdict(lambda: {
                'total_qty': Decimal('0'),
                'total_cost': Decimal('0'),
                'line_count': 0,
                'uom': set(),
                'vendors': set(),
                'price_units': []  # For calculating average
            })
            
            for row in rows:
                product_name = extract_english_text(row['product_name'])
                if not product_name:
                    continue
                
                qty = Decimal(str(row['product_qty'] or 0))
                price_unit = Decimal(str(row['price_unit'] or 0))
                uom_name = extract_english_text(row['uom_name']) or 'Unknown'
                vendor_name = extract_english_text(row['vendor_name']) if row['vendor_name'] else 'Unknown'
                
                product_summary[product_name]['total_qty'] += qty
                product_summary[product_name]['total_cost'] += Decimal(str(row['price_subtotal'] or 0))
                product_summary[product_name]['line_count'] += 1
                product_summary[product_name]['uom'].add(uom_name)
                product_summary[product_name]['vendors'].add(vendor_name)
                if price_unit > 0:
                    product_summary[product_name]['price_units'].append(float(price_unit))
            
            # Build summary data
            summary_data = []
            for product_name, data in sorted(product_summary.items()):
                # Calculate average cost (mathematical mean of price_unit)
                if data['price_units']:
                    avg_cost = sum(data['price_units']) / len(data['price_units'])
                else:
                    avg_cost = 0.0
                
                # Handle multiple UoMs (should be rare, but possible)
                uom_str = ', '.join(sorted(data['uom'])) if len(data['uom']) > 1 else (list(data['uom'])[0] if data['uom'] else 'Unknown')
                
                # List vendors
                vendors_str = ', '.join(sorted(data['vendors']))
                
                summary_data.append({
                    'Product Name': product_name,
                    'Total Purchased QTY': float(data['total_qty']),
                    'UoM': uom_str,
                    'Average Cost': round(avg_cost, 2),
                    'Vendors': vendors_str,
                    'Purchase Lines': data['line_count'],
                    'Total Cost': float(data['total_cost'])
                })
            
            # Create DataFrame
            df = pd.DataFrame(summary_data)
            
            # Set output path
            if output_path is None:
                output_path = project_root / 'data' / 'step1_output' / 'artifacts' / 'odoo_inventory_summary'
            output_path = Path(output_path)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Save as CSV
            csv_file = output_path / 'odoo_october_inventory_summary.csv'
            df.to_csv(csv_file, index=False)
            print(f"✅ Saved CSV: {csv_file}")
            
            # Save as Excel
            excel_file = output_path / 'odoo_october_inventory_summary.xlsx'
            with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Inventory Summary', index=False)
                
                # Auto-adjust column widths
                worksheet = writer.sheets['Inventory Summary']
                for idx, col in enumerate(df.columns):
                    max_length = max(
                        df[col].astype(str).map(len).max(),
                        len(col)
                    ) + 2
                    worksheet.column_dimensions[chr(65 + idx)].width = min(max_length, 50)
            
            print(f"✅ Saved Excel: {excel_file}")
            
            # Print summary statistics
            print(f"\n📊 Summary Statistics:")
            print(f"   Total unique products: {len(summary_data)}")
            print(f"   Total purchase lines: {sum(df['Purchase Lines'])}")
            print(f"   Total quantity purchased: {df['Total Purchased QTY'].sum():,.2f}")
            print(f"   Total cost: ${df['Total Cost'].sum():,.2f}")
            print(f"   Average cost per product: ${df['Average Cost'].mean():.2f}")
            
            return df
            
    except Exception as e:
        print(f"ERROR: {e}", exc_info=True)
        return None
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate Odoo inventory purchase summary for October 2025')
    parser.add_argument('--output', '-o', type=Path, help='Output directory path (default: data/step1_output/artifacts/odoo_inventory_summary)')
    
    args = parser.parse_args()
    
    generate_inventory_summary(args.output)

