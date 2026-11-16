"""Goals 2, 3, and 4: Pure functions for reconciling claims and computing reports."""

from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def round_money(value: Decimal) -> float:
    """Round a Decimal to 2 decimal places (ROUND_HALF_UP) and convert to float for JSON."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_metrics(
    in_scope_claims: list[dict[str, Any]],
    reversed_claim_ids: set[str],
) -> list[dict[str, Any]]:
    """Goal 2: Calculate fills, reverts, average unit price, and total price per (npi, ndc).

    - `fills`: Total valid claims submitted for this (npi, ndc).
    - `reverted`: Number of those claims that were later invalidated by a revert event.
    - `avg_price`: Mean unit price (`price / quantity`) across active (non-reverted) claims.
    - `total_price`: Sum of `price` across active (non-reverted) claims.
    """
    fills: Counter[tuple[str, str]] = Counter()
    reverted: Counter[tuple[str, str]] = Counter()
    unit_prices: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    total_prices: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal(0))

    for claim in in_scope_claims:
        key = (claim["npi"], claim["ndc"])
        fills[key] += 1
        if claim["id"] in reversed_claim_ids:
            reverted[key] += 1
        else:
            unit_prices[key].append(claim["price"] / claim["quantity"])
            total_prices[key] += claim["price"]

    report: list[dict[str, Any]] = []
    for npi, ndc in sorted(fills):
        key = (npi, ndc)
        prices = unit_prices[key]
        avg_price = round_money(sum(prices) / len(prices)) if prices else None
        report.append(
            {
                "npi": npi,
                "ndc": ndc,
                "fills": fills[key],
                "reverted": reverted[key],
                "avg_price": avg_price,
                "total_price": round_money(total_prices[key]),
            }
        )
    return report


def compute_recommendations(
    active_claims: list[dict[str, Any]],
    pharmacies: dict[str, str],
    top_n: int = 2,
) -> list[dict[str, Any]]:
    """Goal 3: Recommend the top 2 cheapest chains per drug (ndc) by average unit price.

    Active claim unit prices (`price / quantity`) are pooled by `(ndc, chain)` and
    chains are ranked from lowest to highest average unit price.
    """
    chain_unit_prices: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for claim in active_claims:
        chain = pharmacies[claim["npi"]]
        unit_price = claim["price"] / claim["quantity"]
        chain_unit_prices[(claim["ndc"], chain)].append(unit_price)

    by_drug: dict[str, list[tuple[Decimal, str]]] = defaultdict(list)
    for (ndc, chain), prices in chain_unit_prices.items():
        avg_unit_price = sum(prices) / len(prices)
        by_drug[ndc].append((avg_unit_price, chain))

    return [
        {
            "ndc": ndc,
            "chain": [
                {"name": chain, "avg_price": round_money(avg_price)}
                for avg_price, chain in sorted(by_drug[ndc])[:top_n]
            ],
        }
        for ndc in sorted(by_drug)
    ]


def compute_quantities(
    active_claims: list[dict[str, Any]],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """Goal 4: Find the top 5 most commonly prescribed quantities for each drug (ndc).

    Quantities are ranked by frequency (highest count first), breaking ties by
    smaller numeric quantity first.
    """
    counts_by_drug: dict[str, Counter[Decimal]] = defaultdict(Counter)
    for claim in active_claims:
        counts_by_drug[claim["ndc"]][claim["quantity"]] += 1

    return [
        {
            "ndc": ndc,
            "most_prescribed_quantity": [
                float(qty)
                for qty in sorted(
                    counts_by_drug[ndc],
                    key=lambda q: (-counts_by_drug[ndc][q], q),
                )[:top_n]
            ],
        }
        for ndc in sorted(counts_by_drug)
    ]


def reconcile(
    pharmacies: dict[str, str],
    claims: dict[str, dict[str, Any]],
    reverts: dict[str, dict[str, Any]],
    top_quantities: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Filter claims to known pharmacies, apply reverts, and generate all 3 reports."""
    reversed_claim_ids = {revert["claim_id"] for revert in reverts.values()}

    # Goal 1: Keep only claims from pharmacies present in the pharmacy dataset
    in_scope_claims = [c for c in claims.values() if c["npi"] in pharmacies]

    # Active claims are in-scope claims that have not been reverted
    active_claims = [c for c in in_scope_claims if c["id"] not in reversed_claim_ids]

    return {
        "metrics.json": compute_metrics(in_scope_claims, reversed_claim_ids),
        "recommendations.json": compute_recommendations(active_claims, pharmacies),
        "quantities.json": compute_quantities(active_claims, top_n=top_quantities),
    }
