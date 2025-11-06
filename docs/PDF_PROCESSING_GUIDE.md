# PDF Processing Guide - Adding New Store-Specific Layouts

This guide explains how to add PDF processing support for new stores with store-specific layouts.

## Current PDF Processors

The system currently supports PDF processing for:

1. **Instacart** (`pdf_processor.py`) - Uses CSV baseline matching
2. **Restaurant Depot (RD)** (`rd_pdf_processor.py`) - Grid-based table extraction
3. **WebstaurantStore** (`webstaurantstore_pdf_processor.py`) - Tabular invoice extraction
4. **Amazon** (`amazon_csv_processor.py`) - CSV-first processing (PDFs for validation)

## Architecture Pattern

### 1. PDF Layout Rules (YAML)

Create a new YAML file in `step1_rules/` following the naming pattern:
- `30_[store]_pdf.yaml` or `30_[store]_layout.yaml`

**Example structure:**
```yaml
# Store Name PDF Layout Rules
store_pdf_layouts:
  - name: "Store Name PDF v1"
    parsed_by: "store_pdf_v1"
    applies_to:
      vendor_code: ["STORE_CODE"]
      file_ext: [".pdf"]
      text_contains:
        - "Store Name"
        - "Item Description"
        - "Total"
      filename_patterns:
        - "STORE_.*\\.pdf"
        - ".*store.*\\.pdf"
    
    # Grid mode settings (for tabular PDFs)
    table:
      mode: "grid"  # or "text" for non-tabular
      header_contains:
        - "Item Description"
        - "Total"
      header_aliases:
        quantity:
          - "QTY"
          - "Quantity"
        unit_price:
          - "Unit Price"
          - "Price"
        total_price:
          - "Total"
          - "Amount"
        product_name:
          - "Item Description"
          - "Description"
    
    # Column mappings
    column_mappings:
      product_name: "Item Description"
      quantity: "^(QTY|Quantity)$"
      unit_price: "^(Unit\\s*Price|Price)$"
      total_price: "(?i)Total|Amount"
    
    # Skip patterns for non-item rows
    skip_patterns:
      - "TOTAL"
      - "TAX"
      - "^$"  # Empty lines
    
    # Totals extraction patterns
    totals:
      subtotal:
        patterns:
          - "Subtotal[:\\s]+(?:\\$?\\s*)?([0-9,]+(?:\\.[0-9]{2})?)"
      tax:
        patterns:
          - "Tax[:\\s]+(?:\\$?\\s*)?([0-9,]+(?:\\.[0-9]{2})?)"
      total:
        patterns:
          - "Total[:\\s]+(?:\\$?\\s*)?([0-9,]+(?:\\.[0-9]{2})?)"
    
    # Normalization settings
    normalization:
      trim_whitespace: true
      preserve_case: true
      currency_symbols:
        - "$"
      thousands_separator: ","
```

### 2. PDF Processor (Python)

Create a new Python module in `step1_extract/`:
- `[store]_pdf_processor.py`

**Example structure:**
```python
#!/usr/bin/env python3
"""
Store Name PDF Processor
Processes Store Name PDF receipts using grid-based table extraction.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Any
import pandas as pd

logger = logging.getLogger(__name__)

# Try to import pdfplumber
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    logger.warning("pdfplumber not available. Install with: pip install pdfplumber")

# Try to import OCR libraries (for scanned PDFs)
try:
    import pytesseract
    from PIL import Image
    import fitz  # PyMuPDF
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.debug("OCR libraries not available")


class StorePDFProcessor:
    """Process Store Name PDF receipts using grid-based table extraction"""
    
    def __init__(self, rule_loader, input_dir=None):
        self.rule_loader = rule_loader
        self.input_dir = Path(input_dir) if input_dir else None
        
        # Load layout rules from YAML
        self._load_layout_rules()
        
        # Prepare config with knowledge base file path
        config = {}
        if self.input_dir:
            kb_file = self.input_dir / 'knowledge_base.json'
            if kb_file.exists():
                config['knowledge_base_file'] = str(kb_file)
        
        # Import ReceiptProcessor for knowledge base enrichment
        from .receipt_processor import ReceiptProcessor
        self._legacy_processor = ReceiptProcessor(config=config)
        
        # Import LayoutApplier to apply layout rules
        from .layout_applier import LayoutApplier
        self.layout_applier = LayoutApplier(rule_loader)
    
    def _load_layout_rules(self):
        """Load layout rules from YAML"""
        try:
            layout_rules = self.rule_loader.load_rule_file_by_name('30_store_pdf.yaml')
            if layout_rules and 'store_pdf_layouts' in layout_rules:
                self.layout_rules = layout_rules['store_pdf_layouts']
                logger.debug("Loaded PDF layout rules from YAML")
                return
            logger.warning("Layout rules not found in YAML")
            self.layout_rules = []
        except Exception as e:
            logger.warning(f"Error loading layout rules: {e}")
            self.layout_rules = []
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Process a PDF file using grid-based table extraction
        
        Args:
            file_path: Path to PDF file
            detected_vendor_code: Vendor code from detection (optional)
            
        Returns:
            Dictionary containing extracted receipt data
        """
        try:
            # Find matching layout
            matching_layout = self._find_matching_layout(file_path, detected_vendor_code)
            if not matching_layout:
                logger.warning(f"No matching layout found for {file_path.name}")
                return None
            
            # Extract table from PDF
            df = self._extract_table_from_pdf(file_path, matching_layout)
            if df is None or df.empty:
                logger.warning(f"No table extracted from {file_path.name}")
                return None
            
            # Apply layout rules using LayoutApplier
            result = self.layout_applier.apply_layout(
                df=df,
                layout=matching_layout,
                vendor_code=detected_vendor_code or 'STORE',
                file_path=file_path
            )
            
            if not result:
                logger.warning(f"Layout application failed for {file_path.name}")
                return None
            
            # Build receipt data
            receipt_data = {
                'filename': file_path.name,
                'source_file': str(file_path),
                'vendor_code': detected_vendor_code or 'STORE',
                'detected_vendor_code': detected_vendor_code or 'STORE',
                'source_type': 'store_based',
                'items': result.get('items', []),
                'parsed_by': matching_layout.get('parsed_by', 'store_pdf_v1'),
                'total': result.get('total', 0.0),
                'subtotal': result.get('subtotal', 0.0),
                'tax': result.get('tax', 0.0),
            }
            
            # Enrich with knowledge base (if available)
            if receipt_data.get('items'):
                self._enrich_with_kb(receipt_data)
            
            return receipt_data
            
        except Exception as e:
            logger.error(f"Error processing PDF file {file_path.name}: {e}", exc_info=True)
            return None
    
    def _find_matching_layout(self, file_path: Path, vendor_code: Optional[str] = None) -> Optional[Dict]:
        """Find matching layout from YAML rules"""
        # Implementation similar to RD PDF processor
        # Check applies_to conditions: vendor_code, file_ext, text_contains, filename_patterns
        pass
    
    def _extract_table_from_pdf(self, file_path: Path, layout: Dict) -> Optional[pd.DataFrame]:
        """Extract table from PDF using pdfplumber or OCR"""
        # Implementation similar to RD PDF processor
        # Try pdfplumber first, fall back to OCR if needed
        pass
    
    def _enrich_with_kb(self, receipt_data: Dict):
        """Enrich items with knowledge base data"""
        # Use ReceiptProcessor to enrich with KB
        if self._legacy_processor:
            receipt_data['items'] = self._legacy_processor.enrich_with_vendor_kb(
                receipt_data['items'],
                vendor_code=receipt_data.get('vendor_code', '')
            )
```

### 3. Vendor Detection

Update `step1_rules/10_vendor_detection.yaml` to add vendor detection patterns:

```yaml
vendor_detection:
  rules:
    - vendor_code: "STORE"
      vendor_name: "Store Name"
      patterns:
        filename:
          - "STORE_.*\\.pdf"
          - ".*store.*\\.pdf"
        path:
          - ".*/[Ss]tore.*/"
        content:
          - "Store Name"
          - "Store Address"
```

### 4. Register in main.py

Add the new processor to `step1_extract/main.py`:

```python
# In detect_group function, add store detection
if store_detected:
    return 'store_based'

# In process_files function, add store processing section
store_based_files = [f for f in pdf_files if detect_group(f, input_dir) == 'store_based']

if store_based_files:
    logger.info("Processing Store-based receipts...")
    from .store_pdf_processor import StorePDFProcessor
    store_processor = StorePDFProcessor(rule_loader, input_dir=input_dir)
    
    for file_path in store_based_files:
        try:
            logger.info(f"Processing [Store]: {file_path.name}")
            receipt_data = store_processor.process_file(file_path, detected_vendor_code='STORE')
            if receipt_data:
                store_based_data[file_path.stem] = receipt_data
        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}", exc_info=True)
```

## Processing Flow

1. **Vendor Detection** - Detects vendor from filename/path/content
2. **PDF Extraction** - Extracts table using pdfplumber (grid mode) or OCR (scanned)
3. **Layout Application** - Applies layout rules using `LayoutApplier`
4. **Knowledge Base Enrichment** - Enriches items with KB data (UoM, category hints)
5. **Name Hygiene** - Extracts UPC/Item# and cleans product names
6. **Category Classification** - Assigns L1/L2 categories
7. **Report Generation** - Generates HTML/CSV reports

## Testing

1. Place sample PDF files in `data/step1_input/[store]/`
2. Run Step 1: `python -m step1_extract.main data/step1_input data/step1_output`
3. Check output: `data/step1_output/store_based/report.html`
4. Verify extracted items match the PDF structure

## Reference Implementations

- **RD PDF Processor**: `step1_extract/rd_pdf_processor.py`
- **RD PDF Layout**: `step1_rules/21_rd_pdf_layout.yaml`
- **WebstaurantStore PDF Processor**: `step1_extract/webstaurantstore_pdf_processor.py`
- **WebstaurantStore PDF Layout**: `step1_rules/29_webstaurantstore_pdf.yaml`

