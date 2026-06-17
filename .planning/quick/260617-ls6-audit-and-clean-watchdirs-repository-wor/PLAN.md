# Quick Task 260617-ls6: Repository workspace hygiene audit

## Goal

Audit the watchdirs working directory, remove safe generated clutter, and verify git/GitHub repository state.

## Plan

1. Inspect git status, remotes, current branch, and GitHub CLI repository resolution.
2. Inventory top-level directories and ignored files.
3. Classify each directory as source, tests, planning, operations asset, git metadata, or generated/cache.
4. Delete only ignored generated/cache artifacts.
5. Verify tests still pass.
6. Record findings, including branch and remote state.

