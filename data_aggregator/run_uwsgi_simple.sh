#!/bin/bash

# Activate virtual environment
source .venv/bin/activate

# Install uWSGI if not already installed
pip install uwsgi

# Run uWSGI with minimal options and simplified module
echo "Starting uWSGI with simplified configuration..."
uwsgi --http 0.0.0.0:5000 --module wsgi_simple:application --master --processes 1 --threads 1 --enable-threads 