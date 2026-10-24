"""Host-pair metrics and reproducible fixed-count link-failure experiments."""
import math
from typing import Dict, List

import networkx as nx
import numpy as np

from src.fat_tree import FatTreeTopology
from src.failure_model import FailureModel


class NetworkMetrics:
    @staticmethod
    def get_host_nodes(graph: nx.Graph) -> List[str]:
        return [n for n, data in graph.nodes(data=True) if data.get("layer") == "host"]

    @staticmethod
    def evaluate_host_communication(graph: nx.Graph) -> Dict[str, float]:
        """Unordered distinct host pairs; undefined conditional path mean is NaN.

        Hosts whose access link fails remain in the reachability denominator.
        For fewer than two hosts, reachability is vacuously 1 and path mean is NaN.
        """
        hosts = NetworkMetrics.get_host_nodes(graph)
        total_pairs = len(hosts) * (len(hosts) - 1) // 2
        reachable_pairs = 0
        distance_sum = 0
        for i, source in enumerate(hosts):
            lengths = nx.single_source_shortest_path_length(graph, source)
            for target in hosts[i + 1:]:
                if target in lengths:
                    distance_sum += lengths[target]
                    reachable_pairs += 1
        return {
            "avg_path_length": distance_sum / reachable_pairs if reachable_pairs else math.nan,
            "reachability": reachable_pairs / total_pairs if total_pairs else 1.0,
            "reachable_pairs": reachable_pairs,
            "total_pairs": total_pairs,
        }

    @staticmethod
    def run_failure_simulation(
        k: int,
        failure_rates: List[float],
        iterations_per_rate: int = 15,
        base_seed: int = 42,
        include_host_links: bool = False,
    ) -> dict:
        """Equal-weight mean of per-trial means, not a pooled host-pair mean.

        The default pool contains fabric links only; host access links are opt-in.
        Keep the original seed schedule, while the new default pool changes results.
        Each rate starts from the intact graph, not the preceding failed graph.
        Standard deviations describe trial variability, not confidence intervals.
        """
        if (isinstance(iterations_per_rate, bool)
                or not isinstance(iterations_per_rate, int) or iterations_per_rate < 1):
            raise ValueError("iterations_per_rate must be a positive integer")
        if any(not 0 <= rate <= 1 for rate in failure_rates):
            raise ValueError("all failure rates must be finite fractions in [0, 1]")
        topology = FatTreeTopology(k)
        total_links = topology.graph.number_of_edges()
        eligible_links = len(FailureModel.get_failable_links(topology.graph, include_host_links))
        scope = "all-links" if include_host_links else "fabric-only"
        result = {key: [] for key in [
            "failure_rates", "actual_failure_rates", "avg_path_lengths", "reachabilities",
            "path_length_stds", "reachability_stds", "valid_path_trials", "trials",
        ]}
        for rate in failure_rates:
            paths, reachabilities = [], []
            for iteration in range(iterations_per_rate):
                seed = base_seed + int(rate * 1000) + iteration
                graph, removed = FailureModel.inject_link_failures(
                    topology.graph, rate, seed, include_host_links=include_host_links)
                values = NetworkMetrics.evaluate_host_communication(graph)
                if math.isfinite(values["avg_path_length"]):
                    paths.append(values["avg_path_length"])
                reachabilities.append(values["reachability"])
                result["trials"].append({
                    "k": k, "requested_failure_fraction": rate,
                    "failure_scope": scope, "include_host_links": include_host_links,
                    "eligible_links": eligible_links,
                    "actual_failed_fraction": len(removed) / eligible_links if eligible_links else 0.0,
                    "fraction_of_all_links_removed": len(removed) / total_links,
                    "iteration": iteration, "seed": seed,
                    "removed_links": len(removed), "total_links": total_links,
                    **values,
                })
            result["failure_rates"].append(rate)
            result["actual_failure_rates"].append(
                int(eligible_links * rate) / eligible_links if eligible_links else 0.0)
            result["avg_path_lengths"].append(float(np.mean(paths)) if paths else math.nan)
            result["reachabilities"].append(float(np.mean(reachabilities)))
            result["path_length_stds"].append(float(np.std(paths, ddof=1)) if len(paths) > 1 else math.nan)
            result["reachability_stds"].append(
                float(np.std(reachabilities, ddof=1)) if len(reachabilities) > 1 else math.nan)
            result["valid_path_trials"].append(len(paths))
        return result
