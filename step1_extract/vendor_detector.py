#!/usr/bin/env python3
"""
Vendor Detection - Apply vendor detection rules from 10_vendor_detection.yaml
Detects vendor from file path, filename, and receipt content
"""

import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class VendorDetector:
    """Detect vendor using rules from 10_vendor_detection.yaml"""
    
    def __init__(self, rule_loader):
        """
        Initialize vendor detector
        
        Args:
            rule_loader: RuleLoader instance
        """
        self.rule_loader = rule_loader
        self.detection_rules = rule_loader.get_vendor_detection_rules()
    
    def detect_vendor(self, file_path: Path, receipt_data: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Detect vendor code and source type from file path and receipt data
        
        Args:
            file_path: Path to receipt file
            receipt_data: Optional receipt data dictionary (for content-based detection)
            
        Returns:
            Tuple of (detected_vendor_code, detected_source_type)
        """
        filename_lower = file_path.name.lower()
        path_lower = str(file_path).lower()
        
        # Get detection order
        detection_order = self.detection_rules.get('detection_order', ['filename_path', 'receipt_content'])
        
        # Try filename/path detection first
        if 'filename_path' in detection_order:
            vendor_code, source_type = self._detect_from_filename_path(file_path)
            if vendor_code:
                logger.debug(f"Detected vendor from filename/path: {vendor_code} ({source_type})")
                return vendor_code, source_type
        
        # Try content-based detection if receipt data is available
        if 'receipt_content' in detection_order and receipt_data:
            vendor_code, source_type = self._detect_from_content(receipt_data)
            if vendor_code:
                logger.debug(f"Detected vendor from receipt content: {vendor_code} ({source_type})")
                return vendor_code, source_type
        
        # Fallback
        fallback = self.detection_rules.get('fallback', {})
        default_vendor_code = fallback.get('default_vendor_code', 'UNKNOWN')
        default_source_type = fallback.get('default_source_type', 'vendor_based')
        
        logger.warning(f"Could not detect vendor for {file_path.name}, using fallback: {default_vendor_code} ({default_source_type})")
        return default_vendor_code, default_source_type
    
    def _detect_from_filename_path(self, file_path: Path) -> Tuple[Optional[str], Optional[str]]:
        """Detect vendor from filename and path patterns"""
        filename_lower = file_path.name.lower()
        path_lower = str(file_path).lower()
        
        filename_patterns = self.detection_rules.get('filename_patterns', {})
        folder_patterns = self.detection_rules.get('folder_patterns', {})
        
        # Try folder-based detection for source_type first
        detected_source_type = None
        try:
            rel_path = file_path.relative_to(file_path.parents[-2] if len(file_path.parents) > 2 else Path.cwd())
            folder_name = str(rel_path.parent).lower()
            
            for pattern_group, config in folder_patterns.items():
                patterns = config.get('patterns', [])
                for pattern in patterns:
                    if pattern in folder_name:
                        detected_source_type = config.get('source_type')
                        break
                if detected_source_type:
                    break
        except:
            pass
        
        # Try filename patterns
        for vendor_name, config in filename_patterns.items():
            patterns = config.get('patterns', [])
            for pattern in patterns:
                if pattern in filename_lower or pattern in path_lower:
                    vendor_code = config.get('vendor_code')
                    source_type = config.get('source_type') or detected_source_type
                    return vendor_code, source_type
        
        return None, detected_source_type
    
    def _detect_from_content(self, receipt_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Detect vendor from receipt content keywords"""
        # Build searchable text from receipt data
        text_parts = []
        
        # Add vendor field if present
        vendor = receipt_data.get('vendor', '')
        if vendor:
            text_parts.append(str(vendor))
        
        # Add receipt text if present
        receipt_text = receipt_data.get('receipt_text', '')
        if receipt_text:
            text_parts.append(str(receipt_text))
        
        # Add filename if present
        filename = receipt_data.get('filename', '')
        if filename:
            text_parts.append(str(filename))
        
        searchable_text = ' '.join(text_parts).lower()
        
        # Check content keywords
        content_keywords = self.detection_rules.get('content_keywords', {})
        
        best_match = None
        best_confidence = 0.0
        
        for vendor_name, config in content_keywords.items():
            keywords = config.get('keywords', [])
            confidence = config.get('confidence', 0.5)
            
            # Count keyword matches
            matches = sum(1 for keyword in keywords if keyword.lower() in searchable_text)
            if matches > 0:
                # Calculate score based on keyword matches
                score = (matches / len(keywords)) * confidence if len(keywords) > 0 else 0.0
                
                if score > best_confidence:
                    best_confidence = score
                    best_match = {
                        'vendor_code': config.get('vendor_code'),
                        'source_type': config.get('source_type'),
                        'confidence': score
                    }
        
        if best_match:
            return best_match['vendor_code'], best_match['source_type']
        
        return None, None
    
    def apply_detection_to_receipt(self, file_path: Path, receipt_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply vendor detection to a receipt and add detected_vendor_code and detected_source_type
        
        Args:
            file_path: Path to receipt file
            receipt_data: Receipt data dictionary (will be modified in-place)
            
        Returns:
            Modified receipt data dictionary
        """
        detected_vendor_code, detected_source_type = self.detect_vendor(file_path, receipt_data)
        
        # Add detected fields to receipt data
        receipt_data['detected_vendor_code'] = detected_vendor_code
        receipt_data['detected_source_type'] = detected_source_type
        
        # If vendor is not already set, use detected vendor
        if not receipt_data.get('vendor'):
            receipt_data['vendor'] = detected_vendor_code
        
        logger.debug(f"Applied vendor detection to {file_path.name}: {detected_vendor_code} ({detected_source_type})")
        
        return receipt_data

