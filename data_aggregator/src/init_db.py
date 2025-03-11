"""
Database initialization script for the data aggregator.
"""
import os
import sys
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError, ProgrammingError
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from lib_config.config import Config
from models import Base

# Get the project root directory
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.path.join(project_root, "config.json")

# Initialize configuration
config = Config(config_path=config_path)
logger = config.get_logger(__name__)

def create_database():
    """Create the PostgreSQL database if it doesn't exist."""
    try:
        # Connect to PostgreSQL server (not to a specific database)
        conn = psycopg2.connect(
            host=config.database.host,
            port=config.database.port,
            user=config.database.user,
            password=config.database.password
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        # Check if database exists
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (config.database.name,))
        exists = cursor.fetchone()
        
        if not exists:
            logger.info(f"Creating database {config.database.name}")
            cursor.execute(f'CREATE DATABASE {config.database.name}')
            logger.info(f"Database {config.database.name} created successfully")
        else:
            logger.info(f"Database {config.database.name} already exists")
            
    except psycopg2.Error as e:
        logger.error(f"Error creating database: {str(e)}")
        raise
    finally:
        cursor.close()
        conn.close()

def init_schema():
    """Initialize the database schema using SQLAlchemy models."""
    try:
        # Create SQLAlchemy engine for the specific database
        db_url = f"postgresql://{config.database.user}:{config.database.password}@{config.database.host}:{config.database.port}/{config.database.name}"
        engine = create_engine(db_url)
        
        # Create all tables
        logger.info("Creating database schema")
        Base.metadata.create_all(engine)
        logger.info("Database schema created successfully")
        
    except SQLAlchemyError as e:
        logger.error(f"Error initializing database schema: {str(e)}")
        raise

def main():
    """Main initialization function."""
    try:
        logger.info("Starting database initialization")
        
        # Create database if using PostgreSQL
        if config.database.type == "postgresql":
            create_database()
        
        # Initialize schema
        init_schema()
        
        logger.info("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 