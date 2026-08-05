from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from watchdirs.reporting.trends import GrowthShape, TrendSample, analyze_trend

BASE_TIME = datetime(2026, 8, 1, tzinfo=UTC)


def _samples(values: list[int]) -> tuple[TrendSample, ...]:
    return tuple(
        TrendSample(
            snapshot_id=index + 1,
            finished_at=BASE_TIME + timedelta(days=index),
            disk_bytes=value,
            apparent_bytes=value * 2,
        )
        for index, value in enumerate(values)
    )


def test_analyze_trend_classifies_steady_growth_and_metrics() -> None:
    metrics = analyze_trend(_samples([1000, 1010, 1020, 1030, 1040]), expected_sample_count=6)

    assert metrics.shape is GrowthShape.STEADY_GROWTH
    assert metrics.start_disk_bytes == 1000
    assert metrics.end_disk_bytes == 1040
    assert metrics.net_disk_bytes_delta == 40
    assert metrics.gross_positive_disk_bytes_delta == 40
    assert metrics.gross_negative_disk_bytes_delta == 0
    assert metrics.first_observed_at == BASE_TIME
    assert metrics.first_nonzero_at == BASE_TIME
    assert metrics.last_growth_at == BASE_TIME + timedelta(days=4)
    assert metrics.peak_disk_bytes == 1040
    assert metrics.daily_slope_disk_bytes == pytest.approx(10.0)
    assert metrics.volatility_disk_bytes == pytest.approx(0.0)
    assert metrics.sample_count == 5
    assert metrics.missing_sample_count == 1


def test_analyze_trend_classifies_one_time_jump() -> None:
    metrics = analyze_trend(_samples([0, 1000, 1010, 1005]))

    assert metrics.shape is GrowthShape.ONE_TIME_JUMP
    assert metrics.gross_positive_disk_bytes_delta == 1010
    assert metrics.gross_negative_disk_bytes_delta == 5
    assert metrics.last_growth_at == BASE_TIME + timedelta(days=2)


def test_analyze_trend_classifies_bursty_growth() -> None:
    metrics = analyze_trend(_samples([0, 1000, 1000, 1500, 1500]))

    assert metrics.shape is GrowthShape.BURSTY_GROWTH
    assert metrics.net_disk_bytes_delta == 1500
    assert metrics.gross_positive_disk_bytes_delta == 1500


def test_analyze_trend_classifies_grow_then_clean() -> None:
    metrics = analyze_trend(_samples([100, 1000, 200]))

    assert metrics.shape is GrowthShape.GROW_THEN_CLEAN
    assert metrics.peak_disk_bytes == 1000
    assert metrics.gross_positive_disk_bytes_delta == 900
    assert metrics.gross_negative_disk_bytes_delta == 800


def test_analyze_trend_classifies_stable_large() -> None:
    metrics = analyze_trend(_samples([1000, 1000, 1000, 1000]))

    assert metrics.shape is GrowthShape.STABLE_LARGE
    assert metrics.net_disk_bytes_delta == 0
    assert metrics.last_growth_at is None


def test_analyze_trend_classifies_unknown_for_insufficient_samples() -> None:
    metrics = analyze_trend(_samples([0, 1000]))

    assert metrics.shape is GrowthShape.UNKNOWN_INSUFFICIENT_SAMPLES
    assert metrics.daily_slope_disk_bytes is None


def test_analyze_trend_sorts_samples_by_time_then_snapshot_id() -> None:
    unordered = (
        TrendSample(snapshot_id=2, finished_at=BASE_TIME + timedelta(days=1), disk_bytes=20, apparent_bytes=20),
        TrendSample(snapshot_id=1, finished_at=BASE_TIME, disk_bytes=10, apparent_bytes=10),
        TrendSample(snapshot_id=3, finished_at=BASE_TIME + timedelta(days=2), disk_bytes=30, apparent_bytes=30),
    )

    metrics = analyze_trend(unordered)

    assert [sample.snapshot_id for sample in metrics.samples] == [1, 2, 3]
    assert metrics.shape is GrowthShape.STEADY_GROWTH
