#!/usr/bin/env python3
"""
Feature 4 Tests: Column-Mapping Cache in layout_applier
Tests that column mappings are cached and reused for files with identical headers/layouts.
"""

import os
import unittest
import pandas as pd
import threading
import time
from pathlib import Path

# Setup path
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
os.chdir(PROJECT_ROOT)

from step1_extract.rule_loader import RuleLoader
from step1_extract.layout_applier import LayoutApplier


class TestFeature4ColumnMapCache(unittest.TestCase):
    """Test Feature 4: Column-Mapping Cache"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        cls.rules_dir = PROJECT_ROOT / 'step1_rules'
        cls.rule_loader = RuleLoader(cls.rules_dir)
    
    def test_cache_enabled_by_default(self):
        """Test that column-mapping cache is enabled by default"""
        applier = LayoutApplier(self.rule_loader)
        self.assertTrue(applier._cache_enabled, "Cache should be enabled by default")
    
    def test_cache_can_be_disabled(self):
        """Test that cache can be disabled via environment variable"""
        original_env = os.environ.get('RECEIPTS_DISABLE_COLUMN_MAP_CACHE')
        
        try:
            os.environ['RECEIPTS_DISABLE_COLUMN_MAP_CACHE'] = '1'
            applier = LayoutApplier(self.rule_loader)
            self.assertFalse(applier._cache_enabled, "Cache should be disabled when env var is 1")
            
            os.environ['RECEIPTS_DISABLE_COLUMN_MAP_CACHE'] = '0'
            applier2 = LayoutApplier(self.rule_loader)
            self.assertTrue(applier2._cache_enabled, "Cache should be enabled when env var is 0")
        finally:
            if original_env:
                os.environ['RECEIPTS_DISABLE_COLUMN_MAP_CACHE'] = original_env
            elif 'RECEIPTS_DISABLE_COLUMN_MAP_CACHE' in os.environ:
                del os.environ['RECEIPTS_DISABLE_COLUMN_MAP_CACHE']
    
    def test_identical_headers_cache_hit(self):
        """Test that identical headers and layout produce cache hit"""
        applier = LayoutApplier(self.rule_loader)
        
        headers = ['Item Description', 'QTY', 'Unit Price', 'Extended Amount (USD)']
        layout = {
            'name': 'Test Layout',
            'column_mappings': {
                'product_name': 'Item Description',
                'quantity': 'QTY',
                'unit_price': 'Unit Price',
                'total_price': 'Extended Amount (USD)'
            },
            'skip_patterns': ['TOTAL', 'TAX']
        }
        vendor_code = 'TEST'
        
        # First call - should be a miss
        mapping1, regex1 = applier._get_column_mapping_cached(headers, layout, vendor_code)
        misses_after_first = applier._cache_misses
        hits_after_first = applier._cache_hits
        
        self.assertEqual(misses_after_first, 1, "First call should be a cache miss")
        self.assertEqual(hits_after_first, 0, "First call should have 0 hits")
        
        # Second call - should be a hit
        mapping2, regex2 = applier._get_column_mapping_cached(headers, layout, vendor_code)
        misses_after_second = applier._cache_misses
        hits_after_second = applier._cache_hits
        
        self.assertEqual(misses_after_second, 1, "Second call should not add misses")
        self.assertEqual(hits_after_second, 1, "Second call should be a cache hit")
        
        # Verify mappings are identical
        self.assertEqual(mapping1, mapping2, "Cached mapping should match original")
    
    def test_different_layout_cache_miss(self):
        """Test that changed layout produces cache miss"""
        applier = LayoutApplier(self.rule_loader)
        
        headers = ['Item Description', 'QTY', 'Extended Amount (USD)']
        
        layout1 = {
            'name': 'Layout V1',
            'column_mappings': {
                'product_name': 'Item Description',
                'quantity': 'QTY',
                'total_price': 'Extended Amount (USD)'
            },
            'skip_patterns': []
        }
        
        layout2 = {
            'name': 'Layout V2',  # Different name
            'column_mappings': {
                'product_name': 'Item Description',
                'quantity': 'QTY',
                'total_price': 'Extended Amount (USD)',
                'unit_price': 'Unit Price'  # Added field
            },
            'skip_patterns': []
        }
        
        vendor_code = 'TEST'
        
        # First layout
        applier._get_column_mapping_cached(headers, layout1, vendor_code)
        misses1 = applier._cache_misses
        
        # Second layout with different signature
        applier._get_column_mapping_cached(headers, layout2, vendor_code)
        misses2 = applier._cache_misses
        
        self.assertEqual(misses2, misses1 + 1, "Changed layout should cause cache miss")
    
    def test_layout_signature_deterministic(self):
        """Test that layout signature is deterministic"""
        layout = {
            'name': 'Test',
            'column_mappings': {'a': 'A', 'b': 'B'},
            'skip_patterns': ['TAX', 'TOTAL']
        }
        
        sig1 = LayoutApplier._compute_layout_signature(layout)
        sig2 = LayoutApplier._compute_layout_signature(layout)
        
        self.assertEqual(sig1, sig2, "Signature should be deterministic")
    
    def test_layout_signature_changes_with_content(self):
        """Test that layout signature changes when content changes"""
        layout1 = {
            'name': 'Test',
            'column_mappings': {'a': 'A'},
            'skip_patterns': []
        }
        
        layout2 = {
            'name': 'Test',
            'column_mappings': {'a': 'B'},  # Changed mapping
            'skip_patterns': []
        }
        
        sig1 = LayoutApplier._compute_layout_signature(layout1)
        sig2 = LayoutApplier._compute_layout_signature(layout2)
        
        self.assertNotEqual(sig1, sig2, "Different layouts should have different signatures")
    
    def test_skip_regex_cached(self):
        """Test that compiled skip regex is cached"""
        applier = LayoutApplier(self.rule_loader)
        
        headers = ['Item Description', 'Extended Amount (USD)']
        layout = {
            'name': 'Test',
            'column_mappings': {'product_name': 'Item Description', 'total_price': 'Extended Amount (USD)'},
            'skip_patterns': ['TOTAL', 'TAX', 'SUBTOTAL']
        }
        
        # First call
        mapping1, regex1 = applier._get_column_mapping_cached(headers, layout, 'TEST')
        
        # Second call
        mapping2, regex2 = applier._get_column_mapping_cached(headers, layout, 'TEST')
        
        # Regex should be the same object (cached)
        self.assertIsNotNone(regex1, "Skip regex should be compiled")
        self.assertIs(regex2, regex1, "Cached regex should be same object")
    
    def test_cache_hit_saves_time(self):
        """Test that cache hits report time saved"""
        applier = LayoutApplier(self.rule_loader)
        
        headers = ['Item Description', 'QTY', 'Unit Price', 'Extended Amount (USD)']
        layout = {
            'name': 'Test',
            'column_mappings': {
                'product_name': 'Item Description',
                'quantity': 'QTY',
                'unit_price': 'Unit Price',
                'total_price': 'Extended Amount (USD)'
            },
            'skip_patterns': []
        }
        
        # First call (miss)
        applier._get_column_mapping_cached(headers, layout, 'TEST')
        time_saved_after_miss = applier._cache_time_saved_ms
        
        self.assertEqual(time_saved_after_miss, 0.0, "No time saved on cache miss")
        
        # Second call (hit)
        applier._get_column_mapping_cached(headers, layout, 'TEST')
        time_saved_after_hit = applier._cache_time_saved_ms
        
        self.assertGreater(time_saved_after_hit, 0.0, "Time should be saved on cache hit")
    
    def test_cache_stats(self):
        """Test that cache stats are correctly tracked"""
        applier = LayoutApplier(self.rule_loader)
        
        headers = ['Item Description', 'Extended Amount (USD)']
        layout = {
            'name': 'Test',
            'column_mappings': {'product_name': 'Item Description', 'total_price': 'Extended Amount (USD)'},
            'skip_patterns': []
        }
        
        # Make some calls
        applier._get_column_mapping_cached(headers, layout, 'VENDOR1')  # Miss
        applier._get_column_mapping_cached(headers, layout, 'VENDOR1')  # Hit
        applier._get_column_mapping_cached(headers, layout, 'VENDOR2')  # Miss (different vendor)
        applier._get_column_mapping_cached(headers, layout, 'VENDOR1')  # Hit
        
        stats = applier.get_cache_stats()
        
        self.assertEqual(stats['hits'], 2, "Should have 2 cache hits")
        self.assertEqual(stats['misses'], 2, "Should have 2 cache misses")
        self.assertTrue(stats['enabled'], "Cache should be enabled")
        self.assertGreater(stats['cache_size'], 0, "Cache should contain entries")
        self.assertGreater(stats['time_saved_ms'], 0.0, "Should have saved time")
    
    def test_thread_safety(self):
        """Test that cache is thread-safe"""
        applier = LayoutApplier(self.rule_loader)
        
        headers = ['Item Description', 'Extended Amount (USD)']
        layout = {
            'name': 'Test',
            'column_mappings': {'product_name': 'Item Description', 'total_price': 'Extended Amount (USD)'},
            'skip_patterns': []
        }
        
        results = []
        errors = []
        
        def worker():
            try:
                for _ in range(10):
                    mapping, regex = applier._get_column_mapping_cached(headers, layout, 'TEST')
                    results.append(mapping)
            except Exception as e:
                errors.append(e)
        
        # Run 5 threads concurrently
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        self.assertEqual(len(errors), 0, "Should have no errors")
        self.assertGreater(len(results), 0, "Should have results")
        
        # All mappings should be identical
        first_mapping = results[0]
        for mapping in results[1:]:
            self.assertEqual(mapping, first_mapping, "All thread results should match")
    
    def test_lru_eviction(self):
        """Test that cache evicts old entries when full"""
        applier = LayoutApplier(self.rule_loader)
        
        # Fill cache beyond limit (256)
        for i in range(300):
            headers = [f'Column{i}']
            layout = {
                'name': f'Layout{i}',
                'column_mappings': {f'field{i}': f'Column{i}'},
                'skip_patterns': []
            }
            applier._get_column_mapping_cached(headers, layout, f'VENDOR{i}')
        
        stats = applier.get_cache_stats()
        
        # Cache should be limited to max size
        self.assertLessEqual(stats['cache_size'], 256, "Cache should not exceed max size")
        self.assertEqual(stats['misses'], 300, "All initial calls should be misses")


if __name__ == '__main__':
    unittest.main()

