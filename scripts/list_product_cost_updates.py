#!/usr/bin/env python3
"""
List all products that will have their cost updated based on purchase history
Shows: product name, UoM, original price, new price (average from purchases)
"""

import sys
import csv
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def list_cost_updates(output_file: Path):
    """List products with current and new average prices"""
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to database")
        return
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = """
                SELECT 
                    pol.product_id,
                    pt.name->>'en_US' as product_name,
                    uom.name->>'en_US' as uom_name,
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END as original_price,
                    -- Convert price from purchase UoM to product base UoM
                    AVG(
                        CASE 
                            WHEN pol.product_qty > 0 AND pol.product_uom_qty > 0 THEN
                                pol.price_unit / (pol.product_uom_qty / pol.product_qty)
                            ELSE pol.price_unit
                        END
                    ) as new_price,
                    COUNT(*) as purchase_count,
                    MIN(
                        CASE 
                            WHEN pol.product_qty > 0 AND pol.product_uom_qty > 0 THEN
                                pol.price_unit / (pol.product_uom_qty / pol.product_qty)
                            ELSE pol.price_unit
                        END
                    ) as min_price,
                    MAX(
                        CASE 
                            WHEN pol.product_qty > 0 AND pol.product_uom_qty > 0 THEN
                                pol.price_unit / (pol.product_uom_qty / pol.product_qty)
                            ELSE pol.price_unit
                        END
                    ) as max_price,
                    SUM(pol.product_uom_qty) as total_qty_purchased
                FROM purchase_order_line pol
                JOIN purchase_order po ON pol.order_id = po.id
                JOIN product_product pp ON pol.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                WHERE po.state = 'done'
                  AND pol.price_unit > 0
                GROUP BY 
                    pol.product_id, 
                    pt.name, 
                    pp.standard_price,
                    uom.name
                HAVING COUNT(*) > 0
                ORDER BY 
                    ABS(AVG(
                        CASE 
                            WHEN pol.product_qty > 0 AND pol.product_uom_qty > 0 THEN
                                pol.price_unit / (pol.product_uom_qty / pol.product_qty)
                            ELSE pol.price_unit
                        END
                    ) - COALESCE(
                        CASE 
                            WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                                (pp.standard_price->>'1')::numeric
                            ELSE 0
                        END, 0
                    )) DESC,
                    pt.name->>'en_US'
            """
            
            cur.execute(query)
            products = cur.fetchall()
            
            if not products:
                print("No products with purchase history found")
                return
            
            # Write to CSV
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = [
                    'product_id', 'product_name', 'uom_name', 
                    'original_price', 'new_price', 'price_change',
                    'purchase_count', 'min_price', 'max_price', 'total_qty_purchased'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for product in products:
                    original = float(product['original_price'] or 0)
                    new = float(product['new_price'] or 0)
                    change = new - original
                    
                    writer.writerow({
                        'product_id': product['product_id'],
                        'product_name': product['product_name'] or '',
                        'uom_name': product['uom_name'] or '',
                        'original_price': original,
                        'new_price': new,
                        'price_change': change,
                        'purchase_count': product['purchase_count'],
                        'min_price': float(product['min_price'] or 0),
                        'max_price': float(product['max_price'] or 0),
                        'total_qty_purchased': float(product['total_qty_purchased'] or 0)
                    })
            
            print(f"✓ Exported {len(products)} products to {output_file}")
            
            # Show summary statistics
            total_change = sum(float(p['new_price'] or 0) - float(p['original_price'] or 0) for p in products)
            products_with_change = sum(1 for p in products if abs(float(p['new_price'] or 0) - float(p['original_price'] or 0)) > 0.01)
            
            print(f"\nSummary:")
            print(f"  Total products: {len(products)}")
            print(f"  Products with price changes: {products_with_change}")
            print(f"  Total price change: ${total_change:.2f}")
            
            # Show top changes
            print(f"\n\nTop 20 products with largest price changes:")
            print(f"{'Product Name':<50} {'UoM':<15} {'Original':<12} {'New':<12} {'Change':<12} {'Purchases':<12}")
            print("-" * 120)
            
            for product in products[:20]:
                name = str(product['product_name'] or 'N/A')[:50]
                uom = str(product['uom_name'] or 'N/A')[:15]
                original = float(product['original_price'] or 0)
                new = float(product['new_price'] or 0)
                change = new - original
                count = product['purchase_count']
                
                change_str = f"${change:+.2f}" if abs(change) > 0.01 else "$0.00"
                print(f"{name:<50} {uom:<15} ${original:<11.2f} ${new:<11.2f} {change_str:<12} {count:<12}")
            
            if len(products) > 20:
                print(f"\n  ... and {len(products) - 20} more products")
    
    finally:
        conn.close()


def main():
    """Main function"""
    output_file = Path(__file__).parent.parent / 'data' / 'product_cost_updates.csv'
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    print("Connecting to database...")
    print("Calculating average prices from purchase history...\n")
    list_cost_updates(output_file)
    
    print(f"\nTo view the file:")
    print(f"  open {output_file}")
    print(f"  or: cat {output_file}")


if __name__ == '__main__':
    main()

