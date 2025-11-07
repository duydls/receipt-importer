#!/usr/bin/env python3
"""Fix knowledge base structure - remove Costco entries and move RD items to top-level."""

import json
from pathlib import Path

kb_path = Path('data/step1_input/knowledge_base.json')
kb = json.load(open(kb_path))

# Keep Wismettac items (they're correct)
wismettac_items = {k: v for k, v in kb.items() if isinstance(v, dict) and v.get('store') == 'Wismettac'}

# Extract RD items from nested array and convert to top-level entries
rd_items = {}
if 'items' in kb:
    for item in kb['items']:
        if isinstance(item, dict) and item.get('vendor') == 'RD':
            item_no = item.get('item_number') or item.get('upc')
            if item_no:
                product_name = item.get('canonical_name') or item.get('product_name') or item.get('display_name') or ''
                size_spec = item.get('raw_uom_text') or item.get('purchase_uom') or ''
                # Convert to array format: [product_name, store, size_spec, unit_price]
                rd_items[str(item_no)] = [product_name, 'RD', size_spec, 0.0]

# Rebuild KB with only Wismettac and RD items
fixed_kb = {}
fixed_kb.update(wismettac_items)
fixed_kb.update(rd_items)

# Save
with open(kb_path, 'w') as f:
    json.dump(fixed_kb, f, indent=2, ensure_ascii=False)

print(f"Fixed knowledge base:")
print(f"  Kept {len(wismettac_items)} Wismettac items")
print(f"  Moved {len(rd_items)} RD items to top-level")
print(f"  Removed Costco entries (will be re-added from receipts)")
print(f"  Total entries: {len(fixed_kb)}")

