"""Main entry point for the data collector."""
import asyncio
import logging
import os
import data_collector.async_metrics
import data_collector.remote_metrics
import data_collector.system_metrics
import data_collector.metrics_sender
from lib_config.config import Config
import signal

# Get the project root directory (one level up from the script directory)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.path.join(project_root, "config.json")

# Initialize configuration with the absolute path to config.json
config = Config(config_path=config_path)
# Set up logging and get a logger for this module
logger = config.get_logger(__name__)

# Global collectors for cleanup
metrics_collectors = []

def signal_handler(signum, frame):
    """Handle interrupt signals by initiating cleanup."""
    logger.info("Received signal %s", signum)
    if metrics_collectors:
        logger.info("Initiating graceful shutdown...")
        # Create event loop if needed
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Schedule the cleanup for all collectors
        for collector in metrics_collectors:
            loop.create_task(collector.stop())
        
async def main():
    global metrics_collectors
    logger.info("Starting data collector application")
    
    try:
        # Initialize the system metrics collector with interval from config
        logger.info("Initializing System metrics collector")
        system_metrics_collector = data_collector.system_metrics.SystemMetricsGenerator(
            interval_seconds=config.get("metrics.system_metrics_interval_seconds")
        )
        
        # Initialize the Lichess metrics collectors
        logger.info("Initializing Lichess metrics collectors")
        # One for game metrics
        lichess_game_metrics_collector = data_collector.remote_metrics.LichessMetricsCollector(mode="game")
        # One for system metrics (piece counts)
        lichess_system_metrics_collector = data_collector.remote_metrics.LichessMetricsCollector(mode="system")
        
        # Create async metrics collectors with websocket endpoints
        logger.info("Creating async metrics collectors")
        
        # System metrics collector
        system_collector = data_collector.async_metrics.AsyncMetricsCollector(
            endpoint_url=config.get("metrics.endpoints.system_metrics"),
            metrics_collector=system_metrics_collector
        )
        
        # Lichess game metrics collector (for chess game data)
        lichess_game_collector = data_collector.async_metrics.AsyncMetricsCollector(
            endpoint_url=config.get("metrics.endpoints.game_metrics"),
            metrics_collector=lichess_game_metrics_collector
        )
        
        # Lichess system metrics collector (for piece counts)
        lichess_system_collector = data_collector.async_metrics.AsyncMetricsCollector(
            endpoint_url=config.get("metrics.endpoints.system_metrics"),
            metrics_collector=lichess_system_metrics_collector
        )
        
        # Add collectors to global list for cleanup
        metrics_collectors = [
            system_collector,
            lichess_game_collector,
            lichess_system_collector
        ]
        
        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler, sig, None)
        
        logger.info("Starting the metrics collectors...")
        # Start collecting and sending metrics in parallel
        collection_tasks = []
        for collector in metrics_collectors:
            collection_tasks.append(asyncio.create_task(collector.start()))
            
        # Wait for all collection tasks
        await asyncio.gather(*collection_tasks)
        logger.info("All metrics collectors stopped gracefully")
        
    except Exception as e:
        logger.exception("Fatal error in main process")
        raise
    finally:
        for collector in metrics_collectors:
            try:
                await collector.stop()
            except Exception as e:
                logger.exception("Error during collector cleanup: %s", str(e))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.exception("Unhandled exception in main")
        raise
