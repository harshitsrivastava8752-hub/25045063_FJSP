# Causal Failure Analysis — FJSP Greedy & Tabu Search Scheduler

## Executive Summary & Analytical Framework

This document diagnoses where and why the construction-plus-tabu-search solver
loses quality, using only aggregate evidence from `results/` (per-class runs,
`controlled_sweeps.csv`, `ablation.csv`) — no hand-constructed toy instances.
The lower-bound gap mixes solver loss with weakness of the bound, and makespan
alone is not a difficulty measure (noisier/more flexible instances often get
*shorter* makespans), so both are reported together.

Framework per failure mode:
1. **Observation** — the metric discrepancy.
2. **Evidence** — the specific result file(s) and numbers.
3. **Hypothesis** — the algorithmic mechanism proposed to cause it.
4. **Structural explanation** — why the instance structure produces that effect.
5. **Proposed improvement** — an untested idea, clearly labeled as such.

---

## Failure Mode 1: High-variance and unbalanced instances have the largest lower-bound gap

### 1. Observation
Across the nine named instance classes (10 seeds each, `results/<class>.json`),
high_variance and unbalanced have the two largest mean lower-bound gaps.

### 2. Evidence
| Class | Mean gap |
|---|---:|
| high_variance | 0.106 |
| unbalanced | 0.102 |
| average | 0.088 |
| balanced | 0.080 |

The noise sweep in `controlled_sweeps.csv` shows mean makespan *falling* as
noise scale rises (55.6 at 0.0 → 35.15 at 1.5), so the larger gap on
high_variance is not caused by a larger makespan — it is a larger distance
from the lower bound.

### 3. Hypothesis
The greedy construction phase scores candidates by current finish time plus a
congestion term computed from the current machine load. It has no lookahead
on how much slack a job's remaining chain has, so it does not protect
long-duration operations from being queued behind shorter ones.

### 4. Structural explanation
In unbalanced instances, job chain lengths differ sharply (unbalanced allows
1–8 operations per job). A delay to the first operation of the longest chain
propagates additively through every later operation of that job, while a
short job that causes the delay may have large unused slack. The lower bound
(longest job chain, machine-work bound, assignment bound) does not model this
queueing delay, so it understates achievable makespan and the measured gap is
inflated by bound weakness as well as solver loss — the two are not separated
by the current metrics.

### 5. Proposed improvement (idea only, not implemented)
Add a remaining-chain-length term to the construction score so long jobs are
prioritized earlier, and add a lower bound that accounts for machine
queueing (e.g., a two-machine bottleneck bound) to separate bound weakness
from solver loss.

---

## Failure Mode 2: The predicted high-flexibility/bottleneck failure was not reproduced

### 1. Observation
We expected instances combining high routing flexibility with heavy bottleneck
contention to show a larger lower-bound gap than low-flexibility instances.
The data does not support this.

### 2. Evidence
| Class | Mean gap |
|---|---:|
| high_flexibility | 0.064 |
| low_flexibility | 0.080 |
| bottleneck | 0.065 |
| average | 0.088 |

In `controlled_sweeps.csv`, raising bottleneck probability from 0.0 to 1.0
slightly *lowers* mean makespan (55.6 → 51.7), and raising flexibility from
0.0 to 1.0 lowers it sharply (132.4 → 39.55). Neither sweep shows the
expected failure pattern.

### 3. Hypothesis
The generator's bottleneck mechanism only *adds* the bottleneck machine to an
operation's eligible set — it does not remove alternatives. As soon as
flexibility is above zero, the solver can route around the bottleneck machine,
so genuine contention never forms.

### 4. Structural explanation
Contention only becomes a hard sequencing problem when assignment freedom is
removed (operations forced onto one shared machine). At the tested sizes
(~60 operations, 6 machines), the congestion-aware construction plus tabu
search's critical-block moves are enough to absorb the added routing options
before contention can bind. Larger instances or a stricter bottleneck
(operations restricted to *only* the bottleneck machine) were not tested.

### 5. Proposed improvement (idea only, not implemented)
Add a generator mode that restricts a fraction of operations to the
bottleneck machine exclusively, then run a flexibility × bottleneck-probability
grid over many seeds and larger instances to see if the predicted failure
appears at scale. If the report cannot show this failure with real data, it
should state plainly that the hypothesis was not confirmed — which is what
Section 6 of `REPORT.md` currently does.

---

## Failure Mode 3: Additional search budget did not improve results on the same instances

### 1. Observation
Two different search budgets produced statistically identical results on
directly comparable instances.

### 2. Evidence
- `controlled_sweeps.csv`, flexibility = 0.4 row (10 jobs, 5 machines,
  4 operations, 20 starts, 50 local-search iterations, 20 seeds): mean
  makespan 55.6, std. dev. 5.68.
- `ablation.csv`, `greedy_plus_local_search` row (same instance family, 30
  starts, 100 local-search iterations, 20 seeds): mean makespan 55.6, std.
  dev. 5.68.

The two configurations, run at different search budgets, report the same
mean and standard deviation over the same seed set.

### 3. Hypothesis
The search converges to the same solution (optimal or a shared local optimum)
well within the smaller budget, so the extra starts and iterations in the
larger budget find nothing new. The current data cannot distinguish these two
explanations.

### 4. Structural explanation
The tabu neighborhoods (N1, N2, N3) act only on critical-block operations.
Once no critical move reduces makespan, additional tenure and aspiration
cycling only reorders schedules of equal cost, and additional greedy restarts
draw from the same basin of attraction because the construction heuristic is
deterministic apart from tie-breaking.

### 5. Proposed improvement (idea only, not implemented)
Add diversification — restart tabu search from perturbed schedules, or add
path relinking between distinct good schedules — and compare against an exact
or CP-SAT solution on mid-sized instances to check whether the plateau found
is actually optimal.

---

## Summary

| Failure mode | Backed by | Status |
|---|---|---|
| High-variance/unbalanced gap | Per-class table + noise/nothing-else sweep | Confirmed in aggregate data |
| High-flexibility bottleneck failure | Per-class table + flexibility/bottleneck sweeps | **Not reproduced** — hypothesis rejected by the data |
| Budget plateau | Sweep row vs. ablation row (same seeds) | Confirmed; cause (optimum vs. local optimum) unresolved |

All three modes are read directly from `results/`; no instance was
hand-constructed or hand-traced to produce these numbers. Failure mode 2 is
reported as an honest negative result rather than fabricated to match the
original hypothesis.
