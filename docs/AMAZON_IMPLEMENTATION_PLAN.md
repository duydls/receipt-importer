# Amazon Receipt Processing - Implementation Plan

## Current Status: ⚠️ PARTIAL (Detection rules added, processing logic needed)

### Amazon Structure Analysis

**Folder Structure:**
```
AMAZON/
├── 112-2077897-1883414/
│   └── 112-2077897-1883414.pdf
├── 114-4690641-2662621/
│   └── 114-4690641-2662621.pdf
└── orders_from_20250901_to_20250930_20251103_0941.csv
```

**Key Characteristics:**
1. **PDF Receipts**: One PDF per order, in subfolder named by Order ID (e.g., `114-4690641-2662621`)
2. **Baseline CSV**: Single CSV file with ALL orders for the period
3. **CSV Structure**: One row per ITEM (not per order like Instacart)
   - Multiple rows share the same Order ID if order has multiple items
   - Order-level fields (Order Subtotal, Order Tax, Order Total) are duplicated across rows
4. **Matching**: Order ID in PDF filename/path links to `Order ID` column in CSV

### What's Been Implemented ✅

1. **Vendor Detection** (`10_vendor_detection.yaml`)
   - Pattern matching for Amazon files
   - Patterns: "amazon", "orders_from_", "112-", "114-"
   - Vendor code: `AMAZON`
   - Source type: `amazon_based`

2. **CSV Matching Rules** (`28_amazon_csv.yaml`)
   - Column mappings for Amazon CSV structure
   - Order ID extraction from PDF path
   - Grouping strategy (group CSV rows by Order ID)
   - Field aggregation rules
   - Validation and fallback behaviors

### What Needs to Be Implemented ⚠️

#### 1. Source Type Handler in `main.py`

**Current Issue**: System only handles `vendor_based` and `instacart_based`. Need to add `amazon_based`.

**Required Changes**:
```python
def determine_source_type(file_path: Path, input_dir: Path) -> str:
    """Returns: 'vendor_based', 'instacart_based', or 'amazon_based'"""
    # Add Amazon detection
    if 'amazon' in folder_name.lower() or file_path.match('*/###-#######-#######/*'):
        return 'amazon_based'
    # ... existing logic
```

**In `process_files()`**:
```python
# Add amazon_based tracking
amazon_based_files = [f for f in all_files if determine_source_type(f, input_dir) == 'amazon_based']

# Process amazon_based files
amazon_based_data = {}
if amazon_based_files:
    logger.info("Processing amazon-based receipts...")
    # Call Amazon processor
```

#### 2. Amazon CSV Matcher (new file: `amazon_csv_matcher.py`)

Similar to `instacart_csv_matcher.py` but with key differences:

**Key Differences from Instacart**:
- **Instacart**: One CSV row = one order, match by filename pattern
- **Amazon**: Multiple CSV rows = one order, match by Order ID, group rows

**Required Functions**:
```python
def find_amazon_csv(pdf_path: Path) -> Optional[Path]:
    """Find Amazon CSV in parent AMAZON folder"""
    # Look for orders_from_*.csv in AMAZON/ folder
    
def extract_order_id_from_path(pdf_path: Path) -> Optional[str]:
    """Extract Order ID from path like '114-4690641-2662621/114-4690641-2662621.pdf'"""
    # Regex: \d{3}-\d{7}-\d{7}
    
def load_and_group_csv(csv_path: Path, rule_loader) -> Dict[str, List[Dict]]:
    """
    Load CSV and group rows by Order ID
    Returns: {order_id: [item1, item2, ...]}
    """
    # Read CSV
    # Group by 'Order ID' column
    # Return dict
    
def match_pdf_to_csv(pdf_path: Path, csv_data: Dict, rule_loader) -> Optional[Dict]:
    """
    Match PDF to CSV data and return enriched receipt dict
    
    Returns:
        {
            'order_id': str,
            'order_date': str,
            'vendor': 'AMAZON',
            'subtotal': float,
            'tax': float,
            'total': float,
            'items': [
                {
                    'product_name': str,
                    'quantity': float,
                    'unit_price': float,
                    'total_price': float,
                    'asin': str,
                    'brand': str,
                    ...
                }
            ],
            'csv_linked': True,
            'source': 'amazon_csv'
        }
    """
```

#### 3. Amazon PDF Processor Integration

**In `receipt_processor.py` or new `amazon_processor.py`**:
```python
def process_amazon_pdf(pdf_path: Path, rule_loader, csv_data=None) -> Dict:
    """
    Process Amazon PDF receipt
    
    If csv_data provided:
        - Use CSV data as authoritative source
        - PDF validates/supplements
    Else:
        - Extract what we can from PDF
        - Mark as needs_review
    """
    if csv_data:
        # CSV-first approach (like Instacart)
        receipt_data = csv_data.copy()
        # Extract additional info from PDF if needed
    else:
        # PDF-only approach
        # Extract from PDF text
        receipt_data = parse_amazon_pdf_text(pdf_path)
        receipt_data['needs_review'] = True
        receipt_data['review_reasons'] = ['No CSV baseline found']
    
    return receipt_data
```

#### 4. Output Structure

Create separate output folder similar to Instacart:
```
data/step1_output/
├── vendor_based/
├── instacart_based/
└── amazon_based/          # NEW
    ├── extracted_data.json
    └── report.html
```

#### 5. Rule Loader Integration

**In `rule_loader.py`**:
```python
def get_amazon_csv_rules(self) -> Dict[str, Any]:
    """Load Amazon CSV matching rules from 28_amazon_csv.yaml"""
    return self.load_rule_file_by_name('28_amazon_csv.yaml')
```

### Implementation Priority

**Phase 1: Minimum Viable Product** (1-2 hours)
1. Add `amazon_based` source type detection in `main.py`
2. Create basic `amazon_csv_matcher.py` with Order ID matching
3. Basic CSV-to-receipt conversion (items, totals)
4. Output to `amazon_based/` folder

**Phase 2: Enhanced Processing** (1-2 hours)
5. PDF text extraction for validation
6. Handle missing CSV gracefully
7. Validation (totals match)
8. HTML report generation

**Phase 3: Polish** (0.5-1 hour)
9. Error handling and edge cases
10. Unit tests
11. Documentation

### Testing Strategy

**Test Cases**:
1. ✅ **Order with 1 item**: Verify single row → single item
2. ✅ **Order with multiple items**: Verify grouping (Order `114-0652295-0417840` has 2 items)
3. ✅ **All 8 PDFs**: Process complete batch
4. ⚠️ **Missing CSV**: Ensure graceful fallback
5. ⚠️ **Order ID not in CSV**: Flag for review
6. ⚠️ **Total validation**: Sum of items = order total

### Sample CSV Data Analysis

**Order `114-4690641-2662621`** (1 item):
- Item: Torani Puremade Sauce, Caramel (Pack of 4)
- Quantity: 1
- Price: $19.12
- Tax: $0.00
- Total: $19.12

**Order `114-0652295-0417840`** (2 items):
- Item 1: Premium Raw Unsalted Sliced Almonds × 2 = $43.02
- Item 2: Thai Kitchen Coconut Milk × 1 = $15.16
- Order Total: $58.18
- Tax: $0.00

### CSV Column Mapping

**Order-Level** (same across all rows for an order):
- `Order ID` → order_id
- `Order Date` → order_date
- `Order Subtotal` → subtotal
- `Order Tax` → tax
- `Order Net Total` → total

**Item-Level** (unique per row):
- `Title` → product_name
- `Item Quantity` → quantity
- `Purchase PPU` → unit_price
- `Item Subtotal` → line_subtotal
- `Item Tax` → line_tax
- `Item Net Total` → total_price
- `ASIN` → asin
- `Brand` → brand
- `Amazon-Internal Product Category` → category

### Recommendations

1. **Reuse Instacart Pattern**: The CSV-first approach from Instacart works well here
2. **Grouping is Key**: Must group CSV rows by Order ID before matching to PDF
3. **Start Simple**: Get basic CSV → JSON working first, then add PDF validation
4. **Test Incrementally**: Process one order first, then expand to full batch

### Next Steps

1. Implement Phase 1 (amazon_based source type + CSV matcher)
2. Test with sample orders
3. Iterate based on results
4. Document any edge cases discovered

---

**Status**: Ready for implementation
**Estimated Time**: 3-5 hours for full implementation
**Complexity**: Medium (similar to Instacart but with grouping requirement)

