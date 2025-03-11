#!/bin/bash

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script as root (sudo)"
  exit 1
fi

# Get the absolute path of the data_aggregator directory
DATA_AGGREGATOR_DIR=$(cd "$(dirname "$0")" && pwd)
SCRIPT_PATH="$DATA_AGGREGATOR_DIR/data_aggregator.service"

echo "Installing Data Aggregator uWSGI service..."
echo "Service file path: $SCRIPT_PATH"

# Copy the service file to systemd
cp "$SCRIPT_PATH" /etc/systemd/system/data_aggregator.service
if [ $? -ne 0 ]; then
  echo "Failed to copy service file. Please check permissions."
  exit 1
fi

echo "Service file copied to /etc/systemd/system/data_aggregator.service"

# Reload systemd configuration
systemctl daemon-reload
if [ $? -ne 0 ]; then
  echo "Failed to reload systemd configuration."
  exit 1
fi

echo "Systemd configuration reloaded"

# Enable the service to start on boot
systemctl enable data_aggregator
if [ $? -ne 0 ]; then
  echo "Failed to enable service."
  exit 1
fi

echo "Service enabled to start on boot"

# Start the service
systemctl start data_aggregator
if [ $? -ne 0 ]; then
  echo "Failed to start service."
  exit 1
fi

echo "Service started"

# Check service status
echo -e "\nService status:"
systemctl status data_aggregator

echo -e "\nInstallation complete!"
echo "You can manage the service with these commands:"
echo "  sudo systemctl start data_aggregator    # Start the service"
echo "  sudo systemctl stop data_aggregator     # Stop the service"
echo "  sudo systemctl restart data_aggregator  # Restart the service"
echo "  sudo systemctl status data_aggregator   # Check service status"
echo "  sudo journalctl -u data_aggregator      # View service logs" 