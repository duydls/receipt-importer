#!/usr/bin/env python3
"""
Check for products where standard_price (cost) doesn't match stock_valuation_layer.unit_cost (unit price)
"""

import sys
import csv
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def check_cost_inconsistencies(output_file: Path):
    """Find products where standard_price != stock_valuation_layer.unit_cost"""
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to database")
        return
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = """
                SELECT 
                    pp.id as product_id,
                    pt.name->>'en_US' as product_name,
                    uom.name->>'en_US' as uom_name,
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END as standard_price_cost,
                    svl.unit_cost as valuation_layer_cost,
                    svl.remaining_qty,
                    svl.remaining_value,
                    ABS(
                        CASE 
                            WHEN pp.standard_price IS NULL THEN 0
                            WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                                COALESCE((pp.standard_price->>'1')::numeric, 0)
                            ELSE 0
                        END - svl.unit_cost
                    ) as cost_difference,
                    svl.id as valuation_layer_id,
                    svl.create_date
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                JOIN stock_valuation_layer svl ON pp.id = svl.product_id
                WHERE svl.remaining_qty > 0
                  AND (
                      CASE 
                          WHEN pp.standard_price IS NULL THEN 0
                          WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                              COALESCE((pp.standard_price->>'1')::numeric, 0)
                          ELSE 0
                      END != svl.unit_cost
                  )
                ORDER BY 
                    ABS(
                        CASE 
                            WHEN pp.standard_price IS NULL THEN 0
                            WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                                COALESCE((pp.standard_price->>'1')::numeric, 0)
                            ELSE 0
                        END - svl.unit_cost
                    ) DESC,
                    pt.name->>'en_US'
            """
            
            cur.execute(query)
            inconsistencies = cur.fetchall()
            
            if inconsistencies:
                print(f"\nFound {len(inconsistencies)} products with cost inconsistencies:\n")
                print(f"{'Product Name':<50} {'UoM':<15} {'Standard Price':<15} {'Valuation Cost':<15} {'Difference':<12} {'Remaining Qty':<12}")
                print("-" * 120)
                
                total_difference = 0
                for item in inconsistencies:
                    product_name = item['product_name'] or 'Unknown'
                    if len(product_name) > 48:
                        product_name = product_name[:45] + '...'
                    
                    uom = item['uom_name'] or 'N/A'
                    std_price = item['standard_price_cost']
                    val_cost = item['valuation_layer_cost']
                    diff = item['cost_difference']
                    qty = item['remaining_qty']
                    
                    total_difference += abs(diff * qty) if qty else 0
                    
                    print(f"{product_name:<50} {uom:<15} ${std_price:<14.2f} ${val_cost:<14.2f} ${diff:<11.2f} {qty:<12.2f}")
                
                print("-" * 120)
                print(f"\nTotal value difference: ${total_difference:,.2f}")
                
                # Export to CSV
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=[
                        'product_id', 'product_name', 'uom_name', 
                        'standard_price_cost', 'valuation_layer_cost', 
                        'cost_difference', 'remaining_qty', 'remaining_value',
                        'valuation_layer_id', 'create_date'
                    ])
                    writer.writeheader()
                    for item in inconsistencies:
                        writer.writerow({
                            'product_id': item['product_id'],
                            'product_name': item['product_name'],
                            'uom_name': item['uom_name'],
                            'standard_price_cost': item['standard_price_cost'],
                            'valuation_layer_cost': item['valuation_layer_cost'],
                            'cost_difference': item['cost_difference'],
                            'remaining_qty': item['remaining_qty'],
                            'remaining_value': item['remaining_value'],
                            'valuation_layer_id': item['valuation_layer_id'],
                            'create_date': item['create_date']
                        })
                
                print(f"\nExported to: {output_file}")
            else:
                print("\n✓ No cost inconsistencies found! All products have matching standard_price and valuation_layer.unit_cost")
    
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == '__main__':
    output_file = Path(__file__).parent.parent / 'data' / 'cost_inconsistencies.csv'
    check_cost_inconsistencies(output_file)

