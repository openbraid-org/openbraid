"""Unit tests for `_position_tree_dfs_order` (Phase E E4).

Covers:
- empty / no positions → empty
- no relationships → flat list in items[] order
- single tree → pre-order DFS
- multi-root → roots in items[] order, each subtree depth-first
- orphan positions → appended after reached positions, depth=0
- cycle → cycle members appear once each, broken by visited set
- "external:" / org-self / unknown endpoints in reports_to → ignored
- non-reports_to relationship types → ignored
- multiple reports_to for the same child → first-edge-wins
"""

from __future__ import annotations

from server.boot_url import _position_tree_dfs_order


def _pos(pid):
    return {"type": "orgdef:Position", "id": pid, "name": pid.title()}


def _ids_depths_parents(out):
    return [(p["id"], depth, parent) for p, depth, parent in out]


def test_empty_items_returns_empty():
    assert _position_tree_dfs_order({}) == []
    assert _position_tree_dfs_order({"items": []}) == []


def test_no_relationships_yields_items_order_flat():
    content = {
        "items": [_pos("a"), _pos("b"), _pos("c")],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    assert out == [("a", 0, None), ("b", 0, None), ("c", 0, None)]


def test_single_tree_emits_pre_order():
    content = {
        "items": [_pos("root"), _pos("child"), _pos("grandchild")],
        "relationships": [
            {"type": "reports_to", "from": "child", "to": "root"},
            {"type": "reports_to", "from": "grandchild", "to": "child"},
        ],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    assert out == [
        ("root", 0, None),
        ("child", 1, "root"),
        ("grandchild", 2, "child"),
    ]


def test_multi_root_emits_each_subtree():
    content = {
        "items": [_pos("root-a"), _pos("a-child"), _pos("root-b"), _pos("b-child")],
        "relationships": [
            {"type": "reports_to", "from": "a-child", "to": "root-a"},
            {"type": "reports_to", "from": "b-child", "to": "root-b"},
        ],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    assert out == [
        ("root-a", 0, None),
        ("a-child", 1, "root-a"),
        ("root-b", 0, None),
        ("b-child", 1, "root-b"),
    ]


def test_orphan_positions_appended_after_reached():
    """Positions that don't appear as `to` of any reports_to and that
    no reports_to leads to are still positions; they go at the end."""
    content = {
        "items": [_pos("root"), _pos("child"), _pos("orphan")],
        "relationships": [
            {"type": "reports_to", "from": "child", "to": "root"},
        ],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    # 'orphan' has no parent (so it's a root by our algorithm); it's
    # appended at the top level in items[] order — after the
    # reached tree.
    assert out == [
        ("root", 0, None),
        ("child", 1, "root"),
        ("orphan", 0, None),
    ]


def test_cycle_emits_each_member_once():
    """Pathological cycle: a→b→a. Visited-set prevents infinite loop;
    cycle members still appear (orphan-style, depth=0)."""
    content = {
        "items": [_pos("a"), _pos("b")],
        "relationships": [
            {"type": "reports_to", "from": "a", "to": "b"},
            {"type": "reports_to", "from": "b", "to": "a"},
        ],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    ids = [item[0] for item in out]
    assert sorted(ids) == ["a", "b"]
    # Both cycle members get appended as orphans (no node is a root
    # because each has a parent), depth=0, parent=None.
    for _, depth, parent in out:
        assert depth == 0
        assert parent is None


def test_external_and_org_self_endpoints_are_ignored():
    """Endpoints starting with 'external:' or matching the org id are
    not positions; reports_to entries pointing at them don't shape
    the tree."""
    content = {
        "id": "openbraid",
        "items": [_pos("director"), _pos("strategist")],
        "relationships": [
            {"type": "reports_to", "from": "strategist", "to": "director"},
            {"type": "coordinates_with", "from": "director", "to": "external:other-org"},
            {"type": "implements_for", "from": "openbraid", "to": "external:catdef-org"},
        ],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    assert out == [
        ("director", 0, None),
        ("strategist", 1, "director"),
    ]


def test_non_reports_to_relationship_types_are_ignored():
    content = {
        "items": [_pos("a"), _pos("b")],
        "relationships": [
            {"type": "coordinates_with", "from": "a", "to": "b"},
        ],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    assert out == [("a", 0, None), ("b", 0, None)]


def test_multiple_reports_to_for_same_child_first_edge_wins():
    content = {
        "items": [_pos("a"), _pos("b"), _pos("c")],
        "relationships": [
            {"type": "reports_to", "from": "c", "to": "a"},
            {"type": "reports_to", "from": "c", "to": "b"},
        ],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    # c reports to a (first edge); b becomes a root with no children.
    assert out == [
        ("a", 0, None),
        ("c", 1, "a"),
        ("b", 0, None),
    ]


def test_job_and_role_items_are_filtered_out():
    """Only orgdef:Position items appear in the tree walk."""
    content = {
        "items": [
            _pos("a"),
            {"type": "roledef:Job", "id": "a", "name": "Job for a"},
            {"type": "roledef:Role", "id": "some-role", "name": "Role"},
            _pos("b"),
        ],
        "relationships": [
            {"type": "reports_to", "from": "b", "to": "a"},
        ],
    }
    out = _ids_depths_parents(_position_tree_dfs_order(content))
    assert out == [
        ("a", 0, None),
        ("b", 1, "a"),
    ]
