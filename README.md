# Receipt Importer - Rule-Driven Receipt Processing System

A comprehensive, **100% YAML-driven** receipt processing pipeline that extracts, categorizes, and normalizes purchase data from multiple vendors and formats (Excel, PDF, CSV).

---

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run Step 1: Extract & Classify
python -m step1_extract.main data/step1_input data/step1_output

# View HTML reports
open data/step1_output/report.html
open data/step1_output/classification_report.html

# View PDFs (auto-generated)
open data/step1_output/classification_report.pdf
```

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Output Structure](#output-structure)
- [Configuration](#configuration)
- [Category Classification](#category-classification)
- [Performance Features](#performance-features)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)

---

## 🎯 Overview

This system processes receipts from **4 distinct source types**:

| Source Type | Format | Vendors | Processing Method |
|------------|--------|---------|-------------------|
| **Local Grocery** | Excel (.xlsx) | Costco, Jewel-Osco, Aldi, Mariano's, Restaurant Depot, ParkToShop | Layout-based extraction |
| **Instacart** | PDF + CSV baseline | Instacart | PDF text extraction + CSV enrichment |
| **BBI** | Excel (.xlsx) | BBI Wholesale | Layout-based extraction |
| **Amazon** | CSV + PDF validation | Amazon Business | CSV-first processing |

### Key Principles

✅ **100% Rule-Driven**: All vendor logic, parsing patterns, and categories defined in YAML  
✅ **No Hardcoded Logic**: Column names, regex patterns, categories all in configuration files  
✅ **Deterministic**: Same input always produces same output  
✅ **Explainable**: Every classification decision is traceable with rule IDs  
✅ **Maintainable**: Add new vendors/categories by editing YAML, no code changes  

---

## 🏗 Architecture

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│  INPUT: Excel/PDF/CSV files organized by source type        │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  STAGE 1: Vendor Detection (10_vendor_detection.yaml)       │
│  - Detects vendor from filename/path/content                │
│  - Assigns source_type: localgrocery/instacart/bbi/amazon   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  STAGE 2: Layout Application (20_*.yaml files)              │
│  - Modern: Multi-layout YAML rules with applies_to          │
│  - Legacy: Fallback to group1/group2 if no match            │
│  - Extracts: items, tax, total, metadata                    │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  STAGE 3: UoM Extraction (30_uom_extraction.yaml)           │
│  - Extracts raw unit/size text from product names           │
│  - Handles vendor-specific abbreviations                    │
│  - Adds: raw_uom_text, purchase_uom                         │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  STAGE 4: Category Classification (55-59_*.yaml)            │
│  - L1 (Accounting): COGS, Packaging, Taxes, etc.           │
│  - L2 (Operational): Tea/Coffee, Fresh Fruit, Cups, etc.   │
│  - Pipeline: source_map → keywords → heuristics → fallback  │
│  - Adds: l1_category, l2_category, confidence, source       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  OUTPUT: JSON + HTML + PDF reports per source type          │
│  - extracted_data.json (structured data)                    │
│  - report.html (detailed item review)                       │
│  - classification_report.html (category analytics)          │
│  - All reports also generated as PDFs                       │
└─────────────────────────────────────────────────────────────┘
```

### Rule Files (step1_rules/)

| File | Purpose |
|------|---------|
| `10_vendor_detection.yaml` | Filename/content patterns → vendor code |
| `15_vendor_aliases.yaml` | Vendor name normalization |
| `20_costco_layout.yaml` | Costco Excel layouts (multiple) |
| `21_rd_layout.yaml` | Restaurant Depot layouts |
| `22_jewel_layout.yaml` | Jewel-Osco layout |
| `23_aldi_layout.yaml` | Aldi layout |
| `24_marianos_layout.yaml` | Mariano's layout |
| `26_parktoshop_layout.yaml` | ParkToShop layout |
| `27_bbi_layout.yaml` | BBI Wholesale layout |
| `25_instacart_csv.yaml` | Instacart CSV matching rules |
| `28_amazon_csv.yaml` | Amazon CSV field mappings |
| `30_uom_extraction.yaml` | UoM regex patterns |
| `40_vendor_normalization.yaml` | Vendor name cleanup |
| `shared.yaml` | Shared rules (fees, text parsing, validation) |
| `vendor_profiles.yaml` | Vendor KB lookup configs |
| `55_categories_l1.yaml` | L1 categories + L2→L1 mapping |
| `56_categories_l2.yaml` | L2 category catalog |
| `57_category_maps_instacart.yaml` | Instacart-specific mappings |
| `58_category_maps_amazon.yaml` | Amazon-specific mappings (UNSPSC) |
| `59_category_keywords.yaml` | Global keywords + heuristics |

---

## ✨ Features

### Data Extraction
- ✅ **Multi-format support**: Excel (.xlsx, .xls), PDF, CSV
- ✅ **Vendor-specific parsers**: Costco, RD, Jewel-Osco, Aldi, Mariano's, ParkToShop, BBI, Instacart, Amazon
- ✅ **Smart header detection**: Dynamically finds headers in messy Excel files
- ✅ **Robust numeric parsing**: Handles currency symbols, commas, negatives, Excel-quoted strings
- ✅ **Multi-layout support**: Each vendor can have multiple layouts with conditional matching
- ✅ **Graceful fallback**: Uses legacy rules if modern layouts don't match
- ✅ **CSV baseline matching**: Instacart PDFs enriched with CSV data
- ✅ **CSV-first processing**: Amazon treats CSV as authoritative, PDFs for validation

### Unit of Measure (UoM)
- ✅ **Pattern-based extraction**: Regex patterns for standard units (lb, kg, oz, ct, etc.)
- ✅ **Vendor abbreviations**: RD ("CHX" → chicken), Costco ("ORG STRAWBRY" → organic strawberry)
- ✅ **Multi-pack formats**: "6×3-kg", "42 Count", "10 Lb", "Pack of 12"
- ✅ **Knowledge base enrichment**: Costco/RD items enriched with KB specs

### Category Classification
- ✅ **Two-level hierarchy**: L1 (Accounting) → L2 (Operational)
- ✅ **14 L1 categories**: COGS-Ingredients, COGS-Packaging, Taxes & Fees, Shipping, Tips, Office, etc.
- ✅ **30+ L2 categories**: Tea & Coffee, Fresh Fruit, Frozen Vegetables, Cups & Lids, etc.
- ✅ **Multi-stage pipeline**: Source maps → Keywords → Heuristics → Overrides → Fallback
- ✅ **Source-specific rules**: Instacart (department/aisle), Amazon (UNSPSC taxonomy)
- ✅ **Vendor-specific patterns**: Costco fruit abbreviations, RD protein prefixes, BBI packaging
- ✅ **Explainable**: Every item tagged with `category_source`, `category_rule_id`, `category_confidence`

### Quality & Validation
- ✅ **Automatic review flagging**: Zero prices, missing quantities, total mismatches
- ✅ **Confidence scoring**: Per-item confidence scores
- ✅ **Tax-exempt validation**: Flags unexpected tax for Costco, Instacart, ParkToShop
- ✅ **Count verification**: Items sold vs extracted item count
- ✅ **Total verification**: Sum of items vs grand total

### Reporting
- ✅ **Detailed HTML reports**: Per-source-type breakdowns with item details
- ✅ **Classification analytics**: L1/L2 breakdowns, vendor analysis, unmapped queue
- ✅ **Interactive charts**: 5 pie charts (L1 items/spend, L2 top 10, vendors, sources)
- ✅ **PDF generation**: Auto-converts all HTML reports to PDF using Chrome headless
- ✅ **CSV export**: Classification data exportable to CSV

### Performance
- ✅ **Vectorized extraction**: Pandas vectorized ops for large Excel files (Feature 2)
- ✅ **Rule loader fast-path**: Hot-reload OFF by default, ~50ms saved per file (Feature 3)
- ✅ **Column mapping cache**: LRU cache for repeated layouts, ~30-50% faster (Feature 4)
- ✅ **Modern-first short-circuit**: Skips legacy processing if modern succeeds (Feature 1)
- ✅ **Parallel processing**: ThreadPoolExecutor for batch processing

---

## 💻 Installation

### Prerequisites
- Python 3.8+
- Chrome/Chromium (optional, for PDF generation)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Optional: Install Playwright for PDF Generation

```bash
pip install playwright
playwright install chromium
```

*Note: PDF generation will skip gracefully if Chrome is not available. You can still print HTML reports to PDF manually from your browser.*

---

## 📖 Usage

### Basic Usage

```bash
# Process all receipts
python -m step1_extract.main data/step1_input data/step1_output
```

### Input Directory Structure

```
data/step1_input/
├── COSTCO/               # Local grocery - Costco Excel files
│   ├── Costco_0907.xlsx
│   └── Costco_0916.xlsx
├── RD/                   # Local grocery - Restaurant Depot
│   ├── RD_0902.xlsx
│   └── RD_0922.xlsx
├── JEWEL/                # Local grocery - Jewel-Osco
│   └── Jewel-Osco_0903.xlsx
├── ALDI/                 # Local grocery - Aldi
│   └── aldi_0905.xlsx
├── MARIANOS/             # Local grocery - Mariano's
│   └── 0915_marianos.xlsx
├── PARKTOSHOP/           # Local grocery - ParkToShop
│   └── parktoshop_0908.xlsx
├── INSTACART/            # Instacart PDFs + CSV baseline
│   ├── *.pdf
│   └── order_summary_report.csv
├── BBI/                  # BBI Wholesale Excel files
│   └── BBI_Purchase_*.xlsx
└── AMAZON/               # Amazon CSV + PDF validation
    ├── orders_from_*.csv
    └── *.pdf
```

### Environment Variables (Optional)

```bash
# Debug controls
export RECEIPTS_DEBUG=1                    # Enable debug logging
export FORCE_VENDOR=COSTCO                 # Force vendor detection
export FORCE_LAYOUT=costco_layout_2        # Force layout selection

# Performance toggles
export RECEIPTS_VECTORIZE=0                # Disable vectorized extraction
export RECEIPTS_HOT_RELOAD=1               # Enable YAML hot-reload
export RECEIPTS_DISABLE_COLUMN_MAP_CACHE=1 # Disable column map cache

# Feature flags
export RECEIPTS_PARALLEL=1                 # Enable parallel processing
```

---

## 📊 Output Structure

```
data/step1_output/
├── report.html                      # Combined report (all sources)
├── report.pdf                       # PDF version
├── classification_report.html       # Category analytics
├── classification_report.pdf        # PDF version
├── classification_report.csv        # Exportable category data
│
├── localgrocery_based/             # Local grocery Excel receipts
│   ├── extracted_data.json
│   ├── report.html
│   └── report.pdf
│
├── instacart_based/                # Instacart PDF + CSV
│   ├── extracted_data.json
│   ├── report.html
│   └── report.pdf
│
├── bbi_based/                      # BBI Wholesale
│   ├── extracted_data.json
│   ├── report.html
│   └── report.pdf
│
└── amazon_based/                   # Amazon Business
    ├── extracted_data.json
    ├── report.html
    └── report.pdf
```

### JSON Schema (extracted_data.json)

```json
{
  "receipts": [
    {
      "source_file": "Costco_0907.xlsx",
      "detected_vendor_code": "COSTCO",
      "detected_source_type": "localgrocery_based",
      "parsed_by": "costco_layout_1",
      "vendor_name": "Costco Wholesale",
      "transaction_date": "2025-09-07",
      "total": 123.45,
      "tax": 10.12,
      "other_charges": 0.0,
      "needs_review": false,
      "review_reasons": [],
      "items": [
        {
          "product_name": "ORG STRAWBRY",
          "quantity": 2.0,
          "unit_price": 4.99,
          "total_price": 9.98,
          "purchase_uom": "2-lb",
          "raw_uom_text": "2 lb",
          "l1_category": "A01",
          "l1_category_name": "COGS–Ingredients",
          "l2_category": "C09",
          "l2_category_name": "Fresh Fruit",
          "category_source": "keyword_rule",
          "category_rule_id": "kw_fruit_001",
          "category_confidence": 0.95,
          "needs_category_review": false
        }
      ]
    }
  ]
}
```

---

## ⚙️ Configuration

### Adding a New Vendor

1. **Add vendor detection rule** (`step1_rules/10_vendor_detection.yaml`):
```yaml
- vendor_code: NEWVENDOR
  filename_patterns:
    - "(?i)newvendor"
  path_patterns:
    - "NEWVENDOR/"
  source_type: localgrocery_based
```

2. **Create layout file** (`step1_rules/20_newvendor_layout.yaml`):
```yaml
newvendor_layout:
  - name: newvendor_layout_1
    applies_to:
      vendor_code: NEWVENDOR
    column_mappings:
      "Item Name": product_name
      "Qty": quantity
      "Price": unit_price
      "Total": total_price
```

3. **Add UoM patterns** (if needed):
```yaml
# 30_uom_extraction.yaml
extract_patterns:
  - '(\d+\.?\d*)\s*(?:lb|kg|oz|ct)'
```

4. **Add category rules** (if vendor has specific patterns):
```yaml
# 59_category_keywords.yaml
keyword_rules:
  - include_regex: '(?i)vendor_specific_term'
    map_to_l2: C01
```

### Adding a New Category

1. **Add L2 category** (`step1_rules/56_categories_l2.yaml`):
```yaml
- id: C50
  name: New Category
  description: Description here
  examples: [example1, example2]
```

2. **Add L2→L1 mapping** (`step1_rules/55_categories_l1.yaml`):
```yaml
l2_to_l1_map:
  C50: A01  # Maps to existing L1
```

3. **Add keyword rules** (`step1_rules/59_category_keywords.yaml`):
```yaml
keyword_rules:
  - include_regex: '(?i)keyword_pattern'
    map_to_l2: C50
    priority: 80
```

---

## 📂 Category Classification

### L1 Categories (Accounting)

| ID | Name | Description |
|----|------|-------------|
| A01 | COGS–Ingredients | Raw ingredients for production |
| A02 | COGS–Packaging | Packaging materials (cups, lids, bags) |
| A03 | COGS–Non-food | Non-food consumables (napkins, straws) |
| A04 | Smallwares/Equipment | Small equipment & tools |
| A05 | Cleaning/Janitorial | Cleaning supplies |
| A06 | Office/Admin | Office supplies, uniforms |
| A07 | Taxes & Fees | Sales tax, fees |
| A08 | Shipping/Delivery | Shipping charges |
| A09 | Tips/Gratuities | Tips |
| A99 | Other/Unmapped | Uncategorized |

### L2 Categories (Operational) - Top 15

| ID | Name | Parent L1 |
|----|------|-----------|
| C01 | Tea & Coffee | A01 |
| C02 | Syrups & Flavorings | A01 |
| C03 | Jam/Purée/Sauce | A01 |
| C04 | Dairy & Milk | A01 |
| C05 | Sweeteners/Sugar | A01 |
| C06 | Creamer & Powders | A01 |
| C07 | Grains & Starches | A01 |
| C08 | Toppings & Jellies | A01 |
| C09 | Fresh Fruit | A01 |
| C10 | Frozen Fruit | A01 |
| C11 | Canned/Processed Fruit | A01 |
| C12 | Fresh Vegetables | A01 |
| C13 | Frozen Vegetables | A01 |
| C14 | Meat & Seafood | A01 |
| C15 | Other Ingredients | A01 |

*See `docs/CATEGORY_CLASSIFICATION_GUIDE.md` for complete list.*

### Classification Pipeline

```
1. SOURCE MAPS (highest priority)
   ├─ Instacart: department/category_path/aisle
   └─ Amazon: UNSPSC taxonomy, item_title_regex

2. VENDOR OVERRIDES
   └─ Vendor-specific mappings from 56_categories_l2.yaml

3. GLOBAL KEYWORDS
   └─ Regex patterns from 59_category_keywords.yaml

4. HEURISTICS
   ├─ Fruit detector (strawberry, grape, banana)
   ├─ Packaging detector (cup, lid, bag, tray)
   ├─ Topping detector (boba, jelly, pearl)
   ├─ Dairy detector (milk, cream, cheese)
   └─ Frozen disambiguator ("frozen fruit" vs "frozen fries")

5. SPECIAL OVERRIDES
   ├─ Tax lines → A07
   ├─ Discounts → mapped via l2_to_l1_map
   ├─ Shipping → A08
   └─ Tips → A09

6. FALLBACK
   └─ C99 Unknown (needs manual review)
```

---

## ⚡ Performance Features

### Feature 1: Modern-First Short-Circuit
- **What**: Skips legacy processing if modern layout succeeds
- **Benefit**: Reduces processing time by ~30% for modern layouts
- **Implementation**: `excel_processor.py` returns `ParseResult` with success flag

### Feature 2: Vectorized DataFrame Extraction
- **What**: Uses pandas vectorized operations instead of row-by-row iteration
- **Benefit**: 3× faster on large datasets (100+ rows)
- **Toggle**: `RECEIPTS_VECTORIZE=0` to disable

### Feature 3: Rule Loader Fast-Path
- **What**: Disables hot-reload by default (no MD5 checksums)
- **Benefit**: ~50ms saved per file, especially on network filesystems
- **Toggle**: `RECEIPTS_HOT_RELOAD=1` to re-enable for development

### Feature 4: Column-Mapping Cache
- **What**: LRU cache for column mappings and compiled regex
- **Benefit**: 30-50% faster mapping step on repeated layouts
- **Toggle**: `RECEIPTS_DISABLE_COLUMN_MAP_CACHE=1` to disable

---

## 🐛 Troubleshooting

### Common Issues

**Problem**: No items extracted from Excel  
**Solution**: Check layout rules match your Excel headers. Enable debug: `RECEIPTS_DEBUG=1`

**Problem**: Tax not extracted  
**Solution**: Ensure tax line is not in `skip_patterns` in layout YAML

**Problem**: UoM shows "UNKNOWN"  
**Solution**: Add UoM pattern to `30_uom_extraction.yaml`

**Problem**: Category is C99 (Unknown)  
**Solution**: Add keyword rule to `59_category_keywords.yaml`

**Problem**: PDF generation fails  
**Solution**: Install playwright: `pip install playwright && playwright install chromium`

### Debug Commands

```bash
# Enable full debug logging
export RECEIPTS_DEBUG=1
python -m step1_extract.main data/step1_input data/step1_output

# Force specific vendor/layout
export FORCE_VENDOR=COSTCO
export FORCE_LAYOUT=costco_layout_2

# Check rule loading
grep -r "category_l1" step1_rules/
```

---

## 📚 Documentation

### Core Documentation
- `README.md` - This file (overview, quick start, configuration)
- `docs/CATEGORY_CLASSIFICATION_GUIDE.md` - Complete category system guide
- `step1_rules/README.md` - Rule system architecture

### Feature Documentation
- `docs/FEATURE_2_VECTORIZED_EXTRACTION.md` - Vectorized extraction details
- `docs/FEATURE_3_RULE_LOADER_FAST_PATH.md` - Rule loader optimization
- `docs/FEATURE_4_COLUMN_MAP_CACHE.md` - Column mapping cache

### Implementation Notes
- `docs/AMAZON_IMPLEMENTATION_PLAN.md` - Amazon CSV-first processing
- `docs/RD_ABBREVIATIONS_STRATEGY.md` - Restaurant Depot abbreviation handling
- `docs/AMAZON_BBI_REPORTS.md` - Amazon & BBI reporting strategy

### Session Logs
- `docs/CATEGORY_IMPROVEMENTS_SESSION.md` - Category system development log
- `docs/CURRENT_STATUS.md` - Current implementation status

---

## 🔄 Workflow

This is **Step 1** of a 3-step workflow:

1. **Step 1 (This)**: Extract & Classify receipts → JSON + Reports
2. **Step 2**: Match products to database → Mapping file
3. **Step 3**: Generate Odoo SQL → Import to database

---

## 📄 License

See LICENSE file.

---

## 🙏 Acknowledgments

- **pandas**: Vectorized data processing
- **openpyxl**: Excel file reading
- **PyMuPDF/PyPDF2/pdfplumber**: PDF text extraction
- **Chart.js**: Interactive charts
- **Playwright**: PDF generation

---

## 📞 Support

For issues:
1. Check `data/step1_output/report.html` for review reasons
2. Enable debug logging: `RECEIPTS_DEBUG=1`
3. Review rule files in `step1_rules/`
4. Check documentation in `docs/`

---

**Built with ❤️ for accurate, transparent, and maintainable receipt processing.**
