from fyers_apiv3.FyersWebsocket import data_ws
import json
from config import fyersconfig
from logger import logger
import time

class FyersWebsocketClient:
    def __init__(self, access_token, redis_client, socketio):
        self.client_id = fyersconfig.BROKER_APID
        self.access_token = access_token
        self.redis_client = redis_client
        self.socketio = socketio
        self.subscribed_symbols = set()
        self.fyers = None
        self.is_connected = False
        self.default_symbols = ["NSE:NIFTY50-INDEX"]
        self.market_update_cb = None
        self.order_update_cb = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.token_expired = False

    def update_token(self, new_token):
        """Update access token and reinitialize connection"""
        try:
            self.access_token = new_token
            self.token_expired = False
            self.reconnect_attempts = 0
            return self.connect()
        except Exception as e:
            logger.error({"error": f"Error updating token: {str(e)}"})
            return False

    def handle_token_expired(self):
        """Handle token expiry by notifying clients"""
        logger.warning({"message": "Token expired, notifying clients"})
        self.token_expired = True
        self.is_connected = False
        self.socketio.emit('auth_status', {"status": "token_expired"}, to=None)

    def on_error(self, error):
        """Handle websocket errors"""
        try:
            error_data = error if isinstance(error, dict) else json.loads(error) if isinstance(error, str) else {"error": str(error)}
            error_msg = str(error_data.get('message', str(error_data)))
            error_code = error_data.get('code', None)
            
            logger.error({
                "message": "Websocket error received",
                "error_code": error_code,
                "error_message": error_msg
            })
            
            # Check specific error conditions
            if error_code == -99 or 'Token is expired' in error_msg:
                self.handle_token_expired()
            elif error_code == 500:
                logger.error({"error": "Internal server error from Fyers"})
            elif error_code == 400:
                logger.error({"error": "Bad request to Fyers API"})
            else:
                logger.error({"error": f"Websocket error: {error_msg}"})
                
            self.is_connected = False
            
        except Exception as e:
            logger.error({
                "error": f"Error handling websocket error: {str(e)}",
                "original_error": str(error)
            })

    def connect(self):
        """Establish websocket connection with retry mechanism"""
        try:
            if self.token_expired:
                logger.warning({"message": "Token is expired, cannot connect"})
                return False

            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logger.error({"message": "Max reconnection attempts reached"})
                return False

            if self.fyers:
                try:
                    self.fyers.close()
                except:
                    pass

            # Initialize the websocket with proper access token format
            auth_token = f"{self.client_id}:{self.access_token}"
            logger.info({
                "message": "Initializing websocket",
                "client_id": self.client_id,
                "token_length": len(self.access_token) if self.access_token else 0
            })

            self.fyers = data_ws.FyersDataSocket(
                access_token=auth_token,
                log_path="",
                litemode=False,
                write_to_file=False,
                reconnect=True,
                on_connect=self.on_connect,
                on_close=self.on_close,
                on_error=self.on_error,
                on_message=self.on_message
            )
            
            # Connect and wait for confirmation
            self.fyers.connect()
            time.sleep(2)  # Give time for connection to establish
            
            # Check connection status
            is_connected = self.fyers and self.fyers.is_connected()
            if is_connected:
                self.is_connected = True
                self.token_expired = False  # Reset token expired flag on successful connection
                self.reconnect_attempts = 0
                logger.info({"message": "Websocket connection established successfully"})
                return True
            else:
                self.reconnect_attempts += 1
                logger.warning({
                    "message": "Connection attempt failed",
                    "attempt": self.reconnect_attempts,
                    "max_attempts": self.max_reconnect_attempts
                })
                return False
            
        except Exception as e:
            self.reconnect_attempts += 1
            logger.error({
                "error": f"Websocket connection failed: {str(e)}",
                "attempt": self.reconnect_attempts
            })
            return False

    def on_connect(self):
        """Handle websocket connection open"""
        try:
            logger.info({"message": "Websocket connected"})
            self.is_connected = True
            self.reconnect_attempts = 0
            
            # Wait a moment before subscribing
            time.sleep(1)
            
            # Subscribe to default symbols
            if self.default_symbols:
                self.subscribe(self.default_symbols)
                logger.info({"message": "Subscribed to default symbols", "symbols": self.default_symbols})
        except Exception as e:
            logger.error({"error": f"Error in on_connect handler: {str(e)}"})

    def on_close(self):
        """Handle websocket connection close"""
        logger.info({"message": "Websocket connection closed"})
        self.is_connected = False
        
        # Attempt to reconnect if not max attempts
        if self.reconnect_attempts < self.max_reconnect_attempts:
            time.sleep(2)  # Wait before reconnecting
            self.connect()

    def set_callbacks(self, market_update_cb=None, order_update_cb=None):
        """Set callback functions for different types of messages"""
        self.market_update_cb = market_update_cb
        self.order_update_cb = order_update_cb
        logger.info({"message": "Callbacks set successfully"})

    def on_message(self, message):
        """Handle incoming market data messages"""
        try:
            # Parse incoming message
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.error({"error": "Failed to parse message as JSON", "message": str(message)[:200]})
                    return
            else:
                data = message

            logger.debug({"message": "Raw message received", "data": data})
            
            # Process market data directly
            try:
                symbol = str(data.get('symbol', ''))
                if not symbol:
                    return

                # Create market data dict with all available fields
                market_update = {
                    'symbol': symbol,
                    'timestamp': int(time.time() * 1000),
                    'ltp': float(data.get('ltp', 0)),
                    'open': float(data.get('open_price', 0)),
                    'high': float(data.get('high_price', 0)),
                    'low': float(data.get('low_price', 0)),
                    'close': float(data.get('prev_close_price', 0)),
                    'volume': int(data.get('vol_traded_today', 0)),
                    'bid': float(data.get('bid_price', 0)),
                    'ask': float(data.get('ask_price', 0)),
                    'bid_qty': int(data.get('bid_size', 0)),
                    'ask_qty': int(data.get('ask_size', 0))
                }

                # Calculate change and change_percent
                prev_close = market_update['close'] or market_update['ltp']
                market_update.update({
                    'change': round(market_update['ltp'] - prev_close, 2),
                    'change_percent': round(((market_update['ltp'] - prev_close) / prev_close * 100) if prev_close != 0 else 0, 2)
                })

                logger.info({
                    "message": "Market data prepared",
                    "symbol": symbol,
                    "ltp": market_update['ltp'],
                    "timestamp": market_update['timestamp']
                })

                # Store in Redis using hset
                redis_key = f"market_update:{symbol}"
                try:
                    # Store as a single JSON object instead of individual fields
                    self.redis_client.set(redis_key, json.dumps(market_update))
                    self.redis_client.expire(redis_key, 86400)  # 24 hour TTL
                    
                    logger.info({
                        "message": "Market data stored in Redis",
                        "symbol": symbol,
                        "key": redis_key
                    })
                except Exception as e:
                    logger.error({
                        "error": f"Redis storage error: {str(e)}",
                        "symbol": symbol
                    })

                # Emit to all clients with market_update event name
                try:
                    if self.socketio:
                        self.socketio.emit('market_update', market_update)
                        logger.info({
                            "message": "Market data broadcasted",
                            "symbol": symbol,
                            "event": "market_update",
                            "ltp": market_update['ltp']
                        })
                except Exception as e:
                    logger.error({
                        "error": f"Socket.IO emission error: {str(e)}",
                        "symbol": symbol
                    })

                # Call market data callback if set
                try:
                    if self.market_update_cb:
                        self.market_update_cb(market_update)
                        logger.info({
                            "message": "Market data callback executed",
                            "symbol": symbol
                        })
                except Exception as e:
                    logger.error({
                        "error": f"Callback error: {str(e)}",
                        "symbol": symbol
                    })

            except Exception as e:
                logger.error({
                    "error": f"Error processing market data: {str(e)}",
                    "data": str(data)[:200],
                    "traceback": str(e.__traceback__)
                })

        except Exception as e:
            logger.error({
                "error": f"Error in on_message: {str(e)}",
                "message": str(message)[:200],
                "traceback": str(e.__traceback__)
            })

    def subscribe(self, symbols):
        """Subscribe to market data with default symbol protection"""
        try:
            if not isinstance(symbols, list):
                symbols = [symbols]
                
            new_symbols = set(symbols) - self.subscribed_symbols
            if new_symbols:
                self.fyers.subscribe(symbols=list(new_symbols))
                self.subscribed_symbols.update(new_symbols)
                logger.info({"message": "Subscribed to symbols", "symbols": list(new_symbols)})
                
        except Exception as e:
            logger.error({"error": f"Subscription failed: {str(e)}"})

    def unsubscribe(self, symbols):
        """Unsubscribe from market data with default symbol protection"""
        try:
            if not isinstance(symbols, list):
                symbols = [symbols]
            
            # Don't unsubscribe from default symbols
            symbols_to_remove = set(symbols) - set(self.default_symbols)
            symbols_to_remove = symbols_to_remove & self.subscribed_symbols
            
            if symbols_to_remove:
                self.fyers.unsubscribe(symbols=list(symbols_to_remove))
                self.subscribed_symbols -= symbols_to_remove
                logger.info({"message": "Unsubscribed from symbols", "symbols": list(symbols_to_remove)})
                
        except Exception as e:
            logger.error({"error": f"Unsubscribe failed: {str(e)}"})