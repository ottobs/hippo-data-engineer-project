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
