import random
import networkx as nx
from typing import Tuple, List


class FailureModel:
    """
    Applies failure scenarios (e.g., link perturbations) to a network topology.
    """

    @staticmethod
    def get_failable_links(
        graph: nx.Graph,
        include_host_links: bool = False,
    ) -> List[Tuple[str, str]]:
        """Return the eligible pool in graph order; host links are opt-in.

        Keeping graph order preserves the previous all-link seeded samples when
        include_host_links=True. Topology nodes identify hosts with layer='host'.
        """
        return [
            (u, v) for u, v in graph.edges()
            if include_host_links or (
                graph.nodes[u].get("layer") != "host"
                and graph.nodes[v].get("layer") != "host"
            )
        ]

    @staticmethod
    def inject_link_failures(
        graph: nx.Graph,
        failure_rate: float,
        seed: int = None,
        include_host_links: bool = False,
    ) -> Tuple[nx.Graph, List[Tuple[str, str]]]:
        """
        Remove floor(failure_rate * eligible_links) uniformly without replacement.
        :param graph: The original network topology graph.
        :param failure_rate: Fraction of the eligible pool to remove, in [0, 1].
        :param seed: Random seed for reproducibility.
        :param include_host_links: Also fail host access links; default is fabric only.
        :return: (failed_graph, list of removed edges)
        """
        if not (0.0 <= failure_rate <= 1.0):
            raise ValueError(f"failure_rate must be between 0.0 and 1.0, got {failure_rate}")

        failed_graph = graph.copy()
        eligible_links = FailureModel.get_failable_links(failed_graph, include_host_links)
        num_links_to_fail = int(len(eligible_links) * failure_rate)

        # Reproduce seeded runs without changing the caller's random generator.
        failed_edges = random.Random(seed).sample(eligible_links, num_links_to_fail)
        failed_graph.remove_edges_from(failed_edges)

        return failed_graph, failed_edges
