"""
Dashboard module for visualizing chess data in real-time.
"""
import dash
from dash import dcc, html, callback, Output, Input, clientside_callback, State
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import func, desc
from sqlalchemy.sql import text
import re
import logging
import json
import requests
import functools
from sqlalchemy.orm import joinedload

# Initialize logger
logger = logging.getLogger(__name__)

from models import Game, Move, RawData, Metric, MetricType, MetricOrigin, TimeZoneSource, Player
from database import Session
from chess_utils import is_valid_fen, derive_fen_from_moves, DEFAULT_FEN

# Global cache reference
_cache = None

# Cache utility functions
def init_cache(cache_instance):
    """Initialize the global cache reference."""
    global _cache
    _cache = cache_instance
    logger.info("Cache initialized in dashboard module")

def cached_query(timeout=60):
    """
    Decorator to cache a function that returns query results.
    
    Args:
        timeout: Cache timeout in seconds (default: 60)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if _cache is None:
                # No cache available, execute the function directly
                logger.debug(f"No cache available for {func.__name__}, executing directly")
                return func(*args, **kwargs)
            
            # Create a cache key based on function name and arguments
            key = f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            
            # Try to get from cache first
            result = _cache.get(key)
            if result is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return result
            
            # If not in cache, execute the function and cache the result
            logger.debug(f"Cache miss for {func.__name__}, executing query")
            result = func(*args, **kwargs)
            _cache.set(key, result, timeout=timeout)
            return result
        return wrapper
    return decorator

# Initialize the Dash app with Bootstrap theme
dash_app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.css"
    ],
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    url_base_pathname='/dash/',
    external_scripts=[
        "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/chess.js/0.10.3/chess.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.js"
    ]
)

# Define the layout - fixed to remove duplicate elements
dash_app.layout = dbc.Container([
    # Hidden containers for data - using dcc.Store instead of html.Div for state
    dcc.Store(id="current-fen", data=DEFAULT_FEN),
    dcc.Store(id="game-moves", data=[]),
    html.Div(id="clientside-script-container", style={"display": "none"}),
    
    # Store for debug info
    dcc.Store(id="debug-fen", data=DEFAULT_FEN),
    
    # Add refresh interval component
    dcc.Interval(
        id='interval-component',
        interval=500,  # in milliseconds
        n_intervals=0
    ),
    
    # Dashboard header
    dbc.Row([
        dbc.Col([
            html.H1("Chess Data Dashboard", className="text-center my-4"),
            html.Hr()
        ], width=12)
    ]),
    
    # Debug information display
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Debug Information"),
                dbc.CardBody([
                    html.Pre(id="debug-display", className="small")
                ])
            ], className="mb-4")
        ], width=12)
    ]),
    
    # Dashboard metrics row
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Games Overview"),
                dbc.CardBody([
                    html.Div(id="games-count", className="text-center h3"),
                    html.Div(id="active-games", className="text-center h5 text-muted")
                ])
            ], className="mb-4")
        ], width=4),
        
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Data Ingestion Rate"),
                dbc.CardBody([
                    html.Div(id="data-rate", className="text-center h3"),
                    html.Div("events per minute", className="text-center text-muted")
                ])
            ], className="mb-4")
        ], width=4),
        
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Latest Event"),
                dbc.CardBody([
                    html.Div(id="latest-event", className="text-center h5")
                ])
            ], className="mb-4")
        ], width=4)
    ]),
    
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Data Ingestion Over Time"),
                dbc.CardBody([
                    dcc.Graph(id="ingestion-graph")
                ])
            ], className="mb-4")
        ], width=12)
    ]),
    
    # System Metrics Section
    dbc.Row([
        dbc.Col([
            html.H2("System Metrics", className="mt-4 mb-3")
        ], width=12)
    ]),
    
    # All Metrics Table Section
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("All Metrics"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Filter by Origin:"),
                            dcc.Dropdown(
                                id="metrics-origin-filter",
                                options=[],
                                placeholder="Select origin...",
                                clearable=True
                            )
                        ], width=4),
                        dbc.Col([
                            html.Label("Filter by Metric Type:"),
                            dcc.Dropdown(
                                id="metrics-type-filter",
                                options=[],
                                placeholder="Select metric type...",
                                clearable=True
                            )
                        ], width=4),
                        dbc.Col([
                            html.Label("Records per page:"),
                            dcc.Dropdown(
                                id="metrics-page-size",
                                options=[
                                    {"label": "10", "value": 10},
                                    {"label": "25", "value": 25},
                                    {"label": "50", "value": 50},
                                    {"label": "100", "value": 100}
                                ],
                                value=25,
                                clearable=False
                            )
                        ], width=4)
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Filter by Date Range:"),
                            dcc.DatePickerRange(
                                id="metrics-date-range",
                                start_date_placeholder_text="Start Date",
                                end_date_placeholder_text="End Date",
                                clearable=True,
                                with_portal=True,
                                className="mb-3"
                            )
                        ], width=12)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Filter by Value Range:"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Input(
                                        id="metrics-min-value",
                                        type="number",
                                        placeholder="Min Value",
                                        step="any"
                                    )
                                ], width=6),
                                dbc.Col([
                                    dbc.Input(
                                        id="metrics-max-value",
                                        type="number",
                                        placeholder="Max Value",
                                        step="any"
                                    )
                                ], width=6)
                            ]),
                            html.Small("Set min and max to filter by range", className="text-muted")
                        ], width=6, className="mb-3"),
                        dbc.Col([
                            html.Label("Search Exact Value:"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Input(
                                        id="metrics-exact-value",
                                        type="number",
                                        placeholder="Exact Value",
                                        step="any"
                                    )
                                ], width=7),
                                dbc.Col([
                                    dbc.Input(
                                        id="metrics-value-tolerance",
                                        type="number",
                                        placeholder="±Tolerance",
                                        step="any",
                                        min=0
                                    )
                                ], width=5)
                            ]),
                            html.Small("Add tolerance for fuzzy matching", className="text-muted")
                        ], width=6, className="mb-3")
                    ]),
                    dbc.Row([
                        dbc.Col([
                            dbc.Button("Reset Filters", id="reset-metrics-filters", color="secondary", size="sm", className="mb-3 me-2"),
                            dbc.Button("Apply Filters", id="apply-metrics-filters", color="primary", size="sm", className="mb-3")
                        ], width=12)
                    ]),
                    html.Div(id="all-metrics-table"),
                    dbc.Row([
                        dbc.Col([
                            dbc.Pagination(
                                id="metrics-pagination",
                                max_value=5,
                                first_last=True,
                                previous_next=True,
                                active_page=1,
                                step=2,
                                fully_expanded=False
                            )
                        ], width=12, className="d-flex justify-content-center mt-3")
                    ])
                ])
            ], className="mb-4")
        ], width=12)
    ]),
    
    # Message to Clients Section
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Send Message to Clients"),
                dbc.CardBody([
                    dbc.Input(id="client-message", placeholder="Enter message for clients...", type="text"),
                    dbc.Button("Send Message", id="send-message-button", color="primary", className="mt-2")
                ])
            ], className="mb-4")
        ], width=12)
    ]),
    
    # Current System Metrics
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("CPU Usage"),
                dbc.CardBody([
                    html.Div(id="current-cpu", className="text-center h3"),
                    html.Div("percent", className="text-center text-muted")
                ])
            ], className="mb-4")
        ], width=3),
        
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Memory Usage"),
                dbc.CardBody([
                    html.Div(id="current-memory", className="text-center h3"),
                    html.Div("percent", className="text-center text-muted")
                ])
            ], className="mb-4")
        ], width=3),
        
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Process Count"),
                dbc.CardBody([
                    html.Div(id="current-processes", className="text-center h3"),
                    html.Div("processes", className="text-center text-muted")
                ])
            ], className="mb-4")
        ], width=2),
        
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("White Pieces"),
                dbc.CardBody([
                    html.Div(id="current-white-pieces", className="text-center h3"),
                    html.Div("pieces", className="text-center text-muted")
                ])
            ], className="mb-4")
        ], width=2),
        
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Black Pieces"),
                dbc.CardBody([
                    html.Div(id="current-black-pieces", className="text-center h3"),
                    html.Div("pieces", className="text-center text-muted")
                ])
            ], className="mb-4")
        ], width=2)
    ]),
    
    # CPU and Memory Usage
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("CPU Usage Over Time"),
                dbc.CardBody([
                    dcc.Graph(id="cpu-usage-graph")
                ])
            ], className="mb-4")
        ], width=6),
        
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Memory Usage Over Time"),
                dbc.CardBody([
                    dcc.Graph(id="memory-usage-graph")
                ])
            ], className="mb-4")
        ], width=6)
    ]),
    
    # Network Usage
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Network Traffic"),
                dbc.CardBody([
                    dcc.Graph(id="network-traffic-graph")
                ])
            ], className="mb-4")
        ], width=12),
    ]),
    
    # Combined System Metrics
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Combined System Metrics"),
                dbc.CardBody([
                    dcc.Graph(id="combined-metrics-graph")
                ])
            ], className="mb-4")
        ], width=12)
    ]),
    
    # Chess Piece Counts
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Chess Piece Counts Over Time"),
                dbc.CardBody([
                    dcc.Graph(id="chess-pieces-graph")
                ])
            ], className="mb-4")
        ], width=12)
    ]),
    
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Game Events Distribution"),
                dbc.CardBody([
                    dcc.Graph(id="events-distribution")
                ])
            ], className="mb-4")
        ], width=6),
        
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Recent Games"),
                dbc.CardBody([
                    html.Div(id="recent-games-table")
                ])
            ], className="mb-4")
        ], width=6)
    ]),
    
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.Span("Active Chess Game", className="me-auto"),
                    html.Div([
                        dcc.Dropdown(
                            id='game-selector',
                            placeholder="Select a game...",
                            style={
                                'width': '500px',  # Increased width
                                'min-width': '300px',  # Minimum width
                                'white-space': 'normal',  # Allow text to wrap
                                'text-overflow': 'ellipsis'  # Add ellipsis for overflow
                            }
                        )
                    ], style={'min-width': '500px'})  # Container div width
                ], className="d-flex justify-content-between align-items-center"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Div(id="board-container", style={'width': '400px', 'height': '400px', 'position': 'relative'}),
                            html.Div(id="board-placeholder", children=[
                                html.Div("Chess board will appear here", 
                                         className="text-center text-muted p-5 border", 
                                         style={'height': '400px', 'display': 'flex', 'justifyContent': 'center', 'alignItems': 'center'})
                            ]),
                            html.Div([
                                html.Div(id="white-player", className="mt-2"),
                                html.Div(id="black-player", className="mt-1")
                            ])
                        ], width=6),
                        dbc.Col([
                            html.H5("Move History"),
                            html.Div(id="move-history", className="border p-2", style={'height': '400px', 'overflowY': 'auto'})
                        ], width=6)
                    ])
                ])
            ], className="mb-4")
        ], width=12)
    ])
], fluid=True)

# Callback for updating games count
@callback(
    [Output("games-count", "children"),
     Output("active-games", "children")],
    [Input("interval-component", "n_intervals")]
)
def update_games_count(n):
    total_games, active_games_count = get_games_count()
    return f"{total_games:,}", f"{active_games_count:,}"

# Callback for updating data ingestion rate
@callback(
    Output("data-rate", "children"),
    [Input("interval-component", "n_intervals")]
)
def update_data_rate(n):
    events_last_minute = get_events_last_minute()
    return f"{events_last_minute}"

# Callback for updating latest event
@callback(
    Output("latest-event", "children"),
    [Input("interval-component", "n_intervals")]
)
def update_latest_event(n):
    latest_event = get_latest_event()
    
    if latest_event:
        measurement = latest_event.measurement or "unknown"
        event_display = ""
        
        # Process based on measurement type
        if measurement == "chess_game" and latest_event.data and isinstance(latest_event.data, dict):
            # Chess game events
            tags = latest_event.data.get('tags', {})
            if isinstance(tags, dict):
                game_id = tags.get('game_id', 'unknown')
                event_type = tags.get('event_type', 'unknown')
                event_display = f"{measurement} - {event_type} - Game: {game_id}"
            else:
                event_display = f"{measurement} - incomplete data"
        
        elif measurement.startswith("metric_") and latest_event.data and isinstance(latest_event.data, dict):
            # System metrics
            tags = latest_event.data.get('tags', {})
            fields = latest_event.data.get('fields', {})
            if isinstance(tags, dict) and isinstance(fields, dict):
                origin = tags.get('origin', 'unknown')
                field_names = list(fields.keys())
                field_names_display = ", ".join(field_names[:3])
                if len(field_names) > 3:
                    field_names_display += f" (and {len(field_names) - 3} more)"
                event_display = f"{measurement} - {origin} - Fields: {field_names_display}"
            else:
                event_display = f"{measurement} - incomplete data"
                
        else:
            # Other types
            event_display = f"{measurement} - Generic Event"
            
        event_time = latest_event.received_timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return f"{event_time} - {event_display}"
    
    return "No events recorded yet"

# Callback for updating ingestion graph
@callback(
    Output("ingestion-graph", "figure"),
    [Input("interval-component", "n_intervals")]
)
def update_ingestion_graph(n):
    session = Session()
    try:
        # Get data from the last hour
        one_hour_ago = datetime.now() - timedelta(hours=1)
        
        # SQL query to get data counts per minute
        query = text("""
            SELECT 
                strftime('%Y-%m-%d %H:%M:00', received_timestamp) as minute,
                COUNT(*) as count
            FROM 
                raw_data
            WHERE 
                received_timestamp > :one_hour_ago
            GROUP BY 
                minute
            ORDER BY 
                minute
        """)
        
        result = session.execute(query, {"one_hour_ago": one_hour_ago})
        data = [{"minute": row[0], "count": row[1]} for row in result]
        
        if not data:
            # Create empty figure with message
            fig = go.Figure()
            fig.add_annotation(
                text="No data available for the last hour",
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False,
                font=dict(size=20)
            )
            return fig
        
        df = pd.DataFrame(data)
        df['minute'] = pd.to_datetime(df['minute'])
        
        fig = px.line(
            df, 
            x='minute', 
            y='count',
            title="Events Per Minute (Last Hour)",
            labels={"minute": "Time", "count": "Event Count"}
        )
        
        fig.update_layout(
            xaxis=dict(tickformat='%H:%M'),
            yaxis=dict(rangemode='nonnegative'),
            hovermode='x unified'
        )
        
        return fig
    finally:
        session.close()

# Callback for updating events distribution
@callback(
    Output("events-distribution", "figure"),
    [Input("interval-component", "n_intervals")]
)
def update_events_distribution(n):
    session = Session()
    try:
        # Get event types distribution from the last hour
        one_hour_ago = datetime.now() - timedelta(hours=1)
        
        query = text("""
            SELECT 
                json_extract(data, '$.tags.event_type') as event_type,
                COUNT(*) as count
            FROM 
                raw_data
            WHERE 
                received_timestamp > :one_hour_ago
                AND json_extract(data, '$.measurement') = 'chess_game'
            GROUP BY 
                event_type
            ORDER BY 
                count DESC
        """)
        
        result = session.execute(query, {"one_hour_ago": one_hour_ago})
        data = [{"event_type": row[0] or "unknown", "count": row[1]} for row in result]
        
        if not data:
            # Create empty figure with message
            fig = go.Figure()
            fig.add_annotation(
                text="No chess game events in the last hour",
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False,
                font=dict(size=20)
            )
            return fig
        
        df = pd.DataFrame(data)
        
        fig = px.pie(
            df, 
            values='count', 
            names='event_type',
            title="Chess Game Event Types (Last Hour)",
            hole=0.3
        )
        
        fig.update_traces(textposition='inside', textinfo='percent+label')
        
        return fig
    finally:
        session.close()

# Callback for updating recent games table
@callback(
    Output("recent-games-table", "children"),
    [Input("interval-component", "n_intervals")]
)
def update_recent_games(n):
    recent_games = get_recent_games(limit=5)
    
    if not recent_games:
        return html.Div("No games recorded yet", className="text-center text-muted")
    
    # Create table
    table_header = [
        html.Thead(html.Tr([
            html.Th("Game ID"),
            html.Th("White"),
            html.Th("Black"),
            html.Th("Started"),
            html.Th("Moves")
        ]))
    ]
    
    rows = []
    for game in recent_games:
        # Format time
        time_diff = datetime.now() - game['start_time']
        if time_diff.days > 0:
            time_str = f"{time_diff.days}d ago"
        elif time_diff.seconds > 3600:
            time_str = f"{time_diff.seconds // 3600}h ago"
        else:
            time_str = f"{time_diff.seconds // 60}m ago"
        
        # Get player names and move count
        white_name = game['white_player_name']
        black_name = game['black_player_name']
        move_count = game['move_count']
        
        rows.append(html.Tr([
            html.Td(game['game_id']),
            html.Td(white_name),
            html.Td(black_name),
            html.Td(time_str),
            html.Td(move_count)
        ]))
    
    table_body = [html.Tbody(rows)]
    
    return dbc.Table(
        table_header + table_body,
        bordered=True,
        hover=True,
        responsive=True,
        striped=True,
        size="sm"
    )

# Callback for game selector dropdown
@callback(
    Output("game-selector", "options"),
    [Input("interval-component", "n_intervals")]
)
def update_game_selector(n):
    active_games = get_active_games()
    
    if not active_games:
        return []
    
    # Format options for dropdown
    options = []
    for game in active_games:
        # Get player names
        white_name = game['white_player_name']
        black_name = game['black_player_name']
        
        # Format the time difference
        time_diff = datetime.now() - game['last_move_time']
        if time_diff.seconds < 60:
            time_str = f"{time_diff.seconds}s ago"
        else:
            time_str = f"{time_diff.seconds // 60}m ago"
        
        options.append({
            "label": f"{white_name} vs {black_name} ({game['game_id']}) - {time_str}",
            "value": game['game_id']
        })
    
    return options

# Modified clientside callback to properly handle FEN data
clientside_callback(
    """
    function(fen, n_intervals) {
        if (!fen) {
            console.log("No FEN data provided, not updating board");
            return "No FEN data";
        }
        
        // For debugging
        console.log("Rendering chessboard with FEN:", fen);
        
        try {
            // Clear existing board first
            $('#board-container').empty();
            
            // Configure the board with piece theme
            var config = {
                position: fen,
                showNotation: true,
                pieceTheme: "https://chessboardjs.com/img/chesspieces/wikipedia/{piece}.png"
            };

            // Initialize the board with the config
            var board = Chessboard('board-container', config);
            
            // Make sure the board container is visible and placeholder is hidden
            $('#board-container').show();
            $('#board-placeholder').hide();
            
            // Resize the board to fit the container
            $(window).resize(function() {
                board.resize();
            });
            
            return "Board rendered successfully with FEN: " + fen.substring(0, 20) + "...";
        } catch(e) {
            console.error('Error setting up chessboard:', e);
            $('#board-placeholder').show();
            return "Error: " + e.message;
        }
    }
    """,
    Output('clientside-script-container', 'children'),
    [Input('current-fen', 'data'),
     Input('interval-component', 'n_intervals')]
)

# Callback for updating chess board and related information
@callback(
    [Output("current-fen", "data"),
     Output("game-moves", "data"),
     Output("white-player", "children"),
     Output("black-player", "children"),
     Output("move-history", "children"),
     Output("board-placeholder", "style"),
     Output("debug-fen", "data"),
     Output("debug-display", "children")],
    [Input("game-selector", "value"),
     Input("interval-component", "n_intervals")]
)
def update_chess_board(selected_game_id, n):
    debug_info = []  # List to collect debug info
    
    debug_info.append(f"Update triggered at: {datetime.now().isoformat()}")
    debug_info.append(f"Game ID: {selected_game_id}")
    debug_info.append(f"Interval: {n}")
    
    if not selected_game_id:
        logger.debug(f"No game selected, using DEFAULT_FEN: {DEFAULT_FEN}")
        debug_info.append(f"No game selected, using DEFAULT_FEN")
        return DEFAULT_FEN, [], "White: Select a game", "Black: Select a game", [], {'display': 'none'}, DEFAULT_FEN, "\n".join(debug_info)
    
    # Get game data using cached function
    game, moves = get_game_data(selected_game_id)
    
    if not game:
        logger.debug(f"Game {selected_game_id} not found, using DEFAULT_FEN")
        debug_info.append(f"Game {selected_game_id} not found, using DEFAULT_FEN")
        return DEFAULT_FEN, [], "White: Select a game", "Black: Select a game", [], {'display': 'none'}, DEFAULT_FEN, "\n".join(debug_info)
    
    debug_info.append(f"Found {len(moves)} moves for game {selected_game_id}")
    
    if not moves:
        logger.debug(f"No moves found for game {selected_game_id}, using DEFAULT_FEN")
        debug_info.append(f"No moves found, using DEFAULT_FEN")
        return DEFAULT_FEN, [], f"White: {game['white_player']['name'] if game['white_player']['name'] else 'Unknown'}", f"Black: {game['black_player']['name'] if game['black_player']['name'] else 'Unknown'}", [], {'display': 'none'}, DEFAULT_FEN, "\n".join(debug_info)
    
    # Get the latest FEN position or derive it from moves
    latest_move = moves[-1]
    debug_info.append(f"Latest move: {latest_move['last_move']}")
    
    # Check if the latest move has a valid FEN position
    if latest_move['fen_position'] and is_valid_fen(latest_move['fen_position']):
        current_fen = latest_move['fen_position']
        logger.debug(f"Using stored FEN for game {selected_game_id}: {current_fen}")
        debug_info.append(f"Using stored FEN: {current_fen}")
    else:
        logger.debug(f"Deriving FEN for game {selected_game_id} from {len(moves)} moves")
        debug_info.append(f"Stored FEN missing or invalid, deriving from {len(moves)} moves")
        # Output first few moves for debugging
        if len(moves) > 0:
            debug_info.append("Sample moves:")
            for i, move in enumerate(moves[:5]):
                debug_info.append(f"  {i}: {move['last_move']}")
            if len(moves) > 5:
                debug_info.append(f"  ... and {len(moves)-5} more")
        
        try:
            current_fen = derive_fen_from_moves(moves)
            logger.debug(f"Derived FEN: {current_fen}")
            debug_info.append(f"Derived FEN: {current_fen}")
        except Exception as e:
            logger.error(f"Error deriving FEN: {str(e)}")
            debug_info.append(f"ERROR: Could not derive FEN: {str(e)}")
            current_fen = DEFAULT_FEN
    
    # Format player info
    white_info = f"White: {game['white_player']['name'] if game['white_player']['name'] else 'Unknown'}"
    if game['white_player']['name'] and game['white_player']['title']:
        white_info = f"{game['white_player']['title']} {white_info}"
        
    black_info = f"Black: {game['black_player']['name'] if game['black_player']['name'] else 'Unknown'}"
    if game['black_player']['name'] and game['black_player']['title']:
        black_info = f"{game['black_player']['title']} {black_info}"
    
    # Create move history display
    move_history_items = []
    for i, move in enumerate(moves):
        if move['last_move']:
            move_num = (i // 2) + 1
            if i % 2 == 0:  # White's move
                move_item = html.Div([
                    html.Span(f"{move_num}. ", className="text-muted"),
                    html.Span(f"{move['last_move']}", className="font-weight-bold")
                ], className="d-inline-block me-2")
            else:  # Black's move
                move_item = html.Div([
                    html.Span(f"{move['last_move']} ", className="font-weight-bold")
                ], className="d-inline-block me-3")
            move_history_items.append(move_item)
    
    # Create rows of moves (pairs of white/black moves)
    move_rows = []
    for i in range(0, len(move_history_items), 2):
        row_items = [move_history_items[i]]
        if i + 1 < len(move_history_items):
            row_items.append(move_history_items[i + 1])
        move_rows.append(html.Div(row_items, className="mb-1"))
    
    # Extract move notations for chess.js
    move_notations = [m['last_move'] for m in moves if m['last_move']]
    
    # Final check to make sure we're not sending an empty FEN
    if not current_fen or not is_valid_fen(current_fen):
        logger.warning(f"Invalid FEN detected in final output for game {selected_game_id}, using DEFAULT_FEN")
        debug_info.append(f"WARNING: Invalid derived FEN, falling back to DEFAULT_FEN")
        current_fen = DEFAULT_FEN
    
    debug_info.append(f"FINAL FEN being sent to client: {current_fen}")
    
    return current_fen, move_notations, white_info, black_info, move_rows, {'display': 'none'}, current_fen, "\n".join(debug_info)

# Add callback for current system metrics
@callback(
    [Output("current-cpu", "children"),
     Output("current-memory", "children"),
     Output("current-processes", "children"),
     Output("current-white-pieces", "children"),
     Output("current-black-pieces", "children")],
    [Input("interval-component", "n_intervals")]
)
def update_current_system_metrics(n):
    latest_cpu, latest_memory, latest_processes, latest_white_pieces, latest_black_pieces = get_system_metrics()
    
    # Format CPU usage
    if latest_cpu and latest_cpu.value is not None:
        cpu_text = f"{latest_cpu.value:.1f}%"
    else:
        cpu_text = "N/A"
    
    # Format memory usage
    if latest_memory and latest_memory.value is not None:
        memory_text = f"{latest_memory.value:.1f}%"
    else:
        memory_text = "N/A"
    
    # Format process count
    if latest_processes and latest_processes.value is not None:
        processes_text = f"{int(latest_processes.value)}"
    else:
        processes_text = "N/A"
    
    # Format chess piece counts
    if latest_white_pieces is not None:
        white_pieces_text = f"{latest_white_pieces:.1f}"
    else:
        white_pieces_text = "N/A"
        
    if latest_black_pieces is not None:
        black_pieces_text = f"{latest_black_pieces:.1f}"
    else:
        black_pieces_text = "N/A"
    
    return cpu_text, memory_text, processes_text, white_pieces_text, black_pieces_text

# Add callback for CPU usage graph
@callback(
    Output("cpu-usage-graph", "figure"),
    [Input("interval-component", "n_intervals")]
)
def update_cpu_usage_graph(n):
    session = Session()
    try:
        # Get CPU usage data for the last hour
        one_hour_ago = datetime.now() - timedelta(hours=1)
        cpu_metrics = session.query(
            Metric.timestamp, 
            Metric.value, 
            MetricOrigin.name.label('origin')
        ).join(MetricType).join(MetricOrigin)\
            .filter(MetricType.name == 'cpu_percent')\
            .filter(Metric.timestamp > one_hour_ago)\
            .order_by(Metric.timestamp).all()
        
        if not cpu_metrics:
            # Return empty figure if no data
            return go.Figure().update_layout(
                title="No CPU usage data available",
                xaxis_title="Time",
                yaxis_title="CPU Usage (%)"
            )
        
        # Create dataframe from metrics
        data = []
        for metric in cpu_metrics:
            data.append({
                'timestamp': metric.timestamp,
                'cpu_percent': metric.value,
                'origin': metric.origin
            })
        
        df = pd.DataFrame(data)
        
        # Create the figure with color differentiation by origin (hostname)
        fig = px.line(df, x='timestamp', y='cpu_percent', color='origin',
                      title="CPU Usage Over Time")
        fig.update_layout(
            xaxis_title="Time",
            yaxis_title="CPU Usage (%)",
            yaxis=dict(range=[0, 100])
        )
        return fig
    except Exception as e:
        logger.exception(f"Error updating CPU usage graph: {str(e)}")
        return go.Figure().update_layout(
            title=f"Error: {str(e)}",
            xaxis_title="Time",
            yaxis_title="CPU Usage (%)"
        )
    finally:
        session.close()

# Add callback for Memory usage graph
@callback(
    Output("memory-usage-graph", "figure"),
    [Input("interval-component", "n_intervals")]
)
def update_memory_usage_graph(n):
    session = Session()
    try:
        # Get memory usage data for the last hour
        one_hour_ago = datetime.now() - timedelta(hours=1)
        memory_metrics = session.query(
            Metric.timestamp, 
            Metric.value, 
            MetricOrigin.name.label('origin')
        ).join(MetricType).join(MetricOrigin)\
            .filter(MetricType.name == 'memory_percent')\
            .filter(Metric.timestamp > one_hour_ago)\
            .order_by(Metric.timestamp).all()
        
        if not memory_metrics:
            # Return empty figure if no data
            return go.Figure().update_layout(
                title="No memory usage data available",
                xaxis_title="Time",
                yaxis_title="Memory Usage (%)"
            )
        
        # Create dataframe from metrics
        data = []
        for metric in memory_metrics:
            data.append({
                'timestamp': metric.timestamp,
                'memory_percent': metric.value,
                'origin': metric.origin
            })
        
        df = pd.DataFrame(data)
        
        # Create the figure with color differentiation by origin (hostname)
        fig = px.line(df, x='timestamp', y='memory_percent', color='origin',
                      title="Memory Usage Over Time")
        fig.update_layout(
            xaxis_title="Time",
            yaxis_title="Memory Usage (%)",
            yaxis=dict(range=[0, 100])
        )
        return fig
    except Exception as e:
        logger.exception(f"Error updating memory usage graph: {str(e)}")
        return go.Figure().update_layout(
            title=f"Error: {str(e)}",
            xaxis_title="Time",
            yaxis_title="Memory Usage (%)"
        )
    finally:
        session.close()

# Add callback for Network traffic graph
@callback(
    Output("network-traffic-graph", "figure"),
    [Input("interval-component", "n_intervals")]
)
def update_network_traffic_graph(n):
    session = Session()
    try:
        # Get network traffic data for the last hour
        one_hour_ago = datetime.now() - timedelta(hours=1)
        
        # Get network metrics - using the exact metric_type from the logs
        network_metrics = session.query(
            Metric.timestamp, 
            Metric.value, 
            MetricOrigin.name.label('origin'),
            MetricType.name.label('metric_type')
        ).join(MetricType).join(MetricOrigin)\
            .filter(MetricType.name.in_(['network_bytes_sent', 'network_bytes_recv']))\
            .filter(Metric.timestamp > one_hour_ago)\
            .order_by(Metric.timestamp).all()
        
        if not network_metrics:
            # Return empty figure if no data
            return go.Figure().update_layout(
                title="No network traffic data available",
                xaxis_title="Time",
                yaxis_title="Network Traffic (bytes)"
            )
        
        # Create dataframe
        data = []
        for metric in network_metrics:
            data.append({
                'timestamp': metric.timestamp,
                'value': metric.value,
                'origin': metric.origin,
                'metric_type': metric.metric_type
            })
        
        df = pd.DataFrame(data)
        
        # Create the figure with multiple traces
        fig = go.Figure()
        
        # Group by origin and metric_type
        for (origin, metric_type), group_df in df.groupby(['origin', 'metric_type']):
            name = f"{origin} - {metric_type.replace('network_bytes_', '')}"
            color = 'blue' if 'sent' in metric_type else 'green'
            
            fig.add_trace(go.Scatter(
                x=group_df['timestamp'],
                y=group_df['value'],
                mode='lines',
                name=name,
                line=dict(color=color if 'sent' in metric_type else None)
            ))
        
        # Format y-axis to show in MB
        fig.update_layout(
            title="Network Traffic Over Time",
            xaxis_title="Time",
            yaxis_title="Network Traffic (bytes)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(
                tickformat=".2s"  # Use SI prefix formatting (K, M, G, etc.)
            )
        )
        return fig
    except Exception as e:
        logger.exception(f"Error updating network traffic graph: {str(e)}")
        return go.Figure().update_layout(
            title=f"Error: {str(e)}",
            xaxis_title="Time",
            yaxis_title="Network Traffic (bytes)"
        )
    finally:
        session.close()

# Add callback for combined system metrics graph
@callback(
    Output("combined-metrics-graph", "figure"),
    [Input("interval-component", "n_intervals")]
)
def update_combined_metrics_graph(n):
    session = Session()
    try:
        # Get data for the last hour for multiple metrics
        one_hour_ago = datetime.now() - timedelta(hours=1)
        
        # Query for CPU, memory, and process count metrics
        metrics = session.query(
            Metric.timestamp, 
            MetricType.name.label('metric_type'), 
            Metric.value, 
            MetricOrigin.name.label('origin')
        ).join(MetricType).join(MetricOrigin)\
            .filter(MetricType.name.in_(['cpu_percent', 'memory_percent', 'process_count']))\
            .filter(Metric.timestamp > one_hour_ago)\
            .order_by(Metric.timestamp).all()
        
        if not metrics:
            # Return empty figure if no data
            return go.Figure().update_layout(
                title="No system metrics data available",
                xaxis_title="Time",
                yaxis_title="Value"
            )
        
        # Create dataframe from metrics
        data = []
        for metric in metrics:
            data.append({
                'timestamp': metric.timestamp,
                'metric_type': metric.metric_type,
                'value': metric.value,
                'origin': metric.origin
            })
        
        df = pd.DataFrame(data)
        
        # Create a figure with multiple y-axes
        fig = go.Figure()
        
        # Add CPU percent trace
        cpu_df = df[df['metric_type'] == 'cpu_percent']
        if not cpu_df.empty:
            for origin, group in cpu_df.groupby('origin'):
                fig.add_trace(go.Scatter(
                    x=group['timestamp'],
                    y=group['value'],
                    mode='lines',
                    name=f'CPU ({origin})',
                    line=dict(color='red')
                ))
        
        # Add memory percent trace
        memory_df = df[df['metric_type'] == 'memory_percent']
        if not memory_df.empty:
            for origin, group in memory_df.groupby('origin'):
                fig.add_trace(go.Scatter(
                    x=group['timestamp'],
                    y=group['value'],
                    mode='lines',
                    name=f'Memory ({origin})',
                    line=dict(color='blue')
                ))
        
        # Add process count trace with secondary y-axis
        process_df = df[df['metric_type'] == 'process_count']
        if not process_df.empty:
            for origin, group in process_df.groupby('origin'):
                fig.add_trace(go.Scatter(
                    x=group['timestamp'],
                    y=group['value'],
                    mode='lines',
                    name=f'Processes ({origin})',
                    line=dict(color='green'),
                    yaxis='y2'
                ))
        
        # Update layout with secondary y-axis
        fig.update_layout(
            title="Combined System Metrics",
            xaxis_title="Time",
            yaxis=dict(
                title="Percentage (%)",
                range=[0, 100]
            ),
            yaxis2=dict(
                title="Process Count",
                overlaying='y',
                side='right'
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        return fig
    except Exception as e:
        logger.exception(f"Error updating combined metrics graph: {str(e)}")
        return go.Figure().update_layout(
            title=f"Error: {str(e)}",
            xaxis_title="Time",
            yaxis_title="Value"
        )
    finally:
        session.close()

# Add callback for chess piece counts graph
@callback(
    Output("chess-pieces-graph", "figure"),
    [Input("interval-component", "n_intervals")]
)
def update_chess_pieces_graph(n):
    session = Session()
    try:
        # Get chess piece count data for the last hour
        one_hour_ago = datetime.now() - timedelta(hours=1)
        
        # Query for white_pieces and black_pieces metrics
        piece_metrics = session.query(
            Metric.timestamp, 
            MetricType.name.label('metric_type'), 
            Metric.value, 
            MetricOrigin.name.label('origin')
        ).join(MetricType).join(MetricOrigin)\
            .filter(MetricType.name.in_(['white_pieces', 'black_pieces']))\
            .filter(Metric.timestamp > one_hour_ago)\
            .order_by(Metric.timestamp).all()
        
        if not piece_metrics:
            # Return empty figure if no data
            return go.Figure().update_layout(
                title="No chess piece count data available",
                xaxis_title="Time",
                yaxis_title="Piece Count"
            )
        
        # Create dataframe from metrics
        data = []
        for metric in piece_metrics:
            data.append({
                'timestamp': metric.timestamp,
                'metric_type': metric.metric_type,
                'value': metric.value,
                'origin': metric.origin
            })
        
        df = pd.DataFrame(data)
        
        # Create the figure
        fig = go.Figure()
        
        # Add white pieces trace
        white_df = df[df['metric_type'] == 'white_pieces']
        if not white_df.empty:
            for origin, group in white_df.groupby('origin'):
                fig.add_trace(go.Scatter(
                    x=group['timestamp'],
                    y=group['value'],
                    mode='lines',
                    name=f'White Pieces ({origin})',
                    line=dict(color='blue')
                ))
        
        # Add black pieces trace
        black_df = df[df['metric_type'] == 'black_pieces']
        if not black_df.empty:
            for origin, group in black_df.groupby('origin'):
                fig.add_trace(go.Scatter(
                    x=group['timestamp'],
                    y=group['value'],
                    mode='lines',
                    name=f'Black Pieces ({origin})',
                    line=dict(color='black')
                ))
        
        # Update layout
        fig.update_layout(
            title="Chess Piece Counts Over Time",
            xaxis_title="Time",
            yaxis_title="Piece Count",
            yaxis=dict(range=[0, 16]),  # Maximum of 16 pieces per side in chess
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            )
        )
        
        return fig
    except Exception as e:
        logger.exception(f"Error updating chess pieces graph: {str(e)}")
        return go.Figure().update_layout(
            title=f"Error: {str(e)}",
            xaxis_title="Time",
            yaxis_title="Piece Count"
        )
    finally:
        session.close()

# Callback for sending message to clients
@callback(
    Output("send-message-button", "disabled"),
    [Input("send-message-button", "n_clicks")],
    [State("client-message", "value")]
)
def send_message_to_clients(n_clicks, message):
    if n_clicks is None or message is None or message.strip() == "":
        return False

    # Get current timestamp for the message
    timestamp = datetime.now().isoformat()
    
    # Create message payload
    payload = {
        "message": message,
        "timestamp": timestamp,
        "type": "dashboard_message"
    }
    
    # Send message to server API endpoint
    try:
        requests.post('http://localhost:5000/api/send_message', json=payload)
        logger.info(f"Sent dashboard message: {message}")
    except Exception as e:
        logger.error(f"Failed to send dashboard message: {e}")
    
    # Re-enable the button
    return False

# Callback for all metrics table
@callback(
    Output("all-metrics-table", "children"),
    [Input("interval-component", "n_intervals"),
     Input("metrics-origin-filter", "value"),
     Input("metrics-type-filter", "value"),
     Input("metrics-pagination", "active_page"),
     Input("metrics-page-size", "value"),
     Input("metrics-date-range", "start_date"),
     Input("metrics-date-range", "end_date"),
     Input("metrics-min-value", "value"),
     Input("metrics-max-value", "value"),
     Input("metrics-exact-value", "value"),
     Input("metrics-value-tolerance", "value")]
)
def update_all_metrics(n, origin_filter, type_filter, page, page_size, start_date, end_date, min_value, max_value, exact_value, tolerance):
    if page_size is None:
        page_size = 25
    if page is None:
        page = 1
        
    session = Session()
    try:
        # Build query with filters
        query = session.query(
            Metric.id,
            MetricOrigin.name.label('origin'),
            MetricType.name.label('metric_type'),
            Metric.value,
            Metric.timestamp,
            TimeZoneSource.name.label('timezone')
        ).join(MetricOrigin).join(MetricType).outerjoin(TimeZoneSource)
        
        if origin_filter:
            query = query.filter(MetricOrigin.name == origin_filter)
        if type_filter:
            query = query.filter(MetricType.name == type_filter)
        
        # Apply date range filter if provided
        if start_date:
            start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Metric.timestamp >= start_datetime)
        if end_date:
            # Add one day to include the end date fully
            end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Metric.timestamp < end_datetime)
            
        # Apply value range filters if provided
        if min_value is not None:
            query = query.filter(Metric.value >= min_value)
        if max_value is not None:
            query = query.filter(Metric.value <= max_value)
        
        # Apply exact value filter with optional tolerance
        if exact_value is not None:
            if tolerance is not None and tolerance > 0:
                # Use between for tolerance range
                query = query.filter(Metric.value.between(exact_value - tolerance, exact_value + tolerance))
            else:
                # Use exact match
                query = query.filter(Metric.value == exact_value)
            
        # Get total count for pagination
        total_count = query.count()
        
        # Calculate offset for pagination
        offset = (page - 1) * page_size
        
        # Get the metrics with pagination
        metrics = query.order_by(desc(Metric.timestamp))\
            .offset(offset).limit(page_size).all()
        
        if not metrics:
            return html.Div("No metrics found with the current filters", className="text-center text-muted")
        
        # Create table
        table_header = [
            html.Thead(html.Tr([
                html.Th("ID"),
                html.Th("Origin"),
                html.Th("Metric Type"),
                html.Th("Value"),
                html.Th("Timestamp"),
                html.Th("Timezone")
            ]))
        ]
        
        rows = []
        for metric in metrics:
            # Format timestamp
            timestamp_str = metric.timestamp.strftime("%Y-%m-%d %H:%M:%S") if metric.timestamp else "N/A"
            
            # Format value with 2 decimal places if it's a float
            value_str = f"{metric.value:.2f}" if isinstance(metric.value, float) else str(metric.value)
            
            rows.append(html.Tr([
                html.Td(metric.id),
                html.Td(metric.origin),
                html.Td(metric.metric_type),
                html.Td(value_str),
                html.Td(timestamp_str),
                html.Td(metric.timezone or "UTC")
            ]))
        
        table_body = [html.Tbody(rows)]
        
        return dbc.Table(
            table_header + table_body,
            bordered=True,
            hover=True,
            responsive=True,
            striped=True,
            size="sm"
        )
    finally:
        session.close()

# Callback to update pagination max value
@callback(
    Output("metrics-pagination", "max_value"),
    [Input("interval-component", "n_intervals"),
     Input("metrics-origin-filter", "value"),
     Input("metrics-type-filter", "value"),
     Input("metrics-page-size", "value"),
     Input("metrics-date-range", "start_date"),
     Input("metrics-date-range", "end_date"),
     Input("metrics-min-value", "value"),
     Input("metrics-max-value", "value"),
     Input("metrics-exact-value", "value"),
     Input("metrics-value-tolerance", "value")]
)
def update_pagination(n, origin_filter, type_filter, page_size, start_date, end_date, min_value, max_value, exact_value, tolerance):
    if page_size is None:
        page_size = 25
        
    session = Session()
    try:
        # Build query with filters
        query = session.query(Metric)
        
        if origin_filter:
            query = query.filter(Metric.origin == origin_filter)
        if type_filter:
            query = query.filter(Metric.metric_type == type_filter)
            
        # Apply date range filter if provided
        if start_date:
            start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Metric.timestamp >= start_datetime)
        if end_date:
            # Add one day to include the end date fully
            end_datetime = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Metric.timestamp < end_datetime)
            
        # Apply value range filters if provided
        if min_value is not None:
            query = query.filter(Metric.value >= min_value)
        if max_value is not None:
            query = query.filter(Metric.value <= max_value)
            
        # Apply exact value filter with optional tolerance
        if exact_value is not None:
            if tolerance is not None and tolerance > 0:
                # Use between for tolerance range
                query = query.filter(Metric.value.between(exact_value - tolerance, exact_value + tolerance))
            else:
                # Use exact match
                query = query.filter(Metric.value == exact_value)
            
        # Get total count for pagination
        total_count = query.count()
        
        # Calculate max pages
        max_pages = (total_count + page_size - 1) // page_size
        
        # Ensure at least 1 page
        return max(1, max_pages)
    finally:
        session.close()

# Callback to populate origin filter dropdown
@callback(
    Output("metrics-origin-filter", "options"),
    [Input("interval-component", "n_intervals")]
)
def update_origin_filter(n):
    session = Session()
    try:
        # Get distinct origins
        origins = session.query(MetricOrigin.name).distinct().all()
        
        # Format for dropdown
        options = [{"label": origin[0], "value": origin[0]} for origin in origins]
        return options
    finally:
        session.close()

# Callback to populate metric type filter dropdown
@callback(
    Output("metrics-type-filter", "options"),
    [Input("interval-component", "n_intervals"),
     Input("metrics-origin-filter", "value")]
)
def update_metric_type_filter(n, origin_filter):
    session = Session()
    try:
        # Build query
        query = session.query(MetricType.name).distinct()
        
        # Apply origin filter if selected
        if origin_filter:
            query = (query.join(Metric).join(MetricOrigin)
                    .filter(MetricOrigin.name == origin_filter))
            
        # Get distinct metric types
        metric_types = query.all()
        
        # Format for dropdown
        options = [{"label": metric_type[0], "value": metric_type[0]} for metric_type in metric_types]
        return options
    except Exception as e:
        logger.error(f"Error updating metric type filter: {str(e)}")
        return []
    finally:
        session.close()

# Callback to reset filters
@callback(
    [Output("metrics-origin-filter", "value"),
     Output("metrics-type-filter", "value"),
     Output("metrics-pagination", "active_page"),
     Output("metrics-date-range", "start_date"),
     Output("metrics-date-range", "end_date"),
     Output("metrics-min-value", "value"),
     Output("metrics-max-value", "value"),
     Output("metrics-exact-value", "value"),
     Output("metrics-value-tolerance", "value")],
    [Input("reset-metrics-filters", "n_clicks")]
)
def reset_filters(n_clicks):
    """Reset all metric filters to default values."""
    # Reset all filters and go back to page 1
    return None, None, 1, None, None, None, None, None, None

# Callback to reset pagination when Apply Filters is clicked
@callback(
    Output("metrics-pagination", "active_page", allow_duplicate=True),
    [Input("apply-metrics-filters", "n_clicks")],
    prevent_initial_call=True
)
def reset_pagination_on_filter(n_clicks):
    # Reset to page 1 when filters are applied
    return 1

# Function to get the Dash server
def get_dash_app(cache=None):
    """Return the Dash application instance."""
    if cache is not None:
        init_cache(cache)
        logger.info("Cache initialized in dashboard")
    return dash_app

# Data retrieval functions that can be cached
@cached_query(timeout=30)
def get_active_games():
    """Get list of active games with recent moves."""
    session = Session()
    try:
        ten_min_ago = datetime.now() - timedelta(minutes=10)
        
        # Get game_id and player info for games with recent moves
        active_games = session.query(
            Game.game_id,
            Game.white_player_id,
            Game.black_player_id,
            func.max(Move.timestamp).label('last_move_time')
        ).join(Move, Game.game_id == Move.game_id) \
         .filter(Move.timestamp > ten_min_ago) \
         .group_by(Game.game_id, Game.white_player_id, Game.black_player_id) \
         .order_by(desc('last_move_time')) \
         .all()
        
        # Get all relevant player data in a single query
        player_ids = []
        for _, white_id, black_id, _ in active_games:
            if white_id:
                player_ids.append(white_id)
            if black_id:
                player_ids.append(black_id)
        
        players = {}
        if player_ids:
            player_records = session.query(Player).filter(Player.id.in_(player_ids)).all()
            for player in player_records:
                players[player.id] = player.name
        
        # Create a list of dictionaries with all needed data
        result = []
        for game_id, white_id, black_id, last_move_time in active_games:
            result.append({
                'game_id': game_id,
                'white_player_name': players.get(white_id, "Unknown") if white_id else "Unknown",
                'black_player_name': players.get(black_id, "Unknown") if black_id else "Unknown",
                'last_move_time': last_move_time
            })
        
        return result
    finally:
        session.close()

@cached_query(timeout=15)
def get_games_count():
    """Get count of total and active games."""
    session = Session()
    try:
        # Total games count
        total_games = session.query(func.count(Game.id)).scalar()
        
        # Active games (with moves in last 10 minutes)
        ten_min_ago = datetime.now() - timedelta(minutes=10)
        active_games_count = session.query(
            func.count(func.distinct(Move.game_id))
        ).filter(Move.timestamp > ten_min_ago).scalar()
        
        return total_games, active_games_count
    finally:
        session.close()

@cached_query(timeout=15)
def get_events_last_minute():
    """Get count of events in the last minute."""
    session = Session()
    try:
        one_min_ago = datetime.now() - timedelta(minutes=1)
        events_last_minute = session.query(func.count(RawData.id)) \
            .filter(RawData.received_timestamp > one_min_ago).scalar()
        return events_last_minute
    finally:
        session.close()

@cached_query(timeout=10)
def get_latest_event():
    """Get the latest event received."""
    session = Session()
    try:
        latest_event = session.query(RawData) \
            .order_by(desc(RawData.received_timestamp)).first()
        return latest_event
    finally:
        session.close()

@cached_query(timeout=60)
def get_game_data(game_id):
    """Get game and move data for a specific game."""
    if not game_id:
        return None, []
        
    session = Session()
    try:
        # Get game info with eager loading of relationships
        game = session.query(Game) \
            .options(joinedload(Game.white_player), joinedload(Game.black_player)) \
            .filter(Game.game_id == game_id).first()
            
        if not game:
            return None, []
            
        # Create a dictionary from the game data to avoid detached objects
        game_data = {
            'game_id': game.game_id,
            'white_player': {
                'name': game.white_player.name if game.white_player else None,
                'title': game.white_player.title if game.white_player and hasattr(game.white_player, 'title') else None
            },
            'black_player': {
                'name': game.black_player.name if game.black_player else None,
                'title': game.black_player.title if game.black_player and hasattr(game.black_player, 'title') else None
            }
        }
            
        # Get moves for this game, ordered by timestamp
        moves = session.query(Move).filter(Move.game_id == game_id) \
            .order_by(Move.timestamp).all()
            
        # Convert move objects to dictionaries
        move_data = []
        for move in moves:
            move_data.append({
                'last_move': move.last_move,
                'fen_position': move.fen_position,
                'timestamp': move.timestamp,
                'white_time': move.white_time,
                'black_time': move.black_time,
                'white_piece_count': move.white_piece_count,
                'black_piece_count': move.black_piece_count
            })
            
        return game_data, move_data
    finally:
        session.close()

@cached_query(timeout=30)
def get_recent_games(limit=5):
    """Get the most recent games."""
    session = Session()
    try:
        # Get 5 most recent games with player names, eagerly loading relationships
        recent_games = session.query(Game) \
            .options(joinedload(Game.white_player), joinedload(Game.black_player)) \
            .order_by(desc(Game.start_time)) \
            .limit(limit).all()
            
        # Also preload move counts to avoid additional queries
        game_ids = [game.game_id for game in recent_games]
        move_counts = {}
        if game_ids:
            move_count_results = session.query(
                Move.game_id, 
                func.count(Move.id).label('move_count')
            ).filter(Move.game_id.in_(game_ids)) \
             .group_by(Move.game_id).all()
            
            for game_id, count in move_count_results:
                move_counts[game_id] = count
                
        # Create a clean dictionary of data to cache instead of ORM objects
        result = []
        for game in recent_games:
            result.append({
                'game_id': game.game_id,
                'white_player_name': game.white_player.name if game.white_player else "Unknown",
                'black_player_name': game.black_player.name if game.black_player else "Unknown",
                'start_time': game.start_time,
                'move_count': move_counts.get(game.game_id, 0)
            })
        
        return result
    finally:
        session.close()

@cached_query(timeout=30)
def get_system_metrics():
    """Get current system metrics."""
    session = Session()
    try:
        # Get latest CPU usage
        latest_cpu = session.query(Metric) \
            .join(MetricType, Metric.metric_type_id == MetricType.id) \
            .filter(MetricType.name == 'cpu_percent') \
            .order_by(desc(Metric.timestamp)) \
            .first()
        
        # Get latest memory usage
        latest_memory = session.query(Metric) \
            .join(MetricType, Metric.metric_type_id == MetricType.id) \
            .filter(MetricType.name == 'memory_percent') \
            .order_by(desc(Metric.timestamp)) \
            .first()
        
        # Get process count
        latest_processes = session.query(Metric) \
            .join(MetricType, Metric.metric_type_id == MetricType.id) \
            .filter(MetricType.name == 'process_count') \
            .order_by(desc(Metric.timestamp)) \
            .first()
            
        # Get chess pieces stats
        latest_white_pieces = session.query(func.avg(Move.white_piece_count)) \
            .filter(Move.timestamp > (datetime.now() - timedelta(minutes=10))) \
            .scalar()
            
        latest_black_pieces = session.query(func.avg(Move.black_piece_count)) \
            .filter(Move.timestamp > (datetime.now() - timedelta(minutes=10))) \
            .scalar()
            
        return latest_cpu, latest_memory, latest_processes, latest_white_pieces, latest_black_pieces
    finally:
        session.close()
