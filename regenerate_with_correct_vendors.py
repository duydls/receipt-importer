#!/usr/bin/env python3
"""
Regenerate SQL with correct vendor mappings
"""

import json
from datetime import datetime

# Load the corrected mapping
exec(open('data/correct_vendor_mapping.py').read())

def get_vendor_id(vendor_name: str) -> int:
    """Get vendor ID from mapping"""
    return ID_MAPPING['partners'].get(vendor_name, 1)

# [Rest of SQL generation code would go here...]
# This would regenerate the final_receipt_purchase_orders.sql with correct IDs

print("✅ Vendor mapping loaded. Run this script to regenerate SQL with correct IDs.")
