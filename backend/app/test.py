import pandas as pd 
import numpy as np
from pathlib import Path
import os
import logging
from fyers_apiv3 import fyersModel
from datetime import datetime, timedelta
import pytz
from fastapi import HTTPException

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
    "BANKEX": "BSE:BANKEX-INDEX"
}

def get_current_index_price(index: str) -> float:
    """Get current index price using Fyers API"""
    try:
        # Read access token
        token_path = DATA_DIR / "access_token.txt"
        if not token_path.exists():
            logger.error("Access token file not found")
            return 0

        with open(token_path, 'r') as f:
            access_token = f.read().strip()

        # Initialize Fyers model
        fyers = fyersModel.FyersModel(client_id=os.getenv("FYERS_CLIENT_ID"), is_async=False, token=access_token)

        # Get index symbol
        index_symbol = INDEX_SYMBOLS.get(index)

        # Get current market price
        symbol_data = {"symbols": index_symbol}
        quote_response = fyers.quotes(data=symbol_data)

        if quote_response.get('s') == 'ok':
            return float(quote_response.get('d', [{}])[0].get('v', {}).get('lp', 0))

    except Exception as e:
        logger.error(f"Error getting current index price: {str(e)}")
        return 0

def get_index_strikes(index: str):
    # Read the master data file
    master_df = pd.read_csv(DATA_DIR / "master_file.csv")
    
    # Filter options based on exSymbol
    index_options = master_df[(master_df['exSymbol'] == index) & (master_df['exSymName'].str.contains('CE|PE'))]   
    # Extract strike prices and convert to numeric
    strikes = pd.to_numeric(index_options['strikePrice'].unique(), errors='coerce')
    # strikes = strikes.dropna().sort_values()
    
    # Get current index price from Fyers API
    current_price = get_current_index_price(index)
    
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
        "index_symbol": index
    }

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


def get_historical_straddle(index: str, strikePrice: str, days_back: int = 10):
    try:
        # Load master data
        csv_path = DATA_DIR / "master_file.csv"
        if not csv_path.exists():
            raise HTTPException(status_code=404, detail="Master file not found")
        
        df = pd.read_csv(csv_path)
        
        # Filter for the given index and strike price
        filtered_df = df[(df['exSymbol'].str.contains(index)) & 
                        (df['strikePrice'] == float(strikePrice))]
        
        if filtered_df.empty:
            raise HTTPException(status_code=404, detail="No data found for given criteria")
        
        # Sort by expiry date and get the nearest expiry
        filtered_df = filtered_df.sort_values('expiryDate')
        nearest_expiry = filtered_df['expiryDate'].iloc[0] if not filtered_df.empty else None
        
        if nearest_expiry is None:
            raise HTTPException(status_code=404, detail="No data found for given criteria")
            
        # Get CE and PE symbols
        ce_filtered = filtered_df[filtered_df['symbol'].str.endswith('CE')]
        pe_filtered = filtered_df[filtered_df['symbol'].str.endswith('PE')]
        
        if ce_filtered.empty or pe_filtered.empty:
            raise HTTPException(status_code=404, detail="CE or PE data not found for given criteria")

        ce_data = ce_filtered.iloc[0]
        pe_data = pe_filtered.iloc[0]
        print(ce_data)
        print(pe_data)
        
        # Get historical data
        ce_hist = get_historical_data(ce_data['symbol'], days_back)
        pe_hist = get_historical_data(pe_data['symbol'], days_back)
        spot_hist = get_historical_data(INDEX_SYMBOLS[index], days_back)
        
        # Prepare CE and PE data with symbol names
        ce_json = {
            "symbol": ce_data['symbol'],
            "data": ce_hist[['date', 'close']].values.tolist()
        }
        pe_json = {
            "symbol": pe_data['symbol'],
            "data": pe_hist[['date', 'close']].values.tolist()
        }
        
        return {
            "ce_data": ce_json,
            "pe_data": pe_json
        }
        
    except Exception as e:
        print(e)

# Example Usage
if __name__ == "__main__":
    try:
        # Ensure strikePrice is passed as a string
        print(get_historical_straddle("NIFTY", "23400"))
    except Exception as e:
        print(f"An error occurred: {e}")