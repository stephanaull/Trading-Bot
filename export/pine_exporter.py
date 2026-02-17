"""Python strategy to Pine Script v6 converter.

Converts strategy metadata into a valid Pine Script v6 file that can be
loaded directly into TradingView.

The exporter works from structured metadata that each strategy declares,
not from general-purpose Python-to-Pine transpilation.
"""

import logging
from pathlib import Path
from typing import Optional

from strategies.base_strategy import BaseStrategy
from export.pine_templates import (
    PINE_HEADER, PINE_FULL_TEMPLATE, PINE_INDICATORS,
    PINE_INPUT_INT, PINE_INPUT_FLOAT, PINE_INPUT_BOOL,
    PINE_ENTRY_LONG, PINE_ENTRY_SHORT, PINE_EXIT, PINE_CLOSE,
    PINE_CROSSOVER, PINE_CROSSUNDER,
)
from engine.utils import get_export_dir

logger = logging.getLogger(__name__)


class PineExporter:
    """Converts a Python strategy to Pine Script v6."""

    def __init__(self, strategy: BaseStrategy):
        self.strategy = strategy
        self.meta = strategy.get_pine_metadata()

    def export(self, output_path: str = None) -> str:
        """Generate a Pine Script v6 file from the strategy.

        Args:
            output_path: Path to save the .pine file. Auto-generates if None.

        Returns:
            Path to the saved .pine file
        """
        if output_path is None:
            name = self.meta["name"].replace(" ", "_").lower()
            version = self.meta["version"]
            output_path = str(get_export_dir() / f"{name}_{version}.pine")

        pine_code = self._generate()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(pine_code)

        logger.info(f"Pine Script exported to {output_path}")
        return output_path

    def _generate(self) -> str:
        """Generate the complete Pine Script code."""
        inputs = self._generate_inputs()
        indicators = self._generate_indicators()
        conditions = self._generate_conditions()
        entries = self._generate_entries()
        plots = self._generate_plots()

        # Use the full template
        code = PINE_FULL_TEMPLATE.format(
            name=self.meta["name"],
            overlay="true",
            qty_pct=10,
            commission=0.1,
            slippage=0,
            inputs=inputs if inputs else "// No custom inputs",
            indicators=indicators if indicators else "// No indicators defined",
            conditions=conditions if conditions else "// Conditions defined inline below",
            entries=entries if entries else "// TODO: Define entry/exit logic",
            plots=plots if plots else "// No plots",
        )

        return code

    def _generate_inputs(self) -> str:
        """Convert strategy params to Pine Script input declarations."""
        lines = []
        params = self.meta.get("params", {})

        for name, value in params.items():
            clean_name = name.replace("_", " ").title()

            if isinstance(value, bool):
                lines.append(f'{name} = ' + PINE_INPUT_BOOL.format(
                    default=str(value).lower(), title=clean_name))
            elif isinstance(value, int):
                lines.append(f'{name} = ' + PINE_INPUT_INT.format(
                    default=value, title=clean_name,
                    min=1, max=value * 10))
            elif isinstance(value, float):
                if value < 1:  # Likely a percentage
                    lines.append(f'{name} = ' + PINE_INPUT_FLOAT.format(
                        default=value, title=clean_name,
                        min=0.0, max=1.0, step=0.01))
                else:
                    lines.append(f'{name} = ' + PINE_INPUT_FLOAT.format(
                        default=value, title=clean_name,
                        min=0.0, max=value * 10, step=0.1))

        return "\n".join(lines)

    def _generate_indicators(self) -> str:
        """Convert indicator metadata to Pine Script ta.xxx() calls."""
        lines = []
        indicators = self.meta.get("indicators", [])

        for ind in indicators:
            name = ind.get("name", "").lower()
            params = ind.get("params", {})
            var = ind.get("var", f"{name}_val")

            template_info = PINE_INDICATORS.get(name)
            if template_info:
                code_template = template_info["code"]
                try:
                    code = code_template.format(var=var, **params)
                    lines.append(code)
                except KeyError as e:
                    lines.append(f"// TODO: Fix indicator {name} - missing param: {e}")
            else:
                lines.append(f"// TODO: Implement indicator: {name}({params})")

        return "\n".join(lines)

    def _generate_conditions(self) -> str:
        """Convert condition metadata to Pine Script conditions."""
        lines = []
        conditions = self.meta.get("conditions", {})

        for cond_name, cond_expr in conditions.items():
            clean_name = cond_name.replace("_", " ")
            lines.append(f"{cond_name} = {cond_expr}")

        return "\n".join(lines)

    def _generate_entries(self) -> str:
        """Generate strategy.entry() and strategy.exit() calls."""
        lines = []
        conditions = self.meta.get("conditions", {})
        params = self.meta.get("params", {})

        # Generate entry logic
        if "long_entry" in conditions:
            lines.append(f"if ({conditions['long_entry']})")
            lines.append(f'    strategy.entry("Long", strategy.long)')

            # Add stop/target if params exist
            stop_pct = params.get("stop_loss_pct")
            tp_pct = params.get("take_profit_pct")
            if stop_pct or tp_pct:
                stop_expr = f"close * (1 - {stop_pct})" if stop_pct else "na"
                tp_expr = f"close * (1 + {tp_pct})" if tp_pct else "na"
                lines.append(f'    strategy.exit("Long Exit", "Long", '
                             f'stop={stop_expr}, limit={tp_expr})')

        if "short_entry" in conditions:
            lines.append(f"if ({conditions['short_entry']})")
            lines.append(f'    strategy.entry("Short", strategy.short)')

            stop_pct = params.get("stop_loss_pct")
            tp_pct = params.get("take_profit_pct")
            if stop_pct or tp_pct:
                stop_expr = f"close * (1 + {stop_pct})" if stop_pct else "na"
                tp_expr = f"close * (1 - {tp_pct})" if tp_pct else "na"
                lines.append(f'    strategy.exit("Short Exit", "Short", '
                             f'stop={stop_expr}, limit={tp_expr})')

        # Generate exit logic
        if "long_exit" in conditions:
            lines.append(f"if ({conditions['long_exit']})")
            lines.append(f'    strategy.close("Long")')

        if "short_exit" in conditions:
            lines.append(f"if ({conditions['short_exit']})")
            lines.append(f'    strategy.close("Short")')

        if not lines:
            lines.append("// TODO: Define your entry and exit conditions")
            lines.append("// Example:")
            lines.append('// if (ta.crossover(fast_ema, slow_ema))')
            lines.append('//     strategy.entry("Long", strategy.long)')
            lines.append('// if (ta.crossunder(fast_ema, slow_ema))')
            lines.append('//     strategy.close("Long")')

        return "\n".join(lines)

    def _generate_plots(self) -> str:
        """Generate plot() calls for indicators."""
        lines = []
        indicators = self.meta.get("indicators", [])

        for ind in indicators:
            name = ind.get("name", "").lower()
            var = ind.get("var", f"{name}_val")

            template_info = PINE_INDICATORS.get(name)
            if template_info and template_info.get("plot"):
                title = f"{name.upper()} {ind.get('params', {}).get('length', '')}"
                plot_code = template_info["plot"].format(var=var, title=title.strip())
                lines.append(plot_code)

        return "\n".join(lines)

    def get_pine_code(self) -> str:
        """Return the Pine Script code as a string without saving to file."""
        return self._generate()
