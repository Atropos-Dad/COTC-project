"""Module for collecting system-related metrics."""
import psutil
import platform
import json
from dataclasses import dataclass, asdict
from typing import Dict, Any

@dataclass
class SystemMetrics:
    cpu_count_physical: int
    cpu_count_logical: int
    cpu_percent: float
    cpu_temp: float
    memory_total: int
    memory_available: int
    memory_percent: float
    disk_usage: Dict[str, Dict[str, Any]]
    platform_info: str
    python_version: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert the SystemMetrics instance to a dictionary."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert the SystemMetrics instance to a JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> 'SystemMetrics':
        """Create a SystemMetrics instance from a JSON string."""
        data = json.loads(json_str)
        return cls(**data)


def collect_system_metrics(cpu_measure_interval: int = 0.2) -> SystemMetrics:
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

    # Get disk usage for all mounted partitions
    disk_usage = {}
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disk_usage[partition.mountpoint] = {
                'total': usage.total,
                'used': usage.used,
                'free': usage.free,
                'percent': usage.percent
            }
        except PermissionError:
            continue

    # Get platform information
    platform_info = f"{platform.system()} {platform.release()}"
    python_version = platform.python_version()

    # cpu_percent = cpu_percent.result()
    # from testing, this is async approach is literally useless - 
    # time benefit is negligible
    # in fact, it's better when we don't use async (by 1000th of a second)

    result = SystemMetrics(
        cpu_count_physical=cpu_count_physical,
        cpu_count_logical=cpu_count_logical,
        cpu_percent=cpu_percent,
        cpu_temp=cpu_temp,
        memory_total=memory_total,
        memory_available=memory_available,
        memory_percent=memory_percent,
        disk_usage=disk_usage,
        platform_info=platform_info,
        python_version=python_version
    )
    
    return result
