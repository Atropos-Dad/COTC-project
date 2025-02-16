"""Data collector package for system metrics."""

from .system_metrics import collect_system_metrics, SystemMetrics

__all__ = ['collect_system_metrics', 'SystemMetrics']

def hello() -> str:
    return "Hello from data-collector!"
