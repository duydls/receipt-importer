#!/usr/bin/env python3
"""
RD Amount Reconciler
Post-extraction correction for RD (Restaurant Depot) scanned receipts where OCR may drop
the leading digit of right-aligned amounts (e.g., "14.40" -> "4.40").

Scope: RD only. Safe, deterministic corrections with metadata for reporting.
"""

from __future__ import annotations

import logging
from statistics import median
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _norm_name(name: str) -> str:
    import re
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t and t not in {"rd", "restaurant", "depot", "frozen", "fz", "whl", "whole"}]
    tokens.sort()
    return " ".join(tokens)


def _cluster_key(item: Dict[str, Any]) -> Tuple[str, str, str]:
    upc = str(item.get("upc") or "").strip()
    item_no = str(item.get("item_number") or "").strip()
    if upc:
        return ("upc", upc, "")
    if item_no:
        return ("item", item_no, "")
    return ("name", _norm_name(item.get("product_name") or ""), str(item.get("purchase_uom") or ""))


def _qty(item: Dict[str, Any]) -> Optional[float]:
    try:
        q = item.get("quantity")
        return float(q) if q is not None and str(q) != "" else None
    except Exception:
        return None


def _money(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return round(v, 2)
    except Exception:
        return None


def _is_discount_like(item: Dict[str, Any]) -> bool:
    name = (item.get("product_name") or "").lower()
    if any(k in name for k in ["discount", "coupon", "refund", "promo", "return"]):
        return True
    tp = _money(item.get("total_price"))
    return tp is not None and tp < 0


def _median_unit_price(cluster: List[Dict[str, Any]]) -> Optional[float]:
    vals: List[float] = []
    for it in cluster:
        q = _qty(it)
        tp = _money(it.get("total_price"))
        up = _money(it.get("unit_price"))
        if up is None and tp is not None and q and q > 0:
            up = round(tp / q, 2)
        if up is not None and up > 0:
            vals.append(up)
    if not vals:
        return None
    try:
        return round(median(vals), 2)
    except Exception:
        return None


def _score_candidate(item: Dict[str, Any], candidate_total: float, doc_totals: Dict[str, float], cluster_median_up: Optional[float]) -> float:
    """
    Combined score of row arithmetic, document reconciliation, and cluster consistency.
    Score in [0, 1]. Higher is better.
    """
    score = 0.0
    weights = {"doc": 0.5, "row": 0.35, "cluster": 0.15}

    # Row arithmetic consistency
    q = _qty(item) or 0.0
    up = _money(item.get("unit_price"))
    row_match = 0.0
    if q > 0:
        expected = (up if up is not None else 0.0) * q
        row_match = 1.0 - min(abs((expected - candidate_total)) / (abs(expected) + 1e-6), 1.0)
    score += weights["row"] * row_match

    # Document reconciliation (if totals provided)
    doc_score = 0.0
    if doc_totals:
        # Assume we update this line only — simulate receipt reconciliation
        current_tp = _money(item.get("total_price")) or 0.0
        delta = candidate_total - current_tp
        subtotal = float(doc_totals.get("subtotal", 0.0) or 0.0)
        total = float(doc_totals.get("total", 0.0) or 0.0)
        tax = float(doc_totals.get("tax", 0.0) or 0.0)
        # Desired: subtotal + tax ~= total after applying delta to subtotal
        new_subtotal = subtotal + delta
        desired_total = new_subtotal + tax
        doc_score = 1.0 - min(abs(desired_total - total) / (abs(total) + 1e-6), 1.0)
    score += weights["doc"] * doc_score

    # Cluster consistency: candidate unit price close to median
    cluster_score = 0.0
    if cluster_median_up and q > 0:
        cand_up = candidate_total / q
        cluster_score = 1.0 - min(abs(cand_up - cluster_median_up) / (cluster_median_up + 1e-6), 1.0)
    score += weights["cluster"] * cluster_score

    return max(0.0, min(1.0, score))


def reconcile_rd_amounts(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Apply RD-only reconciliation for suspicious short amounts and merge duplicates.

    Adds metadata to item:
      - rd_fix_status: 'fixed' | 'flagged' | None
      - rd_fix_reason, rd_fix_improvement_pct, rd_source_indices (for merged)
    """
    vendor = (receipt.get("vendor") or receipt.get("detected_vendor_code") or "").upper()
    if vendor not in {"RD", "RESTAURANT_DEPOT"}:
        return receipt

    items: List[Dict[str, Any]] = list(receipt.get("items", []))
    if not items:
        return receipt

    # Exclude discounts/returns from clustering
    work_items: List[Tuple[int, Dict[str, Any]]] = [
        (idx, it) for idx, it in enumerate(items) if not _is_discount_like(it)
    ]

    # Build clusters
    clusters: Dict[Tuple[str, str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    for idx, it in work_items:
        key = _cluster_key(it)
        clusters.setdefault(key, []).append((idx, it))

    # Precompute cluster medians
    cluster_medians: Dict[Tuple[str, str, str], Optional[float]] = {}
    for k, pairs in clusters.items():
        cluster_medians[k] = _median_unit_price([p[1] for p in pairs])

    # Document totals
    doc_totals = {
        "subtotal": _money(receipt.get("subtotal")) or 0.0,
        "tax": _money(receipt.get("tax")) or 0.0,
        "total": _money(receipt.get("total")) or 0.0,
    }

    # Detect suspicious items and propose corrections
    fixed_indices = set()
    for key, pairs in clusters.items():
        median_up = cluster_medians.get(key)
        for idx, it in pairs:
            tp = _money(it.get("total_price"))
            if tp is None or tp <= 0:
                continue
            q = _qty(it) or 0.0

            # Heuristic: suspicious if value < 10 and cluster median suggests ~10–30
            if tp < 10.0 and (median_up is not None) and (10.0 <= median_up <= 30.0):
                # Candidate set: 10x prefix + two decimals normalized
                base = round(tp, 2)
                candidates = [round(base + 10.0, 2), round(base + 20.0, 2)]
                # Cluster-anchored
                if q > 0 and median_up:
                    candidates.append(round(median_up * q, 2))

                # Score candidates
                orig_score = _score_candidate(it, tp, doc_totals, median_up)
                best_score = orig_score
                best_val = tp
                for cand in candidates:
                    s = _score_candidate(it, cand, doc_totals, median_up)
                    if s > best_score:
                        best_score = s
                        best_val = cand

                improvement = 0.0 if orig_score == 0 else (best_score - orig_score) / max(1e-6, (1.0 - orig_score))

                if best_val != tp and best_score >= 0.8 and improvement >= 0.8:
                    # Accept fix
                    old_tp = tp
                    it['total_price'] = best_val
                    # Backfill/align unit price if possible
                    if q > 0:
                        it['unit_price'] = round((best_val / q), 2)
                    it['rd_fix_status'] = 'fixed'
                    it['rd_fix_reason'] = 'RD: missing leading digit; improved row/page/cluster consistency'
                    it['rd_fix_improvement_pct'] = round(best_score * 100, 1)
                    fixed_indices.add(idx)
                    logger.info(f"RD fix: idx={idx} {old_tp} -> {best_val} (score={best_score:.2f})")
                else:
                    # Flag for review
                    it['rd_fix_status'] = 'flagged'
                    it['rd_fix_reason'] = 'RD: suspicious short amount; insufficient evidence to auto-fix'
                    it['rd_fix_improvement_pct'] = round(best_score * 100, 1)

    # Merge duplicates within clusters (post-fix)
    merged_items: List[Dict[str, Any]] = []
    consumed = set()
    for key, pairs in clusters.items():
        # Re-read possibly updated items
        cluster_list = [(idx, items[idx]) for idx, _ in pairs]
        # Avoid discounts
        cluster_list = [(i, it) for (i, it) in cluster_list if not _is_discount_like(it)]
        if len(cluster_list) <= 1:
            continue

        # Aggregate
        total_qty = 0.0
        total_amount = 0.0
        source_idx = []
        for idx, it in cluster_list:
            q = _qty(it) or 0.0
            tp = _money(it.get('total_price')) or 0.0
            total_qty += q
            total_amount += tp
            source_idx.append(idx)
        if total_qty <= 0 or total_amount <= 0:
            continue

        # Build merged representative from the first item
        rep_idx, rep = cluster_list[0]
        merged = dict(rep)
        merged['quantity'] = round(total_qty, 2)
        merged['total_price'] = round(total_amount, 2)
        # Use cluster median unit or recomputed stable
        median_up = cluster_medians.get(key)
        stable_up = round(total_amount / total_qty, 2)
        merged['unit_price'] = round(median_up, 2) if (median_up and abs(median_up - stable_up) / median_up <= 0.2) else stable_up
        merged['rd_fix_status'] = (merged.get('rd_fix_status') or 'merged')
        merged['rd_source_indices'] = source_idx

        merged_items.append((key, merged, source_idx))

    # Apply merges: replace first occurrence and delete others
    for key, merged, idxs in merged_items:
        idxs_sorted = sorted(idxs)
        keep = idxs_sorted[0]
        items[keep] = merged
        for j in idxs_sorted[1:]:
            items[j] = None  # mark for removal
    receipt['items'] = [it for it in items if it]

    return receipt


