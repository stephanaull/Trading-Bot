"""Shared utilities for formatting, paths, and logging."""

import os
import logging
from pathlib import Path


# Project root is the parent of engine/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_project_root() -> Path:
    """Get the project root directory."""
    return PROJECT_ROOT


def get_data_dir() -> Path:
    """Get the data directory path, creating it if needed."""
    path = PROJECT_ROOT / "data"
    path.mkdir(exist_ok=True)
    return path


def get_strategies_dir() -> Path:
    """Get the strategies directory path, creating it if needed."""
    path = PROJECT_ROOT / "strategies"
    path.mkdir(exist_ok=True)
    return path


def get_reports_dir() -> Path:
    """Get the reports directory path, creating it if needed."""
    path = PROJECT_ROOT / "reports"
    path.mkdir(exist_ok=True)
    return path


def get_export_dir() -> Path:
    """Get the export directory path, creating it if needed."""
    path = PROJECT_ROOT / "export"
    path.mkdir(exist_ok=True)
    return path


def format_currency(value: float) -> str:
    """Format a float as currency: $1,234.56"""
    if value >= 0:
        return f"${value:,.2f}"
    return f"-${abs(value):,.2f}"


def format_percentage(value: float) -> str:
    """Format a float as percentage: 12.34%"""
    return f"{value:.2f}%"


def format_number(value: float, decimals: int = 2) -> str:
    """Format a number with commas and decimal places."""
    return f"{value:,.{decimals}f}"


def format_metrics_table(metrics: dict, title: str = "Backtest Results") -> str:
    """Format a metrics dictionary as a pretty console table."""
    lines = []
    lines.append(f"\n{'=' * 50}")
    lines.append(f"  {title}")
    lines.append(f"{'=' * 50}")

    for key, value in metrics.items():
        label = key.replace("_", " ").title()
        if isinstance(value, float):
            if "pct" in key or "rate" in key or "return" in key or "drawdown" in key:
                formatted = format_percentage(value)
            elif "ratio" in key or "factor" in key or "expectancy" in key:
                formatted = format_number(value)
            else:
                formatted = format_currency(value)
        elif isinstance(value, int):
            formatted = f"{value:,}"
        else:
            formatted = str(value)

        lines.append(f"  {label:<30} {formatted:>18}")

    lines.append(f"{'=' * 50}\n")
    return "\n".join(lines)


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the engine."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
