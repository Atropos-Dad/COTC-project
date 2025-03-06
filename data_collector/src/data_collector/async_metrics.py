"""Module for handling asynchronous metric collection and sending."""
import asyncio
import logging
import socketio  # Changed to python-socketio
import json
import time
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
        self._setup_socketio_handlers()
        logger.info("Initialized AsyncMetricsCollector with endpoint: %s, queue_size: %d, reconnect_interval: %d", 
                   endpoint_url, queue_size, reconnect_interval)

    def _setup_socketio_handlers(self):
        """Set up Socket.IO event handlers."""
        @self.sio.event
        async def connect():
            logger.info("Connected to Socket.IO server at %s with namespace %s", self.endpoint_url, self.namespace)
            self.connected = True
            self.reconnect_count = 0  # Reset reconnect counter on successful connection
            # Process any buffered metrics once connected
            asyncio.create_task(self._process_buffer())

        @self.sio.event
        async def disconnect():
            logger.warning("Disconnected from Socket.IO server at %s", self.endpoint_url)
            self.connected = False

        @self.sio.event
        def success(data):
            logger.info("Server acknowledged data: %s", data)

        @self.sio.event
        def error(data):
            logger.error("Server reported error: %s", data)

        @self.sio.event
        def connect_error(data):
            logger.error("Connection error to Socket.IO server: %s", data)
            self.connected = False
            # Will automatically reconnect based on the client settings

    async def _connect_with_retry(self):
        """Connect to Socket.IO server with retries."""
        while self.running:
            try:
                if not self.sio.connected:
                    logger.info("Attempting to connect to Socket.IO server at %s", self.endpoint_url)
                    await self.sio.connect(self.endpoint_url, namespaces=[self.namespace])
                    return True
                else:
                    return True  # Already connected
            except socketio.exceptions.ConnectionError as e:
                self.reconnect_count += 1
                if self.max_reconnect_attempts > 0 and self.reconnect_count >= self.max_reconnect_attempts:
                    logger.error("Failed to connect after %d attempts. Giving up.", self.reconnect_count)
                    return False
                
                wait_time = self.reconnect_interval
                logger.warning("Connection attempt %d failed: %s. Retrying in %d seconds...", 
                              self.reconnect_count, str(e), wait_time)
                await asyncio.sleep(wait_time)
            except Exception as e:
                logger.exception("Unexpected error while connecting to Socket.IO server: %s", str(e))
                await asyncio.sleep(self.reconnect_interval)
        
        return False  # Not running anymore
    
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
