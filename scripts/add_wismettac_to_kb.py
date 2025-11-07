#!/usr/bin/env python3
"""
Add Wismettac products to knowledge base from online lookup.

This script:
1. Loads Wismettac receipts from extracted data
2. For each item, fetches product info from Wismettac online catalog
3. Adds products to knowledge base in the format: {item_number: [product_name, store, size_spec, unit_price]}
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Union

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from step1_extract.wismettac_client import WismettacClient

KB_PATH = Path('data/step1_input/knowledge_base.json')
WISMETTAC_DATA_PATH = Path('data/step1_output/wismettac_based/extracted_data.json')


def load_knowledge_base(kb_path: Path) -> Dict[str, Any]:
    """Load knowledge base from JSON file."""
    if not kb_path.exists():
        return {}
    try:
        with kb_path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Warning: Knowledge base has JSON syntax error: {e}")
        print("Creating backup and starting with empty KB...")
        # Create backup
        backup_path = kb_path.with_suffix('.json.backup')
        if not backup_path.exists():
            kb_path.rename(backup_path)
            print(f"Backup created: {backup_path}")
        return {}
    except Exception as e:
        print(f"Error loading knowledge base: {e}")
        return {}


def save_knowledge_base(kb_path: Path, kb: Dict[str, Any]) -> None:
    """Save knowledge base to JSON file."""
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    with kb_path.open('w', encoding='utf-8') as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)


def add_wismettac_product_to_kb(
    kb: Dict[str, Any],
    item_number: str,
    product: Any,
    unit_price: Optional[float] = None,
    detail_data: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Add a Wismettac product to knowledge base with all available information.
    
    KB format: {item_number: [product_name, store, size_spec, unit_price]}
    Extended format: If detail_data available, store as dict with all fields
    
    Args:
        kb: Knowledge base dictionary
        item_number: Item number (key)
        product: WismettacProduct object
        unit_price: Optional unit price (if not provided, uses 0.0)
        detail_data: Optional detailed product data from website (Brand, Category, etc.)
    
    Returns:
        True if product was added/updated, False otherwise
    """
    if not item_number or not product:
        return False
    
    # Normalize item number (remove # prefix if present)
    item_no = str(item_number).strip().lstrip('#')
    
    # Get product name - prefer online name if available
    product_name = product.name or ''
    if detail_data and detail_data.get('name'):
        product_name = detail_data['name']
    
    # Build size_spec from pack_size_raw or detail_data
    size_spec = ''
    if detail_data and detail_data.get('Pack Size'):
        size_spec = detail_data['Pack Size']
    elif product.pack_size_raw:
        size_spec = product.pack_size_raw
    elif product.pack and product.each_qty and product.each_uom:
        size_spec = f"{product.pack}/{product.each_qty} {product.each_uom}"
    elif product.pack:
        size_spec = f"{product.pack} pack"
    
    # Use provided unit_price or default to 0.0
    price = float(unit_price) if unit_price is not None else 0.0
    
    # If we have detailed data, store as dict with all fields
    if detail_data:
        # Store as dict with all available information
        # Handle both normalized (lowercase) and original (title case) keys
        brand = detail_data.get('brand') or detail_data.get('Brand', '')
        category = detail_data.get('category') or detail_data.get('Category', '')
        pack_size = detail_data.get('pack_size') or detail_data.get('Pack Size', size_spec)
        min_order_qty = detail_data.get('minimum_order_qty') or detail_data.get('Minimum Order Qty', '')
        barcode = detail_data.get('barcode') or detail_data.get('Barcode (UPC)', '')
        
        kb[item_no] = {
            'name': product_name,
            'store': 'Wismettac',
            'size_spec': size_spec,
            'unit_price': price,
            'brand': brand,
            'category': category,
            'item_number': item_no,  # Use receipt's item_number
            'pack_size': pack_size,
            'min_order_qty': min_order_qty,
            'barcode': barcode,
            'detail_url': detail_data.get('detail_url', ''),
        }
    else:
        # Store in old format if no detailed data
        kb[item_no] = [
            product_name,
            'Wismettac',
            size_spec,
            price
        ]
    
    return True


def process_wismettac_receipts(
    wismettac_data_path: Path,
    kb_path: Path
) -> Dict[str, Any]:
    """
    Process Wismettac receipts and add products to knowledge base.
    
    Returns:
        Dictionary with statistics: {added, updated, skipped, errors}
    """
    # Load knowledge base
    kb = load_knowledge_base(kb_path)
    print(f"Loaded knowledge base with {len(kb)} items")
    
    # Load Wismettac receipts
    if not wismettac_data_path.exists():
        print(f"Error: Wismettac data file not found: {wismettac_data_path}")
        return {'added': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
    
    with wismettac_data_path.open('r', encoding='utf-8') as f:
        wismettac_data = json.load(f)
    
    print(f"Found {len(wismettac_data)} Wismettac receipts")
    
    # Initialize client
    client = WismettacClient()
    
    # Statistics
    stats = {'added': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
    
    # Collect all unique item numbers from receipts
    items_to_process = {}
    for receipt_id, receipt in wismettac_data.items():
        for item in receipt.get('items', []):
            item_no = item.get('item_number', '').strip()
            if item_no:
                # Store item with unit_price if available
                if item_no not in items_to_process:
                    items_to_process[item_no] = {
                        'item_number': item_no,
                        'product_name': item.get('product_name', ''),
                        'unit_price': item.get('unit_price'),
                    }
    
    # Also check existing KB entries for Wismettac products
    existing_wismettac_items = {}
    for key, value in kb.items():
        if isinstance(value, list) and len(value) >= 2 and value[1] == 'Wismettac':
            item_no_clean = str(key).strip().lstrip('#')
            if item_no_clean not in items_to_process:
                # Extract existing data
                existing_wismettac_items[item_no_clean] = {
                    'item_number': item_no_clean,
                    'product_name': value[0] if len(value) > 0 else '',
                    'unit_price': value[3] if len(value) > 3 else 0.0,
                }
    
    # Merge both sets
    all_items = {**items_to_process, **existing_wismettac_items}
    
    print(f"\nFound {len(items_to_process)} items from receipts")
    if existing_wismettac_items:
        print(f"Found {len(existing_wismettac_items)} existing Wismettac items in KB")
    print(f"Total items to process: {len(all_items)}")
    
    # Process each item
    for item_no, item_info in all_items.items():
        # Normalize item number
        item_no_clean = str(item_no).strip().lstrip('#')
        
        # Check if already in KB
        already_in_kb = item_no_clean in kb
        
        try:
            # Fetch product info using item_number as keyword to search
            print(f"\nProcessing item {item_no}...")
            prod = None
            detail_data = None
            import re
            
            # Normalize keys so downstream expects consistent labels
            def _normalize_detail_keys(d):
                if not d:
                    return d
                # map snake/camel → human labels (only if label not present)
                label_map = {
                    "brand": "Brand",
                    "category": "Category",
                    "itemNumber": "Item Number",
                    "item_number": "Item Number",
                    "packSizeRaw": "Pack Size",
                    "pack_size": "Pack Size",
                    "minOrderQty": "Minimum Order Qty",
                    "min_order_qty": "Minimum Order Qty",
                    "barcode": "Barcode (UPC)",
                    "upc": "Barcode (UPC)",
                    "detailsUrl": "detail_url",
                    "detail_url": "detail_url",
                }
                out = dict(d)
                for k, v in list(d.items()):
                    if k in label_map and label_map[k] not in out:
                        out[label_map[k]] = v
                return out
            
            # Strategy 1: Use wismettac_client.py to search by item_number as keyword
            # Strategy 2: If item_number search fails, try searching by product name
            if item_no:
                print(f"  Searching by item_number (as keyword): {item_no}...")
                try:
                    # Use wismettac_client.py script directly
                    import sys
                    from pathlib import Path
                    scripts_dir = Path(__file__).parent
                    if str(scripts_dir) not in sys.path:
                        sys.path.insert(0, str(scripts_dir))
                    
                    from wismettac_client import fetch_by_keyword, fetch_by_product_id, get_session, to_public_json
                    
                    # Create session without cookies, with insecure SSL
                    session = get_session(cookie=None, user_agent=None, insecure=True)
                    
                    # Try search first, then fallback to direct product ID lookup
                    result = None
                    try:
                        results = fetch_by_keyword(session, item_no, branch='CHI')
                        if results and len(results) > 0:
                            result = results[0]
                            # Skip if it's an error result
                            if '_error' in result:
                                result = None
                    except Exception:
                        # Search failed, will try direct lookup below
                        pass
                    
                    # If search failed or returned no results, try direct product ID lookup
                    if not result:
                        print(f"  Search by item_number failed, trying direct product ID lookup...")
                        direct_result = fetch_by_product_id(session, item_no, branch='CHI')
                        if direct_result:
                            result = direct_result
                    
                    # If still no result, try searching by product name
                    if not result and item_info.get('product_name'):
                        product_name = item_info.get('product_name')
                        print(f"  Direct lookup failed, trying search by product name: {product_name}...")
                        try:
                            results = fetch_by_keyword(session, product_name, branch='CHI')
                            if results and len(results) > 0:
                                result = results[0]
                                # Skip if it's an error result
                                if '_error' in result:
                                    result = None
                        except Exception:
                            pass
                    
                    if result:
                        # Normalize to public JSON format
                        normalized = to_public_json(result)
                        
                        if normalized.get('name'):
                            print(f"  ✓ Found product")
                            # Use normalized data
                            detail_data = normalized
                            # Use receipt's item_number instead of website's item_number
                            detail_data['item_number'] = item_no
                            # Don't use barcode from website
                            detail_data['barcode'] = None
                            # Also keep original result for detail_url
                            if 'detail_url' in result:
                                detail_data['detail_url'] = result['detail_url']
                            
                            # Create a WismettacProduct from detail_data
                            from step1_extract.wismettac_client import WismettacProduct
                            prod = WismettacProduct(
                                item_number=item_no,  # Use receipt's item_number
                                name=detail_data.get('name', ''),
                                brand=detail_data.get('brand'),
                                category=detail_data.get('category'),
                                pack_size_raw=detail_data.get('pack_size'),
                                pack=None,
                                each_qty=None,
                                each_uom=None,
                                barcode=None,  # Don't use barcode from website
                                min_order_qty=detail_data.get('minimum_order_qty'),
                                detail_url=detail_data.get('detail_url', f"https://ecatalog.wismettacusa.com/product.php?id={item_no}")
                            )
                            
                            # Display all fields for verification
                            print(f"    Brand: {detail_data.get('brand', 'N/A')}")
                            print(f"    Category: {detail_data.get('category', 'N/A')}")
                            print(f"    Item Number: {item_no} (from receipt)")
                            print(f"    Pack Size: {detail_data.get('pack_size', 'N/A')}")
                            print(f"    Minimum Order Qty: {detail_data.get('minimum_order_qty', 'N/A')}")
                            print(f"    Name: {detail_data.get('name', 'N/A')}")
                        else:
                            print(f"  ✗ Product found but no name extracted")
                    else:
                        print(f"  ✗ Product not found")
                except Exception as e:
                    print(f"  ✗ Error searching: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Add to KB with online data (update existing entries)
            if prod:
                unit_price = item_info.get('unit_price') or (kb.get(item_no_clean, [0, '', '', 0.0])[3] if isinstance(kb.get(item_no_clean), list) and len(kb.get(item_no_clean, [])) > 3 else 0.0)
                added = add_wismettac_product_to_kb(kb, item_no_clean, prod, unit_price, detail_data)
                
                if added:
                    if already_in_kb:
                        stats['updated'] += 1
                        print(f"  ✓ Updated in KB with online data: {prod.name or (detail_data.get('name') if detail_data else 'N/A')}")
                    else:
                        stats['added'] += 1
                        print(f"  ✓ Added to KB: {prod.name or (detail_data.get('name') if detail_data else 'N/A')}")
                    
                    # Display all available information
                    if detail_data:
                        print(f"    Brand: {detail_data.get('Brand', 'N/A')}")
                        print(f"    Category: {detail_data.get('Category', 'N/A')}")
                        print(f"    Item Number: {detail_data.get('Item Number', 'N/A')}")
                        print(f"    Pack Size: {detail_data.get('Pack Size', 'N/A')}")
                        print(f"    Minimum Order Qty: {detail_data.get('Minimum Order Qty', 'N/A')}")
                        print(f"    Barcode: {detail_data.get('Barcode (UPC)', 'N/A')}")
                    elif prod:
                        if prod.brand:
                            print(f"    Brand: {prod.brand}")
                        if prod.category:
                            print(f"    Category: {prod.category}")
                        if prod.pack_size_raw:
                            print(f"    Pack Size: {prod.pack_size_raw}")
                        if prod.barcode:
                            print(f"    Barcode: {prod.barcode}")
                else:
                    stats['skipped'] += 1
                    print(f"  ⚠ Skipped (no data)")
            else:
                stats['skipped'] += 1
                print(f"  ⚠ Not found online")
        except Exception as e:
            stats['errors'] += 1
            print(f"  ✗ Error: {e}")
    
    # Save updated knowledge base
    if stats['added'] > 0 or stats['updated'] > 0:
        save_knowledge_base(kb_path, kb)
        print(f"\n✓ Saved knowledge base with {len(kb)} items")
    
    return stats


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Add Wismettac products to knowledge base from online lookup'
    )
    parser.add_argument(
        '--kb-path',
        type=Path,
        default=KB_PATH,
        help=f'Path to knowledge base JSON file (default: {KB_PATH})'
    )
    parser.add_argument(
        '--wismettac-data',
        type=Path,
        default=WISMETTAC_DATA_PATH,
        help=f'Path to Wismettac extracted data JSON (default: {WISMETTAC_DATA_PATH})'
    )
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("ADDING WISMETTAC PRODUCTS TO KNOWLEDGE BASE")
    print("=" * 80)
    print(f"Knowledge Base: {args.kb_path}")
    print(f"Wismettac Data: {args.wismettac_data}")
    print("=" * 80)
    
    # Process receipts (no branch needed - we fetch without branch parameter)
    stats = process_wismettac_receipts(args.wismettac_data, args.kb_path)
    
    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Added: {stats['added']}")
    print(f"Updated: {stats['updated']}")
    print(f"Skipped: {stats['skipped']}")
    print(f"Errors: {stats['errors']}")
    print("=" * 80)


if __name__ == '__main__':
    main()

