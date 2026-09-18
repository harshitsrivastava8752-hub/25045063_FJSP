# Flexible Job-Shop Scheduling Toolkit

This project implements the complete experimental pipeline for the Algo Prepathon
Flexible Job-Shop Scheduling problem:

`Generate -> Solve -> Validate -> Measure -> Experiment`

It uses only the Python standard library (Python 3.10+). The generator supports
variable job lengths, controllable routing flexibility, Gaussian processing-time
variation, bottleneck injection, machine specialization, named instance classes,
and reproducible seeds. The solver is a lookahead-congestion randomized greedy
multi-start construction followed by an adaptive-tenure tabu search with
critical-path-guided N1 (machine reassignment), N2 (adjacent swap), and N3
(insertion) neighbourhoods. The independent evaluator computes feasibility,
makespan, utilization, critical-path lower bound, and lower-bound gap.

## Quick start

```powershell
python fjsp.py generate --jobs 5 --machines 3 --operations 4 --instance-class average --seed 42 --output instance.json
python fjsp.py solve instance.json --iterations 30 --local-search 100
python fjsp.py validate instance.json schedule.json
python fjsp.py function-one --instance-class bottleneck --seed 42 --output function_one.json
python fjsp.py experiment --jobs 10 --machines 5 --operations 5 --instance-class bottleneck --repetitions 20
python -m unittest -v
python run_submission.py
```

Every generated instance records its seed and parameters. Reusing the same
parameters and seed produces the same instance. The validator independently
checks completeness, duplicate and unknown operations, machine eligibility,
durations, non-negative intervals, job precedence, and machine overlap. See
`REPORT.md` for the algorithm description, experiment design, results, and
failure analysis.

## Project structure

- `fjsp.py`: data model, generator, validator, metrics, solver, CLI, and experiments.
- `fjsp/algorithms/solver.py`: lookahead construction and critical-path-guided
  adaptive tabu search implementation.
- `test_fjsp.py`: reproducibility, valid-schedule, and validator tests.
- `run_submission.py`: creates the reproducible experiment result bundle.
- `REPORT.md`: final submission report.
- `results/`: generated aggregate and per-instance experiment results.

The heuristic combines a lookahead-aware construction phase with critical-path
local search. It remains a defensible baseline for the required reasoning
task: it is expected to perform worse when high flexibility and bottleneck
contention enlarge the assignment/search trade-off.

## Run
python -m unittest -v test_fjsp.py
python run_submission.py
