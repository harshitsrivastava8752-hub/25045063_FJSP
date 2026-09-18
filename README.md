# Flexible Job-Shop Scheduling Toolkit

Submission for the Algo Prepathon (Inter-IIT Tech Meet 15.0): Flexible Job-Shop
Scheduling (FJSP), covering the full pipeline

`Generate -> Validate -> Solve -> Stress Test -> Analyze -> Improve`

Pure Python standard library, Python 3.10+. No third-party dependencies.

## What is inside

- **Generator** (`fjsp/generator/`): reproducible random instances with variable job
  lengths, controllable routing flexibility, Gaussian processing-time variation,
  bottleneck injection, machine specialization and nine named instance classes.
  Every instance stores its seed and generator parameters.
- **Validator and metrics** (`fjsp/environment/`): an independent referee that does not
  trust the solver. It checks completeness, duplicate/unknown operations, machine
  eligibility, durations, negative start times, job precedence and machine overlap,
  and reports clear error messages. It also computes job completion times, makespan,
  machine utilization, the critical path, a lower bound and the lower-bound gap.
  `metrics.py` also has an exact branch-and-bound solver for tiny instances.
- **Solver** (`fjsp/algorithms/solver.py`): lookahead-congestion randomized greedy
  multi-start construction, followed by an adaptive-tenure tabu search with
  critical-block N1 (machine reassignment), N2 (adjacent swap) and N3 (insertion)
  neighbourhoods.
- **Experiments** (`fjsp/experiments/runner.py`, `run_submission.py`): CLI, first
  milestone command, per-class experiments, controlled sweeps, exact-optimum
  benchmark, ablation and hand-built edge-case fixtures.
- **Report**: `REPORT.md` (generator, validator, algorithm, experiments, failure
  analysis). Extra worked examples are in `fjsp/analysis/failure_analysis.md`.

## Quick start

All commands are run from the repository root (works in bash and PowerShell).

```bash
# 1. generate an instance
python -m fjsp.experiments.runner generate --jobs 5 --machines 3 --operations 4 --instance-class average --seed 42 --output instance.json

# 2. solve it (prints schedule + validation + metrics as JSON)
python -m fjsp.experiments.runner solve instance.json --iterations 30 --local-search 100 > schedule.json

# 3. independently validate a schedule (exit code 0 = VALID, 1 = INVALID, 2 = bad input)
python -m fjsp.experiments.runner validate instance.json schedule.json

# first milestone in one command: generate -> solve -> validate -> makespan
python -m fjsp.experiments.runner function-one --instance-class bottleneck --seed 42 --output function_one.json

# repeated experiment over seeds
python -m fjsp.experiments.runner experiment --jobs 10 --machines 5 --operations 5 --instance-class bottleneck --repetitions 20
```

Available `--instance-class` values: `average`, `low_flexibility`, `high_flexibility`,
`bottleneck`, `balanced`, `high_variance`, `machine_advantage`, `extreme`, `unbalanced`.

## Tests

```bash
python -m unittest -v test_fjsp.py
```

11 tests: reproducibility, valid solver output, exact solver check, instance-class
handling, malformed instance import, metrics, and validator rejection of overlap,
wrong duration, precedence violations and malformed schedule entries.

## Reproduce all results

```bash
python run_submission.py          # about 3 minutes; regenerates results/ and instances/edge_cases/
python run_submission.py --clean  # delete results/ first
python run_submission.py 20260910 # optional seed base (default 20260910)
```

Class experiments use 10 seeds (`seed_base` .. `seed_base + 9`), sweeps and the
ablation use 20 seeds (`seed_base` .. `seed_base + 19`). `results/manifest.json`
stores a hash of each result file. Runtimes in the results depend on the machine;
makespans do not.

## Project structure

```
fjsp/
  model.py                    data model (Instance, Operation, ScheduledOperation)
  generator/instance_generator.py   random generator and named classes
  environment/validator.py    independent schedule validator
  environment/metrics.py      metrics, lower bound, exact optimum for tiny instances
  algorithms/solver.py        construction + tabu search
  experiments/runner.py       CLI, function-one, experiment runner
  analysis/failure_analysis.md      worked (hand-traced) failure examples
instances/                    saved instances and edge_cases/ fixtures
results/                      per-class JSON, sweeps, ablation, exact benchmark, manifest
test_fjsp.py                  unit tests
run_submission.py             reproducible result bundle
REPORT.md                     final report
```

## Reading guide

Start with `REPORT.md`. Section 5 lists the measured results and Section 6 the
failure analysis, including one prediction that the experiments did **not** confirm.
`fjsp/analysis/failure_analysis.md` contains small hand-traced examples that
illustrate the mechanisms; they are explanations, not aggregate evidence.
