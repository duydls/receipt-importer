#!/usr/bin/env python3
"""
Fix Knowledge Base Structure

This script:
1. Removes incorrect/outdated Costco entries
2. Moves RD items from nested "items" array to top-level entries
3. Ensures consistent format across all vendors
"""

import json
from pathlib import Path
from typing import Dict, Any

KB_PATH = Path('data/step1_input/knowledge_base.json')


def load_kb() -> Dict[str, Any]:
    """Load knowledge base."""
    if not KB_PATH.exists():
        return {}
    with KB_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def save_kb(kb: Dict[str, Any]) -> None:
    """Save knowledge base."""
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with KB_PATH.open('w', encoding='utf-8') as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)


def main():
    """Fix knowledge base structure."""
    print("=" * 80)
    print("FIXING KNOWLEDGE BASE STRUCTURE")
    print("=" * 80)
    
    kb = load_kb()
    if not kb:
        print("Knowledge base is empty or doesn't exist")
        return
    
    print(f"Loaded knowledge base with {len(kb)} top-level entries")
    
    # Count items by type
    wismettac_count = 0
    costco_count = 0
    rd_items_count = 0
    
    # Identify Wismettac items (dict format with store='Wismettac')
    wismettac_items = {}
    costco_items = {}
    rd_items = {}
    
    for key, value in kb.items():
        if key == 'items':
            # Skip the nested items array for now
            continue
        
        if isinstance(value, dict):
            if value.get('store') == 'Wismettac':
                wismettac_items[key] = value
                wismettac_count += 1
        elif isinstance(value, list) and len(value) >= 2:
            if value[1] == 'Costco':
                costco_items[key] = value
                costco_count += 1
    
    # Extract RD items from nested "items" array
    if 'items' in kb:
        rd_items_array = kb.get('items', [])
        for item in rd_items_array:
            if isinstance(item, dict) and item.get('vendor') == 'RD':
                item_no = item.get('item_number') or item.get('upc')
                if item_no:
                    # Convert to top-level entry format
                    # Use array format: [product_name, store, size_spec, unit_price]
                    # But we don't have unit_price from RD receipts, so use 0.0
                    product_name = item.get('canonical_name') or item.get('product_name') or item.get('display_name') or ''
                    size_spec = item.get('raw_uom_text') or ''
                    
                    rd_items[str(item_no)] = [
                        product_name,
                        'RD',
                        size_spec,
                        0.0  # No price available from receipts
                    ]
                    rd_items_count += 1
    
    print(f"\nFound:")
    print(f"  Wismettac items: {wismettac_count}")
    print(f"  Costco items: {costco_count}")
    print(f"  RD items (in nested array): {rd_items_count}")
    
    # Ask user what to do with Costco items
    print("\n" + "=" * 80)
    print("COSTCO ITEMS")
    print("=" * 80)
    print("Current Costco entries (may be outdated/incorrect):")
    for key, value in sorted(costco_items.items())[:10]:
        print(f"  {key}: {value}")
    
    if costco_count > 0:
        print(f"\n⚠ Found {costco_count} Costco entries in old format.")
        print("These may contain outdated/incorrect data.")
        print("\nOptions:")
        print("  1. Remove all Costco entries (recommended - they'll be re-added from receipts)")
        print("  2. Keep Costco entries as-is")
        choice = input("\nEnter choice (1 or 2, default=1): ").strip() or "1"
        
        if choice == "1":
            print("Removing Costco entries...")
            # Remove Costco entries
            for key in list(costco_items.keys()):
                del kb[key]
            print(f"✓ Removed {costco_count} Costco entries")
        else:
            print("Keeping Costco entries as-is")
    
    # Move RD items from nested array to top-level
    if rd_items_count > 0:
        print("\n" + "=" * 80)
        print("RD ITEMS")
        print("=" * 80)
        print(f"Moving {rd_items_count} RD items from nested array to top-level entries...")
        
        # Remove nested items array
        if 'items' in kb:
            del kb['items']
        
        # Add RD items as top-level entries
        for item_no, entry in rd_items.items():
            kb[item_no] = entry
        
        print(f"✓ Moved {rd_items_count} RD items to top-level entries")
    
    # Save fixed knowledge base
    save_kb(kb)
    
    # Final stats
    final_count = len([k for k in kb.keys() if k != 'items'])
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Knowledge base now contains {final_count} top-level entries")
    print(f"  Wismettac: {wismettac_count} items")
    if choice == "2":
        print(f"  Costco: {costco_count} items")
    print(f"  RD: {rd_items_count} items")
    print("=" * 80)
    print(f"\n✓ Knowledge base saved to: {KB_PATH}")


if __name__ == '__main__':
    main()

