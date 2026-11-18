"""Static SVG heatmap of games rising and falling across weeks (light + dark variants).

Rows: the most-mentioned games in the window, ordered by the week they peaked, so successive
waves of attention read as a diagonal. Columns: threads. Cell shade: commenters who named the
game that week (one blue ramp, binned). Each row's peak cell is labelled; every value is also in
the table under the chart, since GitHub renders these as images with no hover.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from .pipeline import WeekResult

FONT = 'system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'

# Bins over "commenters naming the game that week": (lower bound, label). 0 = empty cell.
BINS = [(1, "1"), (2, "2"), (3, "3–4"), (5, "5–7"), (8, "8+")]

THEMES = {
    "light": {
        "surface": "#fcfcfb", "empty": "#f0efec", "primary": "#0b0b0b", "secondary": "#52514e",
        "muted": "#898781", "rule": "#e1e0d9",
        # blue ramp steps 150 / 250 / 350 / 450 / 600: light -> dark as values grow
        "ramp": ["#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#184f95"],
        "ink_on_fill": ("#0b0b0b", "#ffffff"),
    },
    "dark": {
        "surface": "#1a1a19", "empty": "#262624", "primary": "#f0efec", "secondary": "#c3c2b7",
        "muted": "#898781", "rule": "#2c2c2a",
        # same ramp, own steps: 600 / 500 / 400 / 300 / 150, dark (recedes) -> bright as values grow
        "ramp": ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#b7d3f6"],
        "ink_on_fill": ("#0b0b0b", "#f0efec"),
    },
}

# Layout (px)
CELL_W, CELL_H, GAP = 40, 22, 2
LABEL_W, TOTAL_W, PAD = 236, 56, 16
HEAD_H, LEGEND_H = 44, 48
MAX_NAME = 34


@dataclass
class Grid:
    weeks: list[WeekResult]
    rows: list[tuple[str, list[int]]]  # (game name, mentioners per week)


def build_grid(window: list[WeekResult], top_n: int = 20) -> Grid:
    series: dict[str, list[int]] = {}
    names: dict[str, str] = {}
    for i, w in enumerate(window):
        for g in w.games:
            series.setdefault(g.key, [0] * len(window))[i] = g.mentioners
            names[g.key] = g.name
    # Most-mentioned overall (ties: name), then order by peak week, then by size of peak.
    top = sorted(series, key=lambda k: (-sum(series[k]), names[k].lower()))[:top_n]
    peak = lambda k: max(range(len(window)), key=lambda i: (series[k][i], -i))
    top.sort(key=lambda k: (peak(k), -max(series[k]), names[k].lower()))
    return Grid(window, [(names[k], series[k]) for k in top])


def _bin(v: int) -> int:
    """Index into the ramp for value v (v >= 1)."""
    return max(i for i, (lo, _) in enumerate(BINS) if v >= lo)


def _lum(hex_: str) -> float:
    def ch(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _ink(fill: str, inks: tuple[str, str]) -> str:
    return max(inks, key=lambda t: contrast(t, fill))


def _short(name: str) -> str:
    return name if len(name) <= MAX_NAME else name[: MAX_NAME - 1].rstrip() + "…"


def _day(w: WeekResult) -> str:
    from datetime import datetime
    d = datetime.fromisoformat(w.published)
    return f"{d.day} {d:%b}"


def svg(grid: Grid, mode: str) -> str:
    t = THEMES[mode]
    n_weeks, n_rows = len(grid.weeks), len(grid.rows)
    step_x, step_y = CELL_W + GAP, CELL_H + GAP
    plot_x, plot_y = PAD + LABEL_W, PAD + HEAD_H
    width = plot_x + n_weeks * step_x - GAP + TOTAL_W + PAD
    plot_h = n_rows * step_y - GAP
    height = plot_y + plot_h + LEGEND_H + PAD

    o: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family=\'{FONT}\' role="img">',
        f'<rect width="{width}" height="{height}" rx="8" fill="{t["surface"]}"/>',
    ]

    # Column headers: thread number + date
    for i, w in enumerate(grid.weeks):
        cx = plot_x + i * step_x + CELL_W / 2
        o.append(f'<text x="{cx}" y="{PAD + 16}" text-anchor="middle" font-size="12" '
                 f'fill="{t["secondary"]}" style="font-variant-numeric:tabular-nums">#{w.number}</text>')
        o.append(f'<text x="{cx}" y="{PAD + 32}" text-anchor="middle" font-size="11" '
                 f'fill="{t["muted"]}">{_day(w)}</text>')
    tx = plot_x + n_weeks * step_x - GAP + TOTAL_W - 4
    o.append(f'<text x="{tx}" y="{PAD + 32}" text-anchor="end" font-size="11" fill="{t["muted"]}">total</text>')

    # Rows
    for r, (name, vals) in enumerate(grid.rows):
        y = plot_y + r * step_y
        mid = y + CELL_H / 2 + 4.5
        o.append(f'<text x="{plot_x - 12}" y="{mid}" text-anchor="end" font-size="13" '
                 f'fill="{t["primary"]}">{escape(_short(name))}</text>')
        peak_i = max(range(n_weeks), key=lambda i: (vals[i], -i))
        for i, v in enumerate(vals):
            x = plot_x + i * step_x
            fill = t["ramp"][_bin(v)] if v else t["empty"]
            o.append(f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" rx="3" fill="{fill}"/>')
            if v and i == peak_i:
                o.append(f'<text x="{x + CELL_W / 2}" y="{mid}" text-anchor="middle" font-size="12" '
                         f'font-weight="600" fill="{_ink(fill, t["ink_on_fill"])}" '
                         f'style="font-variant-numeric:tabular-nums">{v}</text>')
        o.append(f'<text x="{tx}" y="{mid}" text-anchor="end" font-size="12" fill="{t["secondary"]}" '
                 f'style="font-variant-numeric:tabular-nums">{sum(vals)}</text>')

    # Legend: binned scale
    ly = plot_y + plot_h + 24
    o.append(f'<text x="{plot_x - 12}" y="{ly + 11}" text-anchor="end" font-size="12" '
             f'fill="{t["secondary"]}">Commenters naming it</text>')
    x = plot_x
    for (lo, label), fill in zip(BINS, t["ramp"]):
        o.append(f'<rect x="{x}" y="{ly}" width="{CELL_W}" height="14" rx="3" fill="{fill}"/>')
        o.append(f'<text x="{x + CELL_W / 2}" y="{ly + 30}" text-anchor="middle" font-size="11" '
                 f'fill="{t["secondary"]}">{label}</text>')
        x += step_x
    o.append(f'<text x="{x + 8}" y="{ly + 11}" font-size="11" fill="{t["muted"]}">'
             f'number = the game’s peak week · total = sum across weeks</text>')

    o.append("</svg>")
    return "\n".join(o) + "\n"


def table_md(grid: Grid) -> str:
    head = "| Game | " + " | ".join(f"#{w.number}" for w in grid.weeks) + " | Total |"
    sep = "|---|" + "--:|" * (len(grid.weeks) + 1)
    rows = [
        f"| {name.replace('|', '\\|')} | " + " | ".join(str(v) if v else "·" for v in vals) + f" | {sum(vals)} |"
        for name, vals in grid.rows
    ]
    return "\n".join([head, sep, *rows])
