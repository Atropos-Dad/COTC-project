#!/bin/bash

# This script runs the Flask-SocketIO application using gunicorn with eventlet

# Activate virtual environment
source .venv/bin/activate

# Install gunicorn and eventlet if not already installed
pip install gunicorn eventlet

# Run gunicorn with eventlet workers
# Note: Only use 1 worker as Flask-SocketIO doesn't support multiple workers without a message queue
gunicorn --worker-class eventlet --workers 1 --bind 0.0.0.0:8000 wsgi:application 