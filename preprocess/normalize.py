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

