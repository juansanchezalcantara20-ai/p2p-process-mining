"""Shared chart styling: one quiet, consistent look for every static figure in the report.

Colours follow a validated categorical order (blue, orange, aqua, yellow) and are assigned by
entity, never by rank. Grids and axes are recessive; text uses ink colours, not series colours.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MUTED = "#a9a8a2"
CRITICAL = "#e34948"

CATEGORY_COLORS = {
    "3-way match, invoice before GR": SERIES[0],
    "3-way match, invoice after GR": SERIES[1],
    "Consignment": SERIES[2],
    "2-way match": SERIES[3],
}


def setup() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "axes.titleweight": "bold",
            "axes.titlesize": 12,
            "axes.titlelocation": "left",
            "axes.labelsize": 10,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "font.family": "DejaVu Sans",
            "lines.linewidth": 2,
        }
    )


def save(fig: plt.Figure, path: Path, source: str = "Source: BPI Challenge 2019 event log") -> Path:
    fig.text(0.01, 0.005, source, fontsize=7.5, color=INK_2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def hbar(ax, labels, values, color=SERIES[0], fmt="{:,.0f}", highlight=None):
    """Horizontal bars, largest on top, with selective value labels at the bar end."""
    labels, values = list(labels)[::-1], list(values)[::-1]
    colors = [color] * len(values)
    if highlight is not None:
        colors = [color if h else MUTED for h in list(highlight)[::-1]]
    ax.barh(labels, values, color=colors, height=0.62, edgecolor=SURFACE, linewidth=1)
    ax.grid(axis="y", visible=False)
    vmax = max(values) if values else 1
    for i, v in enumerate(values):
        ax.text(v + vmax * 0.01, i, fmt.format(v), va="center", fontsize=8.5, color=INK_2)
    ax.set_xlim(0, vmax * 1.15)
    ax.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    return ax


setup()
