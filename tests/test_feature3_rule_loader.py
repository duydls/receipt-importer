#!/usr/bin/env python3
"""
Feature 3 Tests: Rule Loader Fast-Path (Hot-Reload OFF by default)
Tests that hot-reload is disabled by default and can be toggled via environment variable.
"""

import os
import unittest
from pathlib import Path

# Setup path
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
os.chdir(PROJECT_ROOT)

from step1_extract.rule_loader import RuleLoader


class TestFeature3RuleLoader(unittest.TestCase):
    """Test Feature 3: Rule Loader Fast-Path"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.rules_dir = PROJECT_ROOT / 'step1_rules'
    
    def test_hot_reload_default_off(self):
        """Test that hot-reload is OFF by default"""
        loader = RuleLoader(self.rules_dir)
        self.assertFalse(loader._enable_hot_reload, "Hot-reload should be OFF by default")
        self.assertIsNone(loader._file_checksums, "File checksums should not be tracked when hot-reload is OFF")
    
    def test_hot_reload_explicit_on(self):
        """Test that hot-reload can be explicitly enabled"""
        loader = RuleLoader(self.rules_dir, enable_hot_reload=True)
        self.assertTrue(loader._enable_hot_reload, "Hot-reload should be ON when explicitly enabled")
        self.assertIsNotNone(loader._file_checksums, "File checksums should be tracked when hot-reload is ON")
        self.assertIsInstance(loader._file_checksums, dict)
    
    def test_hot_reload_env_variable(self):
        """Test that RECEIPTS_HOT_RELOAD=1 enables hot-reload"""
        # Save original value
        original_env = os.environ.get('RECEIPTS_HOT_RELOAD')
        
        try:
            # Test enabled via env var
            os.environ['RECEIPTS_HOT_RELOAD'] = '1'
            loader_on = RuleLoader(self.rules_dir)
            self.assertTrue(loader_on._enable_hot_reload, "Hot-reload should be ON when RECEIPTS_HOT_RELOAD=1")
            
            # Test disabled (default)
            os.environ['RECEIPTS_HOT_RELOAD'] = '0'
            loader_off = RuleLoader(self.rules_dir)
            self.assertFalse(loader_off._enable_hot_reload, "Hot-reload should be OFF when RECEIPTS_HOT_RELOAD=0")
            
            # Test unset (default)
            del os.environ['RECEIPTS_HOT_RELOAD']
            loader_default = RuleLoader(self.rules_dir)
            self.assertFalse(loader_default._enable_hot_reload, "Hot-reload should be OFF when env var unset")
        finally:
            # Restore original value
            if original_env:
                os.environ['RECEIPTS_HOT_RELOAD'] = original_env
            elif 'RECEIPTS_HOT_RELOAD' in os.environ:
                del os.environ['RECEIPTS_HOT_RELOAD']
    
    def test_no_duplicate_reads_hot_reload_off(self):
        """Test that files are read only once when hot-reload is OFF"""
        loader = RuleLoader(self.rules_dir, enable_hot_reload=False)
        
        # First load
        loader.reset_file_read_count()
        shared1 = loader._load_shared_rules()
        first_read_count = loader.get_file_read_count()
        
        self.assertGreater(first_read_count, 0, "Should have read at least one file")
        
        # Second load - should use cache
        shared2 = loader._load_shared_rules()
        second_read_count = loader.get_file_read_count()
        
        self.assertEqual(second_read_count, first_read_count, 
                        "Should not re-read files when hot-reload is OFF")
        self.assertEqual(shared1, shared2, "Cached rules should match original")
    
    def test_no_duplicate_reads_layout_rules(self):
        """Test that layout rules are cached when hot-reload is OFF"""
        loader = RuleLoader(self.rules_dir, enable_hot_reload=False)
        
        # First load
        loader.reset_file_read_count()
        costco1 = loader.get_layout_rules('COSTCO')
        first_read_count = loader.get_file_read_count()
        
        self.assertGreater(len(costco1), 0, "Should have loaded Costco layouts")
        self.assertGreater(first_read_count, 0, "Should have read at least one file")
        
        # Second load - should use cache
        costco2 = loader.get_layout_rules('COSTCO')
        second_read_count = loader.get_file_read_count()
        
        self.assertEqual(second_read_count, first_read_count,
                        "Should not re-read layout files when hot-reload is OFF")
        self.assertEqual(costco1, costco2, "Cached layouts should match original")
    
    def test_reload_works_when_hot_reload_on(self):
        """Test that hot-reload detects changes when ON"""
        loader = RuleLoader(self.rules_dir, enable_hot_reload=True)
        
        # Load shared rules
        shared_file = self.rules_dir / 'shared.yaml'
        should_reload_first = loader._should_reload_file('shared.yaml', shared_file)
        
        # First time should reload (not in cache)
        self.assertTrue(should_reload_first, "First load should reload")
        
        # Load the file
        shared1 = loader._load_shared_rules()
        
        # Second time should NOT reload (checksum unchanged)
        should_reload_second = loader._should_reload_file('shared.yaml', shared_file)
        self.assertFalse(should_reload_second, "Second load should not reload if file unchanged")
    
    def test_fast_path_no_checksum_calculation(self):
        """Test that fast-path doesn't calculate checksums when hot-reload is OFF"""
        loader = RuleLoader(self.rules_dir, enable_hot_reload=False)
        
        # Load some rules
        loader.get_layout_rules('COSTCO')
        loader.get_layout_rules('RD')
        loader._load_shared_rules()
        
        # File checksums dict should remain None (not created)
        self.assertIsNone(loader._file_checksums, 
                         "Checksums should not be calculated when hot-reload is OFF")
    
    def test_file_read_counter(self):
        """Test that file read counter tracks I/O operations"""
        loader = RuleLoader(self.rules_dir, enable_hot_reload=False)
        
        initial_count = loader.get_file_read_count()
        self.assertEqual(initial_count, 0, "Initial read count should be 0")
        
        # Load some rules
        loader._load_shared_rules()
        after_shared = loader.get_file_read_count()
        self.assertGreater(after_shared, 0, "Should have read shared.yaml")
        
        loader.get_layout_rules('COSTCO')
        after_costco = loader.get_file_read_count()
        self.assertGreater(after_costco, after_shared, "Should have read Costco layout")
        
        # Reset counter
        loader.reset_file_read_count()
        self.assertEqual(loader.get_file_read_count(), 0, "Counter should reset to 0")
    
    def test_integration_multiple_vendors(self):
        """Integration test: Load multiple vendor rules without duplicate I/O"""
        loader = RuleLoader(self.rules_dir, enable_hot_reload=False)
        
        vendors = ['COSTCO', 'RD', 'JEWEL', 'ALDI']
        
        # First pass
        loader.reset_file_read_count()
        for vendor in vendors:
            loader.get_layout_rules(vendor)
        first_pass_reads = loader.get_file_read_count()
        
        # Second pass - should use cache
        for vendor in vendors:
            loader.get_layout_rules(vendor)
        second_pass_reads = loader.get_file_read_count()
        
        self.assertEqual(first_pass_reads, second_pass_reads,
                        "Second pass should not perform any additional file I/O")


if __name__ == '__main__':
    unittest.main()

