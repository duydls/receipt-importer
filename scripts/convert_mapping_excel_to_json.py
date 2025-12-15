#!/usr/bin/env python3
"""
Convert Excel Product Mapping file back to JSON format

Reads the Excel file created by generate_product_mapping_excel.py and converts it
back to the JSON mapping format used by the system.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any
import pandas as pd


def convert_excel_to_json(excel_file: Path, output_file: Path) -> Dict[str, Dict[str, Any]]:
    """
    Convert Excel mapping file to JSON format
    
    Args:
        excel_file: Path to Excel file
        output_file: Path to output JSON file
        
    Returns:
        Dictionary with mapping data
    """
    # Read Excel file
    try:
        df = pd.read_excel(excel_file, sheet_name='Product Mappings')
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return {}
    
    # Convert to dictionary
    mappings = {}
    
    for _, row in df.iterrows():
        receipt_name = str(row.get('Receipt Product Name', '')).strip()
        if not receipt_name or receipt_name.lower().startswith('example'):
            continue  # Skip empty rows and example rows
        
        # Get Odoo Product ID
        product_id = row.get('Odoo Product ID', '')
        if pd.isna(product_id) or product_id == '':
            print(f"⚠️  Skipping row: '{receipt_name}' - missing Odoo Product ID")
            continue
        
        try:
            product_id = int(float(product_id))  # Handle Excel numeric format
        except (ValueError, TypeError):
            print(f"⚠️  Skipping row: '{receipt_name}' - invalid Odoo Product ID: {product_id}")
            continue
        
        # Build mapping entry
        mapping_entry = {
            'database_product_id': product_id,
            'database_product_name': str(row.get('Odoo Product Name', '')).strip(),
        }
        
        # Optional fields
        receipt_uom = str(row.get('Receipt UoM', '')).strip()
        if receipt_uom and receipt_uom != 'nan':
            mapping_entry['receipt_uom'] = receipt_uom
        
        odoo_uom_id = row.get('Odoo UoM ID', '')
        if not pd.isna(odoo_uom_id) and odoo_uom_id != '':
            try:
                mapping_entry['odoo_uom_id'] = int(float(odoo_uom_id))
            except (ValueError, TypeError):
                pass
        
        odoo_uom_name = str(row.get('Odoo UoM Name', '')).strip()
        if odoo_uom_name and odoo_uom_name != 'nan':
            mapping_entry['odoo_uom_name'] = odoo_uom_name
        
        conversion_ratio = row.get('UoM Conversion Ratio', '')
        if not pd.isna(conversion_ratio) and conversion_ratio != '':
            try:
                mapping_entry['uom_conversion_ratio'] = float(conversion_ratio)
            except (ValueError, TypeError):
                pass
        
        # Vendors (comma-separated list)
        vendors_str = str(row.get('Vendors', '')).strip()
        if vendors_str and vendors_str != 'nan':
            vendors = [v.strip() for v in vendors_str.split(',') if v.strip()]
            if vendors:
                mapping_entry['vendors'] = vendors
        
        # Notes
        notes = str(row.get('Notes', '')).strip()
        if notes and notes != 'nan':
            mapping_entry['notes'] = notes
        
        # Active flag
        active = row.get('Active', True)
        if pd.isna(active):
            active = True
        mapping_entry['active'] = bool(active)
        
        # Add to mappings
        mappings[receipt_name] = mapping_entry
    
    # Add metadata
    result = {
        '_metadata': {
            'source': 'Excel file',
            'excel_file': str(excel_file),
            'generated_at': pd.Timestamp.now().isoformat(),
            'total_mappings': len(mappings)
        },
        **mappings
    }
    
    # Save to JSON
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Converted {len(mappings)} mappings to JSON: {output_file}")
    
    return result


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Convert Excel Product Mapping file to JSON format'
    )
    parser.add_argument(
        'excel_file',
        type=str,
        help='Input Excel file path'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='Output JSON file path (default: same name as Excel with .json extension)'
    )
    
    args = parser.parse_args()
    
    excel_file = Path(args.excel_file)
    if not excel_file.exists():
        print(f"Error: Excel file not found: {excel_file}")
        sys.exit(1)
    
    # Determine output file
    if args.output:
        output_file = Path(args.output)
    else:
        output_file = excel_file.with_suffix('.json')
    
    print(f"Reading Excel file: {excel_file}")
    print(f"Output JSON file: {output_file}")
    
    # Convert
    mappings = convert_excel_to_json(excel_file, output_file)
    
    if mappings:
        print(f"\n✅ Successfully converted {len(mappings) - 1} mappings (excluding metadata)")
        print(f"   Output: {output_file}")
    else:
        print("\n⚠️  No mappings found in Excel file")


if __name__ == '__main__':
    main()

