"""
Command-line script to run the data aggregator server.
"""

import logging
from datetime import datetime

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Import app after logging setup
    from src.app import socketio, app
    
    # Log server startup
    start_time = datetime.now().isoformat()
    logger.info(f"[SERVER_START] Time: {start_time} | Starting data aggregator server from run.py...")
    logger.info(f"[SERVER_CONFIG] Host: 0.0.0.0 | Port: 5000 | Debug: True | Async Mode: {socketio.async_mode}")
    
    # Run the server
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
