"""Render the measured trial points and medians; no simulated values."""

import argparse
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main(directory):
    rows = json.loads((directory / "tool-loop-trials.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.8), sharey=True)
    for axis, scenario, title in zip(
        axes,
        ["l3_only", "resident"],
        ["Verified L3-only prefix", "Resident prefix (negative control)"],
    ):
        for position, mode, color in [
            (0, "baseline", "#43658b"),
            (1, "proactive", "#209783"),
        ]:
            values = [
                r["continuation_ttft_ms"]
                for r in rows
                if r["scenario"] == scenario and r["mode"] == mode
            ]
            median = statistics.median(values)
            axis.bar(position, median, width=0.55, color=color, alpha=0.85)
            offsets = [
                position + (i - (len(values) - 1) / 2) * 0.1 for i in range(len(values))
            ]
            axis.scatter(offsets, values, color="#1b2430", s=25, zorder=3)
            axis.text(
                position, median + 15, f"{median:.0f} ms", ha="center", fontsize=11
            )
        axis.set_xticks([0, 1], ["Without ToolGap", "ToolGap"])
        axis.set_title(title, fontsize=11)
        axis.set_ylim(0, 650)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Continuation TTFT (ms)")
    fig.suptitle("Real model → document search → continuation", fontsize=15, y=0.98)
    fig.text(
        0.5,
        0.89,
        "Qwen2.5-1.5B • single L4 • 3520 saved tokens • file L3 • n=3/condition",
        ha="center",
        fontsize=10,
    )
    fig.text(
        0.5,
        0.03,
        "Bars: medians. Dots: every trial. Controlled cache eviction; OS page cache may be warm.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=[0, 0.08, 1, 0.85])
    fig.savefig(directory / "ttft.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    main(parser.parse_args().results)
