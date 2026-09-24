"""Explainable graph algorithms used by the local and MCP graph tools.

The algorithms operate on entities and relations returned by a graph backend.
They never infer that two entities are connected merely because they look
similar.  A relation may be marked ``observed_path`` when a bounded GSQL path
query returned it, but its provenance is retained in the result.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterable


def node_key(node_type: str, identifier: Any) -> str:
    return f"{node_type}:{identifier}"


def _node_map(nodes: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = node.get("type") or node.get("node_type")
        identifier = node.get("id") if "id" in node else node.get("v_id")
        if ntype is None or identifier is None:
            continue
        item = dict(node)
        item["type"] = str(ntype)
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


def _adjacency(edges: Iterable[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, str], dict[str, Any]]]:
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in edges:
        if not isinstance(raw, dict):
            continue
        edge = dict(raw)
        ends = _edge_ends(edge)
        if ends is None:
            continue
        left, right = ends
        edge.setdefault("source", left.split(":", 1)[1])
        edge.setdefault("target", right.split(":", 1)[1])
        edge.setdefault("source_type", left.split(":", 1)[0])
        edge.setdefault("target_type", right.split(":", 1)[0])
        edge_map[(left, right)] = edge
        adjacency[left].append(edge)
        adjacency[right].append(edge)
    return adjacency, edge_map


def connected_component(
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    seed_type: str,
    seed_id: Any,
) -> dict[str, Any]:
    """Return the undirected component containing ``seed_type:seed_id``.

    The result is deterministic and bounded by the supplied relation set.  A
    ``truncated`` field is set by the backend when its graph query was bounded;
    this function never labels a partial ring as a global community.
    """
    node_map = _node_map(nodes)
    adjacency, edge_map = _adjacency(edges)
    seed = node_key(seed_type, seed_id)
    if seed not in node_map:
        return {
            "algorithm": "undirected_connected_component",
            "seed": {"type": str(seed_type), "id": str(seed_id)},
            "nodes": [], "edges": [], "size": 0, "node_type_counts": {},
            "scope": "returned_relation_set", "truncated": False,
            "error": "seed is not present in the supplied graph relation set",
        }
    visited: set[str] = {seed}
    queue: deque[str] = deque([seed])
    while queue:
        current = queue.popleft()
        for edge in adjacency.get(current, []):
            ends = _edge_ends(edge)
            if ends is None:
                continue
            neighbor = ends[1] if ends[0] == current else ends[0]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    component_edges = [
        edge for (left, right), edge in edge_map.items()
        if left in visited and right in visited
    ]
    component_nodes = [node_map[key] for key in sorted(visited) if key in node_map]
    type_counts: dict[str, int] = defaultdict(int)
    for node in component_nodes:
        type_counts[str(node.get("type"))] += 1
    return {
        "algorithm": "undirected_connected_component",
        "seed": {"type": str(seed_type), "id": str(seed_id)},
        "nodes": component_nodes,
        "edges": sorted(component_edges, key=lambda e: (
            str(e.get("source_type", "")), str(e.get("source", "")),
            str(e.get("type", "")), str(e.get("target_type", "")), str(e.get("target", "")),
        )),
        "size": len(component_nodes),
        "node_type_counts": dict(sorted(type_counts.items())),
        "scope": "returned_relation_set",
        "truncated": False,
    }


def shortest_path(
    nodes: Iterable[dict[str, Any]],
    edges: Iterable[dict[str, Any]],
    source_type: str,
    source_id: Any,
    target_type: str,
    target_id: Any,
) -> dict[str, Any]:
    """Breadth-first shortest path over supplied relations."""
    node_map = _node_map(nodes)
    adjacency, _ = _adjacency(edges)
    source = node_key(source_type, source_id)
    target = node_key(target_type, target_id)
    if source not in node_map or target not in node_map:
        return {
            "algorithm": "breadth_first_shortest_path",
            "source": {"type": source_type, "id": str(source_id)},
            "target": {"type": target_type, "id": str(target_id)},
            "reachable": False,
            "distance": None,
            "path": [],
            "provenance": "both endpoints must occur in the supplied graph relation set",
        }
    queue: deque[str] = deque([source])
    previous: dict[str, str] = {}
    seen = {source}
    while queue:
        current = queue.popleft()
        if current == target:
            break
        for edge in adjacency.get(current, []):
            ends = _edge_ends(edge)
            if ends is None:
                continue
            neighbor = ends[1] if ends[0] == current else ends[0]
            if neighbor not in seen:
                seen.add(neighbor)
                previous[neighbor] = current
                queue.append(neighbor)
    if target not in seen:
        return {
            "algorithm": "breadth_first_shortest_path",
            "source": {"type": source_type, "id": str(source_id)},
            "target": {"type": target_type, "id": str(target_id)},
            "reachable": False,
            "distance": None,
            "path": [],
            "provenance": "no path in the supplied relation set",
        }
    path_keys = [target]
    while path_keys[-1] != source:
        path_keys.append(previous[path_keys[-1]])
    path_keys.reverse()
    return {
        "algorithm": "breadth_first_shortest_path",
        "source": {"type": source_type, "id": str(source_id)},
        "target": {"type": target_type, "id": str(target_id)},
        "reachable": True,
        "distance": len(path_keys) - 1,
        "path": [node_map[key] for key in path_keys if key in node_map],
        "provenance": "edges are direct or explicitly marked observed_path relations returned by the graph backend",
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

    def neighbors(key: str) -> set[str]:
        result: set[str] = set()
        for edge in adjacency.get(key, []):
            ends = _edge_ends(edge)
            if ends is None:
                continue
            result.add(ends[1] if ends[0] == key else ends[0])
        result.discard(key)
        return result

    shared = sorted(neighbors(left) & neighbors(right))
    return {
        "algorithm": "shared_neighbors",
        "left": {"type": left_type, "id": str(left_id)},
        "right": {"type": right_type, "id": str(right_id)},
        "shared": [node_map[key] for key in shared if key in node_map],
        "shared_keys": shared,
        "count": len(shared),
    }
