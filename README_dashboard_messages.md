# Dashboard Messaging System

This feature allows sending messages from the dashboard to all connected client machines, which are then stored in a logbook file.

## System Components

### Dashboard UI
- A text input field and button added to the dashboard UI
- Messages entered by users are sent to all client machines

### Server (app.py)
- Added an API endpoint `/api/send_message` to receive messages from the dashboard
- Uses existing WebSocket infrastructure to broadcast messages to connected clients
- Messages are tagged with timestamps and message type

### Client (async_metrics.py)
- Added a new event handler for `dashboard_message` events
- Messages received from the server are written to a logbook file
- Logbook location: `logbook/dashboard_messages.log` in the current working directory

## How to Use

1. Start the data aggregator server as usual
2. Start the data collector client as usual
3. Navigate to the dashboard in your browser
4. Find the "Send Message to Clients" section
5. Enter a message in the text box and click "Send Message"
6. The message will be sent to all connected clients and stored in their logbook files

## Message Format

Messages in the logbook file are stored with timestamps and the IP address of the dashboard user:

```
[2023-07-30T14:53:26.123456] [192.168.1.100] Your message text here
```

The logbook file is created in the `logbook` directory in the current working directory of where the client application is started.

## Implementation Notes

- Uses the existing `/ws/metrics` WebSocket namespace
- Leverages the existing Socket.IO infrastructure for client-server communication
- No additional applications are required beyond the standard data_aggregator and data_collector 