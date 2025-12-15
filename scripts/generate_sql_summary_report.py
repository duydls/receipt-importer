#!/usr/bin/env python3
"""
Generate a summary report of all generated SQL files showing conversions applied
"""

import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict

def extract_sql_info(sql_file: Path) -> Dict:
    """Extract information from a SQL file"""
    with open(sql_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract receipt ID from filename
    receipt_id = sql_file.stem.replace('purchase_order_', '')
    
    # Extract PO ID
    po_id_match = re.search(r'INSERT INTO purchase_order.*?SELECT\s+(\d+)', content, re.DOTALL)
    po_id = int(po_id_match.group(1)) if po_id_match else None
    
    # Extract vendor
    vendor_match = re.search(r'-- Vendor: (.+)', content)
    vendor = vendor_match.group(1).strip() if vendor_match else 'N/A'
    
    # Extract date
    date_match = re.search(r'-- Date: (.+)', content)
    date = date_match.group(1).strip() if date_match else 'N/A'
    
    # Extract total
    total_match = re.search(r'-- Total: \$(.+)', content)
    total = total_match.group(1).strip() if total_match else 'N/A'
    
    # Extract line conversions
    conversions = []
    line_pattern = r'-- Line \d+: (.+?)\n--\s+Product ID: (\d+).*?--\s+Original Quantity: (.+?)\n--\s+Converted Quantity: (.+?)\n'
    for match in re.finditer(line_pattern, content, re.DOTALL):
        product_name = match.group(1).strip()
        product_id = match.group(2).strip()
        orig_qty = match.group(3).strip()
        conv_qty = match.group(4).strip()
        conversions.append({
            'product_name': product_name,
            'product_id': product_id,
            'original': orig_qty,
            'converted': conv_qty
        })
    
    # Extract lines without conversions
    simple_line_pattern = r'-- Line \d+: (.+?)\n--\s+Product ID: (\d+).*?--\s+Quantity: (.+?)\n--\s+Unit Price:'
    for match in re.finditer(simple_line_pattern, content, re.DOTALL):
        product_name = match.group(1).strip()
        product_id = match.group(2).strip()
        qty = match.group(3).strip()
        conversions.append({
            'product_name': product_name,
            'product_id': product_id,
            'original': qty,
            'converted': qty
        })
    
    return {
        'receipt_id': receipt_id,
        'po_id': po_id,
        'vendor': vendor,
        'date': date,
        'total': total,
        'conversions': conversions,
        'file': sql_file.name
    }


def generate_html_report(sql_infos: List[Dict], output_file: Path):
    """Generate HTML summary report"""
    
    # Calculate statistics
    total_items = sum(len(info['conversions']) for info in sql_infos)
    converted_items = sum(1 for info in sql_infos for conv in info['conversions'] if conv['original'] != conv['converted'])
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Purchase Order SQL Generation Summary</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .summary {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th {{ background: #4CAF50; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
        tr:hover {{ background: #f5f5f5; }}
        .conversion {{ color: #1976d2; font-weight: bold; }}
        .no-conversion {{ color: #666; }}
        .po-id {{ font-weight: bold; color: #4CAF50; }}
        .receipt-id {{ font-family: monospace; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Purchase Order SQL Generation Summary</h1>
        <div class="summary">
            <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Total Purchase Orders:</strong> {len(sql_infos)}</p>
            <p><strong>Total Items:</strong> {total_items}</p>
            <p><strong>Items with Conversions:</strong> {converted_items}</p>
        </div>
"""
    
    # Add table
    html += """
        <h2>Purchase Orders</h2>
        <table>
            <thead>
                <tr>
                    <th>PO ID</th>
                    <th>Receipt ID</th>
                    <th>Vendor</th>
                    <th>Date</th>
                    <th>Total</th>
                    <th>Items</th>
                    <th>SQL File</th>
                </tr>
            </thead>
            <tbody>
"""
    
    for info in sorted(sql_infos, key=lambda x: x['po_id'] or 0):
        has_conversion = any(c['original'] != c['converted'] for c in info['conversions'])
        row_class = 'conversion' if has_conversion else ''
        
        html += f"""
                <tr class="{row_class}">
                    <td class="po-id">{info['po_id'] or 'N/A'}</td>
                    <td class="receipt-id">{info['receipt_id']}</td>
                    <td>{info['vendor']}</td>
                    <td>{info['date']}</td>
                    <td>${info['total']}</td>
                    <td>{len(info['conversions'])}</td>
                    <td><code>{info['file']}</code></td>
                </tr>
"""
    
    html += """
            </tbody>
        </table>
"""
    
    # Add detailed conversions
    html += """
        <h2>UoM Conversions Applied</h2>
        <table>
            <thead>
                <tr>
                    <th>PO ID</th>
                    <th>Product</th>
                    <th>Original Quantity</th>
                    <th>Converted Quantity</th>
                </tr>
            </thead>
            <tbody>
"""
    
    for info in sorted(sql_infos, key=lambda x: x['po_id'] or 0):
        for conv in info['conversions']:
            if conv['original'] != conv['converted']:
                html += f"""
                <tr>
                    <td class="po-id">{info['po_id'] or 'N/A'}</td>
                    <td>{conv['product_name']} (ID: {conv['product_id']})</td>
                    <td class="conversion">{conv['original']}</td>
                    <td class="conversion">{conv['converted']}</td>
                </tr>
"""
    
    html += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ Generated SQL summary report: {output_file}")


def main():
    sql_dir = Path('data/sql')
    if not sql_dir.exists():
        print("No SQL directory found")
        return
    
    # Find all main SQL files (exclude rollback)
    sql_files = [f for f in sql_dir.glob('purchase_order_*.sql') if '_rollback' not in f.name]
    
    if not sql_files:
        print("No SQL files found")
        return
    
    # Extract info from each SQL file
    sql_infos = []
    for sql_file in sorted(sql_files):
        try:
            info = extract_sql_info(sql_file)
            sql_infos.append(info)
        except Exception as e:
            print(f"Error processing {sql_file}: {e}")
    
    # Generate report
    output_file = Path('data/sql/sql_generation_summary.html')
    generate_html_report(sql_infos, output_file)
    
    # Print summary
    print(f"\n📊 Summary:")
    print(f"   Total Purchase Orders: {len(sql_infos)}")
    total_items = sum(len(info['conversions']) for info in sql_infos)
    converted_items = sum(1 for info in sql_infos for conv in info['conversions'] if conv['original'] != conv['converted'])
    print(f"   Total Items: {total_items}")
    print(f"   Items with Conversions: {converted_items}")


if __name__ == '__main__':
    main()

