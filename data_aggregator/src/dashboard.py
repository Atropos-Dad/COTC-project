"""
Dashboard module for visualizing chess data in real-time.
"""
import dash
from dash import dcc, html, callback, Output, Input, clientside_callback
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import func, desc
from sqlalchemy.sql import text
import re
import logging

# Initialize logger
logger = logging.getLogger(__name__)

from models import Game, Move, RawData
from database import Session
from chess_utils import is_valid_fen, derive_fen_from_moves, DEFAULT_FEN

# Initialize the Dash app with Bootstrap theme
dash_app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdnjs.cloudflare.com/ajax/libs/chessboard-js/1.0.0/chessboard-1.0.0.min.css"
    ],
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
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
                            style={'width': '250px'}
                        )
                    ])
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
    session = Session()
    try:
        total_games = session.query(func.count(Game.id)).scalar()
        
        # Get games with moves in the last 5 minutes
        five_min_ago = datetime.now() - timedelta(minutes=5)
        active_games = session.query(func.count(func.distinct(Move.game_id)))\
            .filter(Move.timestamp > five_min_ago).scalar()
        
        return f"{total_games}", f"{active_games} active in last 5 min"
    finally:
        session.close()

# Callback for updating data ingestion rate
@callback(
    Output("data-rate", "children"),
    [Input("interval-component", "n_intervals")]
)
def update_data_rate(n):
    session = Session()
    try:
        one_min_ago = datetime.now() - timedelta(minutes=1)
        events_last_minute = session.query(func.count(RawData.id))\
            .filter(RawData.received_timestamp > one_min_ago).scalar()
        
        return f"{events_last_minute}"
    finally:
        session.close()

# Callback for updating latest event
@callback(
    Output("latest-event", "children"),
    [Input("interval-component", "n_intervals")]
)
def update_latest_event(n):
    session = Session()
    try:
        latest_event = session.query(RawData)\
            .order_by(desc(RawData.received_timestamp)).first()
        
        if latest_event:
            measurement = latest_event.measurement or "unknown"
            game_id = "unknown"
            event_type = "unknown"
            
            if latest_event.data and isinstance(latest_event.data, dict):
                tags = latest_event.data.get('tags', {})
                if isinstance(tags, dict):
                    game_id = tags.get('game_id', 'unknown')
                    event_type = tags.get('event_type', 'unknown')
            
            time_diff = datetime.now() - latest_event.received_timestamp
            seconds_ago = int(time_diff.total_seconds())
            
            if seconds_ago < 60:
                time_str = f"{seconds_ago} seconds ago"
            else:
                minutes_ago = seconds_ago // 60
                time_str = f"{minutes_ago} minutes ago"
            
            return f"{measurement} - {event_type} - Game: {game_id} ({time_str})"
        else:
            return "No events recorded yet"
    finally:
        session.close()

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
    session = Session()
    try:
        # Get 5 most recent games
        recent_games = session.query(Game)\
            .order_by(desc(Game.start_time))\
            .limit(5).all()
        
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
            # Count moves for this game
            move_count = session.query(func.count(Move.id))\
                .filter(Move.game_id == game.game_id).scalar()
            
            # Format time
            time_diff = datetime.now() - game.start_time
            if time_diff.days > 0:
                time_str = f"{time_diff.days}d ago"
            elif time_diff.seconds > 3600:
                time_str = f"{time_diff.seconds // 3600}h ago"
            else:
                time_str = f"{time_diff.seconds // 60}m ago"
            
            rows.append(html.Tr([
                html.Td(game.game_id),
                html.Td(game.white_player or "Unknown"),
                html.Td(game.black_player or "Unknown"),
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
    finally:
        session.close()

# Callback for game selector dropdown
@callback(
    Output("game-selector", "options"),
    [Input("interval-component", "n_intervals")]
)
def update_game_selector(n):
    session = Session()
    try:
        # Get active games (with moves in the last 10 minutes)
        ten_min_ago = datetime.now() - timedelta(minutes=10)
        
        # Get game_id and player info for games with recent moves
        active_games = session.query(Game.game_id, Game.white_player, Game.black_player)\
            .join(Move, Game.game_id == Move.game_id)\
            .filter(Move.timestamp > ten_min_ago)\
            .group_by(Game.game_id)\
            .all()
        
        if not active_games:
            return []
        
        # Format options for dropdown
        options = []
        for game_id, white, black in active_games:
            white_name = white or "Unknown"
            black_name = black or "Unknown"
            options.append({
                "label": f"{white_name} vs {black_name} ({game_id})",
                "value": game_id
            })
        
        return options
    finally:
        session.close()

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
    
    session = Session()
    try:
        # Get game info
        game = session.query(Game).filter(Game.game_id == selected_game_id).first()
        
        if not game:
            logger.debug(f"Game {selected_game_id} not found, using DEFAULT_FEN")
            debug_info.append(f"Game {selected_game_id} not found, using DEFAULT_FEN")
            return DEFAULT_FEN, [], "White: Select a game", "Black: Select a game", [], {'display': 'none'}, DEFAULT_FEN, "\n".join(debug_info)
        
        # Get moves for this game, ordered by timestamp
        moves = session.query(Move).filter(Move.game_id == selected_game_id)\
            .order_by(Move.timestamp).all()
        
        debug_info.append(f"Found {len(moves)} moves for game {selected_game_id}")
        
        if not moves:
            logger.debug(f"No moves found for game {selected_game_id}, using DEFAULT_FEN")
            debug_info.append(f"No moves found, using DEFAULT_FEN")
            return DEFAULT_FEN, [], f"White: {game.white_player or 'Unknown'}", f"Black: {game.black_player or 'Unknown'}", [], {'display': 'none'}, DEFAULT_FEN, "\n".join(debug_info)
        
        # Get the latest FEN position or derive it from moves
        latest_move = moves[-1]
        debug_info.append(f"Latest move: {latest_move.last_move}")
        
        # Check if the latest move has a valid FEN position
        if latest_move.fen_position and is_valid_fen(latest_move.fen_position):
            current_fen = latest_move.fen_position
            logger.debug(f"Using stored FEN for game {selected_game_id}: {current_fen}")
            debug_info.append(f"Using stored FEN: {current_fen}")
        else:
            logger.debug(f"Deriving FEN for game {selected_game_id} from {len(moves)} moves")
            debug_info.append(f"Stored FEN missing or invalid, deriving from {len(moves)} moves")
            # Output first few moves for debugging
            if len(moves) > 0:
                debug_info.append("Sample moves:")
                for i, move in enumerate(moves[:5]):
                    debug_info.append(f"  {i}: {move.last_move}")
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
        white_info = f"White: {game.white_player or 'Unknown'}"
        if game.white_rating:
            white_info += f" ({game.white_rating})"
        if game.white_title:
            white_info = f"{game.white_title} {white_info}"
            
        black_info = f"Black: {game.black_player or 'Unknown'}"
        if game.black_rating:
            black_info += f" ({game.black_rating})"
        if game.black_title:
            black_info = f"{game.black_title} {black_info}"
        
        # Create move history display
        move_history_items = []
        for i, move in enumerate(moves):
            if move.last_move:
                move_num = (i // 2) + 1
                if i % 2 == 0:  # White's move
                    move_item = html.Div([
                        html.Span(f"{move_num}. ", className="text-muted"),
                        html.Span(f"{move.last_move}", className="font-weight-bold")
                    ], className="d-inline-block me-2")
                else:  # Black's move
                    move_item = html.Div([
                        html.Span(f"{move.last_move} ", className="font-weight-bold")
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
        move_notations = [m.last_move for m in moves if m.last_move]
        
        # Final check to make sure we're not sending an empty FEN
        if not current_fen or not is_valid_fen(current_fen):
            logger.warning(f"Invalid FEN detected in final output for game {selected_game_id}, using DEFAULT_FEN")
            debug_info.append(f"WARNING: Invalid derived FEN, falling back to DEFAULT_FEN")
            current_fen = DEFAULT_FEN
        
        debug_info.append(f"FINAL FEN being sent to client: {current_fen}")
        
        return current_fen, move_notations, white_info, black_info, move_rows, {'display': 'none'}, current_fen, "\n".join(debug_info)
    except Exception as e:
        logger.exception(f"Error updating chess board: {str(e)}")
        debug_info.append(f"ERROR: {str(e)}")
        return DEFAULT_FEN, [], "Error", "Error", [], {'display': 'none'}, DEFAULT_FEN, "\n".join(debug_info)
    finally:
        session.close()

# Function to get the Dash server
def get_dash_app():
    return dash_app
