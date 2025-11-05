#!/usr/bin/env python3
"""
Excel Processor - BBI-based receipts only
Processes Excel files using rule-driven layout application.

Note: Excel files are no longer processed for localgrocery vendors (RD, Costco, Aldi, Jewel, Mariano's, Parktoshop).
These vendors now use PDF files only. Only BBI-based receipts use Excel files.

Rule-Driven Processing Flow:
1. Vendor detection (handled by main.py via VendorDetector)
2. Layout application (tries layout rules first: 27_bbi_layout.yaml)
3. Legacy processing (fallback if layout rules don't match)
4. UoM extraction (always applied: 30_uom_extraction.yaml)

See step1_rules/README.md for rule file documentation.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Optional
from collections import namedtuple

logger = logging.getLogger(__name__)

# Minimal compatibility shim for variable layout return shapes
LayoutInfo = namedtuple("LayoutInfo", "matched name product_rows meta_rows")

def _coerce_layout_result(res):
    """Normalize layout_applier.try_apply(...) into (matched, name, products, meta)."""
    if res is None:
        return LayoutInfo(False, None, [], [])
    if hasattr(res, "matched") and hasattr(res, "product_rows"):
        return LayoutInfo(bool(getattr(res, "matched")),
                          getattr(res, "name", "unnamed"),
                          list(getattr(res, "product_rows") or []),
                          list(getattr(res, "meta_rows") or []))
    if isinstance(res, dict):
        # accept multiple synonyms from layout_applier
        rows = (res.get("product_rows") or res.get("rows") or
                res.get("items") or res.get("products") or [])
        meta = (res.get("meta_rows") or res.get("meta") or
                res.get("footer_rows") or [])
        matched = res.get("matched")
        if matched is None:
            matched = res.get("ok") or res.get("success") or bool(rows)
        return LayoutInfo(bool(matched),
                          res.get("name") or "unnamed",
                          list(rows),
                          list(meta))
    if isinstance(res, (list, tuple)):
        if len(res) >= 3 and isinstance(res[0], (bool, int)):
            matched = bool(res[0]); products = res[1] or []; meta = res[2] or []
            name = (len(res) >= 4 and res[3]) or "unnamed"
            return LayoutInfo(matched, name, list(products), list(meta))
        if len(res) >= 2:
            products = res[0] or []; meta = res[1] or []
            return LayoutInfo(True, "unnamed", list(products), list(meta))
    return LayoutInfo(False, None, [], [])


class ExcelProcessor:
    """Process Excel files for vendor-based receipts using rule-driven layouts"""
    
    def __init__(self, rule_loader, input_dir=None):
        """
        Initialize Excel processor
        
        Args:
            rule_loader: RuleLoader instance
            input_dir: Input directory path (for knowledge base location)
        """
        self.rule_loader = rule_loader
        # Note: group1_excel.yaml removed - Excel files no longer supported for localgrocery vendors
        # BBI uses its own layout (27_bbi_layout.yaml) loaded via layout_applier
        self.group_rules = {}  # No longer loading group1 rules
        self.input_dir = Path(input_dir) if input_dir else None
        
        # Prepare config with knowledge base file path (from input folder)
        config = {}
        if self.input_dir:
            kb_file = self.input_dir / 'knowledge_base.json'
            if kb_file.exists():
                config['knowledge_base_file'] = str(kb_file)
        
        # Import existing ReceiptProcessor for Excel processing
        # (This preserves all existing Excel logic exactly)
        from .receipt_processor import ReceiptProcessor
        self._legacy_processor = ReceiptProcessor(config=config)
        
        # Feature 4: Create layout applier once for caching
        from .layout_applier import LayoutApplier
        self.layout_applier = LayoutApplier(rule_loader)

        # Debug controls via env vars
        self._debug = os.getenv("RECEIPTS_DEBUG", "0") == "1"
        self._force_vendor = os.getenv("FORCE_VENDOR")
        self._force_layout = os.getenv("FORCE_LAYOUT")

    # -------------------- helpers: header detection & normalization --------------------
    @staticmethod
    def _normalize_header_cell(s: object) -> str:
        if s is None:
            return ""
        t = str(s)
        t = t.replace("\ufeff", "")  # BOM
        t = t.replace("\u00A0", " ")  # NBSP
        t = t.strip().strip('"').strip("'")
        t = " ".join(t.split())
        return t

    @staticmethod
    def _clean_number(x):
        """Parse $1,234.56 or (12.34) -> -12.34. Return float or None."""
        try:
            import pandas as pd  # type: ignore
        except Exception:
            pd = None  # type: ignore
        if x is None:
            return None
        if isinstance(x, (int, float)):
            try:
                if pd is not None and pd.isna(x):
                    return None
            except Exception:
                pass
            return float(x)
        s = str(x).strip().replace("$", "").replace(",", "").replace("\u00A0", " ")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        try:
            return float(s)
        except Exception:
            return None

    @staticmethod
    def _vendor_header_fingerprint(vendor_code: Optional[str]) -> list:
        # Vendor-specific fingerprints removed - Excel files no longer supported for localgrocery vendors
        # BBI uses its own layout rules (27_bbi_layout.yaml)
        return []

    def _detect_header_row(self, df, vendor_code: Optional[str], max_scan: int = 30) -> int:
        target = set(self._vendor_header_fingerprint(vendor_code))
        best_row, best_score = -1, -1
        rows = min(max_scan, len(df))
        for r in range(rows):
            raw = list(df.iloc[r].values)
            norm = [self._normalize_header_cell(x) for x in raw]
            score = sum(1 for h in norm if h in target) if target else sum(1 for h in norm if h)
            if score > best_score:
                best_row, best_score = r, score
        return best_row

    def _reheader_dataframe(self, df, header_row: int):
        import pandas as pd
        header = [self._normalize_header_cell(x) for x in df.iloc[header_row].values]
        body = df.iloc[header_row + 1:].copy()
        body.columns = header
        keep = [c for c in body.columns if c]
        body = body[keep]
        body = body.reset_index(drop=True)
        return body

    def _compose_receipt_text(self, df) -> str:
        parts = []
        parts.append(",".join(map(str, df.columns)))
        sample = df.head(5).astype(str).apply(lambda r: " | ".join(r.values), axis=1).tolist()
        parts.extend(sample)
        return "\n".join(parts)
    
    def detect_vendor(self, file_path: Path) -> Optional[str]:
        """
        Detect vendor from file path or name (internal helper)
        
        Note: Main vendor detection is handled by VendorDetector in main.py.
        This method is used internally for vendor-to-vendor-code mapping.
        
        Args:
            file_path: Path to file
            
        Returns:
            Vendor name or None
        """
        filename_lower = file_path.name.lower()
        path_lower = str(file_path).lower()
        
        # Vendor detection now handled by VendorDetector in main.py
        # This method is kept for backward compatibility but no longer uses group1_excel.yaml
        # BBI detection is handled via vendor detection rules
        return None
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Dict:
        """
        Process an Excel file using layout rules if available, fallback to legacy processor
        
        Note: Excel files are no longer processed for localgrocery vendors (RD, Costco, Aldi, Jewel, Parktoshop).
        Only BBI-based receipts use Excel files now.
        
        Args:
            file_path: Path to Excel file
            detected_vendor_code: Optional vendor code from vendor detection (if already detected)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        try:
            import pandas as pd
            
            # Localgrocery vendors no longer use Excel files (PDF only)
            localgrocery_vendors = ['COSTCO', 'RD', 'RESTAURANT_DEPOT', 'JEWEL', 'JEWELOSCO', 'ALDI', 'PARKTOSHOP']
            
            # Use detected_vendor_code if provided, otherwise try to detect from filename
            if self._force_vendor:
                vendor_code = self._force_vendor.upper()
                vendor = vendor_code.title()
            elif detected_vendor_code:
                vendor_code = detected_vendor_code
                # Map vendor code to vendor name for legacy processor
                vendor = vendor_code.title() if vendor_code else None
            else:
                vendor = self.detect_vendor(file_path)
                # Map vendor name to vendor code
                vendor_code_map = {
                    'Costco': 'COSTCO',
                    'RD': 'RD',
                    'Restaurant Depot': 'RD',
                    'JewelOsco': 'JEWEL',
                    'Jewel Osco': 'JEWEL',
                    'Mariano': 'MARIANOS',
                }
                vendor_code = vendor_code_map.get(vendor, vendor.upper() if vendor else None)
            
            # Reject localgrocery vendors (Excel no longer supported)
            if vendor_code and vendor_code.upper() in localgrocery_vendors:
                logger.warning(f"Excel files no longer supported for {vendor_code}. Use PDF files instead. Skipping: {file_path.name}")
                return {
                    'filename': file_path.name,
                    'vendor': vendor_code,
                    'items': [],
                    'needs_review': True,
                    'review_reasons': [f'Excel files no longer supported for {vendor_code}. Please use PDF files.'],
                    'parsed_by': 'rejected_excel_format'
                }
            
            if vendor_code:
                # Try layout rules first
                try:
                    # Block xlrd import to avoid Python 2 syntax errors
                    import sys
                    xlrd_backup = sys.modules.get('xlrd')
                    sys.modules['xlrd'] = None
                    
                    try:
                        # Support both Excel and CSV inputs (read raw without header for detection)
                        suffix = file_path.suffix.lower()
                        if suffix == '.csv':
                            df_raw = pd.read_csv(file_path, dtype=object, encoding='utf-8-sig', header=None)
                        else:
                            df_raw = pd.read_excel(file_path, engine='openpyxl', dtype=object, header=None)
                    finally:
                        # Restore xlrd if it was there
                        if xlrd_backup is not None:
                            sys.modules['xlrd'] = xlrd_backup
                        elif 'xlrd' in sys.modules:
                            del sys.modules['xlrd']
                    
                    # Detect and set header row
                    hdr_row = self._detect_header_row(df_raw, vendor_code)
                    if self._debug:
                        logger.debug(f"[debug] vendor_code={vendor_code} detected header row={hdr_row} shape={df_raw.shape}")
                    if hdr_row >= 0:
                        df = self._reheader_dataframe(df_raw, hdr_row)
                    else:
                        df = df_raw

                    # Try to apply layout rules
                    from .layout_applier import LayoutApplier
                    layout_applier = self.layout_applier  # Feature 4: Use instance for caching
                    
                    receipt_data = {
                        'filename': file_path.name.strip(),
                        'vendor': (vendor or '').strip(),
                        'items': [],
                        'total': 0.0,
                        'subtotal': 0.0,
                        'tax': 0.0,
                        'source_type': 'excel',
                    }
                    
                    # Apply layout rules (pass file_path for extension matching, receipt_text for content matching)
                    receipt_text = self._compose_receipt_text(df)
                    force_kwargs = {}
                    if self._force_layout:
                        force_kwargs['force_layout'] = self._force_layout
                    items = layout_applier.apply_layout_to_excel(df, vendor_code, receipt_data, file_path, receipt_text, **force_kwargs)
                    # Normalize iterables/generators to a concrete list to avoid len() TypeError
                    try:
                        items = list(items or [])
                    except TypeError:
                        # If items isn't iterable (None or unexpected), coerce to empty list
                        items = []
                    logger.info(f"[MODERN] raw item count from layout: {len(items)}")
                    try:
                        rd_items_any = list(receipt_data.get('items') or [])
                        rd_len = len(rd_items_any)
                    except Exception:
                        rd_items_any = []
                        rd_len = -1
                    logger.info(f"[MODERN] receipt_data items after layout: {rd_len}")
                    if rd_len > 0:
                        logger.info(f"[MODERN] Authoritative: {rd_len} item rows from layout '{getattr(layout_applier, 'last_matched_layout', None)}' for {file_path.name}")
                        items = rd_items_any
                    else:
                        try:
                            items = list(items or [])
                        except TypeError:
                            items = []

                    # Determine modern row count
                    modern_count = len(items)
                    try:
                        applier_count = int(getattr(layout_applier, 'last_product_count', 0) or 0)
                    except Exception:
                        applier_count = 0
                    if applier_count > modern_count:
                        modern_count = applier_count

                    # Modern path: if we have items, finalize and return immediately
                    if modern_count > 0:
                        logger.info(f"[MODERN] Returning {modern_count} item rows for {file_path.name}; layout={getattr(layout_applier,'last_matched_layout', None)}")
                        # Ensure items are properly coerced
                        receipt_data['items'] = items
                        # Get tax/total/subtotal from ctx if available
                        # ALWAYS prefer tax_total (from control lines) over tax (from legacy extraction)
                        if 'tax_total' in receipt_data:
                            receipt_data['tax'] = receipt_data['tax_total']
                        elif receipt_data.get('tax') is None or receipt_data.get('tax') == 0.0:
                            receipt_data['tax'] = 0.0
                        
                        # Tax-exempt vendors: Check against configured list
                        # If tax > $1.00, flag for review (may indicate parsing error)
                        tax_exempt_vendors = self.rule_loader.get_tax_exempt_vendors()
                        if vendor_code in tax_exempt_vendors:
                            tax_amount = receipt_data.get('tax', 0.0)
                            if tax_amount > 1.0:
                                if not receipt_data.get('needs_review'):
                                    receipt_data['needs_review'] = True
                                    receipt_data['review_reasons'] = []
                                receipt_data['review_reasons'].append(
                                    f"Tax-exempt vendor ({vendor_code}) has tax=${tax_amount:.2f} (expected ~$0.00)"
                                )
                                logger.warning(f"{file_path.name}: Tax-exempt vendor {vendor_code} has tax=${tax_amount:.2f}")
                        
                        # Subtotal: prefer control line value, otherwise calculate from items
                        if 'subtotal' not in receipt_data or receipt_data.get('subtotal') == 0.0:
                            receipt_data['subtotal'] = sum(float(it.get('total_price', 0) or 0) for it in items)
                        
                        # Set total: prefer grand_total from control lines, otherwise calculate
                        if receipt_data.get('grand_total'):
                            receipt_data['total'] = receipt_data['grand_total']
                        else:
                            receipt_data['total'] = receipt_data['subtotal'] + receipt_data.get('tax', 0.0)
                        if 'parsed_by' not in receipt_data:
                            receipt_data['parsed_by'] = getattr(layout_applier, 'last_matched_layout', 'modern_layout')
                        receipt_data['detected_vendor_code'] = vendor_code
                        receipt_data['needs_review'] = False
                        receipt_data['review_reasons'] = []
                        
                        # Apply UoM extraction (do not let failures force legacy)
                        try:
                            from .uom_extractor import UoMExtractor
                            uom_extractor = UoMExtractor(self.rule_loader)
                            receipt_data['items'] = uom_extractor.extract_uom_from_items(items)
                        except Exception as e:
                            logger.warning(f"UoM extraction failed for {file_path.name}: {e}; continuing with modern items")
                        
                        # Vendor-specific enrichment removed - Excel files no longer supported for localgrocery vendors
                        # BBI items are enriched via knowledge base in receipt_processor if needed
                        
                        logger.info(f"[MODERN] Processed {file_path.name} using layout '{receipt_data.get('parsed_by')}' for {vendor_code}")
                        return receipt_data
                    
                    # Modern reported false positive - fall back to legacy precisely once
                    matched_name = getattr(layout_applier, 'last_matched_layout', None)
                    reason = 'no layout matched' if not matched_name else 'zero product rows after filter'
                    logger.info(f"[LEGACY] Fallback. layout={matched_name} reason={reason} modern_count={modern_count} file={file_path.name}")
                except Exception as layout_error:
                    logger.warning(f"Error applying layout rules for {file_path.name}: {layout_error}, falling back to legacy processor", exc_info=True)
            
            # Check if legacy parsers are enabled (feature flag)
            legacy_enabled = True
            if self.rule_loader:
                legacy_enabled = self.rule_loader.get_legacy_enabled()
            
            if not legacy_enabled:
                logger.warning(f"[LEGACY] Legacy parsers disabled, but no modern layout matched for {file_path.name} (vendor={vendor_code})")
                return {
                    'filename': file_path.name,
                    'vendor': vendor or 'Unknown',
                    'items': [],
                    'total': 0.0,
                    'detected_vendor_code': vendor_code,
                    'parsed_by': 'none',
                    'needs_review': True,
                    'review_reasons': ['step1: no modern layout matched and legacy parsers disabled']
                }
            
            # Fall back to legacy processor (preserves all existing logic)
            logger.info(f"[LEGACY] Using legacy parser for: {file_path.relative_to(self.input_dir) if self.input_dir and self.input_dir in file_path.parents else file_path.name} (vendor={vendor_code}, reason=modern returned zero items)")
            receipt_data = self._legacy_processor.process_excel(str(file_path))
            
            # Preserve fields from vendor detection (merged by main.py after process_file returns)
            
            # Enhance with vendor info if vendor detected (but don't overwrite preserved fields)
            if vendor and not receipt_data.get('vendor'):
                receipt_data['vendor'] = vendor
                receipt_data['vendor_source'] = 'filename'
            elif vendor and receipt_data.get('vendor') == vendor:
                receipt_data['vendor_source'] = 'filename'
            
            # Add detected_vendor_code if we have it (but only if not already set)
            if vendor_code and 'detected_vendor_code' not in receipt_data:
                receipt_data['detected_vendor_code'] = vendor_code
            
            # Mark as needs_review and add parsed_by if we fell back to legacy processor
            receipt_data['parsed_by'] = receipt_data.get('parsed_by', 'legacy_excel_fallback')
            receipt_data['needs_review'] = True
            if 'review_reasons' not in receipt_data:
                receipt_data['review_reasons'] = []
            receipt_data['review_reasons'].append("step1: no modern layout matched, used legacy excel processor")
            
            # Add parsed_by to all items
            if receipt_data.get('items'):
                for item in receipt_data['items']:
                    item['parsed_by'] = receipt_data.get('parsed_by', 'legacy_excel_fallback')
            
            # Apply UoM extraction even for legacy processor
            if receipt_data.get('items'):
                from .uom_extractor import UoMExtractor
                uom_extractor = UoMExtractor(self.rule_loader)
                receipt_data['items'] = uom_extractor.extract_uom_from_items(receipt_data['items'])
            
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing Excel file {file_path.name}: {e}", exc_info=True)
            return {
                'filename': file_path.name,
                'vendor': self.detect_vendor(file_path) or 'Unknown',
                'items': [],
                'total': 0.0,
                'needs_review': True,
                'review_reasons': [f'Error processing: {str(e)}']
            }
    
    def process_pdf(self, file_path: Path) -> Dict:
        """
        Process a PDF file (for Group 1 vendors that might have PDFs)
        
        Args:
            file_path: Path to PDF file
            
        Returns:
            Dictionary containing extracted receipt data
        """
        # For Group 1, PDF processing can fall back to existing PDF processor
        # but this is less common - most Group 1 are Excel files
        try:
            receipt_data = self._legacy_processor.process_pdf(str(file_path))
            
            # Enhance with vendor rules
            vendor = self.detect_vendor(file_path)
            if vendor and not receipt_data.get('vendor'):
                receipt_data['vendor'] = vendor
            
            # Apply UoM extraction even for PDF processor
            if receipt_data.get('items'):
                from .uom_extractor import UoMExtractor
                uom_extractor = UoMExtractor(self.rule_loader)
                receipt_data['items'] = uom_extractor.extract_uom_from_items(receipt_data['items'])
            
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing PDF file {file_path.name}: {e}", exc_info=True)
            return {
                'filename': file_path.name,
                'vendor': self.detect_vendor(file_path) or 'Unknown',
                'items': [],
                'total': 0.0,
                'needs_review': True,
                'review_reasons': [f'Error processing: {str(e)}']
            }
    
    def _enrich_costco_items(self, items: list, items_sold_hint: int = None) -> list:
        """
        Enrich Costco items with unit_price and quantity from knowledge base.
        
        Costco receipts only show total_price per item (no unit_price or quantity breakdown).
        We use the knowledge base to get the standard unit_price, then calculate quantity.
        
        Args:
            items: List of item dictionaries
            items_sold_hint: Optional "Total Items Sold" from receipt for validation
        
        Returns:
            List of enriched items
        """
        from decimal import Decimal, ROUND_HALF_UP
        from . import vendor_profiles
        
        # Load knowledge base (uses singleton cache)
        kb = vendor_profiles._ensure_kb_loaded()
        
        if not kb:
            logger.warning("Knowledge base not loaded, skipping Costco enrichment")
            return items
        
        enriched_items = []
        total_qty = 0
        unresolved = []
        
        for item in items:
            item_number = str(item.get('item_number', '')).strip()
            total_price = float(item.get('total_price', 0) or 0)
            current_qty = float(item.get('quantity', 1) or 1)
            current_unit_price = item.get('unit_price')
            
            # Skip if already has valid unit_price and quantity
            if current_unit_price and current_unit_price > 0 and current_qty > 1:
                enriched_items.append(item)
                total_qty += int(current_qty)
                continue
            
            # Look up in knowledge base
            kb_entry = kb.get(item_number)
            if kb_entry and total_price > 0:
                kb_unit_price = float(kb_entry.get('price', 0) or 0)
                kb_spec = kb_entry.get('spec', '')  # Size/spec info (e.g., "3-lbs bag", "6 × 32-fl oz")
                kb_store = kb_entry.get('store', '')
                
                # Always add size/spec info if available
                if kb_spec:
                    item['kb_size'] = kb_spec
                    item['kb_source'] = 'knowledge_base'
                
                if kb_unit_price > 0:
                    # Calculate quantity using Decimal for precision
                    u = Decimal(str(kb_unit_price))
                    t = Decimal(str(total_price))
                    ratio = t / u
                    q = int(ratio.to_integral_value(rounding=ROUND_HALF_UP))
                    
                    # Allow small monetary errors (max 6 cents or 2% relative)
                    abs_eps = Decimal('0.06')
                    rel_eps = max(abs_eps, t * Decimal('0.02'))
                    
                    # Check if calculated quantity makes sense
                    candidates = [q, int(ratio), int(ratio) + 1] if q > 0 else [1]
                    best_qty = None
                    for cand in candidates:
                        if cand < 1:
                            continue
                        error = abs(t - (u * Decimal(cand)))
                        if error <= rel_eps:
                            best_qty = cand
                            break
                    
                    if best_qty and 1 <= best_qty <= 100:
                        item['quantity'] = float(best_qty)
                        item['unit_price'] = kb_unit_price
                        item['price_source'] = 'knowledge_base'
                        item['price_status'] = 'qty_inferred_from_kb'
                        total_qty += best_qty
                        logger.info(f"Costco KB: {item.get('product_name', 'Unknown')} ({item_number}): {best_qty} × ${kb_unit_price:.2f} = ${total_price:.2f}")
                    else:
                        # Couldn't resolve quantity cleanly
                        item['price_status'] = 'qty_unresolved'
                        unresolved.append(item)
                        logger.warning(f"Costco KB: Could not resolve quantity for {item_number} (total=${total_price:.2f}, unit=${kb_unit_price:.2f}, calc_qty={float(ratio):.2f})")
                else:
                    logger.debug(f"Costco KB: No unit price for {item_number}")
                    unresolved.append(item)
            else:
                if not kb_entry:
                    logger.debug(f"Costco KB: Item {item_number} not found in knowledge base")
                unresolved.append(item)
            
            enriched_items.append(item)
        
        # If we have "Total Items Sold" hint and unresolved items, try to distribute
        if items_sold_hint and unresolved and total_qty < items_sold_hint:
            diff = int(items_sold_hint) - total_qty
            logger.info(f"Costco: Distributing {diff} remaining items across {len(unresolved)} unresolved items")
            
            # Distribute evenly (usually unresolved items are 1-piece items)
            qty_per_item = max(1, diff // len(unresolved))
            for item in unresolved:
                if diff <= 0:
                    break
                item['quantity'] = float(qty_per_item)
                item['price_status'] = 'qty_inferred_by_items_sold_hint'
                # Try to back-calculate unit_price
                if item.get('total_price', 0) > 0:
                    item['unit_price'] = float(item['total_price']) / qty_per_item
                diff -= qty_per_item
        
        return enriched_items
    
    def _enrich_rd_items(self, items: list) -> list:
        """
        Enrich RD items with size/spec information from knowledge base.
        
        RD receipts already have unit_price and quantity, so we only add size info.
        
        Args:
            items: List of item dictionaries
        
        Returns:
            List of enriched items
        """
        from . import vendor_profiles
        
        # Load knowledge base (uses singleton cache)
        kb = vendor_profiles._ensure_kb_loaded()
        
        if not kb:
            logger.warning("Knowledge base not loaded, skipping RD enrichment")
            return items
        
        enriched_items = []
        
        for item in items:
            item_number = str(item.get('item_number', '')).strip()
            
            # Look up in knowledge base
            kb_entry = kb.get(item_number)
            if kb_entry:
                kb_spec = kb_entry.get('spec', '')  # Size/spec info
                kb_name = kb_entry.get('name', '')
                kb_store = kb_entry.get('store', '')
                
                # Add size/spec info if available
                if kb_spec:
                    item['kb_size'] = kb_spec
                    item['kb_source'] = 'knowledge_base'
                    logger.debug(f"RD KB: {item.get('product_name', 'Unknown')} ({item_number}): size={kb_spec}")
                
                # Optionally verify the name matches (for QA purposes)
                if kb_name and kb_name.upper() != item.get('product_name', '').upper():
                    item['kb_name_mismatch'] = True
                    logger.debug(f"RD KB: Name mismatch for {item_number}: receipt='{item.get('product_name')}' vs kb='{kb_name}'")
            else:
                logger.debug(f"RD KB: Item {item_number} not found in knowledge base")
            
            enriched_items.append(item)
        
        return enriched_items

