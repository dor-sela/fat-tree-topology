import networkx as nx
from typing import Dict, Any


class FatTreeTopology:
    """
    Generates a three-tier Fat-Tree network topology based on Al-Fares et al. (2008).
    """

    def __init__(self, k: int):
        if isinstance(k, bool) or not isinstance(k, int) or k % 2 != 0 or k < 2:
            raise ValueError(f"k must be an even positive integer, got {k}")
        self.k = k
        self.half_k = k // 2
        self.num_pods = k
        self.graph = nx.Graph()
        self._build_topology()

    def _build_topology(self) -> None:
        # 1. Build Pods (Edge switches, Aggregation switches, Hosts, and Pod internal links)
        for p in range(self.num_pods):
            for e in range(self.half_k):
                edge_id = f"edge_p{p}_e{e}"
                self.graph.add_node(edge_id, layer="edge", pod=p)

                # Connect Edge switch to k/2 Hosts
                for h in range(self.half_k):
                    host_id = f"host_p{p}_e{e}_h{h}"
                    self.graph.add_node(host_id, layer="host", pod=p)
                    self.graph.add_edge(edge_id, host_id, link_type="edge-host")

            for a in range(self.half_k):
                agg_id = f"agg_p{p}_a{a}"
                self.graph.add_node(agg_id, layer="aggregation", pod=p)

                # Connect all Edge switches in the pod to this Aggregation switch
                for e in range(self.half_k):
                    edge_id = f"edge_p{p}_e{e}"
                    self.graph.add_edge(agg_id, edge_id, link_type="agg-edge")

        # 2. Build Core layer and connect to Aggregation switches
        # Total core switches: (k/2)^2 organized in (k/2) groups of (k/2) switches
        for j in range(self.half_k):
            for i in range(self.half_k):
                core_id = f"core_j{j}_i{i}"
                self.graph.add_node(core_id, layer="core", group=j)

                # Each core switch connects to one aggregation switch per pod
                for p in range(self.num_pods):
                    agg_id = f"agg_p{p}_a{j}"
                    self.graph.add_edge(core_id, agg_id, link_type="core-agg")

    def get_summary(self) -> Dict[str, Any]:
        """Returns structural statistics of the generated topology."""
        nodes_by_layer = {"host": 0, "edge": 0, "aggregation": 0, "core": 0}
        for _, data in self.graph.nodes(data=True):
            layer = data.get("layer")
            if layer in nodes_by_layer:
                nodes_by_layer[layer] += 1

        return {
            "k": self.k,
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "hosts": nodes_by_layer["host"],
            "edge_switches": nodes_by_layer["edge"],
            "aggregation_switches": nodes_by_layer["aggregation"],
            "core_switches": nodes_by_layer["core"],
            "total_switches": (
                nodes_by_layer["edge"]
                + nodes_by_layer["aggregation"]
                + nodes_by_layer["core"]
            ),
        }
