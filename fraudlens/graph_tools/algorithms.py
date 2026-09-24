"""Deterministic, explainable algorithms over a bounded graph result.

Algorithms treat supplied relations as undirected evidence.  They never infer a
connection from similar attributes.  Results state that scope explicitly so a
bounded two-hop ring is not mislabeled as a global community.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Iterable
from typing import Any


def node_key(node_type: str, identifier: Any) -> str:
    """Return the stable typed key used in algorithm output."""
    return f"{node_type}:{identifier}"


def _node_map(nodes: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        node_type = raw.get("type") or raw.get("node_type")
        identifier = raw.get("id") if "id" in raw else raw.get("v_id")
        if node_type is None or identifier is None:
            continue
        item = dict(raw)
        item["type"] = str(node_type)
        item["id"] = str(identifier)
        result[node_key(item["type"], item["id"])] = item
    return result


def _edge_ends(edge: dict[str, Any]) -> tuple[str, str] | None:
    source = edge.get("source") if "source" in edge else edge.get("from")
    target = edge.get("target") if "target" in edge else edge.get("to")
    source_type = edge.get("source_type") or edge.get("from_type")
    target_type = edge.get("target_type") or edge.get("to_type")
    if source is None or target is None or source_type is None or target_type is None:
        return None
    return node_key(str(source_type), source), node_key(str(target_type), target)


def _normalise_edge(raw: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    if not isinstance(raw, dict):
        return None
    edge = dict(raw)
    ends = _edge_ends(edge)
    if ends is None:
        return None
    left, right = ends
    # Parse the typed keys once, without splitting IDs that may contain ':'.
    left_type, left_id = left.split(":", 1)
    right_type, right_id = right.split(":", 1)
    edge.setdefault("source", left_id)
    edge.setdefault("target", right_id)
    edge.setdefault("source_type", left_type)
    edge.setdefault("target_type", right_type)
    return left, right, edge


def _edge_identity(left: str, right: str, edge: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in edge.items()
        if key not in {"source", "target", "source_type", "target_type", "type", "relation"}
    }
    return json.dumps(
        [left, right, str(edge.get("type", "")), payload],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _adjacency(
    edges: Iterable[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in edges:
        normalised = _normalise_edge(raw)
        if normalised is None:
            continue
        left, right, edge = normalised
        identity = _edge_identity(left, right, edge)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(edge)
        adjacency[left].append(edge)
        adjacency[right].append(edge)
    for key in adjacency:
        adjacency[key].sort(
            key=lambda edge: (
                str(edge.get("type", "")),
                str(edge.get("target_type", "")),
                str(edge.get("target", "")),
                str(edge.get("source_type", "")),
                str(edge.get("source", "")),
            )
        )
    return adjacency, unique


def _neighbour(current: str, left: str, right: str) -> str:
    if left == current:
        return right
    if right == current:
        return left
    return current


def connected_component(
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    seed_type: str,
    seed_id: Any,
) -> dict[str, Any]:
    """Return the component containing ``seed_type:seed_id``."""
    node_map = _node_map(nodes)
    adjacency, unique_edges = _adjacency(edges)
    seed = node_key(seed_type, seed_id)
    if seed not in node_map:
        return {
            "algorithm": "undirected_connected_component",
            "seed": {"type": str(seed_type), "id": str(seed_id)},
            "nodes": [],
            "edges": [],
            "size": 0,
            "node_type_counts": {},
            "scope": "returned_relation_set",
            "truncated": False,
            "error": "seed is not present in the supplied graph relation set",
        }

    visited = {seed}
    queue: deque[str] = deque([seed])
    while queue:
        current = queue.popleft()
        for edge in adjacency.get(current, []):
            ends = _edge_ends(edge)
            if ends is None:
                continue
            left, right = ends
            neighbour = _neighbour(current, left, right)
            if neighbour in node_map and neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)

    component_edges = [
        edge
        for edge in unique_edges
        if (ends := _edge_ends(edge)) is not None
        and ends[0] in visited
        and ends[1] in visited
        and ends[0] in node_map
        and ends[1] in node_map
    ]
    component_nodes = [node_map[key] for key in sorted(visited)]
    type_counts: dict[str, int] = defaultdict(int)
    for node in component_nodes:
        type_counts[str(node.get("type"))] += 1
    return {
        "algorithm": "undirected_connected_component",
        "seed": {"type": str(seed_type), "id": str(seed_id)},
        "nodes": component_nodes,
        "edges": sorted(component_edges, key=_edge_sort_key),
        "size": len(component_nodes),
        "node_type_counts": dict(sorted(type_counts.items())),
        "scope": "returned_relation_set",
        "truncated": False,
    }


def _edge_sort_key(edge: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(edge.get("source_type", "")),
        str(edge.get("source", "")),
        str(edge.get("type", "")),
        str(edge.get("target_type", "")),
        str(edge.get("target", "")),
    )


def shortest_path(
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    source_type: str,
    source_id: Any,
    target_type: str,
    target_id: Any,
) -> dict[str, Any]:
    """Return a deterministic breadth-first path and its observed edges."""
    node_map = _node_map(nodes)
    adjacency, _ = _adjacency(edges)
    source = node_key(source_type, source_id)
    target = node_key(target_type, target_id)
    base = {
        "algorithm": "breadth_first_shortest_path",
        "source": {"type": str(source_type), "id": str(source_id)},
        "target": {"type": str(target_type), "id": str(target_id)},
    }
    if source not in node_map or target not in node_map:
        return {
            **base,
            "reachable": False,
            "distance": None,
            "path": [],
            "edges": [],
            "provenance": "both endpoints must occur in the supplied graph relation set",
        }

    queue: deque[str] = deque([source])
    previous: dict[str, tuple[str, dict[str, Any]]] = {}
    seen = {source}
    while queue:
        current = queue.popleft()
        if current == target:
            break
        for edge in adjacency.get(current, []):
            ends = _edge_ends(edge)
            if ends is None:
                continue
            neighbour = _neighbour(current, *ends)
            if neighbour in node_map and neighbour not in seen:
                seen.add(neighbour)
                previous[neighbour] = (current, edge)
                queue.append(neighbour)
    if target not in seen:
        return {
            **base,
            "reachable": False,
            "distance": None,
            "path": [],
            "edges": [],
            "provenance": "no path in the supplied relation set",
        }

    path_keys = [target]
    path_edges: list[dict[str, Any]] = []
    while path_keys[-1] != source:
        parent, edge = previous[path_keys[-1]]
        path_edges.append(edge)
        path_keys.append(parent)
    path_keys.reverse()
    path_edges.reverse()
    return {
        **base,
        "reachable": True,
        "distance": len(path_keys) - 1,
        "path": [node_map[key] for key in path_keys],
        "edges": path_edges,
        "provenance": "edges are direct or explicitly observed relations returned by the graph backend",
    }


def shared_neighbors(
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    left_type: str,
    left_id: Any,
    right_type: str,
    right_id: Any,
) -> dict[str, Any]:
    """Return the actual intersection of two nodes' one-hop neighborhoods."""
    node_map = _node_map(nodes)
    adjacency, _ = _adjacency(edges)
    left = node_key(left_type, left_id)
    right = node_key(right_type, right_id)
    result: dict[str, Any] = {
        "algorithm": "shared_neighbors",
        "left": {"type": left_type, "id": str(left_id)},
        "right": {"type": right_type, "id": str(right_id)},
        "shared": [],
        "shared_keys": [],
        "count": 0,
    }
    if left not in node_map or right not in node_map:
        result["error"] = "both endpoints must occur in the supplied graph relation set"
        return result

    def neighbours(key: str) -> set[str]:
        found: set[str] = set()
        for edge in adjacency.get(key, []):
            ends = _edge_ends(edge)
            if ends is not None:
                found.add(_neighbour(key, *ends))
        found.discard(key)
        return found

    shared = sorted(neighbours(left) & neighbours(right))
    result.update(
        {
            "shared": [node_map[key] for key in shared if key in node_map],
            "shared_keys": shared,
            "count": len(shared),
        }
    )
    return result


def degree_centrality(
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Return deterministic undirected degree scores for supplied nodes."""
    node_map = _node_map(nodes)
    _, unique_edges = _adjacency(edges)
    scores: dict[str, int] = {key: 0 for key in node_map}
    for edge in unique_edges:
        ends = _edge_ends(edge)
        if ends is None or ends[0] not in scores or ends[1] not in scores:
            continue
        scores[ends[0]] += 1
        if ends[1] != ends[0]:
            scores[ends[1]] += 1
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    denominator = max(1, len(scores) - 1)
    return {
        "algorithm": "undirected_degree_centrality",
        "ranking": [
            {
                "node": node_map[key],
                "degree": degree,
                "centrality": round(degree / denominator, 8),
            }
            for key, degree in ordered
        ],
        "scope": "returned_relation_set",
    }
