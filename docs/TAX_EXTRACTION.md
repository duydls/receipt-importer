# Tax Extraction

This document describes how tax extraction works across all vendors.

## Overview

The system extracts tax amounts from receipts using multiple patterns to handle different formats and vendor-specific variations.

## Tax Patterns

### Standard Tax Patterns

The system recognizes the following tax patterns (defined in vendor-specific YAML files):

- `Tax` - Generic tax line
- `Sales Tax` - Sales tax
- `Tax Amount` - Tax amount field
- `Grocery Tax` - Grocery tax (handled globally for all vendors)

### Global "Grocery Tax" Handling

**"Grocery Tax" is treated as tax for all orders**, not just specific vendors. This is handled in `step1_extract/pdf_processor_unified.py` with two patterns:

1. **Summary Format**: `Grocery Tax $ 0.11`
   - Pattern: `^\s*Grocery\s+Tax\s+\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})`
   - Matches when `$` appears immediately after "Tax"

2. **Item-like Format**: `Grocery Tax 0.11 Units $ 1.00 $ 0.11`
   - Pattern: `^\s*Grocery\s+Tax\s+.*?\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})\s*$`
   - Extracts the last `$` amount from the end of the line
   - Only used if summary format didn't match (to avoid double counting)

### Vendor-Specific Tax Patterns

Each vendor can define additional tax patterns in their YAML file (e.g., `step1_rules/32_odoo_pdf.yaml`):

```yaml
total_patterns:
  tax:
    pattern: "(?im)^\\s*(?:Tax|Sales\\s+Tax|Tax\\s+Amount)(?:\\s+\\d+(?:\\.\\d+)?%)?\\s*\\$?\\s*(\\d{1,3}(?:,\\d{3})*\\.\\d{2})"
    group: 1
    case_insensitive: true
```

### Processing Order

Tax extraction follows this order:

1. **Main tax pattern** (from vendor YAML) - can match multiple times and sum them
2. **Grocery Tax patterns** (global) - summary format first, then item-like format
3. **Water tax pattern** (if defined in YAML)
4. **Combined tax pattern** (fallback if main pattern found nothing)

### Examples

#### Odoo Purchase Orders

- **P00004**: `Grocery Tax 0.11 Units $ 1.00 $ 0.11` → Extracts `$0.11` (item-like format)
- **P00005**: `Tax 10.25% $ 11.27` → Extracts `$11.27` (standard tax pattern)

#### Other Vendors

Any receipt containing "Grocery Tax" will have the tax amount extracted, regardless of vendor.

## Implementation

The tax extraction logic is in `step1_extract/pdf_processor_unified.py` in the `_extract_totals_from_text` method:

```python
# Try grocery tax pattern (for all vendors - handles both summary and item-like formats)
# Pattern 1: Summary format "Grocery Tax $ 0.11"
grocery_tax_pattern1 = r'(?im)^\s*Grocery\s+Tax\s+\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})(?:\s|$)'
# Pattern 2: Item-like format "Grocery Tax 0.11 Units $ 1.00 $ 0.11"
grocery_tax_pattern2 = r'(?im)^\s*Grocery\s+Tax\s+.*?\$\s*(\d{1,3}(?:,\d{3})*\.\d{2})\s*$'
```

## Notes

- All tax amounts are summed if multiple tax lines are found
- Tax extraction is case-insensitive
- The system handles thousands separators (commas) in amounts
- Negative tax amounts (in parentheses) are converted to negative values

