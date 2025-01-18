#config.py

import redis
from datetime import date, timedelta

class fyersconfig:
    # Fyers API Configuration
    BROKER_APID = "OGS4N9MW72-100"
    BROKER_SECRETKEY = "T7ED0IDY1L"
    BROKER_ACC = "FA2060"  # Your fyers ID
    REDIRECT_URL = "https://127.0.0.1:8080/"
    
    # Authentication Details
    TOTP_KEY = "FTJEBP37ZFWVUTGOBAJEXTS7D3CUPE7M"  # TOTP secret for 2Factor
    PIN = "5417"  # User pin for fyers account
    
    # API Constants
    GRANT_TYPE = "authorization_code"
    RESPONSE_TYPE = "code"
    STATE = "sample"

class RedisConfig:
    REDIS_HOST = 'localhost'
    REDIS_PORT = 6379
    REDIS_DB = 0

# Trading parameters
SYMBOL = ['NSE:NIFTY24D1226000CE', 'NSE:NIFTY24D1225900CE']  
START_DATE = date.today() - timedelta(days=2)
END_DATE = date.today() + timedelta(days=1)
INITIAL_QUANTITY = 25  
DATA_FILE = "data.json"

# Initialize Redis connection
redis_cli = redis.StrictRedis(
    host=RedisConfig.REDIS_HOST,
    port=RedisConfig.REDIS_PORT,
    db=RedisConfig.REDIS_DB,
    decode_responses=True
)
