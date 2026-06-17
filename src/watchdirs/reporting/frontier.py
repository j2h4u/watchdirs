from __future__ import annotations

from watchdirs.models import DiffRow, ExplainPathResult, FrontierRow

FRONTIER_DOMINANCE_RATIO = 0.95


def prune_growth_frontier(rows: tuple[DiffRow, ...] | list[DiffRow]) -> tuple[FrontierRow, ...]:
    positive_candidates = sorted(
        (row for row in rows if row.classification in {"created", "grown"} and row.disk_bytes_delta > 0),
        key=lambda row: (
            -row.disk_bytes_delta,
            -row.depth,
            row.root_path.as_posix().encode(),
            row.baseline_snapshot_id,
            row.current_snapshot_id,
            row.path,
        ),
    )

    candidates_by_scope: dict[tuple[str, int, int], list[DiffRow]] = {}
    for row in positive_candidates:
        key = (str(row.root_path), row.baseline_snapshot_id, row.current_snapshot_id)
        candidates_by_scope.setdefault(key, []).append(row)

    retained: list[FrontierRow] = []
    for scope_candidates in candidates_by_scope.values():
        dominated_ancestors: set[bytes] = set()
        suppressed_ancestor_counts: dict[bytes, int] = {}

        for ancestor in scope_candidates:
            dominating_descendants = [
                descendant
                for descendant in scope_candidates
                if _is_ancestor_path(ancestor.path, descendant.path)
                and descendant.disk_bytes_delta >= ancestor.disk_bytes_delta * FRONTIER_DOMINANCE_RATIO
            ]
            if not dominating_descendants:
                continue
            dominated_ancestors.add(ancestor.path)
            chosen_descendant = min(
                dominating_descendants,
                key=lambda row: (-row.disk_bytes_delta, -row.depth, row.path),
            )
            suppressed_ancestor_counts[chosen_descendant.path] = (
                suppressed_ancestor_counts.get(chosen_descendant.path, 0) + 1
            )

        surviving = [candidate for candidate in scope_candidates if candidate.path not in dominated_ancestors]
        suppressed_descendants: set[bytes] = set()
        for candidate in surviving:
            if candidate.path in suppressed_descendants:
                continue

            suppressed_descendant_count = 0
            for descendant in surviving:
                if descendant.path == candidate.path or descendant.path in suppressed_descendants:
                    continue
                if (
                    _is_ancestor_path(candidate.path, descendant.path)
                    and descendant.disk_bytes_delta < candidate.disk_bytes_delta * FRONTIER_DOMINANCE_RATIO
                ):
                    suppressed_descendants.add(descendant.path)
                    suppressed_descendant_count += 1

            retained.append(
                FrontierRow(
                    row=candidate,
                    suppressed_descendant_count=suppressed_descendant_count,
                    suppressed_ancestor_count=suppressed_ancestor_counts.get(candidate.path, 0),
                    reason=_reason_for_counts(
                        suppressed_descendant_count=suppressed_descendant_count,
                        suppressed_ancestor_count=suppressed_ancestor_counts.get(candidate.path, 0),
                    ),
                )
            )

    retained.sort(
        key=lambda entry: (
            -entry.row.disk_bytes_delta,
            -entry.row.depth,
            entry.row.path,
        )
    )
    return tuple(retained)


def _is_ancestor_path(ancestor: bytes, descendant: bytes) -> bool:
    if ancestor == descendant:
        return False
    if ancestor == b"/":
        return descendant.startswith(b"/")
    return descendant.startswith(ancestor + b"/")


def _reason_for_counts(*, suppressed_descendant_count: int, suppressed_ancestor_count: int) -> str:
    if suppressed_ancestor_count and suppressed_descendant_count:
        return "dominates near-duplicate ancestors while hiding lower-signal descendants"
    if suppressed_ancestor_count:
        return "dominates near-duplicate ancestors"
    if suppressed_descendant_count:
        return "suppresses lower-signal descendants"
    return "highest-signal growth target"


def explain_path_breakdown(
    rows: tuple[DiffRow, ...] | list[DiffRow],
    *,
    target_path: bytes,
    limit: int,
    depth: int,
) -> ExplainPathResult:
    target = next(row for row in rows if row.path == target_path)
    if depth == 0:
        return ExplainPathResult(
            target=target,
            children=(),
            unshown_or_direct_disk_bytes_delta=target.disk_bytes_delta,
            unshown_or_direct_apparent_bytes_delta=target.apparent_bytes_delta,
        )

    descendants = [
        row
        for row in rows
        if row.path != target_path and row.classification != "unchanged" and _is_ancestor_path(target_path, row.path)
    ]
    immediate_children = sorted(
        (row for row in descendants if row.parent_path == target_path),
        key=lambda row: (-row.disk_bytes_delta, -row.apparent_bytes_delta, row.path),
    )
    shown_immediate = immediate_children[:limit]

    max_depth = target.depth + depth
    rendered_children: list[DiffRow] = []
    for child in shown_immediate:
        rendered_children.append(child)
        if depth <= 1:
            continue
        rendered_children.extend(
            sorted(
                (
                    row
                    for row in descendants
                    if row.parent_path != target_path
                    and row.depth <= max_depth
                    and _is_ancestor_path(child.path, row.path)
                ),
                key=lambda row: (row.depth, row.path),
            )
        )

    shown_disk_delta = sum(row.disk_bytes_delta for row in shown_immediate)
    shown_apparent_delta = sum(row.apparent_bytes_delta for row in shown_immediate)
    return ExplainPathResult(
        target=target,
        children=tuple(rendered_children),
        unshown_or_direct_disk_bytes_delta=target.disk_bytes_delta - shown_disk_delta,
        unshown_or_direct_apparent_bytes_delta=target.apparent_bytes_delta - shown_apparent_delta,
    )
