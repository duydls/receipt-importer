# Step 1 Rules Configuration

Step 1 extraction uses YAML-based rule files organized by processing stages.

## File Structure

```
step1_rules/
├── shared.yaml              # Shared rules (UoM aliases, fees, validation, etc.)
├── vendor_profiles.yaml      # Vendor profile definitions
├── group1_excel.yaml         # Legacy rules (Excel processing - fallback only)
├── group2_pdf.yaml           # Legacy rules (PDF processing - fallback only)
│
├── 10_vendor_detection.yaml  # Vendor detection rules
├── 20_costco_layout.yaml    # Costco multi-layout rules
├── 21_rd_layout.yaml        # Restaurant Depot multi-layout rules
├── 22_jewel_layout.yaml     # Jewel/Mariano's multi-layout rules
└── 30_uom_extraction.yaml   # UoM extraction rules
```

## Processing Flow

Step 1 processes receipts in the following order:

1. **Vendor Detection** (`10_vendor_detection.yaml`) - Detects vendor and source type from filename/path and receipt content
2. **Layout Application** (`20_*.yaml` files) - Iterates through multiple layouts and picks the first matching one
3. **UoM Extraction** (`30_uom_extraction.yaml`) - Extracts raw UoM/size text (no normalization)
4. **Legacy Processing** (fallback) - Uses legacy processors (`group1_excel.yaml` or `group2_pdf.yaml`) if no layout matches

## Rule Files

### 10_vendor_detection.yaml

Detects vendor code and source type from file path, filename, and receipt content.

**Output fields added to receipts:**
- `detected_vendor_code`: Vendor code (e.g., 'COSTCO', 'RD', 'JEWEL', 'INSTACART')
- `detected_source_type`: Source type ('vendor_based' or 'instacart_based')

**Detection methods:**
1. **Filename/Path patterns**: Matches filename or path against vendor patterns
2. **Content keywords**: Matches receipt text content against vendor keywords
3. **Fallback**: Uses default values if detection fails

### 20_costco_layout.yaml, 21_rd_layout.yaml, 22_jewel_layout.yaml

Multi-layout rule files that define multiple layout variants per vendor. Each file contains a top-level list of layouts:

**Structure:**
```yaml
costco_layouts:
  - name: "Standard Costco Receipt"
    applies_to:
      vendor_code: ["COSTCO"]
      file_ext: [".xlsx", ".xls"]
      header_contains: ["Item Description", "Extended Amount (USD)"]
    required_columns: [...]
    column_mappings: {...}
    ...
  - name: "Costco Detailed Receipt"
    applies_to: {...}
    ...
```

**Layout matching:**
- Iterates through layouts in order
- Picks the **first** layout that matches all `applies_to` conditions
- If no layout matches, falls back to legacy rules

**`applies_to` conditions:**
- `vendor_code`: List of vendor codes (e.g., `["COSTCO"]`, `["RD", "RESTAURANT_DEPOT"]`)
- `file_ext`: List of file extensions (e.g., `[".xlsx", ".xls"]`)
- `header_contains`: List of required column headers (matched against DataFrame columns)
- `text_contains`: Optional list of text patterns (matched against receipt text content)

**Column mappings:**
- Maps Excel column names to internal field names
- Supports optional columns (marked with `# Optional` in comments)
- Handles fuzzy matching for column names

**Normalization:**
- Clean citation markers (e.g., `[cite: ...]`)
- Trim whitespace
- Preserve case (for RD short codes)

**Skip patterns:**
- List of patterns to skip during extraction (e.g., "TAX", "TOTAL", "nan")

### 30_uom_extraction.yaml

Extracts raw unit/size text from receipt lines without normalization.

**Output fields added to items:**
- `raw_uom_text`: Raw unit of measure text from receipt
- `raw_size_text`: Raw size/weight text from receipt

**Extraction priority:**
1. Excel columns ('Size', 'UOM', 'Unit', etc.)
2. Product name patterns (e.g., "PRODUCT 3 LB" → "3 LB")
3. Separate size lines (PDFs)
4. Quantity unit patterns

**Important:**
- Does **NOT** normalize to Odoo UoMs
- Step 2 handles UoM normalization
- Preserves original case and formatting

## Legacy Rule Files

### group1_excel.yaml

Legacy rules for vendor-based Excel receipts (fallback only).

- Used when no modern layout matches
- Adds `parsed_by: "legacy_group1_excel"` to receipt and items
- Marks with `needs_review: true` and review reason

### group2_pdf.yaml

Legacy rules for Instacart PDF receipts (fallback only).

- Used for PDF processing
- Adds `parsed_by: "legacy_group2_pdf"` to receipt and items
- Marks with `needs_review: true` and review reason

### shared.yaml

Shared rules inherited by legacy processors:
- `uom_aliases`: Unit of measure normalization
- `fees`: Fee pattern definitions
- `validation`: Validation rules (tolerance, required fields)
- `output_fields`: Standard output schema

### vendor_profiles.yaml

Vendor profile definitions for product enrichment.

## Layout Matching Logic

When processing a receipt:

1. **Load vendor layout file** (e.g., `20_costco_layout.yaml`)
2. **Get layouts list** (e.g., `costco_layouts`)
3. **Iterate through layouts** in order
4. **Check `applies_to` conditions:**
   - `vendor_code`: Must match detected vendor code
   - `file_ext`: Must match file extension
   - `header_contains`: All specified headers must be present in DataFrame columns
   - `text_contains`: All specified patterns must be present in receipt text (if provided)
5. **Apply first matching layout:**
   - Extract items using column mappings
   - Apply normalization rules
   - Skip rows matching skip patterns
   - Set `parsed_by` field on receipt and items
6. **If no layout matches:**
   - Fall back to legacy processor (`group1_excel.yaml` or `group2_pdf.yaml`)
   - Add `parsed_by: "legacy_group1_excel"` or `"legacy_group2_pdf"`
   - Set `needs_review: true`
   - Add review reason: `"step1: no modern layout matched, used legacy group rules"`

## Output Schema

**Receipt-level fields:**
- `detected_vendor_code`: Vendor code from detection rules
- `detected_source_type`: Source type ('vendor_based' or 'instacart_based')
- `parsed_by`: Parser/layout used ('layout_standard_costco_receipt', 'legacy_group1_excel', etc.)
- `needs_review`: `true` if legacy rules were used, `false` otherwise
- `review_reasons`: Array of review reasons (only when using legacy rules)
- `vendor`: Vendor name (may differ from detected_vendor_code)
- `source_file`: Relative path to source file
- `source_group`: Receipt group ('vendor_based' or 'instacart_based')

**Item-level fields:**
- `parsed_by`: Same as receipt-level (indicates which parser extracted this item)
- `raw_uom_text`: Raw unit of measure text (no normalization)
- `raw_size_text`: Raw size/weight text (no normalization)
- `product_name`: Product name from receipt
- `quantity`: Quantity
- `unit_price`: Unit price
- `total_price`: Total price
- Other fields as extracted by processors

## Rule Loading

Rules are loaded by `step1_extract/rule_loader.py`:
- Automatically loads rule files by name
- Supports hot-reload (checksum-based caching)
- Handles both new multi-layout structure and old format structure (backward compatibility)

## Processing Architecture

### Rule-Driven Modules

1. **`vendor_detector.py`** - Applies vendor detection rules
   - Loads `10_vendor_detection.yaml`
   - Detects vendor from filename/path and receipt content
   - Adds `detected_vendor_code` and `detected_source_type` to receipts

2. **`layout_applier.py`** - Applies layout rules to Excel files
   - Loads layout rules (`20_*.yaml`) based on vendor code
   - Iterates through layouts and picks first matching one
   - Extracts items using column mappings from matched layout
   - Updates receipt metadata

3. **`uom_extractor.py`** - Extracts raw UoM/size text
   - Loads `30_uom_extraction.yaml`
   - Extracts from Excel columns or product names
   - Adds `raw_uom_text` and `raw_size_text` to items
   - Does NOT normalize (Step 2 handles that)

### Legacy Processors

- **`excel_processor.py`** - Excel file processing (with layout rule support)
  - Tries layout rules first
  - Falls back to legacy `ReceiptProcessor` if no layout matches
  - Applies UoM extraction after processing

- **`pdf_processor.py`** - PDF file processing
  - Uses legacy `ReceiptProcessor` for PDFs
  - Applies UoM extraction after processing

## Knowledge Base

Product enrichment for Costco and Restaurant Depot uses a local knowledge base:
- Location: `data/step1_input/knowledge_base.json`
- Format: JSON dictionary with item numbers/UPCs as keys
- Structure: `{item_number: [name, store, spec, price]}`
- Manual updates: Edit JSON file as new items are encountered

## Usage

Rules are automatically loaded by the Step 1 extraction system. No manual configuration needed.

**To modify rules:**
1. Edit the appropriate YAML file
2. Rules are automatically reloaded on next run (checksum-based)
3. Or restart the workflow to force reload

**To add a new layout:**
1. Edit the appropriate layout file (`20_*.yaml`, `21_*.yaml`, or `22_*.yaml`)
2. Add a new layout entry to the list
3. Define `applies_to` conditions for matching
4. Define `column_mappings` and other configuration

**To add a new vendor:**
1. Add vendor patterns to `10_vendor_detection.yaml`
2. Create a new layout file (e.g., `23_newvendor_layout.yaml`)
3. Add vendor code mapping in `rule_loader.py`

## Migration from Legacy

The new multi-layout approach:
- ✅ Maintains backward compatibility (legacy processors used as fallback)
- ✅ Adds new fields (`parsed_by`, `needs_review`, `review_reasons`)
- ✅ Preserves all existing processing logic
- ✅ Gradual migration path available

Existing code continues to work, with new multi-layout features added on top.
