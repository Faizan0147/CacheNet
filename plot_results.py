"""Turn bench.py results into the R6 graphs and one combined table.

    python plot_results.py                      # newest raw CSV for every label in results/
    python plot_results.py results/bench_wifi_*_raw.csv results/bench_wired_*_raw.csv

Reads the *_raw.csv files (every run), so the charts show the mean as a bar,
the standard deviation as an error bar, and each individual run as a dot.
Writes PNGs and r6_summary.csv to results/plots/.
"""

import csv
import glob
import os
import re
import statistics
import sys
from collections import OrderedDict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.join("results", "plots")

# Categorical slots in fixed order (validated light-mode palette): dataset 1 blue, dataset 2 orange, ...
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"]
INK, INK_2, GRID = "#1f1f1e", "#52514e", "#e6e5e0"


def pick_files(args):
    if args:
        return args
    newest = {}
    for path in sorted(glob.glob(os.path.join("results", "bench_*_raw.csv"))):
        m = re.match(r"bench_(.+)_(\d{8}_\d{6})_raw\.csv$", os.path.basename(path))
        if m:
            newest[m.group(1)] = path  # sorted by name, so the last one per label is the newest
    return list(newest.values())


def load(paths):
    """{label: {(test, condition): {"ms": [...], "bytes": [...]}}} in file order."""
    data = OrderedDict()
    for path in paths:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                cell = data.setdefault(row["label"], OrderedDict()).setdefault(
                    (row["test"], row["condition"]), {"ms": [], "bytes": []})
                cell["ms"].append(float(row["time_ms"]))
                cell["bytes"].append(int(row["bytes"] or 0))
    return data


def stats_of(values):
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def mbps(cell):
    return [b * 8 / (ms / 1000) / 1e6 for b, ms in zip(cell["bytes"], cell["ms"]) if ms > 0]


def grouped(data, rows, title, ylabel, filename, value=lambda c: c["ms"], note=None):
    """rows: list of (test, condition, x-axis label). One bar group per row, one bar per dataset."""
    labels = list(data)
    width = 0.8 / max(len(labels), 1)
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    for li, label in enumerate(labels):
        color = SERIES[li % len(SERIES)]
        for xi, (test, cond, _) in enumerate(rows):
            cell = data[label].get((test, cond))
            if not cell:
                continue
            vals = value(cell)
            s = stats_of(vals)
            x = xi - 0.4 + width * (li + 0.5)
            ax.bar(x, s["mean"], width * 0.86, color=color, alpha=0.9, zorder=2,
                   label=label if xi == 0 else None)
            ax.errorbar(x, s["mean"], yerr=s["stdev"], color=INK, capsize=3, lw=1, zorder=3)
            ax.scatter([x] * len(vals), vals, s=12, facecolor="white", edgecolor=INK, lw=0.7, zorder=4)
            ax.annotate(f"{s['mean']:.1f}", (x, max(s["mean"] + s["stdev"], s["max"])), xytext=(0, 5),
                        textcoords="offset points", ha="center", fontsize=7.5, color=INK_2)
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([r[2] for r in rows], fontsize=9, color=INK)
    ax.set_ylabel(ylabel, fontsize=9, color=INK_2)
    ax.set_title(title, fontsize=11, color=INK, loc="left")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#b9b8b2")
    ax.tick_params(colors=INK_2, labelsize=8)
    if len(labels) > 1:
        ax.legend(frameon=False, fontsize=8, title="Network condition", title_fontsize=8)
    caption = "Bar = mean, error bar = ±1 standard deviation, dots = individual runs."
    fig.text(0.01, 0.01, caption + (" " + note if note else ""), fontsize=7, color=INK_2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = os.path.join(OUT, filename)
    fig.savefig(path)
    plt.close(fig)
    print("wrote", path)


def main():
    paths = pick_files(sys.argv[1:])
    if not paths:
        raise SystemExit("No results/bench_*_raw.csv found. Run bench.py first.")
    print("datasets:", ", ".join(paths))
    data = load(paths)
    os.makedirs(OUT, exist_ok=True)

    grouped(data, [("Object /index.html", "MISS", "MISS (origin fetched)"),
                   ("Object /index.html", "HIT", "HIT (served from cache)")],
            "Small object /index.html: cache MISS vs HIT", "Response time (ms)", "r6_small_object_miss_hit.png",
            note="Each request opens a new TCP connection.")
    grouped(data, [("Throughput /large.txt", "MISS", "MISS"), ("Throughput /large.txt", "HIT", "HIT")],
            "Large object /large.txt (~200 KB): transfer time", "Transfer time (ms)", "r6_large_object_time.png")
    grouped(data, [("Throughput /large.txt", "MISS", "MISS"), ("Throughput /large.txt", "HIT", "HIT")],
            "Large object /large.txt: application throughput", "Throughput (Mbps)", "r6_throughput.png",
            value=mbps, note="Throughput = response bytes x 8 / transfer time.")
    grouped(data, [("Page fetch (4 objects)", "persistent, warm cache", "Keep-alive\nwarm cache"),
                   ("Page fetch (4 objects)", "non-persistent, warm cache", "Close after response\nwarm cache"),
                   ("Page fetch (4 objects)", "persistent, cold cache", "Keep-alive\ncold cache"),
                   ("Page fetch (4 objects)", "non-persistent, cold cache", "Close after response\ncold cache")],
            "Page fetch (4 objects): persistent vs non-persistent", "Page fetch time (ms)", "r6_page_fetch.png")
    grouped(data, [("TCP connect (~1 RTT)", "client->proxy", "TCP connect\n(SYN → SYN-ACK)"),
                   ("App RTT (HEAD, open conn)", "cached", "CNTP HEAD on\nopen connection")],
            "Round-trip time client → proxy", "Time (ms)", "r6_rtt.png")

    table = os.path.join(OUT, "r6_summary.csv")
    with open(table, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "test", "condition", "runs", "mean_ms", "median_ms", "stdev_ms",
                    "min_ms", "max_ms", "mean_bytes", "mean_mbps"])
        for label, cells in data.items():
            for (test, cond), cell in cells.items():
                s = stats_of(cell["ms"])
                b = statistics.mean(cell["bytes"])
                rate = statistics.mean(mbps(cell)) if b > 1000 else ""  # throughput only means something for large bodies
                w.writerow([label, test, cond, s["n"], round(s["mean"], 2), round(s["median"], 2),
                            round(s["stdev"], 2), round(s["min"], 2), round(s["max"], 2), round(b),
                            round(rate, 2) if rate != "" else ""])
    print("wrote", table)


if __name__ == "__main__":
    main()
