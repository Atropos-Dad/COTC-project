#!/usr/bin/env python3
"""
This script runs the Flask-SocketIO application directly without uWSGI.
Use this for comparison to see if the issue is with uWSGI or with the application.
"""

import os
import sys

# Add the project root directory to the Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Import eventlet and monkey patch
import eventlet
eventlet.monkey_patch()

# Import config before app to set up logging
from src.lib_config.config import Config

# Initialize configuration with the absolute path to config.json
config_path = os.path.join(project_root, "config.json")
config = Config(config_path=config_path)

# Get the logger for this module
logger = config.get_logger(__name__)
logger.info("Starting direct Flask-SocketIO server")

# Import the Flask application and SocketIO instance
from src.app import app, socketio

if __name__ == "__main__":
    logger.info(f"Running server on {config.server.host}:{config.server.port}")
    socketio.run(app, 
                debug=True, 
                host=config.server.host, 
                port=config.server.port,
                use_reloader=False)  # Disable reloader to avoid duplicate startup 