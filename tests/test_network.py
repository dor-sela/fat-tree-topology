"""Regression checks against graph invariants, closed forms and a BFS oracle."""
from collections import deque
import math
from pathlib import Path
import random
import subprocess
import sys
import unittest

import networkx as nx

from src.failure_model import FailureModel
from src.fat_tree import FatTreeTopology
from src.metrics import NetworkMetrics


class NetworkTests(unittest.TestCase):
    def test_structure_and_baseline_formula(self):
        for k in [2, 4, 6, 8, 12]:
            with self.subTest(k=k):
                graph = FatTreeTopology(k).graph
                h, hosts = k//2, k**3//4
                self.assertEqual(graph.number_of_nodes(), hosts + 5*k*k//4)
                self.assertEqual(graph.number_of_edges(), 3*k**3//4)
                for node, data in graph.nodes(data=True):
                    self.assertEqual(graph.degree(node), 1 if data['layer'] == 'host' else k)
                for j in range(h):
                    for i in range(h):
                        self.assertEqual(set(graph[f'core_j{j}_i{i}']),
                                         {f'agg_p{p}_a{j}' for p in range(k)})
                expected = (2*(h-1)+4*h*(h-1)+6*h*h*(k-1))/(hosts-1)
                values = NetworkMetrics.evaluate_host_communication(graph)
                self.assertAlmostEqual(values['avg_path_length'], expected)
                self.assertEqual(values['reachability'], 1)

    def test_failure_count_reproducibility_and_no_mutation(self):
        graph = FatTreeTopology(4).graph
        original_edges = set(graph.edges())
        random.seed(321)
        state = random.getstate()
        for include_host_links, pool_size in [(False, 32), (True, 48)]:
            for rate in [0, 0.01, 0.1, 0.25, 1]:
                failed, removed = FailureModel.inject_link_failures(
                    graph, rate, 123, include_host_links=include_host_links)
                _, repeated = FailureModel.inject_link_failures(
                    graph, rate, 123, include_host_links=include_host_links)
                self.assertEqual(removed, repeated)
                self.assertEqual(len(removed), int(pool_size*rate))
                self.assertEqual(failed.number_of_edges(), 48-len(removed))
        self.assertEqual(set(graph.edges()), original_edges)
        self.assertEqual(random.getstate(), state)

    def test_independent_bfs_on_failed_snapshots(self):
        for k in [2, 4, 6]:
            for include_host_links in [False, True]:
                for rate in [0, 0.1, 0.25, 0.8, 1]:
                    graph, _ = FailureModel.inject_link_failures(
                        FatTreeTopology(k).graph, rate, 45, include_host_links=include_host_links)
                    hosts = NetworkMetrics.get_host_nodes(graph)
                    distances = []
                    for i, source in enumerate(hosts):
                        lengths, queue = {source: 0}, deque([source])
                        while queue:
                            node = queue.popleft()
                            for neighbor in graph[node]:
                                if neighbor not in lengths:
                                    lengths[neighbor] = lengths[node]+1
                                    queue.append(neighbor)
                        distances.extend(lengths[h] for h in hosts[i+1:] if h in lengths)
                    actual = NetworkMetrics.evaluate_host_communication(graph)
                    self.assertEqual(actual['reachable_pairs'], len(distances))
                    self.assertEqual(actual['total_pairs'], len(hosts)*(len(hosts)-1)//2)
                    self.assertAlmostEqual(actual['reachability'], len(distances)/actual['total_pairs'])
                    if distances:
                        self.assertAlmostEqual(actual['avg_path_length'], sum(distances)/len(distances))
                    else:
                        self.assertTrue(math.isnan(actual['avg_path_length']))

    def test_default_protects_every_host_access_link(self):
        for k in [2, 4, 6]:
            graph = FatTreeTopology(k).graph
            failed, removed = FailureModel.inject_link_failures(graph, 1, seed=9)
            self.assertEqual(len(removed), k**3//2)
            self.assertEqual(failed.number_of_edges(), k**3//4)
            for u, v in removed:
                self.assertNotEqual(graph.nodes[u]['layer'], 'host')
                self.assertNotEqual(graph.nodes[v]['layer'], 'host')
            for host in NetworkMetrics.get_host_nodes(failed):
                self.assertEqual(failed.degree(host), 1)

    def test_empty_eligible_pool(self):
        graph = nx.Graph()
        graph.add_node('host', layer='host')
        graph.add_node('edge', layer='edge')
        graph.add_edge('host', 'edge')
        failed, removed = FailureModel.inject_link_failures(graph, 1, seed=1)
        self.assertEqual(removed, [])
        self.assertEqual(failed.number_of_edges(), 1)
        failed, removed = FailureModel.inject_link_failures(graph, 1, 1, include_host_links=True)
        self.assertEqual(len(removed), 1)
        self.assertEqual(failed.number_of_edges(), 0)

    def test_access_link_failure_stays_in_denominator(self):
        graph = FatTreeTopology(4).graph
        graph.remove_edge('host_p0_e0_h0', 'edge_p0_e0')
        values = NetworkMetrics.evaluate_host_communication(graph)
        self.assertEqual(values['reachable_pairs'], 15*14//2)
        self.assertEqual(values['total_pairs'], 16*15//2)
        self.assertEqual(values['reachability'], 0.875)

    def test_exact_single_link_failure_expectation(self):
        graph = FatTreeTopology(4).graph
        reachability_sum = 0
        for edge in list(graph.edges()):
            failed = graph.copy()
            failed.remove_edge(*edge)
            values = NetworkMetrics.evaluate_host_communication(failed)
            self.assertAlmostEqual(values['avg_path_length'], 82/15)
            reachability_sum += values['reachability']
        # 16/48 links are host access links; each such failure disconnects 15/120 pairs.
        self.assertAlmostEqual(reachability_sum/48, 1-(16/48)*(15/120))

    def test_every_single_fabric_link_failure_preserves_k4_metrics(self):
        graph = FatTreeTopology(4).graph
        eligible = FailureModel.get_failable_links(graph)
        self.assertEqual(len(eligible), 32)
        for edge in eligible:
            failed = graph.copy()
            failed.remove_edge(*edge)
            values = NetworkMetrics.evaluate_host_communication(failed)
            self.assertEqual(values['reachability'], 1)
            self.assertAlmostEqual(values['avg_path_length'], 82/15)

    def test_no_pairs_or_no_reachable_pairs(self):
        for hosts in [0, 1, 2]:
            graph = nx.Graph()
            graph.add_nodes_from((f'h{i}', {'layer': 'host'}) for i in range(hosts))
            values = NetworkMetrics.evaluate_host_communication(graph)
            self.assertTrue(math.isnan(values['avg_path_length']))
            self.assertEqual(values['reachability'], 1.0 if hosts < 2 else 0.0)
            self.assertEqual(values['reachable_pairs'], 0)

    def test_invalid_inputs(self):
        for k in [-2, 0, 1, 3, 4.0, True]:
            with self.assertRaises(ValueError):
                FatTreeTopology(k)
        graph = FatTreeTopology(4).graph
        for rate in [-0.1, 1.1, math.nan, math.inf]:
            with self.assertRaises(ValueError):
                FailureModel.inject_link_failures(graph, rate)
        for count in [0, -1, 1.5, True]:
            with self.assertRaises(ValueError):
                NetworkMetrics.run_failure_simulation(4, [0], count)

    def test_cli_rejects_invalid_rates_and_k(self):
        script = Path(__file__).resolve().parents[1] / 'main.py'
        for option, value in [('--failure-rate', '-0.1'), ('--failure-rate', 'nan'),
                              ('--failure-rate', '1.1'), ('--k', '3')]:
            run = subprocess.run([sys.executable, str(script), option, value], capture_output=True)
            self.assertEqual(run.returncode, 2, (option, value, run.stderr))

    def test_total_failure_simulation_has_no_false_zero_hops(self):
        data = NetworkMetrics.run_failure_simulation(4, [1], 3, 100, include_host_links=True)
        self.assertEqual(data['reachabilities'], [0.0])
        self.assertEqual(data['valid_path_trials'], [0])
        self.assertTrue(math.isnan(data['avg_path_lengths'][0]))
        self.assertEqual(len(data['trials']), 3)

    def test_complete_fabric_failure_keeps_same_edge_host_pairs(self):
        for k in [2, 4, 6]:
            graph, _ = FailureModel.inject_link_failures(FatTreeTopology(k).graph, 1, seed=8)
            values = NetworkMetrics.evaluate_host_communication(graph)
            expected_reachability = (k//2-1)/(k**3//4-1)
            self.assertAlmostEqual(values['reachability'], expected_reachability)
            if k == 2:
                self.assertTrue(math.isnan(values['avg_path_length']))
            else:
                self.assertEqual(values['avg_path_length'], 2)

    def test_simulation_records_scope_and_both_denominators(self):
        for include_host_links, eligible, removed in [(False, 32, 3), (True, 48, 4)]:
            data = NetworkMetrics.run_failure_simulation(
                4, [0.1], 1, 100, include_host_links=include_host_links)
            trial = data['trials'][0]
            self.assertEqual(trial['eligible_links'], eligible)
            self.assertEqual(trial['total_links'], 48)
            self.assertEqual(trial['removed_links'], removed)
            self.assertEqual(trial['include_host_links'], include_host_links)
            self.assertEqual(trial['failure_scope'], 'all-links' if include_host_links else 'fabric-only')
            self.assertEqual(trial['actual_failed_fraction'], removed/eligible)
            self.assertEqual(trial['fraction_of_all_links_removed'], removed/48)
            self.assertEqual(data['actual_failure_rates'], [removed/eligible])

    def test_cli_failure_scope(self):
        script = Path(__file__).resolve().parents[1] / 'main.py'
        cases = [([], 32, 3), (['--include-host-links'], 48, 4),
                 (['--include-host-links', '--no-include-host-links'], 32, 3)]
        for flags, eligible, removed in cases:
            run = subprocess.run([sys.executable, str(script), '--k', '4',
                                  '--failure-rate', '0.10', '--seed', '42', *flags],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn(f'Eligible links: {eligible} of 48 total', run.stdout)
            self.assertIn(f'Removed links: {removed}', run.stdout)


if __name__ == '__main__':
    unittest.main()
