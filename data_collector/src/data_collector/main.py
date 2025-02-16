"""Main entry point for the data collector."""
import asyncio
import logging
import async_metrics
import remote_metrics
from logging_config import setup_logging

logger = logging.getLogger(__name__)

async def main():
    # Set up logging
    setup_logging()
    logger.info("Starting data collector application")
    
    try:
        # Initialize the metrics collector
        logger.info("Initializing Lichess metrics collector")
        metrics_collector = remote_metrics.LichessMetricsCollector()
        
        # Create async metrics collector
        logger.info("Creating async metrics collector")
        collector = async_metrics.AsyncMetricsCollector(
            endpoint_url="http://localhost:5000/api/data",
            metrics_collector=metrics_collector
        )
        
        logger.info("Starting the metrics collector...")
        # Start collecting and sending metrics
        await collector.start()
        logger.info("Metrics collector stopped gracefully")
        
    except Exception as e:
        logger.exception("Fatal error in main process")
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.exception("Unhandled exception in main")
        raise
