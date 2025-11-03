#!/usr/bin/env python3
"""
Fee Extractor - Extract fees from receipts and match to fee products
"""

import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class FeeExtractor:
    """Extract and match fees to products"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.fee_config = config.get('FEE_PRODUCTS', {}) if config else {}
    
    def extract_fees_from_receipt_text(self, text: str) -> List[Dict]:
        """
        Extract fees from receipt text
        Supports optional dollar signs and additional fee types (Environmental, CRV, Deposit)
        
        Args:
            text: Receipt text content
            
        Returns:
            List of fee dictionaries
        """
        fees = []
        found_fee_types = set()  # Track found types to avoid duplicates
        
        # Pattern for fees (matching common PDF receipt formats)
        # Dollar signs are optional, numbers near "Fee" are captured
        fee_patterns = {
            'bag_fee': [
                r'(?:Checkout\s+)?Bag\s+Fee[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Bag\s+Fee[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Bags?[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
            ],
            'tip': [
                r'Grocery\s+Tip[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Delivery\s+Tip[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Tip[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
            ],
            'service_fee': [
                r'Instacart\s+Service\s+Fee[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Service\s+Fee[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Delivery\s+Fee[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
            ],
            'environmental_fee': [
                r'Environmental\s+Fee[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Enviro\s+Fee[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Env\s+Fee[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
            ],
            'crv': [
                r'CRV[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'California\s+Redemption\s+Value[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Bottle\s+Deposit[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
            ],
            'deposit': [
                r'Deposit[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
                r'Container\s+Deposit[:\s]+(?:\$?\s*)?(\d+\.\d{2})',
            ],
            'delivery_discount': [
                r'Scheduled\s+delivery\s+discount[:\s]+(?:-\$?\s*)?(\d+\.\d{2})',
                r'Delivery\s+discount[:\s]+(?:-\$?\s*)?(\d+\.\d{2})',
                r'Scheduled\s+discount[:\s]+(?:-\$?\s*)?(\d+\.\d{2})',
            ],
        }
        
        # Fallback: match numbers near "Fee" keyword (for cases where $ is missing)
        fee_fallback_pattern = r'\bFee[:\s]+(?:\$?\s*)?(\d+\.\d{2})\b'
        
        for fee_type, patterns in fee_patterns.items():
            if fee_type in found_fee_types:
                continue  # Skip if already found
            
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    try:
                        amount = float(match.group(1))
                        # For discounts, amount should be negative
                        if fee_type == 'delivery_discount':
                            amount = -amount  # Make it negative
                        
                        fee_name = self._get_fee_product_name(fee_type)
                        
                        fees.append({
                            'type': fee_type,
                            'name': fee_name,
                            'amount': amount,
                        })
                        
                        found_fee_types.add(fee_type)
                        
                        # Log with confidence information (position and matched text)
                        logger.debug(f"[{fee_type}] Detected at {match.start()} with text: {match.group(0)}")
                        logger.debug(f"Extracted {fee_type}: {fee_name} = ${amount:.2f}")
                        break  # Only extract once per fee type
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Error parsing fee amount from match {match.group(0)}: {e}")
                        continue
        
        # Fallback: if no specific fee patterns matched, try generic "Fee" pattern
        if not fees:
            fallback_match = re.search(fee_fallback_pattern, text, re.IGNORECASE)
            if fallback_match:
                try:
                    amount = float(fallback_match.group(1))
                    logger.debug(f"[Fee (fallback)] Detected at {fallback_match.start()} with text: {fallback_match.group(0)}")
                    fees.append({
                        'type': 'fee',
                        'name': 'Fee',
                        'amount': amount,
                    })
                except (ValueError, IndexError) as e:
                    logger.warning(f"Error parsing fallback fee amount: {e}")
        
        return fees
    
    def _get_fee_product_name(self, fee_type: str) -> str:
        """Get fee product name from config"""
        fee_config = self.fee_config.get(fee_type, {})
        search_names = fee_config.get('search_names', [])
        
        if search_names:
            return search_names[0]  # Return first search name as product name
        
        # Default names (extended with new fee types)
        defaults = {
            'bag_fee': 'Checkout Bag Fee',
            'tip': 'Grocery Tip',
            'service_fee': 'Instacart Service Fee',
            'environmental_fee': 'Environmental Fee',
            'crv': 'CRV (California Redemption Value)',
            'deposit': 'Deposit',
            'delivery_discount': 'Scheduled delivery discount',
            'fee': 'Fee',  # Generic fallback
        }
        
        return defaults.get(fee_type, fee_type.replace('_', ' ').title())
    
    def add_fees_to_receipt_items(self, receipt_data: Dict, fees: List[Dict]) -> Dict:
        """
        Add fees as separate line items to receipt data
        Appends a "Fees Total" summary line for reconciliation
        
        Args:
            receipt_data: Receipt data dictionary
            fees: List of fee dictionaries
            
        Returns:
            Updated receipt data
        """
        if not fees:
            return receipt_data
        
        fees_total = 0.0
        
        for fee in fees:
            fee_item = {
                'product_name': fee.get('name', ''),
                'quantity': 1.0,
                'purchase_uom': 'each',
                'unit_price': fee.get('amount', 0),
                'total_price': fee.get('amount', 0),
                'is_fee': True,  # Flag as fee product
                'fee_type': fee.get('type', ''),
            }
            
            receipt_data['items'].append(fee_item)
            fees_total += fee.get('amount', 0)
            logger.info(f"Added fee item: {fee['name']} = ${fee['amount']:.2f}")
        
        # Recalculate subtotal (items only, excluding fees)
        # Total will be set from CSV baseline file for Instacart receipts
        item_only_items = [item for item in receipt_data['items'] if not item.get('is_fee', False)]
        receipt_data['subtotal'] = sum(item['total_price'] for item in item_only_items)
        
        # Only recalculate total if not already set (e.g., from CSV baseline)
        if not receipt_data.get('total'):
            receipt_data['total'] = receipt_data['subtotal'] + fees_total
        
        return receipt_data



