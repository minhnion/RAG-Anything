from __future__ import annotations

from typing import Any

import networkx as nx


def _score_baseline(graph: nx.Graph) -> dict[Any, float]:
    degree = dict(graph.degree())
    try:
        pagerank = nx.pagerank(graph)
    except Exception:
        pagerank = {node: 0.0 for node in graph.nodes()}
    return {node: float(degree.get(node, 0)) + float(pagerank.get(node, 0)) for node in graph.nodes()}


def prune_baseline(graph: nx.Graph, max_nodes: int) -> nx.Graph:
    if max_nodes <= 0 or graph.number_of_nodes() <= max_nodes:
        return graph.copy()
    scores = _score_baseline(graph)
    keep = sorted(graph.nodes(), key=lambda node: scores.get(node, 0.0), reverse=True)[:max_nodes]
    return graph.subgraph(keep).copy()


def prune_hybrid(graph: nx.Graph, max_nodes: int) -> nx.Graph:
    if max_nodes <= 0 or graph.number_of_nodes() <= max_nodes:
        return graph.copy()

    degree = dict(graph.degree())
    max_degree = max(degree.values()) if degree else 1
    norm_degree = {node: degree.get(node, 0) / max_degree for node in graph.nodes()}

    try:
        betweenness = nx.betweenness_centrality(graph)
    except Exception:
        betweenness = norm_degree.copy()
    try:
        eigenvector = nx.eigenvector_centrality_numpy(graph)
    except Exception:
        eigenvector = norm_degree.copy()

    max_between = max(betweenness.values()) if betweenness else 1
    max_eigen = max(eigenvector.values()) if eigenvector else 1
    scores = {}
    for node in graph.nodes():
        b = betweenness.get(node, 0.0) / max_between if max_between else 0.0
        e = eigenvector.get(node, 0.0) / max_eigen if max_eigen else 0.0
        d = norm_degree.get(node, 0.0)
        scores[node] = 0.4 * b + 0.4 * e + 0.2 * d

    try:
        communities = list(nx.community.louvain_communities(graph, seed=42))
    except Exception:
        communities = [set(graph.nodes())]

    keep: set[Any] = set()
    total_nodes = max(sum(len(c) for c in communities), 1)
    for community in communities:
        slots = max(1, int(max_nodes * len(community) / total_nodes))
        ranked = sorted(community, key=lambda node: scores.get(node, 0.0), reverse=True)
        keep.update(ranked[:slots])

    for node in sorted(graph.nodes(), key=lambda node: scores.get(node, 0.0), reverse=True):
        if len(keep) >= max_nodes:
            break
        keep.add(node)

    if len(keep) > max_nodes:
        keep = set(sorted(keep, key=lambda node: scores.get(node, 0.0), reverse=True)[:max_nodes])
    return graph.subgraph(keep).copy()


class PruningService:
    PROFILE_ALGORITHMS = {
        "baseline_50": ("baseline", 50),
        "baseline_75": ("baseline", 75),
        "hybrid_50": ("hybrid", 50),
        "compact_30": ("baseline", 30),
        "media_aware_50": ("baseline", 50),
    }

    def resolve(self, profile: str | None, algorithm: str | None, max_nodes: int | None) -> tuple[str, int]:
        if profile and profile in self.PROFILE_ALGORITHMS:
            default_algorithm, default_max = self.PROFILE_ALGORITHMS[profile]
        else:
            default_algorithm, default_max = ("baseline", 50)
        return (algorithm or default_algorithm).lower(), int(max_nodes or default_max)

    def prune(
        self,
        graph: nx.Graph,
        *,
        profile: str | None = None,
        algorithm: str | None = None,
        max_nodes: int | None = None,
    ) -> nx.Graph:
        resolved_algorithm, resolved_max = self.resolve(profile, algorithm, max_nodes)
        if resolved_algorithm == "hybrid":
            return prune_hybrid(graph, resolved_max)
        return prune_baseline(graph, resolved_max)

