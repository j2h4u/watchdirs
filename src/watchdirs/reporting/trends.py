from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from math import sqrt
from pathlib import Path

MIN_CLASSIFIABLE_SAMPLES = 3
STEADY_GROWTH_INTERVAL_RATIO = 0.6
NEGATIVE_TO_POSITIVE_STEADY_MAX_RATIO = 0.2
ONE_TIME_JUMP_DOMINANCE_RATIO = 0.75
GROW_THEN_CLEAN_NEGATIVE_RATIO = 0.5
MATERIAL_DELTA_FLOOR_BYTES = 1
MATERIAL_DELTA_CURRENT_RATIO = 0.01


class GrowthShape(StrEnum):
    STEADY_GROWTH = "steady_growth"
    ONE_TIME_JUMP = "one_time_jump"
    BURSTY_GROWTH = "bursty_growth"
    GROW_THEN_CLEAN = "grow_then_clean"
    CURRENT_BURST_AFTER_LATEST_SNAPSHOT = "current_burst_after_latest_snapshot"
    STABLE_LARGE = "stable_large"
    UNKNOWN_INSUFFICIENT_SAMPLES = "unknown_insufficient_samples"


@dataclass(frozen=True, slots=True)
class TrendSample:
    snapshot_id: int
    finished_at: datetime
    disk_bytes: int
    apparent_bytes: int


@dataclass(frozen=True, slots=True)
class TrendMetrics:
    samples: tuple[TrendSample, ...]
    start_disk_bytes: int | None
    end_disk_bytes: int | None
    net_disk_bytes_delta: int
    gross_positive_disk_bytes_delta: int
    gross_negative_disk_bytes_delta: int
    first_observed_at: datetime | None
    first_nonzero_at: datetime | None
    last_growth_at: datetime | None
    peak_disk_bytes: int | None
    daily_slope_disk_bytes: float | None
    volatility_disk_bytes: float
    sample_count: int
    missing_sample_count: int
    shape: GrowthShape


@dataclass(frozen=True, slots=True)
class PathTrend:
    root_path: Path
    path: bytes
    path_bytes_hex: str
    parent_path: bytes | None
    depth: int
    snapshot_ids: tuple[int, ...]
    snapshot_statuses: tuple[str, ...]
    metrics: TrendMetrics


@dataclass(frozen=True, slots=True)
class _ShapeInputs:
    samples: tuple[TrendSample, ...]
    deltas: tuple[int, ...]
    gross_positive: int
    gross_negative: int
    net_delta: int
    peak_disk_bytes: int | None
    material_delta: int


@dataclass(frozen=True, slots=True)
class _SteadyGrowthInputs:
    positive_interval_count: int
    interval_count: int
    gross_positive: int
    gross_negative: int
    net_delta: int
    material_delta: int


def analyze_trend(
    samples: Sequence[TrendSample],
    *,
    expected_sample_count: int | None = None,
) -> TrendMetrics:
    ordered_samples = tuple(sorted(samples, key=lambda sample: (sample.finished_at, sample.snapshot_id)))
    sample_count = len(ordered_samples)
    missing_sample_count = _missing_sample_count(sample_count, expected_sample_count)
    start_disk_bytes = ordered_samples[0].disk_bytes if ordered_samples else None
    end_disk_bytes = ordered_samples[-1].disk_bytes if ordered_samples else None
    deltas = _disk_deltas(ordered_samples)
    gross_positive = sum(delta for delta in deltas if delta > 0)
    gross_negative = sum(-delta for delta in deltas if delta < 0)
    net_delta = 0 if start_disk_bytes is None or end_disk_bytes is None else end_disk_bytes - start_disk_bytes
    peak_disk_bytes = max((sample.disk_bytes for sample in ordered_samples), default=None)
    material_delta = _material_delta_threshold(peak_disk_bytes)
    shape = _classify_shape(
        _ShapeInputs(
            samples=ordered_samples,
            deltas=deltas,
            gross_positive=gross_positive,
            gross_negative=gross_negative,
            net_delta=net_delta,
            peak_disk_bytes=peak_disk_bytes,
            material_delta=material_delta,
        )
    )

    return TrendMetrics(
        samples=ordered_samples,
        start_disk_bytes=start_disk_bytes,
        end_disk_bytes=end_disk_bytes,
        net_disk_bytes_delta=net_delta,
        gross_positive_disk_bytes_delta=gross_positive,
        gross_negative_disk_bytes_delta=gross_negative,
        first_observed_at=ordered_samples[0].finished_at if ordered_samples else None,
        first_nonzero_at=_first_nonzero_at(ordered_samples),
        last_growth_at=_last_growth_at(ordered_samples, deltas=deltas, material_delta=material_delta),
        peak_disk_bytes=peak_disk_bytes,
        daily_slope_disk_bytes=_daily_slope(ordered_samples),
        volatility_disk_bytes=_volatility(deltas),
        sample_count=sample_count,
        missing_sample_count=missing_sample_count,
        shape=shape,
    )


def _classify_shape(inputs: _ShapeInputs) -> GrowthShape:
    shape = GrowthShape.STABLE_LARGE
    if len(inputs.samples) < MIN_CLASSIFIABLE_SAMPLES or inputs.peak_disk_bytes is None:
        shape = GrowthShape.UNKNOWN_INSUFFICIENT_SAMPLES
    elif inputs.gross_positive < inputs.material_delta and inputs.gross_negative < inputs.material_delta:
        shape = GrowthShape.STABLE_LARGE
    elif _is_grow_then_clean(
        inputs.gross_positive,
        inputs.gross_negative,
        inputs.net_delta,
        inputs.peak_disk_bytes,
        inputs.samples[-1].disk_bytes,
    ):
        shape = GrowthShape.GROW_THEN_CLEAN
    elif _is_one_time_jump(inputs.deltas, inputs.gross_positive):
        shape = GrowthShape.ONE_TIME_JUMP
    elif _is_steady_growth(
        _SteadyGrowthInputs(
            positive_interval_count=sum(1 for delta in inputs.deltas if delta >= inputs.material_delta),
            interval_count=len(inputs.deltas),
            gross_positive=inputs.gross_positive,
            gross_negative=inputs.gross_negative,
            net_delta=inputs.net_delta,
            material_delta=inputs.material_delta,
        )
    ):
        shape = GrowthShape.STEADY_GROWTH
    elif inputs.gross_positive >= inputs.material_delta:
        shape = GrowthShape.BURSTY_GROWTH
    return shape


def _is_grow_then_clean(
    gross_positive: int,
    gross_negative: int,
    net_delta: int,
    peak_disk_bytes: int,
    end_disk_bytes: int,
) -> bool:
    return (
        gross_positive > 0
        and gross_negative >= gross_positive * GROW_THEN_CLEAN_NEGATIVE_RATIO
        and peak_disk_bytes > end_disk_bytes
        and net_delta <= gross_positive - gross_negative
    )


def _is_one_time_jump(deltas: tuple[int, ...], gross_positive: int) -> bool:
    if gross_positive <= 0:
        return False
    largest_positive = max((delta for delta in deltas if delta > 0), default=0)
    return largest_positive >= gross_positive * ONE_TIME_JUMP_DOMINANCE_RATIO


def _is_steady_growth(inputs: _SteadyGrowthInputs) -> bool:
    if (
        inputs.interval_count <= 0
        or inputs.gross_positive < inputs.material_delta
        or inputs.net_delta < inputs.material_delta
    ):
        return False
    positive_ratio = inputs.positive_interval_count / inputs.interval_count
    if positive_ratio < STEADY_GROWTH_INTERVAL_RATIO:
        return False
    return inputs.gross_negative <= inputs.gross_positive * NEGATIVE_TO_POSITIVE_STEADY_MAX_RATIO


def _disk_deltas(samples: tuple[TrendSample, ...]) -> tuple[int, ...]:
    return tuple(current.disk_bytes - previous.disk_bytes for previous, current in pairwise(samples))


def _first_nonzero_at(samples: tuple[TrendSample, ...]) -> datetime | None:
    for sample in samples:
        if sample.disk_bytes > 0:
            return sample.finished_at
    return None


def _last_growth_at(
    samples: tuple[TrendSample, ...], *, deltas: tuple[int, ...], material_delta: int
) -> datetime | None:
    for index in range(len(deltas) - 1, -1, -1):
        if deltas[index] >= material_delta:
            return samples[index + 1].finished_at
    return None


def _daily_slope(samples: tuple[TrendSample, ...]) -> float | None:
    if len(samples) < MIN_CLASSIFIABLE_SAMPLES:
        return None
    elapsed_seconds = (samples[-1].finished_at - samples[0].finished_at).total_seconds()
    if elapsed_seconds <= 0:
        return None
    return (samples[-1].disk_bytes - samples[0].disk_bytes) / (elapsed_seconds / 86400)


def _volatility(deltas: tuple[int, ...]) -> float:
    if not deltas:
        return 0.0
    mean = sum(deltas) / len(deltas)
    variance = sum((delta - mean) ** 2 for delta in deltas) / len(deltas)
    return sqrt(variance)


def _missing_sample_count(sample_count: int, expected_sample_count: int | None) -> int:
    if expected_sample_count is None:
        return 0
    return max(0, expected_sample_count - sample_count)


def _material_delta_threshold(peak_disk_bytes: int | None) -> int:
    if peak_disk_bytes is None:
        return MATERIAL_DELTA_FLOOR_BYTES
    return max(MATERIAL_DELTA_FLOOR_BYTES, int(peak_disk_bytes * MATERIAL_DELTA_CURRENT_RATIO))
