import argparse
import networkx as nx
from src.fat_tree import FatTreeTopology
from src.failure_model import FailureModel


def even_k(value):
    k = int(value)
    if k < 2 or k % 2:
        raise argparse.ArgumentTypeError("k must be an even integer >= 2")
    return k


def failure_fraction(value):
    rate = float(value)
    if not 0.0 <= rate <= 1.0:
        raise argparse.ArgumentTypeError("failure-rate must be a finite fraction in [0, 1]")
    return rate


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Fat-Tree Topology Generation and Link Failure Simulation"
    )
    parser.add_argument(
        "--k",
        type=even_k,
        default=4,
        help="Switch port count (must be an even integer >= 2, default: 4)"
    )
    parser.add_argument(
        "--failure-rate",
        type=failure_fraction,
        default=0.0,
        help="Fraction of eligible links to fail (0.0 to 1.0; default: 0.0, fabric links only)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for failure modeling"
    )
    parser.add_argument(
        "--include-host-links",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Also allow host access links to fail (default: switch-to-switch links only)"
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()

    print(f"[*] Generating Fat-Tree topology with k={args.k}...")
    topology = FatTreeTopology(k=args.k)
    base_graph = topology.graph
    stats = topology.get_summary()

    print("\n--- Base Topology Statistics ---")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print(f"\n[*] Graph is initially connected: {nx.is_connected(base_graph)}")
    eligible_links = len(FailureModel.get_failable_links(base_graph, args.include_host_links))
    scope = "all links including host access" if args.include_host_links else "switch-to-switch fabric links only"
    print(f"[*] Failure scope: {scope}")
    print(f"  Eligible links: {eligible_links} of {base_graph.number_of_edges()} total")

    # Failure Injection
    if args.failure_rate > 0.0:
        print(f"\n[*] Injecting link failures (rate: {args.failure_rate * 100:.2f}%)...")
        failed_graph, removed_links = FailureModel.inject_link_failures(
            base_graph, args.failure_rate, seed=args.seed,
            include_host_links=args.include_host_links,
        )
        print(f"  Removed links: {len(removed_links)}")
        actual_fraction = len(removed_links) / eligible_links if eligible_links else 0.0
        print(f"  Actual failed fraction of eligible links: {actual_fraction:.6f}")
        print(f"  Fraction of all links removed: {len(removed_links) / base_graph.number_of_edges():.6f}")
        print(f"  Remaining links: {failed_graph.number_of_edges()}")
        print(f"  Graph remains connected: {nx.is_connected(failed_graph)}")
        print(f"  Connected components: {nx.number_connected_components(failed_graph)}")
    else:
        print("\n[*] No failures injected (failure-rate = 0.0).")


if __name__ == "__main__":
    main()
