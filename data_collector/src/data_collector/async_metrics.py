"""Module for handling asynchronous metric collection and sending."""
import asyncio
import logging
import socketio  # Changed to python-socketio
import json
from typing import Any

logger = logging.getLogger(__name__)

class AsyncMetricsCollector:
    def __init__(self, 
                 endpoint_url: str, 
                 metrics_collector: Any,  # Instance of a metrics collector class
                 queue_size: int = 1000):
        """Initialize the async metrics collector.
        
        Args:
            endpoint_url: The URL to send metrics to (should be a ws:// or wss:// URL)
            metrics_collector: Instance of a metrics collector class with generate_metrics method
            queue_size: Maximum size of the queue before blocking
        """
        # Convert ws:// to http:// for Socket.IO
        self.endpoint_url = endpoint_url.replace('ws://', 'http://').replace('wss://', 'https://') # TODO: why??
        self.metrics_collector = metrics_collector
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.running = False
        
        # Initialize Socket.IO client
        self.sio = socketio.AsyncClient()
        self._setup_socketio_handlers()
        logger.info("Initialized AsyncMetricsCollector with endpoint: %s, queue_size: %d", 
                   endpoint_url, queue_size)

    def _setup_socketio_handlers(self):
        """Set up Socket.IO event handlers."""
        @self.sio.event
        async def connect():
            logger.info("Connected to Socket.IO server at %s", self.endpoint_url)

        @self.sio.event
        async def disconnect():
            logger.warning("Disconnected from Socket.IO server at %s", self.endpoint_url)

        @self.sio.event
        def success(data):
            logger.info("Server acknowledged data: %s", data)

        @self.sio.event
        def error(data):
            logger.error("Server reported error: %s", data)

        @self.sio.event
        def connect_error(data):
            logger.error("Connection error to Socket.IO server: %s", data)

    async def start(self):
        """Start the metrics collection and sending processes."""
        logger.info("Starting metrics collection and sending processes")
        self.running = True

        # Connect to Socket.IO server
        try:
            await self.sio.connect(self.endpoint_url, namespaces=['/ws/data'])
        except Exception as e:
            logger.error("Failed to connect to Socket.IO server: %s", str(e))
            raise

        # Create tasks for producer and consumer
        producer = asyncio.create_task(self._collect_metrics())
        consumer = asyncio.create_task(self._send_metrics())
        
        try:
            # Wait for both tasks
            await asyncio.gather(producer, consumer)
        except Exception as e:
            logger.exception("Error in metrics collection/sending tasks")
            raise
        finally:
            logger.info("Metrics collection and sending processes stopped")
            await self.sio.disconnect()

    async def stop(self):
        """Stop the metrics collection and sending processes."""
        if not self.running:
            logger.info("Collector already stopped")
            return

        logger.info("Stopping metrics collection")
        self.running = False
        
        try:
            # Wait for queue to be empty with a timeout
            try:
                await asyncio.wait_for(self.queue.join(), timeout=5.0)
                logger.info("All pending metrics processed")
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for queue to empty, some metrics may be lost")
            
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
            logger.exception("Error during collector cleanup")
            raise

    async def _collect_metrics(self):
        """Collect metrics from the generator and put them in the queue."""
        metrics_count = 0
        try:
            async for metric in self.metrics_collector.generate_metrics():
                if not self.running:
                    break
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
                # Get metric from queue
                metric = await self.queue.get()
                
                # Send metric through Socket.IO
                try:
                    logger.debug("Attempting to send metric: %s", json.dumps(metric, indent=2))
                    await self.sio.emit('data', metric, namespace='/ws/data')
                    metrics_sent += 1
                    if metrics_sent % 100 == 0:  # Log every 100 metrics
                        logger.info("Sent %d metrics, %d errors", 
                                   metrics_sent, errors)
                                
                except Exception as e:
                    logger.exception("Socket.IO error sending metric: %s", str(e))
                    errors += 1
                
                # Mark task as done
                self.queue.task_done()
                
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
