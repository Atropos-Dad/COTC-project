"""Module for sending generic metrics to the data aggregator server using the existing AsyncMetricsCollector."""
import json
import logging
import asyncio
import requests
from typing import Dict, Any, List, Generator, AsyncGenerator
from datetime import datetime
from urllib.parse import urljoin

from data_collector.async_metrics import AsyncMetricsCollector
from data_collector.models import GenericMetric, MetricsGenerator

logger = logging.getLogger(__name__)

class GenericMetricsGenerator(MetricsGenerator):
    """Generator class for providing generic metrics to AsyncMetricsCollector.
    
    This class implements the MetricsGenerator protocol and allows manual
    addition of metrics for sending to the server.
    """
    
    def __init__(self):
        """Initialize the metrics generator."""
        self.metrics_queue = asyncio.Queue()
        self.running = True
        logger.info("Initialized GenericMetricsGenerator")
    
    async def add_metric(self, metric: GenericMetric):
        """Add a GenericMetric to the queue for processing.
        
        Args:
            metric: GenericMetric object
        """
        # Convert to timeseries format
        formatted_metric = metric.to_timeseries_format()
        await self.metrics_queue.put(formatted_metric)
        logger.debug("Added metric to queue: %s", metric.metric_type)
        
    async def add_dict_metric(self, metric: Dict[str, Any]):
        """Add a metric from dictionary format for backward compatibility.
        
        Args:
            metric: Metric data with format:
                {
                    'origin': str,          # Source of the metric
                    'metric_type': str,     # Type of metric
                    'value': float,         # Numeric value
                    'timestamp': datetime,  # Optional, defaults to now
                    'metadata': dict        # Optional additional context
                }
        """
        # Create timestamp if missing
        if 'timestamp' not in metric or not metric['timestamp']:
            metric['timestamp'] = datetime.now()
        elif isinstance(metric['timestamp'], str):
            try:
                metric['timestamp'] = datetime.fromisoformat(metric['timestamp'])
            except ValueError:
                metric['timestamp'] = datetime.now()
            
        # Convert to GenericMetric and add to queue
        generic_metric = GenericMetric(
            origin=metric.get('origin', 'unknown'),
            metric_type=metric.get('metric_type', 'unknown'),
            value=float(metric.get('value', 0.0)),
            timestamp=metric['timestamp'],
            metadata=metric.get('metadata')
        )
        
        await self.add_metric(generic_metric)
    
    async def add_metrics(self, metrics: List):
        """Add multiple metrics to the queue.
        
        Args:
            metrics: List of GenericMetric objects or metric dictionaries
        """
        for metric in metrics:
            if isinstance(metric, GenericMetric):
                await self.add_metric(metric)
            elif isinstance(metric, dict):
                await self.add_dict_metric(metric)
            else:
                logger.warning("Ignoring invalid metric type: %s", type(metric))
    
    async def generate_metrics(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Generate metrics from the queue.
        
        Implements the interface expected by AsyncMetricsCollector.
        
        Yields:
            dict: Metric data in the timeseries format expected by the server
        """
        while self.running or not self.metrics_queue.empty():
            try:
                # Get with timeout to allow for checking running flag
                metric = await asyncio.wait_for(self.metrics_queue.get(), timeout=0.5)
                yield metric
                self.metrics_queue.task_done()
            except asyncio.TimeoutError:
                # No metrics available, check if we should continue running
                if not self.running and self.metrics_queue.empty():
                    break
            except Exception as e:
                logger.exception("Error in generate_metrics: %s", str(e))
                # Continue on error to maintain the generator
    
    async def stop(self):
        """Stop the metrics generator."""
        self.running = False
        # Wait for queue to empty
        if not self.metrics_queue.empty():
            try:
                await asyncio.wait_for(self.metrics_queue.join(), timeout=5.0)
                logger.info("All queued metrics processed")
            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for metrics queue to empty")

class GenericMetricsSender:
    """Client for sending generic metrics to the server using AsyncMetricsCollector."""
    
    def __init__(self, endpoint_url: str = "http://localhost:5000/ws/metrics", use_async: bool = True):
        """
        Initialize the metrics sender.
        
        Args:
            endpoint_url: The WebSocket endpoint URL for the metrics server
            use_async: Whether to use the AsyncMetricsCollector (True) or HTTP fallback (False)
        """
        self.endpoint_url = endpoint_url
        self.use_async = use_async
        self.metrics_generator = GenericMetricsGenerator()
        self.collector = None
        self.collector_task = None
        
        if use_async:
            # Create the AsyncMetricsCollector with our generator
            self.collector = AsyncMetricsCollector(
                endpoint_url=endpoint_url,
                metrics_collector=self.metrics_generator
            )
        
        logger.info("Initialized GenericMetricsSender with endpoint: %s, use_async: %s", endpoint_url, use_async)
    
    async def start(self):
        """Start the async metrics collector if in async mode."""
        if self.use_async and self.collector:
            try:
                # Start the collector in a separate task
                self.collector_task = asyncio.create_task(self.collector.start())
                logger.info("Started AsyncMetricsCollector")
                return True
            except Exception as e:
                logger.error(f"Failed to start AsyncMetricsCollector: {str(e)}")
                return False
        return False
    
    async def stop(self):
        """Stop the async metrics collector and generator."""
        if self.use_async:
            if self.collector:
                try:
                    await self.collector.stop()
                    logger.info("Stopped AsyncMetricsCollector")
                except Exception as e:
                    logger.error(f"Error stopping AsyncMetricsCollector: {str(e)}")
            
            if self.metrics_generator:
                try:
                    await self.metrics_generator.stop()
                    logger.info("Stopped GenericMetricsGenerator")
                except Exception as e:
                    logger.error(f"Error stopping GenericMetricsGenerator: {str(e)}")
            
            if self.collector_task:
                try:
                    # Cancel the task if it's still running
                    if not self.collector_task.done():
                        self.collector_task.cancel()
                        try:
                            await self.collector_task
                        except asyncio.CancelledError:
                            pass
                    logger.info("Cancelled collector task")
                except Exception as e:
                    logger.error(f"Error cancelling collector task: {str(e)}")
    
    async def send_metric(self, metric) -> Dict[str, Any]:
        """Send a single metric to the server.
        
        Args:
            metric: Either a GenericMetric object or a dictionary with the format:
                {
                    'origin': str,          # Source of the metric
                    'metric_type': str,     # Type of metric
                    'value': float,         # Numeric value
                    'timestamp': datetime,  # Optional, defaults to now
                    'metadata': dict        # Optional additional context
                }
                
        Returns:
            dict: Server response or error information
        """
        if self.use_async and self.metrics_generator:
            try:
                if isinstance(metric, GenericMetric):
                    await self.metrics_generator.add_metric(metric)
                else:
                    await self.metrics_generator.add_dict_metric(metric)
                return {'success': True, 'message': 'Metric queued for async sending'}
            except Exception as e:
                logger.error("Error queuing metric: %s", str(e))
                return {'success': False, 'error': str(e)}
        else:
            # Fallback to HTTP if not using async
            try:
                # Convert to dictionary if it's a GenericMetric
                if isinstance(metric, GenericMetric):
                    metric_dict = {
                        'origin': metric.origin,
                        'metric_type': metric.metric_type,
                        'value': metric.value,
                        'timestamp': metric.timestamp,
                        'metadata': metric.metadata
                    }
                else:
                    metric_dict = metric.copy()  # Create a copy to avoid modifying the original
                
                # Format timestamp for HTTP endpoint
                if 'timestamp' in metric_dict and isinstance(metric_dict['timestamp'], datetime):
                    metric_dict['timestamp'] = metric_dict['timestamp'].isoformat()
                
                url = urljoin(self.endpoint_url.replace('ws://', 'http://').replace('wss://', 'https://'), 
                             '/api/metrics')
                response = requests.post(
                    url, 
                    json=metric_dict,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code in (200, 201):
                    return {'success': True, 'response': response.json()}
                else:
                    logger.error("Error sending metric via HTTP: %s - %s", response.status_code, response.text)
                    return {'success': False, 'error': f"HTTP {response.status_code}: {response.text}"}
            except Exception as e:
                logger.error("Error sending metric via HTTP: %s", str(e))
                return {'success': False, 'error': str(e)}
    
    async def send_metrics(self, metrics: List) -> List[Dict[str, Any]]:
        """Send multiple metrics to the server.
        
        Args:
            metrics: List of GenericMetric objects or metric dictionaries
                
        Returns:
            list: List of server responses or error information for each metric
        """
        if self.use_async and self.metrics_generator:
            try:
                await self.metrics_generator.add_metrics(metrics)
                return [{'success': True, 'message': 'Metric queued for async sending'} for _ in metrics]
            except Exception as e:
                logger.error("Error queuing metrics: %s", str(e))
                return [{'success': False, 'error': str(e)} for _ in metrics]
        else:
            # Fallback to HTTP if not using async
            results = []
            for metric in metrics:
                result = await self.send_metric(metric)
                results.append(result)
            return results
