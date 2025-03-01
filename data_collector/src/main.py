"""Main entry point for the data collector."""
import asyncio
import logging
import os
import data_collector.async_metrics
import data_collector.remote_metrics
from lib_config.config import Config
import signal

# Get the project root directory (one level up from the script directory)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.path.join(project_root, "config.json")

# Initialize configuration with the absolute path to config.json
config = Config(config_path=config_path)
# Set up logging and get a logger for this module
logger = config.get_logger(__name__)

# Global collector for cleanup
collector = None

def signal_handler(signum, frame):
    """Handle interrupt signals by initiating cleanup."""
    logger.info(f"Received signal {signum}")
    if collector:
        logger.info("Initiating graceful shutdown...")
        # Create event loop if needed
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Schedule the cleanup
        loop.create_task(collector.stop())
        
async def main():
    global collector
    logger.info("Starting data collector application")
    
    try:
        # Initialize the metrics collector
        logger.info("Initializing Lichess metrics collector")
        metrics_collector = data_collector.remote_metrics.LichessMetricsCollector()
        
        # Create async metrics collector with websocket endpoint
        logger.info("Creating async metrics collector")
        collector = data_collector.async_metrics.AsyncMetricsCollector(
            endpoint_url="ws://localhost:5000/ws/data",  # Changed to websocket endpoint
            metrics_collector=metrics_collector
        )
        
        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler, sig, None)
        
        logger.info("Starting the metrics collector...")
        # Start collecting and sending metrics
        await collector.start()
        logger.info("Metrics collector stopped gracefully")
        
    except Exception as e:
        logger.exception("Fatal error in main process")
        raise
    finally:
        if collector:
            try:
                await collector.stop()
            except Exception as e:
                logger.exception("Error during collector cleanup")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.exception("Unhandled exception in main")
        raise
