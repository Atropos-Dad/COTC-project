import eventlet
eventlet.monkey_patch()  # Required for proper async operation

from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
import json
from datetime import datetime
import os
import logging
import sys

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
socketio = SocketIO(app, 
                   cors_allowed_origins="*", # Allow all origins for testing
                   async_mode='eventlet',    # Use eventlet for better performance
                   logger=True,              # Enable SocketIO's own logging
                   engineio_logger=True)     # Enable Engine.IO logging

# Create a data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# Create a templates directory if it doesn't exist
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# Initialize the database
init_db()

# Initialize the Dash app
dash_app = get_dash_app()
dash_app.init_app(app)

# Home route
@app.route('/')
def home():
    return render_template('index.html')

# Dashboard route
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# Keep the HTTP endpoint for backward compatibility
@app.route('/api/data', methods=['POST'])
def receive_data():
    try:
        data = request.get_json()
        
        if not data:
            logger.warning("Received empty data in HTTP endpoint")
            return jsonify({'error': 'No data provided'}), 400
        
        # Enhanced logging for HTTP data reception
        current_time = datetime.now().isoformat()
        data_size = len(json.dumps(data))
        client_ip = request.remote_addr
        
        logger.info(f"[HTTP_DATA_RECEIVED] Time: {current_time} | Client IP: {client_ip} | Size: {data_size} bytes")
        
        # Log data type and measurement if available
        measurement = data.get('measurement', 'unknown')
        tags = data.get('tags', {})
        game_id = tags.get('game_id', 'unknown')
        event_type = tags.get('event_type', 'unknown')
        
        logger.info(f"[HTTP_DATA_DETAILS] Measurement: {measurement} | Game ID: {game_id} | Event: {event_type}")
        
        result = save_chess_data(data)
        
        if 'error' in result:
            return jsonify(result), 500
            
        return jsonify(result), 201
        
    except Exception as e:
        logger.error(f"Error in HTTP endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

# API endpoint for generic metrics
@app.route('/api/metrics', methods=['POST'])
def receive_metrics():
    try:
        data = request.get_json()
        
        if not data:
            logger.warning("Received empty data in metrics endpoint")
            return jsonify({'error': 'No data provided'}), 400
        
        # Enhanced logging for metrics reception
        current_time = datetime.now().isoformat()
        data_size = len(json.dumps(data))
        client_ip = request.remote_addr
        
        logger.info(f"[METRICS_DATA_RECEIVED] Time: {current_time} | Client IP: {client_ip} | Size: {data_size} bytes")
        logger.debug(f"[METRICS_DATA_CONTENT] {json.dumps(data)}")
        
        result = save_metric_data(data)
        
        if 'error' in result:
            return jsonify(result), 500
            
        return jsonify(result), 201
        
    except Exception as e:
        logger.error(f"Error in metrics endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

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

@socketio.on('metric', namespace='/ws/metrics')
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

@socketio.on('metric', namespace='/ws/game_metrics')
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
        result = save_chess_data(data)
        
        if 'error' in result:
            logger.error(f"Error processing chess game metric from {request.sid}: {result['error']}")
            emit('error', result)
        else:
            logger.info(f"Successfully processed chess game metric from {request.sid}")
            emit('success', result)
            
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Exception in handle_game_metrics: {error_msg}")
        emit('error', {'error': error_msg})

# WebSocket endpoint for data
@socketio.on('connect', namespace='/ws/data')
def handle_connect():
    """Handle client connection."""
    client_id = request.sid
    client_ip = request.remote_addr
    connection_time = datetime.now().isoformat()
    
    logger.info(f"[SOCKET_CONNECT] Time: {connection_time} | Client ID: {client_id} | IP: {client_ip}")
    logger.debug(f"[SOCKET_CONNECT_DETAILS] Headers: {dict(request.headers)}")
    
    emit('response', {'data': 'Connected', 'sid': client_id})

@socketio.on('disconnect', namespace='/ws/data')
def handle_disconnect():
    """Handle client disconnection."""
    client_id = request.sid
    disconnect_time = datetime.now().isoformat()
    
    logger.info(f"[SOCKET_DISCONNECT] Time: {disconnect_time} | Client ID: {client_id}")

@socketio.on('data', namespace='/ws/data')
def handle_data(data):
    """Handle incoming data through WebSocket."""
    try:
        # Enhanced logging for socket data reception
        current_time = datetime.now().isoformat()
        data_size = len(json.dumps(data))
        client_id = request.sid
        
        logger.info(f"[SOCKET_DATA_RECEIVED] Time: {current_time} | Client: {client_id} | Size: {data_size} bytes")
        
        # Log data type and measurement if available
        measurement = data.get('measurement', 'unknown')
        tags = data.get('tags', {})
        game_id = tags.get('game_id', 'unknown')
        event_type = tags.get('event_type', 'unknown')
        
        logger.info(f"[SOCKET_DATA_DETAILS] Measurement: {measurement} | Game ID: {game_id} | Event: {event_type}")
        
        # Original debug log with full data content
        logger.debug(f"Data content: {json.dumps(data, indent=2)}")
        
        result = save_chess_data(data)
        
        if 'error' in result:
            logger.error(f"Error processing data from {request.sid}: {result['error']}")
            emit('error', result)
        else:
            logger.info(f"Successfully processed data from {request.sid}")
            emit('success', result)
            
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Exception in handle_data: {error_msg}")
        emit('error', {'error': error_msg})

if __name__ == '__main__':
    start_time = datetime.now().isoformat()
    logger.info(f"[SERVER_START] Time: {start_time} | Starting data aggregator server...")
    logger.info(f"[SERVER_CONFIG] Host: {config.server.host} | Port: {config.server.port} | Debug: True | Async Mode: {socketio.async_mode}")
    socketio.run(app, debug=True, host=config.server.host, port=config.server.port)
