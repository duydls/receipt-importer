#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Dict, Any, List

ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / 'data/step1_input/knowledge_base.json'
LOCAL_OUT = ROOT / 'data/step1_output/localgrocery_based/extracted_data.json'


def _load_json(p: Path):
    if not p.exists():
        return {}
    with p.open('r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def _norm(s: Any) -> str:
    return (str(s).strip()) if s is not None else ''


def main() -> None:
    kb = _load_json(KB_PATH)
    extracted = _load_json(LOCAL_OUT)

    kb_items: List[Dict[str, Any]] = kb.get('items') or []

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
    for rid, rec in extracted.items():
        vendor_code = (rec.get('vendor') or rec.get('vendor_name') or rec.get('detected_vendor_code') or '').upper()
        if vendor_code not in ('RD', 'RESTAURANT DEPOT', 'RESTAURANT_DEPOT', 'RESTAURANT'):
            continue
        for it in rec.get('items', []):
            if it.get('is_fee'):
                continue
            item_no = _norm(it.get('item_number'))
            upc = _norm(it.get('upc'))
            if not item_no and not upc:
                continue
            row = {
                'vendor': 'RD',
                'item_number': item_no,
                'upc': upc,
            }
            # Optional helpful fields
            for k in ('canonical_name', 'product_name', 'display_name', 'raw_uom_text', 'purchase_uom'):
                v = _norm(it.get(k))
                if v:
                    row[k] = v
            k = kb_key(row)
            if not k:
                continue
            if k in index:
                index[k].update({kk: vv for kk, vv in row.items() if vv})
            else:
                kb_items.append(row)
                index[k] = row
            merged += 1

    kb['items'] = kb_items
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with KB_PATH.open('w', encoding='utf-8') as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    print(f'Merged/updated {merged} RD items into {KB_PATH}')


if __name__ == '__main__':
    main()
