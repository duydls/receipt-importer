# Category Classification System - User Guide

## Overview

The category classification system automatically categorizes receipt line items into:
- **L1 (Level 1)**: Accounting categories for P&L and financial reporting
- **L2 (Level 2)**: Operational categories for inventory and day-to-day tracking

**Key Principle**: All category mappings are defined in YAML rule files. There is NO hardcoded logic in Python code.

---

## Rule Files Location

All category rules are in: `step1_rules/`

| File | Purpose |
|------|---------|
| `55_categories_l1.yaml` | L1 accounting categories + L2→L1 mapping + special overrides |
| `56_categories_l2.yaml` | L2 operational categories with descriptions and hints |
| `57_category_maps_instacart.yaml` | Instacart-specific classification rules |
| `58_category_maps_amazon.yaml` | Amazon-specific classification rules |
| `59_category_keywords.yaml` | Global keywords, heuristics, and pipeline settings |

---

## How to Update Category Mappings

### Example 1: Change which L1 category a product type goes to

**Scenario**: Move "Office Supplies" from A06 to A04

**File**: `55_categories_l1.yaml`

```yaml
l2_to_l1_map:
  C60: A04  # Changed from A06 to A04
```

### Example 2: Add a new product pattern

**Scenario**: Classify "energy drinks" as C01 (Tea & Coffee)

**File**: `59_category_keywords.yaml`

```yaml
keyword_rules:
  - include_regex: '(?i)\b(energy drink|red bull|monster)\b'
    map_to_l2: C01
    priority: 90
    hints: ['Energy drinks']
```

### Example 3: Change tax override category

**Scenario**: Tax should go to a different L2 category

**File**: `55_categories_l1.yaml`

```yaml
tax_overrides:
  description: Tax override
  map_to_l2: C70  # Change this value
  patterns:
    - '(?i)\btax\b'
```

### Example 4: Add Amazon-specific pattern

**Scenario**: Classify items with "kombucha" in title as C01 (Tea & Coffee)

**File**: `58_category_maps_amazon.yaml`

```yaml
rules:
  - match:
      item_title_regex: '(?i)\b(kombucha)\b'
    map_to_l2: C01
    priority: 90
    notes: Kombucha beverages
```

### Example 5: Add new L2 category

**Step 1**: Add to `56_categories_l2.yaml`

```yaml
l2_categories:
  - id: C16
    name: Specialty Beverages
    description: Specialty and artisan beverages
    examples:
      - Kombucha
      - Cold brew
    synonyms:
      - kombucha
      - cold brew
    vendor_hints:
      - title_contains: ['kombucha', 'cold brew']
```

**Step 2**: Add L2→L1 mapping in `55_categories_l1.yaml`

```yaml
l2_to_l1_map:
  C16: A01  # Maps to COGS-Ingredients
```

**Step 3**: Add classification rules in appropriate mapping files

---

## Classification Pipeline

Items are classified in this order (defined in `59_category_keywords.yaml`):

1. **source_map** - Instacart/Amazon specific rules (confidence: 0.95)
2. **vendor_overrides** - Vendor-specific hints (confidence: 0.90)
3. **keywords** - Global keyword matching (confidence: 0.80)
4. **heuristics** - Smart classifiers (fruit, packaging, etc.) (confidence: 0.70)
5. **overrides** - Tax/discount/shipping/tips (confidence: 1.00)
6. **fallback** - C99 Unknown (confidence: 0.20)

Items with confidence < 0.60 are flagged for review.

---

## Category Output Fields

Each item gets these added fields:

```json
{
  "l2_category": "C08",
  "l2_category_name": "Toppings & Jellies",
  "l1_category": "A01",
  "l1_category_name": "COGS–Ingredients",
  "category_source": "instacart_map",
  "category_rule_id": "instacart_rule_15",
  "category_confidence": 0.95,
  "needs_category_review": false
}
```

---

## Testing Changes

After editing YAML files:

1. **No code restart needed** - Rules are loaded fresh each run
2. **Rerun Step 1**:
   ```bash
   python -m step1_extract.main data/step1_input data/step1_output
   ```
3. **Check reports** - Category info appears in all HTML reports
4. **Review flagged items** - Look for `needs_category_review: true`

---

## Best Practices

### ✅ DO:
- Edit YAML files to change behavior
- Use descriptive rule notes/hints
- Test with sample data
- Set appropriate confidence levels
- Use regex for flexible matching

### ❌ DON'T:
- Hardcode category IDs in Python code
- Skip the L2→L1 mapping step
- Use overly broad regex patterns
- Set all rules to priority 100
- Forget to test after changes

---

## Common Patterns

### Match by vendor
```yaml
- match:
    vendor_code: 'COSTCO'
    text_contains: ['kirkland']
  map_to_l2: C01
```

### Match by department (Instacart)
```yaml
- match:
    department: 'produce'
    text_contains: ['organic']
  map_to_l2: C09
```

### Match by title regex (Amazon)
```yaml
- match:
    item_title_regex: '(?i)\b(pack of \d+)\b'
  map_to_l2: C20
```

### Exclude false positives
```yaml
- include_regex: '(?i)\bbag\b'
  exclude_regex: '(?i)\b(tea bag|trash bag)\b'
  map_to_l2: C21
```

---

## Troubleshooting

### Items going to C99 (Unknown)
1. Check if patterns match (case-insensitive)
2. Add more keyword rules
3. Lower priority of competing rules
4. Check confidence threshold

### Wrong L1 category
1. Check L2→L1 mapping in `55_categories_l1.yaml`
2. Verify L2 category is correct first

### Rules not working
1. Check YAML syntax (indentation!)
2. Test regex patterns separately
3. Check pipeline order
4. Verify rule priority

---

## Support

For questions or issues:
1. Check this guide
2. Review YAML file comments
3. Check logs for classification decisions
4. Test with `RECEIPTS_DEBUG=1` for verbose output

---

**Remember**: All mappings live in YAML files. Never hardcode category IDs in Python!

