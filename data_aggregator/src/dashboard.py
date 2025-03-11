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
    dcc.Store(id="is-loaded", data=False),
    html.Div(id="clientside-script-container", style={"display": "none"}),
    
    # Store for debug info
    dcc.Store(id="debug-fen", data=DEFAULT_FEN),
    
    # Invisible intervals for triggering callbacks
    html.Div([
        dcc.Interval(id="critical-interval", interval=15000),  # Changed to 15 seconds
        dcc.Interval(id="standard-interval", interval=15000),  # 15 seconds for standard updates
        dcc.Interval(id="slow-interval", interval=15000),      # Changed to 15 seconds
        dcc.Interval(id="graph-interval", interval=15000),     # Changed to 15 seconds
        # Store intermediate data
    ]),
    
    # Dashboard header
    dbc.Row([
        dbc.Col([
            html.H1("Chess Data Dashboard", className="text-center mb-4")
        ])
    ]),
    
    # Stats row
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Total Games", className="text-center"),
                dbc.CardBody([
                    html.H3(id="games-count", className="text-center")
                ])
            ])
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Active Games", className="text-center"),
                dbc.CardBody([
                    html.H3(id="active-games", className="text-center")
                ])
            ])
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Events/Minute", className="text-center"),
                dbc.CardBody([
                    html.H3(id="data-rate", className="text-center")
                ])
            ])
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Latest Event", className="text-center"),
                dbc.CardBody([
                    html.P(id="latest-event", className="text-center")
                ])
            ])
        ], width=3)
    ], className="mb-4"),
    
    # System metrics
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("System Metrics", className="text-center"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Div("CPU Usage: ", className="fw-bold"),
                            html.Span(id="current-cpu")
                        ], width=4),
                        dbc.Col([
                            html.Div("Memory Usage: ", className="fw-bold"),
                            html.Span(id="current-memory")
                        ], width=4),
                        dbc.Col([
                            html.Div("Processes: ", className="fw-bold"),
                            html.Span(id="current-processes")
                        ], width=4)
                    ])
                ])
            ])
        ], width=8),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Latest Piece Counts", className="text-center"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Div("White Pieces: ", className="fw-bold"),
                            html.Span(id="latest-white-pieces")
                        ], width=6),
                        dbc.Col([
                            html.Div("Black Pieces: ", className="fw-bold"),
                            html.Span(id="latest-black-pieces")
                        ], width=6)
                    ]),
                    html.Div("Game ID: ", className="fw-bold mt-2"),
                    html.Small(id="latest-pieces-game-id", className="text-muted")
                ])
            ])
        ], width=4)
    ], className="mb-4"),
    
    # System metrics graphs - Combined into one row for system metrics graphs
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("CPU Usage", className="text-center"),
                dbc.CardBody([
                    dcc.Graph(id="cpu-usage-graph", style={"height": "300px"})
                ])
            ])
        ], width=4),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Memory Usage", className="text-center"),
                dbc.CardBody([
                    dcc.Graph(id="memory-usage-graph", style={"height": "300px"})
                ])
            ])
        ], width=4),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Processes", className="text-center"),
                dbc.CardBody([
                    dcc.Graph(id="processes-graph", style={"height": "300px"})
                ])
            ])
        ], width=4)
    ], className="mb-4"),
    
    # Event graphs - Combined into one row
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Event Ingestion Rate", className="text-center"),
                dbc.CardBody([
                    dcc.Graph(id="ingestion-graph", style={"height": "300px"})
                ])
            ])
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Event Type Distribution", className="text-center"),
                dbc.CardBody([
                    dcc.Graph(id="events-distribution", style={"height": "300px"})
                ])
            ])
        ], width=6)
    ], className="mb-4"),
    
    # Additional metrics graphs - Combined into one row
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Combined System Metrics", className="text-center"),
                dbc.CardBody([
                    dcc.Graph(id="combined-metrics-graph", style={"height": "300px"})
                ])
            ])
        ], width=6),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Chess Piece Count", className="text-center"),
                dbc.CardBody([
                    dcc.Graph(id="chess-pieces-graph", style={"height": "300px"})
                ])
            ])
        ], width=6)
    ], className="mb-4"),
    
    # Chess board and recent games
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Chess Board", className="text-center"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            dcc.Dropdown(
                                id="game-selector",
                                placeholder="Select game to view"
                            )
                        ], width=12, className="mb-3")
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.H5(id="white-player"),
                            html.H5(id="black-player"),
                            html.Div(id="board-container", style={"height": "400px", "width": "400px"}),
                            # Placeholder for board when no game is selected
                            html.Div(id="board-placeholder", className="text-center p-5 border", 
                                    children=["Select a game to view the board"],
                                    style={"height": "400px", "width": "400px", "display": "block"})
                        ], width=6),
                        dbc.Col([
                            html.H5("Move History"),
                            html.Div(id="move-history", style={"max-height": "400px", "overflow-y": "auto"})
                        ], width=6)
                    ])
                ])
            ])
        ], width=8),
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Recent Games", className="text-center"),
                dbc.CardBody([
                    html.Div(id="recent-games-table")
                ])
            ], className="mb-4"),
            dbc.Card([
                dbc.CardHeader("Send Message to Clients", className="text-center"),
                dbc.CardBody([
                    dbc.Textarea(id="client-message", placeholder="Enter message to send to all clients", className="mb-2"),
                    dbc.Button("Send", id="send-message-button", color="primary", className="w-100")
                ])
            ])
        ], width=4)
    ], className="mb-4"),
    
    # Debug info
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Debug Info", className="text-center"),
                dbc.CardBody([
                    html.Pre(id="debug-display", style={"max-height": "200px", "overflow-y": "auto"})
                ])
            ])
        ])
    ], className="mb-4"),
    
    # Metrics table
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("All Metrics", className="text-center"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Origin:"),
                            dcc.Dropdown(id="metrics-origin-filter", multi=True)
                        ], width=3),
                        dbc.Col([
                            html.Label("Metric Type:"),
                            dcc.Dropdown(id="metrics-type-filter", multi=True)
                        ], width=3),
                        dbc.Col([
                            html.Label("Date Range:"),
                            dcc.DatePickerRange(id="metrics-date-range")
                        ], width=3),
                        dbc.Col([
                            html.Label("Page Size:"),
                            dcc.Dropdown(
                                id="metrics-page-size",
                                options=[
                                    {"label": "10", "value": 10},
                                    {"label": "25", "value": 25},
                                    {"label": "50", "value": 50},
                                    {"label": "100", "value": 100}
                                ],
                                value=25
                            )
                        ], width=3)
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Min Value:"),
                            dbc.Input(id="metrics-min-value", type="number")
                        ], width=2),
                        dbc.Col([
                            html.Label("Max Value:"),
                            dbc.Input(id="metrics-max-value", type="number")
                        ], width=2),
                        dbc.Col([
                            html.Label("Exact Value:"),
                            dbc.Input(id="metrics-exact-value", type="number")
                        ], width=2),
                        dbc.Col([
                            html.Label("Tolerance:"),
                            dbc.Input(id="metrics-value-tolerance", type="number", value=0.1)
                        ], width=2),
                        dbc.Col([
                            html.Div([
                                dbc.Button("Apply", id="apply-metrics-filters", color="primary", className="me-2"),
                                dbc.Button("Reset", id="reset-metrics-filters", color="secondary")
                            ], className="d-flex align-items-end h-100")
                        ], width=4)
                    ], className="mb-3"),
                    html.Div(id="all-metrics-table"),
                    dbc.Pagination(
                        id="metrics-pagination",
                        active_page=1,
                        max_value=1,
                        first_last=True,
                        previous_next=True,
                        max_visible=7
                    )
                ])
            ])
        ])
    ])
], fluid=True)

# Callback for updating games count
@callback(
    [Output("games-count", "children"),
     Output("active-games", "children")],
    [Input("critical-interval", "n_intervals")]
)
def update_games_count(n):
    total_games, active_games_count = get_games_count()
    return f"{total_games:,}", f"{active_games_count:,}"

# Callback for updating data ingestion rate
@callback(
    Output("data-rate", "children"),
    [Input("critical-interval", "n_intervals")]
)
def update_data_rate(n):
    events_last_minute = get_events_last_minute()
    return f"{events_last_minute}"

# Callback for updating latest event
@callback(
    Output("latest-event", "children"),
    [Input("critical-interval", "n_intervals")]
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
    [Output("ingestion-graph", "figure"),
     Output("events-distribution", "figure")],
    [Input("graph-interval", "n_intervals")]
)
def update_event_graphs(n):
    """Combine event-related graphs to reduce HTTP requests."""
    session = Session()
    try:
        # --- Ingestion Rate Graph ---
        # Get data for ingestion rate (last 5 minutes)
        five_min_ago = datetime.now() - timedelta(minutes=5)
        
        # Group by minute and count events
        event_counts = session.query(
            func.to_char(func.date_trunc('minute', RawData.received_timestamp), 'YYYY-MM-DD HH24:MI').label('minute'),
            func.count(RawData.id).label('count')
        ).filter(RawData.received_timestamp > five_min_ago) \
         .group_by('minute') \
         .order_by('minute') \
         .all()
        
        ingestion_fig = go.Figure()
        
        if event_counts:
            # Convert to dataframe
            df = pd.DataFrame([(datetime.strptime(ec.minute, '%Y-%m-%d %H:%M'), ec.count) 
                              for ec in event_counts], 
                              columns=['time', 'count'])
            
            # Create the figure
            ingestion_fig = px.bar(df, x='time', y='count',
                            title='Event Ingestion Rate (per minute)',
                            labels={'count': 'Events', 'time': 'Time'})
            
            ingestion_fig.update_layout(margin=dict(l=20, r=20, t=40, b=20))
        else:
            ingestion_fig.add_annotation(text="No event data available",
                                 xref="paper", yref="paper",
                                 x=0.5, y=0.5, showarrow=False)
            ingestion_fig.update_layout(title='Event Ingestion Rate')
        
        # --- Events Distribution Graph ---
        # Get distribution of event types (last 5 minutes)
        event_types = session.query(
            RawData.measurement,
            func.count(RawData.id).label('count')
        ).filter(RawData.received_timestamp > five_min_ago) \
         .filter(RawData.measurement.isnot(None)) \
         .group_by(RawData.measurement) \
         .order_by(desc('count')) \
         .all()
        
        distribution_fig = go.Figure()
        
        if event_types:
            # Convert to dataframe
            df = pd.DataFrame([(et.measurement, et.count) for et in event_types],
                             columns=['event_type', 'count'])
            
            # Limit to top 10 event types for readability
            if len(df) > 10:
                top_df = df.head(10)
                
                # Add an "Other" category for the rest
                other_count = df.iloc[10:]['count'].sum()
                if other_count > 0:
                    top_df = pd.concat([top_df, pd.DataFrame([{'event_type': 'Other', 'count': other_count}])])
                
                df = top_df
            
            # Create pie chart
            distribution_fig = px.pie(df, values='count', names='event_type',
                               title='Event Type Distribution',
                               hole=0.4)
            
            distribution_fig.update_layout(margin=dict(l=20, r=20, t=40, b=20))
        else:
            distribution_fig.add_annotation(text="No event data available",
                                    xref="paper", yref="paper",
                                    x=0.5, y=0.5, showarrow=False)
            distribution_fig.update_layout(title='Event Type Distribution')
        
        return ingestion_fig, distribution_fig
    except Exception as e:
        logger.exception(f"Error updating event graphs: {str(e)}")
        empty_fig = go.Figure()
        empty_fig.add_annotation(text="Error loading data",
                          xref="paper", yref="paper",
                          x=0.5, y=0.5, showarrow=False)
        return empty_fig, empty_fig
    finally:
        session.close()

# Callback for updating recent games table
@callback(
    Output("recent-games-table", "children"),
    [Input("standard-interval", "n_intervals")]
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
    [Input("critical-interval", "n_intervals")]
)
def update_game_selector(n):
    # Use the cached query but with more frequent updates
    active_games = get_active_games()
    
    if not active_games:
        return []
    
    # Format options for dropdown
    options = []
    for game in active_games:
        # Get player names
        white_name = game['white_player_name']
        black_name = game['black_player_name']
        
        # Convert last_move_time to naive datetime if it's timezone-aware
        last_move_time = game['last_move_time']
        if hasattr(last_move_time, 'tzinfo') and last_move_time.tzinfo is not None:
            last_move_time = last_move_time.replace(tzinfo=None)
        
        # Format the time difference
        time_diff = datetime.now() - last_move_time
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
     Input('critical-interval', 'n_intervals')]
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
     Input("critical-interval", "n_intervals")],
    prevent_initial_call=True
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
    
    # Use real-time function without caching for chess board updates
    game, moves = get_game_data_realtime(selected_game_id)
    
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
        logger.warning(f"Missing valid FEN for game {selected_game_id}, using DEFAULT_FEN")
        debug_info.append(f"Missing valid FEN, using DEFAULT_FEN")
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
     Output("cpu-usage-graph", "figure"),
     Output("memory-usage-graph", "figure"),
     Output("processes-graph", "figure")],
    [Input("standard-interval", "n_intervals")],
    prevent_initial_call=True
)
def update_system_metrics_combined(n):
    """Single callback for all system metrics to reduce HTTP requests."""
    # Get basic metrics
    latest_cpu, latest_memory, latest_processes, _, _ = get_system_metrics()
    
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
    
    # Generate CPU usage graph
    session = Session()
    try:
        # Query data for the CPU usage graph
        cpu_metrics = session.query(
            func.to_char(func.date_trunc('minute', Metric.timestamp), 'YYYY-MM-DD HH24:MI:00').label('minute'),
            func.avg(Metric.value).label('avg_value')
        ).join(MetricType, Metric.metric_type_id == MetricType.id) \
          .filter(MetricType.name == 'cpu_percent') \
          .filter(Metric.timestamp > (datetime.now() - timedelta(minutes=5))) \
          .group_by(func.date_trunc('minute', Metric.timestamp)) \
          .order_by(func.date_trunc('minute', Metric.timestamp)) \
          .all()
        
        # Extract data for plotting
        cpu_times = [datetime.strptime(m.minute, '%Y-%m-%d %H:%M:00') for m in cpu_metrics]
        cpu_values = [m.avg_value for m in cpu_metrics]
        
        # Create CPU figure
        cpu_fig = go.Figure()
        cpu_fig.add_trace(go.Scatter(
            x=cpu_times, 
            y=cpu_values,
            mode='lines+markers',
            name='CPU Usage',
            line=dict(color='red')
        ))
        cpu_fig.update_layout(
            title='CPU Usage (5 min)',
            xaxis_title='Time',
            yaxis_title='CPU %',
            margin=dict(l=20, r=20, t=40, b=20),
            height=250
        )
        
        # Query data for Memory usage graph
        memory_metrics = session.query(
            func.to_char(func.date_trunc('minute', Metric.timestamp), 'YYYY-MM-DD HH24:MI:00').label('minute'),
            func.avg(Metric.value).label('avg_value')
        ).join(MetricType, Metric.metric_type_id == MetricType.id) \
          .filter(MetricType.name == 'memory_percent') \
          .filter(Metric.timestamp > (datetime.now() - timedelta(minutes=5))) \
          .group_by(func.date_trunc('minute', Metric.timestamp)) \
          .order_by(func.date_trunc('minute', Metric.timestamp)) \
          .all()
        
        # Extract data for plotting
        memory_times = [datetime.strptime(m.minute, '%Y-%m-%d %H:%M:00') for m in memory_metrics]
        memory_values = [m.avg_value for m in memory_metrics]
        
        # Create Memory figure
        memory_fig = go.Figure()
        memory_fig.add_trace(go.Scatter(
            x=memory_times, 
            y=memory_values,
            mode='lines+markers',
            name='Memory Usage',
            line=dict(color='blue')
        ))
        memory_fig.update_layout(
            title='Memory Usage (5 min)',
            xaxis_title='Time',
            yaxis_title='Memory %',
            margin=dict(l=20, r=20, t=40, b=20),
            height=250
        )
        
        # Query data for Processes graph
        processes_metrics = session.query(
            func.to_char(func.date_trunc('minute', Metric.timestamp), 'YYYY-MM-DD HH24:MI:00').label('minute'),
            func.avg(Metric.value).label('avg_value')
        ).join(MetricType, Metric.metric_type_id == MetricType.id) \
          .filter(MetricType.name == 'process_count') \
          .filter(Metric.timestamp > (datetime.now() - timedelta(minutes=5))) \
          .group_by(func.date_trunc('minute', Metric.timestamp)) \
          .order_by(func.date_trunc('minute', Metric.timestamp)) \
          .all()
        
        # Extract data for plotting
        processes_times = [datetime.strptime(m.minute, '%Y-%m-%d %H:%M:00') for m in processes_metrics]
        processes_values = [m.avg_value for m in processes_metrics]
        
        # Create Processes figure
        processes_fig = go.Figure()
        processes_fig.add_trace(go.Scatter(
            x=processes_times, 
            y=processes_values,
            mode='lines+markers',
            name='Process Count',
            line=dict(color='purple')
        ))
        processes_fig.update_layout(
            title='Process Count (5 min)',
            xaxis_title='Time',
            yaxis_title='Number of Processes',
            margin=dict(l=20, r=20, t=40, b=20),
            height=250
        )
        
        return cpu_text, memory_text, processes_text, cpu_fig, memory_fig, processes_fig
    except Exception as e:
        logger.exception(f"Error updating system metrics: {str(e)}")
        empty_fig = go.Figure()
        empty_fig.add_annotation(text="Error loading data", 
                            xref="paper", yref="paper",
                            x=0.5, y=0.5, showarrow=False)
        return "Error", "Error", "Error", empty_fig, empty_fig, empty_fig
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
    [Input("standard-interval", "n_intervals"),
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
    [Input("standard-interval", "n_intervals"),
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
    [Input("standard-interval", "n_intervals")]
)
def update_origin_filter(n):
    session = Session()
    try:
        # Get distinct origins
        origins = session.query(MetricOrigin.name).distinct().all()
        
        # Format for dropdown
        options = [{"label": origin[0], "value": origin[0]} for origin in origins]
    finally:
        session.close()

# Callback to populate metric type filter dropdown
@callback(
    Output("metrics-type-filter", "options"),
    [Input("standard-interval", "n_intervals"),
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
    return None, None, 1, None, None, None, None

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
@cached_query(timeout=5)  # Reduced from 30 to 5 seconds
def get_active_games():
    """Get list of active games with recent moves."""
    session = Session()
    try:
        one_min_ago = datetime.now() - timedelta(seconds=15)
        
        # Get game_id and player info for games with recent moves
        active_games = session.query(
            Game.game_id,
            Game.white_player_id,
            Game.black_player_id,
            func.max(Move.timestamp).label('last_move_time')
        ).join(Move, Game.game_id == Move.game_id) \
         .filter(Move.timestamp > one_min_ago) \
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
        
        # Active games (with moves in last 15 seconds)
        one_min_ago = datetime.now() - timedelta(seconds=15)
        active_games_count = session.query(
            func.count(func.distinct(Move.game_id))
        ).filter(Move.timestamp > one_min_ago).scalar()
        
        return total_games, active_games_count
    finally:
        session.close()

@cached_query(timeout=15)
def get_events_last_minute():
    """Get count of events in the last minute."""
    session = Session()
    try:
        one_min_ago = datetime.now() - timedelta(seconds=15)
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

@cached_query(timeout=5)  # Reduce timeout from 60 to 5 seconds
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

def get_game_data_realtime(game_id):
    """Get game data without caching for real-time updates."""
    # This is a direct call to the function without caching
    return get_game_data.__wrapped__(game_id)

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
            .filter(Move.timestamp > (datetime.now() - timedelta(seconds=15))) \
            .scalar()
            
        latest_black_pieces = session.query(func.avg(Move.black_piece_count)) \
            .filter(Move.timestamp > (datetime.now() - timedelta(seconds=15))) \
            .scalar()
            
        return latest_cpu, latest_memory, latest_processes, latest_white_pieces, latest_black_pieces
    finally:
        session.close()

@cached_query(timeout=5)
def get_latest_piece_counts():
    """Get the latest piece counts from the most recent move."""
    session = Session()
    try:
        # Get latest move by timestamp
        latest_move = session.query(Move) \
            .order_by(desc(Move.timestamp)) \
            .first()
            
        if latest_move:
            return latest_move.white_piece_count, latest_move.black_piece_count, latest_move.game_id
        else:
            return None, None, None
    finally:
        session.close()

@dash_app.callback(
    Output("combined-metrics-graph", "figure"),
    [Input("slow-interval", "n_intervals")]
)
def update_combined_metrics(n):
    """Callback for less frequently updated system metrics graph."""
    session = Session()
    try:
        # Get data for the last 5 minutes
        five_min_ago = datetime.now() - timedelta(minutes=5)
        
        # --- Combined Metrics Graph ---
        # Query for CPU, memory, and process count metrics
        metrics = session.query(
            Metric.timestamp, 
            MetricType.name.label('metric_type'), 
            Metric.value
        ).join(MetricType)\
            .filter(MetricType.name.in_(['cpu_percent', 'memory_percent', 'process_count']))\
            .filter(Metric.timestamp > five_min_ago)\
            .order_by(Metric.timestamp).all()
        
        # Create dataframe
        data = []
        for metric in metrics:
            data.append({
                'timestamp': metric.timestamp,
                'metric_type': metric.metric_type,
                'value': metric.value
            })
        
        df = pd.DataFrame(data) if data else pd.DataFrame(columns=['timestamp', 'metric_type', 'value'])
        
        # Create combined metrics figure
        combined_fig = go.Figure()
        
        # Add CPU percent trace
        cpu_df = df[df['metric_type'] == 'cpu_percent']
        if not cpu_df.empty:
            combined_fig.add_trace(go.Scatter(
                x=cpu_df['timestamp'],
                y=cpu_df['value'],
                mode='lines',
                name='CPU',
                line=dict(color='red')
            ))
        
        # Add memory percent trace
        memory_df = df[df['metric_type'] == 'memory_percent']
        if not memory_df.empty:
            combined_fig.add_trace(go.Scatter(
                x=memory_df['timestamp'],
                y=memory_df['value'],
                mode='lines',
                name='Memory',
                line=dict(color='blue')
            ))
        
        # Add process count with secondary y-axis
        process_df = df[df['metric_type'] == 'process_count']
        if not process_df.empty:
            combined_fig.add_trace(go.Scatter(
                x=process_df['timestamp'],
                y=process_df['value'],
                mode='lines',
                name='Processes',
                line=dict(color='purple'),
                yaxis='y2'
            ))
        
        # Update layout
        combined_fig.update_layout(
            title="Combined System Metrics (5 min)",
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
            legend=dict(orientation="h", y=1.1),
            margin=dict(l=20, r=40, t=40, b=20)
        )
        
        return combined_fig
    except Exception as e:
        logger.exception(f"Error updating combined metrics graph: {str(e)}")
        empty_fig = go.Figure()
        empty_fig.add_annotation(text="Error loading data", 
                          xref="paper", yref="paper",
                          x=0.5, y=0.5, showarrow=False)
        return empty_fig
    finally:
        session.close()

@callback(
    Output("chess-pieces-graph", "figure"),
    [Input("game-selector", "value"),
     Input("critical-interval", "n_intervals")],
    prevent_initial_call=True
)
def update_chess_pieces_graph(selected_game_id, n):
    """Callback to update the chess pieces graph for the current selected game."""
    if not selected_game_id:
        # No game selected, show empty graph
        chess_fig = go.Figure()
        chess_fig.add_annotation(text="No game selected", 
                         xref="paper", yref="paper",
                         x=0.5, y=0.5, showarrow=False)
        chess_fig.update_layout(
            title="Current Game Piece Counts",
            xaxis_title="Move Number",
            yaxis_title="Piece Count",
            yaxis=dict(range=[0, 16]),
            margin=dict(l=20, r=20, t=40, b=20)
        )
        return chess_fig
    
    # Get game data for the selected game
    _, moves = get_game_data_realtime(selected_game_id)
    
    # Create chess pieces figure
    chess_fig = go.Figure()
    
    if moves:
        # Create lists for move numbers, white piece counts, and black piece counts
        move_numbers = list(range(1, len(moves) + 1))
        white_piece_counts = [move.get('white_piece_count', None) for move in moves]
        black_piece_counts = [move.get('black_piece_count', None) for move in moves]
        
        # Filter out None values
        valid_moves = [(n, w, b) for n, w, b in zip(move_numbers, white_piece_counts, black_piece_counts) 
                      if w is not None and b is not None]
        
        if valid_moves:
            move_numbers, white_piece_counts, black_piece_counts = zip(*valid_moves)
            
            # Add traces
            chess_fig.add_trace(go.Scatter(
                x=move_numbers,
                y=white_piece_counts,
                mode='lines+markers',
                name='White Pieces',
                line=dict(color='blue')
            ))
            
            chess_fig.add_trace(go.Scatter(
                x=move_numbers,
                y=black_piece_counts,
                mode='lines+markers',
                name='Black Pieces',
                line=dict(color='black')
            ))
            
            # Update layout
            chess_fig.update_layout(
                title="Current Game Piece Counts",
                xaxis_title="Move Number",
                yaxis_title="Piece Count",
                yaxis=dict(range=[0, 16]),
                legend=dict(orientation="h", y=1.1),
                margin=dict(l=20, r=20, t=40, b=20)
            )
        else:
            chess_fig.add_annotation(text="No piece count data available for this game", 
                            xref="paper", yref="paper",
                            x=0.5, y=0.5, showarrow=False)
            chess_fig.update_layout(title="Current Game Piece Counts")
    else:
        chess_fig.add_annotation(text="No moves data available for this game", 
                         xref="paper", yref="paper",
                         x=0.5, y=0.5, showarrow=False)
        chess_fig.update_layout(title="Current Game Piece Counts")
    
    return chess_fig

@callback(
    Output("is-loaded", "data"),
    [Input("critical-interval", "n_intervals")]
)
def update_is_loaded(n):
    """Update is-loaded status to indicate dashboard is ready."""
    return True

# Add new callback for piece counts
@callback(
    [Output("latest-white-pieces", "children"),
     Output("latest-black-pieces", "children"),
     Output("latest-pieces-game-id", "children")],
    [Input("critical-interval", "n_intervals")],
    prevent_initial_call=True
)
def update_latest_piece_counts(n):
    """Update the latest piece counts display."""
    latest_white, latest_black, game_id = get_latest_piece_counts()
    
    # Format piece counts
    if latest_white is not None:
        white_pieces_text = f"{int(latest_white)}"
    else:
        white_pieces_text = "N/A"
        
    if latest_black is not None:
        black_pieces_text = f"{int(latest_black)}"
    else:
        black_pieces_text = "N/A"
    
    return white_pieces_text, black_pieces_text, game_id or "N/A"
