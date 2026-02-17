"""Market data downloader supporting Yahoo Finance and Alpha Vantage.

Downloads OHLCV data and saves to CSV in the data/ directory.
"""

import logging
from pathlib import Path
from datetime import datetime

import pandas as pd

from engine.utils import get_data_dir

logger = logging.getLogger(__name__)


class DataDownloader:
    """Downloads market data from external APIs."""

    @staticmethod
    def from_yahoo(ticker: str, start: str = "2020-01-01",
                   end: str = None, interval: str = "1d") -> pd.DataFrame:
        """Download data from Yahoo Finance using yfinance.

        Args:
            ticker: Ticker symbol (e.g., 'AAPL', 'BTC-USD', 'SPY')
            start: Start date string (YYYY-MM-DD)
            end: End date string (YYYY-MM-DD). Defaults to today.
            interval: Data interval. Options:
                      '1m','2m','5m','15m','30m','60m','90m','1h' (max 7 days)
                      '1d','5d','1wk','1mo','3mo' (longer history)

        Returns:
            DataFrame with OHLCV data and datetime index
        """
        try:
            import yfinance as yf
        except ImportError:
            raise ImportError("yfinance not installed. Install with: pip install yfinance")

        if end is None:
            end = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Downloading {ticker} from Yahoo Finance ({start} to {end}, {interval})")

        data = yf.download(ticker, start=start, end=end, interval=interval, progress=False)

        if data.empty:
            raise ValueError(f"No data returned for {ticker} ({start} to {end})")

        # Handle multi-level columns from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Normalize column names
        data.columns = [c.lower().replace(" ", "_") for c in data.columns]

        # Rename 'adj_close' to keep standard OHLCV
        if "adj_close" in data.columns and "close" not in data.columns:
            data.rename(columns={"adj_close": "close"}, inplace=True)

        # Ensure required columns
        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in data.columns:
                raise ValueError(f"Missing column '{col}' in downloaded data. "
                                 f"Columns: {list(data.columns)}")

        # Keep only OHLCV
        data = data[required]
        data.index.name = "date"

        logger.info(f"Downloaded {len(data)} bars for {ticker}")
        return data

    @staticmethod
    def from_alpha_vantage(ticker: str, api_key: str,
                           function: str = "TIME_SERIES_DAILY",
                           outputsize: str = "full") -> pd.DataFrame:
        """Download data from Alpha Vantage API.

        Args:
            ticker: Ticker symbol
            api_key: Alpha Vantage API key
            function: API function (TIME_SERIES_DAILY, TIME_SERIES_INTRADAY, etc.)
            outputsize: 'compact' (100 points) or 'full' (20+ years)

        Returns:
            DataFrame with OHLCV data and datetime index
        """
        try:
            import requests
        except ImportError:
            raise ImportError("requests not installed. Install with: pip install requests")

        logger.info(f"Downloading {ticker} from Alpha Vantage ({function})")

        url = "https://www.alphavantage.co/query"
        params = {
            "function": function,
            "symbol": ticker,
            "apikey": api_key,
            "outputsize": outputsize,
            "datatype": "json",
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        # Find the time series key
        ts_key = None
        for key in data:
            if "Time Series" in key:
                ts_key = key
                break

        if ts_key is None:
            error = data.get("Error Message", data.get("Note", "Unknown error"))
            raise ValueError(f"Alpha Vantage API error: {error}")

        ts_data = data[ts_key]

        # Parse into DataFrame
        records = []
        for date_str, values in ts_data.items():
            records.append({
                "date": pd.to_datetime(date_str),
                "open": float(values.get("1. open", 0)),
                "high": float(values.get("2. high", 0)),
                "low": float(values.get("3. low", 0)),
                "close": float(values.get("4. close", 0)),
                "volume": float(values.get("5. volume", 0)),
            })

        df = pd.DataFrame(records)
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)

        logger.info(f"Downloaded {len(df)} bars for {ticker} from Alpha Vantage")
        return df

    @staticmethod
    def save_to_csv(df: pd.DataFrame, ticker: str,
                    interval: str = "1d", data_dir: str = None) -> str:
        """Save DataFrame to CSV in the data/ directory.

        Naming convention: TICKER_INTERVAL.csv (e.g., AAPL_1d.csv)

        Args:
            df: DataFrame with OHLCV data
            ticker: Ticker symbol
            interval: Data interval string
            data_dir: Override data directory path

        Returns:
            Path to the saved CSV file
        """
        data_path = Path(data_dir) if data_dir else get_data_dir()
        data_path.mkdir(parents=True, exist_ok=True)

        filename = f"{ticker.upper()}_{interval}.csv"
        filepath = data_path / filename

        df.to_csv(filepath)
        logger.info(f"Saved {len(df)} bars to {filepath}")
        return str(filepath)

    @staticmethod
    def list_available_data(data_dir: str = None) -> list:
        """List all CSV files in the data directory with metadata.

        Returns:
            List of dicts with filename, ticker, timeframe info
        """
        data_path = Path(data_dir) if data_dir else get_data_dir()

        files = []
        for csv_file in sorted(data_path.glob("*.csv")):
            parts = csv_file.stem.split("_")
            ticker = parts[0] if parts else csv_file.stem
            interval = parts[1] if len(parts) > 1 else "unknown"

            try:
                # Read just the first and last few rows for date range
                df = pd.read_csv(csv_file, nrows=1)
                # Count lines efficiently
                with open(csv_file) as f:
                    row_count = sum(1 for _ in f) - 1

                files.append({
                    "filename": csv_file.name,
                    "path": str(csv_file),
                    "ticker": ticker.upper(),
                    "interval": interval,
                    "rows": row_count,
                })
            except Exception as e:
                files.append({
                    "filename": csv_file.name,
                    "path": str(csv_file),
                    "error": str(e),
                })

        return files
