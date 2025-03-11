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
   pip install uwsgi eventlet gevent flask-socketio
   ```

## Running with uWSGI

### Quick Start

Use the provided shell script:
```bash
./run_uwsgi.sh
```

### Manual Start

```bash
uwsgi --ini uwsgi.ini --enable-threads --thunder-lock
```

## Testing SocketIO Functionality

We've provided a test script to verify WebSocket functionality:

```bash
# Make sure the server is running first!
./test_socketio.py
```

If the WebSocket functionality doesn't work properly with uWSGI, you can try running the Flask-SocketIO server directly:

```bash
./run_socketio_directly.py
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

### Common uWSGI + SocketIO Issues

If uWSGI gets stuck at `[uWSGI] getting INI configuration from uwsgi.ini`, try these solutions:

1. **Use HTTP instead of socket for testing**:
   - In uwsgi.ini, ensure you're using the HTTP option instead of socket
   - `http = 0.0.0.0:5000` should be uncommented
   - Comment out the socket lines with `#`

2. **Reduce complexity**:
   - Set processes to 1 and threads to 1
   - Enable single-interpreter mode
   - Add gevent support with `gevent = 1000`

3. **Check for monkey patching issues**:
   - Make sure eventlet.monkey_patch() is called BEFORE importing Flask-SocketIO
   - Use the updated wsgi.py which handles this correctly

4. **Try running with additional flags**:
   ```bash
   uwsgi --ini uwsgi.ini --enable-threads --thunder-lock --py-autoreload=1
   ```

5. **Test with direct Flask-SocketIO**:
   - If uWSGI doesn't work, run the application directly with Flask-SocketIO:
   ```bash
   ./run_socketio_directly.py
   ```

### General Troubleshooting

- uWSGI logs: `tail -f logs/uwsgi.log`
- Nginx logs: `tail -f /var/log/nginx/error.log`
- Python tracebacks: `uwsgi --connect-and-read uwsgi-tracebacker.sock`

### Common issues:
1. **Socket permission denied**: Make sure the socket file has the correct permissions.
2. **Module not found**: Ensure your virtual environment is correctly activated.
3. **WebSocket connection issues**: Check that Nginx is properly configured for WebSockets.
4. **Eventlet/Gevent conflicts**: Be careful mixing eventlet and gevent.

## Performance Tuning

For Flask-SocketIO applications, the optimal configuration is often:

- Using `gevent = 1000` in uwsgi.ini
- Setting `processes = 1` (multiple processes can cause WebSocket routing issues)
- Enabling threads with `enable-threads = true`
- Using a proper load balancer for horizontal scaling instead of multiple processes 