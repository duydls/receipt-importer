#!/usr/bin/env python3
"""
Rule Loader - Load YAML rules from step2_rules directory
Loads rules in processing order and provides access to rule configurations
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class RuleLoader:
    """Load and parse YAML rules from step2_rules directory"""
    
    def __init__(self, rules_dir: Path):
        """
        Initialize rule loader with rules directory
        
        Args:
            rules_dir: Path to step2_rules directory
        """
        self.rules_dir = Path(rules_dir)
        self._rules_cache: Dict[str, Dict[str, Any]] = {}
        self._processing_order: List[str] = []
        self._load_all_rules()
    
    def _load_yaml_file(self, file_path: Path) -> Dict[str, Any]:
        """Load a YAML file directly"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error loading YAML file {file_path}: {e}")
            return {}
    
    def _load_all_rules(self) -> None:
        """Load all rule files from step2_rules directory"""
        if not self.rules_dir.exists():
            logger.error(f"Rules directory not found: {self.rules_dir}")
            return
        
        # Load meta.yaml first to get processing order
        meta_file = self.rules_dir / '00_meta.yaml'
        if meta_file.exists():
            meta_data = self._load_yaml_file(meta_file)
            self._rules_cache['meta'] = meta_data
            self._processing_order = meta_data.get('processing_order', [])
            logger.info(f"Loaded meta.yaml with {len(self._processing_order)} processing stages")
        else:
            logger.warning("00_meta.yaml not found, will try to load all numbered YAML files")
        
        # Load all numbered rule files
        rule_files = sorted(self.rules_dir.glob('[0-9][0-9]_*.yaml'))
        for rule_file in rule_files:
            if rule_file.name == '00_meta.yaml':
                continue  # Already loaded
            
            filename = rule_file.name
            rule_data = self._load_yaml_file(rule_file)
            if rule_data:
                self._rules_cache[filename] = rule_data
                # Add to processing order if not already there
                if filename not in self._processing_order:
                    self._processing_order.append(filename)
                logger.debug(f"Loaded rule file: {filename}")
        
        logger.info(f"Loaded {len(self._rules_cache)} rule files")
    
    def get_meta(self) -> Dict[str, Any]:
        """Get meta information from 00_meta.yaml"""
        return self._rules_cache.get('meta', {})
    
    def get_processing_order(self) -> List[str]:
        """Get ordered list of rule files to process"""
        return self._processing_order.copy()
    
    def get_rule(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Get rule data for a specific file
        
        Args:
            filename: Name of the rule file (e.g., '01_inputs.yaml')
            
        Returns:
            Dictionary containing rule data, or None if not found
        """
        return self._rules_cache.get(filename)
    
    def get_all_rules(self) -> Dict[str, Dict[str, Any]]:
        """Get all loaded rules"""
        return self._rules_cache.copy()
    
    def get_stage_config(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific processing stage
        
        Args:
            stage_name: Stage name (e.g., 'inputs', 'vendor_match', 'db_match')
            
        Returns:
            Configuration dictionary for the stage, or None if not found
        """
        # Search through all rule files for the stage
        for filename, rule_data in self._rules_cache.items():
            if stage_name in rule_data:
                return rule_data[stage_name]
        
        return None

