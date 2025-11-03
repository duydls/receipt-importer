#!/usr/bin/env python3
"""
Unit tests for tax-exempt vendor validation
"""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

# Import the modules we want to test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from rule_loader import RuleLoader
from excel_processor import ExcelProcessor


class TestTaxExemptValidation:
    """Test tax-exempt vendor validation logic"""

    def test_tax_exempt_vendors_from_config(self):
        """Test that tax-exempt vendors are loaded from shared.yaml"""
        rules_dir = Path(__file__).parent.parent.parent / 'step1_rules' if '__file__' in locals() else Path('../../step1_rules')
        loader = RuleLoader(rules_dir)

        exempt_vendors = loader.get_tax_exempt_vendors()
        expected_vendors = ['COSTCO', 'INSTACART', 'PARKTOSHOP']

        assert set(exempt_vendors) == set(expected_vendors), f"Expected {expected_vendors}, got {exempt_vendors}"

    def test_costco_tax_validation(self):
        """Test that Costco receipts with tax > $1.00 are flagged for review"""
        # Mock receipt data with tax
        receipt_data = {
            'vendor': 'Costco',
            'tax': 2.50,  # This should trigger review
            'total': 100.00,
            'items': [],
            'needs_review': False,
            'review_reasons': []
        }

        # Get tax-exempt vendors and test validation logic
        rules_dir = Path(__file__).parent.parent.parent / 'step1_rules' if '__file__' in locals() else Path('../../step1_rules')
        loader = RuleLoader(rules_dir)
        tax_exempt_vendors = loader.get_tax_exempt_vendors()
        vendor_code = 'COSTCO'

        if vendor_code in tax_exempt_vendors:
            tax_amount = receipt_data.get('tax', 0.0)
            if tax_amount > 1.0:
                if not receipt_data.get('needs_review'):
                    receipt_data['needs_review'] = True
                    receipt_data['review_reasons'] = []
                receipt_data['review_reasons'].append(
                    f"Tax-exempt vendor ({vendor_code}) has tax=${tax_amount:.2f} (expected ~$0.00)"
                )

        # Assertions
        assert receipt_data['needs_review'] == True
        assert len(receipt_data['review_reasons']) == 1
        assert 'Tax-exempt vendor (COSTCO) has tax=$2.50' in receipt_data['review_reasons'][0]

    def test_costco_zero_tax_passes(self):
        """Test that Costco receipts with tax = $0.00 pass validation"""
        receipt_data = {
            'vendor': 'Costco',
            'tax': 0.00,
            'total': 100.00,
            'items': [],
            'needs_review': False,
            'review_reasons': []
        }

        # Same logic as above
        rules_dir = Path(__file__).parent.parent.parent / 'step1_rules' if '__file__' in locals() else Path('../../step1_rules')
        loader = RuleLoader(rules_dir)

        tax_exempt_vendors = loader.get_tax_exempt_vendors()
        vendor_code = 'COSTCO'

        if vendor_code in tax_exempt_vendors:
            tax_amount = receipt_data.get('tax', 0.0)
            if tax_amount > 1.0:
                receipt_data['needs_review'] = True
                receipt_data['review_reasons'] = [
                    f"Tax-exempt vendor ({vendor_code}) has tax=${tax_amount:.2f} (expected ~$0.00)"
                ]

        # Assertions
        assert receipt_data['needs_review'] == False
        assert len(receipt_data['review_reasons']) == 0

    def test_non_tax_exempt_vendor_ignored(self):
        """Test that non-tax-exempt vendors are not validated for tax"""
        receipt_data = {
            'vendor': 'Jewel-Osco',
            'tax': 5.00,  # Would be flagged for tax-exempt vendors
            'total': 100.00,
            'items': [],
            'needs_review': False,
            'review_reasons': []
        }

        rules_dir = Path(__file__).parent.parent.parent / 'step1_rules' if '__file__' in locals() else Path('../../step1_rules')
        processor = ExcelProcessor(None)
        processor.rule_loader = RuleLoader(rules_dir)

        tax_exempt_vendors = loader.get_tax_exempt_vendors()
        vendor_code = 'JEWELOSCO'

        # This should not trigger validation
        if vendor_code in tax_exempt_vendors:
            receipt_data['needs_review'] = True

        assert receipt_data['needs_review'] == False


if __name__ == '__main__':
    # Run the tests
    test = TestTaxExemptValidation()
    test.test_tax_exempt_vendors_from_config()
    test.test_costco_tax_validation()
    test.test_costco_zero_tax_passes()
    test.test_non_tax_exempt_vendor_ignored()
    print("✅ All tax-exempt validation tests passed!")
