"""Module for handling asynchronous metric collection and sending."""
import asyncio
import logging
import socketio  # Changed to python-socketio
import json
import time
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class AsyncMetricsCollector:
    def __init__(self, 
                 endpoint_url: str, 
                 metrics_collector: Any,  # Instance of a metrics collector class
                 queue_size: int = 100,  # Reduced queue size for lower latency
                 reconnect_interval: int = 5,
                 max_reconnect_attempts: int = 0):  # 0 for infinite retries
        """Initialize the async metrics collector.
        
        Args:
            endpoint_url: The URL to send metrics to (should be a ws:// or wss:// URL)
            metrics_collector: Instance of a metrics collector class with generate_metrics method
            queue_size: Maximum size of the queue before blocking
            reconnect_interval: Time in seconds between reconnection attempts
            max_reconnect_attempts: Maximum number of reconnection attempts (0 for infinite)
        """
        # Convert ws:// to http:// for Socket.IO
        self.endpoint_url = endpoint_url.replace('ws://', 'http://').replace('wss://', 'https://') # Socket.IO requires HTTP/HTTPS URLs
        
        # Extract the namespace from the URL path
        from urllib.parse import urlparse
        parsed_url = urlparse(endpoint_url)
        self.namespace = parsed_url.path or '/ws/data'  # Use path from URL or default to /ws/data
        self.metrics_collector = metrics_collector
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.running = False
        self.connected = False
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_count = 0
        self.buffer_queue = asyncio.Queue(maxsize=queue_size * 2)  # Buffer for failed sends
        
        # Initialize Socket.IO client with auto reconnection enabled
        self.sio = socketio.AsyncClient(reconnection=True, 
                                       reconnection_attempts=max_reconnect_attempts if max_reconnect_attempts > 0 else 0,
                                       reconnection_delay=reconnect_interval,
                                       logger=True,
                                       engineio_logger=True)
        
        # Debug message to show we're creating the instance properly
        logger.info("Created AsyncMetricsCollector instance with endpoint: %s, namespace: %s", 
                   self.endpoint_url, self.namespace)
                   
        self._setup_socketio_handlers()
        logger.info("Socket.IO event handlers set up")
        
        # Register for dashboard_message events (for debugging)
        @self.sio.event(namespace=self.namespace)
        async def dashboard_message(data):
            logger.info("=== ROOT DASHBOARD MESSAGE HANDLER TRIGGERED ===")
            logger.info("Received dashboard message (root handler): %s", json.dumps(data))
            
            # Use the dedicated save method
            await self._save_dashboard_message(data)

    def _setup_socketio_handlers(self):
        """Setup Socket.IO event handlers."""
        @self.sio.event
        async def connect():
            """Handle connection event."""
            logger.info("Connected to Socket.IO server at %s with namespace %s", self.endpoint_url, self.namespace)
            self.connected = True
            self.reconnect_count = 0  # Reset reconnect counter on successful connection
            # Process any buffered metrics once connected
            asyncio.create_task(self._process_buffer())

        @self.sio.event
        async def disconnect():
            """Handle disconnection event."""
            logger.warning("Disconnected from Socket.IO server at %s", self.endpoint_url)
            self.connected = False

        @self.sio.event
        def success(data):
            """Handle success event."""
            logger.info("Server acknowledged data: %s", data)
        
        @self.sio.event
        def error(data):
            """Handle error event."""
            logger.error("Server reported error: %s", data)
            
        @self.sio.event
        def connect_error(data):
            """Handle connection error."""
            logger.error("Connection error to Socket.IO server: %s", data)
            self.connected = False
            # Will automatically reconnect based on the client settings
            
        @self.sio.event
        async def dashboard_message(data):
            """Handle messages from the dashboard."""
            logger.info("=== DASHBOARD MESSAGE HANDLER TRIGGERED ===")
            logger.info("Received dashboard message: %s", json.dumps(data))
            
            # Use the dedicated save method
            await self._save_dashboard_message(data)

    async def _connect_with_retry(self):
        """Connect to the Socket.IO server with retries."""
        try:
            logger.info("Connecting to Socket.IO server at %s with namespace %s", 
                       self.endpoint_url, self.namespace)
            
            # Connect to the server
            await self.sio.connect(self.endpoint_url, namespaces=[self.namespace], transports=['websocket'])
            
            # Explicitly register to listen for dashboard_message events
            logger.info("Explicitly registering dashboard_message event listener")
            @self.sio.on('dashboard_message', namespace=self.namespace)
            async def on_dashboard_message(data):
                logger.info("=== EXPLICIT DASHBOARD MESSAGE HANDLER TRIGGERED ===")
                logger.info("Received dashboard message via explicit handler: %s", json.dumps(data))
                
                # Use the dedicated save method
                await self._save_dashboard_message(data)
            
            logger.info("Connected successfully")
            return True
            
        except Exception as e:
            logger.error("Failed to connect to Socket.IO server: %s", str(e))
            return False
    
    async def _monitor_connection(self):
        """Monitor the connection and attempt to reconnect when disconnected."""
        while self.running:
            if not self.sio.connected and self.running:
                logger.info("Connection monitor detected disconnection, attempting to reconnect...")
                await self._connect_with_retry()
            await asyncio.sleep(self.reconnect_interval)
    
    async def start(self):
        """Start the metrics collection and sending processes."""
        logger.info("Starting metrics collection and sending processes")
        self.running = True

        # Initial connection - don't raise exception if it fails
        connection_success = await self._connect_with_retry()
        if not connection_success:
            logger.warning("Initial connection failed, but will continue to try reconnecting")

        # Create multiple consumer tasks to process metrics in parallel
        # This helps ensure metrics are sent as soon as possible
        producer = asyncio.create_task(self._collect_metrics())
        consumers = [asyncio.create_task(self._send_metrics()) for _ in range(2)]  # Create 2 sender tasks
        connection_monitor = asyncio.create_task(self._monitor_connection())
        
        try:
            # Wait for all tasks
            await asyncio.gather(producer, *consumers, connection_monitor)
        except Exception as e:
            logger.exception("Error in metrics collection/sending tasks")
            # Don't raise the exception - keep trying to work even with errors
        finally:
            logger.info("Metrics collection and sending processes stopped")
            if self.sio.connected:
                try:
                    await asyncio.wait_for(self.sio.disconnect(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for Socket.IO to disconnect")
                except Exception as e:
                    logger.warning("Error disconnecting from Socket.IO: %s", str(e))

    async def stop(self):
        """Stop the metrics collection and sending processes with graceful shutdown."""
        if not self.running:
            logger.info("Collector already stopped")
            return

        logger.info("Stopping metrics collection")
        self.running = False
        
        try:
            # Process any metrics remaining in the buffer if connected
            if self.sio.connected and self.connected and not self.buffer_queue.empty():
                buffer_size = self.buffer_queue.qsize()
                logger.info("Processing %d buffered metrics during shutdown", buffer_size)
                try:
                    await asyncio.wait_for(self._process_buffer(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Timeout processing buffer during shutdown")

            # Wait for queue to be empty with a timeout
            try:
                await asyncio.wait_for(self.queue.join(), timeout=5.0)
                logger.info("All pending metrics processed")
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for queue to empty, some metrics may be lost")
            
            # Report on any metrics left in the buffer
            if not self.buffer_queue.empty():
                logger.warning("%d metrics still in buffer at shutdown, data will be lost", self.buffer_queue.qsize())
            
            # Disconnect from Socket.IO server
            if self.sio.connected:
                try:
                    await asyncio.wait_for(self.sio.disconnect(), timeout=2.0)
                    logger.info("Disconnected from Socket.IO server")
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for Socket.IO disconnect")
                except Exception as e:
                    logger.error("Error disconnecting from Socket.IO: %s", str(e))
        except Exception as e:
            logger.exception("Error during collector cleanup: %s", str(e))
            # Don't raise the exception during cleanup to allow other shutdown processes to continue

    async def _collect_metrics(self):
        """Collect metrics from the generator and put them in the queue."""
        metrics_count = 0
        try:
            async for metric in self.metrics_collector.generate_metrics():
                if not self.running:
                    break
                # Use put_nowait to avoid blocking if possible
                try:
                    self.queue.put_nowait(metric)
                except asyncio.QueueFull:
                    # If queue is full, fall back to blocking put
                    logger.warning("Queue full, waiting to add metric")
                    await self.queue.put(metric)
                
                metrics_count += 1
                if metrics_count % 100 == 0:  # Log every 100 metrics
                    logger.debug("Collected %d metrics", metrics_count)

        except Exception as e:
            logger.exception("Error in collect_metrics")
            raise
        finally:
            logger.info("Metrics collection stopped. Total metrics collected: %d", 
                       metrics_count)

    async def _send_metrics(self):
        """Send metrics from the queue to the endpoint via Socket.IO."""
        metrics_sent = 0
        errors = 0
        
        while self.running or not self.queue.empty():
            try:
                # Get metric from queue with a short timeout to be responsive
                try:
                    metric = await asyncio.wait_for(self.queue.get(), timeout=0.01)
                    
                    # Send metric through Socket.IO immediately
                    try:
                        logger.debug("Sending metric immediately: %s", json.dumps(metric, indent=2))
                        await self.sio.emit('metric', metric, namespace=self.namespace)
                        metrics_sent += 1
                        if metrics_sent % 100 == 0:  # Log every 100 metrics
                            logger.info("Sent %d metrics, %d errors", 
                                      metrics_sent, errors)
                                    
                    except Exception as e:
                        logger.exception("Socket.IO error sending metric: %s", str(e))
                        errors += 1
                    
                    # Mark task as done
                    self.queue.task_done()
                    
                except asyncio.TimeoutError:
                    # No metrics in queue, just continue the loop
                    await asyncio.sleep(0.01)  # Small sleep to prevent CPU spinning
                    
            except Exception as e:
                logger.exception("Unexpected error in send_metrics")
                errors += 1
                
        logger.info("Metrics sending complete. Sent: %d, Errors: %d", 
                   metrics_sent, errors)

    async def _save_dashboard_message(self, data):
        """Save a dashboard message to the logbook file.
        
        Args:
            data: The message data received from the dashboard
        """
        logger.info("Saving dashboard message: %s", json.dumps(data))
        
        try:
            # Create logbook directory in the current working directory
            logbook_dir = "logbook"
            os.makedirs(logbook_dir, exist_ok=True)
            
            # Write to logbook file in current working directory
            logbook_file = os.path.join(logbook_dir, "dashboard_messages.log")
            
            with open(logbook_file, "a") as f:
                timestamp = data.get("timestamp", datetime.now().isoformat())
                message = data.get("message", "No message content")
                user_ip = data.get("user_ip", "unknown")
                log_entry = f"[{timestamp}] [{user_ip}] {message}\n"
                f.write(log_entry)
            
            logger.info(f"Successfully saved dashboard message to logbook: {os.path.abspath(logbook_file)}")
            return True
        except Exception as e:
            logger.error(f"Failed to save dashboard message: {str(e)}")
            logger.exception("Detailed error:")
            return False

async def collect_and_send_metrics(endpoint_url: str, 
                                 metrics_collector: Any):
    """Main function to start collecting and sending metrics.
    
    Args:
        endpoint_url: The URL to send metrics to
        metrics_collector: Instance of a metrics collector class with generate_metrics method
    """
    logger.info("Starting metrics collection to %s", endpoint_url)
    collector = AsyncMetricsCollector(endpoint_url, metrics_collector)
    try:
        await collector.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        await collector.stop()
    except Exception as e:
        logger.exception("Fatal error in metrics collection")
