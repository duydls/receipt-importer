# Step 1: Receipt Extraction

Step 1 extracts receipt data from PDF, Excel, and CSV files using a rule-driven architecture.

## Overview

Step 1 processes receipts through a multi-stage pipeline:

1. **Vendor Detection** - Detects vendor and source type from file path and content
2. **Layout Application** - Applies vendor-specific Excel/PDF layouts to extract data
3. **UoM Extraction** - Extracts raw UoM/size text without normalization
4. **Legacy Processing** - Falls back to legacy processors if layout rules don't match

## Architecture

### Directory Structure

```
project_root/
├── step1_extract/                # Step 1 Python code
│   ├── __init__.py               # Module exports
│   ├── main.py                   # Main entry point and orchestration
│   ├── rule_loader.py            # YAML rule loading and caching
│   ├── vendor_detector.py        # Vendor detection using 10_vendor_detection.yaml
│   ├── vendor_matcher.py         # Vendor name matching and normalization
│   ├── layout_applier.py         # Layout application using 20_*.yaml files
│   ├── receipt_line_engine.py    # Generic YAML-driven receipt parsing engine
│   ├── uom_extractor.py          # UoM extraction using 30_uom_extraction.yaml
│   ├── excel_processor.py         # Excel file processing
│   ├── pdf_processor.py          # PDF file processing
│   ├── receipt_processor.py       # Legacy receipt processor (fallback)
│   ├── csv_processor.py          # CSV file processing (Instacart)
│   ├── instacart_csv_matcher.py  # Instacart CSV matching logic
│   ├── vendor_profiles.py        # Vendor profile handling
│   ├── fee_extractor.py          # Fee and discount extraction
│   ├── receipt_parsers.py        # Generic receipt parsing utilities
│   ├── ai_line_interpreter.py    # AI-based line interpretation (fallback)
│   ├── generate_report.py        # HTML report generation
│   ├── logger.py                 # Logging configuration
│   ├── utils/                    # Small helper modules
│   │   ├── __init__.py
│   │   ├── address_filter.py    # Address line filtering
│   │   └── text_extractor.py     # PDF text extraction
│   └── legacy/                   # Quarantined legacy parsers (fallback only)
│       ├── __init__.py
│       ├── costco_parser.py      # Old Costco-specific parser (deprecated)
│       └── rd_parser.py          # Old RD-specific parser (deprecated)
└── step1_rules/                  # Step 1 YAML rule files
    ├── 10_vendor_detection.yaml   # Vendor detection rules
    ├── 15_vendor_aliases.yaml     # Vendor alias normalization
    ├── 20_costco_layout.yaml      # Costco layout definitions
    ├── 21_rd_layout.yaml          # Restaurant Depot layout definitions
    ├── 22_jewel_layout.yaml       # Jewel/Mariano's layout definitions
    ├── 25_instacart_csv.yaml      # Instacart CSV matching config
    ├── 30_uom_extraction.yaml     # UoM extraction rules
    ├── 40_vendor_normalization.yaml  # Additional vendor normalization
    ├── 50_text_parsing.yaml      # Text parsing patterns
    ├── group1_excel.yaml         # Legacy Excel rules (fallback only)
    ├── group2_pdf.yaml           # Legacy PDF rules (fallback only)
    ├── shared.yaml               # Shared configuration (flags, fees, etc.)
    └── vendor_profiles.yaml      # Vendor profile definitions
```

### Rule-Driven Modules

- **`vendor_detector.py`** - Vendor detection using `10_vendor_detection.yaml`
- **`layout_applier.py`** - Layout application using `20_*.yaml` files
- **`receipt_line_engine.py`** - Generic YAML-driven receipt parsing (replaces vendor-specific parsers)
- **`uom_extractor.py`** - UoM extraction using `30_uom_extraction.yaml`
- **`rule_loader.py`** - YAML rule loading and caching

### Processors

- **`excel_processor.py`** - Excel file processing (tries layout rules first, falls back to legacy)
- **`pdf_processor.py`** - PDF file processing (Instacart - tries modern layouts, falls back to legacy)
- **`receipt_processor.py`** - Legacy receipt processor (used as fallback)

### Supporting Modules

- **`main.py`** - Main entry point and orchestration
- **`generate_report.py`** - HTML report generation
- **`vendor_profiles.py`** - Vendor profile handling
- **`csv_processor.py`** - CSV file processing (Instacart)
- **`fee_extractor.py`** - Fee and discount extraction
- **`instacart_csv_matcher.py`** - Instacart CSV matching logic

### Utilities

- **`utils/address_filter.py`** - Filters address lines from receipt text
- **`utils/text_extractor.py`** - Extracts text from PDF files (vendor-agnostic)

## Usage

### Command Line

```bash
python -m step1_extract.main <input_dir> <output_dir> [--rules-dir RULES_DIR] [--use-threads]
```

**Arguments:**
- `input_dir` - Input directory containing receipts
- `output_dir` - Output directory (creates `vendor_based/` and `instacart_based/` subdirs)
- `--rules-dir` - Custom rules directory (default: `step1_rules` in parent directory)
- `--use-threads` - Process files in parallel using ThreadPoolExecutor

**Example:**
```bash
python -m step1_extract.main data/step1_input data/step1_output
```

### Programmatic Usage

```python
from step1_extract import process_files
from pathlib import Path

results = process_files(
    input_dir=Path('data/step1_input'),
    output_base_dir=Path('data/step1_output'),
    rules_dir=Path('step1_rules'),
    use_threads=False
)

print(f"Extracted {len(results['vendor_based'])} vendor-based receipts")
print(f"Extracted {len(results['instacart_based'])} instacart-based receipts")
```

## Processing Flow

```
Input Files (PDF/Excel/CSV)
    ↓
Vendor Detection (10_vendor_detection.yaml)
    ↓ Adds: detected_vendor_code, detected_source_type
Layout Application (20_*.yaml files - multi-layout matching)
    ↓ Iterates layouts → picks first match → extracts items
    ↓ Adds: parsed_by (layout name)
UoM Extraction (30_uom_extraction.yaml)
    ↓ Adds: raw_uom_text, raw_size_text
Legacy Processing (fallback if no layout matches)
    ↓ Uses group1_excel.yaml or group2_pdf.yaml
    ↓ Adds: parsed_by (legacy_group1_excel/legacy_group2_pdf)
    ↓ Adds: needs_review: true, review_reasons
Output JSON + HTML Reports
```

## Output Structure

```
data/step1_output/
├── vendor_based/
│   ├── extracted_data.json
│   └── report.html
├── instacart_based/
│   ├── extracted_data.json
│   └── report.html
├── report.html (combined report)
└── logs/
    └── step1_extract.log
```

## Receipt Data Schema

### Receipt-Level Fields

```python
{
    'filename': 'Costco_0907.xlsx',
    'vendor': 'Costco',
    'detected_vendor_code': 'COSTCO',      # From vendor detection
    'detected_source_type': 'vendor_based', # From vendor detection
    'parsed_by': 'layout_standard_costco_receipt',  # Parser/layout used
    'needs_review': False,                 # True if legacy rules used
    'review_reasons': [],                   # Reasons if needs_review=True
    'source_file': 'Costco/Costco_0907.xlsx',
    'source_group': 'vendor_based',
    'order_date': '2025-09-07',
    'store_name': 'Costco',
    'items': [...],
    'total': 150.99,
    'subtotal': 150.99,
    'tax': 0.0,
    ...
}
```

### Item-Level Fields

```python
{
    'product_name': 'LIMES 3 LB.',
    'quantity': 1.0,
    'unit_price': 6.49,
    'total_price': 6.49,
    'raw_uom_text': 'lb',              # From UoM extraction (30_uom_extraction.yaml)
    'raw_size_text': '3.0 lb',         # From UoM extraction
    'parsed_by': 'layout_standard_costco_receipt',  # Parser/layout used (same as receipt)
    'item_number': '3923',              # Vendor-specific item identifier
    'upc': '012345678901',              # UPC code (if available)
    'line_text': '...',                 # Original line text from receipt
    ...
}
```

## Rule Files

See `step1_rules/README.md` for detailed rule file documentation.

## Configuration

### Rules Directory

Default: `step1_rules/` in project root

Custom: Use `--rules-dir` argument or set `rules_dir` parameter

### Knowledge Base

Location: `data/step1_input/knowledge_base.json`

Used for product enrichment (Costco and Restaurant Depot)

### Threading

Use `--use-threads` flag for parallel file processing (I/O-bound operations only)

**Note:** ThreadPoolExecutor is used for file-level parallelism only. Each file is processed independently — no shared state or database writes occur.

## Extending Step 1

### Adding a New Vendor

1. **Add vendor detection:**
   - Edit `step1_rules/10_vendor_detection.yaml`
   - Add filename patterns and content keywords

2. **Create layout rules:**
   - Create `step1_rules/23_newvendor_layout.yaml`
   - Define Excel formats and column mappings

3. **Update rule loader:**
   - Edit `step1_extract/rule_loader.py`
   - Add vendor code to layout file mapping

### Modifying Layout Extraction

1. **Edit layout file:**
   - Edit the appropriate `20_*.yaml` or create new one
   - Update column mappings for vendor's Excel format

2. **Rules auto-reload:**
   - Rules are reloaded automatically on next run (checksum-based)
   - No code changes needed

### Modifying UoM Extraction

1. **Edit UoM extraction rules:**
   - Edit `step1_rules/30_uom_extraction.yaml`
   - Add new extraction patterns or priority rules

## Legacy Parsers (Quarantined Fallback)

### Purpose

Legacy parsers are kept-but-quarantined fallback processors that are **not part of the normal processing path**. They exist to ensure backward compatibility and handle edge cases where modern YAML-based layouts do not match. All legacy code is located in `step1_extract/legacy/` and should not be used for new vendor implementations.

### When Legacy Parsers Trigger

Legacy parsers are only invoked when:

1. **Vendor detection rules have been applied** (10 → 15 → 40)
2. **No vendor layout matched** (20/21/22 for vendor-based, or no modern Instacart layout)
3. **For Instacart**: CSV matching (25) failed or CSV unavailable
4. **Feature flag enabled**: `shared.yaml` → `flags.enable_legacy_parsers: true` (default: ON)

**Processing order (explicit):**
```
10_vendor_detection.yaml
  ↓
15_vendor_aliases.yaml
  ↓
40_vendor_normalization.yaml
  ↓
IF detected_source_type == "instacart-based":
  25_instacart_csv.yaml
    ↓
  group2_pdf.yaml (legacy fallback if CSV failed/unavailable)
ELSE (vendor-based):
  20_costco_layout.yaml → 21_rd_layout.yaml → 22_jewel_layout.yaml (try each)
    ↓
  30_uom_extraction.yaml
    ↓
  group1_excel.yaml (legacy fallback if no layout matched)
  ↓
shared.yaml (common flags, fee keywords, multiline rules)
  ↓
vendor_profiles.yaml (Costco/RD extra info, if available)
```

### Output Contract

When legacy parsers are used, the following fields are guaranteed:

**Receipt-level fields:**
- `parsed_by: "legacy_group1_excel"` or `"legacy_group2_pdf"` - Identifies legacy processing
- `needs_review: true` - Always set when legacy is used
- `review_reasons: ["step1: no modern layout matched, used legacy group rules"]` - Review reason

**Item-level fields:**
- `parsed_by: "legacy_group1_excel"` or `"legacy_group2_pdf"` - Same as receipt level

**Preserved fields (never overwritten):**
- `detected_vendor_code` - From vendor detection (preserved)
- `detected_source_type` - From vendor detection (preserved)
- `source_file` - Original file path (preserved)

### Rule-of-Thumb

**Python applies; YAML decides.** Parsers do not guess layouts. If no YAML layout matches, the system falls back to legacy with explicit logging.

### Logging

When legacy parsers are invoked, a clear log message is printed:

```
[LEGACY] Using legacy parser for: <file_path> (vendor=<vendor_code>, reason=no layout matched)
```

This makes it easy to identify receipts that need modern layout rules.

### How to Avoid Legacy Parsers

To move receipts off legacy processing:

1. **Expand vendor layout YAML**: Add or update `20_*.yaml`, `21_*.yaml`, `22_*.yaml` files
2. **Update Instacart CSV matching**: Improve `25_instacart_csv.yaml` rules
3. **Adjust text parsing**: Update `50_text_parsing.yaml` patterns
4. **Improve vendor detection**: Update `10_vendor_detection.yaml` patterns
5. **Normalize vendor names**: Update `15_vendor_aliases.yaml` or `40_vendor_normalization.yaml`

### Toggle/Quarantine

**Feature flag:** Legacy parsers can be disabled by setting in `step1_rules/shared.yaml`:

```yaml
flags:
  enable_legacy_parsers: false  # Disable legacy fallback
```

**Default:** `true` (enabled for backward compatibility)

**Location:** All legacy code is quarantined in `step1_extract/legacy/`:
- `legacy/costco_parser.py` - Old Costco-specific parser (deprecated)
- `legacy/rd_parser.py` - Old RD-specific parser (deprecated)

These should **never** be imported directly. They are only called through `receipt_processor.py` when the feature flag is enabled.

### QA Checklist for Parsing PRs

When adding or modifying parsing logic:

- [ ] **Positive applies_to**: Test with receipts that should match the layout
- [ ] **Negative applies_to**: Test with receipts that should NOT match the layout
- [ ] **parsed_by label**: Verify `parsed_by` is set correctly on receipt and all items
- [ ] **Report renders**: HTML report displays correctly without legacy warnings
- [ ] **Review flags**: If legacy fires, verify `needs_review: true` and `review_reasons` contain fallback message
- [ ] **Preserved fields**: Verify `detected_vendor_code`, `detected_source_type`, `source_file` are not overwritten
- [ ] **Logging**: Verify `[LEGACY]` log message appears when legacy is used

## Testing

Unit tests are located in `step1_extract/test_legacy_fallback.py`:

```bash
python -m pytest step1_extract/test_legacy_fallback.py -v
```

Tests verify:
- Legacy fallback sets correct `parsed_by` markers
- `needs_review` and `review_reasons` are set correctly
- Preserved fields are not overwritten
- Feature flag correctly enables/disables legacy parsers

## Integration with Step 2

Step 1 output is consumed by Step 2:

- **Vendor detection fields:** `detected_vendor_code`, `detected_source_type` → Used for vendor matching in Step 2
- **UoM extraction fields:** `raw_uom_text`, `raw_size_text` → Normalized to Odoo UoMs in Step 2
- **Item fields:** All item fields are passed through for mapping in Step 2

## See Also

- **Rules Documentation:** `step1_rules/README.md`
- **Step 2 Documentation:** `step2_mapping/README.md`
- **Workflow Documentation:** `README_WORKFLOW.md`

