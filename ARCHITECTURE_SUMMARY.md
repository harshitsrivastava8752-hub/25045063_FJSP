# FJSP Pipeline — Architecture Summary

A complete Flexible Job-Shop Scheduling (FJSP) pipeline built for Inter-IIT
Tech Meet 15.0.  All six stages — **Stage 1: Generate → Stage 2: Validate →
Stage 3: Solve → Stage 4: Stress Testing → Stage 5: Causal Failure Analysis
→ Stage 6: Improve** — are implemented as independent, composable Python
modules under the `fjsp/` package.

**Primary entry point:** `python run_submission.py [--clean]`

---

## Repository Layout

```
.\
├── fjsp/                        Package root — public API surface
│   ├── __init__.py              Re-exports every public symbol
│   ├── model.py                 Core data classes and JSON serializers
│   ├── generator/
│   │   └── instance_generator.py  Parametric FJSP instance factory
│   ├── environment/
│   │   ├── validator.py         Independent schedule referee
│   │   └── metrics.py           Quality metrics + exact benchmark
│   ├── algorithms/
│   │   └── solver.py            Two-phase Tabu Search solver
│   └── experiments/
│       └── runner.py            Multi-seed experiment runner + CLI
├── analysis/
│   └── failure_analysis.md      4-mode causal failure write-ups
├── instances/
│   └── edge_cases/              7 hand-built extreme fixtures (JSON)
├── results/                     Generated artefacts (14 files + manifest)
├── run_submission.py            End-to-end pipeline entry point
├── test_fjsp.py                 11-test unit suite
├── REPORT.md                    Technical report (Sections 1–6)
└── ARCHITECTURE_SUMMARY.md      This file
```

---

## File-by-File System Summary

### `fjsp/__init__.py`

**Role:** Public API gateway.

Re-exports every symbol used by external callers so that the import path
`from fjsp import generate_instance, solve, validate` always works,
regardless of internal refactors.

**Exports (grouped):**

| Group | Symbols |
|---|---|
| Data model | `Operation`, `Instance`, `ScheduledOperation`, `ValidationResult`, `instance_to_dict`, `instance_from_dict`, `validate_instance` |
| Generator | `generate_instance`, `named_instance_parameters` |
| Environment | `validate`, `metrics`, `exact_optimum` |
| Algorithms | `solve` |
| Experiments | `function_one`, `run_experiment`, `main` |

---

### `fjsp/model.py`

**Role:** Shared, immutable data contracts that flow between every pipeline stage.

**Key types:**

| Class | Fields | Notes |
|---|---|---|
| `Operation` | `job`, `index`, `options: dict[int,int]` | Frozen dataclass; `options` maps machine ID → processing time |
| `Instance` | `jobs`, `machines`, `operations`, `seed`, `parameters` | Carries full metadata; `operations_by_job` property returns sorted per-job lists |
| `ScheduledOperation` | `job`, `index`, `machine`, `start`, `end` | Frozen; `end - start` must equal the processing time for the assigned machine |
| `ValidationResult` | `valid`, `makespan`, `errors` | Returned by the validator |

**Serialization helpers:** `instance_to_dict` / `instance_from_dict` support
JSON round-trips.  `instance_from_dict` calls `validate_instance` before
returning to reject malformed imports.

**Structural checker:** `validate_instance(instance) -> list[str]` verifies
contiguous job/op IDs, positive durations, non-empty eligibility sets, and
valid machine IDs.  Called at the end of every `generate_instance` call.

---

### `fjsp/generator/instance_generator.py`

**Role:** Parametric, seeded FJSP instance factory. Stage 1 of the pipeline.

**Entry point:** `generate_instance(jobs, machines, operations_per_job, ...)`

**Parameters:**

| Parameter | Type | Effect |
|---|---|---|
| `seed` | `int \| None` | Sole source of randomness; guarantees full determinism |
| `jobs` / `machines` | `int` | Problem dimensions |
| `operations_per_job` | `int \| (int,int)` | Fixed count or random range per job |
| `flexibility` | `float [0,1]` | Fraction of machines eligible per operation |
| `processing_time_min/max` | `int` | Uniform sampling bounds |
| `processing_time_noise_scale` | `float ≥ 0` | Gaussian multiplier: `p = center × (1 + N(0, σ))` |
| `bottleneck_probability` | `float [0,1]` | Probability of forcing ops onto a bottleneck machine |
| `machine_advantage` | `float ≥ 0` | Speedup factor for a specialist machine |
| `instance_class` | `str` | Named preset that overrides any above parameters |

**Named instance classes (9):**

| Class | Key characteristics |
|---|---|
| `average` | `flexibility=0.5`, mild noise, slight bottleneck |
| `low_flexibility` | `flexibility=0.05` — near-JSP; ≤ 2 machines eligible per op (see near-zero fixture note below) |
| `high_flexibility` | `flexibility=0.95` — near-open-shop |
| `bottleneck` | `bottleneck_probability=0.85` |
| `balanced` | `bottleneck_probability=0.0` — no forced routing |
| `high_variance` | `noise_scale=1.0`, `time_max=100` |
| `machine_advantage` | `machine_advantage=0.8` — strong specialist |
| `extreme` | `flexibility=0.95`, `noise_scale=1.5`, `time_max=10000`, `bottleneck=0.8` |
| `unbalanced` | `operations_per_job=(1,8)` — random job lengths drawn from `[1, 8]`, simulating real-world workload imbalance where short jobs complete early and long jobs create machine-queue starvation |

**Machine Sampling Strategy:**

For each operation `O(j, k)`, the number of eligible machines is computed as:

```
k = max(1, min(M, round(1 + flexibility × (M − 1))))
```

`k` machines are then drawn via uniform random selection **without replacement**
from `{0, …, M−1}` using `rng.sample(range(machines), k)`.  This guarantees:

- At `flexibility=0.0`: exactly 1 machine eligible per operation (pure JSP).
- At `flexibility=1.0`: all M machines eligible per operation (open-shop).
- Intermediate values scale linearly between these extremes.

If `bottleneck_probability > 0`, the pre-drawn bottleneck machine index is
unconditionally added to the eligible set *after* the random sample, so that
operations may have `k+1` eligible machines when the bottleneck is not already
in the sample.  Machine IDs are stored sorted to ensure determinism.

**Feasibility guarantees:** Every operation has at least one eligible machine.
Durations are clamped to `max(1, ...)`. IDs are contiguous from zero. A full
`validate_instance()` check is run before returning.

---

### `fjsp/environment/validator.py`

**Role:** Independent schedule referee. Stage 2: Validate.

**Entry point:** `validate(instance, schedule) -> ValidationResult`

Zero imports from `fjsp.algorithms`. Checks, in order:

| Check | Condition caught | Error message pattern |
|---|---|---|
| Malformed schedule | Not a `list` | `"malformed schedule: expected a list"` |
| Malformed entry | Non-`ScheduledOperation` or non-int fields | `"malformed schedule entry at position N"` |
| Duplicate operation | Same `(job, index)` seen twice | `"duplicate operation J{j}-O{i}"` |
| Unknown operation | `(job, index)` not in instance | `"unknown operation J{j}-O{i} (job X has N operation(s))"` |
| Ineligible machine | Machine ∉ `op.options` | `"Machine M{m} is not eligible for J{j}-O{i} (eligible: M0, M2...)"` |
| Invalid interval | `start < 0` or `end ≤ start` | `"invalid interval for J{j}-O{i}: [start, end)"` |
| Duration mismatch | `end - start ≠ processing_time` | `"Wrong duration for J{j}-O{i} on M{m}: expected X, got Y"` |
| Missing operations | Any `(job, index)` not scheduled | `"missing operation J{j}-O{i}"` |
| Precedence violation | `O(j,k).end > O(j,k+1).start` | `"Precedence violation in J{j}: O{k} ends at X but O{k+1} starts at Y"` |
| Machine overlap | Two ops sharing time on same machine | `"Overlap on M{m}: J{a}-O{b} [s,e) ∩ J{c}-O{d} [s,e)"` |

Returns `ValidationResult(valid, makespan, errors)`.
`makespan = max(end)` only when `valid=True`, else `None`.

**Mathematical Invariants:**

> **a) Transitive precedence coverage.**  The checker verifies
> $S(j,k+1) \geq C(j,k)$ for every adjacent operation pair
> $(O(j,k),\,O(j,k+1))$ within each job.  Because job chains are
> strictly linear (no branching or merging within a job), this pairwise
> adjacent check transitively prevents *any* non-adjacent same-job
> overlap: if $S(j,k+1) \geq C(j,k)$ holds for all $k$, then by
> induction $S(j,k+n) \geq C(j,k+n-1) \geq \ldots \geq C(j,k)$ for
> all $n \geq 1$.  No additional multi-hop precedence scan is required.

> **b) Non-preemption (operation splitting).**  FJSP requires each
> operation to execute contiguously on a single machine — splitting is
> forbidden.  This is enforced indirectly by the **duplicate
> `(job, index)` set-hash check** (L36–38): any schedule that executes
> the same `(job, index)` on two different time windows would produce a
> duplicate key, which is detected and rejected before timing checks run.
> The `end ≤ start` interval guard additionally rules out zero-width
> (instantaneous) or inverted entries that could otherwise model splits.

---

### `fjsp/environment/metrics.py`

**Role:** Schedule quality diagnostics and exact benchmark. Stage 4: Stress Testing.

**`metrics(instance, schedule) -> dict`** — Returns:

| Key | Description |
|---|---|
| `makespan` | `max(end)` over all operations |
| `job_completion_times` | Per-job finish time |
| `machine_utilization` | Fraction of horizon each machine is busy |
| `critical_path` | Longest path through the disjunctive graph (DAG) |
| `job_chain_lower_bound` | Sum of minimum durations along the longest job chain |
| `max_machine_workload` | Maximum total work on any single machine |
| `lower_bound` | `max(job_chain, machine_workload, assignment_lb)` |
| `lower_bound_gap` | `(makespan - lower_bound) / lower_bound` |

**`exact_optimum(instance, limit=9) -> int`** — Exhaustive memoized
branch-and-bound for instances with ≤ 9 operations. Used in
`results/exact_small_instances.json` to calibrate heuristic quality.

---

### `fjsp/algorithms/solver.py`

**Role:** Two-phase Tabu Search heuristic. Stage 3: Solve.

**Entry point:** `solve(instance, seed, iterations, local_search_iterations, tabu_tenure) -> list[ScheduledOperation]`

#### Phase 1 — Congestion-Aware Greedy Multi-Start

Runs `iterations` independent construction passes. At each step, all
`(ready_operation, machine)` pairs are scored by:

```
score = earliest_finish + congestion_ratio × duration
```

where `congestion_ratio = machine_load / total_load`. A random tie-breaker
ensures diversity across restarts. The best valid schedule across all starts
is forwarded to Phase 2.

#### Phase 2 — Critical-Path-Restricted Tabu Search

Internal state: `assignments: {(job,idx): machine}` and
`priority: {(job,idx): rank}` together deterministically reconstruct any
schedule via `_rebuild()`.

**Neighbourhood N1 — Machine Reassignment:**
Identifies critical-path operations via DAG longest-path analysis
(`_compute_critical_path`). Samples up to `⌈|ops|/3⌉` candidates,
prioritising critical ops. For each, tries reassigning to every alternative
eligible machine.

**Neighbourhood N2 — Critical Block Adjacent Swap (N5):**
Extracts critical blocks (maximal runs of consecutive critical-path
operations sharing the same machine) via `_extract_critical_blocks`.
Restricts adjacent swaps **strictly to the boundary pairs of each critical
block**: the first pair `(block[0], block[1])` and the last pair
`(block[-2], block[-1])`.  This directly implements the **Nowicki &
Smutnicki (1996) N5 neighbourhood**, which is theoretically sufficient
because only boundary swaps can shorten the critical path — interior swaps
within a block cannot reduce the block's total processing time.

**Performance design:**

| Optimisation | Mechanism |
|---|---|
| O(1) tabu lookup | `tabu: dict[tuple, int]` — stores move signature → expiry iteration |
| Fast candidate evaluation | `max(s.end for s in sched)` instead of full `validate()` |
| O(1) op access | `op_lookup = {(job,idx): op}` built once before the loop |
| Stagnation early exit | Break after 15 consecutive non-improving accepted moves |

> **Stagnation Cutoff Rationale:** The limit of 15 non-improving iterations
> is calibrated to balance local plateau exploration against execution budget.
> Each full iteration evaluates O(|sample| × M) N1 moves plus O(|blocks|)
> boundary N2 pairs.  Across 30+ seed sweeps, a larger stagnation window
> would multiply wall-clock time proportionally with diminishing returns in
> high-flexibility instances where the makespan landscape is flat (see Failure
> Mode 4 in `analysis/failure_analysis.md`).

**Tabu memory:** Move signatures `("N1", key, from_m, to_m)` and
`("N2", lk, rk, machine)` are stored with expiry `iteration + tabu_tenure`.
**Aspiration criterion:** A tabu move is accepted if it strictly beats the
global best makespan.

**State resync:** After every accepted move (N1 or N2), both `assignments`
and `priority` are rebuilt from the accepted schedule to prevent state drift.

---

### `fjsp/experiments/runner.py`

**Role:** Parametric multi-seed experiment runner and CLI entrypoint. Stage 4: Stress Testing.

**`function_one(...) -> dict`** — Runs one Generate→Solve→Validate→Metrics
pass and returns submission-ready JSON with instance, schedule, validation,
metrics, and algorithm metadata.

**`run_experiment(args) -> dict`** — Runs `args.repetitions` seeded trials
and returns aggregate statistics:

| Output field | Description |
|---|---|
| `average_makespan` | Mean across repetitions |
| `makespan_ci_95_half` | 95% confidence interval half-width: `1.96 σ/√n` |
| `makespan_mean_lower/upper` | CI bounds |
| `best/worst_makespan` | Range |
| `average_lower_bound_gap` | Mean gap from theoretical lower bound |
| `makespan_stddev` | Standard deviation |
| `algorithm` | Name, seed, iterations, `tabu_tenure`, Python version |

**CLI subcommands:** `generate`, `solve`, `validate`, `function-one`,
`experiment` — invoked via the package module entry:
`python -m fjsp <command>` or through `run_submission.py` (primary entry point).

---

### `run_submission.py`

**Role:** End-to-end artifact generation pipeline. Single reproducible entry point.

**Usage:** `python run_submission.py [--clean]`

`--clean` wipes and recreates `results/` before running.

**Pipeline stages executed:**

1. **`function_one`** → `results/function_one.json`
2. **9 instance classes** (10 repetitions each) → `results/{class}.json`
3. **Controlled sweeps** (4 parameters × up to 6 values × 20 seeds) → `results/controlled_sweeps.csv`
4. **Exact benchmark** (10 seeds, tiny instances) → `results/exact_small_instances.json`
5. **Ablation study** (3 algorithms × 20 seeds) → `results/ablation.csv`
6. **7 edge-case fixtures** → `instances/edge_cases/{name}.json`
7. **SHA-256 manifest** → `results/manifest.json`

**SPT baseline:** `spt_schedule(instance)` dispatches by shortest available
processing time at each step. Included in the ablation to establish a
single-pass greedy lower reference point.

---

### `analysis/failure_analysis.md`

**Role:** Causal failure mode documentation. Stage 5: Causal Failure Analysis.

Contains 4 failure modes, each following the required 5-step structure:
**Observation → Evidence → Hypothesis → Structural Explanation → Proposed Improvement.**

| Mode | Root cause |
|---|---|
| 1 — High-Flexibility Bottleneck | Large N1 neighbourhood → greedy commits to contended machine |
| 2 — High-Variance Critical Path | Single outlier duration dominates job-chain lower bound |
| 3 — Machine Advantage Overloading | Greedy always prefers specialist → single-machine queue buildup |
| 4 — Stagnation Trap | Flat makespan topology in high-flexibility instances → early exit before diversification |

---

### `instances/edge_cases/`

7 JSON fixtures for boundary condition testing:

| File | Dimensions | Stress |
|---|---|---|
| `single_machine.json` | 5 jobs × 1 machine × 3 ops | Pure JSP — no machine choice |
| `single_job.json` | 1 job × 4 machines × 4 ops | No job contention |
| `many_machines.json` | 3 jobs × 8 machines × 2 ops | Full flexibility |
| `extreme_gap.json` | 2 jobs × 2 machines × 2 ops | Processing times 1 vs 10 000 |
| `long_chain.json` | 2 jobs × 1 machine × 12 ops | Long precedence chain |
| `identical_times.json` | 3 jobs × 2 machines × 3 ops | All durations = 5; tests tie-breaking |
| `many_jobs_bottleneck.json` | 20 jobs × 4 machines × 2 ops | 100% bottleneck routing; peak contention |

---

### `results/` (generated)

14 artefacts created by `run_submission.py --clean`:

| File | Content |
|---|---|
| `function_one.json` | First-milestone submission artifact |
| `{class}.json` × 9 | Per-instance-class aggregate results with CI bounds |
| `controlled_sweeps.csv` | 1D parameter sensitivity (flexibility, bottleneck, noise, advantage) |
| `exact_small_instances.json` | Heuristic vs exact optimum comparison |
| `ablation.csv` | SPT baseline → greedy → tabu search improvement |
| `manifest.json` | SHA-256 (16-hex) digest of every result file |

---

### `test_fjsp.py`

11 unit tests covering:

- Generator determinism and instance class correctness
- Validator: overlap, precedence, duration mismatch, malformed entries
- Solver: produces a valid schedule across instance classes
- Metrics: critical path field present and correct
- `validate_instance`: rejects malformed imports
- CLI validator exits with code 1 on bad input

---

## Data Flow Diagram

```
run_submission.py
      │
      ├─ generate_instance()  ──────────────────┐
      │       ↓                                  │
      │   Instance                               │  instances/edge_cases/*.json
      │       │                                  │
      ├─ solve()                                 │
      │       ↓                                  │
      │   list[ScheduledOperation]               │
      │       │                                  │
      ├─ validate()                              │
      │       ↓                                  │
      │   ValidationResult                       │
      │       │                                  │
      ├─ metrics()                               │
      │       ↓                                  │
      │   dict (makespan, CI, gap, ...)          │
      │       │                                  │
      └──────→ results/*.json / *.csv ──────────→ manifest.json
```

---

## Key Design Invariants

1. **Determinism:** All randomness flows through `random.Random(seed)`. Given
   the same seed and parameters, every component produces bit-identical output.

2. **Validator independence:** `fjsp/environment/validator.py` imports zero
   symbols from `fjsp/algorithms/`. It trusts only the `Instance` definition
   and recomputes all timing constraints from scratch.

3. **Feasibility by construction:** `generate_instance` guarantees non-empty
   `E(j,k)`, positive integer durations, and contiguous IDs before returning,
   enforced by a `validate_instance()` assertion at line 149.

4. **State consistency:** After every accepted tabu move, both the `assignments`
   dict and the `priority` dict are rebuilt from the accepted schedule. This
   prevents the assignment-priority drift bug that would otherwise occur when
   N1 moves change machine availability and therefore natural sequencing order.
