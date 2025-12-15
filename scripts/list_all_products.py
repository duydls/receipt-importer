#!/usr/bin/env python3
"""
List all products with their names, UoM, and prices
Outputs to CSV file
"""

import sys
import csv
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def list_all_products(output_file: Path):
    """List all products with names, UoM, and prices"""
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
                    pt.default_code,
                    pp.barcode,
                    uom.name->>'en_US' as uom_name,
                    uom.id as uom_id,
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END as standard_price,
                    pt.list_price as sale_price,
                    pt.categ_id,
                    pc.name as category_name,
                    pt.purchase_ok,
                    pt.sale_ok,
                    pt.active
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                LEFT JOIN product_category pc ON pt.categ_id = pc.id
                ORDER BY pt.name->>'en_US'
            """
            
            cur.execute(query)
            products = cur.fetchall()
            
            if not products:
                print("No products found")
                return
            
            # Write to CSV
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = [
                    'product_id', 'product_name', 'default_code', 'barcode',
                    'uom_name', 'uom_id', 'standard_price', 'sale_price',
                    'category_name', 'purchase_ok', 'sale_ok', 'active'
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                for product in products:
                    writer.writerow({
                        'product_id': product['product_id'],
                        'product_name': product['product_name'] or '',
                        'default_code': product['default_code'] or '',
                        'barcode': product['barcode'] or '',
                        'uom_name': product['uom_name'] or '',
                        'uom_id': product['uom_id'] or '',
                        'standard_price': product['standard_price'] or 0,
                        'sale_price': product['sale_price'] or 0,
                        'category_name': product['category_name'] or '',
                        'purchase_ok': product['purchase_ok'],
                        'sale_ok': product['sale_ok'],
                        'active': product['active']
                    })
            
            print(f"✓ Exported {len(products)} products to {output_file}")
            print(f"\nSample products:")
            for product in products[:10]:
                name = str(product['product_name'] or 'N/A')[:40]
                uom = str(product['uom_name'] or 'N/A')[:15]
                cost = float(product['standard_price'] or 0)
                print(f"  {name:<40} {uom:<15} ${cost:.2f}")
            
            if len(products) > 10:
                print(f"  ... and {len(products) - 10} more")
    
    finally:
        conn.close()


def main():
    """Main function"""
    output_file = Path(__file__).parent.parent / 'data' / 'all_products.csv'
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    print("Connecting to database...")
    list_all_products(output_file)
    
    print(f"\nTo view the file:")
    print(f"  open {output_file}")
    print(f"  or: cat {output_file}")


if __name__ == '__main__':
    main()

