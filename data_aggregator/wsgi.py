"""
WSGI entry point for the data aggregator server.
This file is used by uWSGI to run the application.
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

# Import the Flask application
from src.app import app as application

# The uWSGI server expects the Flask application to be called "application"
# If you're using SocketIO directly without Flask, you would need a different approach 