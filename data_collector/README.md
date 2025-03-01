# Data Collector Service

A Python service for collecting system and remote metrics asynchronously.

## Features

- Asynchronous metric collection
- Remote metrics gathering
- System metrics monitoring
- Configurable logging
- Graceful shutdown handling

## Installation

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

## Project Structure

```
data_collector/
├── src/
│   └── data_collector/
│       ├── __init__.py
│       ├── main.py              # Entry point
│       ├── async_metrics.py     # Async metric collection
│       ├── remote_metrics.py    # Remote metric gathering
│       ├── system_metrics.py    # System metric collection
│       ├── models.py           # Data models
│       └── logging_config.py   # Logging configuration
├── tests/                      # Test directory
├── pyproject.toml             # Project configuration
├── README.md                  # This file
└── .env                       # Environment variables (gitignored)
```

## Usage

1. Copy `.env.example` to `.env` and configure your settings
2. Run the collector:
   ```bash
   python -m data_collector.main
   ```

## Development

- Format code: `black src/`
- Sort imports: `isort src/`
- Run tests: `pytest`
- Type checking: `mypy src/`

## Configuration

The service can be configured through environment variables:

- `LOG_LEVEL`: Logging level (default: INFO)
- `METRICS_INTERVAL`: Collection interval in seconds (default: 60)
- `REMOTE_ENDPOINT`: Remote metrics endpoint URL

## License

MIT