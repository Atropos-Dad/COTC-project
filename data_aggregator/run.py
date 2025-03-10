"""
Command-line script to run the data aggregator server.
"""

import os
import logging
from datetime import datetime

if __name__ == "__main__":
    # Get the project root directory (same directory as this script)
    project_root = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(project_root, "config.json")
    
    # Check if this is a Flask reloader restart
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    
    # Set up basic logging for startup, but only log config path on initial start
    logging.basicConfig(level=logging.DEBUG)
    if not is_reloader_process:
        logging.debug(f"Looking for config file at: {config_path}")
    
    # Import config before app to set up logging
    from src.lib_config.config import Config
    
    # Initialize configuration with the absolute path to config.json
    config = Config(config_path=config_path)
    # Set up logging and get a logger for this module
    logger = config.get_logger(__name__)
    
    # Import app after logging setup
    from src.app import socketio, app
    
    # Log server startup
    start_time = datetime.now().isoformat()
    logger.info(f"[SERVER_START] Time: {start_time} | Starting data aggregator server from run.py...")
    logger.info(f"[SERVER_CONFIG] Host: {config.server.host} | Port: {config.server.port} | Debug: True | Async Mode: {socketio.async_mode}")
    
    # Run the server
    socketio.run(app, debug=True, host=config.server.host, port=config.server.port)
