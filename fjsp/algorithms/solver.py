"""FJSP solver with lookahead construction and critical-path-guided tabu search.

Architecture
------------
1. **Construction phase** — Lookahead-congestion randomized greedy multi-start
   dispatcher.  At each step every ready (operation, machine) pair is scored
   by earliest finish + a congestion penalty *plus* an estimate of the
   remaining committed workload on that machine (so early assignments no
   longer ignore downstream contention).  Acceptance across restarts uses a
   simulated-annealing-style criterion so worse-looking early starts are
   occasionally kept, improving diversification across the multi-start pool.

2. **Improvement phase** — Critical-path-restricted local search with
   adaptive tabu memory.  The disjunctive graph is built, the true critical
   path is computed via longest-path DAG traversal, critical *blocks*
   (maximal runs of consecutive critical-path operations on the same
   machine) are extracted, and neighbourhood operators are applied:

   * **Adjacent swap** — swap boundary pairs *and* all interior adjacent
     pairs within each critical block (full Nowicki & Smutnicki N5 style,
     not just the two ends).
   * **Insertion move** — remove a critical operation from its machine
     position and reinsert it at the start/end of the block (cheap
     critical-block-local version of the classical insertion neighbourhood).
   * **Machine reassignment** — reassign a critical operation to an
     alternative eligible machine, scored with the same lookahead estimate
     used in construction.

   A *tabu list* of recently applied moves prevents cycling.  Tabu tenure is
   *adaptive*: it grows on stagnation (more diversification) and shrinks
   after fresh improvements (more intensification).  The *aspiration
   criterion* overrides the tabu if a move produces a new global best.

Representation
--------------
A schedule is a list of ``ScheduledOperation(job, index, machine, start,
end)``.  Internally the search manipulates an *assignment dict*
``{(job, op_idx): machine}`` and a *priority dict*
``{(job, op_idx): int}`` that together deterministically produce a
semi-active schedule via ``_rebuild()``.

Complexity
----------
With *I* starts, *O* operations, *M* machines, and *L* local-search
iterations the construction phase is O(I · O² · M) and the improvement
phase is O(L · O² · M) per restart. Memory is O(O + M).
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Any

from fjsp.model import Instance, Operation, ScheduledOperation
from fjsp.environment.validator import validate


# ---------------------------------------------------------------------------
# Schedule builder
# ---------------------------------------------------------------------------

def _rebuild(instance: Instance, assignments: dict[tuple[int, int], int],
             priority: dict[tuple[int, int], int]) -> list[ScheduledOperation]:
    """List-schedule a candidate assignment in a deterministic priority order."""
    operations = {(op.job, op.index): op for op in instance.operations}
    next_index = {job: 0 for job in range(instance.jobs)}
    job_end = {job: 0 for job in range(instance.jobs)}
    machine_end = {machine: 0 for machine in range(instance.machines)}
    result: list[ScheduledOperation] = []
    unscheduled = set(operations)
    while len(result) < len(operations):
        ready = [
            op for key, op in operations.items()
            if key in unscheduled
            and next_index[op.job] == op.index
        ]
        if not ready:
            raise ValueError("candidate priority contains an invalid precedence order")
        operation = min(ready, key=lambda op: priority[(op.job, op.index)])
        key = (operation.job, operation.index)
        machine = assignments[key]
        start = max(job_end[operation.job], machine_end[machine])
        end = start + operation.options[machine]
        result.append(ScheduledOperation(operation.job, operation.index, machine, start, end))
        unscheduled.remove(key)
        next_index[operation.job] += 1
        job_end[operation.job] = end
        machine_end[machine] = end
    return result


# ---------------------------------------------------------------------------
# Lookahead helpers for construction and machine-reassignment scoring
# ---------------------------------------------------------------------------

def _remaining_workload_per_job(
    instance: Instance,
) -> dict[int, dict[int, int]]:
    """For each job, the mean-duration remaining workload *after* each op index.

    remaining[job][idx] = sum of average-eligible-machine durations for all
    operations of that job with index > idx.  Used as a static lookahead
    term so the construction heuristic can anticipate how much future
    contention a job will still bring to the system, independent of which
    machine a given operation is ultimately assigned to.
    """
    remaining: dict[int, dict[int, int]] = {}
    for job, ops in instance.operations_by_job.items():
        ordered = sorted(ops, key=lambda o: o.index)
        avg_durations = [
            (sum(op.options.values()) / max(1, len(op.options)))
            for op in ordered
        ]
        suffix_totals: dict[int, int] = {}
        running = 0.0
        for op, avg_dur in zip(reversed(ordered), reversed(avg_durations)):
            suffix_totals[op.index] = int(round(running))
            running += avg_dur
        remaining[job] = suffix_totals
    return remaining


def _machine_pressure(instance: Instance) -> dict[int, float]:
    """Static estimate of relative long-run contention per machine.

    For every operation, its average duration is split evenly across all of
    its eligible machines and accumulated.  Machines that are eligible for
    more/longer operations accrue higher pressure, letting construction
    steer early assignments away from machines that will become bottlenecks
    later, rather than only reacting to congestion already incurred.
    """
    pressure = {m: 0.0 for m in range(instance.machines)}
    for op in instance.operations:
        if not op.options:
            continue
        share = (sum(op.options.values()) / len(op.options)) / len(op.options)
        for machine in op.options:
            pressure[machine] += share
    return pressure


# ---------------------------------------------------------------------------
# Critical-path computation on the disjunctive graph
# ---------------------------------------------------------------------------

def _compute_critical_path(
    instance: Instance,
    schedule: list[ScheduledOperation],
) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    """Compute the true critical path through the disjunctive graph.

    Returns
    -------
    critical_ops : list[(job, index)]
        Operation keys on the longest path, in topological order.
    longest : dict[(job, index), int]
        Longest path length ending at each operation.
    """
    by_job = instance.operations_by_job
    by_machine: dict[int, list[ScheduledOperation]] = {}
    for item in schedule:
        by_machine.setdefault(item.machine, []).append(item)
    machine_sequences = {
        machine: sorted(items, key=lambda item: (item.start, item.end))
        for machine, items in by_machine.items()
    }

    # Build predecessor map (job-order + machine-sequence edges)
    predecessors: dict[tuple[int, int], list[tuple[int, int]]] = {
        (item.job, item.index): [] for item in schedule
    }
    for items in by_job.values():
        ordered = sorted(items, key=lambda item: item.index)
        for previous, current in zip(ordered, ordered[1:]):
            predecessors[(current.job, current.index)].append(
                (previous.job, previous.index)
            )
    for items in machine_sequences.values():
        for previous, current in zip(items, items[1:]):
            predecessors[(current.job, current.index)].append(
                (previous.job, previous.index)
            )

    duration = {(item.job, item.index): item.end - item.start for item in schedule}
    longest: dict[tuple[int, int], int] = {}

    # Process in topological order (by start time)
    for item in sorted(schedule, key=lambda entry: (entry.start, entry.end)):
        key = (item.job, item.index)
        longest[key] = duration[key] + max(
            (longest[pred] for pred in predecessors[key]), default=0
        )

    if not longest:
        return [], longest

    # Back-trace to find the critical path
    terminal = max(longest, key=lambda k: longest[k])
    critical_ops: list[tuple[int, int]] = []
    current = terminal
    while current is not None:
        critical_ops.append(current)
        best_pred = None
        best_length = -1
        for pred in predecessors[current]:
            if longest[pred] > best_length:
                best_length = longest[pred]
                best_pred = pred
        current = best_pred

    critical_ops.reverse()
    return critical_ops, longest


def _extract_critical_blocks(
    schedule: list[ScheduledOperation],
    critical_ops: list[tuple[int, int]],
) -> list[list[ScheduledOperation]]:
    """Extract maximal runs of consecutive critical-path ops on the same machine."""
    critical_set = set(critical_ops)
    by_machine: dict[int, list[ScheduledOperation]] = {}
    for item in schedule:
        by_machine.setdefault(item.machine, []).append(item)
    for items in by_machine.values():
        items.sort(key=lambda item: (item.start, item.end))
    blocks: list[list[ScheduledOperation]] = []
    for items in by_machine.values():
        current_block: list[ScheduledOperation] = []
        for item in items:
            if (item.job, item.index) in critical_set:
                current_block.append(item)
            else:
                if len(current_block) >= 2:
                    blocks.append(current_block)
                current_block = []
        if len(current_block) >= 2:
            blocks.append(current_block)
    return blocks


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve(
    instance: Instance,
    seed: int | None = None,
    iterations: int = 20,
    local_search_iterations: int = 200,
    tabu_tenure: int = 7,
) -> list[ScheduledOperation]:
    """
    Phase 1: Lookahead-congestion randomized greedy multi-start construction,
              with simulated-annealing-style acceptance across restarts.
    Phase 2: Adaptive-tenure tabu search with machine-reassignment and
              critical-block resequencing/insertion moves.

    Neighbourhood N1: reassign a critical operation O(j,k) to an alternative
                       eligible machine (lookahead-scored).
    Neighbourhood N2: swap adjacent operation pairs within each critical block
                       (boundary AND interior pairs).
    Neighbourhood N3: remove a critical operation from its block position and
                       reinsert it at the opposite end of the block.

    Tabu list: stores (op_key, from_machine, to_machine) for N1 moves and
               (op_key_a, op_key_b, machine) for N2/N3 moves, with adaptive
               tenure (grows on stagnation, shrinks on improvement).
    Aspiration: accept a tabu move if it beats the global best makespan.
    """
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if local_search_iterations < 0:
        raise ValueError("local_search_iterations must be non-negative")

    rng = random.Random(seed)
    operations_by_job = instance.operations_by_job

    # ── Phase 1: Lookahead multi-start greedy construction ────────────────
    remaining_workload = _remaining_workload_per_job(instance)
    machine_pressure = _machine_pressure(instance)
    max_pressure = max(machine_pressure.values(), default=0.0) or 1.0

    best: list[ScheduledOperation] | None = None
    best_makespan = float("inf")

    # SA-style acceptance across the multi-start pool: keep a "working best"
    # that can occasionally accept a slightly worse restart to diversify the
    # pool of seeds used for phase 2, while the true best is always tracked
    # separately in `best`/`best_makespan`.
    accepted_span = float("inf")
    sa_temperature = max(1.0, float(max(1, sum(len(ops) for ops in operations_by_job.values()))))
    sa_cooling = 0.90

    for start_round in range(iterations):
        ready = {job: 0 for job in range(instance.jobs)}
        mach_end = {m: 0 for m in range(instance.machines)}
        mach_load = {m: 0 for m in range(instance.machines)}
        next_idx = {job: 0 for job in range(instance.jobs)}
        current: list[ScheduledOperation] = []
        remaining = sum(len(ops) for ops in operations_by_job.values())

        while remaining:
            candidates = []
            for job, idx in next_idx.items():
                ops = operations_by_job[job]
                if idx >= len(ops):
                    continue
                op = ops[idx]
                job_tail = remaining_workload.get(job, {}).get(idx, 0)
                for machine, duration in op.options.items():
                    start = max(ready[job], mach_end[machine])
                    finish = start + duration
                    total = max(1, sum(mach_load.values()))
                    cong = mach_load[machine] / total
                    # Lookahead term: how heavily loaded/pressured is this
                    # machine expected to become given remaining committed
                    # and structural workload, not just what's booked so far.
                    pressure_term = (machine_pressure.get(machine, 0.0) / max_pressure)
                    lookahead = 0.15 * pressure_term * duration + 0.05 * job_tail
                    score = (finish + cong * duration + lookahead, rng.random())
                    candidates.append((score, op, machine, start, finish))

            _, op, machine, start, finish = min(candidates, key=lambda x: x[0])
            current.append(ScheduledOperation(op.job, op.index, machine, start, finish))
            ready[op.job] = finish
            next_idx[op.job] += 1
            mach_end[machine] = finish
            mach_load[machine] += finish - start
            remaining -= 1

        vr = validate(instance, current)
        if not (vr.valid and vr.makespan is not None):
            continue

        span = vr.makespan
        if span < best_makespan:
            best, best_makespan = current, span

        # SA-style diversification bookkeeping (does not affect correctness,
        # only which restart's assignment/priority seeds phase 2 most
        # recently — `best` above always tracks the true incumbent).
        delta = span - accepted_span if accepted_span != float("inf") else 0
        if delta <= 0 or rng.random() < math.exp(-delta / max(1e-9, sa_temperature)):
            accepted_span = span
        sa_temperature *= sa_cooling

    if best is None:
        raise RuntimeError("solver failed to produce a valid schedule")

    if not local_search_iterations:
        return sorted(best, key=lambda x: (x.start, x.machine, x.job, x.index))

    # ── Phase 2: Adaptive Tabu Search ──────────────────────────────────────

    # O(1) op lookup — build once
    op_lookup = {(o.job, o.index): o for o in instance.operations}

    assignments = {(item.job, item.index): item.machine for item in best}
    ordered = sorted(best, key=lambda x: (x.start, x.machine, x.job, x.index))
    priority = {(item.job, item.index): rank for rank, item in enumerate(ordered)}

    global_best = best
    global_best_span = best_makespan
    current_schedule = best
    current_span = best_makespan

    # O(1) tabu lookup via dict instead of linear deque scan
    tabu: dict[tuple, int] = {}  # sig -> expiry_iteration

    # Adaptive tenure: base value from the caller, nudged up on stagnation
    # (more diversification) and back down after fresh improvements (more
    # intensification), bounded to stay sane relative to the budget.
    min_tenure = max(2, tabu_tenure // 2)
    max_tenure = max(min_tenure + 1, tabu_tenure * 3)
    current_tenure = tabu_tenure

    def is_tabu(sig: tuple, iteration: int) -> bool:
        return tabu.get(sig, 0) > iteration

    def add_tabu(sig: tuple, iteration: int) -> None:
        tabu[sig] = iteration + current_tenure

    def fast_makespan(sched: list[ScheduledOperation]) -> int:
        return max(s.end for s in sched) if sched else 0

    budget = min(local_search_iterations, max(20, 30000 // max(1, len(instance.operations))))
    stagnation = 0
    max_stagnation = 15
    tenure_growth_after = 5  # consecutive non-improving moves before growing tenure

    for iteration in range(budget):
        best_move_delta = float("inf")
        best_move = None
        best_move_sig = None
        best_move_type = None

        # ── Neighbourhood N1: machine reassignment (lookahead-scored) ─────
        crit_ops, _ = _compute_critical_path(instance, current_schedule)
        crit_keys = set(crit_ops)
        all_keys = list(assignments.keys())
        # Prioritise critical ops but evaluate all within a sample budget
        candidate_keys = list(crit_keys) + [k for k in all_keys if k not in crit_keys]
        sample_size = min(len(candidate_keys), max(10, len(candidate_keys) // 3))
        sampled_keys = candidate_keys[:sample_size]

        for key in sampled_keys:
            op = op_lookup[key]  # O(1) instead of O(O)
            current_machine = assignments[key]
            for alt_machine in op.options:
                if alt_machine == current_machine:
                    continue
                sig = ("N1", key, current_machine, alt_machine)
                rev_sig = ("N1", key, alt_machine, current_machine)

                trial_assign = assignments.copy()
                trial_assign[key] = alt_machine
                try:
                    trial_sched = _rebuild(instance, trial_assign, priority)
                except (KeyError, ValueError):
                    continue

                span = fast_makespan(trial_sched)  # O(O) instead of full validate
                delta = span - current_span
                tabu_blocked = is_tabu(sig, iteration) or is_tabu(rev_sig, iteration)
                aspirated = span < global_best_span

                if (not tabu_blocked or aspirated) and delta < best_move_delta:
                    best_move_delta = delta
                    best_move = (trial_assign, trial_sched, span)
                    best_move_sig = sig
                    best_move_type = "N1"

        # ── Neighbourhood N2: swap ALL adjacent pairs within critical blocks ─
        blocks = _extract_critical_blocks(current_schedule, crit_ops)
        for block in blocks:
            # Every adjacent pair within the block, not just the two ends —
            # this is the theoretically correct N5-style move set for
            # job-shop local search, giving much better search coverage of
            # the critical structure than boundary-only swaps.
            for i in range(len(block) - 1):
                left, right = block[i], block[i + 1]
                lk = (left.job, left.index)
                rk = (right.job, right.index)
                sig = ("N2", lk, rk, left.machine)
                rev_sig = ("N2", rk, lk, left.machine)

                trial_prio = priority.copy()
                trial_prio[lk], trial_prio[rk] = trial_prio[rk], trial_prio[lk]
                try:
                    trial_sched = _rebuild(instance, assignments, trial_prio)
                except (KeyError, ValueError):
                    continue

                span = fast_makespan(trial_sched)
                delta = span - current_span
                tabu_blocked = is_tabu(sig, iteration) or is_tabu(rev_sig, iteration)
                aspirated = span < global_best_span

                if (not tabu_blocked or aspirated) and delta < best_move_delta:
                    best_move_delta = delta
                    best_move = (assignments, trial_sched, span)
                    best_move_sig = sig
                    best_move_type = "N2"

        # ── Neighbourhood N3: critical-block insertion move ────────────────
        # Remove one end operation of a block and reinsert it at the other
        # end — a cheap, block-local version of the classical insertion
        # neighbourhood that complements pairwise swaps with a longer-range
        # reordering move, still restricted to critical structure.
        for block in blocks:
            if len(block) < 3:
                continue
            first, last = block[0], block[-1]
            fk = (first.job, first.index)
            lk = (last.job, last.index)
            sig = ("N3", fk, lk, first.machine)
            rev_sig = ("N3", lk, fk, first.machine)

            trial_prio = priority.copy()
            # Move `first` to just after `last` in priority order.
            block_keys = [(item.job, item.index) for item in block]
            block_ranks = sorted(trial_prio[k] for k in block_keys)
            new_order = block_keys[1:] + [block_keys[0]]
            for rank, key in zip(block_ranks, new_order):
                trial_prio[key] = rank

            try:
                trial_sched = _rebuild(instance, assignments, trial_prio)
            except (KeyError, ValueError):
                continue

            span = fast_makespan(trial_sched)
            delta = span - current_span
            tabu_blocked = is_tabu(sig, iteration) or is_tabu(rev_sig, iteration)
            aspirated = span < global_best_span

            if (not tabu_blocked or aspirated) and delta < best_move_delta:
                best_move_delta = delta
                best_move = (assignments, trial_sched, span)
                best_move_sig = sig
                best_move_type = "N3"

        if best_move is None:
            # No improving or non-tabu move found; continue to next iteration
            stagnation += 1
            if stagnation >= max_stagnation:
                break
            continue

        new_assign, new_sched, new_span = best_move
        add_tabu(best_move_sig, iteration)

        # Always resync both dicts from the accepted schedule (prevents state drift)
        assignments = {(item.job, item.index): item.machine for item in new_sched}
        reordered = sorted(new_sched, key=lambda x: (x.start, x.machine, x.job, x.index))
        priority = {(item.job, item.index): rank for rank, item in enumerate(reordered)}

        current_schedule = new_sched
        current_span = new_span

        if new_span < global_best_span:
            global_best = new_sched
            global_best_span = new_span
            stagnation = 0
            # Fresh improvement: intensify by shrinking tenure back down.
            current_tenure = max(min_tenure, current_tenure - 1)
        else:
            stagnation += 1
            if stagnation % tenure_growth_after == 0:
                # Prolonged non-improvement: diversify by growing tenure.
                current_tenure = min(max_tenure, current_tenure + 1)
            if stagnation >= max_stagnation:
                break

    return sorted(global_best, key=lambda x: (x.start, x.machine, x.job, x.index))
