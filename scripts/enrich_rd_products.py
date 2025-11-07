#!/usr/bin/env python3
"""
Enrich RD products in knowledge base with data from Instacart RD search.

This script:
1. Loads all RD products from knowledge_base.json
2. For each product, searches Instacart RD using UPC or item_number
3. Retrieves all available product information (name, brand, size, UPC, price, etc.)
4. Updates the knowledge base with enriched information
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import the Instacart RD search function
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))
try:
    from instacart_rd_search import get_session, search_by_upc_graphql
except ImportError:
    # Try relative import
    spec = importlib.util.spec_from_file_location("instacart_rd_search", scripts_dir / "instacart_rd_search.py")
    instacart_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instacart_module)
    get_session = instacart_module.get_session
    search_by_upc_graphql = instacart_module.search_by_upc_graphql

KB_PATH = Path('data/step1_input/knowledge_base.json')


def load_knowledge_base() -> Dict[str, Any]:
    """Load knowledge base from JSON file."""
    if not KB_PATH.exists():
        print(f"Error: Knowledge base not found at {KB_PATH}", file=sys.stderr)
        sys.exit(1)
    
    with KB_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def save_knowledge_base(kb: Dict[str, Any]) -> None:
    """Save knowledge base to JSON file."""
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with KB_PATH.open('w', encoding='utf-8') as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)


def get_rd_items(kb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract all RD items from knowledge base."""
    items = kb.get('items', [])
    rd_items = [item for item in items if isinstance(item, dict) and item.get('vendor') == 'RD']
    return rd_items


def enrich_rd_item(item: Dict[str, Any], session, shop_id: str = '523', postal_code: str = '60601', zone_id: str = '974', debug: bool = False) -> Optional[Dict[str, Any]]:
    """
    Enrich a single RD item with data from Instacart RD search.
    
    Returns:
        Enriched item dict with all available information, or None if not found
    """
    # Try UPC first, then item_number
    upc = item.get('upc', '').strip()
    item_number = item.get('item_number', '').strip()
    
    search_query = upc if upc else item_number
    if not search_query:
        if debug:
            print(f"  Skipping item with no UPC or item_number: {item}", file=sys.stderr)
        return None
    
    if debug:
        print(f"  Searching for UPC/item_number: {search_query}", file=sys.stderr)
    
    try:
        # Search Instacart RD
        results = search_by_upc_graphql(session, search_query, shop_id=shop_id, postal_code=postal_code, zone_id=zone_id, debug=debug)
        
        if not results:
            if debug:
                print(f"  No results found for {search_query}", file=sys.stderr)
            return None
        
        # Use the first result (best match)
        product = results[0]
        
        # Enrich the item with all available information
        enriched = item.copy()
        
        # Update name if we have a better one
        if product.get('name'):
            enriched['canonical_name'] = product['name']
            enriched['product_name'] = product['name']
            enriched['display_name'] = product['name']
        
        # Add brand if available
        if product.get('brand'):
            enriched['brand'] = product['brand']
        
        # Add size if available
        if product.get('size'):
            enriched['size'] = product['size']
            # Also update purchase_uom if we can extract it
            size_text = product['size']
            if size_text:
                enriched['purchase_uom'] = size_text
        
        # Update UPC if we found a better one
        if product.get('UPC') or product.get('barcode'):
            upc_found = product.get('UPC') or product.get('barcode')
            if upc_found:
                enriched['upc'] = upc_found
        
        # Update item_number if we found productId
        if product.get('productId'):
            enriched['item_number'] = product['productId']
        
        # Add legacyId if available
        if product.get('legacyId'):
            enriched['legacy_id'] = product['legacyId']
        
        # Add detail URL
        if product.get('detail_url'):
            enriched['detail_url'] = product['detail_url']
        
        # Add evergreen URL
        if product.get('evergreenUrl'):
            enriched['evergreen_url'] = product['evergreenUrl']
        
        # Add Instacart price if available
        if product.get('price') is not None:
            enriched['instacart_price'] = product['price']
        if product.get('priceString'):
            enriched['instacart_price_string'] = product['priceString']
        
        # Add all other fields from product
        for key, value in product.items():
            if key not in enriched and value and key not in ['price', 'priceString']:  # Already handled above
                enriched[f'instacart_{key.lower()}'] = value
        
        # Mark as enriched
        enriched['enriched_from'] = 'instacart_rd'
        enriched['enriched_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        
        return enriched
    
    except Exception as e:
        if debug:
            print(f"  Error searching for {search_query}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="Enrich RD products in knowledge base with Instacart RD data")
    parser.add_argument("--cookie", help="Cookie string from browser")
    parser.add_argument("--auto-cookie", action="store_true", help="Read cookies from browser automatically")
    parser.add_argument("--shop-id", default="523", help="Shop ID (default: 523 for Restaurant Depot)")
    parser.add_argument("--postal-code", default="60601", help="Postal code (default: 60601)")
    parser.add_argument("--zone-id", default="974", help="Zone ID (default: 974)")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between requests in seconds (default: 1.0)")
    parser.add_argument("--max", type=int, help="Maximum number of items to process (for testing)")
    parser.add_argument("--debug", action="store_true", help="Print debug information")
    parser.add_argument("--dry-run", action="store_true", help="Don't save changes to knowledge base")
    
    args = parser.parse_args()
    
    if not (args.cookie or args.auto_cookie):
        print("Error: Must provide --cookie or --auto-cookie", file=sys.stderr)
        sys.exit(1)
    
    # Load knowledge base
    print("Loading knowledge base...")
    kb = load_knowledge_base()
    
    # Get RD items
    rd_items = get_rd_items(kb)
    print(f"Found {len(rd_items)} RD items in knowledge base")
    
    if not rd_items:
        print("No RD items found in knowledge base", file=sys.stderr)
        sys.exit(0)
    
    # Limit items if --max specified
    if args.max:
        rd_items = rd_items[:args.max]
        print(f"Processing first {len(rd_items)} items (--max={args.max})")
    
    # Create session
    print("Creating session...")
    session = get_session(cookie=args.cookie, auto_cookie=args.auto_cookie)
    
    # Process each item
    print(f"\nProcessing {len(rd_items)} RD items...")
    print("=" * 80)
    
    enriched_count = 0
    not_found_count = 0
    error_count = 0
    
    items_array = kb.get('items', [])
    items_index = {i: item for i, item in enumerate(items_array) if isinstance(item, dict) and item.get('vendor') == 'RD'}
    
    for idx, item in enumerate(rd_items, 1):
        upc = item.get('upc', '').strip()
        item_number = item.get('item_number', '').strip()
        name = item.get('canonical_name') or item.get('product_name') or item.get('display_name') or 'Unknown'
        
        print(f"\n[{idx}/{len(rd_items)}] Processing: {name}")
        if upc:
            print(f"  UPC: {upc}")
        if item_number:
            print(f"  Item Number: {item_number}")
        
        # Enrich item
        enriched = enrich_rd_item(
            item,
            session,
            shop_id=args.shop_id,
            postal_code=args.postal_code,
            zone_id=args.zone_id,
            debug=args.debug
        )
        
        if enriched:
            # Update the item in the knowledge base
            # Find the item in the items array and update it
            for i, kb_item in enumerate(items_array):
                if (isinstance(kb_item, dict) and 
                    kb_item.get('vendor') == 'RD' and
                    (kb_item.get('upc') == upc or kb_item.get('item_number') == item_number)):
                    items_array[i] = enriched
                    break
            
            enriched_count += 1
            print(f"  ✓ Enriched with data from Instacart RD")
            if enriched.get('brand'):
                print(f"    Brand: {enriched['brand']}")
            if enriched.get('size'):
                print(f"    Size: {enriched['size']}")
        else:
            not_found_count += 1
            print(f"  ✗ Not found in Instacart RD")
        
        # Delay between requests
        if idx < len(rd_items):
            time.sleep(args.delay)
    
    # Save updated knowledge base
    if not args.dry_run:
        kb['items'] = items_array
        save_knowledge_base(kb)
        print("\n" + "=" * 80)
        print(f"Knowledge base updated!")
        print(f"  Enriched: {enriched_count}")
        print(f"  Not found: {not_found_count}")
        print(f"  Errors: {error_count}")
        print(f"  Total processed: {len(rd_items)}")
    else:
        print("\n" + "=" * 80)
        print("DRY RUN - No changes saved")
        print(f"  Would enrich: {enriched_count}")
        print(f"  Would not find: {not_found_count}")
        print(f"  Would error: {error_count}")


if __name__ == "__main__":
    main()

