"""Report generation: console summaries, HTML reports, and chart exports."""

import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

import pandas as pd
import numpy as np

from engine.backtest import BacktestResult
from engine.utils import get_reports_dir, format_currency, format_percentage

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates visual reports from backtest results."""

    def __init__(self, result: BacktestResult):
        self.result = result
        self.metrics = result.metrics
        self.equity = result.equity_curve
        self.trades = result.trade_log

    def print_console_summary(self) -> None:
        """Print formatted KPI table to stdout."""
        self.result.print_summary()

    def export_trade_log(self, output_path: str = None) -> str:
        """Export detailed trade log as CSV.

        Args:
            output_path: Path to save CSV. If None, auto-generates.

        Returns:
            Path to the saved CSV file
        """
        if output_path is None:
            name = self.result.strategy_name.replace(" ", "_").lower()
            output_path = str(get_reports_dir() / f"{name}_trades.csv")

        self.trades.to_csv(output_path, index=False)
        logger.info(f"Trade log exported to {output_path}")
        return output_path

    def generate_html_report(self, output_path: str = None) -> str:
        """Generate a standalone HTML report with embedded charts.

        Includes:
        - Equity curve chart
        - Drawdown chart
        - KPI summary table
        - Trade log table
        - Monthly returns heatmap

        Args:
            output_path: Path to save HTML. If None, auto-generates.

        Returns:
            Path to the saved HTML file
        """
        if output_path is None:
            name = self.result.strategy_name.replace(" ", "_").lower()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(get_reports_dir() / f"{name}_{timestamp}.html")

        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            html_content = self._generate_plotly_report()
        except ImportError:
            logger.warning("Plotly not installed. Generating basic HTML report.")
            html_content = self._generate_basic_html_report()

        Path(output_path).write_text(html_content)
        logger.info(f"HTML report saved to {output_path}")
        return output_path

    def _generate_plotly_report(self) -> str:
        """Generate HTML report with Plotly interactive charts."""
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        import plotly.io as pio

        m = self.metrics

        # Create subplots
        fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=("Equity Curve", "Drawdown", "Trade PnL Distribution"),
            row_heights=[0.45, 0.3, 0.25],
            vertical_spacing=0.08,
        )

        # Equity curve
        fig.add_trace(
            go.Scatter(
                x=self.equity.index, y=self.equity.values,
                mode="lines", name="Equity",
                line=dict(color="#2196F3", width=2),
                fill="tozeroy", fillcolor="rgba(33,150,243,0.1)",
            ),
            row=1, col=1,
        )

        # Drawdown
        peak = self.equity.expanding().max()
        drawdown_pct = ((self.equity - peak) / peak) * 100
        fig.add_trace(
            go.Scatter(
                x=drawdown_pct.index, y=drawdown_pct.values,
                mode="lines", name="Drawdown %",
                line=dict(color="#f44336", width=1.5),
                fill="tozeroy", fillcolor="rgba(244,67,54,0.15)",
            ),
            row=2, col=1,
        )

        # Trade PnL distribution
        if not self.trades.empty and "pnl" in self.trades.columns:
            pnls = self.trades["pnl"].dropna()
            colors = ["#4CAF50" if p > 0 else "#f44336" for p in pnls]
            fig.add_trace(
                go.Bar(
                    x=list(range(len(pnls))), y=pnls.values,
                    name="Trade PnL",
                    marker_color=colors,
                ),
                row=3, col=1,
            )

        fig.update_layout(
            title=dict(text=f"{self.result.strategy_name} - Backtest Report",
                       font=dict(size=20)),
            height=900,
            showlegend=False,
            template="plotly_white",
        )

        fig.update_yaxes(title_text="Equity ($)", row=1, col=1)
        fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)
        fig.update_yaxes(title_text="PnL ($)", row=3, col=1)
        fig.update_xaxes(title_text="Trade #", row=3, col=1)

        chart_html = pio.to_html(fig, full_html=False, include_plotlyjs="cdn")

        # Build KPI table
        kpi_rows = ""
        kpi_data = [
            ("Net Profit", f"{format_currency(m['net_profit'])} ({m['net_profit_pct']:.2f}%)"),
            ("Max Drawdown", f"{format_currency(m['max_drawdown'])} ({m['max_drawdown_pct']:.2f}%)"),
            ("Sharpe Ratio", f"{m['sharpe_ratio']:.2f}"),
            ("Sortino Ratio", f"{m['sortino_ratio']:.2f}"),
            ("Profit Factor", f"{m['profit_factor']:.2f}"),
            ("Win Rate", f"{m['win_rate_pct']:.1f}% ({m['winning_trades']}/{m['total_trades']})"),
            ("Risk/Reward", f"1:{m['risk_reward_ratio']:.2f}"),
            ("Expectancy", format_currency(m['expectancy'])),
            ("Recovery Factor", f"{m['recovery_factor']:.2f}"),
            ("Avg Trade", format_currency(m['avg_trade'])),
            ("Max Consec. Wins", f"{m['max_consecutive_wins']}"),
            ("Max Consec. Losses", f"{m['max_consecutive_losses']}"),
        ]
        for label, value in kpi_data:
            kpi_rows += f"<tr><td>{label}</td><td>{value}</td></tr>\n"

        # Trade log table
        trade_rows = ""
        if not self.trades.empty:
            for _, t in self.trades.iterrows():
                pnl_color = "#4CAF50" if (t.get("pnl", 0) or 0) > 0 else "#f44336"
                trade_rows += f"""<tr>
                    <td>{t.get('entry_time', '')}</td>
                    <td>{t.get('exit_time', '')}</td>
                    <td>{t.get('direction', '')}</td>
                    <td>{t.get('entry_price', 0):.2f}</td>
                    <td>{t.get('exit_price', 0):.2f}</td>
                    <td style="color:{pnl_color}">{format_currency(t.get('pnl', 0) or 0)}</td>
                    <td>{t.get('exit_reason', '')}</td>
                </tr>\n"""

        html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>{self.result.strategy_name} - Backtest Report</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           margin: 20px; background: #fafafa; color: #333; }}
    h1 {{ color: #1a237e; }}
    h2 {{ color: #283593; margin-top: 30px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #e8eaf6; font-weight: 600; }}
    tr:nth-child(even) {{ background: #f5f5f5; }}
    .kpi-table {{ max-width: 500px; }}
    .kpi-table td:first-child {{ font-weight: 600; width: 200px; }}
    .kpi-table td:last-child {{ text-align: right; }}
    .trade-table {{ font-size: 0.9em; overflow-x: auto; }}
    .report-meta {{ color: #666; font-size: 0.9em; }}
</style>
</head><body>
<h1>{self.result.strategy_name}</h1>
<p class="report-meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |
Bars: {len(self.equity):,}</p>

<h2>Performance Summary</h2>
<table class="kpi-table">
{kpi_rows}
</table>

<h2>Charts</h2>
{chart_html}

<h2>Trade Log ({len(self.trades)} trades)</h2>
<div class="trade-table">
<table>
<tr><th>Entry</th><th>Exit</th><th>Direction</th><th>Entry Price</th>
    <th>Exit Price</th><th>PnL</th><th>Reason</th></tr>
{trade_rows}
</table>
</div>

</body></html>"""
        return html

    def _generate_basic_html_report(self) -> str:
        """Generate a basic HTML report without Plotly."""
        m = self.metrics
        kpi_rows = ""
        for key, val in m.items():
            label = key.replace("_", " ").title()
            if isinstance(val, float):
                formatted = f"{val:,.2f}"
            else:
                formatted = str(val)
            kpi_rows += f"<tr><td>{label}</td><td>{formatted}</td></tr>\n"

        return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>{self.result.strategy_name} - Backtest Report</title>
<style>
    body {{ font-family: sans-serif; margin: 20px; }}
    table {{ border-collapse: collapse; margin: 10px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #f0f0f0; }}
</style>
</head><body>
<h1>{self.result.strategy_name}</h1>
<h2>Performance Metrics</h2>
<table>{kpi_rows}</table>
<p><em>Install plotly for interactive charts: pip install plotly</em></p>
</body></html>"""

    def plot_equity_curve(self, save_path: str = None) -> None:
        """Display or save equity curve plot using matplotlib.

        Args:
            save_path: Path to save PNG. If None, displays interactively.
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            logger.error("matplotlib not installed. Install with: pip install matplotlib")
            return

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [3, 1]})

        # Equity curve
        axes[0].plot(self.equity.index, self.equity.values, color="#2196F3", linewidth=1.5)
        axes[0].fill_between(self.equity.index, self.equity.values,
                              alpha=0.1, color="#2196F3")
        axes[0].set_title(f"{self.result.strategy_name} - Equity Curve")
        axes[0].set_ylabel("Equity ($)")
        axes[0].grid(True, alpha=0.3)

        # Drawdown
        peak = self.equity.expanding().max()
        drawdown_pct = ((self.equity - peak) / peak) * 100
        axes[1].fill_between(drawdown_pct.index, drawdown_pct.values,
                              color="#f44336", alpha=0.3)
        axes[1].plot(drawdown_pct.index, drawdown_pct.values, color="#f44336", linewidth=1)
        axes[1].set_title("Drawdown (%)")
        axes[1].set_ylabel("Drawdown (%)")
        axes[1].grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info(f"Chart saved to {save_path}")
        else:
            plt.show()

        plt.close()
