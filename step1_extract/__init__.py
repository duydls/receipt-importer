"""
Step 1: Extract Data from Receipts
Reads PDF, Excel, and CSV files and extracts structured receipt data.
Uses rule-driven architecture with vendor detection, layout application, and UoM extraction.
"""

from .main import process_files, detect_group
from .rule_loader import RuleLoader
from .vendor_detector import VendorDetector
from .layout_applier import LayoutApplier
from .receipt_line_engine import ReceiptLineEngine
from .uom_extractor import UoMExtractor
from .receipt_processor import ReceiptProcessor
from .csv_processor import CSVProcessor
from .fee_extractor import FeeExtractor
from .utils.text_extractor import TextExtractor
from .instacart_csv_matcher import InstacartCSVMatcher
from .vendor_profiles import VendorProfileHandler
from .receipt_parsers import VendorIdentifier, ItemLineParser, UnitDetector, TotalValidator

# Optional AI line interpreter (gracefully handles ImportError)
try:
    from .ai_line_interpreter import AILineInterpreter, AI_AVAILABLE, AI_BACKEND
    __all__ = [
        'process_files',
        'detect_group',
        'RuleLoader',
        'VendorDetector',
        'LayoutApplier',
        'ReceiptLineEngine',
        'UoMExtractor',
        'ReceiptProcessor', 
        'CSVProcessor', 
        'FeeExtractor',
        'TextExtractor',
        'InstacartCSVMatcher',
        'VendorProfileHandler',
        'VendorIdentifier',
        'ItemLineParser',
        'UnitDetector',
        'TotalValidator',
        'AILineInterpreter',
        'AI_AVAILABLE',
        'AI_BACKEND',
    ]
except ImportError:
    __all__ = [
        'process_files',
        'detect_group',
        'RuleLoader',
        'VendorDetector',
        'LayoutApplier',
        'ReceiptLineEngine',
        'UoMExtractor',
        'ReceiptProcessor', 
        'CSVProcessor', 
        'FeeExtractor',
        'TextExtractor',
        'InstacartCSVMatcher',
        'VendorProfileHandler',
        'VendorIdentifier',
        'ItemLineParser',
        'UnitDetector',
        'TotalValidator',
    ]

