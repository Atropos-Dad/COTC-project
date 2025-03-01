"""
Migration script to transfer data from log files to the SQLite database.
"""
import os
import glob
import logging
from .database import init_db, migrate_log_to_db

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """
    Main function to migrate all log files to database.
    """
    try:
        # Initialize database
        logger.info("Initializing database...")
        init_db()
        
        # Find all log files
        data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        log_files = glob.glob(os.path.join(data_dir, "data_*.log"))
        
        if not log_files:
            logger.warning("No log files found in data directory.")
            return
        
        logger.info(f"Found {len(log_files)} log files to migrate.")
        
        # Migrate each log file
        total_records = 0
        for log_file in sorted(log_files):
            logger.info(f"Migrating {os.path.basename(log_file)}...")
            records_migrated = migrate_log_to_db(log_file)
            total_records += records_migrated
            logger.info(f"Migrated {records_migrated} records from {os.path.basename(log_file)}")
            
            # Optionally rename the processed file to avoid reprocessing
            # os.rename(log_file, f"{log_file}.migrated")
        
        logger.info(f"Migration complete. Total records migrated: {total_records}")
        
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()
