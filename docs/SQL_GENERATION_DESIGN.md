# Design: Streamlined SQL Generation from Receipt Processing

## Current State

### Existing Workflow
```
Step 1: Extract Receipts
  ↓
Step 2: Manual Review (optional)
  ↓
Step 3: Product Matching
  ↓
Step 4: Generate SQL
```

### Current SQL Generation
- `step4_sql/generate_receipt_sql.py` - Requires Step 3 mapped data
- `scripts/generate_purchase_order_sql.py` - Standalone, reads Step 1 output directly

### Key Insight
**Step 1 already matches items to Odoo!** We have:
- `standard_name` from Odoo
- `odoo_product_id` for each matched item
- `l1_category` and `l2_category` from Odoo
- All fees from Odoo purchase orders

**We can skip Step 3 and generate SQL directly from Step 1 output!**

---

## Proposed Design: Direct SQL Generation

### Simplified Workflow
```
Step 1: Extract Receipts + Odoo Matching
  ↓
SQL Generation: Direct from Step 1 output
```

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Step 1 Output (extracted_data.json)      │
│  - Receipts with items                                  │
│  - Items matched to Odoo (standard_name, odoo_product_id) │
│  - Categories from Odoo                                 │
│  - Fees from Odoo                                       │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│         SQL Generator (New/Enhanced)                    │
│                                                          │
│  1. Load Step 1 output                                  │
│  2. Validate Odoo matches (all items should have IDs)    │
│  3. Generate Purchase Order SQL                         │
│  4. Generate Purchase Order Line SQL                    │
│  5. Handle UoM conversions                              │
│  6. Add fees as line items                              │
│  7. Generate rollback SQL                               │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              SQL Files (Ready for Odoo)                 │
│  - purchase_order_{receipt_id}.sql                     │
│  - purchase_order_{receipt_id}_rollback.sql             │
└─────────────────────────────────────────────────────────┘
```

---

## Component Design

### 1. SQL Generator Class

```python
class DirectSQLGenerator:
    """
    Generate SQL directly from Step 1 output
    Uses Odoo matching data already in receipt items
    
    Validates that all products and UoMs exist in Odoo before generating SQL
    """
    
    def __init__(self, db_connection):
        self.conn = db_connection
        self.po_id_sequence = self._get_next_po_id()
        self.po_line_id_sequence = self._get_next_po_line_id()
        self.missing_products = []
        self.missing_uoms = []
    
    def validate_before_generation(
        self,
        step1_output_dir: Path
    ) -> Tuple[bool, Dict[str, List[str]]]:
        """
        Validate all products and UoMs exist in Odoo database
        
        Returns:
            (is_valid, missing_items_dict)
            missing_items_dict: {
                'missing_products': [...],
                'missing_uoms': [...],
                'missing_vendors': [...]
            }
        """
        pass
    
    def generate_sql_from_step1_output(
        self, 
        step1_output_dir: Path,
        output_dir: Path,
        skip_validation: bool = False
    ) -> List[Path]:
        """
        Main entry point: Generate SQL for all receipts in Step 1 output
        
        Args:
            step1_output_dir: Directory containing Step 1 extracted_data.json files
            output_dir: Directory to save SQL files
            skip_validation: If True, skip validation (not recommended)
            
        Returns:
            List of generated SQL file paths
            
        Raises:
            ValidationError: If products/UoMs/vendors are missing
        """
        # Step 1: Validate all required data exists
        if not skip_validation:
            is_valid, missing = self.validate_before_generation(step1_output_dir)
            if not is_valid:
                self._report_missing_items(missing)
                raise ValidationError("Missing products/UoMs/vendors. Please create them first.")
        
        # Step 2: Generate SQL
        pass
    
    def generate_sql_for_receipt(
        self,
        receipt_id: str,
        receipt_data: Dict,
        po_id: int
    ) -> Tuple[str, str]:
        """
        Generate SQL for one receipt
        
        Returns:
            (main_sql, rollback_sql) tuple
        """
        pass
```

### 2. Purchase Order Generation

```python
def generate_purchase_order_sql(
    receipt_id: str,
    receipt_data: Dict,
    po_id: int,
    conn
) -> str:
    """
    Generate SQL INSERT for purchase_order table
    
    Uses:
    - receipt_data['vendor'] → lookup res_partner
    - receipt_data['transaction_date'] → date_order
    - receipt_data['total'] → amount_total
    - receipt_data['tax'] → amount_tax
    - receipt_data['subtotal'] → amount_untaxed
    """
    # Key fields:
    # - name: receipt_id or generated PO name
    # - partner_id: Lookup from res_partner by vendor name
    # - date_order: transaction_date
    # - state: 'draft' (user confirms in UI)
    # - amount_total, amount_tax, amount_untaxed
    pass
```

### 3. Purchase Order Line Generation

```python
def generate_purchase_order_line_sql(
    item: Dict,
    po_line_id: int,
    po_id: int,
    sequence: int,
    conn
) -> Optional[str]:
    """
    Generate SQL INSERT for purchase_order_line table
    
    Uses data already in item from Step 1:
    - item['odoo_product_id'] → product_id (convert to product_product ID)
    - item['quantity'] → product_qty
    - item['unit_price'] → price_unit
    - item['total_price'] → price_subtotal
    - item['purchase_uom'] → product_uom (lookup UoM ID)
    - item['standard_name'] → name (Odoo product name)
    """
    # Key validations:
    # 1. Must have odoo_product_id
    # 2. Must have valid quantity > 0
    # 3. Must have valid price
    # 4. UoM must be valid (lookup from database)
    pass
```

### 4. Fee Handling

```python
def generate_fee_lines(
    receipt_data: Dict,
    po_id: int,
    po_line_id_start: int,
    conn
) -> List[str]:
    """
    Generate SQL for fee items (tips, service fees, taxes, etc.)
    
    Fees are already in receipt_data['items'] with is_fee=True
    Each fee becomes a purchase_order_line
    """
    # Fees from Step 1:
    # - Already matched to Odoo (if available)
    # - Have standard_name, odoo_product_id
    # - Have fee_type (tip, service_fee, tax, etc.)
    pass
```

### 5. UoM Conversion

```python
def convert_uom_for_purchase_order(
    item: Dict,
    conn
) -> Tuple[float, int]:
    """
    Convert item UoM to product's default UoM if needed
    
    Returns:
        (converted_quantity, uom_id)
    """
    # Logic:
    # 1. Get product's default UoM from database
    # 2. If item UoM matches product UoM category → use as-is
    # 3. If different category → convert quantity
    # 4. Handle special cases (fruit weight → units, etc.)
    pass
```

---

## Validation Flow

```
Step 1 Output
    ↓
┌─────────────────────────────────────┐
│  Validation Phase                  │
│  1. Check all products exist        │
│  2. Check all UoMs exist            │
│  3. Check all vendors exist         │
└─────────────────────────────────────┘
    ↓
    ├─→ All Valid? ──YES──→ Generate SQL
    │
    └─→ Missing Items? ──NO──→
        │
        ▼
┌─────────────────────────────────────┐
│  Report Missing Items               │
│  - Console warnings                 │
│  - CSV report                       │
│  - Stop SQL generation              │
└─────────────────────────────────────┘
    │
    ▼
User creates missing items in Odoo
    │
    ▼
Re-run validation → Generate SQL
```

## Data Flow

### Input: Step 1 Output Structure
```json
{
  "receipt_id": {
    "vendor": "Costco",
    "transaction_date": "2025-10-15",
    "total": 123.45,
    "subtotal": 100.00,
    "tax": 10.00,
    "items": [
      {
        "product_name": "Chicken Breast",
        "standard_name": "Chicken Breast",  // From Odoo
        "odoo_product_id": 12345,           // From Odoo
        "quantity": 10.0,
        "purchase_uom": "lb",
        "unit_price": 5.99,
        "total_price": 59.90,
        "l1_category": "A02",
        "l2_category": "C20"
      },
      {
        "product_name": "Grocery Tip",
        "standard_name": "Grocery Tip",
        "odoo_product_id": 67890,
        "is_fee": true,
        "fee_type": "tip",
        "quantity": 1.0,
        "total_price": 5.00
      }
    ]
  }
}
```

### Output: SQL File Structure
```sql
-- ================================================
-- Purchase Order: P00123
-- Receipt ID: receipt_123
-- Vendor: Costco
-- Date: 2025-10-15
-- Total: $123.45
-- ================================================

BEGIN;

-- Purchase Order Header
INSERT INTO purchase_order (...)
SELECT 
    123,  -- po_id
    id,   -- partner_id (from res_partner lookup)
    ...
FROM res_partner
WHERE name = 'Costco'
LIMIT 1;

-- Purchase Order Lines
INSERT INTO purchase_order_line (...)
VALUES (...);

-- Fees
INSERT INTO purchase_order_line (...)
VALUES (...);

COMMIT;
```

---

## Key Features

### 1. **Validation Before SQL Generation**

#### A. Validate Products Exist in Odoo
```python
def validate_products_exist(
    items: List[Dict],
    conn
) -> Tuple[List[Dict], List[Dict]]:
    """
    Check if all product IDs exist in Odoo database
    
    Returns:
        (valid_items, missing_items)
        missing_items: [{'product_id': ..., 'product_name': ..., 'receipt_id': ...}]
    """
    valid_items = []
    missing_items = []
    
    product_ids = [item.get('odoo_product_id') for item in items 
                   if item.get('odoo_product_id') and not item.get('is_fee')]
    
    if not product_ids:
        return items, []
    
    # Query database for existing products
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT id 
            FROM product_product 
            WHERE id = ANY(%s)
        """, (product_ids,))
        existing_ids = {row[0] for row in cur.fetchall()}
    
    # Check each item
    for item in items:
        if item.get('is_fee'):
            valid_items.append(item)
            continue
            
        product_id = item.get('odoo_product_id')
        if not product_id:
            missing_items.append({
                'product_id': None,
                'product_name': item.get('product_name', 'Unknown'),
                'receipt_id': item.get('_receipt_id', 'Unknown'),
                'reason': 'No odoo_product_id in receipt data'
            })
        elif product_id not in existing_ids:
            missing_items.append({
                'product_id': product_id,
                'product_name': item.get('standard_name') or item.get('product_name', 'Unknown'),
                'receipt_id': item.get('_receipt_id', 'Unknown'),
                'reason': f'Product ID {product_id} not found in Odoo database'
            })
        else:
            valid_items.append(item)
    
    return valid_items, missing_items
```

#### B. Validate UoMs Exist in Odoo
```python
def validate_uoms_exist(
    items: List[Dict],
    conn
) -> Tuple[List[str], List[Dict]]:
    """
    Check if all UoMs exist in Odoo database
    
    Returns:
        (valid_uoms, missing_uoms)
        missing_uoms: [{'uom_name': ..., 'used_by': [...]}]
    """
    valid_uoms = []
    missing_uoms = []
    
    # Collect all unique UoM names from items
    uom_names = set()
    uom_usage = defaultdict(list)  # Track which items use each UoM
    
    for item in items:
        uom_name = item.get('purchase_uom', '').strip()
        if uom_name:
            uom_names.add(uom_name)
            uom_usage[uom_name].append({
                'product_name': item.get('product_name', 'Unknown'),
                'receipt_id': item.get('_receipt_id', 'Unknown')
            })
    
    if not uom_names:
        return [], []
    
    # Query database for existing UoMs
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT name::text as uom_name
            FROM uom_uom
            WHERE name::text = ANY(%s)
        """, (list(uom_names),))
        existing_uoms = {extract_english_text(row[0]) for row in cur.fetchall()}
    
    # Check each UoM
    for uom_name in uom_names:
        normalized_name = normalize_uom_name(uom_name)
        if normalized_name not in existing_uoms:
            missing_uoms.append({
                'uom_name': uom_name,
                'normalized_name': normalized_name,
                'used_by': uom_usage[uom_name],
                'count': len(uom_usage[uom_name])
            })
        else:
            valid_uoms.append(uom_name)
    
    return valid_uoms, missing_uoms
```

#### C. Validate Vendors/Partners Exist
```python
def validate_vendors_exist(
    receipts_data: Dict[str, Dict],
    conn
) -> Tuple[List[str], List[Dict]]:
    """
    Check if all vendors exist in res_partner table
    
    Returns:
        (valid_vendors, missing_vendors)
    """
    valid_vendors = []
    missing_vendors = []
    
    # Collect all unique vendor names
    vendor_names = set()
    vendor_usage = defaultdict(list)
    
    for receipt_id, receipt_data in receipts_data.items():
        vendor = receipt_data.get('vendor', '').strip()
        if vendor:
            vendor_names.add(vendor)
            vendor_usage[vendor].append(receipt_id)
    
    if not vendor_names:
        return [], []
    
    # Query database for existing partners
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT name::text as partner_name
            FROM res_partner
            WHERE name::text = ANY(%s)
        """, (list(vendor_names),))
        existing_vendors = {extract_english_text(row[0]) for row in cur.fetchall()}
    
    # Check each vendor
    for vendor_name in vendor_names:
        normalized_name = normalize_vendor_name(vendor_name)
        if normalized_name not in existing_vendors:
            missing_vendors.append({
                'vendor_name': vendor_name,
                'normalized_name': normalized_name,
                'used_by_receipts': vendor_usage[vendor_name],
                'count': len(vendor_usage[vendor_name])
            })
        else:
            valid_vendors.append(vendor_name)
    
    return valid_vendors, missing_vendors
```

#### D. Comprehensive Validation
```python
def validate_before_generation(
    self,
    step1_output_dir: Path
) -> Tuple[bool, Dict[str, List]]:
    """
    Comprehensive validation before SQL generation
    
    Returns:
        (is_valid, missing_items)
        missing_items: {
            'missing_products': [...],
            'missing_uoms': [...],
            'missing_vendors': [...],
            'items_without_product_id': [...]
        }
    """
    missing_items = {
        'missing_products': [],
        'missing_uoms': [],
        'missing_vendors': [],
        'items_without_product_id': []
    }
    
    # Load all receipts from Step 1 output
    all_receipts = self._load_step1_output(step1_output_dir)
    all_items = []
    
    for receipt_id, receipt_data in all_receipts.items():
        items = receipt_data.get('items', [])
        for item in items:
            item['_receipt_id'] = receipt_id
            all_items.append(item)
    
    # Validate products
    valid_items, missing_products = validate_products_exist(all_items, self.conn)
    missing_items['missing_products'] = missing_products
    missing_items['items_without_product_id'] = [
        p for p in missing_products if p['product_id'] is None
    ]
    
    # Validate UoMs
    valid_uoms, missing_uoms = validate_uoms_exist(valid_items, self.conn)
    missing_items['missing_uoms'] = missing_uoms
    
    # Validate vendors
    valid_vendors, missing_vendors = validate_vendors_exist(all_receipts, self.conn)
    missing_items['missing_vendors'] = missing_vendors
    
    # Check if validation passed
    is_valid = (
        len(missing_products) == 0 and
        len(missing_uoms) == 0 and
        len(missing_vendors) == 0
    )
    
    return is_valid, missing_items
```

#### E. Report Missing Items
```python
def _report_missing_items(self, missing_items: Dict[str, List]):
    """
    Generate detailed report of missing items
    
    Creates:
    - Console output with clear warnings
    - CSV file with missing items for easy review
    - Summary report
    """
    print("\n" + "="*80)
    print("⚠️  VALIDATION FAILED: Missing Items in Odoo Database")
    print("="*80)
    
    # Missing Products
    if missing_items['missing_products']:
        print(f"\n❌ Missing Products: {len(missing_items['missing_products'])}")
        print("   Please create these products in Odoo first:")
        for item in missing_items['missing_products'][:10]:
            print(f"     - Product ID: {item.get('product_id', 'N/A')}")
            print(f"       Name: {item.get('product_name', 'Unknown')}")
            print(f"       Receipt: {item.get('receipt_id', 'Unknown')}")
            print(f"       Reason: {item.get('reason', 'Not found')}")
            print()
        if len(missing_items['missing_products']) > 10:
            print(f"     ... and {len(missing_items['missing_products']) - 10} more")
    
    # Missing UoMs
    if missing_items['missing_uoms']:
        print(f"\n❌ Missing UoMs: {len(missing_items['missing_uoms'])}")
        print("   Please create these UoMs in Odoo first:")
        for uom in missing_items['missing_uoms'][:10]:
            print(f"     - UoM Name: {uom.get('uom_name', 'Unknown')}")
            print(f"       Used by {uom.get('count', 0)} items")
            print(f"       Sample items: {', '.join([i['product_name'][:30] for i in uom.get('used_by', [])[:3]])}")
            print()
        if len(missing_items['missing_uoms']) > 10:
            print(f"     ... and {len(missing_items['missing_uoms']) - 10} more")
    
    # Missing Vendors
    if missing_items['missing_vendors']:
        print(f"\n❌ Missing Vendors: {len(missing_items['missing_vendors'])}")
        print("   Please create these vendors/partners in Odoo first:")
        for vendor in missing_items['missing_vendors']:
            print(f"     - Vendor Name: {vendor.get('vendor_name', 'Unknown')}")
            print(f"       Used by {vendor.get('count', 0)} receipts")
            print(f"       Receipts: {', '.join(vendor.get('used_by_receipts', [])[:5])}")
            print()
    
    # Generate CSV report
    self._generate_missing_items_report(missing_items)
    
    print("\n" + "="*80)
    print("📋 Detailed report saved to: data/sql/missing_items_report.csv")
    print("="*80)
    print("\n💡 Next Steps:")
    print("   1. Review the missing items report")
    print("   2. Create missing products/UoMs/vendors in Odoo")
    print("   3. Re-run SQL generation")
    print()

def _generate_missing_items_report(self, missing_items: Dict[str, List]):
    """Generate CSV report of missing items"""
    import pandas as pd
    
    report_data = []
    
    # Add missing products
    for item in missing_items['missing_products']:
        report_data.append({
            'Type': 'Missing Product',
            'ID': item.get('product_id', 'N/A'),
            'Name': item.get('product_name', 'Unknown'),
            'Receipt ID': item.get('receipt_id', 'Unknown'),
            'Reason': item.get('reason', 'Not found')
        })
    
    # Add missing UoMs
    for uom in missing_items['missing_uoms']:
        for usage in uom.get('used_by', []):
            report_data.append({
                'Type': 'Missing UoM',
                'ID': 'N/A',
                'Name': uom.get('uom_name', 'Unknown'),
                'Receipt ID': usage.get('receipt_id', 'Unknown'),
                'Reason': f"UoM not found in Odoo database"
            })
    
    # Add missing vendors
    for vendor in missing_items['missing_vendors']:
        for receipt_id in vendor.get('used_by_receipts', []):
            report_data.append({
                'Type': 'Missing Vendor',
                'ID': 'N/A',
                'Name': vendor.get('vendor_name', 'Unknown'),
                'Receipt ID': receipt_id,
                'Reason': 'Vendor/Partner not found in Odoo database'
            })
    
    if report_data:
        df = pd.DataFrame(report_data)
        output_file = Path('data/sql/missing_items_report.csv')
        output_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_file, index=False)
```

### 2. **ID Management**
```python
def get_next_po_id(conn, check_existing_sql: bool = True) -> int:
    """
    Get next available purchase_order ID
    
    Checks:
    1. Database sequence
    2. Existing SQL files (to avoid conflicts)
    """
    pass

def get_next_po_line_id(conn, check_existing_sql: bool = True) -> int:
    """Get next available purchase_order_line ID"""
    pass
```

### 3. **Vendor/Partner Lookup**
```python
def lookup_vendor_partner_id(
    vendor_name: str,
    conn
) -> Optional[int]:
    """
    Lookup res_partner ID by vendor name
    
    Handles:
    - Exact name match
    - Instacart format: "IC-{store_name}"
    - Vendor aliases
    """
    pass
```

### 4. **UoM Lookup and Conversion**
```python
def lookup_uom_id(
    uom_name: str,
    conn
) -> Optional[Dict]:
    """
    Lookup UoM ID and category from database
    
    Returns:
        {
            'id': uom_id,
            'name': uom_name,
            'category_id': category_id,
            'factor': conversion_factor
        }
    """
    pass

def convert_quantity(
    quantity: float,
    from_uom: Dict,
    to_uom: Dict
) -> float:
    """
    Convert quantity between UoMs in same category
    """
    pass
```

### 5. **Product ID Resolution**
```python
def get_product_product_id(
    product_id: int,
    conn
) -> Optional[int]:
    """
    Convert product_template ID to product_product ID
    
    purchase_order_line.product_id must be product_product ID
    """
    pass
```

---

## Error Handling

### Missing Odoo Product IDs
```python
def handle_unmatched_items(
    receipt_data: Dict
) -> Tuple[List[Dict], List[Dict]]:
    """
    Separate matched and unmatched items
    
    Returns:
        (matched_items, unmatched_items)
    """
    matched = []
    unmatched = []
    
    for item in receipt_data.get('items', []):
        if item.get('is_fee'):
            # Fees can be added even without product_id (as service products)
            matched.append(item)
        elif item.get('odoo_product_id'):
            matched.append(item)
        else:
            unmatched.append(item)
    
    return matched, unmatched
```

### Options for Unmatched Items
1. **Skip**: Don't include in SQL (current approach)
2. **Create Placeholder**: Create product on-the-fly (advanced)
3. **Flag for Review**: Generate SQL with comments marking issues

---

## SQL File Structure

### Main SQL File
```sql
-- ================================================
-- Purchase Order: P00123
-- Receipt ID: receipt_123
-- Vendor: Costco
-- Date: 2025-10-15
-- Total: $123.45
-- ================================================
-- 
-- Instructions:
-- 1. Review this SQL file
-- 2. Execute in Odoo database
-- 3. Go to Odoo web UI: Purchase > Purchase Orders
-- 4. Find PO ID: 123
-- 5. CONFIRM the purchase order from web UI
-- 
-- Note: PO is created in 'draft' state
-- ================================================

BEGIN;

-- Purchase Order Header
INSERT INTO purchase_order (...)
SELECT ...;

-- Purchase Order Lines (Products)
INSERT INTO purchase_order_line (...)
VALUES (...);

-- Purchase Order Lines (Fees)
INSERT INTO purchase_order_line (...)
VALUES (...);

COMMIT;

-- Verification Queries
SELECT ...;
```

### Rollback SQL File
```sql
-- Rollback SQL for Purchase Order: P00123
-- Receipt ID: receipt_123

BEGIN;

DELETE FROM purchase_order_line WHERE order_id = 123;
DELETE FROM purchase_order WHERE id = 123;

COMMIT;
```

---

## Integration Points

### 1. **With Step 1 Output**
- Read from `data/step1_output/*/extracted_data.json`
- Support multiple output folders (localgrocery_based, instacart_based, etc.)
- Handle merged output format

### 2. **With Odoo Database**
- Query for vendor/partner lookup
- Query for UoM information
- Query for product information
- Get next available IDs

### 3. **With Existing Scripts**
- Can enhance `scripts/generate_purchase_order_sql.py`
- Or create new `step1_to_sql/generate_sql.py`
- Maintain compatibility with Step 4 workflow

---

## Benefits

1. **Simplified Workflow**: Skip Step 3 (product matching already done)
2. **Faster**: Direct path from extraction to SQL
3. **More Accurate**: Uses Odoo-matched data directly
4. **Less Error-Prone**: No intermediate mapping step
5. **Better Integration**: Leverages Odoo matching in Step 1

---

## Implementation Strategy

### Option 1: Enhance Existing Script
- Update `scripts/generate_purchase_order_sql.py`
- Add validation for Odoo-matched items
- Improve error handling

### Option 2: Create New Module
- Create `step1_to_sql/` directory
- New `generate_sql.py` that reads Step 1 output
- Cleaner separation of concerns

### Option 3: Add to Workflow
- Add `step1_to_sql()` method to `ReceiptWorkflow`
- Optional step after Step 1
- Can still use Step 4 for manual matching cases

---

## Validation Output Example

### Console Output
```
================================================================================
⚠️  VALIDATION FAILED: Missing Items in Odoo Database
================================================================================

❌ Missing Products: 3
   Please create these products in Odoo first:
     - Product ID: 12345
       Name: Special Product XYZ
       Receipt: receipt_123
       Reason: Product ID 12345 not found in Odoo database
     
     - Product ID: None
       Name: Unknown Product
       Receipt: receipt_456
       Reason: No odoo_product_id in receipt data

❌ Missing UoMs: 2
   Please create these UoMs in Odoo first:
     - UoM Name: custom-unit
       Used by 5 items
       Sample items: Product A, Product B, Product C

❌ Missing Vendors: 1
   Please create these vendors/partners in Odoo first:
     - Vendor Name: New Vendor Inc
       Used by 2 receipts
       Receipts: receipt_789, receipt_790

================================================================================
📋 Detailed report saved to: data/sql/missing_items_report.csv
================================================================================

💡 Next Steps:
   1. Review the missing items report
   2. Create missing products/UoMs/vendors in Odoo
   3. Re-run SQL generation
```

### CSV Report Format
```csv
Type,ID,Name,Receipt ID,Reason
Missing Product,12345,Special Product XYZ,receipt_123,Product ID 12345 not found in Odoo database
Missing Product,,Unknown Product,receipt_456,No odoo_product_id in receipt data
Missing UoM,N/A,custom-unit,receipt_123,UoM not found in Odoo database
Missing Vendor,N/A,New Vendor Inc,receipt_789,Vendor/Partner not found in Odoo database
```

## Questions to Consider

1. **What to do with unmatched items?**
   - ✅ **RECOMMENDED**: Stop and report (current design)
   - Alternative: Skip unmatched items, generate SQL for matched only
   - Alternative: Create placeholder products automatically (risky)

2. **How to handle duplicate receipts?**
   - Check if PO already exists in Odoo (by receipt_id or partner_ref)
   - Skip if exists, or update existing PO
   - Option to force regenerate

3. **Transaction handling?**
   - ✅ One transaction per receipt (recommended)
   - Alternative: Batch multiple receipts in one transaction

4. **Error recovery?**
   - ✅ Stop on validation errors (recommended)
   - Alternative: Continue with warnings, generate partial SQL

5. **Validation level?**
   - ✅ **STRICT**: All items must exist in Odoo (recommended)
   - Alternative: Flexible mode (generate SQL for matched items only)

---

## Example Usage

### Basic Usage with Validation
```python
from step1_to_sql.generate_sql import DirectSQLGenerator
from step3_mapping.query_database import connect_to_database

# Connect to database
conn = connect_to_database()

# Initialize generator
generator = DirectSQLGenerator(conn)

try:
    # Generate SQL from Step 1 output (with validation)
    sql_files = generator.generate_sql_from_step1_output(
        step1_output_dir=Path('data/step1_output'),
        output_dir=Path('data/sql')
    )
    print(f"✅ Generated {len(sql_files)} SQL files")
except ValidationError as e:
    print(f"❌ Validation failed: {e}")
    print("Please create missing items in Odoo and try again")
```

### Validation Only (Check Before Generating)
```python
# Just validate without generating SQL
is_valid, missing = generator.validate_before_generation(
    step1_output_dir=Path('data/step1_output')
)

if is_valid:
    print("✅ All products, UoMs, and vendors exist in Odoo")
    # Proceed with SQL generation
else:
    print("❌ Missing items found. Review report and create in Odoo first.")
    generator._report_missing_items(missing)
```

### Skip Validation (Not Recommended)
```python
# Only use if you're certain all items exist
sql_files = generator.generate_sql_from_step1_output(
    step1_output_dir=Path('data/step1_output'),
    output_dir=Path('data/sql'),
    skip_validation=True  # ⚠️ Use with caution
)
```

---

## Next Steps

1. **Review this design** with user
2. **Choose implementation approach** (enhance existing vs. new module)
3. **Implement core SQL generation** from Step 1 output
4. **Add validation and error handling**
5. **Test with October receipts**
6. **Document usage**

