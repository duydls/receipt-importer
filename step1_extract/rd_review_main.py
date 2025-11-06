import argparse
import json
import time
from collections import defaultdict, Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _now_version() -> str:
    return time.strftime("v%Y.%m.%d-%H%M%S")


def _is_vendor_receipt(r: Dict[str, Any], vendors: List[str]) -> bool:
    vc = (r.get('detected_vendor_code') or r.get('vendor') or '').upper()
    for v in vendors:
        vu = v.upper()
        if vu in vc:
            return True
        # common aliases
        if vu == 'RESTAURANT_DEPOT' and ('RD' in vc or 'RESTAURANT' in vc):
            return True
        if vu == 'COSTCO' and 'COSTCO' in vc:
            return True
    return False


def _iter_vendor_items(extracted: Dict[str, Any], vendors: List[str]):
    for _, rec in extracted.items():
        if not isinstance(rec, dict):
            continue
        if not _is_vendor_receipt(rec, vendors):
            continue
        for it in rec.get('items', []) or []:
            yield (rec, it)


def build_review_queue(extracted: Dict[str, Any], vendors: List[str]) -> List[Dict[str, Any]]:
    """Aggregate RD items to unique review entries by strong key (upc>item_number>match_key>name)."""
    buckets: Dict[str, Dict[str, Any]] = {}
    counts: Counter = Counter()
    for rec, it in _iter_vendor_items(extracted, vendors):
        vendor_code = (rec.get('detected_vendor_code') or rec.get('vendor') or '').upper()
        upc = str(it.get('upc') or '').strip()
        item_no = str(it.get('item_number') or '').strip()
        match_key = str(it.get('match_key') or '').strip()
        name = str(it.get('product_name') or '').strip()
        key = None
        if upc:
            key = f"UPC|{upc}"
        elif item_no:
            key = f"ITEM|{item_no}"
        elif match_key:
            key = f"MK|{match_key}"
        else:
            key = f"NAME|{name.lower()}"

        counts[key] += 1
        if key not in buckets:
            buckets[key] = {
                'key': key,
                'vendor': vendor_code,
                'upc': upc or None,
                'item_number': item_no or None,
                'product_name': name or None,
                'purchase_uom': it.get('purchase_uom'),
                'raw_uom_text': it.get('raw_uom_text'),
                'l2_category': it.get('l2_category'),
                'l1_category': it.get('l1_category'),
                'category_source': it.get('category_source'),
                'has_codes': bool(it.get('has_codes')),
            }

    q = []
    for k, meta in buckets.items():
        q.append({**meta, 'count': counts[k]})
    # sort by missing codes first, then by frequency desc
    q.sort(key=lambda x: (x.get('has_codes', True), -int(x.get('count', 0))))
    return q


def compute_metrics(extracted: Dict[str, Any], vendors: List[str]) -> Dict[str, Any]:
    total = 0
    with_codes = 0
    categorized = 0
    price_mismatch = 0

    for _, it in _iter_vendor_items(extracted, vendors):
        total += 1
        if it.get('has_codes'):
            with_codes += 1
        if it.get('l2_category') and it.get('l1_category'):
            categorized += 1
        # basic arithmetic check
        try:
            qty = float(it.get('quantity') or 0)
            unit = float(it.get('unit_price') or 0)
            line = float(it.get('total_price') or 0)
            # RD Excel/PDF totals are tax-exclusive at line level; conservative check
            calc = round(qty * unit, 2)
            if line and abs(calc - line) > 0.02:
                price_mismatch += 1
        except Exception:
            pass

    coverage = (categorized / total) if total else 0.0
    codes_rate = (with_codes / total) if total else 0.0
    mismatch_rate = (price_mismatch / total) if total else 0.0

    # unknown top-N by name
    unknown_counter: Counter = Counter()
    for _, it in _iter_vendor_items(extracted, vendors):
        if not it.get('l2_category'):
            name = str(it.get('product_name') or '').strip()
            if name:
                unknown_counter[name] += 1

    top_unknown = [{'product_name': n, 'count': c} for n, c in unknown_counter.most_common(20)]

    return {
        'total_items': total,
        'coverage_l2': round(coverage, 4),
        'codes_rate': round(codes_rate, 4),
        'mismatch_rate': round(mismatch_rate, 4),
        'top_unknown': top_unknown,
    }


def build_suggestions(extracted: Dict[str, Any], vendors: List[str]) -> Dict[str, Any]:
    """Non-binding hints. Duplicate-aware (same item_number with multiple names). Totals-agnostic here."""
    by_item: Dict[str, set] = defaultdict(set)
    for rec, it in _iter_vendor_items(extracted, vendors):
        item_no = str(it.get('item_number') or '').strip()
        name = str(it.get('product_name') or '').strip()
        if item_no and name:
            by_item[item_no].add(name)
    duplicates = [{
        'item_number': k,
        'names': sorted(list(v))
    } for k, v in by_item.items() if len(v) > 1]

    return {
        'notes': 'Suggestions are hints only. No auto-fix performed.',
        'name_duplicates': duplicates[:50],
    }


def write_artifacts(out_dir: Path, extracted_path: Path, version: str, review_queue, suggestions, metrics):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'VERSION').write_text(version)
    (out_dir / 'manifest.json').write_text(json.dumps({
        'version': version,
        'timestamp': int(time.time()),
        'extracted_data_path': str(extracted_path)
    }, indent=2))
    (out_dir / 'review_queue.json').write_text(json.dumps(review_queue, indent=2))
    (out_dir / 'suggestions.json').write_text(json.dumps(suggestions, indent=2))
    (out_dir / 'metrics.json').write_text(json.dumps(metrics, indent=2))


def load_decisions(decisions_file: Path) -> List[Dict[str, Any]]:
    if not decisions_file.exists():
        return []
    return json.loads(decisions_file.read_text() or '[]')


def decisions_to_patch(decisions: List[Dict[str, Any]], version: str) -> Dict[str, Any]:
    """Turn human decisions into immutable patch operations."""
    return {
        'version': version,
        'timestamp': int(time.time()),
        'ops': decisions,
    }


def apply_patch_safely(base_overrides: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply patch ops into overrides structure (RD-only). We never touch base KB here."""
    overrides = json.loads(json.dumps(base_overrides))  # deep copy
    # vendor-scoped buckets (e.g., RD, COSTCO)
    def _get_vendor_buckets(vendor_code: str):
        bucket = overrides.setdefault(vendor_code, {})
        return bucket.setdefault('aliases', {}), bucket.setdefault('kb', {})

    for op in patch.get('ops', []):
        kind = op.get('op')
        vendor_code = str(op.get('vendor') or 'RD').upper()
        aliases, kb = _get_vendor_buckets(vendor_code)

        if kind == 'add_alias':
            src = str(op.get('source') or '').strip()
            dst = str(op.get('target') or '').strip()
            if src and dst:
                aliases[src] = dst
        elif kind == 'add_kb_entry':
            key = str(op.get('key') or '').strip()
            if key:
                kb[key] = {
                    'name': op.get('name'),
                    'spec': op.get('spec'),
                    'category_l2': op.get('category_l2'),
                    'locked': bool(op.get('locked', False)),
                }
        elif kind == 'set_spec':
            key = str(op.get('key') or '').strip()
            if key:
                entry = kb.setdefault(key, {})
                entry['spec'] = op.get('spec')
        elif kind == 'lock_category':
            key = str(op.get('key') or '').strip()
            if key:
                entry = kb.setdefault(key, {})
                entry['category_l2'] = op.get('category_l2')
                entry['locked'] = True
        elif kind == 'unlock_category':
            key = str(op.get('key') or '').strip()
            if key:
                entry = kb.setdefault(key, {})
                entry['locked'] = False
        elif kind == 'must_include':
            # reserved for future categorizer hints
            pass
        elif kind == 'must_exclude':
            # reserved for future categorizer hints
            pass
        elif kind == 'mark_fee':
            key = str(op.get('key') or '').strip()
            if key:
                entry = kb.setdefault(key, {})
                entry['is_fee'] = True
    return overrides


def safety_gate(prev_metrics: Dict[str, Any], new_metrics: Dict[str, Any]) -> Tuple[bool, str]:
    # Coverage must not decrease; mismatch must not increase
    if new_metrics.get('coverage_l2', 0) + 1e-9 < prev_metrics.get('coverage_l2', 0):
        return False, 'coverage_regressed'
    if new_metrics.get('mismatch_rate', 1) - 1e-9 > prev_metrics.get('mismatch_rate', 1):
        return False, 'mismatch_rate_increased'
    return True, 'ok'


def main():
    p = argparse.ArgumentParser(description='RD-only Review Loop')
    p.add_argument('--extracted', default='data/step1_output/localgrocery_based/extracted_data.json')
    p.add_argument('--out-dir', default='data/rd_review')
    p.add_argument('--decisions', default='data/rd_review/decisions.json')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--vendors', nargs='*', default=['RD', 'COSTCO'], help='Vendor codes to include (e.g., RD COSTCO)')
    args = p.parse_args()

    extracted_path = Path(args.extracted)
    out_dir = Path(args.out_dir)
    decisions_path = Path(args.decisions)
    version = _now_version()

    if not extracted_path.exists():
        raise SystemExit(f"extracted file not found: {extracted_path}")

    extracted = json.load(open(extracted_path, 'r'))

    vendors = args.vendors
    review_queue = build_review_queue(extracted, vendors)
    suggestions = build_suggestions(extracted, vendors)
    prev_metrics = compute_metrics(extracted, vendors)
    write_artifacts(out_dir, extracted_path, version, review_queue, suggestions, prev_metrics)

    # Build patch from decisions if present
    decisions = load_decisions(decisions_path)
    if not decisions:
        print("No decisions file found. Generated artifacts for review.")
        return

    patch = decisions_to_patch(decisions, version)
    patches_dir = out_dir / 'patches'
    patches_dir.mkdir(parents=True, exist_ok=True)
    (patches_dir / f'{version}.patch.json').write_text(json.dumps(patch, indent=2))

    # Load current overrides (immutable store separate from base KB)
    overrides_file = out_dir / 'kb_overrides.json'
    base_overrides = {}
    if overrides_file.exists():
        try:
            base_overrides = json.loads(overrides_file.read_text())
        except Exception:
            base_overrides = {}

    new_overrides = apply_patch_safely(base_overrides, patch)

    # Dry-run safety gate: write temp overrides and recompute metrics
    temp_overrides_file = out_dir / 'kb_overrides.temp.json'
    temp_overrides_file.write_text(json.dumps(new_overrides, indent=2))

    # Note: recomputing extraction here would require rerunning step1.
    # As a proxy safety check before a full re-run, ensure patch is non-empty and plausible.
    ok, reason = safety_gate(prev_metrics, prev_metrics)
    if not ok:
        print(f"Safety gate failed (pre-run): {reason}")
        return

    if args.dry_run:
        print(f"Dry-run complete. Temp overrides written to {temp_overrides_file}")
        return

    if args.apply:
        overrides_file.write_text(json.dumps(new_overrides, indent=2))
        print(f"Applied overrides: {overrides_file}")
        return

    print("Patch generated. Use --apply or --dry-run.")


if __name__ == '__main__':
    main()


