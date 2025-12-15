#!/usr/bin/env python3
"""
Generate a comprehensive report of all products from purchase orders
Shows product name, UOM, price statistics (avg/low/high), and all vendors
"""

import sys
from pathlib import Path
from collections import defaultdict
import csv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from step3_mapping.query_database import connect_to_database

def generate_purchase_report():
    """Generate comprehensive purchase order product report"""

    print("Connecting to database...")
    conn = connect_to_database()
    if not conn:
        print("Failed to connect to database")
        return

    print("Generating purchase order product report...")

    try:
        with conn.cursor() as cur:
            # Query to get all purchase order line data with product and vendor info
            query = """
            SELECT
                pt.name->>'en_US' as product_name,
                uom.name->>'en_US' as uom_name,
                pol.price_unit,
                pol.product_qty,
                pol.product_uom_qty,
                partner.name as vendor_name,
                po.name as po_number,
                po.date_order,
                po.date_planned,
                po.state as po_state,
                pol.product_uom as pol_uom_id,
                pt.uom_id as template_uom_id,
                tuom.name->>'en_US' as template_uom_name,
                pol.product_id,
                po.partner_id
            FROM purchase_order_line pol
            JOIN purchase_order po ON pol.order_id = po.id
            JOIN res_partner partner ON po.partner_id = partner.id
            JOIN product_product pp ON pol.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            LEFT JOIN uom_uom uom ON pol.product_uom = uom.id
            LEFT JOIN uom_uom tuom ON pt.uom_id = tuom.id
            WHERE po.state IN ('done', 'purchase')
              AND partner.name NOT ILIKE '%wismettac%'
              AND partner.name NOT ILIKE '%boba baron%'
              AND partner.name NOT ILIKE '%biba barib%'
            ORDER BY pt.name->>'en_US', po.date_order
            """

            cur.execute(query)
            rows = cur.fetchall()

            print(f"Found {len(rows)} purchase order lines")

            # Process data by product
            product_data = defaultdict(lambda: {
                'vendors': set(),
                'price_uom_qty_base_qty_triples': [],  # Store (price_unit, product_uom_qty, product_qty) for proper UOM conversion
                'template_uom_name': None,  # Store the base/template UOM name
                'purchase_uoms': set(),  # Store all purchase UOMs used for this product
                'po_numbers': [],
                'quantities': []
            })

            for row in rows:
                product_name = row[0] or 'Unknown Product'
                purchase_uom_name = row[1] or 'Unknown UOM'
                price_unit = float(row[2] or 0)
                product_qty = float(row[3] or 0)
                product_uom_qty = float(row[4] or 0)
                vendor_name = row[5] or 'Unknown Vendor'
                po_number = row[6] or 'Unknown PO'
                po_state = row[9] or 'unknown'
                template_uom_name = row[12] or 'Unknown UOM'

                # Only include completed/done orders
                if po_state not in ('done', 'purchase'):
                    continue

                key = product_name

                product_data[key]['vendors'].add(vendor_name)
                product_data[key]['price_uom_qty_base_qty_triples'].append((float(price_unit), float(product_uom_qty), float(product_qty)))
                # Store the template UOM name (only once per product)
                if product_data[key]['template_uom_name'] is None:
                    product_data[key]['template_uom_name'] = template_uom_name
                # Store all purchase UOMs used for this product
                product_data[key]['purchase_uoms'].add(purchase_uom_name)
                product_data[key]['po_numbers'].append(po_number)
                product_data[key]['quantities'].append(float(product_qty))

            # Generate report
            report_data = []
            for product_name, data in sorted(product_data.items()):
                if not data['price_uom_qty_base_qty_triples']:
                    continue

                # Calculate weighted average price with proper UOM conversion
                total_weighted_value = 0
                total_base_quantity = 0
                all_prices_per_base_unit = []

                for price_unit, product_uom_qty, product_qty in data['price_uom_qty_base_qty_triples']:
                    if product_uom_qty > 0 and product_qty > 0:
                        # Convert price to per base unit
                        # price_per_base_unit = price_unit / (product_uom_qty / product_qty)
                        price_per_base_unit = price_unit * (product_qty / product_uom_qty)

                        # Weight by actual base quantity
                        weighted_value = price_per_base_unit * product_qty
                        total_weighted_value += weighted_value
                        total_base_quantity += product_qty
                        all_prices_per_base_unit.append(price_per_base_unit)

                if total_base_quantity > 0:
                    avg_price = total_weighted_value / total_base_quantity
                else:
                    avg_price = 0

                # Get min and max prices (converted to per base unit)
                if all_prices_per_base_unit:
                    min_price = min(all_prices_per_base_unit)
                    max_price = max(all_prices_per_base_unit)
                else:
                    min_price = max_price = 0

                total_quantity_display = sum(data['quantities'])
                vendor_list = ', '.join(sorted(data['vendors']))
                base_uom = data['template_uom_name'] or 'Unknown UOM'
                purchase_uoms_list = ', '.join(sorted(data['purchase_uoms']))
                po_count = len(data['po_numbers'])

                report_data.append({
                    'product_name': product_name,
                    'uom': base_uom,
                    'possible_purchase_uoms': purchase_uoms_list,
                    'average_price': avg_price,
                    'lowest_price': min_price,
                    'highest_price': max_price,
                    'total_quantity': total_base_quantity,
                    'vendor_count': len(data['vendors']),
                    'vendors': vendor_list,
                    'po_count': po_count
                })

            # Sort by product name
            report_data.sort(key=lambda x: x['product_name'])

            # Save to CSV
            output_file = Path('./purchase_order_product_report.csv')

            print(f"Saving to: {output_file.absolute()}")
            print(f"Report data length: {len(report_data)}")

            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['product_name', 'uom', 'possible_purchase_uoms', 'average_price', 'lowest_price',
                            'highest_price', 'total_quantity', 'vendor_count', 'vendors', 'po_count']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for row in report_data:
                    writer.writerow(row)

            print(f"✓ Report saved to: {output_file.absolute()}")
            print(f"✓ File exists after writing: {output_file.exists()}")
            print(f"✓ File size: {output_file.stat().st_size if output_file.exists() else 0} bytes")
            print(f"✓ Total products analyzed: {len(report_data)}")

            # Print summary statistics
            print("\nSummary:")
            print(f"Total products: {len(report_data)}")
            print(f"Products with multiple vendors: {sum(1 for p in report_data if p['vendor_count'] > 1)}")
            print("Each product now shows its base UOM (template UOM)")

            # Show top 10 by average price
            print("\nTop 10 products by average price:")
            top_by_price = sorted(report_data, key=lambda x: x['average_price'], reverse=True)[:10]
            for item in top_by_price:
                print(f"  {item['product_name'][:50]:<50} ${item['average_price']:.2f}")

            # Show products with price variance
            print("\nProducts with highest price variance (high - low):")
            variance_items = [(p, p['highest_price'] - p['lowest_price'])
                            for p in report_data if p['highest_price'] > p['lowest_price']]
            variance_items.sort(key=lambda x: x[1], reverse=True)
            for item, variance in variance_items[:10]:
                print(".2f")

    except Exception as e:
        print(f"Error generating report: {e}")
        import traceback
        traceback.print_exc()

    finally:
        conn.close()
        print("✓ Database connection closed")

if __name__ == '__main__':
    generate_purchase_report()
