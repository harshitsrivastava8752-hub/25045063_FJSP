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
python -m fjsp.experiments.runner generate --jobs 5 --machines 3 --operations 4 --instance-class average --seed 42 --output instance.json
python -m fjsp.experiments.runner solve instance.json --iterations 30 --local-search 100
python -m fjsp.experiments.runner validate instance.json schedule.json
python -m fjsp.experiments.runner function-one --instance-class bottleneck --seed 42 --output function_one.json
python -m fjsp.experiments.runner experiment --jobs 10 --machines 5 --operations 5 --instance-class bottleneck --repetitions 20
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

- `fjsp/model.py`: core data model (Instance, Operation, ScheduledOperation).
- `fjsp/generator/instance_generator.py`: random instance generator and named classes.
- `fjsp/environment/validator.py`: independent schedule validator.
- `fjsp/environment/metrics.py`: metrics, exact optimum, lower-bound gap.
- `fjsp/algorithms/solver.py`: lookahead construction and critical-path-guided
  adaptive tabu search implementation.
- `fjsp/experiments/runner.py`: CLI, first-milestone function, and experiment runner.
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

is this correct or still incorrect just y/n
