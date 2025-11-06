#!/usr/bin/env python3
"""
Text Normalization Module
Preprocesses product names by removing CJK characters and normalizing text.
"""

import re
import unicodedata

# CJK ranges + CJK punctuation + fullwidth forms
# \u3400-\u4DBF: CJK Extension A
# \u4E00-\u9FFF: CJK Unified Ideographs
# \uF900-\uFAFF: CJK Compatibility Ideographs
# \u3000-\u303F: CJK Symbols and Punctuation
# \uFF00-\uFFEF: Halfwidth and Fullwidth Forms
_CJK_RE = re.compile(r'[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3000-\u303F\uFF00-\uFFEF]')


def fold_ws(text: str) -> str:
    """
    Fold whitespace (newlines/tabs/multiple spaces into single space).
    Keep CJK characters. Normalize to NFKC.
    
    Args:
        text: Text to normalize
        
    Returns:
        Text with whitespace collapsed, CJK preserved
    """
    t = unicodedata.normalize('NFKC', text or "")
    t = t.replace('–', '-').replace('—', '-').replace('×', 'x')
    return re.sub(r'\s+', ' ', t).strip()


def normalize_item_name(item: dict) -> None:
    """
    Normalize item name by applying alias and folding whitespace.
    Sets canonical_name and raw_name_original.
    
    Args:
        item: Item dictionary to normalize
    """
    raw = (item.get("display_name") or item.get("product_name") or "").strip()
    
    # Apply alias
    try:
        from step1_extract.alias_loader import apply_aliases
        raw = apply_aliases(raw, keep_cjk=True)
    except ImportError:
        # Fallback if alias_loader location is different
        try:
            from kb.aliase.alias_loader import apply_aliases
            raw = apply_aliases(raw, keep_cjk=True)
        except ImportError:
            pass
    
    # Fold whitespace (keep CJK)
    item["canonical_name"] = fold_ws(raw)
    item["raw_name_original"] = raw


def strip_cjk(text: str) -> str:
    """
    Strip Chinese/Japanese/Korean characters and punctuation from text.
    Preserves all English/ASCII text and numbers.
    
    Args:
        text: Text to process
        
    Returns:
        Text with CJK characters removed, normalized to NFKC, and whitespace cleaned
    """
    if not text:
        return text
    
    # Remove CJK characters
    s = _CJK_RE.sub('', text)
    
    # Normalize to NFKC (fullwidth -> halfwidth)
    s = unicodedata.normalize('NFKC', s)
    
    # Replace special characters
    s = s.replace('×', 'x').replace('–', '-').replace('—', '-')
    
    # Normalize whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    
    return s

