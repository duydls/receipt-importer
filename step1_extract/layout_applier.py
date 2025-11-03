#!/usr/bin/env python3
"""
Layout Applier - Apply layout rules from step1_rules/20_*.yaml files
Applies vendor-specific Excel/PDF layout configurations to extract data.
Supports multiple layouts per vendor with applies_to conditions.
"""

import re
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

META_PATTERNS = (
    "total items sold", "items sold",
    "total (grand total)", "grand total",
    "tax", "sales tax", "checkout bag fee",
)

SUMMARY_PAT = re.compile(r"\b(total( items sold)?|subtotal|grand total|balance|tax|fee|tip|service fee|discount)\b", re.I)

CONTROL_PATTERNS = re.compile(r'\b(subtotal|tax|total|items\s*sold)\b', re.I)

FOOTER_KEYS = (
    "tax (fee)", "total (grand total)", "total items sold",
    "tax", "total", "items sold",
)

def _is_meta_name(name: str) -> bool:
    n = (name or "").strip().lower()
    return any(p in n for p in META_PATTERNS)

def is_summary_or_fee(name: str) -> bool:
    return bool(SUMMARY_PAT.search((name or "").strip()))

def _is_product_row(name: str, qty, unit_price, total, item_number: str, upc: str) -> bool:
    """Decide if a row is a product row (not meta). Keep amount-only rows to be enriched later."""
    if not name or _is_meta_name(name):
        return False
    # If we have a valid total amount, treat as a product line (to be enriched)
    if total not in (None, '', 0, '0', 0.0):
        return True
    # Other strong product signals
    try:
        if qty is not None and str(qty) != '' and float(qty) > 0:
            return True
    except Exception:
        pass
    if item_number or upc:
        return True
    return False


class LayoutApplier:
    """Apply layout rules from step1_rules for vendor-specific layouts"""
    
    def __init__(self, rule_loader):
        """
        Initialize layout applier
        
        Args:
            rule_loader: RuleLoader instance
        """
        self.rule_loader = rule_loader
        # Remember the last matched layout name for diagnostics
        self.last_matched_layout: Optional[str] = None
        self.last_product_count: int = 0
        
    # ---------------- helpers: header & number normalization ----------------
    @staticmethod
    def _norm_header_text(headers: List[str]) -> List[str]:
        out: List[str] = []
        for h in headers or []:
            s = str(h).replace("\ufeff", "").replace("\u00A0", " ").strip().strip('"').strip("'")
            s = " ".join(s.split()).lower()
            out.append(s)
        return out

    @staticmethod
    def _canon(s: str) -> str:
        import re
        s = s.lower()
        s = re.sub(r"\(.*?\)", "", s)
        s = s.replace("\u00A0", " ")
        s = re.sub(r"[^\w\s]", " ", s)
        s = " ".join(s.split())
        return s

    @staticmethod
    def _clean_number(x):
        import pandas as pd, re
        if x is None:
            return None
        if isinstance(x, (int, float)) and pd.notna(x):
            return float(x)
        s = str(x).strip()
        if not s or s.lower() in ("nan", "none"):
            return None
        s = s.replace("$", "").replace(",", "").replace("\u00A0", " ").strip()
        if re.fullmatch(r"\(.*\)", s):
            s = "-" + s[1:-1]
        try:
            return float(s)
        except:
            return None
    
    def apply_layout_to_excel(self, df: pd.DataFrame, vendor_code: str, receipt_data: Dict[str, Any], file_path: Optional[Path] = None, receipt_text: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Apply layout rules to Excel DataFrame and extract items.
        Iterates through multiple layouts and picks the first matching one.
        
        Args:
            df: Pandas DataFrame from Excel file
            vendor_code: Vendor code (e.g., 'COSTCO', 'RD', 'JEWEL')
            receipt_data: Receipt data dictionary (will be updated)
            file_path: Path to the Excel file (for file extension matching)
            receipt_text: Receipt text content (for text_contains matching)
            
        Returns:
            List of extracted items, or empty list if no layout matches
        """
        layout_rules = self.rule_loader.get_layout_rules(vendor_code)
        if not layout_rules:
            logger.warning(f"No layout rules found for vendor: {vendor_code}")
            return []
        
        # Get layouts array from structure (list directly or nested in dict)
        layouts = None
        
        if isinstance(layout_rules, list):
            # Already a list (new structure)
            layouts = layout_rules
        elif isinstance(layout_rules, dict):
            # Check for new structure with 'layouts' key
            if 'layouts' in layout_rules and isinstance(layout_rules['layouts'], list):
                layouts = layout_rules['layouts']
            # Check for old format with 'excel_formats'
            elif 'excel_formats' in layout_rules:
                logger.debug(f"Old format structure found for vendor {vendor_code}, trying excel_formats")
                return self._try_old_format_structure(df, layout_rules, receipt_data)
            else:
                # Try to find layouts list directly in dict values
                for key, value in layout_rules.items():
                    if isinstance(value, list) and len(value) > 0:
                        if isinstance(value[0], dict) and ('applies_to' in value[0] or 'name' in value[0]):
                            layouts = value
                            break
        
        if not layouts or not isinstance(layouts, list) or len(layouts) == 0:
            logger.debug(f"No layouts list found for vendor {vendor_code}")
            return []
        
        # Get file info for matching
        file_extension = None
        if file_path:
            file_extension = file_path.suffix.lower()
        
        # Reset last matched layout for each apply call
        self.last_matched_layout = None
        self.last_product_count = 0
        # Get header text from DataFrame columns
        raw_header_text = [str(col).strip() for col in df.columns]
        header_text = raw_header_text[:]
        norm_header_text = self._norm_header_text(raw_header_text)
        
        # Iterate through layouts and find first match
        logger.info(f"Trying {len(layouts)} layouts for vendor {vendor_code} with headers {raw_header_text}")
        for layout in layouts:
            layout_name = layout.get('name', 'unnamed')
            logger.info(f"Checking layout '{layout_name}'")
            if self._layout_applies_to(layout, vendor_code, file_extension, norm_header_text, receipt_text):
                logger.info(f"✓ Matched layout '{layout_name}' for vendor {vendor_code}")
                # Pass receipt_data as ctx to _extract_items_from_layout so control lines can be written
                items = self._extract_items_from_layout(df, layout, vendor_code, ctx=receipt_data)
                
                if items:
                    # Remember matched layout
                    self.last_matched_layout = layout.get('name')
                    # Update receipt metadata
                    self._update_receipt_metadata(df, layout, receipt_data)
                    # Add parsed_by from layout (use parsed_by from YAML if present, otherwise generate)
                    parsed_by = layout.get('parsed_by')
                    if parsed_by:
                        receipt_data['parsed_by'] = parsed_by
                    else:
                        # Fallback: generate from layout name
                        receipt_data['parsed_by'] = f"layout_{layout.get('name', 'unnamed').lower().replace(' ', '_')}"
                    for item in items:
                        item['parsed_by'] = receipt_data['parsed_by']
                    self.last_product_count = len(items)
                    # Also stash items into receipt_data for callers that read from it
                    try:
                        receipt_data['items'] = list(items)
                    except Exception:
                        receipt_data['items'] = items
                    logger.info(f"Successfully extracted {len(items)} items using layout '{layout.get('name', 'unnamed')}'")
                    return items
                else:
                    logger.warning(f"Layout '{layout.get('name', 'unnamed')}' matched but extracted 0 items (df has {len(df)} rows)")
        
        # No layout matched
        logger.debug(f"No matching layout found for vendor {vendor_code}")
        return []
    
    def get_matching_layout(self, vendor_code: str, file_path: Optional[Path] = None, receipt_text: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get matching layout for PDF/text parsing (doesn't extract items, just returns layout config)
        
        Args:
            vendor_code: Vendor code (e.g., 'COSTCO', 'RD', 'JEWEL')
            file_path: Path to the file (for file extension matching)
            receipt_text: Receipt text content (for text_contains matching)
            
        Returns:
            Matching layout dictionary, or None if no layout matches
        """
        layout_rules = self.rule_loader.get_layout_rules(vendor_code)
        if not layout_rules:
            logger.debug(f"No layout rules found for vendor: {vendor_code}")
            return None
        
        # Get layouts array from structure
        layouts = None
        
        if isinstance(layout_rules, list):
            layouts = layout_rules
        elif isinstance(layout_rules, dict):
            if 'layouts' in layout_rules and isinstance(layout_rules['layouts'], list):
                layouts = layout_rules['layouts']
            else:
                for key, value in layout_rules.items():
                    if isinstance(value, list) and len(value) > 0:
                        if isinstance(value[0], dict) and ('applies_to' in value[0] or 'name' in value[0]):
                            layouts = value
                            break
        
        if not layouts or not isinstance(layouts, list) or len(layouts) == 0:
            logger.debug(f"No layouts list found for vendor {vendor_code}")
            return None
        
        # Get file info for matching
        file_extension = None
        if file_path:
            file_extension = file_path.suffix.lower()
        
        # Iterate through layouts and find first match
        for layout in layouts:
            if self._layout_applies_to(layout, vendor_code, file_extension, None, receipt_text):
                logger.debug(f"Matched layout '{layout.get('name', 'unnamed')}' for vendor {vendor_code}")
                return layout
        
        # No layout matched
        logger.debug(f"No matching layout found for vendor {vendor_code}")
        return None
    
    def _layout_applies_to(self, layout: Dict[str, Any], vendor_code: str, file_extension: Optional[str] = None, header_text: List[str] = None, receipt_text: Optional[str] = None) -> bool:
        """
        Check if a layout applies based on applies_to conditions
        
        Args:
            layout: Layout configuration dictionary
            vendor_code: Vendor code to match
            file_extension: File extension (e.g., '.xlsx')
            header_text: List of column header text
            receipt_text: Receipt text content
            
        Returns:
            True if layout applies, False otherwise
        """
        applies_to = layout.get('applies_to', {})
        if not applies_to:
            return False
        
        # Check vendor_code
        layout_vendor_codes = applies_to.get('vendor_code', [])
        if isinstance(layout_vendor_codes, str):
            layout_vendor_codes = [layout_vendor_codes]
        
        if layout_vendor_codes:
            vendor_code_upper = vendor_code.upper() if vendor_code else ''
            if not any(vc.upper() == vendor_code_upper for vc in layout_vendor_codes):
                logger.debug(f"Layout '{layout.get('name','unnamed')}' rejected: vendor_code mismatch (want {layout_vendor_codes}, have {vendor_code_upper})")
                return False
        
        # Check file_ext
        if file_extension:
            allowed_extensions = applies_to.get('file_ext', [])
            if isinstance(allowed_extensions, str):
                allowed_extensions = [allowed_extensions]
            
            if allowed_extensions and file_extension not in allowed_extensions:
                logger.debug(f"Layout '{layout.get('name','unnamed')}' rejected: file_ext mismatch (want {allowed_extensions}, have {file_extension})")
                return False
        
        # Check header_contains (normalized)
        if header_text:
            required_headers = applies_to.get('header_contains', [])
            if isinstance(required_headers, str):
                required_headers = [required_headers]
            
            if required_headers:
                header_text_lower = [str(h).lower().strip() for h in header_text]
                header_text_canon = [self._canon(h) for h in header_text_lower]
                logger.info(f"Checking header_contains for layout '{layout.get('name','unnamed')}': required={required_headers}, actual(norm)={header_text_lower}")
                for req_header in required_headers:
                    req_header_lower = str(req_header).lower().strip()
                    req_header_canon = self._canon(req_header_lower)
                    # Try exact match first
                    if req_header_lower in header_text_lower:
                        logger.info(f"  ✓ '{req_header}' matched exactly")
                        continue
                    # Try contains match (check if required header is contained in any actual header)
                    matched = False
                    for header in header_text_lower:
                        # Try contains match (most permissive)
                        if req_header_lower in header:
                            matched = True
                            logger.info(f"  ✓ '{req_header}' found in '{header}' (contains match)")
                            break
                        # Also try reverse: check if header is contained in required (for partial matches)
                        if header in req_header_lower:
                            matched = True
                            logger.info(f"  ✓ '{req_header}' contains '{header}' (reverse match)")
                            break
                    if matched:
                        continue
                    # Canonical fuzzy match
                    if req_header_canon and req_header_canon in header_text_canon:
                        logger.info(f"  ✓ '{req_header}' matched canonically")
                        continue
                    if not matched:
                        # Try regex as last resort
                        for header in header_text_lower:
                            try:
                                if re.search(req_header, header, re.IGNORECASE):
                                    matched = True
                                    logger.info(f"  ✓ '{req_header}' matched via regex in '{header}'")
                                    break
                            except:
                                pass
                    if not matched:
                        logger.warning(f"  ✗ Layout '{layout.get('name','unnamed')}' rejected: '{req_header}' NOT found. headers(norm)={header_text_lower} headers(canon)={header_text_canon}")
                        return False
        
        # Check text_contains (in receipt text content)
        if receipt_text:
            required_text = applies_to.get('text_contains', [])
            if isinstance(required_text, str):
                required_text = [required_text]
            
            if required_text:
                receipt_text_lower = receipt_text.lower()
                for req_text in required_text:
                    if req_text.lower() not in receipt_text_lower:
                        # Try regex match
                        if not re.search(req_text, receipt_text, re.IGNORECASE):
                            logger.debug(f"Layout '{layout.get('name','unnamed')}' rejected: text_contains missing '{req_text}'")
                            return False
        
        return True
    
    def _extract_items_from_layout(self, df: pd.DataFrame, layout: Dict[str, Any], vendor_code: str, ctx: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Extract items from DataFrame using layout configuration
        
        Args:
            df: DataFrame to extract from
            layout: Layout configuration
            vendor_code: Vendor code
            ctx: Optional context dict to write control line values (tax, total, items_sold)
        """
        items = []
        column_mappings = layout.get('column_mappings', {})
        
        # Get normalization and skip patterns
        normalization = layout.get('normalization', {})
        skip_patterns = layout.get('skip_patterns', [])
        
        # Store original column names for matching (don't modify df.columns)
        original_columns = list(df.columns)
        # Map string names to string names (for compatibility with pandas row access)
        original_columns_map = {str(col).strip(): str(col).strip() for col in df.columns}
        
        # Clean column names (remove special chars, strip whitespace) for matching
        cleaned_columns_map = {}
        for col in df.columns:
            cleaned = re.sub(r'[^\w\s]', '', str(col)).strip().lower()
            col_str = str(col).strip()
            cleaned_columns_map[cleaned] = col_str
        
        for idx, row in df.iterrows():
            # Build item from row
            item = {}
            
            # Check skip patterns (only check product_name column to avoid false positives in optional columns)
            skip_row = False
            product_name_col = None
            # Find product_name column first (match against original column names)
            product_name_mapping = column_mappings.get('product_name')
            if product_name_mapping:
                # Try exact match first on original columns
                product_name_str = str(product_name_mapping).strip()
                if product_name_str in original_columns_map:
                    product_name_col = original_columns_map[product_name_str]
                else:
                    # Try case-insensitive match
                    for orig_col_str, orig_col in original_columns_map.items():
                        if orig_col_str.lower() == product_name_str.lower():
                            product_name_col = orig_col
                            break
                
                # If not found, try cleaned match
                if not product_name_col:
                    product_name_clean = re.sub(r'[^\w\s]', '', product_name_str).strip().lower()
                    if product_name_clean in cleaned_columns_map:
                        product_name_col = cleaned_columns_map[product_name_clean]
            
            # Only check skip patterns against product_name column (and optionally Item Description/Item Name if different)
            if product_name_col:
                cell_value = str(row.get(product_name_col, '')).strip() if pd.notna(row.get(product_name_col)) else ''
                for pattern in skip_patterns:
                    if not pattern or not pattern.strip():
                        continue
                    if pattern.lower() in cell_value.lower():
                        skip_row = True
                        break
            
            if skip_row:
                continue
            
            # Map columns to item fields
            for field_name, column_name in column_mappings.items():
                if not column_name:  # Skip null mappings
                    continue
                
                # Find matching column (match against original column names)
                matched_col = None
                column_name_str = str(column_name).strip()
                
                # Try exact match first on original columns
                if column_name_str in original_columns_map:
                    matched_col = original_columns_map[column_name_str]
                else:
                    # Try case-insensitive match
                    for orig_col_str, orig_col in original_columns_map.items():
                        if orig_col_str.lower() == column_name_str.lower():
                            matched_col = orig_col
                            break
                
                # If not found, try regex match on original columns
                if not matched_col and ('\\' in column_name_str or '(' in column_name_str or column_name_str.startswith('^') or column_name_str.endswith('$')):
                    try:
                        for orig_col_str, orig_col in original_columns_map.items():
                            if re.search(column_name_str, orig_col_str, re.IGNORECASE):
                                matched_col = orig_col
                                break
                    except:
                        pass
                
                # If still not found, try cleaned match
                if not matched_col:
                    column_name_clean = re.sub(r'[^\w\s]', '', column_name_str).strip().lower()
                    if column_name_clean in cleaned_columns_map:
                        matched_col = cleaned_columns_map[column_name_clean]
                
                if matched_col:
                    try:
                        value = row.get(matched_col)
                        if pd.isna(value):
                            value = None
                    except (KeyError, AttributeError, TypeError):
                        # Fallback: try direct access
                        try:
                            value = row[matched_col]
                            if pd.isna(value):
                                value = None
                        except (KeyError, IndexError, TypeError):
                            logger.debug(f"Could not access column '{matched_col}' from row {idx}")
                            value = None
                    
                    # Normalize value
                    if value is not None and pd.notna(value):
                        value_str = str(value).strip()
                        
                        # Clean citations if enabled
                        if normalization.get('clean_citations', False):
                            value_str = re.sub(r'\[cite[^\]]*\]', '', value_str).strip()
                        
                        # Trim whitespace
                        if normalization.get('trim_whitespace', True):
                            value_str = value_str.strip()
                        
                        # Skip if empty or 'nan'
                        if value_str and value_str.lower() not in ['nan', 'none', '']:
                            item[field_name] = value_str
                else:
                    # Log missing column only for required fields
                    if field_name in ['product_name', 'total_price']:
                        logger.debug(f"Row {idx}: Could not find column '{column_name_str}' for field '{field_name}'")
            
            # Skip empty items
            if not item or not item.get('product_name'):
                logger.info(f"Skipping row {idx}: no product_name extracted (item keys: {list(item.keys())})")
                continue
            
            # ---- Numeric cleaning & derivation (robust) ----
            qty_raw  = item.get('quantity')
            up_raw   = item.get('unit_price')
            tp_raw   = item.get('total_price')

            qty = self._clean_number(qty_raw)
            up  = self._clean_number(up_raw)
            tp  = self._clean_number(tp_raw)

            if qty is None and up is not None and tp is not None and up != 0:
                qty = round(tp / up, 3)
            if up is None and qty not in (None, 0) and tp is not None:
                up = round(tp / qty, 4)
            if tp is None and qty not in (None, 0) and up not in (None, 0):
                tp = round(qty * up, 2)

            if qty is None or qty == 0:
                qty = 1.0
            if up is None:
                up = 0.0
            if tp is None:
                tp = round(qty * up, 2)

            item['quantity'] = float(qty)
            item['unit_price'] = float(up)
            item['total_price'] = float(tp)
            
            # Add parsed_by from layout
            parsed_by = layout.get('parsed_by')
            if parsed_by:
                item['parsed_by'] = parsed_by
            
            logger.info(f"Row {idx}: built item with fields: "
                        f"name='{item.get('product_name')}', qty={item.get('quantity')}, "
                        f"unit_price={item.get('unit_price')}, total={item.get('total_price')}")

            # Check if this is a control line (tax, total, items sold)
            name = (item.get('product_name') or '').strip()
            if CONTROL_PATTERNS.search(name):
                # Write control values into ctx if provided
                if ctx is not None:
                    lname = name.lower()
                    # Items sold/count - check this FIRST before "total" (since "Total Items" could match both)
                    if 'items' in lname and ('sold' in lname or lname.startswith('total items')):
                        try:
                            ctx['items_sold'] = float(item.get('total_price') or 0.0)
                            logger.debug(f"Row {idx}: extracted items_sold={ctx.get('items_sold')} from control line '{name}'")
                        except Exception:
                            pass
                    # Subtotal (before tax)
                    elif lname.startswith('subtotal'):
                        try:
                            ctx['subtotal'] = float(item.get('total_price') or 0.0)
                            logger.debug(f"Row {idx}: extracted subtotal={ctx.get('subtotal')} from control line")
                        except Exception:
                            pass
                    # Grand total (includes tax)
                    elif 'total' in lname and 'grand' in lname:
                        try:
                            ctx['grand_total'] = float(item.get('total_price') or 0.0)
                            logger.debug(f"Row {idx}: extracted grand_total={ctx.get('grand_total')} from control line '{name}'")
                        except Exception:
                            pass
                    # Transaction total / generic total (RD uses "TRANSACTION TOTAL")
                    elif lname.startswith('total') or 'transaction' in lname:
                        try:
                            ctx['grand_total'] = float(item.get('total_price') or 0.0)
                            logger.debug(f"Row {idx}: extracted grand_total={ctx.get('grand_total')} from control line '{name}'")
                        except Exception:
                            pass
                    # Tax (can appear multiple times, so accumulate)
                    elif 'tax' in lname:
                        try:
                            ctx['tax_total'] = float(ctx.get('tax_total', 0.0)) + float(item.get('total_price') or 0.0)
                            logger.debug(f"Row {idx}: extracted tax_total={ctx.get('tax_total')} from control line '{name}'")
                        except Exception:
                            pass
                # Do not append control lines as items
                logger.debug(f"Row {idx}: skipping control line '{name}'")
                continue
            
            # Classify meta vs product rows
            name_for_class = item.get('product_name')
            qty_for_class = item.get('quantity')
            unit_price_for_class = item.get('unit_price')
            total_for_class = item.get('total_price')
            item_no_for_class = item.get('item_number') or ''
            upc_for_class = item.get('upc') or ''
            if not _is_product_row(name_for_class, qty_for_class, unit_price_for_class, total_for_class, item_no_for_class, upc_for_class):
                # Do not include meta rows in product items list (kept out to avoid false positives)
                logger.debug(f"Row {idx}: classified as meta '{item.get('product_name')}', not adding to product items")
            else:
                items.append(item)
        
        # Extract tax from Excel file (similar to legacy processor) - only if ctx not provided
        # If ctx was provided, control lines were already extracted above
        # Always initialize tax to 0.0, then try to extract from file
        # Even if tax is 0.00 in the file, we need to extract and show it
        tax_extracted = False
        if ctx is not None:
            ctx.setdefault('tax', 0.0)
        # Legacy code path for when ctx is not provided (backwards compatibility)
        # This block should be removed once all callers pass ctx
        
        # Look for tax in Item Number column (Costco-specific)
        # Also check Item Description column for "TAX", "B:Taxable" patterns
        if 'Item Number' in df.columns:
            for idx, row in df.iterrows():
                item_num = str(row.get('Item Number', '')).strip() if pd.notna(row.get('Item Number')) else ''
                item_num = re.sub(r'\[cite[^\]]*\]', '', item_num).strip().lower()
                
                # Check Item Description column for tax patterns (Aldi: "B:Taxable @2.250%")
                item_desc = str(row.get('Item Description', '')).strip() if pd.notna(row.get('Item Description')) else ''
                item_desc_clean = re.sub(r'\[cite[^\]]*\]', '', item_desc).strip().lower()
                
                # Check if Item Number or Item Description indicates tax
                if item_num in ['tax (fee)', 'tax'] or 'tax' in item_desc_clean or 'b:taxable' in item_desc_clean:
                    # Tax amount might be in Extended Amount column
                    amount_col = None
                    for col in df.columns:
                        if 'extended' in col.lower() or 'amount' in col.lower():
                            amount_col = col
                            break
                    
                    if amount_col:
                        amount = row.get(amount_col)
                        if pd.notna(amount):
                            try:
                                amount_str = str(amount).strip()
                                amount_str = re.sub(r'\[cite[^\]]*\]', '', amount_str).strip()
                                # Match tax amount (including 0.00)
                                tax_match = re.search(r'(\d+\.\d{2})', amount_str)
                                if tax_match:
                                    tax_value = float(tax_match.group(1))
                                    if ctx is not None:
                                        ctx['tax'] = tax_value
                                    tax_extracted = True
                                    logger.debug(f"Extracted tax from Item Number/Description column: ${tax_value:.2f}")
                                    break
                            except:
                                pass
                    
                    # Also check next row for tax amount (Costco format: tax on next row)
                    if not tax_extracted and idx + 1 < len(df):
                        next_row = df.iloc[idx + 1]
                        next_amount = next_row.get(amount_col) if amount_col else None
                        if pd.notna(next_amount):
                            try:
                                next_amount_str = str(next_amount).strip()
                                next_amount_str = re.sub(r'\[cite[^\]]*\]', '', next_amount_str).strip()
                                tax_match = re.search(r'(\d+\.\d{2})', next_amount_str)
                                if tax_match:
                                    tax_value = float(tax_match.group(1))
                                    if ctx is not None:
                                        ctx['tax'] = tax_value
                                    tax_extracted = True
                                    logger.debug(f"Extracted tax from next row after Item Number: ${tax_value:.2f}")
                                    break
                            except:
                                pass
        
        # Look for tax in trailing rows with empty Item Description (RD/Aldi format)
        if not tax_extracted:
            # Find product_name column
            product_name_col = None
            for col in df.columns:
                col_lower = str(col).lower()
                if 'description' in col_lower or 'item' in col_lower:
                    product_name_col = col
                    break
            
            if product_name_col:
                # Iterate backwards through rows to find trailing summary rows
                # Look for tax before total (tax is typically smaller and appears first)
                for idx in range(len(df) - 1, -1, -1):
                    row = df.iloc[idx]
                    item_desc = str(row.get(product_name_col, '')).strip() if pd.notna(row.get(product_name_col)) else ''
                    
                    # Empty Item Description indicates summary row
                    if not item_desc or item_desc.lower() in ['nan', 'none', '']:
                        # Skip legacy tax extraction if control lines already processed
                        if ctx is not None and (ctx.get('grand_total') or ctx.get('tax_total')):
                            continue
                        
                        # Check for amount column
                        amount_col = None
                        for col in df.columns:
                            if 'extended' in col.lower() or 'amount' in col.lower():
                                amount_col = col
                                break
                        
                        if amount_col:
                            amount = row.get(amount_col)
                            if pd.notna(amount):
                                try:
                                    amount_float = self._clean_number(amount)
                                    # Tax is typically small (< $100) and appears before total
                                    # But we need to distinguish between tax and other small amounts
                                    # Check if this looks like tax: small amount, not an integer count
                                    if 0 <= amount_float < 100 and amount_float != int(amount_float):
                                        # This could be tax - but we need to be more careful
                                        # Only set if we haven't found total yet (tax comes before total)
                                        if ctx is not None:
                                            total_val = ctx.get('total', ctx.get('grand_total'))
                                            if not total_val or amount_float < total_val:
                                                ctx['tax'] = amount_float
                                                tax_extracted = True
                                                logger.debug(f"Extracted tax from trailing row (empty {product_name_col}): ${amount_float:.2f}")
                                                break
                                except:
                                    pass
        
        # Always ensure tax is set (even if 0.00)
        # But don't overwrite tax_total from control lines
        if ctx is not None:
            if 'tax_total' not in ctx and 'tax' not in ctx:
                ctx['tax'] = 0.0
                if not tax_extracted:
                    logger.debug(f"No tax found in Excel file, setting tax=0.00")
        
        return items
    
    def _update_receipt_metadata(self, df: pd.DataFrame, layout: Dict[str, Any], receipt_data: Dict[str, Any]) -> None:
        """Update receipt metadata from DataFrame using layout configuration"""
        column_mappings = layout.get('column_mappings', {})
        
        # Extract receipt-level fields
        if 'store_name' in column_mappings:
            store_col = column_mappings['store_name']
            if store_col:
                store_col_clean = re.sub(r'[^\w\s]', '', str(store_col)).strip()
                for col in df.columns:
                    col_clean = re.sub(r'[^\w\s]', '', str(col)).strip()
                    if store_col_clean.lower() == col_clean.lower():
                        store_values = df[col].dropna().unique()
                        if len(store_values) > 0:
                            receipt_data['store_name'] = str(store_values[0]).strip()
                        break
        
        if 'transaction_date' in column_mappings:
            date_col = column_mappings['transaction_date']
            if date_col:
                date_col_clean = re.sub(r'[^\w\s]', '', str(date_col)).strip()
                for col in df.columns:
                    col_clean = re.sub(r'[^\w\s]', '', str(col)).strip()
                    if date_col_clean.lower() == col_clean.lower():
                        date_values = df[col].dropna().unique()
                        if len(date_values) > 0:
                            receipt_data['order_date'] = str(date_values[0]).strip()
    
    def _try_old_format_structure(self, df: pd.DataFrame, layout_rules: Dict[str, Any], receipt_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Fallback: Try to use old excel_formats structure for backward compatibility
        """
        excel_formats = layout_rules.get('excel_formats', {})
        if not excel_formats:
            return []
        
        # Detect format using old logic
        detected_format = self._detect_excel_format_old(df, excel_formats)
        if not detected_format:
            return []
        
        format_config = excel_formats[detected_format]
        logger.debug(f"Using old format structure: {detected_format}")
        
        # Extract items using old format structure
        items = self._extract_items_from_format_old(df, format_config, layout_rules)
        
        # Update receipt metadata
        self._update_receipt_metadata_old(df, format_config, receipt_data)
        
        return items
    
    def _detect_excel_format_old(self, df: pd.DataFrame, excel_formats: Dict[str, Any]) -> Optional[str]:
        """Detect which Excel format matches the DataFrame columns (old structure)"""
        df_columns_lower = [str(col).lower().strip() for col in df.columns]
        
        for format_name, format_config in excel_formats.items():
            identifier_columns = format_config.get('identifier_columns', [])
            required_columns = format_config.get('required_columns', identifier_columns)
            
            # Check if all required columns are present
            if all(col.lower().strip() in df_columns_lower for col in required_columns):
                return format_name
        
        return None
    
    def _extract_items_from_format_old(self, df: pd.DataFrame, format_config: Dict[str, Any], layout_rules: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract items from DataFrame using format configuration (old structure)"""
        items = []
        column_mappings = format_config.get('column_mappings', {})
        skip_patterns = layout_rules.get('skip_patterns', [])
        normalization = layout_rules.get('normalization', {})
        
        for idx, row in df.iterrows():
            item = {}
            
            # Check skip patterns
            skip_row = False
            for pattern in skip_patterns:
                for col in df.columns:
                    cell_value = str(row.get(col, '')).strip()
                    if pattern.lower() in cell_value.lower():
                        skip_row = True
                        break
                if skip_row:
                    break
            
            if skip_row:
                continue
            
            # Map columns to item fields
            for field_name, column_name in column_mappings.items():
                if column_name and column_name in df.columns:
                    value = row.get(column_name)
                    
                    if pd.notna(value):
                        value_str = str(value).strip()
                        
                        if normalization.get('clean_citations', False):
                            value_str = re.sub(r'\[cite[^\]]*\]', '', value_str).strip()
                        
                        if normalization.get('trim_whitespace', True):
                            value_str = value_str.strip()
                        
                        if value_str and value_str.lower() not in ['nan', 'none', '']:
                            item[field_name] = value_str
            
            if not item or not item.get('product_name'):
                continue
            
            # Ensure required fields have defaults
            if 'quantity' not in item:
                item['quantity'] = 1.0
            if 'unit_price' not in item:
                item['unit_price'] = 0.0
            if 'total_price' not in item:
                qty = float(item.get('quantity', 1.0))
                up = float(item.get('unit_price', 0.0))
                item['total_price'] = qty * up if qty and up else 0.0
            
            # Convert to float
            try:
                item['quantity'] = float(item.get('quantity', 1.0))
                item['unit_price'] = float(item.get('unit_price', 0.0))
                item['total_price'] = float(item.get('total_price', 0.0))
            except:
                pass
            
            items.append(item)
        
        return items
    
    def _update_receipt_metadata_old(self, df: pd.DataFrame, format_config: Dict[str, Any], receipt_data: Dict[str, Any]) -> None:
        """Update receipt metadata from DataFrame (old structure)"""
        column_mappings = format_config.get('column_mappings', {})
        
        if 'store_name' in column_mappings:
            store_col = column_mappings['store_name']
            if store_col and store_col in df.columns:
                store_values = df[store_col].dropna().unique()
                if len(store_values) > 0:
                    receipt_data['store_name'] = str(store_values[0]).strip()
        
        if 'transaction_date' in column_mappings:
            date_col = column_mappings['transaction_date']
            if date_col and date_col in df.columns:
                date_values = df[date_col].dropna().unique()
                if len(date_values) > 0:
                    receipt_data['order_date'] = str(date_values[0]).strip()
