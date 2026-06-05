#!/usr/bin/env python3
"""
pipeline/scripts/visualize.py
==============================
Reads processed_data/report_*.json and renders chart PNGs into
pipeline/charts/output/{user_id}/*.png

Each chart function is standalone — call any one individually to re-render
a single chart without re-running the whole pipeline.

Art style contract (keep consistent across all charts):
  - Background:   #FFFFFF (light) / exported transparently for dark mode
  - Font:         DejaVu Sans (bundled with matplotlib) or system serif fallback
  - Colors:       per-cat accents defined in CAT_ACCENTS; gray palette for human data
  - Spine / grid: 0.3 alpha, color #888780
  - Line width:   1.5pt data lines, 0.5pt grid
  - Point size:   4pt markers, no edge color
  - No chart titles inside the figure (titles live in the Astro component)
  - DPI:          150 (web-optimised, crisp on retina)

Run:
  python3 pipeline/scripts/visualize.py
  python3 pipeline/scripts/visualize.py --user vanillaSky00 --chart trust_all
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent.parent
PROCESSED_DIR = ROOT / "pipeline" / "processed_data"
OUT_DIR = ROOT / "pipeline" / "charts" / "output"

# ── art style constants ───────────────────────────────────────────────────────
CAT_ACCENTS: dict[str, str] = {
    "mewi": "#888780",
    "miso": "#639922",
    "yuzu": "#BA7517",
    "haru": "#534AB7",
}
GRAY_PALETTE = ["#888780", "#B4B2A9", "#5F5E5A", "#444441", "#D3D1C7", "#2C2C2A"]
DPI = 150
BG = "#FFFFFF"
SPINE_COLOR = "#888780"
GRID_COLOR = "#888780"
LABEL_COLOR = "#5F5E5A"
TEXT_COLOR = "#2C2C2A"

RADAR_LABELS = ["Approach", "Retreat", "Offer item", "Wait / dwell", "Call out", "Pet attempt"]


def _apply_style(ax: plt.Axes, grid: bool = True) -> None:
    """Apply consistent art style to any axes object."""
    ax.set_facecolor(BG)
    ax.figure.patch.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_color(SPINE_COLOR)
        spine.set_linewidth(0.5)
    ax.tick_params(colors=LABEL_COLOR, labelsize=9, length=3, width=0.5)
    if grid:
        ax.grid(True, color=GRID_COLOR, alpha=0.25, linewidth=0.5, linestyle="-")
        ax.set_axisbelow(True)


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"  saved → {path.relative_to(ROOT)}")


# ── chart: trust all cats ─────────────────────────────────────────────────────

def chart_trust_all(data: dict, out_dir: Path) -> None:
    """Line chart: trust score per session for all four cats."""
    cats = data["cats"]
    sessions = list(range(1, data["meta"]["sessions"] + 1))

    fig, ax = plt.subplots(figsize=(7, 3.2))
    _apply_style(ax)

    for cat_id, cat in cats.items():
        arc = cat["trust_arc"]
        color = CAT_ACCENTS.get(cat_id, "#888780")
        ax.plot(sessions, arc, color=color, linewidth=1.5,
                marker="o", markersize=4, markeredgecolor="none",
                label=cat["name"])

    ax.set_xlim(0.7, len(sessions) + 0.3)
    ax.set_xticks(sessions)
    ax.set_xticklabels([f"S{s}" for s in sessions], color=LABEL_COLOR, fontsize=9)
    ax.set_ylabel("trust score", color=LABEL_COLOR, fontsize=9)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True, nbins=5))

    legend = ax.legend(
        frameon=False, fontsize=8, labelcolor=LABEL_COLOR,
        ncol=len(cats), loc="upper left",
        handlelength=1.2, handletextpad=0.4, columnspacing=1.0,
    )

    fig.tight_layout(pad=0.8)
    _save(fig, out_dir / "trust_all.png")


# ── chart: per-cat trust arc ──────────────────────────────────────────────────

def chart_trust_cat(data: dict, cat_id: str, out_dir: Path) -> None:
    """Line chart: trust arc for a single cat."""
    cat = data["cats"][cat_id]
    arc = cat["trust_arc"]
    sessions = list(range(1, len(arc) + 1))
    color = CAT_ACCENTS.get(cat_id, "#888780")

    fig, ax = plt.subplots(figsize=(4.5, 2.5))
    _apply_style(ax)

    ax.fill_between(sessions, arc, alpha=0.08, color=color)
    ax.plot(sessions, arc, color=color, linewidth=1.5,
            marker="o", markersize=4, markeredgecolor="none")

    ax.set_xlim(0.7, len(sessions) + 0.3)
    ax.set_xticks(sessions)
    ax.set_xticklabels([f"S{s}" for s in sessions], color=LABEL_COLOR, fontsize=9)
    ax.set_ylabel("trust", color=LABEL_COLOR, fontsize=9)
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True, nbins=4))
    ax.set_ylim(bottom=0)

    fig.tight_layout(pad=0.6)
    _save(fig, out_dir / f"trust_{cat_id}.png")


# ── chart: radar (hexagonal) ──────────────────────────────────────────────────

def chart_radar(data: dict, out_dir: Path) -> None:
    """Hexagonal radar chart of human action distribution."""
    radar = data["radar"]
    values = [radar.get(label, 0) for label in RADAR_LABELS]
    n = len(RADAR_LABELS)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    values_plot = values + [values[0]]
    angles_plot = angles + [angles[0]]

    fig, ax = plt.subplots(figsize=(4.5, 4.5), subplot_kw={"polar": True})
    ax.set_facecolor(BG)
    fig.patch.set_facecolor(BG)

    ax.plot(angles_plot, values_plot, color="#888780", linewidth=1.5, linestyle="-")
    ax.fill(angles_plot, values_plot, color="#888780", alpha=0.08)

    ax.set_xticks(angles)
    ax.set_xticklabels(RADAR_LABELS, color=LABEL_COLOR, fontsize=9)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], color=LABEL_COLOR, fontsize=7, alpha=0.6)
    ax.set_ylim(0, 100)

    ax.spines["polar"].set_color(SPINE_COLOR)
    ax.spines["polar"].set_linewidth(0.5)
    ax.grid(color=GRID_COLOR, alpha=0.2, linewidth=0.5)

    # mark data points
    for angle, val in zip(angles, values):
        ax.plot(angle, val, "o", color="#888780", markersize=4, markeredgecolor="none")

    fig.tight_layout(pad=0.5)
    _save(fig, out_dir / "radar_human_actions.png")


# ── chart: attention distribution ────────────────────────────────────────────

def chart_attention(data: dict, out_dir: Path) -> None:
    """Horizontal bar chart: attention % per cat."""
    att = data["attention_pct"]
    cats_data = data["cats"]
    cat_ids = [k for k in ["mewi", "miso", "yuzu", "haru"] if k in att]
    labels = [cats_data[k]["name"] for k in cat_ids]
    values = [att.get(k, 0) for k in cat_ids]
    colors = [CAT_ACCENTS.get(k, "#888780") for k in cat_ids]

    fig, ax = plt.subplots(figsize=(5, 2.5))
    _apply_style(ax, grid=False)

    bars = ax.barh(labels, values, color=colors, height=0.4)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{val}%", va="center", color=LABEL_COLOR, fontsize=9)

    ax.set_xlim(0, 110)
    ax.set_xlabel("attention %", color=LABEL_COLOR, fontsize=9)
    ax.tick_params(axis="y", color=LABEL_COLOR)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color=GRID_COLOR, alpha=0.2, linewidth=0.5)

    fig.tight_layout(pad=0.6)
    _save(fig, out_dir / "attention_dist.png")


# ── chart: attachment profile ─────────────────────────────────────────────────

def chart_attachment(data: dict, out_dir: Path) -> None:
    """Horizontal bar chart: attachment profile dimensions."""
    profile = data["attachment_profile"]
    labels = [d["label"] for d in profile]
    values = [d["value"] for d in profile]
    colors = [d["color"] for d in profile]

    fig, ax = plt.subplots(figsize=(6, 3.2))
    _apply_style(ax, grid=False)

    bars = ax.barh(labels, values, color=colors, height=0.45)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{val}%", va="center", color=LABEL_COLOR, fontsize=9)

    ax.set_xlim(0, 115)
    ax.invert_yaxis()
    ax.set_xlabel("score %", color=LABEL_COLOR, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color=GRID_COLOR, alpha=0.2, linewidth=0.5)

    fig.tight_layout(pad=0.6)
    _save(fig, out_dir / "attachment_profile.png")


# ── chart: trust bars per cat ─────────────────────────────────────────────────

def chart_trust_bars(data: dict, cat_id: str, out_dir: Path) -> None:
    """Horizontal bar chart: trust signal bars for a single cat."""
    cat = data["cats"][cat_id]
    bars_data = cat["bars"]
    labels = [b["label"] for b in bars_data]
    values = [b["value"] for b in bars_data]
    color = CAT_ACCENTS.get(cat_id, "#888780")

    fig, ax = plt.subplots(figsize=(5, 2.5))
    _apply_style(ax, grid=False)

    bars = ax.barh(labels, values, color=color, height=0.4, alpha=0.85)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{val}%", va="center", color=LABEL_COLOR, fontsize=9)

    ax.set_xlim(0, 115)
    ax.invert_yaxis()
    ax.set_xlabel("score %", color=LABEL_COLOR, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color=GRID_COLOR, alpha=0.2, linewidth=0.5)

    fig.tight_layout(pad=0.6)
    _save(fig, out_dir / f"trust_bars_{cat_id}.png")


# ── dispatcher ────────────────────────────────────────────────────────────────

CHART_MAP: dict[str, str] = {
    "trust_all":    "chart_trust_all",
    "radar":        "chart_radar",
    "attention":    "chart_attention",
    "attachment":   "chart_attachment",
}


def render_all(data: dict, out_dir: Path) -> None:
    chart_trust_all(data, out_dir)
    chart_radar(data, out_dir)
    chart_attention(data, out_dir)
    chart_attachment(data, out_dir)
    for cat_id in CAT_ACCENTS:
        if cat_id in data["cats"]:
            chart_trust_cat(data, cat_id, out_dir)
            chart_trust_bars(data, cat_id, out_dir)


def _matches_user_filter(fp: Path, user_filter: str) -> bool:
    if user_filter in fp.stem:
        return True

    try:
        with open(fp) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False

    user = data.get("user", {})
    candidates = {
        data.get("user_id", ""),
        user.get("display_name", ""),
        user.get("handle", ""),
        user.get("report_slug", ""),
    }
    needle = user_filter.lower()
    return any(needle in str(candidate).lower() for candidate in candidates)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Mewi report charts.")
    parser.add_argument("--user", default=None, help="Only render this user. Matches internal ID, display name, handle, or route slug.")
    parser.add_argument("--chart", default=None, help="Only render this chart key (trust_all | radar | attention | attachment | trust_<cat> | trust_bars_<cat>).")
    args = parser.parse_args()

    files = list(PROCESSED_DIR.glob("report_*.json"))
    if args.user:
        files = [f for f in files if _matches_user_filter(f, args.user)]

    if not files:
        print("No processed data files found. Post raw sessions to the backend report route first.")
        return

    for fp in files:
        with open(fp) as f:
            data = json.load(f)
        user_id = data["user_id"]
        user = data.get("user", {})
        display_name = user.get("display_name", user_id)
        out_dir = OUT_DIR / user.get("report_slug", user_id)
        print(f"\nRendering charts for {display_name} ({user_id}) → {out_dir.relative_to(ROOT)}")

        if args.chart:
            key = args.chart
            if key == "trust_all":
                chart_trust_all(data, out_dir)
            elif key == "radar":
                chart_radar(data, out_dir)
            elif key == "attention":
                chart_attention(data, out_dir)
            elif key == "attachment":
                chart_attachment(data, out_dir)
            elif key.startswith("trust_bars_"):
                chart_trust_bars(data, key.replace("trust_bars_", ""), out_dir)
            elif key.startswith("trust_"):
                chart_trust_cat(data, key.replace("trust_", ""), out_dir)
            else:
                print(f"  Unknown chart key: {key}")
        else:
            render_all(data, out_dir)


if __name__ == "__main__":
    main()
