#!/usr/bin/env python3
import re
from typing import List, Dict

from preprocess.normalize import fold_ws

PRICE_TOK = re.compile(r"\$\s*\d")
HEADER_OR_DATE = re.compile(r"(?:Qty\s+Item|Invoice|Payment|^\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)
TAIL_WORD = re.compile(r"^(?:Cake|蛋糕|千层|千層|瑞士卷)\s*$", re.IGNORECASE)


def clean_description(desc: str) -> str:
    if not desc:
        return ""
    if HEADER_OR_DATE.search(desc):
        return ""
    if PRICE_TOK.search(desc):
        desc = desc.split("$", 1)[0]
    desc = fold_ws(desc)
    return re.sub(r"\s*[-–—]\s*$", "", desc)


def stitch_tail_items(items: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for it in items:
        raw_name = it.get("Description") or it.get("display_name") or it.get("product_name") or ""
        desc = clean_description(raw_name)
        if out and TAIL_WORD.fullmatch(desc):
            prev = out[-1]
            prev["display_name"] = fold_ws(f"{prev.get('display_name') or ''} {desc}")
            continue
        it["display_name"] = desc or (it.get("display_name") or it.get("product_name") or "")
        out.append(it)
    return out
