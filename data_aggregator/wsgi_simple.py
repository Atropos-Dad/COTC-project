"""
Simplified WSGI entry point for testing.
This uses a direct Flask application without SocketIO middleware.
"""

import os
import sys

# Add the project root directory to the Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Import config before app to set up logging
from src.lib_config.config import Config

# Initialize configuration with the absolute path to config.json
config_path = os.path.join(project_root, "config.json")
config = Config(config_path=config_path)

# Get the logger for this module
logger = config.get_logger(__name__)
logger.info("Starting simplified WSGI application")

# Import the Flask application directly
from src.app import app as application

logger.info("Simplified WSGI application initialized and ready") 