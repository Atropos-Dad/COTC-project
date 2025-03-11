#!/bin/bash

# Activate virtual environment
source .venv/bin/activate

# Install uWSGI and other required packages if not already installed
pip install uwsgi eventlet gevent flask-socketio

# Enable verbose logging
export UWSGI_LOGLEVEL=debug

# Run uWSGI with the configuration file in verbose mode
uwsgi --ini uwsgi.ini --enable-threads --thunder-lock 