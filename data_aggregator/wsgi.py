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

# Get the logger for this module
logger = config.get_logger(__name__)
logger.info("Starting WSGI application")

# This is the critical part for SocketIO
try:
    import eventlet
    eventlet.monkey_patch()
    logger.info("Eventlet monkey patching applied")
except ImportError:
    logger.error("Eventlet not available - SocketIO may not work correctly")
    pass

# Import the Flask application and SocketIO instance
from src.app import app, socketio

# Create the WSGI application
# For uWSGI with SocketIO, we need the SocketIO middleware
application = socketio.middleware(app)

logger.info("WSGI application initialized and ready") 