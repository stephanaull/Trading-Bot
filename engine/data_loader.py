"""CSV data loading, validation, and preprocessing for OHLCV data."""

import os
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

from engine.utils import get_data_dir

logger = logging.getLogger(__name__)

# Common column name variations to normalize
COLUMN_MAP = {
    "date": "date", "Date": "date", "datetime": "date", "Datetime": "date",
    "timestamp": "date", "Timestamp": "date", "time": "date", "Time": "date",
    "open": "open", "Open": "open", "OPEN": "open",
    "high": "high", "High": "high", "HIGH": "high",
    "low": "low", "Low": "low", "LOW": "low",
    "close": "close", "Close": "close", "CLOSE": "close",
    "adj close": "close", "Adj Close": "close", "adj_close": "close",
    "volume": "volume", "Volume": "volume", "VOLUME": "volume",
    "vol": "volume", "Vol": "volume",
}

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


class DataLoader:
    """Loads, validates, and preprocesses OHLCV data from CSV files."""

    @staticmethod
    def from_csv(filepath: str, date_column: str = None) -> pd.DataFrame:
        """Load OHLCV data from a CSV file.

        Args:
            filepath: Path to the CSV file
            date_column: Name of the date column (auto-detected if None)

        Returns:
            DataFrame with normalized columns: date (index), open, high, low, close, volume
        """
        filepath = Path(filepath)
        if not filepath.exists():
            # Try looking in data/ directory
            alt_path = get_data_dir() / filepath.name
            if alt_path.exists():
                filepath = alt_path
            else:
                raise FileNotFoundError(f"Data file not found: {filepath}")

        df = pd.read_csv(filepath)

        # Normalize column names
        df.columns = [COLUMN_MAP.get(col.strip(), col.strip().lower()) for col in df.columns]

        # Find and parse date column
        if date_column:
            date_col = COLUMN_MAP.get(date_column, date_column.lower())
        else:
            date_col = "date"
            if date_col not in df.columns:
                # Try to find a date-like column
                for col in df.columns:
                    if col in ("date", "datetime", "timestamp", "time"):
                        date_col = col
                        break

        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col])
            df.set_index(date_col, inplace=True)
        else:
            # Assume the first column or index is the date
            df.index = pd.to_datetime(df.index)

        df.index.name = "date"

        # Ensure required columns exist
        missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

        # Keep only OHLCV + any extra columns (indicators already present)
        base_cols = [col for col in REQUIRED_COLUMNS if col in df.columns]
        extra_cols = [col for col in df.columns if col not in REQUIRED_COLUMNS]
        df = df[base_cols + extra_cols]

        # Sort by date ascending
        df.sort_index(inplace=True)

        # Convert to float
        for col in base_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop rows with NaN in OHLCV
        df.dropna(subset=base_cols, inplace=True)

        # Validate
        warnings = DataLoader.validate(df)
        for w in warnings:
            logger.warning(w)

        logger.info(f"Loaded {len(df)} bars from {filepath.name} "
                     f"({df.index[0].date()} to {df.index[-1].date()})")
        return df

    @staticmethod
    def validate(df: pd.DataFrame) -> list:
        """Validate OHLCV data integrity. Returns list of warning messages."""
        warnings = []

        # Check for high < low violations
        violations = df[df["high"] < df["low"]]
        if len(violations) > 0:
            warnings.append(f"Found {len(violations)} bars where high < low")

        # Check for negative prices
        for col in ["open", "high", "low", "close"]:
            neg = df[df[col] < 0]
            if len(neg) > 0:
                warnings.append(f"Found {len(neg)} negative values in {col}")

        # Check for duplicate timestamps
        dupes = df.index.duplicated()
        if dupes.any():
            warnings.append(f"Found {dupes.sum()} duplicate timestamps")

        # Check for zero volume
        zero_vol = df[df["volume"] == 0]
        if len(zero_vol) > 5:
            warnings.append(f"Found {len(zero_vol)} bars with zero volume")

        # Check chronological ordering
        if not df.index.is_monotonic_increasing:
            warnings.append("Data is not in chronological order")

        return warnings

    @staticmethod
    def resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """Resample OHLCV data to a different timeframe.

        Args:
            df: Source DataFrame with OHLCV data
            timeframe: Target timeframe ('5min', '15min', '1h', '4h', '1d', '1w', '1M')

        Returns:
            Resampled DataFrame
        """
        # Map friendly names to pandas offset aliases
        tf_map = {
            "1min": "1min", "5min": "5min", "15min": "15min", "30min": "30min",
            "1h": "1h", "4h": "4h",
            "1d": "1D", "1w": "1W", "1M": "1ME",
        }
        freq = tf_map.get(timeframe, timeframe)

        resampled = df.resample(freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        return resampled

    @staticmethod
    def list_available(data_dir: str = None) -> list:
        """List all available CSV data files with metadata.

        Returns:
            List of dicts with filename, ticker, timeframe, rows, date range
        """
        data_path = Path(data_dir) if data_dir else get_data_dir()
        files = []

        for csv_file in sorted(data_path.glob("*.csv")):
            try:
                df = pd.read_csv(csv_file, nrows=0)
                # Count rows efficiently
                row_count = sum(1 for _ in open(csv_file)) - 1

                # Try to parse ticker and timeframe from filename
                parts = csv_file.stem.split("_")
                ticker = parts[0] if parts else csv_file.stem
                timeframe = parts[1] if len(parts) > 1 else "unknown"

                files.append({
                    "filename": csv_file.name,
                    "path": str(csv_file),
                    "ticker": ticker.upper(),
                    "timeframe": timeframe,
                    "rows": row_count,
                    "columns": list(df.columns),
                })
            except Exception as e:
                logger.warning(f"Could not read {csv_file.name}: {e}")

        return files
