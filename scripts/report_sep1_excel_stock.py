#!/usr/bin/env python3
"""
Report September 1st stock (Excel imports) - products NOT in WH/walkin-storage
"""

import sys
import os
from datetime import datetime
from psycopg2.extras import RealDictCursor
import csv

# Add parent directory to path to import step3_mapping
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from step3_mapping.query_database import connect_to_database

def main():
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to database")
        return
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query stock_quant for products NOT in WH/walkin-storage
            # These should be the Excel imports from September 1st
            query = """
                SELECT 
                    pp.id as product_id,
                    pt.name->>'en_US' as product_name,
                    uom.name->>'en_US' as uom_name,
                    COALESCE(SUM(sq.quantity), 0) as total_quantity,
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END as unit_cost,
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END * COALESCE(SUM(sq.quantity), 0) as total_value
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                JOIN stock_quant sq ON pp.id = sq.product_id
                JOIN stock_location sl ON sq.location_id = sl.id
                WHERE sl.usage = 'internal'
                  AND pt.active = TRUE
                  AND sq.quantity > 0
                  AND (sq.lot_id IS NULL OR sq.lot_id = 0)
                  AND (sq.package_id IS NULL OR sq.package_id = 0)
                  AND (sq.owner_id IS NULL OR sq.owner_id = 0)
                  AND DATE(sq.in_date) <= '2025-09-01'
                  AND sl.complete_name != 'WH/walkin-storage'
                GROUP BY 
                    pp.id, 
                    pt.name, 
                    pp.standard_price,
                    uom.name
                HAVING COALESCE(SUM(sq.quantity), 0) > 0
                ORDER BY 
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END * COALESCE(SUM(sq.quantity), 0) DESC,
                    pt.name->>'en_US'
            """
            
            cur.execute(query)
            products = cur.fetchall()
            
            if products:
                print(f"\nSeptember 1st Stock (Excel Imports - NOT in WH/walkin-storage)")
                print("=" * 100)
                print(f"{'Product Name':<50} {'UoM':<20} {'Quantity':>12} {'Unit Cost':>12} {'Total Value':>15}")
                print("-" * 100)
                
                total_value = 0
                for p in products:
                    product_name = p['product_name'] or 'N/A'
                    uom_name = p['uom_name'] or 'N/A'
                    quantity = float(p['total_quantity'] or 0)
                    unit_cost = float(p['unit_cost'] or 0)
                    value = float(p['total_value'] or 0)
                    total_value += value
                    
                    print(f"{product_name:<50} {uom_name:<20} {quantity:>12.2f} ${unit_cost:>11.2f} ${value:>14.2f}")
                
                print("-" * 100)
                print(f"{'TOTAL':<72} ${total_value:>14.2f}")
                print(f"\nTotal products: {len(products)}")
                print(f"Total value: ${total_value:,.2f}")
                
                # Export to CSV
                csv_file = 'data/sep1_excel_stock.csv'
                with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['product_id', 'product_name', 'uom_name', 'quantity', 'unit_cost', 'total_value'])
                    for p in products:
                        writer.writerow([
                            p['product_id'],
                            p['product_name'],
                            p['uom_name'],
                            p['total_quantity'],
                            p['unit_cost'],
                            p['total_value']
                        ])
                
                print(f"\nExported to: {csv_file}")
            else:
                print("No products found")
    
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == '__main__':
    main()

