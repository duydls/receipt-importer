"""
Step 2: Generate Mapping File
Matches receipt products to database products and creates/updates the mapping file.
Executes rules from step2_rules folder to process receipt items.
"""

from .product_matcher import ProductMatcher
from .rule_loader import RuleLoader
from .main import process_rules, load_step1_output, combine_receipts

__all__ = ['ProductMatcher', 'RuleLoader', 'process_rules', 'load_step1_output', 'combine_receipts']

