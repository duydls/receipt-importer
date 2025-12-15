#!/usr/bin/env python3
"""
Generate stock report for a specific date
Shows: product name, UoM, quantity, cost, total value
"""

import sys
import csv
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from step3_mapping.query_database import connect_to_database
from psycopg2.extras import RealDictCursor


def generate_stock_report(target_date: str, output_file: Path):
    """Generate stock report for a specific date"""
    conn = connect_to_database()
    if not conn:
        print("ERROR: Could not connect to database")
        return
    
    try:
        # Parse target date
        try:
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')
        except ValueError:
            print(f"ERROR: Invalid date format. Use YYYY-MM-DD (e.g., 2025-09-01)")
            return
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Query stock_quant for products that were in stock on or before the target date
            # For quants that have purchase orders, calculate quantity based on stock_move dates
            # Only count stock that arrived on or before target date
            query = """
                SELECT 
                    pp.id as product_id,
                    pt.name->>'en_US' as product_name,
                    uom.name->>'en_US' as uom_name,
                    COALESCE(SUM(
                        -- Start with quant quantity, subtract PO quantities added after target date
                        -- If result is negative, it means the quant was created by POs after target date, so set to 0
                        GREATEST(0, 
                            sq.quantity - COALESCE((
                                SELECT SUM(
                                    CASE 
                                        -- If purchase UoM name contains *N pattern, extract and multiply
                                        WHEN po_uom.name->>'en_US' ~ '\*(\d+)' THEN
                                            pol.product_qty * (
                                                (regexp_match(po_uom.name->>'en_US', '\*(\d+)'))[1]::integer
                                            )
                                        -- Otherwise use product_uom_qty (which should be converted)
                                        ELSE COALESCE(pol.product_uom_qty, pol.product_qty)
                                    END
                                )
                                FROM stock_move sm
                                JOIN stock_picking sp ON sm.picking_id = sp.id
                                JOIN purchase_order po ON sp.origin = po.name
                                JOIN purchase_order_line pol ON pol.order_id = po.id 
                                    AND pol.product_id = sm.product_id
                                LEFT JOIN uom_uom po_uom ON pol.product_uom = po_uom.id
                                WHERE sm.product_id = sq.product_id
                                  AND (
                                      -- Exact location match
                                      sm.location_dest_id = sq.location_id
                                      OR
                                      -- Or quant location is a child of move destination (check parent_path)
                                      EXISTS (
                                          SELECT 1
                                          FROM stock_location sq_loc
                                          JOIN stock_location sm_loc ON sm.location_dest_id = sm_loc.id
                                          WHERE sq_loc.id = sq.location_id
                                            AND sq_loc.parent_path IS NOT NULL
                                            AND sm_loc.parent_path IS NOT NULL
                                            AND sq_loc.parent_path LIKE sm_loc.parent_path || '%%'
                                      )
                                  )
                                  AND po.state = 'done'
                                  AND sm.state = 'done'
                                  AND DATE(sm.date) > %s::date
                            ), 0)
                        )
                    ), 0) as total_quantity,
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
                    END * COALESCE(SUM(
                        -- Use GREATEST(0, ...) to prevent negative values
                        GREATEST(0, 
                            sq.quantity - COALESCE((
                                SELECT SUM(
                                    CASE 
                                        -- If purchase UoM name contains *N pattern, extract and multiply
                                        WHEN po_uom.name->>'en_US' ~ '\*(\d+)' THEN
                                            pol.product_qty * (
                                                (regexp_match(po_uom.name->>'en_US', '\*(\d+)'))[1]::integer
                                            )
                                        -- Otherwise use product_uom_qty (which should be converted)
                                        ELSE COALESCE(pol.product_uom_qty, pol.product_qty)
                                    END
                                )
                                FROM stock_move sm
                                JOIN stock_picking sp ON sm.picking_id = sp.id
                                JOIN purchase_order po ON sp.origin = po.name
                                JOIN purchase_order_line pol ON pol.order_id = po.id 
                                    AND pol.product_id = sm.product_id
                                LEFT JOIN uom_uom po_uom ON pol.product_uom = po_uom.id
                                WHERE sm.product_id = sq.product_id
                                  AND (
                                      -- Exact location match
                                      sm.location_dest_id = sq.location_id
                                      OR
                                      -- Or quant location is a child of move destination (check parent_path)
                                      EXISTS (
                                          SELECT 1
                                          FROM stock_location sq_loc
                                          JOIN stock_location sm_loc ON sm.location_dest_id = sm_loc.id
                                          WHERE sq_loc.id = sq.location_id
                                            AND sq_loc.parent_path IS NOT NULL
                                            AND sm_loc.parent_path IS NOT NULL
                                            AND sq_loc.parent_path LIKE sm_loc.parent_path || '%%'
                                      )
                                  )
                                  AND po.state = 'done'
                                  AND sm.state = 'done'
                                  AND DATE(sm.date) > %s::date
                            ), 0)
                        )
                    ), 0) as total_value
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                LEFT JOIN uom_uom uom ON pt.uom_id = uom.id
                LEFT JOIN stock_quant sq ON pp.id = sq.product_id
                LEFT JOIN stock_location sl ON sq.location_id = sl.id
                WHERE (sl.usage = 'internal' OR sl.usage IS NULL)
                  AND pt.active = TRUE
                  AND sq.quantity > 0
                  AND (sq.lot_id IS NULL OR sq.lot_id = 0)
                  AND (sq.package_id IS NULL OR sq.package_id = 0)
                  AND (sq.owner_id IS NULL OR sq.owner_id = 0)
                  AND DATE(sq.in_date) <= %s::date
                GROUP BY 
                    pp.id, 
                    pt.name, 
                    pp.standard_price,
                    uom.name
                HAVING COALESCE(SUM(
                    sq.quantity - COALESCE((
                        SELECT SUM(sm.product_uom_qty)
                        FROM stock_move sm
                        JOIN stock_picking sp ON sm.picking_id = sp.id
                        JOIN purchase_order po ON sp.origin = po.name
                        WHERE sm.product_id = sq.product_id
                          AND sm.location_dest_id = sq.location_id
                          AND po.state = 'done'
                          AND sm.state = 'done'
                          AND DATE(sm.date) > %s::date
                    ), 0)
                ), 0) > 0
                ORDER BY 
                    CASE 
                        WHEN pp.standard_price IS NULL THEN 0
                        WHEN jsonb_typeof(pp.standard_price) = 'object' THEN 
                            COALESCE((pp.standard_price->>'1')::numeric, 0)
                        ELSE 0
                    END * COALESCE(SUM(
                        sq.quantity - COALESCE((
                            SELECT SUM(pol.product_uom_qty)
                            FROM stock_move sm
                            JOIN stock_picking sp ON sm.picking_id = sp.id
                            JOIN purchase_order po ON sp.origin = po.name
                            JOIN purchase_order_line pol ON pol.order_id = po.id 
                                AND pol.product_id = sm.product_id
                            WHERE sm.product_id = sq.product_id
                              AND (
                                  -- Exact location match
                                  sm.location_dest_id = sq.location_id
                                  OR
                                  -- Or quant location is a child of move destination (check parent_path)
                                  EXISTS (
                                      SELECT 1
                                      FROM stock_location sq_loc
                                      JOIN stock_location sm_loc ON sm.location_dest_id = sm_loc.id
                                      WHERE sq_loc.id = sq.location_id
                                        AND sq_loc.parent_path IS NOT NULL
                                        AND sm_loc.parent_path IS NOT NULL
                                        AND sq_loc.parent_path LIKE sm_loc.parent_path || '%%'
                                  )
                              )
                              AND po.state = 'done'
                              AND sm.state = 'done'
                              AND DATE(sm.date) > %s::date
                        ), 0)
                    ), 0) DESC,
                    pt.name->>'en_US'
            """
            
            cur.execute(query, (target_dt.date(), target_dt.date(), target_dt.date(), target_dt.date(), target_dt.date()))
            products = cur.fetchall()
            
            if products:
                print(f"\nStock Report for {target_date}")
                print("=" * 100)
                print(f"{'Product Name':<50} {'UoM':<15} {'Quantity':<12} {'Unit Cost':<12} {'Total Value':<15}")
                print("-" * 100)
                
                total_value = 0
                for product in products:
                    product_name = product['product_name'] or 'Unknown'
                    if len(product_name) > 48:
                        product_name = product_name[:45] + '...'
                    
                    uom = product['uom_name'] or 'N/A'
                    qty = product['total_quantity']
                    cost = product['unit_cost']
                    value = product['total_value']
                    total_value += value or 0
                    
                    print(f"{product_name:<50} {uom:<15} {qty:<12.2f} ${cost:<11.2f} ${value:<14.2f}")
                
                print("-" * 100)
                print(f"{'TOTAL':<65} ${total_value:<14.2f}")
                print(f"\nTotal products: {len(products)}")
                print(f"Total value: ${total_value:,.2f}")
                
                # Export to CSV
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=[
                        'product_id', 'product_name', 'uom_name', 
                        'quantity', 'unit_cost', 'total_value'
                    ])
                    writer.writeheader()
                    for product in products:
                        writer.writerow({
                            'product_id': product['product_id'],
                            'product_name': product['product_name'],
                            'uom_name': product['uom_name'],
                            'quantity': product['total_quantity'],
                            'unit_cost': product['unit_cost'],
                            'total_value': product['total_value']
                        })
                
                print(f"\nExported to: {output_file}")
            else:
                print(f"\nNo stock found on {target_date}")
                print("All products have in_date after this date, so inventory is 0")
                
                # Still create empty CSV
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=[
                        'product_id', 'product_name', 'uom_name', 
                        'quantity', 'unit_cost', 'total_value'
                    ])
                    writer.writeheader()
                
                print(f"Created empty report: {output_file}")
    
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = '2025-09-01'
    
    output_file = Path(__file__).parent.parent / 'data' / f'stock_report_{target_date}.csv'
    generate_stock_report(target_date, output_file)

