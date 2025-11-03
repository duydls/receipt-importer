#!/usr/bin/env python3
"""
Logger setup for Step 1 extraction
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(log_level: str = 'INFO', log_dir: Optional[Path] = None) -> logging.Logger:
    """
    Setup logging configuration
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_dir: Directory for log files (defaults to 'logs/')
        
    Returns:
        Configured logger instance
    """
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_dir = log_dir or Path('logs')
    
    # Create log directory
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        handlers=[
            logging.FileHandler(log_dir / 'step1_extract.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

