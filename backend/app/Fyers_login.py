from datetime import datetime, timedelta
from pathlib import Path
import logging
import os
from fyers_apiv3 import fyersModel
import pyotp
import requests
from urllib.parse import parse_qs, urlparse
import pandas as pd
import base64
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create data directory if it doesn't exist
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Configuration
REDIRECT_URI = "https://127.0.0.1:5000/"
CLIENT_ID = "OGS4N9MW72-100"
SECRET_KEY = "T7ED0IDY1L"
FY_ID = "FA2060"
TOTP_KEY = "FTJEBP37ZFWVUTGOBAJEXTS7D3CUPE7M"
PIN = "5417"

def getEncodedString(string):
    string = str(string)
    base64_bytes = base64.b64encode(string.encode("ascii"))
    return base64_bytes.decode("ascii")

def is_token_valid():
    """Check if the current access token is valid"""
    try:
        token_path = DATA_DIR / "access_token.txt"
        if not token_path.exists():
            logger.info("No access token file found")
            return False
            
        with open(token_path, 'r') as f:
            access_token = f.read().strip()
            
        if not access_token:
            logger.info("Empty access token")
            return False
            
        # Initialize Fyers model with the token
        fyers = fyersModel.FyersModel(client_id=CLIENT_ID, is_async=False, token=access_token)
        
        # Try to get profile data to check token validity
        profile_response = fyers.get_profile()
        
        if profile_response.get('code') == 200:
            logger.info("Access token is valid")
            return True
            
        logger.info(f"Token validation failed: {profile_response}")
        return False
        
    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        return False

def ensure_valid_token():
    """Ensure there is a valid access token, generate new one if needed"""
    try:
        if is_token_valid():
            logger.info("Using existing valid token")
            with open(DATA_DIR / "access_token.txt", 'r') as f:
                return f.read().strip()
        
        logger.info("Getting new access token")
        return get_access_token()
        
    except Exception as e:
        logger.error(f"Error ensuring valid token: {str(e)}")
        raise

def get_access_token():
    try:
        logger.info("Starting access token generation process")
        
        # Send login OTP
        url_send_login_otp = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
        res = requests.post(url=url_send_login_otp, 
                          json={"fy_id": getEncodedString(FY_ID), "app_id": "2"}).json()
        logger.info("OTP sent successfully")

        # Verify TOTP
        url_verify_otp = "https://api-t2.fyers.in/vagator/v2/verify_otp"
        res2 = requests.post(url=url_verify_otp, 
                           json={"request_key": res["request_key"],
                                "otp": pyotp.TOTP(TOTP_KEY).now()}).json()
        logger.info("TOTP verified successfully")

        # Verify PIN
        ses = requests.Session()
        url_verify_pin = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
        payload2 = {
            "request_key": res2["request_key"],
            "identity_type": "pin",
            "identifier": getEncodedString(PIN)
        }
        res3 = ses.post(url=url_verify_pin, json=payload2).json()
        
        ses.headers.update({
            'authorization': f"Bearer {res3['data']['access_token']}"
        })

        # Get token URL
        token_url = "https://api-t1.fyers.in/api/v3/token"
        payload3 = {
            "fyers_id": FY_ID,
            "app_id": CLIENT_ID[:-4],
            "redirect_uri": REDIRECT_URI,
            "appType": "100",
            "code_challenge": "",
            "state": "None",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True
        }
        res3 = ses.post(url=token_url, json=payload3).json()

        # Parse auth code
        url = res3['Url']
        parsed = urlparse(url)
        auth_code = parse_qs(parsed.query)['auth_code'][0]

        # Generate access token
        session = fyersModel.SessionModel(
            client_id=CLIENT_ID,
            secret_key=SECRET_KEY,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code"
        )
        session.set_token(auth_code)
        response = session.generate_token()
        
        # Save access token
        token_path = DATA_DIR / "access_token.txt"
        with open(token_path, 'w') as f:
            f.write(response['access_token'])
        logger.info(f"Access token saved to: {token_path}")
        
        return response['access_token']
    
    except Exception as e:
        logger.error(f"Error in get_access_token: {str(e)}")
        raise

def download_master_instruments():
    try:
        urls = {
            "NSE_FO": "https://public.fyers.in/sym_details/NSE_FO_sym_master.json",
            "BSE_FO": "https://public.fyers.in/sym_details/BSE_FO_sym_master.json"
        }

        df_all = pd.DataFrame()
        for exchange, url in urls.items():
            response = requests.get(url)
            data = response.json()
            df = pd.DataFrame.from_dict(data, orient='index')
            df.reset_index(inplace=True)
            df.rename(columns={'index': 'symbol'}, inplace=True)
            
            columns_to_keep = ['symbol', 'exSymbol', 'segment', 'exchange', 'expiryDate', 'strikePrice', 'exSymName']
            df = df[columns_to_keep]
            df = df[df['exSymbol'].isin(['NIFTY', 'BANKNIFTY','MIDCPNIFTY', 'FINNIFTY', 'SENSEX', 'BANKEX'])]
            
            # Add logging to check dates
            logger.info(f"Sample raw expiry dates: {df['expiryDate'].head()}")
            df['expiryDate'] = pd.to_datetime(df['expiryDate'], unit='s')
            logger.info(f"Sample converted expiry dates: {df['expiryDate'].head()}")
            
            df_all = pd.concat([df_all, df])

        output_path = DATA_DIR / "master_file.csv"
        df_all.to_csv(output_path, index=False)
        logger.info(f"Master instruments data saved to {output_path}")
        
    except Exception as e:
        logger.error(f"Error in download_master_instruments: {str(e)}")
        raise

def get_historical_data(symbol, days_back=10):
    try:
        token_path = DATA_DIR / "access_token.txt"
        with open(token_path, 'r') as f:
            access_token = f.read().strip()

        fyers = fyersModel.FyersModel(client_id=CLIENT_ID, is_async=False, token=access_token)
        
        today = datetime.today()
        range_from = (today - timedelta(days=days_back)).strftime('%Y-%m-%d')
        range_to = (today + timedelta(days=1)).strftime('%Y-%m-%d')

        data = {
            "symbol": symbol,
            "resolution": "5",
            "date_format": "1",
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "1"
        }

        response = fyers.history(data=data)
        df = pd.DataFrame(response["candles"], 
                         columns=["timestamp", "open", "high", "low", "close", "volume"])
        
        # Convert UTC timestamp to IST timezone
        ist = pytz.timezone('Asia/Kolkata')
        df["date"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(ist)
        df = df[["date", "open", "high", "low", "close", "volume"]]
        
        output_path = DATA_DIR / f"{symbol.replace(':', '_')}.csv"
        df.to_csv(output_path, index=False)
        logger.info(f"Historical data saved to {output_path}")
        
        return df
        
    except Exception as e:
        logger.error(f"Error in get_historical_data: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        # Ensure we have a valid token
        access_token = ensure_valid_token()
        
        # Test the token with a simple API call
        fyers = fyersModel.FyersModel(client_id=CLIENT_ID, is_async=False, token=access_token)
        # symbol_data = {"symbols": "NSE:NIFTY50-INDEX"}
        # quote_response = fyers.quotes(data=symbol_data)
        # print("Quote response:", quote_response)
        
        # Optionally download master instruments
        download_master_instruments()
        
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        raise
