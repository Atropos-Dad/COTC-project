#!/bin/bash

# This script tests uWSGI directly to diagnose issues

# Activate virtual environment
source .venv/bin/activate

echo "==== Environment Information ===="
echo "Python version:"
python --version
echo ""
echo "uWSGI version:"
uwsgi --version
echo ""
echo "Current directory: $(pwd)"
echo "User: $(whoami)"
echo ""

echo "==== Testing uWSGI ===="
echo "Running uWSGI with verbose output..."

# Run uWSGI with debug flags
uwsgi --ini uwsgi.ini --catch-exceptions --need-app --thunder-lock --py-tracebacker=/tmp/tbsocket

# Exit code
EXIT_CODE=$?
echo ""
echo "uWSGI exit code: $EXIT_CODE"

if [ $EXIT_CODE -ne 0 ]; then
  echo "uWSGI failed! Please check the error messages above."
else
  echo "uWSGI started successfully."
fi 