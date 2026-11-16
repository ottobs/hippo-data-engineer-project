"""Unit and integration tests for the Hippo pharmacy claims pipeline."""

import json
from pathlib import Path
import tempfile
import unittest

from hippo.pipeline import main, run


def make_claim(
    index: int,
    *,
    npi: str = "0123456789",
    ndc: str = "00002323401",
    price: float | int | str = 10,
    quantity: float | int | str = 2,
    timestamp: str = "2024-01-02T00:00:00",
) -> dict:
    """Helper to create a valid synthetic claim dictionary for tests."""
    return {
        "id": f"00000000-0000-0000-0000-{index:012d}",
        "npi": npi,
        "ndc": ndc,
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp,
    }


def make_revert(
    index: int,
    claim_index: int,
    *,
    timestamp: str = "2024-01-01T00:00:00",
) -> dict:
    """Helper to create a valid synthetic revert dictionary for tests."""
    return {
        "id": f"10000000-0000-0000-0000-{index:012d}",
        "claim_id": make_claim(claim_index)["id"],
        "timestamp": timestamp,
    }


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("pharmacies", "claims", "reverts"):
            (self.root / folder).mkdir()
        (self.root / "pharmacies" / "mapping.csv").write_text(
            "chain,npi\n"
            "alpha,0123456789\n"
            "alpha,1111111111\n"
            "beta,2222222222\n"
            "gamma,3333333333\n",
            encoding="utf-8",
        )

    def write_json(self, folder: str, rows: list, name: str = "events.json") -> None:
        (self.root / folder / name).write_text(json.dumps(rows), encoding="utf-8")

    def run_pipeline(self, claims: list, reverts: list = (), **kwargs) -> dict:
        self.write_json("claims", claims)
        self.write_json("reverts", list(reverts))
        return run(
            [self.root / "pharmacies"],
            [self.root / "claims"],
            [self.root / "reverts"],
            **kwargs,
        )

    def test_goal2_metrics_and_reconciliation(self) -> None:
        """Goal 2: Verify fills, reverted count, avg unit price, and unknown pharmacy filtering."""
        result = self.run_pipeline(
            [
                make_claim(1, price=10, quantity=2),    # unit price = 5
                make_claim(2, price=100, quantity=10),  # unit price = 10
                make_claim(3, price=999),               # reverted -> excluded from prices
                make_claim(4, npi="9999999999"),        # unknown pharmacy -> ignored
            ],
            [make_revert(1, 3)],
        )
        self.assertEqual(
            result["metrics.json"],
            [
                {
                    "npi": "0123456789",
                    "ndc": "00002323401",
                    "fills": 3,
                    "reverted": 1,
                    "avg_price": 7.5,
                    "total_price": 110.0,
                }
            ],
        )

    def test_goal3_top_two_chains_per_drug(self) -> None:
        """Goal 3: Verify chains are ranked by lowest pooled average unit price."""
        result = self.run_pipeline(
            [
                make_claim(1, price=2, quantity=1),
                make_claim(2, price=2, quantity=1),
                make_claim(3, npi="1111111111", price=14, quantity=1),  # alpha avg = (2+2+14)/3 = 6.0
                make_claim(4, npi="2222222222", price=7, quantity=1),   # beta avg = 7.0
                make_claim(5, npi="3333333333", price=9, quantity=1),   # gamma avg = 9.0
            ]
        )
        self.assertEqual(
            result["recommendations.json"][0]["chain"],
            [
                {"name": "alpha", "avg_price": 6.0},
                {"name": "beta", "avg_price": 7.0},
            ],
        )

    def test_goal4_top_five_quantities_per_drug(self) -> None:
        """Goal 4: Verify top 5 quantities ordered by frequency descending, then value ascending."""
        quantities = [8.5, 2, 8.5, 2, 180, 45, 15, 90]
        result = self.run_pipeline(
            [make_claim(i, quantity=q) for i, q in enumerate(quantities, 1)]
        )
        self.assertEqual(
            result["quantities.json"][0]["most_prescribed_quantity"],
            [2.0, 8.5, 15.0, 45.0, 90.0],
        )

    def test_invalid_rows_are_skipped_without_stopping_valid_rows(self) -> None:
        """Goal 1: Verify malformed events are skipped while valid events still process."""
        malformed = [
            {**make_claim(2), "quantity": 0},
            {**make_claim(3), "quantity": -1},
            {**make_claim(4), "price": -5},
            {**make_claim(5), "timestamp": "invalid-date"},
            {**make_claim(6), "id": "not-a-uuid"},
            {"id": make_claim(7)["id"], "npi": "0123456789"},  # missing fields
        ]
        result = self.run_pipeline([make_claim(1)] + malformed)
        self.assertEqual(len(result["metrics.json"]), 1)
        self.assertEqual(result["metrics.json"][0]["fills"], 1)

    def test_duplicates_and_parallel_workers_are_deterministic(self) -> None:
        """Verify duplicate events are deduplicated and multi-worker runs match single-worker runs."""
        c1 = make_claim(1, price=10, quantity=2)
        self.write_json("claims", [c1, c1], name="batch1.json")
        self.write_json("reverts", [make_revert(1, 99)])
        extra = self.root / "extra"
        extra.mkdir()
        (extra / "batch2.json").write_text(
            json.dumps([make_claim(2, price=20, quantity=2)]), encoding="utf-8"
        )

        single = run(
            [self.root / "pharmacies"],
            [self.root / "claims", extra],
            [self.root / "reverts"],
            workers=1,
        )
        parallel = run(
            [self.root / "pharmacies"],
            [self.root / "claims", extra],
            [self.root / "reverts"],
            workers=4,
        )
        self.assertEqual(single, parallel)
        self.assertEqual(parallel["metrics.json"][0]["fills"], 2)

    def test_cli_writes_three_report_files(self) -> None:
        """Verify CLI entry point writes metrics.json, recommendations.json, and quantities.json."""
        self.run_pipeline([make_claim(1)])
        output_dir = self.root / "output"
        exit_code = main(
            [
                "--pharmacies",
                str(self.root / "pharmacies"),
                "--claims",
                str(self.root / "claims"),
                "--reverts",
                str(self.root / "reverts"),
                "--output",
                str(output_dir),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            {p.name for p in output_dir.iterdir()},
            {"metrics.json", "recommendations.json", "quantities.json"},
        )


if __name__ == "__main__":
    unittest.main()
