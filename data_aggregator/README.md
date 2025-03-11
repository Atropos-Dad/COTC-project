# Chess Data Aggregator

A data aggregation service that collects and stores chess game data.

## Overview

This application provides endpoints for collecting chess game data and stores it in a PostgreSQL or SQLite database using SQLAlchemy ORM. The application supports both HTTP and WebSocket connections for receiving data.

## Database Configuration

The application supports two database backends:

1. **PostgreSQL** (Recommended for production)
   - Configure PostgreSQL settings in `config.json`:
   ```json
   {
     "database": {
       "type": "postgresql",
       "host": "localhost",
       "port": 5432,
       "name": "chess_data",
       "user": "postgres",
       "password": "postgres",
       "pool_size": 10,
       "max_overflow": 20,
       "pool_timeout": 30
     }
   }
   ```

2. **SQLite** (Default for development)
   - Used automatically if PostgreSQL is not configured
   - Data stored in `data/chess_data.db`

## Database Schema

The database consists of three main tables:

1. **Games** - Stores information about chess games
   - game_id (unique identifier)
   - white_player, black_player (player usernames)
   - white_title, black_title (player titles like GM, IM, etc.)
   - white_rating, black_rating (player ELO ratings)
   - start_time (when the game started)

2. **Moves** - Stores individual moves for each game
   - game_id (links to the Games table)
   - last_move (the move notation)
   - white_time, black_time (remaining time for each player)
   - white_piece_count, black_piece_count (number of pieces remaining)
   - fen_position (current board position in FEN notation)
   - timestamp (when the move was made)

3. **RawData** - Stores the original JSON data received
   - measurement (data type identifier)
   - data (the full JSON data as received)
   - received_timestamp (when the data was received)
   - system_timestamp (original timestamp from the data if available)

## Installation

1. Make sure you have Python 3.8+ installed
2. Install dependencies using UV:

```bash
uv pip install -e .
```

## Database Migration and Application Run Process

### Database Migration

Before running the application, you need to migrate the data from the previous log file format to the SQLite database. This is done by running the migration script:

```bash
python migrate.py
```

This script will create the necessary tables in the SQLite database and populate them with data from the log files.

### Running the Application

After migrating the data, you can start the server:

```bash
python run.py
```

The server will be available at http://localhost:5000.

## API Endpoints

### HTTP API

- `POST /api/data` - Send chess game data

### WebSocket API

- Namespace: `/ws/data`
- Events:
  - `data` - Send chess game data
  - `connect` - Connection event
  - `disconnect` - Disconnection event