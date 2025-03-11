# uWSGI Deployment Guide for Data Aggregator

This guide explains how to deploy the Data Aggregator application using uWSGI, either standalone or with Nginx.

## Prerequisites

- Python 3.7+
- pip
- virtualenv
- Nginx (for production)

## Installation

1. **Create and activate a virtual environment** (if not already done):
   ```bash
   cd /path/to/data_aggregator
   python -m venv .venv
   source .venv/bin/activate
   ```

2. **Install the application requirements**:
   ```bash
   pip install -r requirements.txt
   pip install uwsgi
   ```

## Running with uWSGI

### Quick Start

Use the provided shell script:
```bash
./run_uwsgi.sh
```

### Manual Start

```bash
uwsgi --ini uwsgi.ini
```

## Systemd Service Setup (for Production)

1. **Edit the systemd service file**:
   Open `data_aggregator.service` and update the paths:
   - Replace `/path/to/data_aggregator` with the actual path to your installation.

2. **Install the service**:
   ```bash
   sudo cp data_aggregator.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable data_aggregator
   sudo systemctl start data_aggregator
   ```

3. **Check service status**:
   ```bash
   sudo systemctl status data_aggregator
   ```

## Nginx Setup (for Production)

1. **Edit the Nginx configuration file**:
   Open `nginx_data_aggregator.conf` and update:
   - Replace `your_domain.com` with your actual domain.
   - Replace `/path/to/data_aggregator` with the actual path to your installation.

2. **Install the Nginx configuration**:
   ```bash
   sudo cp nginx_data_aggregator.conf /etc/nginx/sites-available/data_aggregator
   sudo ln -s /etc/nginx/sites-available/data_aggregator /etc/nginx/sites-enabled/
   sudo nginx -t  # Test the configuration
   sudo systemctl restart nginx
   ```

## Troubleshooting

### Check logs:
- uWSGI logs: `tail -f logs/uwsgi.log`
- Nginx logs: `tail -f /var/log/nginx/error.log`

### Common issues:
1. **Socket permission denied**: Make sure the socket file has the correct permissions.
2. **Module not found**: Ensure your virtual environment is correctly activated.
3. **WebSocket connection issues**: Check that Nginx is properly configured for WebSockets.

## Performance Tuning

Adjust these parameters in `uwsgi.ini` based on your server's capabilities:
- `processes`: Number of worker processes (typically 1-2 per CPU core)
- `threads`: Number of threads per process
- `buffer-size`: Increase for larger requests

For high-traffic deployments, consider:
- Increasing the number of workers
- Implementing a load balancer
- Using more advanced monitoring 