# Hippo Pharmacy Claims Exercise

A functional, standard-library Python application that reads pharmacy datasets, claim events, and revert events across multiple directories, validates and reconciles records in parallel across up to 10 CPU cores, and outputs the three requested JSON reports.

Exercise prompt: https://gist.github.com/matheus-hellohippo/a0e28bcbeade9e5044a08808a847a11c

## How to Run

Requires Python 3.11+ (no external packages needed).

### 1. Run with the Supplied Archive (`data.tar`)

```sh
mkdir -p data
tar -xf data.tar -C data
python3 -m hippo \
  --pharmacies data/pharmacies \
  --claims data/claims \
  --reverts data/reverts \
  --output output
```

### 2. Run with the Committed Miniature Example

```sh
python3 -m hippo \
  --pharmacies example/pharmacies \
  --claims example/claims \
  --reverts example/reverts \
  --output output
```

### 3. Run Unit Tests

```sh
python3 -m unittest discover -s tests -v
```

## Outputs

The application writes three JSON files to `--output` (default: `output/`):

| File | Goal | Description |
| --- | --- | --- |
| `metrics.json` | Goal 2 | `fills`, `reverted`, `avg_price`, and `total_price` grouped by `(npi, ndc)` |
| `recommendations.json` | Goal 3 | Top 2 cheapest pharmacy chains per drug (`ndc`) by average unit price |
| `quantities.json` | Goal 4 | Top 5 most frequently prescribed quantities per drug (`ndc`) |

## Dataset Analysis & Results

Running the pipeline against the supplied `data.tar` archive (~4.4 MB across 32 files) yields the following breakdown:

### Input & Data Quality Summary

| Category | Metric | Count | Notes |
| --- | --- | --- | --- |
| **Pharmacies** | Valid pharmacies | 17 | 1 CSV file across 3 chains (`saint`, `health`, `doctor`) |
| **Claims** | Total rows read | 27,076 | Across 27 JSON files |
| | Invalid / malformed rows | 3 | Missing `quantity` (2 rows) or `quantity = 0` (1 row); skipped |
| | Unknown pharmacy (`npi`) | 4,085 | Valid rows from NPIs outside the 17-pharmacy dataset; excluded |
| | In-scope fills | 22,988 | Valid claims matched to known pharmacies |
| **Reverts** | Total rows read | 308 | Across 4 JSON files |
| | Duplicate revert IDs | 3 | Same `id` with differing timestamps; deduplicated (earliest retained) |
| | Unique reverts | 305 | 260 matched to in-scope claims (`reverted`); 22,728 `active` claims |

### Report Outputs (`output/`)

- **`metrics.json`**: **170** `(npi, ndc)` groups totaling **22,988** fills and **260** reverts.
  - Example row (`npi: "0123456789"`, `ndc: "00002323401"`): `fills: 151`, `reverted: 2`, `avg_price: 1.3`, `total_price: 8151.0`.
- **`recommendations.json`**: **10** drugs (`ndc`), each with its top 2 cheapest chains by mean unit price.
  - Example (`ndc: "00002323401"`): `saint` (`avg_price: 1.79`), `health` (`avg_price: 293.58`).
- **`quantities.json`**: **10** drugs (`ndc`), each with its top 5 most frequently prescribed quantities.
  - Example (`ndc: "00002323401"`): `[15.0, 8.5, 180.0, 10.0, 1.0]`.

## Code Structure (`hippo/`)

The codebase is split into three small functional modules, with docstrings on every function:

1. **`hippo/parser.py` (Goal 1 — Reading & Validation)**
   * `parse_pharmacy_file(path)`: Reads a pharmacy `.csv` or `.json` file and returns `{npi: chain}`.
   * `parse_claim_file(path)`: Reads a claims `.json` file, validates fields (`id`, `npi`, `ndc`, `quantity > 0`, `price >= 0`, `timestamp`), skips invalid rows, and returns valid claims.
   * `parse_revert_file(path)`: Reads a reverts `.json` file, validates fields (`id`, `claim_id`, `timestamp`), skips invalid rows, and returns valid reverts.

2. **`hippo/reconcile.py` (Goals 2, 3, and 4 — Aggregations)**
   * `reconcile(pharmacies, claims, reverts)`: Filters claims to known pharmacies, separates reverted vs. active claims, and calls the three report functions:
   * `compute_metrics(in_scope_claims, reversed_claim_ids)`: Calculates `fills`, `reverted`, `avg_price`, and `total_price` per `(npi, ndc)`.
   * `compute_recommendations(active_claims, pharmacies)`: Ranks the top 2 cheapest chains per `ndc` by mean unit price (`price / quantity`).
   * `compute_quantities(active_claims)`: Ranks the top 5 most common quantities per `ndc`.

3. **`hippo/pipeline.py` (CLI & Multi-Core Execution)**
   * `discover_files(directories, extensions)`: Collects input files across one or more directories.
   * `load_events_parallel(paths, parser_fn, workers)`: Parses files in parallel across up to 10 CPU cores using `ProcessPoolExecutor` and deduplicates events by `id`.
   * `run(...)` & `main(...)`: Orchestrates the pipeline and writes the JSON reports.

## Architecture Decisions & Trade-offs

* **Parallel Ingestion on 10 Cores (`ProcessPoolExecutor`):**
  For the supplied ~27,000-row sample, single-threaded parsing finishes in under a second, so multiprocessing is not strictly needed at sample scale. However, the specification targets a **10-core instance** and real-world pharmacy claim streams are orders of magnitude larger. Partitioning JSON parsing and `Decimal` validation across up to 10 worker processes prepares the ingestion stage for production-sized batches while keeping output deterministic (files are sorted before mapping and reduced in order).
* **Functional Programming & Simple Modular Separation:**
  A batch data pipeline is naturally a chain of transformations (`parse -> filter -> reconcile -> aggregate`). Implementing `parser.py`, `reconcile.py`, and `pipeline.py` with pure, stateless functions operating on plain Python dicts, lists, and `Counter`s avoids hidden mutable state and side effects. This makes every stage deterministic (same input always produces the exact same output), trivial to test in isolation, and inherently safe to parallelize across worker processes.
* **Two-Phase Load Then Reconcile:**
  Because revert events can arrive in different files or carry timestamps earlier than their corresponding claims, loading and deduplicating all events before building the `reversed_claim_ids` set avoids ordering bugs. For datasets that exceed single-machine memory, this would naturally evolve into hash-partitioning events by `claim_id` and maintaining incremental `(count, unit_price_sum, total_price)` accumulators.
* **Exact Decimal Arithmetic & String Identifiers:**
  Raw JSON values contain floating-point noise (e.g., `64368.00000000001`), so prices and quantities are parsed as `Decimal` and rounded (`ROUND_HALF_UP`) only when writing JSON. `npi` and `ndc` remain strings to preserve leading zeroes.
