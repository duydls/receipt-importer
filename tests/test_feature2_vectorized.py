#!/usr/bin/env python3
"""
Feature 2 Tests: Vectorized DataFrame Extraction
Tests correctness parity and fallback behavior for vectorized extraction.
"""

import os
import unittest
import pandas as pd
from pathlib import Path

# Setup path
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
os.chdir(PROJECT_ROOT)

from step1_extract.rule_loader import RuleLoader
from step1_extract.layout_applier import LayoutApplier


class TestFeature2Vectorized(unittest.TestCase):
    """Test Feature 2: Vectorized DataFrame Extraction"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.rules_dir = PROJECT_ROOT / 'step1_rules'
        cls.rule_loader = RuleLoader(cls.rules_dir)
        cls.layout_applier = LayoutApplier(cls.rule_loader)
        
    def test_parity_costco_7items(self):
        """Test 1: Parity for Costco_0907.xlsx (7 items)"""
        # Load actual file
        file_path = PROJECT_ROOT / 'data/step1_input/Costco/Costco_0907.xlsx'
        if not file_path.exists():
            self.skipTest(f"Test file not found: {file_path}")
        
        # Read and prepare DataFrame
        df = pd.read_excel(file_path, engine='openpyxl')
        
        # Get Costco layout
        layouts = self.rule_loader.get_layout_rules('COSTCO')
        self.assertIsNotNone(layouts, "Costco layouts should exist")
        self.assertGreater(len(layouts), 0, "Should have at least one Costco layout")
        
        layout = layouts[0]
        vendor_code = 'COSTCO'
        
        # Test vectorized extraction
        ctx_vec = {}
        self.layout_applier._vectorize_enabled = True
        items_vec = self.layout_applier._extract_items_from_layout_vectorized(
            df, layout, vendor_code, ctx=ctx_vec
        )
        
        # Test iterrows extraction
        ctx_iter = {}
        items_iter = self.layout_applier._extract_items_from_layout(
            df, layout, vendor_code, ctx=ctx_iter
        )
        
        # Assert item count matches
        self.assertEqual(len(items_vec), 7, "Vectorized should extract 7 items")
        self.assertEqual(len(items_iter), 7, "Iterrows should extract 7 items")
        
        # Assert control lines extracted to context
        self.assertIn('grand_total', ctx_vec, "Context should contain grand_total")
        self.assertIn('tax_total', ctx_vec, "Context should contain tax_total")
        
        # Verify control lines don't appear in items
        for item in items_vec:
            name = item.get('product_name', '').lower()
            self.assertNotIn('total', name, "Control lines should not appear in items")
            self.assertNotIn('tax', name, "Control lines should not appear in items")
    
    def test_fallback_control_lines_only(self):
        """Test 2: Fallback when DataFrame only contains control lines"""
        # Create a tiny DataFrame with only control lines
        df = pd.DataFrame({
            'Item Description': ['SUBTOTAL', 'TAX', 'TOTAL'],
            'Extended Amount (USD)': [100.0, 10.0, 110.0]
        })
        
        # Get any layout
        layouts = self.rule_loader.get_layout_rules('COSTCO')
        layout = layouts[0] if layouts else {
            'column_mappings': {
                'product_name': 'Item Description',
                'total_price': 'Extended Amount (USD)'
            },
            'skip_patterns': []
        }
        
        vendor_code = 'COSTCO'
        
        # Test vectorized extraction - should return 0 items
        ctx = {}
        self.layout_applier._vectorize_enabled = True
        items = self.layout_applier._extract_items_from_layout_vectorized(
            df, layout, vendor_code, ctx=ctx
        )
        
        # Should return 0 items (only control lines)
        self.assertEqual(len(items), 0, "Should return 0 items for control-only DataFrame")
        
        # Context should be populated
        self.assertGreater(len(ctx), 0, "Context should contain control line values")
    
    def test_vectorized_toggle(self):
        """Test 3: RECEIPTS_VECTORIZE environment variable toggle"""
        # Save original value
        original_env = os.environ.get('RECEIPTS_VECTORIZE', '1')
        
        try:
            # Test enabled (default)
            os.environ['RECEIPTS_VECTORIZE'] = '1'
            applier_enabled = LayoutApplier(self.rule_loader)
            self.assertTrue(applier_enabled._vectorize_enabled, "Should be enabled by default")
            
            # Test disabled
            os.environ['RECEIPTS_VECTORIZE'] = '0'
            applier_disabled = LayoutApplier(self.rule_loader)
            self.assertFalse(applier_disabled._vectorize_enabled, "Should be disabled when set to 0")
        finally:
            # Restore original value
            if original_env:
                os.environ['RECEIPTS_VECTORIZE'] = original_env
            elif 'RECEIPTS_VECTORIZE' in os.environ:
                del os.environ['RECEIPTS_VECTORIZE']
    
    def test_numeric_cleaning(self):
        """Test 4: Vectorized numeric cleaning handles various formats"""
        # Create DataFrame with various numeric formats
        df = pd.DataFrame({
            'Item Description': ['Product 1', 'Product 2', 'Product 3', 'Product 4'],
            'QTY': [2, '3', ' 4 ', ''],
            'Unit Price': ['$10.50', '20', '(5.00)', '$15.99'],
            'Extended Amount (USD)': ['$21.00', '60.00', '(20.00)', '$31.98']
        })
        
        layout = {
            'column_mappings': {
                'product_name': 'Item Description',
                'quantity': 'QTY',
                'unit_price': 'Unit Price',
                'total_price': 'Extended Amount (USD)'
            },
            'skip_patterns': []
        }
        
        ctx = {}
        items = self.layout_applier._extract_items_from_layout_vectorized(
            df, layout, 'TEST', ctx=ctx
        )
        
        # Verify all 4 items extracted
        self.assertEqual(len(items), 4, "Should extract 4 items")
        
        # Verify numeric cleaning
        self.assertEqual(items[0]['quantity'], 2.0)
        self.assertEqual(items[0]['unit_price'], 10.50)
        self.assertEqual(items[0]['total_price'], 21.00)
        
        # Verify negative handling
        self.assertEqual(items[2]['unit_price'], -5.00)
        self.assertEqual(items[2]['total_price'], -20.00)


if __name__ == '__main__':
    unittest.main()

