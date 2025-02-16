"""Configure logging for the data collector application."""
import logging
import sys
from datetime import datetime

def setup_logging(log_level=logging.DEBUG):
    """Set up logging configuration for the application.
    
    Args:
        log_level: The logging level to use. Defaults to DEBUG.
    """
    # Create a formatter that includes timestamp, level, and module
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # Create file handler
    file_handler = logging.FileHandler(
        f'data_collector_{datetime.now().strftime("%Y%m%d")}.log'
    )
    file_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Return logger for convenience
    return root_logger
