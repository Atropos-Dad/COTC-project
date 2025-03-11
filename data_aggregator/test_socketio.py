#!/usr/bin/env python3
"""
Script to test the SocketIO connectivity to the data aggregator server.
Run this after starting the server to verify WebSocket functionality.
"""

import socketio
import time
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create a SocketIO client
sio = socketio.Client(logger=True)

@sio.event
def connect():
    logger.info("Connected to server!")

@sio.event
def disconnect():
    logger.info("Disconnected from server")

@sio.event
def response(data):
    logger.info(f"Received response: {data}")

def main():
    # Connect to the server
    try:
        logger.info("Attempting to connect to server...")
        sio.connect('http://localhost:5000', namespaces=['/ws/metrics'])
        logger.info("Connection successful!")
        
        # Send a test metric
        test_metric = {
            "measurement": "test_metric",
            "tags": {
                "source": "test_script"
            },
            "fields": {
                "value": 100
            },
            "timestamp": int(time.time() * 1000)
        }
        
        logger.info(f"Sending test metric: {test_metric}")
        sio.emit('metric', test_metric, namespace='/ws/metrics')
        logger.info("Test metric sent!")
        
        # Wait for 5 seconds to receive any responses
        time.sleep(5)
        
        # Disconnect
        sio.disconnect()
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    main() 