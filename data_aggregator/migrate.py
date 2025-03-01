"""
Command-line script to run the migration from log files to the database.
"""
import os
import sys
from src.migrate_data import main

if __name__ == "__main__":
    main()
