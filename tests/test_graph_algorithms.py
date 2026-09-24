from __future__ import annotations

from graph_tools.algorithms import (
    connected_component,
    degree_centrality,
    shared_neighbors,
    shortest_path,
)

NODES = [
    {"type": "Transaction", "id": "T1"},
    {"type": "Card", "id": "C1"},
    {"type": "DeviceProfile", "id": "D1"},
    {"type": "Transaction", "id": "T2"},
    {"type": "Transaction", "id": "T3"},
]
EDGES = [
    {"source_type": "Transaction", "source": "T1", "type": "PAID_WITH", "target_type": "Card", "target": "C1"},
    {"source_type": "Transaction", "source": "T1", "type": "FROM_DEVICE", "target_type": "DeviceProfile", "target": "D1"},
    {"source_type": "Transaction", "source": "T2", "type": "FROM_DEVICE", "target_type": "DeviceProfile", "target": "D1"},
    {"source_type": "Transaction", "source": "T3", "type": "FROM_DEVICE", "target_type": "DeviceProfile", "target": "D1"},
]


def test_component_and_shortest_path_are_deterministic_and_include_edges() -> None:
    component = connected_component(list(reversed(NODES)), list(reversed(EDGES)), "Transaction", "T1")
    assert component["size"] == 5
    assert component["node_type_counts"] == {"Card": 1, "DeviceProfile": 1, "Transaction": 3}
    assert component["scope"] == "returned_relation_set"
    assert component["edges"] == connected_component(NODES, EDGES, "Transaction", "T1")["edges"]

    path = shortest_path(NODES, list(reversed(EDGES)), "Transaction", "T1", "Transaction", "T3")
    assert path["reachable"] is True
    assert path["distance"] == 2
    assert [node["id"] for node in path["path"]] == ["T1", "D1", "T3"]
    assert [edge["type"] for edge in path["edges"]] == ["FROM_DEVICE", "FROM_DEVICE"]


def test_shared_neighbors_and_centrality_only_use_supplied_relations() -> None:
    result = shared_neighbors(NODES, EDGES, "Transaction", "T1", "Transaction", "T2")
    assert result["shared_keys"] == ["DeviceProfile:D1"]

    missing = shared_neighbors(NODES, EDGES, "Transaction", "missing", "Transaction", "T2")
    assert missing["shared"] == []
    assert "error" in missing

    ranking = degree_centrality(NODES, EDGES)["ranking"]
    assert ranking[0]["node"]["id"] == "D1"
    assert ranking[0]["degree"] == 3
