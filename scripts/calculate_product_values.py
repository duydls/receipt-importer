#!/usr/bin/env python3
"""
Calculate total value of all products in inventory
Value = quantity on hand × standard_price (cost)
"""

import sys
import csv
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def calculate_product_values(output_file: Path):
    """Calculate product values (quantity × cost)"""
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
                    END as unit_cost,
                    COALESCE(SUM(sq.quantity), 0) as total_quantity,
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END * COALESCE(SUM(sq.quantity), 0) as total_value
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                LEFT JOIN stock_quant sq ON pp.id = sq.product_id
                LEFT JOIN stock_location sl ON sq.location_id = sl.id
                WHERE sl.usage = 'internal' OR sl.usage IS NULL
                  AND pt.active = TRUE
                GROUP BY 
                    pp.id, 
                    pt.name, 
                    pp.standard_price,
                    uom.name
                HAVING COALESCE(SUM(sq.quantity), 0) > 0
                   OR CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                      END > 0
                ORDER BY 
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END * COALESCE(SUM(sq.quantity), 0) DESC
            """
            
            cur.execute(query)
            products = cur.fetchall()
            
            if not products:
                print("No products found")
                return
            
            # Calculate totals
            total_value = sum(float(p['total_value'] or 0) for p in products)
            total_quantity = sum(float(p['total_quantity'] or 0) for p in products)
            products_with_stock = sum(1 for p in products if float(p['total_quantity'] or 0) > 0)
            products_with_value = sum(1 for p in products if float(p['total_value'] or 0) > 0)
            
            # Write to CSV
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = [
                    'product_id', 'product_name', 'uom_name', 
                    'unit_cost', 'total_quantity', 'total_value'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for product in products:
                    writer.writerow({
                        'product_id': product['product_id'],
                        'product_name': product['product_name'] or '',
                        'uom_name': product['uom_name'] or '',
                        'unit_cost': float(product['unit_cost'] or 0),
                        'total_quantity': float(product['total_quantity'] or 0),
                        'total_value': float(product['total_value'] or 0)
                    })
            
            print(f"✓ Calculated values for {len(products)} products")
            print(f"✓ Exported to {output_file}")
            
            # Show summary
            print(f"\n{'='*80}")
            print(f"INVENTORY VALUE SUMMARY")
            print(f"{'='*80}")
            print(f"  Total Inventory Value:     ${total_value:,.2f}")
            print(f"  Total Quantity:           {total_quantity:,.2f} units")
            print(f"  Products with Stock:       {products_with_stock}")
            print(f"  Products with Value:       {products_with_value}")
            print(f"  Average Value per Product: ${total_value/products_with_value:,.2f}" if products_with_value > 0 else "  Average Value per Product: $0.00")
            
            # Show top 20 by value
            print(f"\n\nTop 20 Products by Inventory Value:")
            print(f"{'Product Name':<50} {'UoM':<15} {'Qty':<12} {'Unit Cost':<12} {'Total Value':<15}")
            print("-" * 110)
            
            for product in products[:20]:
                name = str(product['product_name'] or 'N/A')[:50]
                uom = str(product['uom_name'] or 'N/A')[:15]
                qty = float(product['total_quantity'] or 0)
                cost = float(product['unit_cost'] or 0)
                value = float(product['total_value'] or 0)
                
                print(f"{name:<50} {uom:<15} {qty:<12.2f} ${cost:<11.2f} ${value:<14.2f}")
            
            if len(products) > 20:
                print(f"\n  ... and {len(products) - 20} more products")
            
            # Show products with no stock but have cost
            no_stock = [p for p in products if float(p['total_quantity'] or 0) == 0 and float(p['unit_cost'] or 0) > 0]
            if no_stock:
                print(f"\n\nProducts with cost but no stock ({len(no_stock)}):")
                for product in no_stock[:10]:
                    name = str(product['product_name'] or 'N/A')[:50]
                    cost = float(product['unit_cost'] or 0)
                    print(f"  {name:<50} ${cost:.2f}")
                if len(no_stock) > 10:
                    print(f"  ... and {len(no_stock) - 10} more")
    
    finally:
        conn.close()


def main():
    """Main function"""
    output_file = Path(__file__).parent.parent / 'data' / 'product_values.csv'
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    print("Connecting to database...")
    print("Calculating product values (quantity × cost)...\n")
    calculate_product_values(output_file)
    
    print(f"\nTo view the file:")
    print(f"  open {output_file}")
    print(f"  or: cat {output_file}")


if __name__ == '__main__':
    main()

