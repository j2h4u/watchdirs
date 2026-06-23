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
        dominated_ancestors, suppressed_ancestor_counts = _dominated_ancestor_index(scope_candidates)

        surviving = [candidate for candidate in scope_candidates if candidate.path not in dominated_ancestors]
        suppressed_descendant_counts, retained_paths = _suppressed_descendant_index(surviving)
        for candidate in surviving:
            if candidate.path not in retained_paths:
                continue
            suppressed_descendant_count = suppressed_descendant_counts.get(candidate.path, 0)
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


def _dominated_ancestor_index(scope_candidates: list[DiffRow]) -> tuple[set[bytes], dict[bytes, int]]:
    candidate_by_path = {candidate.path: candidate for candidate in scope_candidates}
    best_descendant_by_ancestor: dict[bytes, DiffRow] = {}
    for descendant in scope_candidates:
        ancestor_path = _parent_of(descendant.path)
        while ancestor_path is not None:
            ancestor = candidate_by_path.get(ancestor_path)
            if (
                ancestor is not None
                and descendant.disk_bytes_delta >= ancestor.disk_bytes_delta * FRONTIER_DOMINANCE_RATIO
            ):
                best_descendant_by_ancestor.setdefault(ancestor.path, descendant)
            ancestor_path = _parent_of(ancestor_path)

    suppressed_ancestor_counts: dict[bytes, int] = {}
    for descendant in best_descendant_by_ancestor.values():
        suppressed_ancestor_counts[descendant.path] = suppressed_ancestor_counts.get(descendant.path, 0) + 1
    return set(best_descendant_by_ancestor), suppressed_ancestor_counts


def _suppressed_descendant_index(surviving: list[DiffRow]) -> tuple[dict[bytes, int], set[bytes]]:
    retained_by_path: dict[bytes, DiffRow] = {}
    retained_order_by_path: dict[bytes, int] = {}
    retained_paths: set[bytes] = set()
    suppressed_descendant_counts: dict[bytes, int] = {}

    for order, candidate in enumerate(surviving):
        suppressor_path = _first_retained_suppressing_ancestor(
            candidate,
            retained_by_path=retained_by_path,
            retained_order_by_path=retained_order_by_path,
        )
        if suppressor_path is not None:
            suppressed_descendant_counts[suppressor_path] = suppressed_descendant_counts.get(suppressor_path, 0) + 1
            continue

        retained_by_path[candidate.path] = candidate
        retained_order_by_path[candidate.path] = order
        retained_paths.add(candidate.path)

    return suppressed_descendant_counts, retained_paths


def _first_retained_suppressing_ancestor(
    candidate: DiffRow,
    *,
    retained_by_path: dict[bytes, DiffRow],
    retained_order_by_path: dict[bytes, int],
) -> bytes | None:
    best_path: bytes | None = None
    best_order: int | None = None
    ancestor_path = _parent_of(candidate.path)
    while ancestor_path is not None:
        ancestor = retained_by_path.get(ancestor_path)
        if ancestor is not None and candidate.disk_bytes_delta < ancestor.disk_bytes_delta * FRONTIER_DOMINANCE_RATIO:
            order = retained_order_by_path[ancestor_path]
            if best_order is None or order < best_order:
                best_path = ancestor_path
                best_order = order
        ancestor_path = _parent_of(ancestor_path)
    return best_path


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


def _parent_of(path_bytes: bytes) -> bytes | None:
    if path_bytes in (b"", b"/"):
        return None
    stripped = path_bytes.rstrip(b"/")
    head, sep, _tail = stripped.rpartition(b"/")
    if sep == b"":
        return None
    return head if head != b"" else b"/"


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
    max_depth = target.depth + depth
    rendered_children: list[DiffRow] = []
    shown_immediate: list[DiffRow] = []
    for child in immediate_children:
        if len(rendered_children) >= limit:
            break
        shown_immediate.append(child)
        rendered_children.append(child)
        if depth <= 1:
            continue
        remaining_slots = limit - len(rendered_children)
        if remaining_slots <= 0:
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
            )[:remaining_slots]
        )

    shown_disk_delta = sum(row.disk_bytes_delta for row in shown_immediate)
    shown_apparent_delta = sum(row.apparent_bytes_delta for row in shown_immediate)
    return ExplainPathResult(
        target=target,
        children=tuple(rendered_children),
        unshown_or_direct_disk_bytes_delta=target.disk_bytes_delta - shown_disk_delta,
        unshown_or_direct_apparent_bytes_delta=target.apparent_bytes_delta - shown_apparent_delta,
    )
