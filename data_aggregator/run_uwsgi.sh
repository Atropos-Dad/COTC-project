#!/bin/bash

# Activate virtual environment
source .venv/bin/activate

# Install uWSGI if not already installed
#pip install uwsgi

# Run uWSGI with the configuration file
uwsgi --ini uwsgi.ini 