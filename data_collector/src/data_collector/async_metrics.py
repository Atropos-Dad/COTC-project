"""Module for handling asynchronous metric collection and sending."""
import asyncio
import logging
import aiohttp
from typing import Any

logger = logging.getLogger(__name__)

class AsyncMetricsCollector:
    def __init__(self, 
                 endpoint_url: str, 
                 metrics_collector: Any,  # Instance of a metrics collector class
                 queue_size: int = 1000):
        """Initialize the async metrics collector.
        
        Args:
            endpoint_url: The URL to send metrics to
            metrics_collector: Instance of a metrics collector class with generate_metrics method
            queue_size: Maximum size of the queue before blocking
        """
        self.endpoint_url = endpoint_url
        self.metrics_collector = metrics_collector
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.running = False
        logger.info("Initialized AsyncMetricsCollector with endpoint: %s, queue_size: %d", 
                   endpoint_url, queue_size)

    async def start(self):
        """Start the metrics collection and sending processes."""
        logger.info("Starting metrics collection and sending processes")
        self.running = True

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

    async def stop(self):
        """Stop the metrics collection and sending processes."""
        logger.info("Stopping metrics collection")
        self.running = False
        # Wait for queue to be empty
        await self.queue.join()
        logger.info("All pending metrics processed")

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
        """Send metrics from the queue to the endpoint."""
        metrics_sent = 0
        errors = 0
        
        async with aiohttp.ClientSession() as session:
            while self.running or not self.queue.empty():
                try:
                    # Get metric from queue
                    metric = await self.queue.get()
                    
                    # Send metric to endpoint
                    try:
                        async with session.post(
                            self.endpoint_url,
                            json=metric,
                            headers={'Content-Type': 'application/json'}
                        ) as response:
                            if response.status not in (200, 201, 202):
                                logger.error("Failed to send metric: HTTP %d", 
                                           response.status)
                                errors += 1
                            else:
                                metrics_sent += 1
                                if metrics_sent % 100 == 0:  # Log every 100 metrics
                                    logger.debug("Sent %d metrics, %d errors", 
                                               metrics_sent, errors)
                                    
                    except aiohttp.ClientError as e:
                        logger.error("Network error sending metric: %s", str(e))
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
