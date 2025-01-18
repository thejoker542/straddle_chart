import pytest
from fastapi.testclient import TestClient
import pandas as pd
from pathlib import Path
import json
import sys

# Add parent directory to Python path for imports
sys.path.append(str(Path(__file__).parent))
from main import app

# Create test client
client = TestClient(app)

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Trading Data API is running"}

def test_access_token_endpoint():
    response = client.get("/access-token")
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert isinstance(response.json()["access_token"], str)

def test_master_data_endpoint():
    response = client.get("/master-data")
    assert response.status_code == 200
    data = response.json()["data"]
    assert isinstance(data, list)
    if len(data) > 0:
        assert all(key in data[0] for key in [
            "symbol", "exSymbol", "segment", "exchange", 
            "expiryDate", "strikePrice", "exSymName"
        ])

def test_historical_straddle_endpoint():
    # Test with a sample symbol
    test_symbol = "NIFTY2510923450CE"
    response = client.get(f"/historical-straddle/{test_symbol}")
    assert response.status_code == 200
    data = response.json()
    
    # Check response structure
    assert "original_symbol" in data
    assert "formatted_symbol" in data
    assert "pe_symbol" in data
    assert "data" in data
    
    # Verify symbol formatting
    assert data["original_symbol"] == test_symbol
    assert data["formatted_symbol"] == f"NSE:{test_symbol}"
    assert data["pe_symbol"] == f"NSE:{test_symbol[:-2]}PE"
    
    # Save response data to CSV for testing verification
    if len(data["data"]) > 0:
        test_df = pd.DataFrame(data["data"])
        test_output_path = Path(__file__).parent.parent / "data" / f"test_straddle_{test_symbol}.csv"
        test_df.to_csv(test_output_path, index=False)
        
        first_entry = data["data"][0]
        assert all(key in first_entry for key in [
            "date", "ce_price", "pe_price", "straddle_price"
        ])
        
        # Verify straddle price calculation
        assert first_entry["straddle_price"] == (
            first_entry["ce_price"] + first_entry["pe_price"]
        )

def test_historical_straddle_invalid_symbol():
    response = client.get("/historical-straddle/INVALID_SYMBOL")
    assert response.status_code == 500

def test_data_files_exist():
    """Test if necessary data files are created"""
    data_dir = Path(__file__).parent.parent / "data"
    
    assert (data_dir / "access_token.txt").exists(), "Access token file not found"
    assert (data_dir / "master_file.csv").exists(), "Master file not found"

if __name__ == "__main__":
    pytest.main(["-v", __file__])
