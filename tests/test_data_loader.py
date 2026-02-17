"""Tests for the data loader module."""

import sys
import os
import pytest
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data_loader import DataLoader

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_CSV = os.path.join(FIXTURES_DIR, "sample_ohlcv.csv")


class TestDataLoader:
    def test_load_csv(self):
        df = DataLoader.from_csv(SAMPLE_CSV)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert "open" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_datetime_index(self):
        df = DataLoader.from_csv(SAMPLE_CSV)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == "date"

    def test_sorted_ascending(self):
        df = DataLoader.from_csv(SAMPLE_CSV)
        assert df.index.is_monotonic_increasing

    def test_no_nans_in_ohlcv(self):
        df = DataLoader.from_csv(SAMPLE_CSV)
        assert df[["open", "high", "low", "close", "volume"]].isna().sum().sum() == 0

    def test_validate_clean_data(self):
        df = DataLoader.from_csv(SAMPLE_CSV)
        warnings = DataLoader.validate(df)
        # Sample data should be clean
        high_low_warnings = [w for w in warnings if "high < low" in w]
        assert len(high_low_warnings) == 0

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            DataLoader.from_csv("nonexistent_file.csv")

    def test_resample(self):
        df = DataLoader.from_csv(SAMPLE_CSV)
        weekly = DataLoader.resample(df, "1w")
        assert len(weekly) < len(df)
        assert "open" in weekly.columns
        assert "close" in weekly.columns


class TestDataValidation:
    def test_negative_price_detection(self):
        df = pd.DataFrame({
            "open": [100, -50, 102],
            "high": [105, 55, 107],
            "low": [95, 45, 97],
            "close": [103, 52, 105],
            "volume": [1000, 1000, 1000],
        }, index=pd.date_range("2023-01-01", periods=3))

        warnings = DataLoader.validate(df)
        neg_warnings = [w for w in warnings if "negative" in w.lower()]
        assert len(neg_warnings) > 0

    def test_high_low_violation_detection(self):
        df = pd.DataFrame({
            "open": [100, 100],
            "high": [105, 95],   # Second bar: high < low
            "low": [95, 100],
            "close": [103, 98],
            "volume": [1000, 1000],
        }, index=pd.date_range("2023-01-01", periods=2))

        warnings = DataLoader.validate(df)
        hl_warnings = [w for w in warnings if "high < low" in w]
        assert len(hl_warnings) > 0
