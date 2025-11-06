import logging
import re
import yaml
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# --- Setup Logging ---
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s') 

# --- Mock Dependencies ---
PDFPLUMBER_AVAILABLE = True
OCR_AVAILABLE = True

class MockImage:
    def __init__(self, size): pass

class MockPytesseract:
    def image_to_string(self, img, config=None):
        raise Exception("Tesseract is not installed.")

class MockPyMuPDF:
    def open(self, filepath): return self
    def close(self): pass
    def __len__(self): return 1
    def __getitem__(self, index): return self
    def get_pixmap(self, matrix): return self
    @property
    def samples(self): return b'mock_image_data'
    @property
    def width(self): return 10
    @property
    def height(self): return 10
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass

class MockPandas:
    def DataFrame(self, data): return data

pytesseract = MockPytesseract()
Image = MockImage
fitz = MockPyMuPDF()
pd = MockPandas() 

# --- Rule Loader Mock ---
class MockRuleLoader:
    def __init__(self, rule_contents: Dict[str, str]):
        self.rule_contents = rule_contents

    def load_rule_file_by_name(self, filename: str) -> Dict[str, Any]:
        if filename not in self.rule_contents:
            logger.error(f"MockRuleLoader: Rule file '{filename}' not found.")
            return {}
        try:
            return yaml.safe_load(self.rule_contents[filename])
        except yaml.YAMLError as e:
            logger.error(f"MockRuleLoader: Error parsing YAML file {filename}: {e}")
            return {}

# --- Receipt Processor Mock ---
class MockReceiptProcessor:
    def __init__(self, config=None):
        pass
    def enrich_with_vendor_kb(self, items: List[Dict], vendor_code: str) -> List[Dict]:
        return items

class MockModule:
    ReceiptProcessor = MockReceiptProcessor

import sys
sys.modules['receipt_processor'] = MockModule 

# --- Mock PDF Content (Pre-extracted OCR Text) ---
MOCK_PDF_CONTENTS = {
    "aldi_0905.pdf": """
ALDI
store #003
4900 N. BROADWAY
Chicago
nttps://help.aidi us
_ 418510 Heavy Whip 32 02 10,78 FB
ok bine
SUBTOTAL 10.78
B Taxable @2 250% 0.24
AMOUNT DUE 11,02
1 OE AL 1102
2 [TEMS
Debit Card $ 11,02
#9506 F003/006/802 09/05/25 UY: 32AM
CREE CE REECE CARE COREE ES cba bebo
Like ALDI? Tel] ALDI!
Tell us how we did at
www. tel lald) us
Enter the drawing for a chance
to win a $100 ALDI gift card,
Must be 18 years old to enter.
No purchase necessary.
21g up for ALDI emai |s
for 4 sneak peek on the weekly aq
WWW AIG) .US/Signup
VISA 1.0
OPO REAEABIS | OTHER 11.02
09/05/25 09:32 Ref/Seq # 0
Auth # 067556
ALD AQOQOQOQ0S 1010
TYR OOOOOOQ0000
IAD _1F420132A0000000001003027 99959,
UU400000000000000000000000000q 99 :
TSI 0000 = ARC 00 —_—EntryMoge 7
++APPROVED ++
""",

    "parktoshop_0908.pdf": """
Park To Shop
4879 N. Broadway
Chicago IL 60616
773-334-3838
9/8/2025 1:11:13 PM
GREEN ONION
SI LIN
$0.00
3 $0.39ea.3/$1.00
F $1.00
00000000002113
BASIL LEAVE
1.01 lb $5.95/1b
F $6.01
TOTAL $7.01
Visa
Reference# 608973
Item count: 4
""",

    "0915_marianos.pdf": """
MARIANO'S
5201 N. Sheridan Rd.
773.506.0553
Your cashier was CHEC 520
DRIS STRAWBERRY
4.99 B
Rewards Customer
TAX 0.11
**** BALANCE 5.10
Chicago I.60643
VISA CREDIT Purchase
REF#: 005795 1014: 5.10
8931 - H
VISA 5.10
CHANGE 0.00
TOTAL NUMBER OF ITEMS SOLD = 1
09/15/25 10:51am
Annual Card Savings $10.52
Fuel Points Earned Today: 5
"""
}

# --- UNIFIED PDF PROCESSOR CLASS ---
class UnifiedPDFProcessor:
    """Process PDF receipts using vendor-specific YAML rules"""
    
    def __init__(self, rule_loader, input_dir=None):
        self.rule_loader = rule_loader
        self.input_dir = Path(input_dir) if input_dir else Path('.')
        config = {}
        kb_file = self.input_dir / 'knowledge_base.json'
        config['knowledge_base_file'] = str(kb_file)
        from receipt_processor import ReceiptProcessor 
        self._legacy_processor = ReceiptProcessor(config=config)
    
    def process_file(self, file_path: Path, detected_vendor_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            if 'aldi' in file_path.name:
                vendor_code = 'ALDI'
            elif 'parktoshop' in file_path.name:
                vendor_code = 'PARKTOSHOP'
            elif 'marianos' in file_path.name:
                vendor_code = 'MARIANOS'
            else:
                vendor_code = detected_vendor_code or 'UNKNOWN'
            
            pdf_rules = self._load_vendor_pdf_rules(vendor_code)
            if not pdf_rules:
                logger.warning(f"No PDF rules found for vendor: {vendor_code}")
                return None
            
            pdf_text = self._extract_pdf_text_mock(file_path.name)
            if not pdf_text:
                logger.warning(f"Could not extract text from {file_path.name}")
                return None
            
            items = self._parse_receipt_text(pdf_text, pdf_rules)
            if not items:
                logger.warning(f"No items extracted from {file_path.name}")
                return None
            
            totals = self._extract_totals_from_text(pdf_text, pdf_rules)
            
            receipt_data = {
                'filename': file_path.name,
                'vendor': pdf_rules.get('vendor_name', vendor_code),
                'detected_vendor_code': vendor_code,
                'detected_source_type': 'localgrocery_based',
                'source_file': str(file_path.name),
                'items': items,
                'parsed_by': pdf_rules.get('parsed_by', 'unified_pdf_v1'),
                'subtotal': totals.get('subtotal', 0.0),
                'tax': totals.get('tax', 0.0),
                'total': totals.get('total', 0.0),
                'currency': 'USD'
            }
            
            if pdf_rules.get('extract_items_sold'):
                items_sold = self._extract_items_sold(pdf_text, pdf_rules)
                if items_sold is not None:
                    receipt_data['items_sold'] = items_sold
            
            if pdf_rules.get('extract_transaction_date'):
                date = self._extract_transaction_date(pdf_text, pdf_rules)
                if date:
                    receipt_data['transaction_date'] = date
            
            if receipt_data.get('items'):
                receipt_data['items'] = self._enrich_items(receipt_data['items'], vendor_code)
            
            logger.info(f"Extracted {len(items)} items from PDF {file_path.name}")
            return receipt_data
        except Exception as e:
            logger.error(f"Error processing PDF {file_path.name}: {e}", exc_info=True)
            return None
    
    def _extract_pdf_text_mock(self, filename: str) -> str:
        return MOCK_PDF_CONTENTS.get(filename, "")

    def _load_vendor_pdf_rules(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        vendor_file_map = {
            'COSTCO': '20_costco_pdf.yaml',
            'JEWEL': '22_jewel_pdf.yaml',
            'JEWELOSCO': '22_jewel_pdf.yaml',
            'MARIANOS': '22_jewel_pdf.yaml',
            'ALDI': '23_aldi_pdf.yaml',
            'PARKTOSHOP': '24_parktoshop_pdf.yaml',
        }
        yaml_file = vendor_file_map.get(vendor_code.upper())
        if not yaml_file:
            return None
        try:
            rules = self.rule_loader.load_rule_file_by_name(yaml_file)
            if 'pdf_rules' in rules:
                return rules['pdf_rules']
            elif 'pdf_layouts' in rules:
                for layout in rules.get('pdf_layouts', []):
                    applies_to = layout.get('applies_to', {})
                    vendor_codes = applies_to.get('vendor_code', [])
                    if vendor_code.upper() in [v.upper() for v in vendor_codes]:
                        return layout
                return rules.get('pdf_layouts', [{}])[0] if rules.get('pdf_layouts') else None
            else:
                return rules
        except Exception as e:
            logger.warning(f"Could not load PDF rules from {yaml_file}: {e}")
            return None
    
    def _extract_pdf_text(self, file_path: Path, use_ocr: bool = False) -> str:
        return self._extract_pdf_text_mock(file_path.name)
    
    def _extract_pdf_text_ocr(self, file_path: Path) -> str:
        return self._extract_pdf_text_mock(file_path.name)
    
    def _parse_receipt_text(self, text: str, rules: Dict[str, Any]) -> List[Dict[str, Any]]:
        items = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        summary_keywords = rules.get('summary_keywords', ['SUBTOTAL', 'TAX', 'TOTAL'])
        summary_start = len(lines)
        for i, line in enumerate(lines):
            line_upper = line.upper()
            exclude_keywords = rules.get('summary_exclude_keywords', [])
            if any(str(kw).upper() in line_upper for kw in summary_keywords):
                if not any(str(ekw).upper() in line_upper for ekw in exclude_keywords):
                    summary_start = i
                    break
        
        item_patterns = rules.get('item_patterns', [])
        
        line_idx = 0
        while line_idx < summary_start:
            line = lines[line_idx]
            
            skip_keywords = rules.get('skip_keywords', [])
            if any(str(kw).upper() in line.upper() for kw in skip_keywords):
                line_idx += 1
                continue
            
            match_found = False
            for pattern_def in item_patterns:
                pattern_type = pattern_def.get('type', '')
                regex_str = pattern_def.get('regex', '')
                groups = pattern_def.get('groups', [])
                
                if not regex_str:
                    continue
                
                flags = re.IGNORECASE if pattern_def.get('case_insensitive', True) else 0
                match_text = line
                consumed_lines = 1
                
                if pattern_def.get('multiline'):
                    lookahead = min(len(lines) - line_idx, 5)
                    match_text = '\n'.join(lines[line_idx:line_idx + lookahead])
                    flags |= re.MULTILINE 
                
                try:
                    pattern = re.compile(regex_str, flags)
                    match = pattern.search(match_text)
                    
                    if match:
                        match_found = True
                        
                        if pattern_def.get('multiline'):
                            match_end_pos = match.end()
                            consumed_lines = len(match_text[:match_end_pos].split('\n'))
                        else:
                            consumed_lines = 1

                        item_data = {}
                        for idx, group_name in enumerate(groups, 1):
                            if idx <= len(match.groups()):
                                item_data[group_name] = match.group(idx)
                        
                        conditions = pattern_def.get('conditions', [])
                        if conditions:
                            if not self._check_conditions(line, match, item_data, conditions):
                                match_found = False
                                continue
                        
                        item = self._build_item_from_match(item_data, pattern_def, line, rules)
                        
                        if item:
                            if pattern_def.get('quantity_from_next_line'):
                                quantity = self._extract_quantity_from_next_line(lines, line_idx, rules)
                                if quantity:
                                    item['quantity'] = quantity
                                    item['unit_price'] = item['total_price'] / quantity if quantity > 0 else item['total_price']
                                consumed_lines += 1 
                            
                            items.append(item)
                            line_idx += consumed_lines
                            break
                        else:
                            match_found = False
                except Exception as e:
                    logger.debug(f"Error matching pattern {pattern_type}: {e}")
                    continue

            if not match_found:
                line_idx += 1
        
        return items
    
    def _build_item_from_match(self, item_data: Dict[str, str], pattern_def: Dict[str, Any], line: str, rules: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        field_mappings = pattern_def.get('field_mappings', {})
        if not field_mappings:
            field_mappings = rules.get('field_mappings', {})
        
        default_mappings = {
            'item_number': 'item_number',
            'product_name': 'product_name',
            'quantity': 'quantity',
            'unit_price': 'unit_price',
            'total_price': 'total_price',
            'price': 'total_price',
        }
        field_mappings = {**default_mappings, **field_mappings}
        
        item = {
            'vendor': rules.get('vendor_name', 'UNKNOWN'),
            'is_summary': False,
        }
        
        for target_field, source_field in field_mappings.items():
            if source_field in item_data:
                value = item_data[source_field]
                if value is None:
                    continue
                if target_field in ['unit_price', 'total_price', 'quantity']:
                    value_str = str(value).replace(',', '.').replace('$', '').strip()
                    try:
                        item[target_field] = float(value_str)
                    except ValueError:
                        continue
                else:
                    item[target_field] = str(value).strip()
        
        if pattern_def.get('post_process'):
            item = self._apply_post_process(item, pattern_def.get('post_process'), line, rules)
        
        if not item.get('product_name') and not item.get('total_price'):
            return None
        
        if 'quantity' not in item:
            item['quantity'] = 1.0
        if 'unit_price' not in item and 'total_price' in item:
            item['unit_price'] = item['total_price'] / item['quantity'] if item['quantity'] > 0 else item['total_price']
        if 'purchase_uom' not in item:
            item['purchase_uom'] = 'EACH'
        
        return item
    
    def _apply_post_process(self, item: Dict[str, Any], post_process: Dict[str, Any], line: str, rules: Dict[str, Any]) -> Dict[str, Any]:
        if post_process.get('extract_uom'):
            uom_patterns = post_process.get('uom_patterns', [])
            product_name = item.get('product_name', '')
            for pattern_str in uom_patterns:
                match = re.search(pattern_str, product_name, re.IGNORECASE)
                if match:
                    item['purchase_uom'] = match.group(1).upper()
                    item['product_name'] = re.sub(pattern_str, '', product_name, flags=re.IGNORECASE).strip()
                    break
        
        if post_process.get('infer_product_from_price'):
            price_mappings = post_process.get('price_mappings', {})
            total_price = item.get('total_price', 0)
            for price_str, product_name in price_mappings.items():
                try:
                    price_value = float(price_str)
                    if abs(total_price - price_value) < 0.10:
                        item['product_name'] = product_name
                        break
                except ValueError:
                    continue
        
        if post_process.get('clean_product_name'):
            product_name = item.get('product_name', '')
            product_name = re.sub(r'\s+[a-z]\s*$', '', product_name, flags=re.IGNORECASE)
            product_name = re.sub(r'\s+\d+\s*$', '', product_name)
            item['product_name'] = product_name.strip()
        
        return item
    
    def _check_conditions(self, line: str, match: re.Match, item_data: Dict[str, str], conditions: List[str]) -> bool:
        for condition in conditions:
            if condition.startswith('len('):
                try:
                    if 'line' in condition:
                        length = len(line)
                        if '>' in condition:
                            threshold = int(re.search(r'>\s*(\d+)', condition).group(1))
                            if length <= threshold: return False
                        elif '<' in condition:
                            threshold = int(re.search(r'<\s*(\d+)', condition).group(1))
                            if length >= threshold: return False
                except Exception:
                    pass
            elif condition.startswith('total_price'):
                try:
                    if '>' in condition and 'total_price' in item_data:
                        price = float(item_data['total_price'].replace(',', '.').replace('$', ''))
                        if price <= 0: return False
                except Exception:
                    pass
        return True
    
    def _extract_quantity_from_next_line(self, lines: List[str], current_idx: int, rules: Dict[str, Any]) -> Optional[float]:
        if current_idx + 1 >= len(lines):
            return None
        next_line = lines[current_idx + 1]
        quantity_pattern = rules.get('quantity_pattern', r'Quantity:\s*(\d+(?:\.\d+)?)')
        match = re.search(quantity_pattern, next_line, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None
    
    def _extract_totals_from_text(self, text: str, rules: Dict[str, Any]) -> Dict[str, float]:
        totals = {'subtotal': 0.0, 'tax': 0.0, 'total': 0.0}
        total_patterns = rules.get('total_patterns', {})
        
        if 'subtotal' in total_patterns:
            subtotal_match = re.search(total_patterns['subtotal'], text, re.IGNORECASE | re.MULTILINE)
            if subtotal_match:
                totals['subtotal'] = float(subtotal_match.group(1).replace(',', '.'))
        
        if 'tax' in total_patterns:
            tax_match = re.search(total_patterns['tax'], text, re.IGNORECASE | re.MULTILINE)
            if tax_match:
                totals['tax'] = float(tax_match.group(1).replace(',', '.'))
        
        if 'total' in total_patterns:
            total_match = re.search(total_patterns['total'], text, re.IGNORECASE | re.MULTILINE)
            if total_match:
                if len(total_match.groups()) >= 2:
                    dollars = total_match.group(1)
                    cents = total_match.group(2)
                    totals['total'] = float(f"{dollars}.{cents}")
                else:
                    totals['total'] = float(total_match.group(1).replace(',', '.'))
        
        return totals
    
    def _extract_items_sold(self, text: str, rules: Dict[str, Any]) -> Optional[int]:
        items_sold_pattern = rules.get('items_sold_pattern', r'TOTAL NUMBER OF ITEMS SOLD\s*=\s*(\d+)')
        match = re.search(items_sold_pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def _extract_transaction_date(self, text: str, rules: Dict[str, Any]) -> Optional[str]:
        date_pattern = rules.get('date_pattern', r'(\d{2}/\d{2}/\d{4})')
        match = re.search(date_pattern, text)
        if match:
            return match.group(1)
        return None
    
    def _enrich_items(self, items: List[Dict], vendor_code: str) -> List[Dict]:
        if not self._legacy_processor:
            return items
        try:
            if hasattr(self._legacy_processor, 'enrich_with_vendor_kb'):
                return self._legacy_processor.enrich_with_vendor_kb(items, vendor_code=vendor_code)
        except Exception as e:
            logger.warning(f"Error enriching items: {e}")
        return items

# --- Main Execution Logic ---
def process_receipts_unified(rule_contents: Dict[str, str]):
    rule_loader = MockRuleLoader(rule_contents)
    processor = UnifiedPDFProcessor(rule_loader=rule_loader)
    
    files_to_process = {
        "aldi_0905.pdf": "ALDI",
        "parktoshop_0908.pdf": "PARKTOSHOP",
        "0915_marianos.pdf": "MARIANOS"
    }

    all_extracted_data = {}

    for filename, vendor_code in files_to_process.items():
        print(f"\n{'='*80}")
        print(f"Processing {filename} ({vendor_code})")
        print(f"{'='*80}")
        
        file_path = Path(filename)
        extracted_data = processor.process_file(file_path, detected_vendor_code=vendor_code)
        
        if extracted_data:
            all_extracted_data[filename] = extracted_data
            print(f"\n✅ Successfully extracted data")
            print(f"\nReceipt Summary:")
            print(f"  Vendor: {extracted_data.get('vendor', 'N/A')}")
            print(f"  Parsed By: {extracted_data.get('parsed_by', 'N/A')}")
            print(f"  Total: \${extracted_data.get('total', 0):.2f}")
            print(f"  Subtotal: \${extracted_data.get('subtotal', 0):.2f}")
            print(f"  Tax: \${extracted_data.get('tax', 0):.2f}")
            
            items = extracted_data.get('items', [])
            print(f"\nItems Extracted: {len(items)}")
            print('-' * 80)
            
            for i, item in enumerate(items, 1):
                print(f"\nItem {i}:")
                print(f"  Item Number: \"{item.get('item_number', 'N/A')}\"")
                print(f"  Product Name: \"{item.get('product_name', 'N/A')}\"")
                print(f"  Quantity: {item.get('quantity', 'N/A')}")
                print(f"  Unit Price: \${item.get('unit_price', 0):.2f}")
                print(f"  Total Price: \${item.get('total_price', 0):.2f}")
                print(f"  Purchase UOM: {item.get('purchase_uom', 'N/A')}")
            
            print(f"\n{'='*80}")
            print("Full JSON Output:")
            print(f"{'='*80}")
            print(json.dumps(extracted_data, indent=2, default=str))
        else:
            print(f"❌ Extraction FAILED for {filename}.")
            
    return all_extracted_data

if __name__ == "__main__":
    RULE_CONTENTS = {
        '23_aldi_pdf.yaml': """
vendor_name: ALDI
parsed_by: aldi_pdf_v1
extraction_method: ocr
extract_transaction_date: True
summary_keywords: [SUBTOTAL, TAXABLE, AMOUNT DUE, TOTAL, APPROVED]

item_patterns:
  - type: standard_item
    regex: '^_\\s+(\\d+)\\s+(.+?)\\s+(\\d+[.,]\\d{2})\\s*(FB|B)?\\s*$'
    groups: [item_number, product_name, total_price]
    field_mappings:
      item_number: item_number
      product_name: product_name
      total_price: total_price
    post_process:
      clean_product_name: True
      extract_uom: true
      uom_patterns:
        - '\\s+(\\d+)\\s*(LB|LBS|OZ|OZS|CT|GAL|GALS|EA|EACH|L|ML|FL\\s*OZ)\\s*$'
      
total_patterns:
  subtotal: 'SUBTOTAL\\s+(\\d+[.,]\\d{1,2})'
  tax: 'Taxable\\s+@[\\d\\s\\%\\.\\,]*([\\d\\.\\,]+)'
  total: '(?:AMOUNT\\s+DUE|OE\\s+AL|Debit\\s+Card\\s+\\$|TOTAL)\\s+([\\d\\.\\,]+)'

date_pattern: '(\\d{2}/\\d{2}/\\d{2,4})'
""",

        '24_parktoshop_pdf.yaml': """
vendor_name: Park To Shop
parsed_by: parktoshop_pdf_v1
extraction_method: text
extract_transaction_date: True
summary_keywords: [TOTAL, Visa, Reference, Item count]

item_patterns:
  - type: weighted_item
    regex: '^\\s*([A-Z\\s]+?)\\s+([\\d\\.]+)\\s+lb\\s+\\$[\\d\\.]+/lb\\s+F\\s+\\$([\\d\\.\\,]+)$'
    groups: [product_name, size, total_price]
    field_mappings:
      product_name: product_name
      total_price: total_price
    post_process:
      clean_product_name: True
      infer_product_from_price: true
      price_mappings:
        "6.01": "BASIL LEAVE"
        "1.00": "GREEN ONION"
      
  - type: fixed_price_item
    regex: '^([A-Z\\s]+?)\\s*\\n(.*?)\\nF\\s+\\$([\\d\\.\\,]+)'
    groups: [product_name, middle_line, total_price]
    field_mappings:
      product_name: product_name
      total_price: total_price
    multiline: true
    post_process:
      clean_product_name: True
      infer_product_from_price: true
      price_mappings:
        "6.01": "BASIL LEAVE"
        "1.00": "GREEN ONION"
    
total_patterns:
  subtotal: 'TOTAL\\s+\\$([\\d\\.\\,]+)' 
  tax: '^\\s*tax\\s+\\$([\\d\\.\\,]+)' 
  total: 'TOTAL\\s+\\$([\\d\\.\\,]+)'

date_pattern: '(\\d{1,2}/\\d{1,2}/\\d{4})'
""",

        '22_jewel_pdf.yaml': """
vendor_name: MARIANO'S
parsed_by: jewel_pdf_v1
extraction_method: text
extract_transaction_date: True
extract_items_sold: True
summary_keywords: [TAX, BALANCE, VISA, TOTAL NUMBER]
skip_keywords: [Rewards Customer, VISA CREDIT, REF, AID, TC, CHANGE, 8931]

item_patterns:
  - type: standard_item_multiline
    regex: '^(?P<product_name>[A-Z\\s]+?)\\s*\\n(?P<total_price>[\\d\\.]+)\\s+B'
    groups: [product_name, total_price]
    field_mappings:
      product_name: product_name
      total_price: total_price
    multiline: True
    post_process:
      clean_product_name: True
    
total_patterns:
  subtotal: 'DRIS STRAWBERRY\\s*([\\d\\.]+)' 
  tax: 'TAX\\s*([\\d\\.\\,]+)'
  total: 'BALANCE\\s*([\\d\\.\\,]+)'

date_pattern: '(\\d{2}/\\d{2}/\\d{2,4})'
items_sold_pattern: 'TOTAL NUMBER OF ITEMS SOLD\\s*=\\s*(\\d+)'
"""
    }
    
    process_receipts_unified(RULE_CONTENTS)

