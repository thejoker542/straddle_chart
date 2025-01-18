from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from pathlib import Path
import logging
import os
import sys
import json
import time
from datetime import datetime, timedelta
import pytz
import numpy as np
from typing import Dict, Optional, List, Any
import pyarrow.parquet as pq
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from Fyers_login import ensure_valid_token, CLIENT_ID
from contextlib import asynccontextmanager
import asyncio
from queue import Queue
import threading
from pydantic import BaseModel
import socketio
from fyers_ws import FyersWebsocketClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create data directory if it doesn't exist
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Create cache directory for parquet files
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Constants
INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
    "BANKEX": "BSE:BANKEX-INDEX"
}

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()
        self.message_queue = Queue()
        self.broadcast_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.broadcast_thread.start()

    def _process_queue(self):
        """Process messages from the queue in a separate thread"""
        while True:
            try:
                message = self.message_queue.get()
                if message is None:  # Shutdown signal
                    break
                
                # Get the running event loop or create a new one
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Run the broadcast in the event loop
                loop.run_until_complete(self.broadcast(message))
                
            except Exception as e:
                logger.error(f"Error processing message from queue: {e}")

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info(f"Client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total connections: {len(self.active_connections)}")

    def broadcast_sync(self, message: dict):
        """Add message to queue for broadcasting"""
        self.message_queue.put(message)

    async def broadcast(self, message: dict):
        """Asynchronous broadcast to all connected clients"""
        async with self._lock:
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to client: {e}")
                    disconnected.append(connection)
            
            # Clean up disconnected clients
            for connection in disconnected:
                try:
                    self.active_connections.remove(connection)
                except ValueError:
                    pass  # Connection already removed

manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        logger.info("Validating Fyers access token")
        access_token = await ensure_valid_token()
        if access_token:
            logger.info("Token validation successful, initializing WebSocket")
            # Initialize WebSocket client
            app.state.ws_client = FyersWebsocketClient(
                access_token=access_token,
                redis_client=None,
                socketio=sio
            )
            
            # Connect WebSocket client
            connected = app.state.ws_client.connect()
            if not connected:
                logger.error("Failed to connect WebSocket client")
            else:
                logger.info("WebSocket client connected successfully")
        else:
            logger.error("Failed to get valid access token")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        app.state.ws_client = None
    
    yield
    
    # Shutdown
    if hasattr(app.state, 'ws_client') and app.state.ws_client:
        try:
            app.state.ws_client.fyers.close()
            logger.info("WebSocket client closed successfully")
        except Exception as e:
            logger.error(f"Error closing WebSocket client: {str(e)}")
    
    if fyers_socket and fyers_socket.is_connected():
        fyers_socket.close()
    # Signal broadcast thread to stop
    manager.message_queue.put(None)
    manager.broadcast_thread.join(timeout=5)

# Initialize Socket.IO
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio)

# Initialize FastAPI
app = FastAPI(title="Trading Data API", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Socket.IO app
app.mount("/socket.io", socket_app)

# Socket.IO events
@sio.event
async def connect(sid, environ):
    logger.info(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    logger.info(f"Client disconnected: {sid}")

# Global WebSocket client
fyers_socket = None
market_data_cache = {}

def on_message(message):
    """Callback for WebSocket messages"""
    try:
        # Parse incoming message
        if isinstance(message, str):
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse message as JSON: {message[:200]}")
                return
        else:
            data = message

        if isinstance(data, dict):
            symbol = data.get('symbol', '')
            if symbol:
                # Create market data dict directly from Fyers data
                market_update = {
                    'symbol': symbol,
                    'timestamp': data.get('exch_feed_time', int(time.time())),
                    'ltp': float(data.get('ltp', 0)),
                    'open': float(data.get('open_price', 0)),
                    'high': float(data.get('high_price', 0)),
                    'low': float(data.get('low_price', 0)),
                    'prev_close': float(data.get('prev_close_price', 0)),
                    'change': float(data.get('ch', 0)),
                    'change_percent': float(data.get('chp', 0)),
                    'volume': int(data.get('vol_traded_today', 0))
                }

                # Update cache and broadcast
                update_market_data(symbol, market_update)
                manager.broadcast_sync(market_update)
                
                # Log index updates
                if symbol in INDEX_SYMBOLS.values():
                    logger.info(f"Index update received: {symbol} - {market_update['ltp']}")
    except Exception as e:
        logger.error(f"Error processing WebSocket message: {str(e)}")
        logger.error(f"Message causing error: {message}")

def on_connect():
    """Callback for WebSocket connection"""
    logger.info("Connected to Fyers WebSocket")

def on_error(error):
    """Callback for WebSocket errors"""
    logger.error(f"Fyers WebSocket error: {error}")

def on_close():
    """Callback for WebSocket close"""
    logger.info("Fyers WebSocket connection closed")

async def initialize_websocket():
    """Initialize Fyers WebSocket connection"""
    try:
        # Ensure valid token
        access_token = ensure_valid_token()
        if not access_token:
            logger.error("No valid access token available")
            return

        global fyers_socket
        
        # Initialize WebSocket with proper access token format
        auth_token = f"{CLIENT_ID}:{access_token}"
        
        # Initialize WebSocket
        fyers_socket = data_ws.FyersDataSocket(
            access_token=auth_token,
            log_path=str(DATA_DIR),
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=on_connect,
            on_close=on_close,
            on_error=on_error,
            on_message=on_message
        )
        
        # Subscribe to indices
        symbols = list(INDEX_SYMBOLS.values())
        logger.info(f"Subscribing to symbols: {symbols}")
        
        # Connect first
        fyers_socket.connect()
        await asyncio.sleep(2)  # Wait for connection to establish
        
        if fyers_socket.is_connected():
            # Then subscribe
            fyers_socket.subscribe(symbols=symbols, data_type="SymbolUpdate")
            logger.info("Successfully subscribed to symbols")
            
            # Add debug log to verify subscription
            logger.info(f"Current subscriptions: {getattr(fyers_socket, 'subscribed_symbols', [])}")
        else:
            logger.error("Failed to establish WebSocket connection")
        
    except Exception as e:
        logger.error(f"Error initializing WebSocket: {e}")
        logger.exception("Full traceback:")

def update_market_data(symbol: str, data: Dict):
    """Update market data in memory and optionally save to parquet"""
    try:
        market_data_cache[symbol] = {
            "data": data,
            "timestamp": datetime.fromtimestamp(data.get('timestamp', time.time()), pytz.timezone('Asia/Kolkata'))
        }
        
        # Save to parquet every 5 minutes
        cache_file = CACHE_DIR / f"{symbol.replace(':', '_')}.parquet"
        current_time = datetime.now()
        
        if not cache_file.exists() or (current_time - datetime.fromtimestamp(cache_file.stat().st_mtime)).total_seconds() > 300:  # 5 minutes
            df = pd.DataFrame([data])
            df['timestamp'] = pd.Timestamp.fromtimestamp(data.get('timestamp', time.time()), tz='Asia/Kolkata')
            if cache_file.exists():
                existing_df = pd.read_parquet(cache_file)
                df = pd.concat([existing_df, df]).tail(1000)  # Keep last 1000 records
            df.to_parquet(cache_file, index=False)
            
    except Exception as e:
        logger.error(f"Error updating market data: {str(e)}")
        logger.error(f"Data causing error: {data}")

def get_market_data(symbol: str) -> Optional[float]:
    """Get latest market data for a symbol"""
    if symbol in market_data_cache:
        return market_data_cache[symbol]["data"].get("ltp")
    
    # Try to get from parquet if exists
    cache_file = CACHE_DIR / f"{symbol.replace(':', '_')}.parquet"
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        if not df.empty:
            return df.iloc[-1].get("ltp")
    
    return None

def get_current_index_price(index: str) -> float:
    """Get current index price using Fyers API"""
    try:
        # Read access token
        token_path = DATA_DIR / "access_token.txt"
        if not token_path.exists():
            logger.error("Access token file not found")
            raise HTTPException(status_code=404, detail="Access token file not found")

        with open(token_path, 'r') as f:
            access_token = f.read().strip()

        # Initialize Fyers model
        fyers = fyersModel.FyersModel(client_id=os.getenv("FYERS_CLIENT_ID"), is_async=False, token=access_token)

        # Get index symbol
        index_symbol = INDEX_SYMBOLS.get(index)
        if not index_symbol:
            logger.error(f"Index symbol not found for index: {index}")
            raise HTTPException(status_code=400, detail=f"Invalid index: {index}")

        # Get current market price
        symbol_data = {"symbols": index_symbol}
        quote_response = fyers.quotes(data=symbol_data)

        if quote_response.get('s') == 'ok':
            lp = quote_response.get('d', [{}])[0].get('v', {}).get('lp', 0)
            logger.info(f"Current price for {index}: {lp}")
            return float(lp)
        else:
            logger.error(f"Error in Fyers response: {quote_response}")
            raise HTTPException(status_code=500, detail="Failed to fetch current index price from Fyers API")

    except Exception as e:
        logger.error(f"Error getting current index price: {str(e)}")
        return 0

@app.get("/index-strikes/{index}")
async def get_index_strikes(index: str):
    try:
        # Read the master data file
        master_df = pd.read_csv(DATA_DIR / "master_file.csv")
        
        # Filter options based on exSymbol
        index_options = master_df[
            (master_df['exSymbol'] == index) & 
            (master_df['exSymName'].str.contains('CE|PE'))  # Only get options
        ]
        
        if index_options.empty:
            raise HTTPException(status_code=404, detail=f"No options found for index {index}")
        
        # Extract strike prices and convert to numeric
        strikes = pd.to_numeric(index_options['strikePrice'].unique(), errors='coerce')
        
        # Get current index price from Fyers API
        current_price = get_current_index_price(index)
        
        if current_price == 0:
            raise HTTPException(status_code=500, detail="Failed to get current index price")
        
        # Find the nearest strike price
        nearest_strike = strikes[abs(strikes - current_price).argmin()]
        
        # Get strike index and select surrounding strikes
        strike_idx = list(strikes).index(nearest_strike)
        
        # Get 5 strikes below and 5 strikes above
        start_idx = max(0, strike_idx - 5)
        end_idx = min(len(strikes), strike_idx + 6)
        selected_strikes = strikes[start_idx:end_idx].tolist()
        
        return {
            "strikes": selected_strikes,
            "default_strike": nearest_strike,
            "current_price": current_price,
            "index_symbol": INDEX_SYMBOLS.get(index)
        }
        
    except Exception as e:
        logger.error(f"Error getting strike prices: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def get_historical_data(symbol, days_back=10):
    try:
        token_path = DATA_DIR / "access_token.txt"
        with open(token_path, 'r') as f:
            access_token = f.read().strip()

        fyers = fyersModel.FyersModel(client_id="OGS4N9MW72", is_async=False, token=access_token)
        
        today = datetime.today()
        range_from = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')
        range_to = (today + timedelta(days=1)).strftime('%Y-%m-%d')

        data = {
            "symbol": symbol,
            "resolution": "1",
            "date_format": "1",
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "1"
        }

        response = fyers.history(data=data)
        df = pd.DataFrame(response["candles"], 
                         columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        # Convert UTC timestamp to IST timezone and format as YYYY-MM-DD HH:mm
        ist = pytz.timezone('Asia/Kolkata')
        df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(ist).dt.strftime('%Y-%m-%d %H:%M')
        df = df[["date", "open", "high", "low", "close", "volume"]]
        
        output_path = DATA_DIR / f"{symbol.replace(':', '_')}.csv"
        df.to_csv(output_path, index=False)
        logger.info(f"Historical data saved to {output_path}")
        
        return df
        
    except Exception as e:
        logger.error(f"Error in get_historical_data: {str(e)}")
        raise

def get_historical_straddle(index: str, strikePrice: str, days_back: int = 10) -> Dict[str, Any]:
    """Get historical straddle data for a given index and strike price"""
    try:
        # Load master data
        csv_path = DATA_DIR / "master_file.csv"
        if not csv_path.exists():
            logger.error("Master file not found")
            raise HTTPException(status_code=404, detail="Master file not found")
        
        df = pd.read_csv(csv_path)
        
        # Filter for the given index and strike price
        filtered_df = df[(df['exSymbol'].str.contains(index)) & 
                        (df['strikePrice'] == float(strikePrice))]
        
        if filtered_df.empty:
            logger.error(f"No data found for index: {index} with strike price: {strikePrice}")
            raise HTTPException(status_code=404, detail="No data found for given criteria")
        
        # Sort by expiry date and get the nearest expiry
        filtered_df = filtered_df.sort_values('expiryDate')
        nearest_expiry = filtered_df['expiryDate'].iloc[0] if not filtered_df.empty else None
        
        if nearest_expiry is None:
            logger.error("No expiry date found for the filtered criteria")
            raise HTTPException(status_code=404, detail="No data found for given criteria")
            
        # Get CE and PE symbols
        ce_filtered = filtered_df[filtered_df['symbol'].str.endswith('CE')]
        pe_filtered = filtered_df[filtered_df['symbol'].str.endswith('PE')]
        
        if ce_filtered.empty or pe_filtered.empty:
            logger.error("CE or PE data not found for given criteria")
            raise HTTPException(status_code=404, detail="CE or PE data not found for given criteria")

        ce_data = ce_filtered.iloc[0]
        pe_data = pe_filtered.iloc[0]
        logger.info(f"CE Data: {ce_data['symbol']}")
        logger.info(f"PE Data: {pe_data['symbol']}")
        
        # Get historical data
        ce_hist = get_historical_data(ce_data['symbol'], days_back)
        pe_hist = get_historical_data(pe_data['symbol'], days_back)
        spot_hist = get_historical_data(INDEX_SYMBOLS[index], days_back)
        
        # Prepare CE and PE data with symbol names
        ce_json = {
            "symbol": ce_data['symbol'],
            "data": ce_hist[['date', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        }
        pe_json = {
            "symbol": pe_data['symbol'],
            "data": pe_hist[['date', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        }
        
        logger.info(f"Successfully fetched historical straddle data for index: {index}, strike price: {strikePrice}")
        
        return {
            "ce_data": ce_json,
            "pe_data": pe_json
        }
        
    except HTTPException as he:
        logger.error(f"HTTPException: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"Error in get_historical_straddle: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

class HistoricalData(BaseModel):
    symbol: str
    data: List[List[Any]]  # List of [date, close] pairs

class HistoricalStraddleResponse(BaseModel):
    ce_data: HistoricalData
    pe_data: HistoricalData

@app.get("/historical_straddle/{index}/{strikePrice}", response_model=HistoricalStraddleResponse)
def historical_straddle_endpoint(index: str, strikePrice: str):
    """
    Endpoint to retrieve historical straddle data (CE and PE) for a given index and strike price.

    - **index**: The market index (e.g., NIFTY, BANKNIFTY)
    - **strikePrice**: The strike price as a string (e.g., "23400")
    - **days_back**: Number of days back for historical data (optional, default is 10)
    """
    try:
        logger.info(f"Received request for historical straddle data: Index={index}, Strike Price={strikePrice}")
        straddle_data = get_historical_straddle(index, strikePrice)
        return HistoricalStraddleResponse(
            ce_data=HistoricalData(**straddle_data["ce_data"]),
            pe_data=HistoricalData(**straddle_data["pe_data"])
        )
    except HTTPException as he:
        logger.error(f"HTTPException in endpoint: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"Unhandled exception in endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        if not fyers_socket or not fyers_socket.is_connected():
            await initialize_websocket()
            
        while True:
            # Keep connection alive and wait for messages
            data = await websocket.receive_text()
            # You can handle client messages here if needed
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        manager.disconnect(websocket)

@app.get("/")
async def root():
    """Root endpoint to check API status"""
    return {
        "status": "active",
        "timestamp": datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
        "websocket_connected": bool(fyers_socket and fyers_socket.is_connected())
    }

@app.post("/subscribe")
async def subscribe_symbols(request: Request):
    try:
        data = await request.json()
        symbols = data.get('symbols', [])
        
        if not symbols:
            raise HTTPException(status_code=400, detail="No symbols provided")
            
        logger.info({
            "message": "Subscribing to symbols",
            "symbols": symbols
        })
        
        # Get the WebSocket client from the app state
        ws_client = app.state.ws_client
        if not ws_client or not ws_client.is_connected:
            raise HTTPException(status_code=503, detail="WebSocket connection not available")
            
        # Subscribe to the symbols
        ws_client.subscribe(symbols)
        
        return {"status": "success", "message": "Subscribed to symbols", "symbols": symbols}
        
    except Exception as e:
        logger.error({
            "error": f"Error subscribing to symbols: {str(e)}",
            "traceback": str(e.__traceback__)
        })
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)