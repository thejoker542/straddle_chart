import os
from fyers_apiv3.FyersWebsocket import data_ws
import json
import logging
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Read access token from file
def get_access_token():
    try:
        with open('access_token.txt', 'r') as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.error("access_token.txt file not found")
        raise

old_access_token = get_access_token()
client_id = "OGS4N9MW72"

def onmessage(message):
    """
    Callback function to handle incoming messages from the FyersDataSocket WebSocket.

    Parameters:
        message (dict): The received message from the WebSocket.

    """
    print("Response:", message)

    # Example condition: Unsubscribe from NSE:ITC-EQ if its LTP (Last Traded Price) exceeds a certain value
    if message.get('symbol') == 'NSE:ITC-EQ' and message.get('ltp', 0) > 230:  # Replace 230 with your desired condition
        # Unsubscribe from the specified symbol and data type
        data_type = "SymbolUpdate"
        symbols_to_unsubscribe = ['NSE:ITC-EQ']
        fyersDataws.unsubscribe(symbols=symbols_to_unsubscribe, data_type=data_type)
        print(f"Unsubscribed from {symbols_to_unsubscribe} because LTP exceeded the condition")


def onerror(message):
    """
    Callback function to handle WebSocket errors.

    Parameters:
        message (dict): The error message received from the WebSocket.

    """
    print("Error:", message)


def onclose(message):
    """
    Callback function to handle WebSocket connection close events.
    """
    print("Connection closed:", message)


def onopen():
    """
    Callback function to subscribe to data type and symbols upon WebSocket connection.

    """
    # Specify the data type and symbols you want to subscribe to
    data_type = "SymbolUpdate"

    # Subscribe to the specified symbols and data type
    symbols = ['NSE:NIFTY50-INDEX']
    fyersDataws.subscribe(symbols=symbols, data_type=data_type)

    # Keep the socket running to receive real-time data
    fyersDataws.keep_running()


# Replace the sample access token with your actual access token obtained from Fyers
access_token = f'{client_id}:{old_access_token}'

# Create a FyersDataSocket instance with the provided parameters
fyersDataws = data_ws.FyersDataSocket(
    access_token=access_token,       # Access token in the format "appid:accesstoken"
    log_path="",                     # Path to save logs. Leave empty to auto-create logs in the current directory.
    litemode=False,                  # Lite mode disabled. Set to True if you want a lite response.
    write_to_file=False,              # Save response in a log file instead of printing it.
    reconnect=True,                  # Enable auto-reconnection to WebSocket on disconnection.
    on_connect=onopen,               # Callback function to subscribe to data upon connection.
    on_close=onclose,                # Callback function to handle WebSocket connection close events.
    on_error=onerror,                # Callback function to handle WebSocket errors.
    on_message=onmessage             # Callback function to handle incoming messages from the WebSocket.
)

# Function to add a symbol to the subscription
def add_symbol():
    symbol_to_add = 'NSE:ITC-EQ'
    fyersDataws.subscribe(symbols=[symbol_to_add], data_type="SymbolUpdate")
    print(f"Added {symbol_to_add} to subscription")

# Schedule the addition of the symbol after 30 seconds
threading.Timer(30, add_symbol).start()

# Establish a connection to the Fyers WebSocket
print("fyersDataws.connect()")
fyersDataws.connect()