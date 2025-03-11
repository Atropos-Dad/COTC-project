import eventlet
eventlet.monkey_patch()  # Required for proper async operation

from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from flask_caching import Cache
import json
from datetime import datetime
import os
import logging
import sys
import threading
import time

# Import database functions
from database import init_db, save_chess_data, save_metric_data

# Import the Dash app
from dashboard import get_dash_app

# Import the Config class
from lib_config.config import Config

# Get the project root directory (one level up from the script directory)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.path.join(project_root, "config.json")

# Initialize configuration with the absolute path to config.json
config = Config(config_path=config_path)
# Set up logging and get a logger for this module
logger = config.get_logger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Required for SocketIO

# Create a data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# Create cache directory
CACHE_DIR = os.path.join(DATA_DIR, 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# Initialize caching
cache = Cache(app, config={
    'CACHE_TYPE': 'filesystem',
    'CACHE_DIR': CACHE_DIR,
    'CACHE_DEFAULT_TIMEOUT': 60  # seconds
})

socketio = SocketIO(app, 
                   cors_allowed_origins="*", # Allow all origins for testing
                   async_mode='eventlet',    # Use eventlet for better performance
                   logger=True,              # Enable SocketIO's own logging
                   engineio_logger=True)     # Enable Engine.IO logging

# Create a templates directory if it doesn't exist
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# Initialize the database
init_db()

# Initialize the Dash app
dash_app = get_dash_app(cache)
dash_app.init_app(app)

# Home route
@app.route('/')
def home():
    return render_template('index.html')

# Dashboard route
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# Route to handle dashboard messages
@app.route('/api/send_message', methods=['POST'])
def send_dashboard_message():
    """API endpoint to send messages from dashboard to clients."""
    data = request.json
    if data and 'message' in data:
        # Get the IP address of the user
        user_ip = request.remote_addr
        
        payload = {
            'message': data['message'],
            'timestamp': datetime.now().isoformat(),
            'type': 'dashboard_message',
            'user_ip': user_ip  # Include the IP address in the payload
        }
        # Broadcast to all connected clients
        socketio.emit('dashboard_message', payload, namespace='/ws/metrics')
        return jsonify({'status': 'success', 'message': 'Message sent to clients'})
    else:
        return jsonify({'status': 'error', 'message': 'Invalid message data'}), 400

# WebSocket endpoint for metrics
@socketio.on('connect', namespace='/ws/metrics')
def handle_metrics_connect():
    """Handle client connection for metrics."""
    client_id = request.sid
    client_ip = request.remote_addr
    connection_time = datetime.now().isoformat()
    
    logger.info(f"[SOCKET_METRICS_CONNECT] Time: {connection_time} | Client ID: {client_id} | IP: {client_ip}")
    
    emit('response', {'data': 'Connected to metrics endpoint', 'sid': client_id})

@socketio.on('disconnect', namespace='/ws/metrics')
def handle_metrics_disconnect():
    """Handle client disconnection from metrics endpoint."""
    client_id = request.sid
    disconnect_time = datetime.now().isoformat()
    
    logger.info(f"[SOCKET_METRICS_DISCONNECT] Time: {disconnect_time} | Client ID: {client_id}")

@socketio.on('connect', namespace='/ws/game_metrics')
def handle_game_metrics_connect():
    """Handle client connection for game metrics."""
    client_id = request.sid
    client_ip = request.remote_addr
    connection_time = datetime.now().isoformat()
    
    logger.info(f"[SOCKET_GAME_METRICS_CONNECT] Time: {connection_time} | Client ID: {client_id} | IP: {client_ip}")
    
    emit('response', {'data': 'Connected to game metrics endpoint', 'sid': client_id})

@socketio.on('disconnect', namespace='/ws/game_metrics')
def handle_game_metrics_disconnect():
    """Handle client disconnection from game metrics endpoint."""
    client_id = request.sid
    disconnect_time = datetime.now().isoformat()
    
    logger.info(f"[SOCKET_GAME_METRICS_DISCONNECT] Time: {disconnect_time} | Client ID: {client_id}")

@socketio.on('metric', namespace='/ws/metrics') # save metric data
def handle_system_metrics(data):
    """Handle incoming system metric data through WebSocket."""
    try:
        # Enhanced logging for socket metric reception
        current_time = datetime.now().isoformat()
        data_size = len(json.dumps(data))
        client_id = request.sid
        
        logger.info(f"[SOCKET_METRIC_RECEIVED] Time: {current_time} | Client: {client_id} | Size: {data_size} bytes")
        logger.debug(f"[SOCKET_METRIC_CONTENT] {json.dumps(data)}")
        
        result = save_metric_data(data)
        
        if 'error' in result:
            logger.error(f"Error processing metric from {request.sid}: {result['error']}")
            emit('error', result)
        else:
            logger.info(f"Successfully processed metric from {request.sid}")
            emit('success', result)
            
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Exception in handle_system_metrics: {error_msg}")
        emit('error', {'error': error_msg})

@socketio.on('metric', namespace='/ws/game_metrics') # save game metric data
def handle_game_metrics(data):
    """Handle incoming chess game metric data through WebSocket."""
    try:
        # Enhanced logging for socket metric reception
        current_time = datetime.now().isoformat()
        data_size = len(json.dumps(data))
        client_id = request.sid
        
        logger.info(f"[SOCKET_GAME_METRIC_RECEIVED] Time: {current_time} | Client: {client_id} | Size: {data_size} bytes")
        logger.debug(f"[SOCKET_GAME_METRIC_CONTENT] {json.dumps(data)}")
        
        # Ensure the measurement is set to 'chess_game'
        if isinstance(data, dict) and 'measurement' not in data:
            data['measurement'] = 'chess_game'
        
        # Use save_chess_data for chess game metrics
        max_retries = 2
        retries = 0
        while retries <= max_retries:
            try:
                result = save_chess_data(data)
                if 'error' in result:
                    if "foreign key constraint" in result.get('error', '').lower() and retries < max_retries:
                        # Retry if it's a foreign key violation and we haven't exceeded max retries
                        logger.warning(f"[RETRY] Foreign key violation, retrying ({retries+1}/{max_retries})")
                        retries += 1
                        continue
                    logger.error(f"Error processing chess game metric from {client_id}: {result['error']}")
                    emit('error', result)
                else:
                    logger.info(f"Successfully processed chess game metric from {client_id}")
                    emit('success', result)
                break  # Exit the loop if successful or if error is not retryable
            except Exception as inner_e:
                inner_error_msg = str(inner_e)
                if "foreign key constraint" in inner_error_msg.lower() and retries < max_retries:
                    # Retry on foreign key violation
                    logger.warning(f"[RETRY] Exception (foreign key violation), retrying ({retries+1}/{max_retries})")
                    retries += 1
                else:
                    # Re-raise if not a foreign key violation or max retries exceeded
                    raise
            
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Error processing chess game metric from {client_id}: {error_msg}")
        emit('error', {'error': error_msg})

if __name__ == '__main__':
    start_time = datetime.now().isoformat()
    logger.info(f"[SERVER_START] Time: {start_time} | Starting data aggregator server...")
    logger.info(f"[SERVER_CONFIG] Host: {config.server.host} | Port: {config.server.port} | Debug: True | Async Mode: {socketio.async_mode}")
    socketio.run(app, debug=True, host=config.server.host, port=config.server.port)
