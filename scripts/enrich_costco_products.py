#!/usr/bin/env python3
"""
Enrich Costco products in knowledge base with data from Instacart Costco search.

This script:
1. Loads all Costco products from knowledge_base.json
2. For each product, searches Instacart Costco using item_number or product name
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

# Import the Instacart Costco search function
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))
try:
    from instacart_costco_search import get_session, search_by_upc_graphql
except ImportError:
    # Try relative import
    spec = importlib.util.spec_from_file_location("instacart_costco_search", scripts_dir / "instacart_costco_search.py")
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


def get_costco_items(kb: Dict[str, Any]) -> List[tuple]:
    """Extract all Costco items from knowledge base.
    
    Returns:
        List of tuples: (item_number, item_data) where item_data can be:
        - Array format: [product_name, "Costco", size_spec, unit_price]
        - Dict format: {item_number, store, name, ...}
    """
    costco_items = []
    for item_number, item_data in kb.items():
        # Handle array format
        if isinstance(item_data, list) and len(item_data) >= 2 and item_data[1] == 'Costco':
            costco_items.append((item_number, item_data))
        # Handle dict format (already enriched)
        elif isinstance(item_data, dict) and item_data.get('store') == 'Costco':
            costco_items.append((item_number, item_data))
    return costco_items


def enrich_costco_item(item_number: str, item_data: Any, session, shop_id: str = '83', postal_code: str = '60601', zone_id: str = '974', debug: bool = False) -> Optional[Dict[str, Any]]:
    """
    Enrich a single Costco item with data from Instacart Costco search.
    
    Args:
        item_number: Item number (key in knowledge base)
        item_data: Can be:
            - Array format: [product_name, "Costco", size_spec, unit_price]
            - Dict format: {item_number, store, name, ...}
        session: Requests session with cookies
        shop_id: Shop ID for Costco (default: 83)
        postal_code: Postal code (default: 60601)
        zone_id: Zone ID (default: 974)
        debug: Enable debug output
    
    Returns:
        Enriched item dict with all available information, or None if not found
    """
    # Handle both array and dict formats
    if isinstance(item_data, list):
        product_name = item_data[0] if len(item_data) > 0 else ''
        size_spec = item_data[2] if len(item_data) > 2 else ''
        unit_price = item_data[3] if len(item_data) > 3 else 0.0
    elif isinstance(item_data, dict):
        product_name = item_data.get('name') or item_data.get('product_name') or item_data.get('canonical_name') or ''
        size_spec = item_data.get('size') or item_data.get('size_spec') or ''
        unit_price = item_data.get('unit_price', 0.0)
    else:
        product_name = ''
        size_spec = ''
        unit_price = 0.0
    
    # For Costco, rely on item_number only (as per user request)
    search_query = item_number
    if not search_query:
        if debug:
            print(f"  Skipping item with no item_number: {item_data}", file=sys.stderr)
        return None
    
    if debug:
        print(f"  Searching for item_number only: {search_query}", file=sys.stderr)
    
    try:
        # Search Instacart Costco
        results = search_by_upc_graphql(session, search_query, shop_id=shop_id, postal_code=postal_code, zone_id=zone_id, debug=debug)
        
        if not results:
            if debug:
                print(f"  No results found for {search_query}", file=sys.stderr)
            return None
        
        # Filter results to find exact item number match
        # For Costco, we need to match the item_number with the productId or item_number in results
        matched_product = None
        for product in results:
            # Check if productId or item_number matches the search query exactly
            product_id = str(product.get('productId', '') or product.get('item_number', '')).strip()
            if product_id == item_number:
                matched_product = product
                if debug:
                    print(f"  Found exact match: productId={product_id} matches item_number={item_number}", file=sys.stderr)
                break
        
        # If no exact match, try to find products where item_number appears in productId
        if not matched_product:
            for product in results:
                product_id = str(product.get('productId', '') or product.get('item_number', '')).strip()
                # Check if item_number is at the end of productId (e.g., productId ends with item_number)
                if product_id.endswith(item_number):
                    matched_product = product
                    if debug:
                        print(f"  Found suffix match: productId={product_id} ends with item_number={item_number}", file=sys.stderr)
                    break
        
        # If still no match, check if item_number appears in the product name or other fields
        if not matched_product:
            for product in results:
                product_name = str(product.get('name', '') or '').upper()
                # Check if item number appears in product name (e.g., "Item #3923" or "3923")
                if item_number in product_name or f"#{item_number}" in product_name:
                    matched_product = product
                    if debug:
                        print(f"  Found name match: item_number={item_number} appears in product name", file=sys.stderr)
                    break
        
        # If still no match, use the first result (for Costco, search by item_number works correctly)
        # The productId in Instacart is different from Costco item_number, but the search finds the right product
        if not matched_product and results:
            matched_product = results[0]
            if debug:
                product_id = str(matched_product.get('productId') or matched_product.get('item_number') or '').strip()
                print(f"  Using first result (productId={product_id}) for item_number={item_number}", file=sys.stderr)
                print(f"  Product name: {matched_product.get('name', 'N/A')[:60]}", file=sys.stderr)
        
        # If still no match, return None
        if not matched_product:
            if debug:
                print(f"  Warning: No results found for item_number={item_number}", file=sys.stderr)
            return None
        
        product = matched_product
        
        # Build enriched item dict
        enriched = {
            'item_number': item_number,
            'store': 'Costco',
            'name': product.get('name') or product_name,
            'product_name': product.get('name') or product_name,
            'canonical_name': product.get('name') or product_name,
            'display_name': product.get('name') or product_name,
            'size': product.get('size') or size_spec,
            'size_spec': product.get('size') or size_spec,
            'unit_price': unit_price,
        }
        
        # Add brand if available
        if product.get('brand'):
            enriched['brand'] = product['brand']
        
        # Add UPC if available
        if product.get('UPC') or product.get('barcode'):
            upc_found = product.get('UPC') or product.get('barcode')
            if upc_found:
                enriched['barcode'] = upc_found
                enriched['upc'] = upc_found
        
        # Add product ID if available
        if product.get('productId'):
            enriched['product_id'] = product['productId']
        
        # Add legacy ID if available
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
                enriched[f'instacart_{key.lower().replace(" ", "_")}'] = value
        
        # Mark as enriched
        enriched['enriched_from'] = 'instacart_costco'
        enriched['enriched_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        
        return enriched
    
    except Exception as e:
        if debug:
            print(f"  Error searching for {search_query}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="Enrich Costco products in knowledge base with Instacart Costco data")
    parser.add_argument("--cookie", help="Cookie string from browser")
    parser.add_argument("--auto-cookie", action="store_true", help="Read cookies from browser automatically")
    parser.add_argument("--shop-id", default="83", help="Shop ID (default: 83 for Costco)")
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
    
    # Get Costco items
    costco_items = get_costco_items(kb)
    print(f"Found {len(costco_items)} Costco items in knowledge base")
    
    if not costco_items:
        print("No Costco items found in knowledge base", file=sys.stderr)
        sys.exit(0)
    
    # Limit items if --max specified
    if args.max:
        costco_items = costco_items[:args.max]
        print(f"Processing first {len(costco_items)} items (--max={args.max})")
    
    # Create session
    print("Creating session...")
    session = get_session(cookie=args.cookie, auto_cookie=args.auto_cookie)
    
    # Process each item
    print(f"\nProcessing {len(costco_items)} Costco items...")
    print("=" * 80)
    
    enriched_count = 0
    not_found_count = 0
    error_count = 0
    
    for idx, (item_number, item_data) in enumerate(costco_items, 1):
        # Handle both array and dict formats
        if isinstance(item_data, list):
            product_name = item_data[0] if len(item_data) > 0 else 'Unknown'
        elif isinstance(item_data, dict):
            product_name = item_data.get('name') or item_data.get('product_name') or item_data.get('canonical_name') or 'Unknown'
        else:
            product_name = 'Unknown'
        
        print(f"\n[{idx}/{len(costco_items)}] Processing: {product_name}")
        print(f"  Item Number: {item_number}")
        
        # Enrich item
        enriched = enrich_costco_item(
            item_number,
            item_data,
            session,
            shop_id=args.shop_id,
            postal_code=args.postal_code,
            zone_id=args.zone_id,
            debug=args.debug
        )
        
        if enriched:
            # Update the item in the knowledge base
            # Convert enriched dict to array format for backward compatibility
            # But also keep the enriched dict for future use
            # For now, we'll store as dict but could convert back to array format
            kb[item_number] = enriched
            
            enriched_count += 1
            print(f"  ✓ Enriched with data from Instacart Costco")
            if enriched.get('brand'):
                print(f"    Brand: {enriched['brand']}")
            if enriched.get('size'):
                print(f"    Size: {enriched['size']}")
            if enriched.get('barcode'):
                print(f"    UPC: {enriched['barcode']}")
        else:
            not_found_count += 1
            print(f"  ✗ Not found in Instacart Costco")
        
        # Delay between requests
        if idx < len(costco_items):
            time.sleep(args.delay)
    
    # Save updated knowledge base
    if not args.dry_run:
        save_knowledge_base(kb)
        print("\n" + "=" * 80)
        print(f"Knowledge base updated!")
        print(f"  Enriched: {enriched_count}")
        print(f"  Not found: {not_found_count}")
        print(f"  Errors: {error_count}")
        print(f"  Total processed: {len(costco_items)}")
    else:
        print("\n" + "=" * 80)
        print("DRY RUN - No changes saved")
        print(f"  Would enrich: {enriched_count}")
        print(f"  Would not find: {not_found_count}")
        print(f"  Would error: {error_count}")


if __name__ == "__main__":
    main()

