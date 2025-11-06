#!/usr/bin/env python3
"""
Stitch Wrapped Descriptions Repair Module
Re-attaches short trailing tokens (like "Cake") to the previous item for UNI_Mousse.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Pattern to match letters/CJK (words, not price/qty lines)
# B) Tail pattern for stray tails like "Cake" that were split by price columns
TAIL_RX = re.compile(r'^(?:Cake|蛋糕|瑞士卷|千层|千層)\s*$', re.I)


def is_stray_tail(it: dict) -> bool:
    """
    Check if an item is a stray tail line (short word continuation like "Cake").
    
    Args:
        it: Item dictionary to check
        
    Returns:
        True if item looks like a stray tail
    """
    name = (it.get("display_name") or it.get("canonical_name") or it.get("product_name") or "").strip()
    
    if not name:
        return False
    
    # Use TAIL_RX pattern to match common tail words
    return bool(TAIL_RX.match(name))


def merge_tail(prev: dict, tail: dict) -> None:
    """
    Merge tail item fields into previous item.
    
    Args:
        prev: Previous item dictionary (will be modified)
        tail: Tail item dictionary
    """
    for fld in ("display_name", "canonical_name", "product_name"):
        base = prev.get(fld, "")
        add = tail.get(fld) or tail.get("product_name") or "Cake"
        if base and add:
            prev[fld] = f"{base} {add}".strip()
    
    # Also merge raw_line if present
    if tail.get("raw_line") and prev.get("raw_line"):
        prev["raw_line"] = f"{prev['raw_line']}\n{tail['raw_line']}"


def stitch_wrapped_descriptions(items: list, vendor: str) -> list:
    """
    Stitch wrapped descriptions by re-attaching stray tail lines to previous items.
    Only applies to UNI_Mousse vendor.
    
    Args:
        items: List of item dictionaries
        vendor: Vendor name
        
    Returns:
        List of items with tails merged
    """
    if vendor != "UNI_Mousse" and "MOUSSE" not in vendor.upper():
        return items
    
    out = []
    for it in items:
        if is_stray_tail(it) and out:
            merge_tail(out[-1], it)
            logger.debug(f"Stitched tail '{it.get('product_name', '')}' to previous item")
            continue  # drop the tail item
        out.append(it)
    
    return out

