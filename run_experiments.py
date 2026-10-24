"""Reproduce the submitted experiments, export observations, and draw figures."""
import argparse
import csv
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from src.fat_tree import FatTreeTopology
from src.failure_model import FailureModel
from src.metrics import NetworkMetrics

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "results"


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if isinstance(value, float) and not math.isfinite(value)
                             else value for key, value in row.items()})


def draw_topology(output_dir):
    """Illustrate the actual generated k=4 graph, including every link."""
    graph = FatTreeTopology(4).graph
    positions, labels = {}, {}
    for node, data in graph.nodes(data=True):
        parts = node.split("_")
        layer = data["layer"]
        if layer == "core":
            j, i = int(parts[1][1:]), int(parts[2][1:])
            positions[node] = (2 + 4*(2*j+i), 4)
            labels[node] = f"C{j}.{i}"
        else:
            p, index = int(parts[1][1:]), int(parts[2][1:])
            if layer == "host":
                host = int(parts[3][1:])
                positions[node] = (4*p + 0.5 + 2*index + host, 0)
                labels[node] = f"h{p}.{index}.{host}"
            else:
                positions[node] = (4*p + 1 + 2*index, 2.5 if layer == "aggregation" else 1.3)
                labels[node] = f"{'A' if layer == 'aggregation' else 'E'}{p}.{index}"
    fig, ax = plt.subplots(figsize=(14, 5.5), dpi=180)
    nx.draw_networkx_edges(graph, positions, ax=ax, edge_color="#8b959e", width=1, alpha=0.7)
    for layer, color, shape in [
        ("core", "#35618c", "s"), ("aggregation", "#638bad", "s"),
        ("edge", "#acc5d9", "s"), ("host", "#e8ecef", "o"),
    ]:
        nodes = [n for n, data in graph.nodes(data=True) if data["layer"] == layer]
        nx.draw_networkx_nodes(graph, positions, nodelist=nodes, node_color=color,
                               node_shape=shape, node_size=800 if layer != "host" else 650,
                               edgecolors="#35434c", ax=ax)
        nx.draw_networkx_labels(graph, positions, labels={n: labels[n] for n in nodes},
                                font_size=8, font_color="white" if layer in ["core", "aggregation"]
                                else "#152530", ax=ax)
    for p in range(4):
        ax.text(4*p+2, -0.55, f"Pod {p}", ha="center", fontsize=11)
    for y, label in [(4, "Core"), (2.5, "Aggregation"), (1.3, "Edge"), (0, "Hosts")]:
        ax.text(-0.7, y, label, ha="right", va="center", fontsize=10)
    ax.set_title("Generated k=4 Fat-tree: 16 hosts, 20 switches, 48 undirected links", pad=16)
    ax.set_xlim(-2.5, 16); ax.set_ylim(-0.8, 4.5); ax.axis("off")
    fig.tight_layout()
    fig.savefig(output_dir / "topology_k4.png")
    plt.close(fig)


def run_and_plot_experiments(iterations=None, output_dir=DEFAULT_OUTPUT, include_host_links=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rates = [round(x, 3) for x in np.linspace(0, 0.25, 11)]
    settings = [(4, iterations if iterations is not None else 15, 100),
                (6, iterations if iterations is not None else 10, 200)]
    results, all_trials, summaries = {}, [], []
    for k, count, seed in settings:
        print(f"[*] k={k}: {count} trials per rate; base seed={seed}")
        data = NetworkMetrics.run_failure_simulation(
            k, rates, count, seed, include_host_links=include_host_links)
        results[k] = data
        all_trials.extend(data["trials"])
        total_links = 3*k**3 // 4
        eligible_links = len(FailureModel.get_failable_links(
            FatTreeTopology(k).graph, include_host_links))
        for i, rate in enumerate(rates):
            summaries.append({
                "k": k, "requested_failure_fraction": rate,
                "failure_scope": "all-links" if include_host_links else "fabric-only",
                "include_host_links": include_host_links,
                "eligible_links": eligible_links,
                "actual_failed_fraction": data["actual_failure_rates"][i],
                "fraction_of_all_links_removed": int(eligible_links*rate) / total_links,
                "removed_links": int(eligible_links*rate), "total_links": total_links,
                "trials": count, "valid_path_trials": data["valid_path_trials"][i],
                "avg_path_length": data["avg_path_lengths"][i],
                "path_length_std": data["path_length_stds"][i],
                "reachability": data["reachabilities"][i],
                "reachability_std": data["reachability_stds"][i],
            })
    write_csv(output_dir / "trials.csv", all_trials)
    write_csv(output_dir / "summary.csv", summaries)
    metadata = {
        "model": "uniform fixed-count removal without replacement over the eligible link pool",
        "failure_scope": "all-links" if include_host_links else "fabric-only",
        "include_host_links": include_host_links,
        "eligible_link_types": ["agg-edge", "core-agg", "edge-host"] if include_host_links
                               else ["agg-edge", "core-agg"],
        "rounding": "floor(requested_failure_fraction * eligible_links)",
        "actual_failed_fraction_denominator": "eligible_links",
        "plot_x_axis": "requested percentage of eligible links; actual fractions are in the CSV files",
        "failure_rates": rates,
        "settings": [{"k": k, "iterations_per_rate": count, "base_seed": seed,
                      "eligible_links": 3*k**3//4 if include_host_links else k**3//2,
                      "total_links": 3*k**3//4}
                     for k, count, seed in settings],
        "seed_schedule": "base_seed + int(requested_failure_fraction * 1000) + iteration",
        "aggregation": "equal-weight mean of per-trial means; undefined path means omitted",
        "error_bars": "plus/minus one sample standard deviation across trials (ddof=1)",
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ["networkx", "matplotlib", "numpy"]},
    }
    (output_dir / "experiment.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    for key, sd_key, scale, ylabel, title, filename in [
        ("avg_path_lengths", "path_length_stds", 1, "Mean shortest path (hops; connected host pairs)",
         "Conditional host-to-host shortest path under link failures", "path_length_vs_failure.png"),
        ("reachabilities", "reachability_stds", 100, "Reachable unordered host pairs (%)",
         "Host-pair reachability under link failures", "reachability_vs_failure.png"),
    ]:
        fig, ax = plt.subplots(figsize=(9, 5.5), dpi=220)
        for (k, count, _), marker, linestyle in zip(settings, ["o", "s"], ["-", "--"]):
            data = results[k]
            spread = [scale*v if math.isfinite(v) else 0 for v in data[sd_key]]
            ax.errorbar([r*100 for r in data["failure_rates"]],
                        [scale*v for v in data[key]], yerr=spread, marker=marker,
                        linestyle=linestyle, linewidth=1.8, capsize=3,
                        label=f"k={k} ({k**3//4} hosts; {count} trials/rate)")
        ax.set_title(title, pad=12)
        ax.set_xlabel("Requested failed fraction of eligible links (%)")
        ax.set_ylabel(ylabel)
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend(fontsize=9)
        scope_label = "All links including host access" if include_host_links else "Fabric links only; host access protected"
        fig.text(0.5, 0.015, scope_label + ". Counts use floor(f * eligible links). Bars: +/- 1 sample SD.",
                 ha="center", fontsize=8)
        fig.tight_layout(rect=(0, 0.045, 1, 1))
        fig.savefig(output_dir / filename)
        plt.close(fig)
    draw_topology(output_dir)
    print(f"[+] Saved plots, topology, raw trials, summary and settings to {output_dir}")
    return results


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("iterations must be >= 1")
    return number


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=positive_int,
                        help="Override trials per rate for BOTH k values (default: 15 for k=4, 10 for k=6)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="Output folder (default: results next to this script)")
    parser.add_argument("--include-host-links", action=argparse.BooleanOptionalAction, default=False,
                        help="Also fail host access links (default: fabric links only)")
    args = parser.parse_args()
    run_and_plot_experiments(args.iterations, args.output_dir, args.include_host_links)
