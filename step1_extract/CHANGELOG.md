# Step 1 Refactoring Changelog

## Multi-Layout Support (Latest)

### New Multi-Layout Structure

Updated layout rule files to support multiple layouts per vendor with `applies_to` conditions:

- **`20_costco_layout.yaml`** - Multiple Costco layouts
- **`21_rd_layout.yaml`** - Multiple RD layouts
- **`22_jewel_layout.yaml`** - Multiple Jewel/Mariano's layouts

**Structure:**
```yaml
costco_layouts:
  - name: "Standard Costco Receipt"
    applies_to:
      vendor_code: ["COSTCO"]
      file_ext: [".xlsx", ".xls"]
      header_contains: ["Item Description", "Extended Amount (USD)"]
    column_mappings: {...}
  - name: "Costco Detailed Receipt"
    applies_to: {...}
    ...
```

**Layout Matching:**
- Iterates through layouts in order
- Picks first layout that matches all `applies_to` conditions
- Falls back to legacy rules if no layout matches

### Updated Modules

- **`layout_applier.py`** - Updated to support multi-layout matching
  - Iterates through layouts list
  - Checks `applies_to` conditions (vendor_code, file_ext, header_contains, text_contains)
  - Picks first matching layout
  - Sets `parsed_by` field when layout matches
  - Falls back to old format structure for backward compatibility

- **`excel_processor.py`** - Updated fallback logic
  - Adds `parsed_by: "legacy_group1_excel"` when falling back
  - Sets `needs_review: true`
  - Adds `review_reasons: ["step1: no modern layout matched, used legacy group rules"]`
  - Adds `parsed_by` to all items

- **`pdf_processor.py`** - Updated to mark legacy processing
  - Adds `parsed_by: "legacy_group2_pdf"` for PDF processing
  - Sets `needs_review: true`
  - Adds `review_reasons: ["step1: no modern layout matched, used legacy group rules"]`
  - Adds `parsed_by` to all items

- **`rule_loader.py`** - Updated to return layouts list
  - Returns layouts list directly from YAML file
  - Maintains backward compatibility with old format structure

### New Output Fields

**Receipt-level:**
- `parsed_by`: Parser/layout used (e.g., `"layout_standard_costco_receipt"`, `"legacy_group1_excel"`)
- `needs_review`: `true` if legacy rules used, `false` otherwise
- `review_reasons`: Array of review reasons (only when using legacy rules)

**Item-level:**
- `parsed_by`: Same as receipt-level (indicates which parser extracted this item)

### Backward Compatibility

All changes maintain backward compatibility:
- Old `excel_formats` structure still supported (fallback detection)
- Legacy processors remain functional
- No breaking changes to existing functionality
- Gradual migration path available

### Output Schema Changes

**New fields added:**
- `parsed_by`: Indicates which parser/layout was used
- `needs_review`: Flag for review needed (only when legacy rules used)
- `review_reasons`: Array of reasons (only when legacy rules used)

**Preserved fields:**
- All existing fields remain unchanged
- `detected_vendor_code`, `detected_source_type`, `raw_uom_text`, `raw_size_text` preserved
- No breaking changes to Step 2 integration

---

## Rule-Driven Refactoring (Previous)

### New Rule Files

Created new rule-driven architecture with numbered rule files:

- **`10_vendor_detection.yaml`** - Vendor detection rules
  - Detects vendor from filename/path patterns and receipt content keywords
  - Adds `detected_vendor_code` and `detected_source_type` to every receipt
  - Supports: Costco, RD, Jewel, Mariano's, Aldi, ParkToShop, Instacart

- **`20_costco_layout.yaml`** - Costco Excel layout rules
  - Defines Excel formats (Format 1, Format 2, Format 3)
  - Column mappings for product_name, item_number, total_price, etc.
  - Normalization and skip patterns

- **`21_rd_layout.yaml`** - Restaurant Depot Excel layout rules
  - Defines Excel format with 'Item Name', 'Amount', optional 'Qty', 'Price', 'Size'
  - Preserves case for short codes (e.g., "CHX NUGGET BTRD TY")

- **`22_jewel_layout.yaml`** - Jewel/Mariano's Excel layout rules
  - Defines Excel format with 'Item', 'Total', optional 'Qty', 'Unit Price', 'Size'
  - Preserves case for product names

- **`30_uom_extraction.yaml`** - UoM extraction rules
  - Extracts raw unit/size text from Excel columns or product names
  - Adds `raw_uom_text` and `raw_size_text` to items
  - **Does NOT normalize** (Step 2 handles normalization)

### New Modules

- **`vendor_detector.py`** - Vendor detection using `10_vendor_detection.yaml`
  - Detects vendor from filename/path and receipt content
  - Applies detection rules to receipts
  - Adds `detected_vendor_code` and `detected_source_type` fields

- **`layout_applier.py`** - Layout application using `20_*.yaml` files
  - Applies vendor-specific Excel layouts
  - Detects Excel format automatically
  - Extracts items using column mappings from rules
  - Updates receipt metadata

- **`uom_extractor.py`** - UoM extraction using `30_uom_extraction.yaml`
  - Extracts raw UoM/size text from items
  - Priority-based extraction (Excel columns → product name → patterns)
  - Adds `raw_uom_text` and `raw_size_text` fields

### Updated Modules

- **`main.py`** - Updated to use rule-driven architecture
  - Initializes VendorDetector first
  - Applies vendor detection to all receipts
  - Preserves all existing processing logic

- **`excel_processor.py`** - Updated to use layout rules
  - Tries layout rules first (20_*.yaml files)
  - Falls back to legacy processor if layout rules don't match
  - Applies UoM extraction after processing

- **`pdf_processor.py`** - Updated to apply UoM extraction
  - Applies UoM extraction after processing
  - Preserves all existing Instacart logic

- **`rule_loader.py`** - Enhanced with new methods
  - `load_rule_file_by_name()` - Load specific rule file by name
  - `get_vendor_detection_rules()` - Get vendor detection rules
  - `get_layout_rules()` - Get layout rules for vendor code
  - `get_uom_extraction_rules()` - Get UoM extraction rules

### Output Schema Changes

**New receipt-level fields:**
- `detected_vendor_code`: Vendor code from detection rules (e.g., 'COSTCO', 'RD')
- `detected_source_type`: Source type ('vendor_based' or 'instacart_based')

**New item-level fields:**
- `raw_uom_text`: Raw unit of measure text (no normalization)
- `raw_size_text`: Raw size/weight text (no normalization)

**Preserved fields:**
- All existing fields remain unchanged
- Legacy fields (e.g., `purchase_uom`, `size`) preserved for compatibility

### Migration Notes

**For users:**
- No code changes required
- Rules are automatically loaded
- Legacy processing continues to work

**For developers:**
- New rule files: `10_vendor_detection.yaml`, `20_*.yaml`, `30_uom_extraction.yaml`
- New modules: `vendor_detector.py`, `layout_applier.py`, `uom_extractor.py`
- Legacy processors remain as fallback
- Gradual migration path available

### Future Enhancements

Potential future improvements:
- Add more vendor layout rules (Aldi, ParkToShop, etc.)
- Enhance PDF layout rules (currently uses legacy processor)
- Add more UoM extraction patterns
- Improve vendor detection accuracy
- Migrate more processing logic to rules
