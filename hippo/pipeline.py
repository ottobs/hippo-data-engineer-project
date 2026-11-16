"""CLI entry point and parallel multi-core file loading for the Hippo pipeline."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Sequence

from .parser import parse_claim_file, parse_pharmacy_file, parse_revert_file
from .reconcile import reconcile

DataError = ValueError


def discover_files(directories: Sequence[str | Path], extensions: set[str]) -> list[Path]:
    """Find all files matching `extensions` inside the given directories in sorted order."""
    paths: set[Path] = set()
    for raw_dir in directories:
        directory = Path(raw_dir)
        if not directory.is_dir():
            raise DataError(f"Directory does not exist: {directory}")
        found = [
            p.resolve()
            for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() in extensions
        ]
        if not found:
            raise DataError(f"No supported files found in: {directory}")
        paths.update(found)
    return sorted(paths)


def load_events_parallel(
    paths: list[Path],
    parser_fn: Callable[[Path], list[dict[str, Any]]],
    workers: int = 10,
) -> dict[str, dict[str, Any]]:
    """Parse multiple JSON files in parallel across CPU cores and deduplicate by event `id`.

    Uses `ProcessPoolExecutor` up to `workers` processes (default 10 cores).
    If the same event `id` appears more than once, retains the earliest timestamp.
    """
    effective_workers = max(1, min(workers, len(paths), 10))
    if effective_workers == 1:
        batches = [parser_fn(path) for path in paths]
    else:
        try:
            with ProcessPoolExecutor(max_workers=effective_workers) as pool:
                batches = list(pool.map(parser_fn, paths))
        except (OSError, PermissionError):
            batches = [parser_fn(path) for path in paths]

    events: dict[str, dict[str, Any]] = {}
    for batch in batches:
        for event in batch:
            event_id = event["id"]
            if event_id not in events or event["timestamp"] < events[event_id]["timestamp"]:
                events[event_id] = event
    return events


def run(
    pharmacy_dirs: Sequence[str | Path],
    claim_dirs: Sequence[str | Path],
    revert_dirs: Sequence[str | Path],
    top_quantities: int = 5,
    workers: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Load pharmacies, claims, and reverts from input directories and compute all 3 reports."""
    max_workers = min(10, os.cpu_count() or 1) if workers is None else max(1, workers)

    pharmacy_paths = discover_files(pharmacy_dirs, {".csv", ".json"})
    claim_paths = discover_files(claim_dirs, {".json"})
    revert_paths = discover_files(revert_dirs, {".json"})

    pharmacies: dict[str, str] = {}
    for path in pharmacy_paths:
        for npi, chain in parse_pharmacy_file(path).items():
            pharmacies.setdefault(npi, chain)
    if not pharmacies:
        raise DataError("No valid pharmacies found in input directories")

    claims = load_events_parallel(claim_paths, parse_claim_file, workers=max_workers)
    reverts = load_events_parallel(revert_paths, parse_revert_file, workers=max_workers)

    return reconcile(pharmacies, claims, reverts, top_quantities=top_quantities)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments, run the pipeline, and write the 3 JSON output files."""
    parser = argparse.ArgumentParser(
        prog="hippo",
        description="Process pharmacy claims and reverts and generate JSON reports.",
    )
    parser.add_argument("--pharmacies", nargs="+", required=True, help="Pharmacy directories")
    parser.add_argument("--claims", nargs="+", required=True, help="Claims directories")
    parser.add_argument("--reverts", nargs="+", required=True, help="Reverts directories")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory")
    parser.add_argument(
        "--workers",
        type=int,
        default=min(10, os.cpu_count() or 1),
        help="Number of parallel worker processes (default: up to 10 cores)",
    )
    args = parser.parse_args(argv)

    try:
        reports = run(args.pharmacies, args.claims, args.reverts, workers=args.workers)
        args.output.mkdir(parents=True, exist_ok=True)
        for filename, data in reports.items():
            (args.output / filename).write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8"
            )
    except (DataError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    return 0
