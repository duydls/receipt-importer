#!/usr/bin/env python3
"""
Address Filter - Skip address lines in receipts
"""

import re
import logging
from typing import List

logger = logging.getLogger(__name__)


class AddressFilter:
    """Filter out address lines from receipt text"""
    
    def __init__(self):
        """Initialize address filter patterns"""
        # Common address patterns
        self.address_patterns = [
            # Street addresses (e.g., "123 Main St", "2746 N CLYBOURN AVE")
            re.compile(r'\d+\s+[A-Z0-9\s]+(?:ST|STREET|AVE|AVENUE|BLVD|BOULEVARD|RD|ROAD|DR|DRIVE|LN|LANE|PL|PLACE|CT|COURT)', re.IGNORECASE),
            # City, State ZIP (e.g., "CHICAGO, IL 60614")
            re.compile(r'[A-Z\s]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?', re.IGNORECASE),
            # ZIP code patterns (e.g., "60614", "60614-1234")
            re.compile(r'^\d{5}(?:-\d{4})?$'),
            # Store location headers (e.g., "LINCOLN PARK #380")
            re.compile(r'^[A-Z\s]+#\d+$'),
            # Phone numbers (often in address blocks)
            re.compile(r'^\d{3}[-.\s]?\d{3}[-.\s]?\d{4}$'),
            # Store numbers with names (e.g., "Warehouse #380", "Store #123")
            re.compile(r'(?:WAREHOUSE|STORE|SHOP|LOCATION)\s*#?\d+', re.IGNORECASE),
            # Address blocks with member numbers (e.g., "Member 112016081379")
            re.compile(r'^Member\s+\d+$', re.IGNORECASE),
        ]
        
        # Keywords that indicate address lines
        self.address_keywords = [
            'address', 'street', 'st', 'avenue', 'ave', 'boulevard', 'blvd',
            'road', 'rd', 'drive', 'dr', 'lane', 'ln', 'place', 'pl', 'court', 'ct',
            'warehouse', 'store', 'location', 'shop',
        ]
    
    def is_address_line(self, line: str) -> bool:
        """
        Check if a line is an address line
        
        Args:
            line: Line to check
            
        Returns:
            True if line appears to be an address, False otherwise
        """
        line = line.strip()
        
        # Skip empty lines
        if not line:
            return False
        
        # Check against patterns
        for pattern in self.address_patterns:
            if pattern.search(line):
                return True
        
        # Check for address keywords
        line_lower = line.lower()
        for keyword in self.address_keywords:
            if keyword in line_lower:
                # Additional check: if it contains numbers, it's likely an address
                if re.search(r'\d', line):
                    return True
        
        # Check for city, state format (e.g., "CHICAGO, IL")
        if re.search(r'^[A-Z\s]+,\s*[A-Z]{2}\s*$', line):
            return True
        
        return False
    
    def filter_address_lines(self, lines: List[str]) -> List[str]:
        """
        Filter out address lines from a list of lines
        
        Args:
            lines: List of receipt lines
            
        Returns:
            Filtered list without address lines
        """
        filtered = []
        for line in lines:
            if not self.is_address_line(line):
                filtered.append(line)
            else:
                logger.debug(f"Skipping address line: {line[:50]}")
        
        return filtered
    
    def filter_text(self, text: str) -> str:
        """
        Filter out address lines from receipt text
        
        Args:
            text: Receipt text
            
        Returns:
            Filtered text without address lines
        """
        lines = text.split('\n')
        filtered_lines = self.filter_address_lines(lines)
        return '\n'.join(filtered_lines)

