#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Dict, Any

KB_PATH = Path('data/step1_input/knowledge_base.json')
ENRICH_PATH = Path('data/step1_output/wismettac_based/wismettac_enrichment.json')
OUT_PATH = KB_PATH  # in-place update


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def main() -> None:
    kb = load_json(KB_PATH)
    enrich = load_json(ENRICH_PATH)
    if not enrich:
        print('No enrichment file at', ENRICH_PATH)
        return

    kb_items = kb.get('items')
    if kb_items is None or not isinstance(kb_items, list):
        kb_items = []

    # Build index by vendor+item_number or upc
    def kb_key(row: Dict[str, Any]) -> str:
        vendor = (row.get('vendor') or '').upper()
        key = row.get('item_number') or row.get('upc') or row.get('sku')
        return f"{vendor}:{key}" if vendor and key else ''

    index: Dict[str, Dict[str, Any]] = {}
    for row in kb_items:
        k = kb_key(row)
        if k:
            index[k] = row

    merged = 0
    for item_no, rec in enrich.items():
        # Build KB row
        row: Dict[str, Any] = {
            'vendor': 'WISMETTAC',
            'item_number': str(item_no),
            'upc': rec.get('barcode') or '',
            'vendor_brand': rec.get('brand') or '',
            'vendor_category': rec.get('category') or '',
            'pack_size_raw': rec.get('packSizeRaw') or '',
        }
        pp = rec.get('packParsed') or {}
        if isinstance(pp, dict):
            if pp.get('caseQty') is not None:
                row['pack_case_qty'] = pp.get('caseQty')
            if pp.get('each') is not None:
                row['each_qty'] = pp.get('each')
            if pp.get('uom'):
                row['each_uom'] = pp.get('uom')
        # Merge behavior: overwrite or insert
        k = kb_key(row)
        if not k:
            continue
        if k in index:
            index[k].update({k2: v for k2, v in row.items() if v not in (None, '')})
        else:
            kb_items.append(row)
            index[k] = row
        merged += 1

    kb['items'] = kb_items
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open('w', encoding='utf-8') as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    print(f'Merged {merged} Wismettac items into {OUT_PATH}')


if __name__ == '__main__':
    main()
