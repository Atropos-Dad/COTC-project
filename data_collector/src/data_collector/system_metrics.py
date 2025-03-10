"""Module for collecting system-related metrics."""
import psutil
import platform
import json
import socket
import logging
from datetime import datetime
from typing import Dict, Any, List, AsyncGenerator

from data_collector.models import SystemMetrics, GenericMetric, MetricsGenerator

logger = logging.getLogger(__name__)

def collect_system_metrics(cpu_measure_interval: int = 0.2) -> Dict[str, Any]:
    """Collect current system metrics."""
    
    
    # Get CPU information
    
    # - this is redundant -
    # with ThreadPoolExecutor() as executor:
    #     cpu_percent = executor.submit(lambda: psutil.cpu_percent(interval=cpu_measure_interval))

    cpu_percent = psutil.cpu_percent(interval=cpu_measure_interval)
    cpu_count_physical = psutil.cpu_count(logical=False)
    cpu_count_logical = psutil.cpu_count(logical=True)

    # Get CPU temperature
    if platform.system() == 'Linux':
        try:
            temps = psutil.sensors_temperatures()
            cpu_temp = None
            
            # ordered in terms of expected accuracy
            
            # Try k10temp (AMD CPUs)
            if 'k10temp' in temps:
                for entry in temps['k10temp']:
                    if entry.label == 'Tctl':
                        cpu_temp = entry.current
                        break
            
            # Try coretemp (Intel CPUs)
            if cpu_temp is None and 'coretemp' in temps:
                # Use the first core temperature as they're usually similar
                cpu_temp = temps['coretemp'][0].current
                
            
            # Try cros_ec CPU sensor
            if cpu_temp is None and 'cros_ec' in temps:
                for entry in temps['cros_ec']:
                    if 'cpu' in entry.label.lower():
                        cpu_temp = entry.current
                        break
            
            # Fallback to first acpitz reading
            if cpu_temp is None and 'acpitz' in temps:
                cpu_temp = temps['acpitz'][0].current

        except Exception as e:
            print(f"Error reading CPU temperature: {str(e)}")
            cpu_temp = None
    else:
        cpu_temp = None
     
    # Get memory information
    memory = psutil.virtual_memory()
    memory_total = memory.total
    memory_available = memory.available
    memory_percent = memory.percent

    # Get network information
    network = psutil.net_io_counters()
    network_bytes_sent = network.bytes_sent
    network_bytes_recv = network.bytes_recv

    # Get process count
    process_count = len(psutil.pids())

    # Get platform information
    platform_info = f"{platform.system()} {platform.release()}"
    python_version = platform.python_version()

    # cpu_percent = cpu_percent.result()
    # from testing, this is async approach is literally useless - 
    # time benefit is negligible
    # in fact, it's better when we don't use async (by 1000th of a second)

    result = {
        'cpu_count_physical': cpu_count_physical,
        'cpu_count_logical': cpu_count_logical,
        'cpu_percent': cpu_percent,
        'cpu_temp': cpu_temp,
        'memory_total': memory_total,
        'memory_available': memory_available,
        'memory_percent': memory_percent,
        'network_bytes_sent': network_bytes_sent,
        'network_bytes_recv': network_bytes_recv,
        'process_count': process_count,
        'platform_info': platform_info,
        'python_version': python_version
    }
    
    return result


def convert_to_generic_metrics(system_metrics: Dict[str, Any]) -> List[GenericMetric]:
    """
    Convert system metrics to GenericMetric objects.
    
    Args:
        system_metrics: Dictionary of system metrics as returned by collect_system_metrics()
        
    Returns:
        List of GenericMetric objects
    """
    result = []
    timestamp = datetime.now()
    hostname = socket.gethostname()
    
    # Process numeric metrics
    for key, value in system_metrics.items():
        # Skip non-numeric values and complex structures
        if not isinstance(value, (int, float)) or value is None:
            continue
            
        metric = GenericMetric(
            origin=hostname,
            metric_type=key,
            value=float(value),
            timestamp=timestamp,
            metadata={'system_info': system_metrics.get('platform_info')}
        )
        result.append(metric)
    
    return result


class SystemMetricsGenerator(MetricsGenerator):
    """Generates system metrics for AsyncMetricsCollector."""
    
    def __init__(self, interval_seconds: float = 10.0, cpu_measure_interval: float = 0.2):
        """Initialize system metrics generator.
        
        Args:
            interval_seconds: Interval between metric collections in seconds
            cpu_measure_interval: Interval for CPU percentage measurement
        """
        self.interval_seconds = interval_seconds
        self.cpu_measure_interval = cpu_measure_interval
        self.running = True
        logger.info("Initialized SystemMetricsGenerator with interval: %.1f sec", interval_seconds)
    
    async def generate_metrics(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Generate system metrics at regular intervals.
        
        Yields:
            Dict: Metric data in time series format
        """
        try:
            while self.running:
                # Collect system metrics
                system_metrics_dict = collect_system_metrics(cpu_measure_interval=self.cpu_measure_interval)
                
                # Convert to generic metrics format
                metrics = convert_to_generic_metrics(system_metrics_dict)
                
                # Yield each metric as a timeseries data point
                for metric in metrics:
                    yield metric.to_timeseries_format()
                
                # Wait for the next interval
                import asyncio
                await asyncio.sleep(self.interval_seconds)
        
        except Exception as e:
            logger.exception("Error in system metrics generation")
            raise
        finally:
            logger.info("System metrics generation stopped")
    
    def stop(self):
        """Stop metrics generation."""
        logger.info("Stopping system metrics generator")
        self.running = False
