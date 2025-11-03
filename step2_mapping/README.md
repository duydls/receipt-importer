# Step 2: Mapping and Normalization

Step 2 performs READ-ONLY mapping and normalization of receipt items from Step 1 output. It consumes vendor-based and instacart-based receipt data, matches products to the Odoo database, and prepares items for Step 3 SQL generation.

## Quick Start

```bash
# Run Step 2 with default settings
python -m step2_mapping.main data/step1_output data/step2_output

# With custom rules directory
python -m step2_mapping.main data/step1_output data/step2_output --rules-dir custom_rules
```

**Prerequisites:**
- Step 1 output in `data/step1_output/vendor_based/extracted_data.json` and `data/step1_output/instacart_based/extracted_data.json`
- Rules files in `step2_rules/` directory
- Database access (optional, for db_match, usage_probe, bom_protection stages)
- ProductMatcher database dump file (default: `../odoo_data/analysis/products_uom_analysis.json`)

## Overview

Step 2 executes a series of rule-based transformations defined in YAML files in the `step2_rules/` directory. It processes items through 11 stages in a defined order, transforming receipt data into a normalized format suitable for database insertion.

**Key Features:**
- ✅ Rule-based processing from YAML files
- ✅ Vendor normalization (IC-Costco vs Costco)
- ✅ Product canonicalization and matching
- ✅ Database product matching with Odoo
- ✅ UoM mapping and validation
- ✅ BoM protection checks
- ✅ Quality validation and review flagging
- ✅ Generates intermediate stage files for debugging
- ✅ READ-ONLY - does not generate SQL

## Architecture

### Components

1. **`main.py`** - Main entry point that orchestrates rule execution
2. **`rule_loader.py`** - Loads and parses YAML rule files from step2_rules/
3. **`rule_executor.py`** - Executes individual rule stages
4. **`product_matcher.py`** - Matches products to database (from existing codebase)
5. **`query_database.py`** - Database connection and query utilities

### Processing Flow

```
Step 1 Output (vendor_based/ + instacart_based/)
    ↓
Load and Combine Receipts
    ↓
Initialize ProductMatcher (once)
    ↓
Execute 11 Rule Stages in Order:
    1. inputs (normalize fields)
    2. vendor_match (normalize vendors)
    3. product_canonicalization (canonical product names)
    4. db_match (match to Odoo products)
    5. usage_probe (check product usage)
    6. uom_mapping (map UoMs)
    7. enrichment (add defaults)
    8. bom_protection (protect BoMs)
    9. validation (final checks)
    10. outputs (format output)
    11. quality_report (generate reports)
    ↓
Save mapped_items.json
```

## Usage

### Command Line

```bash
python -m step2_mapping.main <step1_output_dir> [step2_output_dir] [--rules-dir RULES_DIR]
```

**Arguments:**
- `step1_output_dir` - Step 1 output directory (must contain `vendor_based/extracted_data.json` and `instacart_based/extracted_data.json`)
- `step2_output_dir` - Step 2 output directory (default: `data/step2_output`)
- `--rules-dir` - Custom rules directory (default: `step2_rules` in parent directory)

**Example:**
```bash
python -m step2_mapping.main data/step1_output data/step2_output
```

### Programmatic Usage

```python
from step2_mapping import process_rules
from pathlib import Path

results = process_rules(
    step1_input_dir=Path('data/step1_output'),
    output_dir=Path('data/step2_output'),
    rules_dir=Path('step2_rules')
)

print(f"Processed {results['total_receipts']} receipts")
print(f"Matched {results['matched_items']} items")
print(f"Needs review: {results['needs_review']} items")
```

## Rule System

### Rule Files

Rules are defined in YAML files in `step2_rules/` directory:

- **`00_meta.yaml`** - Metadata and processing order
- **`01_inputs.yaml`** - Input normalization
- **`02_vendor_match.yaml`** - Vendor matching rules
- **`03_product_canonicalization.yaml`** - Product name canonicalization
- **`04_db_match.yaml`** - Database product matching
- **`05_usage_probe.yaml`** - Product usage analysis
- **`06_uom.yaml`** - UoM mapping and validation
- **`07_enrichment.yaml`** - Data enrichment
- **`08_bom_protection.yaml`** - BoM protection rules
- **`09_validation.yaml`** - Validation checks
- **`10_outputs.yaml`** - Output schema definition
- **`11_quality_report.yaml`** - Quality report generation

### Processing Order

The processing order is defined in `00_meta.yaml`:

```yaml
processing_order:
  - 01_inputs.yaml
  - 02_vendor_match.yaml
  - 03_product_canonicalization.yaml
  - 04_db_match.yaml
  - 05_usage_probe.yaml
  - 06_uom.yaml
  - 07_enrichment.yaml
  - 08_bom_protection.yaml
  - 09_validation.yaml
  - 10_outputs.yaml
  - 11_quality_report.yaml
```

### Rule Execution

Each rule file contains a top-level key (e.g., `vendor_match`, `db_match`) that corresponds to an execution function:

- `inputs` → `execute_inputs_stage()`
- `vendor_match` → `execute_vendor_match_stage()`
- `product_canonicalization` → `execute_product_canonicalization_stage()`
- `db_match` → `execute_db_match_stage()`
- `usage_probe` → `execute_usage_probe_stage()`
- `uom_mapping` → `execute_uom_mapping_stage()`
- `enrichment` → `execute_enrichment_stage()`
- `bom_protection` → `execute_bom_protection_stage()`
- `validation` → `execute_validation_stage()`
- `outputs` → `execute_outputs_stage()`
- `quality_report` → `execute_quality_report_stage()`

## Stage Details

### 1. Inputs Stage (01_inputs.yaml)

**Purpose:** Normalize field names and add metadata

**Actions:**
- Normalizes field names (e.g., `qty` → `quantity`, `amount` → `line_total`)
- Adds metadata (e.g., `source_step: "step1"`)

**Output:** `_stage_inputs.json`

### 2. Vendor Match Stage (02_vendor_match.yaml)

**Purpose:** Normalize vendors (IC-Costco vs Costco)

**Actions:**
- Matches vendors based on source_type, receipt text, filename
- Sets vendor_code and vendor_name
- Distinguishes Instacart vendors from direct vendors

**Rules:**
- `instacart_costco` - Matches Instacart + Costco → IC-COSTCO
- `costco` - Matches Costco → COSTCO
- `rd` - Matches Restaurant Depot → RD
- `jewel` - Matches Jewel-Osco → JEWEL
- `instacart_other` - Default for instacart-based without clear store

**Output:** `_stage_vendor.json`

### 3. Product Canonicalization Stage (03_product_canonicalization.yaml)

**Purpose:** Transform messy receipt names into canonical product keys

**Actions:**
- Normalizes product names (lowercase, strip punctuation)
- Removes store and brand words
- Applies category rules (e.g., "whole milk" → "Whole Milk")
- Applies size rules (e.g., "1 gallon" → "1 gal")
- Composes canonical product key

**Output:** `_stage_canonical.json`

### 4. DB Match Stage (04_db_match.yaml)

**Purpose:** Match canonical products to Odoo database products

**Actions:**
- Connects to Odoo database (read-only)
- Queries products, categories, UoMs, vendors
- Matches products using ProductMatcher
- Follows product_match_order:
  1. Use local odoo_product_id if exists
  2. Match by canonical_key
  3. Match by barcode
  4. Match by default_code
  5. Match by name similarity (threshold: 0.80)
- Validates purchase_ok/sale_ok flags
- Checks category consistency

**Output:** `_stage_db.json`

**Requires:** Database connection and ProductMatcher instance

### 5. Usage Probe Stage (05_usage_probe.yaml)

**Purpose:** Check how products are actually used in the system

**Actions:**
- Queries sales order lines (last 180 days)
- Queries stock moves (last 180 days)
- Queries manufacturing BoM lines
- Infers product role (bom_component, salable, inventory)
- Flags mismatches (e.g., BoM component with purchase_ok=false)

**Output:** `_stage_usage.json`

**Requires:** Database connection

### 6. UoM Mapping Stage (06_uom.yaml)

**Purpose:** Map receipt UoMs to database UoMs and validate category consistency

**Actions:**
- Normalizes receipt UoM (lowercase, aliases)
- Maps to database UoM using ProductMatcher
- Validates UoM category matches product default UoM category
- Falls back to product default UoM if mismatch
- Flags category mismatches for review

**Output:** `_stage_uom.json`

**Requires:** ProductMatcher instance

### 7. Enrichment Stage (07_enrichment.yaml)

**Purpose:** Add default values and recompute derived fields

**Actions:**
- Sets unit_price from preferred field (baseline_unit_price or unit_price)
- Sets quantity from preferred field (baseline_qty or quantity)
- Recomputes line_total if missing (unit_price * quantity)
- Applies default values (company_id: 1, currency_id: 1)

**Output:** `_stage_enriched.json`

### 8. BoM Protection Stage (08_bom_protection.yaml)

**Purpose:** Protect existing MRP BoMs from being broken by auto-mapping

**Actions:**
- Queries database for products used in BoMs
- Marks items as `bom_protected` if product is in BoM
- Prevents replacement of BoM-bound products
- Forces original product_id if mapping tries to replace BoM product

**Output:** `_stage_bom.json`

**Requires:** Database connection

### 9. Validation Stage (09_validation.yaml)

**Purpose:** Final validation checks (does not drop lines)

**Actions:**
- Checks required fields: product_id, final_uom_id, quantity, unit_price, vendor_code
- Validates quantity > 0
- Flags items missing required fields
- Flags UoM conflicts
- All items are included (marked for review if needed)

**Output:** `_stage_validated.json`

### 10. Outputs Stage (10_outputs.yaml)

**Purpose:** Format final output according to schema

**Actions:**
- Filters fields to required + optional schema
- Ensures all required fields are present (or None)
- Removes non-schema fields

**Output:** Used directly for mapped_items.json

### 11. Quality Report Stage (11_quality_report.yaml)

**Purpose:** Generate human-readable QA reports

**Actions:**
- Generates HTML quality report with views:
  - "ready" - Lines ready for Step 3
  - "need_review" - Lines requiring review
  - "bom_protected" - BoM-protected lines
- Generates CSV report with all items
- Includes summary statistics

**Output:** 
- `step2_quality_report.html`
- `step2_quality_report.csv`

## Output Files

### Final Output

- **`mapped_items.json`** - Final mapped items ready for Step 3
  - Contains required fields: product_id, product_name, final_uom_id, quantity, unit_price, vendor_code
  - Optional fields: vendor_name, canonical_product_key, line_total, etc.

### Intermediate Stage Files

All intermediate stage files are saved for debugging:

- `_stage_inputs.json` - After inputs stage
- `_stage_vendor.json` - After vendor_match stage
- `_stage_canonical.json` - After product_canonicalization stage
- `_stage_db.json` - After db_match stage
- `_stage_usage.json` - After usage_probe stage
- `_stage_uom.json` - After uom_mapping stage
- `_stage_enriched.json` - After enrichment stage
- `_stage_bom.json` - After bom_protection stage
- `_stage_validated.json` - After validation stage
- `_stage_10outputs.json` - After outputs stage
- `_stage_11qualityreport.json` - After quality_report stage

### Reports

- **`step2_quality_report.html`** - HTML quality report with filtered views
- **`step2_quality_report.csv`** - CSV export of all items with review status

## Configuration

### ProductMatcher Initialization

ProductMatcher is instantiated once at the beginning of Step 2. It requires:

- **DB Dump JSON** - Path to `products_uom_analysis.json` (default: `../odoo_data/analysis/products_uom_analysis.json`)
- Loads from `config.DB_DUMP_JSON` if available

### Database Connection

Database connection is established when needed (db_match, usage_probe, bom_protection stages). Uses:

- **Connection config:** From `config.py` or `.env` file
- **Credentials:** 
  - Environment variable: `ODOO_DB_PASSWORD`
  - `.env` file: `ODOO_DB_PASSWORD=...`
  - Interactive prompt (fallback)

**Database Access:**
- **Read-only** - Only SELECT queries
- **User:** `odoreader` (read-only user)
- **Host:** `uniuniuptown.shop:5432`

## Shared Context

All stages receive a shared context dictionary containing:

```python
context = {
    'product_matcher': ProductMatcher instance,
    'db_conn': Database connection (if opened),
    'output_dir': Path to output directory,
    'rule_loader': RuleLoader instance,
    'products_in_bom': Set of product IDs in BoMs (populated by bom_protection stage)
}
```

## Error Handling

- **Missing ProductMatcher:** Continues execution but db_match and uom_mapping stages may fail
- **Database connection errors:** Stages log warnings and continue with limited functionality
- **Missing required fields:** Items are flagged for review, not dropped
- **Rule file errors:** Stage logs error and returns items unchanged

## Debugging

### Intermediate Files

Each stage saves its output to an intermediate file. You can inspect these files to debug transformations:

```bash
# Check vendor matching
cat data/step2_output/_stage_vendor.json | jq '.[0]'

# Check canonicalization
cat data/step2_output/_stage_canonical.json | jq '.[0].canonical_product_key'

# Check database matching
cat data/step2_output/_stage_db.json | jq '.[0].product_id'
```

### Logging

Logs are saved to `data/step2_output/logs/step2.log` with detailed execution information:

- Stage execution progress
- Product matching results
- Validation warnings
- Database query errors
- Item counts per stage

## Integration with Step 1

Step 2 expects Step 1 output structure:

```
data/step1_output/
├── vendor_based/
│   └── extracted_data.json
└── instacart_based/
    └── extracted_data.json
```

Step 2 automatically:
1. Loads both vendor_based and instacart_based data
2. Combines them into a single receipt list
3. Adds `source_type` metadata to each receipt and item

## Integration with Step 3

Step 2 produces:

```
data/step2_output/
└── mapped_items.json
```

Step 3 reads `mapped_items.json` and generates SQL INSERT statements.

## Extending Step 2

### Adding a New Stage

1. Add rule file to `step2_rules/` (e.g., `12_new_stage.yaml`)
2. Add to `processing_order` in `00_meta.yaml`
3. Create execution function in `rule_executor.py`:
   ```python
   def execute_new_stage(items: List[Dict], config: Dict, context: Dict) -> List[Dict]:
       # Your logic here
       return transformed_items
   ```
4. Add to `STAGE_EXECUTORS` mapping in `rule_executor.py`

### Modifying Existing Stages

Edit the corresponding YAML rule file in `step2_rules/`. The rule executor will automatically pick up changes on the next run.

## Type Hints

All functions are fully type-hinted:

```python
def process_rules(
    step1_input_dir: Path,
    output_dir: Path,
    rules_dir: Path
) -> Dict[str, Any]:
    ...
```

## Thread Safety

Step 2 currently processes items sequentially. ThreadPoolExecutor is not used as:
- Database connections are shared across stages
- Item transformations may depend on previous stages
- Intermediate files need to be saved in order

## Performance Notes

- **ProductMatcher** is instantiated once and reused across all items
- **Database connection** is opened once and reused for db_match, usage_probe, bom_protection
- **Intermediate files** are saved for debugging but can be large (2-3MB each for 166 items)
- **Processing time:** ~1-2 seconds for 166 items on modern hardware

## See Also

- **Step 1:** `step1_extract/README.md` (if exists)
- **Step 3:** `step3_sql/README.md` (if exists)
- **Rule Files:** `step2_rules/00_meta.yaml` for processing order
- **Workflow:** `workflow.py` for integrated workflow execution

