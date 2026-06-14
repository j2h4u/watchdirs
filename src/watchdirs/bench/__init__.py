"""Dev/CI benchmark harness for watchdirs storage efficiency.

These modules are NOT part of the collect runtime. They measure path churn,
cardinality, and on-disk size on a throwaway/dev SQLite DB to set and gate the
per-snapshot byte budget (D-08/D-09). Run via ``uv run python -m watchdirs.bench.<module>``.
"""
