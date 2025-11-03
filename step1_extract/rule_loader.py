#!/usr/bin/env python3
"""
Rule Loader - Load YAML rules from step1_rules directory
Supports merging shared.yaml with group-specific rules
"""

import yaml
import logging
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class RuleLoader:
    """Load and parse YAML rules, merging shared.yaml with group-specific rules"""
    
    def __init__(self, rules_dir: Path, enable_hot_reload: bool = False):
        """
        Initialize rule loader with rules directory
        
        Args:
            rules_dir: Path to step1_rules directory
            enable_hot_reload: Enable checksum-based hot-reload (default: False)
                              Set to True only during development/testing for rule changes
        """
        self.rules_dir = Path(rules_dir)
        self._rules_cache = {}
        self._file_checksums = {} if enable_hot_reload else None  # Only track when enabled
        self._enable_hot_reload = enable_hot_reload
        self._shared_rules = None  # Cache shared.yaml
    
    def _calculate_file_checksum(self, file_path: Path) -> str:
        """Calculate MD5 checksum for a file"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                return hashlib.md5(content).hexdigest()
        except Exception as e:
            logger.warning(f"Error calculating checksum for {file_path}: {e}")
            return ''
    
    def _should_reload_file(self, filename: str, rule_file: Path) -> bool:
        """Check if a rule file should be reloaded based on checksum"""
        # Fast path: when hot-reload is disabled, only check cache
        if not self._enable_hot_reload:
            return filename not in self._rules_cache
        
        if not rule_file.exists():
            return False
        
        # Hot-reload enabled: calculate checksum and compare
        current_checksum = self._calculate_file_checksum(rule_file)
        cached_checksum = self._file_checksums.get(filename)
        
        if current_checksum != cached_checksum:
            if cached_checksum:
                logger.debug(f"Rule file {filename} modified, reloading...")
            return True
        
        return False
    
    def _load_yaml_file(self, file_path: Path) -> Dict[str, Any]:
        """Load a YAML file directly"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error loading YAML file {file_path}: {e}")
            return {}
    
    def _load_shared_rules(self) -> Dict[str, Any]:
        """Load shared.yaml rules"""
        if self._shared_rules is None or self._should_reload_file('shared.yaml', self.rules_dir / 'shared.yaml'):
            shared_file = self.rules_dir / 'shared.yaml'
            if shared_file.exists():
                self._shared_rules = self._load_yaml_file(shared_file)
                if self._enable_hot_reload:
                    self._file_checksums['shared.yaml'] = self._calculate_file_checksum(shared_file)
                logger.debug("Loaded shared.yaml")
            else:
                self._shared_rules = {}
                logger.warning("shared.yaml not found")
        return self._shared_rules
    
    def get_legacy_enabled(self) -> bool:
        """
        Check if legacy parsers are enabled (feature flag)

        Returns:
            True if legacy parsers should be used, False otherwise
        """
        shared_rules = self._load_shared_rules()
        flags = shared_rules.get('flags', {})
        return flags.get('enable_legacy_parsers', True)  # Default to True for backward compatibility

    def get_tax_exempt_vendors(self) -> List[str]:
        """
        Get list of tax-exempt vendors (company has tax-exempt status)

        Returns:
            List of vendor codes that should have $0.00 tax
        """
        shared_rules = self._load_shared_rules()
        return shared_rules.get('tax_exempt_vendors', [])
    
    def _merge_rules(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two dictionaries
        override takes precedence over base
        """
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_rules(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def load_group_rules(self, group: str = 'group1') -> Dict[str, Any]:
        """
        Load group-specific rules and merge with shared.yaml
        
        Args:
            group: Group name ('group1' or 'group2')
            
        Returns:
            Merged rules dictionary
        """
        # Load shared rules
        shared_rules = self._load_shared_rules()
        
        # Load group-specific rules
        group_file = self.rules_dir / f'{group}.yaml' if group.endswith('.yaml') else self.rules_dir / f'{group}.yaml'
        if not group_file.exists():
            # Try alternative naming
            if group == 'group1':
                group_file = self.rules_dir / 'group1_excel.yaml'
            elif group == 'group2':
                group_file = self.rules_dir / 'group2_pdf.yaml'
        
        if group_file.exists():
            if self._should_reload_file(group_file.name, group_file):
                group_rules = self._load_yaml_file(group_file)
                self._rules_cache[group_file.name] = group_rules
                if self._enable_hot_reload:
                    self._file_checksums[group_file.name] = self._calculate_file_checksum(group_file)
                logger.debug(f"Loaded {group_file.name}")
            else:
                group_rules = self._rules_cache.get(group_file.name, {})
        else:
            logger.warning(f"Group rules file not found: {group_file}")
            group_rules = {}
        
        # Merge: group rules override shared rules
        merged = self._merge_rules(shared_rules, group_rules)
        
        # If group rules specify inherits, respect it
        if 'inherits' in group_rules and group_rules['inherits'] == 'shared.yaml':
            # Already merged above
            pass
        
        return merged
    
    def get_vendor_rule(self, vendor_name: Optional[str], group: str = 'group1') -> Optional[Dict[str, Any]]:
        """
        Get vendor-specific rules from group rules
        
        Args:
            vendor_name: Vendor name (e.g., 'Costco', 'Instacart') or None
            group: Group name ('group1' or 'group2')
            
        Returns:
            Vendor rules dictionary or None
        """
        if not vendor_name:
            return None
        
        rules = self.load_group_rules(group)
        vendors = rules.get('vendors', {})
        
        # Try exact match first
        if vendor_name in vendors:
            return vendors[vendor_name]
        
        # Try case-insensitive match
        vendor_lower = vendor_name.lower()
        for key, value in vendors.items():
            if key and key.lower() == vendor_lower:
                return value
        
        # Try identifier match
        for key, value in vendors.items():
            identifier = value.get('identifier', '')
            if identifier and identifier.lower() in vendor_lower:
                return value
        
        return None
    
    def get_validation_rules(self, group: str = 'group1') -> Dict[str, Any]:
        """Get validation rules for a group"""
        rules = self.load_group_rules(group)
        return rules.get('validation', {})
    
    # Legacy methods for backward compatibility (simplified - no markdown files)
    def load_all_rules(self, force_reload: bool = False) -> Dict[str, Dict[str, Any]]:
        """Load all rule files (legacy method - kept for backward compatibility)"""
        all_rules = {}
        
        # Load YAML group rules
        for group in ['group1', 'group2']:
            all_rules[f'{group}_rules'] = self.load_group_rules(group)
        
        # Return empty dicts for legacy rule names (markdown files removed, using YAML only)
        legacy_rule_names = [
            'vendor_identification',
            'item_line_parsing',
            'unit_detection',
            'validation',
            'error_handling',
            'instacart_csv_match',
            'fallback_rules',
        ]
        
        for rule_name in legacy_rule_names:
            all_rules[rule_name] = {}  # Return empty - rules now in YAML groups
        
        # Load vendor_profiles.yaml if it exists
        vendor_profiles_file = self.rules_dir / 'vendor_profiles.yaml'
        if vendor_profiles_file.exists():
            vendor_profiles_key = 'vendor_profiles.yaml'
            if force_reload or self._should_reload_file(vendor_profiles_key, vendor_profiles_file):
                all_rules['vendor_profiles'] = self._load_yaml_file(vendor_profiles_file)
                if self._enable_hot_reload:
                    self._file_checksums[vendor_profiles_key] = self._calculate_file_checksum(vendor_profiles_file)
            else:
                all_rules['vendor_profiles'] = self._rules_cache.get(vendor_profiles_key, {})
        else:
            all_rules['vendor_profiles'] = {}
        
        return all_rules
    
    def clear_cache(self):
        """Clear the rules cache"""
        logger.debug("Clearing rules cache")
        self._rules_cache.clear()
        self._file_checksums.clear()
        self._shared_rules = None
    
    def reload_all_rules(self) -> Dict[str, Dict[str, Any]]:
        """Force reload all rules"""
        self.clear_cache()
        return self.load_all_rules(force_reload=True)
    
    def get_instacart_csv_match_rules(self) -> Dict[str, Any]:
        """Get Instacart CSV matching rules from shared.yaml"""
        shared_rules = self._load_shared_rules()
        return shared_rules.get('instacart_csv_match', {})
    
    def get_ai_interpreter_rules(self) -> Dict[str, Any]:
        """Get AI line interpreter rules from shared.yaml"""
        shared_rules = self._load_shared_rules()
        return shared_rules.get('ai_line_interpreter', {})
    
    def get_ai_fallback_rules(self) -> Dict[str, Any]:
        """Get AI fallback rules from shared.yaml"""
        shared_rules = self._load_shared_rules()
        return shared_rules.get('ai_fallback', {})
    
    def get_group1_vendors(self) -> list:
        """Get list of Group 1 vendors from shared.yaml"""
        shared_rules = self._load_shared_rules()
        return shared_rules.get('group1_vendors', [])
    
    def get_vendor_normalization_rules(self) -> Dict[str, Any]:
        """Get vendor normalization rules from 40_vendor_normalization.yaml"""
        return self.load_rule_file_by_name('40_vendor_normalization.yaml')
    
    def get_text_parsing_rules(self, vendor: Optional[str] = None) -> Dict[str, Any]:
        """
        Get text parsing rules from 50_text_parsing.yaml
        
        Args:
            vendor: Optional vendor name to get vendor-specific parsing rules
                   (e.g., 'costco' or 'rd')
        
        Returns:
            Dictionary containing parsing rules
        """
        rules = self.load_rule_file_by_name('50_text_parsing.yaml')
        
        if vendor:
            vendor_lower = vendor.lower()
            if 'costco' in vendor_lower:
                return rules.get('costco_parsing', {})
            elif 'rd' in vendor_lower or 'restaurant depot' in vendor_lower:
                return rules.get('rd_parsing', {})
        
        return rules
    
    def get_vendor_profiles(self) -> Dict[str, Any]:
        """Get vendor profiles (YAML)"""
        vendor_profiles_file = self.rules_dir / 'vendor_profiles.yaml'
        if vendor_profiles_file.exists():
            return self._load_yaml_file(vendor_profiles_file)
        return {}
    
    def load_rule_file_by_name(self, filename: str) -> Dict[str, Any]:
        """
        Load a specific rule file by filename (e.g., '10_vendor_detection.yaml')
        
        Args:
            filename: Rule file name (e.g., '10_vendor_detection.yaml')
            
        Returns:
            Rule dictionary or empty dict if not found
        """
        rule_file = self.rules_dir / filename
        
        if not rule_file.exists():
            logger.warning(f"Rule file not found: {rule_file}")
            return {}

        if self._should_reload_file(filename, rule_file):
            rules = self._load_yaml_file(rule_file)
            self._rules_cache[filename] = rules or {}
            if self._enable_hot_reload:
                self._file_checksums[filename] = self._calculate_file_checksum(rule_file)
            logger.debug(f"Loaded rule file: {filename}")
            return self._rules_cache[filename]
        else:
            return self._rules_cache.get(filename, {})
    
    def get_vendor_detection_rules(self) -> Dict[str, Any]:
        """Get vendor detection rules from 10_vendor_detection.yaml"""
        rules = self.load_rule_file_by_name('10_vendor_detection.yaml')
        return rules.get('vendor_detection', {})
    
    def get_layout_rules(self, vendor_code: str) -> Optional[Dict[str, Any]]:
        """
        Get layout rules for a specific vendor
        
        Args:
            vendor_code: Vendor code (e.g., 'COSTCO', 'RD', 'JEWEL')
            
        Returns:
            Layout rules dictionary (with layouts array) or None
        """
        layout_files = {
            'COSTCO': '20_costco_layout.yaml',
            'RD': '21_rd_layout.yaml',
            'RESTAURANT_DEPOT': '21_rd_layout.yaml',
            'JEWEL': '22_jewel_layout.yaml',
            'JEWELOSCO': '22_jewel_layout.yaml',
            'MARIANOS': '22_jewel_layout.yaml',
            'ALDI': '23_aldi_layout.yaml',
            'PARKTOSHOP': '24_parktoshop_layout.yaml',
            'INSTACART': '26_instacart_pdf_layout.yaml',
        }
        
        # Normalize vendor code
        vendor_code_upper = vendor_code.upper() if vendor_code else ''
        
        layout_file = layout_files.get(vendor_code_upper)
        if not layout_file:
            # Try case-insensitive match
            for key, value in layout_files.items():
                if key.upper() == vendor_code_upper:
                    layout_file = value
                    break
        
        if layout_file:
            rules = self.load_rule_file_by_name(layout_file)
            # Return the first top-level key that's not 'meta' (now returns layouts list)
            for key, value in rules.items():
                if key != 'meta' and not key.startswith('_'):
                    return value
        
        return None
    
    def get_uom_extraction_rules(self) -> Dict[str, Any]:
        """Get UoM extraction rules from 30_uom_extraction.yaml"""
        rules = self.load_rule_file_by_name('30_uom_extraction.yaml')
        return rules.get('uom_extraction', {})
    
    def get_vendor_alias_rules(self) -> Dict[str, Any]:
        """Get vendor alias rules from 15_vendor_aliases.yaml"""
        rules = self.load_rule_file_by_name('15_vendor_aliases.yaml')
        return rules.get('vendor_aliases', [])
    
    def get_instacart_csv_rules(self) -> Dict[str, Any]:
        """
        Get Instacart CSV matching rules from 25_instacart_csv.yaml
        
        Returns:
            Instacart CSV configuration dictionary with files, id_fields, match_threshold
        """
        rules = self.load_rule_file_by_name('25_instacart_csv.yaml')
        return rules.get('instacart_csv', {})
    
    def get_multiline_config(self, vendor_code: Optional[str] = None, layout_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get multiline merging configuration based on vendor code and layout name
        
        Args:
            vendor_code: Vendor code (e.g., 'COSTCO', 'RD', 'JEWEL')
            layout_name: Matched layout name (e.g., 'Costco PDF Multiline', 'RD PDF Receipt')
            
        Returns:
            Multiline configuration dictionary with enabled, joiner, max_lines
        """
        shared_rules = self._load_shared_rules()
        multiline_rules = shared_rules.get('multiline_rules', {})
        
        # Try to match by layout name first (most specific)
        if layout_name:
            layout_name_lower = layout_name.lower().replace(' ', '_').replace('-', '_')
            # Try exact match
            if layout_name_lower in multiline_rules:
                config = multiline_rules[layout_name_lower]
                logger.debug(f"Using multiline config for layout: {layout_name}")
                return config
            
            # Try partial match (e.g., "costco_pdf_multiline" -> "costco_pdf")
            for key in multiline_rules.keys():
                if layout_name_lower.startswith(key) or key in layout_name_lower:
                    config = multiline_rules[key]
                    logger.debug(f"Using multiline config for layout pattern: {key}")
                    return config
        
        # Try to match by vendor code
        if vendor_code:
            vendor_code_lower = vendor_code.lower()
            # Map vendor codes to config keys
            vendor_config_map = {
                'costco': 'costco_pdf',
                'rd': 'rd_pdf',
                'restaurant_depot': 'rd_pdf',
                'jewel': 'jewel_pdf',
                'jewelosco': 'jewel_pdf',
                'marianos': 'jewel_pdf',
            }
            
            config_key = vendor_config_map.get(vendor_code_lower)
            if config_key and config_key in multiline_rules:
                config = multiline_rules[config_key]
                logger.debug(f"Using multiline config for vendor: {vendor_code}")
                return config
        
        # Fall back to default
        default_config = multiline_rules.get('default', {
            'enabled': True,
            'joiner': ' ',
            'max_lines': 2
        })
        logger.debug(f"Using default multiline config")
        return default_config