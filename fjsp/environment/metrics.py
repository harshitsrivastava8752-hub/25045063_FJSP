"""Schedule quality metrics and exact benchmark solver.

Provides reproducible diagnostics (makespan, utilization, critical path,
lower-bound gap) and an exhaustive branch-and-bound solver for tiny instances.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fjsp.model import Instance, ScheduledOperation
from fjsp.environment.validator import validate


def metrics(instance: Instance, schedule: list[ScheduledOperation]) -> dict[str, Any]:
    """Return reproducible diagnostics used in experiment tables."""
    result = validate(instance, schedule)
    if not result.valid:
        raise ValueError("metrics require a valid schedule")
    by_machine: dict[int, list[ScheduledOperation]] = {m: [] for m in range(instance.machines)}
    by_job = instance.operations_by_job
    for item in schedule:
        by_machine[item.machine].append(item)
    horizon = result.makespan or 0
    utilization = {
        machine: sum(item.end - item.start for item in items) / horizon if horizon else 0.0
        for machine, items in by_machine.items()
    }
    job_chain = max(
        sum(op.options[item.machine] for op, item in zip(by_job[job], sorted(
            [entry for entry in schedule if entry.job == job], key=lambda entry: entry.index)))
        for job in by_job
    )
    machine_sequences = {machine: sorted(items, key=lambda item: (item.start, item.end))
                         for machine, items in by_machine.items()}
    predecessors: dict[tuple[int, int], set[tuple[int, int]]] = {
        (item.job, item.index): set() for item in schedule
    }
    for items in by_job.values():
        ordered = sorted(items, key=lambda item: item.index)
        for previous, current in zip(ordered, ordered[1:]):
            predecessors[(current.job, current.index)].add((previous.job, previous.index))
    for items in machine_sequences.values():
        for previous, current in zip(items, items[1:]):
            predecessors[(current.job, current.index)].add((previous.job, previous.index))
    duration = {(item.job, item.index): item.end - item.start for item in schedule}
    longest: dict[tuple[int, int], int] = {}
    for item in sorted(schedule, key=lambda entry: (entry.start, entry.end)):
        key = (item.job, item.index)
        longest[key] = duration[key] + max(
            (longest[pred] for pred in predecessors[key]), default=0
        )
    critical_path = max(longest.values(), default=0)
    machine_work = max(
        sum(item.end - item.start for item in items) for items in by_machine.values()
    )
    assignment_lb = max(
        sum(min(op.options.values()) for op in operations) for operations in by_job.values()
    )
    lower_bound = max(job_chain, machine_work, assignment_lb)
    return {
        "makespan": result.makespan,
        "job_completion_times": {
            job: max(item.end for item in schedule if item.job == job)
            for job in by_job
        },
        "machine_utilization": utilization,
        "critical_path": critical_path,
        "job_chain_lower_bound": job_chain,
        "max_machine_workload": machine_work,
        "lower_bound": lower_bound,
        "lower_bound_gap": (result.makespan - lower_bound) / lower_bound if lower_bound else 0.0,
    }


def exact_optimum(instance: Instance, limit: int = 9) -> int:
    """Compute the optimum for tiny instances by exhaustive branch-and-bound."""
    if len(instance.operations) > limit:
        raise ValueError(f"exact benchmark supports at most {limit} operations")
    jobs = instance.operations_by_job
    operation_counts = tuple(len(jobs[job]) for job in range(instance.jobs))
    durations = {(op.job, op.index, machine): value
                 for op in instance.operations for machine, value in op.options.items()}

    @lru_cache(maxsize=None)
    def search(next_indices: tuple[int, ...], job_ends: tuple[int, ...],
               machine_ends: tuple[int, ...]) -> int:
        if next_indices == operation_counts:
            return max(job_ends, default=0)
        best = float("inf")
        for job, index in enumerate(next_indices):
            if index >= operation_counts[job]:
                continue
            operation = jobs[job][index]
            for machine in operation.options:
                start = max(job_ends[job], machine_ends[machine])
                end = start + durations[(job, index, machine)]
                next_state = list(next_indices)
                next_state[job] += 1
                new_jobs = list(job_ends)
                new_machines = list(machine_ends)
                new_jobs[job], new_machines[machine] = end, end
                if max(end, *new_jobs) >= best:
                    continue
                best = min(best, search(tuple(next_state), tuple(new_jobs), tuple(new_machines)))
        return best

    return int(search((0,) * instance.jobs, (0,) * instance.jobs, (0,) * instance.machines))
