"""Goal 1: Functions for reading and validating pharmacy, claim, and revert files."""

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any
from uuid import UUID


def _to_decimal(value: Any, *, positive: bool = False) -> Decimal:
    """Convert a number or numeric string to a finite Decimal, rejecting booleans and NaNs."""
    if isinstance(value, bool) or value is None:
        raise ValueError("Value must be numeric")
    dec = Decimal(str(value).strip())
    if not dec.is_finite() or dec < 0 or (positive and dec == 0):
        raise ValueError("Value out of allowed range")
    return dec


def parse_pharmacy_file(path: Path) -> dict[str, str]:
    """Read a pharmacy CSV or JSON file and return a `{npi: chain}` mapping.

    Supports both `.csv` files (with `npi,chain` columns) and `.json` files
    (with `npi` or `id`, plus `chain`). Invalid rows are skipped.
    """
    try:
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        else:
            with path.open(encoding="utf-8-sig") as f:
                rows = json.load(f)
    except (OSError, ValueError):
        return {}

    if not isinstance(rows, list):
        return {}

    pharmacies: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_npi = row.get("npi") if row.get("npi") is not None else row.get("id")
        raw_chain = row.get("chain")
        if not isinstance(raw_npi, str) or not isinstance(raw_chain, str):
            continue
        npi, chain = raw_npi.strip(), raw_chain.strip()
        if npi and chain and npi not in pharmacies:
            pharmacies[npi] = chain

    return pharmacies


def parse_claim_file(path: Path) -> list[dict[str, Any]]:
    """Read a claims JSON file, validate each event against the schema, and skip bad rows.

    A valid claim requires:
    - `id`: valid UUID string
    - `npi`: non-empty pharmacy identifier string
    - `ndc`: non-empty drug identifier string
    - `quantity`: positive finite number (> 0)
    - `price`: non-negative finite number (>= 0)
    - `timestamp`: valid ISO-8601 datetime string
    """
    try:
        with path.open(encoding="utf-8-sig") as f:
            rows = json.load(f, parse_float=Decimal)
    except (OSError, ValueError, InvalidOperation):
        return []

    if not isinstance(rows, list):
        return []

    valid_claims: list[dict[str, Any]] = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            npi = str(row["npi"]).strip() if isinstance(row.get("npi"), str) else ""
            ndc = str(row["ndc"]).strip() if isinstance(row.get("ndc"), str) else ""
            ts_str = row.get("timestamp")
            if not npi or not ndc or not isinstance(ts_str, str) or "T" not in ts_str:
                continue

            valid_claims.append(
                {
                    "id": str(UUID(str(row["id"]).strip())),
                    "npi": npi,
                    "ndc": ndc,
                    "quantity": _to_decimal(row["quantity"], positive=True),
                    "price": _to_decimal(row["price"], positive=False),
                    "timestamp": datetime.fromisoformat(ts_str.strip()),
                }
            )
        except (KeyError, ValueError, TypeError, InvalidOperation):
            # Skip any event that does not comply with the schema (Goal 1)
            continue

    return valid_claims


def parse_revert_file(path: Path) -> list[dict[str, Any]]:
    """Read a reverts JSON file, validate each event against the schema, and skip bad rows.

    A valid revert requires:
    - `id`: valid UUID string
    - `claim_id`: valid UUID string referencing the claim being invalidated
    - `timestamp`: valid ISO-8601 datetime string
    """
    try:
        with path.open(encoding="utf-8-sig") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        return []

    if not isinstance(rows, list):
        return []

    valid_reverts: list[dict[str, Any]] = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            ts_str = row.get("timestamp")
            if not isinstance(ts_str, str) or "T" not in ts_str:
                continue

            valid_reverts.append(
                {
                    "id": str(UUID(str(row["id"]).strip())),
                    "claim_id": str(UUID(str(row["claim_id"]).strip())),
                    "timestamp": datetime.fromisoformat(ts_str.strip()),
                }
            )
        except (KeyError, ValueError, TypeError):
            continue

    return valid_reverts
