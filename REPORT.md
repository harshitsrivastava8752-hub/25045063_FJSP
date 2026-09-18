# Flexible Job-Shop Scheduling — Final Report

## 1. Scope and reproducibility

This submission implements the required pipeline:

`Generate -> Validate -> Solve -> Stress Test -> Analyze -> Improve`

It has no third-party runtime dependencies and targets Python 3.10+.
`python run_submission.py` regenerates everything in `results/` and
`instances/edge_cases/` (about 3 minutes). Class experiments use ten seeds
(`20260910` to `20260919`); sweeps and the ablation use twenty seeds
(`20260910` to `20260929`). Every result records generator settings, algorithm
settings, runtime, feasibility, makespan, utilization, critical-path lower bound
and lower-bound gap. `results/manifest.json` holds a hash per result file.
All numbers in this report are copied from the files in `results/`.

Code layout: `fjsp/generator/` (generator), `fjsp/environment/` (validator, metrics),
`fjsp/algorithms/` (solver), `fjsp/experiments/` (CLI and experiment runner).

## 2. Instance generator

**Representation.** An instance stores contiguous job and machine IDs, an ordered
operation list per job, the eligible machines of each operation with one integer
processing time per eligible machine, the seed, the generator parameters and the
instance class. A job has a fixed operation count or a `(min, max)` range.

**Parameters.** jobs, machines, operations per job, flexibility, processing-time
range, noise scale (variance), bottleneck probability, machine advantage, seed and
instance class.

**Eligible machines and flexibility.** For each operation the generator samples
`round(1 + flexibility * (machines - 1))` distinct machines, so at least one.
Flexibility 0 means exactly one machine per operation; 1 means all machines. With
probability `bottleneck_probability` one fixed bottleneck machine (drawn once per
instance) is added to the eligible set of the operation.

**Processing times.** Times are positive integers in `[processing_time_min,
processing_time_max]`. With zero noise they are uniform. With non-zero noise, a
uniformly sampled centre is multiplied by a Gaussian factor and clamped to the
valid range; the noise scale is the variance control. Machine advantage shortens
the times on a specialist machine (drawn separately from the bottleneck machine).

**Randomness.** All choices use a local `random.Random(seed)`. The same
parameters and seed always give the same instance, and the global random state is
never touched.

**Named classes** (overrides applied on top of the caller's parameters):

| Class | Concrete setting |
|---|---|
| low_flexibility | flexibility 0.05 |
| high_flexibility | flexibility 0.95 |
| bottleneck | bottleneck probability at least 0.85 |
| high_variance | noise scale 1.0, time max at least 100 |
| machine_advantage | machine advantage at least 0.8 |
| extreme | flexibility 0.95, noise 1.5, time max 10000, bottleneck probability at least 0.8 |
| balanced | bottleneck probability 0 |
| unbalanced | flexibility 0.5, 1 to 8 operations per job |
| average | no override |

**Why instances are valid by construction.** Every operation gets at least one
eligible machine (the sampled set is never empty). A duration is drawn for exactly
the machines in the set and clamped to at least 1, so times are positive, finite
and defined for no machine outside the set. Job and machine IDs are generated
as contiguous ranges and each job is one linear chain, so there are no duplicate
IDs and no branching. Total operations equal the sum of job lengths. Because every
operation has an eligible machine and jobs are chains, a feasible schedule always
exists (run operations one after another). Input validation rejects bad
parameters, and importing an instance re-checks the structure.

**Known limitation.** Because of rounding, different flexibility values can give
the same eligible-set size (for 5 machines, 0.4 and 0.6 both give 3 machines), so
they produce the same instances. This is visible in the sweep below.

## 3. Independent validation environment

`validate(instance, schedule)` uses no solver state. It rejects: missing,
duplicate or unknown operations; unknown job, operation or machine IDs;
ineligible machine; wrong duration or completion time; negative start time;
precedence violation; machine overlap; malformed or incomplete records. Malformed
records are rejected without crashing. Errors are reported in readable form, for
example the operations and intervals that overlap on a machine.

The CLI command `python -m fjsp.experiments.runner validate instance.json
schedule.json` prints `VALID` with the makespan, or `INVALID` with every error,
and exits with code 1 on an invalid schedule (code 2 on unreadable input).

For valid schedules, `metrics` reconstructs job completion times, machine
utilization, the critical path of the schedule (job and machine edges), a lower
bound and the lower-bound gap. The lower bound is the maximum of the longest job
chain (using minimum times), the machine-work bound and an assignment bound.

**Tests** (`test_fjsp.py`, 11 tests, all passing): reproducibility, solver returns
a valid schedule, validator detects wrong duration and precedence violation,
validator detects overlap, validator rejects malformed entries without crashing,
enriched error messages, instance import rejects invalid structure, metrics include
machine and critical-path data, exact solver matches the single-machine sum,
instance classes apply correctly, and the unbalanced class works.

## 4. Algorithm — construction plus tabu search

**Phase 1 — construction.** `iterations` (default 20; 30 in the experiments)
randomized greedy starts. At each step every ready operation and eligible machine
is scored by `finish_time + congestion_ratio * duration`, where the congestion
ratio uses the current machine load; random tie-breaking gives diverse starts.
Across restarts, an annealing-style rule may accept a slightly worse start so the
pool stays diverse, while the true best schedule is always tracked separately.

**Phase 2 — tabu search.**
- **Representation:** a machine assignment for every operation plus a priority order
  of operations; a schedule is decoded from these.
- **Objective:** minimize makespan.
- **N1:** move a critical operation to another eligible machine.
- **N2:** swap adjacent operations inside a critical block on a machine
  (boundary and interior pairs).
- **N3:** take a critical operation and reinsert it at the opposite end of its
  critical block.
- **Tabu list:** stores `(op, from_machine, to_machine)` for N1 and
  `(op_a, op_b, machine)` for N2 and N3; reverse moves are also made tabu.
- **Adaptive tenure:** base 7, kept between `max(2, base // 2)` and `3 * base`;
  it shrinks by 1 after an improvement and grows by 1 every 5 non-improving
  iterations.
- **Aspiration:** a tabu move is accepted if it beats the best makespan so far.
- **Acceptance:** the best allowed neighbour is taken each iteration even if it
  worsens the current makespan.
- **Budget:** `min(local_search_iterations, max(20, 30000 // number_of_operations))`
  iterations (default 100 local-search iterations).
- **Complexity:** per iteration, the number of candidate moves (bounded by critical
  operations times machines plus block moves) times the cost of re-decoding a
  schedule, which is at least linear in the number of operations.
- **Hyperparameters:** starts 20 to 30, local-search iterations 50 to 100,
  tabu tenure 7.

This is an own design in the spirit of tabu search for FJSP (critical-block
neighbourhoods); it is not a reimplementation of a specific paper.

## 5. Experiments

**Per-class results.** 12 jobs, 6 machines, 5 operations per job (unbalanced: 1 to
8), 10 seeds per class, 30 starts and 100 local-search iterations. Source:
`results/<class>.json`. Runtime is per instance and depends on the machine.

| Class | Mean makespan | Mean lower-bound gap | Mean runtime (ms) |
|---|---:|---:|---:|
| average | 93.3 | 0.088 | 580 |
| balanced | 85.3 | 0.080 | 657 |
| bottleneck | 90.8 | 0.065 | 850 |
| extreme | 5892.6 | 0.047 | 1350 |
| high_flexibility | 69.7 | 0.064 | 1247 |
| high_variance | 148.3 | 0.106 | 609 |
| low_flexibility | 223.5 | 0.080 | 120 |
| machine_advantage | 54.5 | 0.049 | 1090 |
| unbalanced | 88.0 | 0.102 | 672 |

All schedules were valid. The extreme class has very large spread (best 3352,
worst 10291) because a few operations of length up to 10000 dominate the makespan.

**Controlled sweeps** (`results/controlled_sweeps.csv`; 10 jobs, 5 machines,
4 operations, 20 seeds, 20 starts, 50 local-search iterations). Mean makespan:

| Flexibility | 0.0 | 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |
|---|---:|---:|---:|---:|---:|---:|
| Makespan | 132.4 | 79.95 | 55.6 | 55.6 | 46.8 | 39.55 |

| Bottleneck probability | 0.0 | 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |
|---|---:|---:|---:|---:|---:|---:|
| Makespan | 55.6 | 55.3 | 54.15 | 54.05 | 53.65 | 51.7 |

The same file also sweeps noise scale (55.6 at 0, 53.95 at 0.3, 43.65 at 0.6,
38.35 at 1.0, 35.15 at 1.5) and machine advantage (55.6 at 0, 53.9 at 0.2, 47.55 at
0.5, 39.3 at 0.8, 34.65 at 1.0).

**Ablation** (`results/ablation.csv`; 10 jobs, 5 machines, 4 operations, average
class, 20 seeds):

| Method | Mean makespan | Std. dev. |
|---|---:|---:|
| Shortest-processing-time baseline | 83.4 | 12.4 |
| Greedy multi-start (no local search) | 71.55 | 7.7 |
| Greedy multi-start + tabu search | 55.6 | 5.7 |

Tabu search improves the multi-start result by 22.3% and the simple baseline by
33.3%.

**Exact benchmark** (`results/exact_small_instances.json`): 10 tiny instances
(3 jobs, 2 machines, 2 operations per job, flexibility 0.7). The heuristic found
the optimum on 8 of 10 seeds; mean optimality gap 3.1%. These instances are very
small, so this mainly checks correctness, not scaling.

**Edge-case fixtures** (`instances/edge_cases/`): single machine, single job,
many machines, extreme time gap (1 to 10000), long chain, identical times, and
many jobs with a bottleneck. They are regenerated by `run_submission.py` and can be
solved with the CLI.

**First-milestone artifact:** `results/function_one.json` holds one generated
instance, a candidate schedule, the validator result, metrics and the algorithm
configuration.

## 6. Failure analysis

Note on evidence: the lower-bound gap compares makespan to a lower bound, so it
mixes solver loss with weakness of the bound. Makespan alone is not a measure of
difficulty (instances with more noise or flexibility get shorter makespans).
`fjsp/analysis/failure_analysis.md` has small hand-traced examples that illustrate
the mechanisms below; they are explanations, not aggregate evidence.

### Failure mode 1 — high-variance and unbalanced instances have the largest gap

1. **Observation.** The largest mean lower-bound gaps are on high_variance (0.106)
   and unbalanced (0.102), above average (0.088) and balanced (0.080).
2. **Evidence.** The per-class table in Section 5 (10 seeds each). The noise sweep
   shows makespan *falling* with noise (55.6 to 35.15), so the higher gap is not a
   bigger makespan; it is a larger distance from the bound.
3. **Hypothesis.** A few long operations, or one long job, form the critical path.
   The greedy construction decides using the current finish time and does not
   protect the long chain early, and the lower bound cannot see queueing delay on
   that chain.
4. **Structural explanation.** In unbalanced instances the longest job chain is
   much longer than the others, so any delay of its first operation shifts every
   later operation of that job by the same amount. Short jobs that occupy a shared
   machine early delay the critical chain, but they have a lot of slack.
   Sequencing (who goes first on a machine) matters more than assignment.
5. **Proposed improvement (idea only).** Give jobs a priority from their
   remaining chain length in the construction rule, and add critical-block swaps
   that always try to move the critical job's operation first. Also strengthen the
   lower bound (or use an exact solver on small cases) to separate solver loss from
   bound weakness.

### Failure mode 2 — the predicted high-flexibility bottleneck failure was not reproduced

1. **Observation.** We expected high-flexibility, bottleneck-heavy instances to have
   a larger gap than low-flexibility ones. The data does not show this.
2. **Evidence.** high_flexibility has gap 0.064 versus low_flexibility 0.080;
   bottleneck has gap 0.065, below average (0.088). In the sweep, raising
   bottleneck probability from 0 to 1 slightly *lowers* makespan (55.6 to 51.7),
   and raising flexibility from 0 to 1 lowers it a lot (132.4 to 39.55).
3. **Hypothesis.** In this generator the bottleneck injection only *adds* the
   bottleneck machine to an operation's eligible set; it does not remove the
   alternatives. With flexibility above zero the solver can route around it, so no
   real contention appears. Genuine contention needs operations whose only
   eligible machine is the shared one.
4. **Structural explanation.** Contention only becomes hard when assignment
   freedom disappears (many operations forced onto one machine, so the problem
   becomes pure sequencing on that machine). Extra flexibility mostly adds options
   the solver can use, and at this size (about 60 operations, 6 machines) the
   congestion-aware construction plus tabu search absorbs the larger search space.
   We did not test larger sizes, so the early-commitment effect may appear there.
5. **Proposed improvement (idea only).** Add a bottleneck mode that restricts a
   fraction of operations to the bottleneck machine only, run a
   flexibility-by-bottleneck grid over many seeds and larger instances, and
   compare the gap. If early commitment appears, add a lookahead cost for machine
   choice or a repair step that re-assigns operations on the bottleneck's critical
   block.

### Failure mode 3 — more search budget did not help on the same instances

1. **Observation.** Two different search budgets gave exactly the same result on
   the baseline instances.
2. **Evidence.** The sweep row at flexibility 0.4 (20 starts, 50 local-search
   iterations) and the ablation row for greedy + tabu (30 starts, 100 iterations)
   both report mean 55.6 and std. dev. 5.68 over the same 20 seeds.
3. **Hypothesis.** The search reaches the same solution (possibly optimal, possibly
   a local optimum) within the smaller budget, so extra iterations have nothing
   to find. We cannot tell which from the current data.
4. **Structural explanation.** The neighbourhoods only act on critical blocks. Once
   no critical move improves the makespan, tabu tenure and aspiration only
   reshuffle equivalent schedules, and the restarts all feed the same basin.
5. **Proposed improvement (idea only).** Add diversification (restart the tabu phase
   from perturbed schedules, or path relinking between good schedules) and compare
   against an exact or CP-SAT result on mid-sized instances to check whether the
   plateau is optimal.

### Other observations

- **Low flexibility** is the hardest structurally: makespan 132.4 at flexibility 0
  versus 39.55 at flexibility 1, yet the gap (0.080) is about average. The loss is
  mostly forced by the instance (no assignment choice), not by the solver, and the
  runtime is the lowest (120 ms) because the neighbourhood is small.
- **Extreme instances** have the smallest gap (0.047) but a very large makespan
  spread; a handful of operations of length up to 10000 decide the result, so
  averages over 10 seeds are unstable (best 3352, worst 10291).
- **Flexibility quantization** (Section 2) makes some flexibility levels identical.

## 7. Limitations

- No scaling study on large instances; the largest experiments have about 60
  operations, so scalability claims are not made.
- The lower bound is weak, so gaps are only upper estimates of solver loss.
- The exact benchmark uses very small instances (12 operations at most).
- No comparison against MILP or CP-SAT, and no comparison with a published FJSP
  algorithm.
- Failure mode 2 is an untested prediction; the proposed experiments are not run.

## 8. Submission contents

- `fjsp/` — generator, validator, metrics, solver, experiment runner and analysis notes.
- `test_fjsp.py` — 11 correctness tests including invalid-schedule rejection.
- `run_submission.py` — reproducible experiment runner.
- `instances/` — saved instances and edge-case fixtures.
- `results/` — per-class JSON, sweeps, ablation, exact benchmark, manifest.
- `README.md` — usage and project overview.
