"""Independent schedule validator for the Flexible Job-Shop Scheduling Problem.

Checks completeness, timing, eligibility, precedence, and overlap constraints.
Error messages include exact job/operation IDs, machine IDs, and interval
boundaries for actionable diagnostics.
"""

from __future__ import annotations

from fjsp.model import Instance, ScheduledOperation, ValidationResult


def validate(instance: Instance, schedule: list[ScheduledOperation]) -> ValidationResult:
    """Independently verify completeness, timing, eligibility, precedence, and overlap.

    Every error message includes the specific operation IDs, machine IDs, and
    time intervals involved so that a user can pinpoint the exact fault.
    """
    errors: list[str] = []
    expected = {(op.job, op.index): op for op in instance.operations}
    seen: set[tuple[int, int]] = set()
    by_job: dict[int, list[ScheduledOperation]] = {}
    by_machine: dict[int, list[ScheduledOperation]] = {}

    if not isinstance(schedule, list):
        return ValidationResult(False, None, ["malformed schedule: expected a list"])
    for position, item in enumerate(schedule):
        if not isinstance(item, ScheduledOperation):
            errors.append(f"malformed schedule entry at position {position}")
            continue
        values = (item.job, item.index, item.machine, item.start, item.end)
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            errors.append(f"malformed values in schedule entry at position {position}")
            continue
        key = (item.job, item.index)
        if key in seen:
            errors.append(f"duplicate operation J{item.job}-O{item.index}")
            continue
        seen.add(key)
        operation = expected.get(key)
        if operation is None:
            max_ops = sum(1 for op in instance.operations if op.job == item.job)
            errors.append(
                f"unknown operation J{item.job}-O{item.index} "
                f"(job {item.job} has {max_ops} operation(s))"
            )
            continue

        # --- Eligibility check with actionable detail ---
        duration = operation.options.get(item.machine)
        if duration is None:
            eligible_str = ", ".join(f"M{m}" for m in sorted(operation.options))
            errors.append(
                f"Machine M{item.machine} is not eligible for J{item.job}-O{item.index} "
                f"(eligible: {eligible_str})"
            )

        # --- Interval validity and duration check ---
        if item.start < 0 or item.end <= item.start:
            errors.append(
                f"invalid interval for J{item.job}-O{item.index}: [{item.start}, {item.end})"
            )
        elif duration is not None and item.end - item.start != duration:
            errors.append(
                f"Wrong duration for J{item.job}-O{item.index} on M{item.machine}: "
                f"expected {duration}, got {item.end - item.start}"
            )

        by_job.setdefault(item.job, []).append(item)
        by_machine.setdefault(item.machine, []).append(item)

    # --- Missing operations ---
    missing = set(expected) - seen
    errors.extend(f"missing operation J{job}-O{index}" for job, index in sorted(missing))

    # --- Precedence violations with interval details ---
    for job, items in by_job.items():
        items.sort(key=lambda item: item.index)
        for previous, current in zip(items, items[1:]):
            if previous.end > current.start:
                errors.append(
                    f"Precedence violation in J{job}: "
                    f"O{previous.index} ends at {previous.end} but "
                    f"O{current.index} starts at {current.start}"
                )

    # --- Machine overlap with full interval details ---
    for machine, items in by_machine.items():
        items.sort(key=lambda item: (item.start, item.end))
        for previous, current in zip(items, items[1:]):
            if previous.end > current.start:
                errors.append(
                    f"Overlap on M{machine}: "
                    f"J{previous.job}-O{previous.index} [{previous.start}, {previous.end}) "
                    f"\u2229 J{current.job}-O{current.index} [{current.start}, {current.end})"
                )

    makespan = max((item.end for item in schedule), default=0) if not errors else None
    return ValidationResult(not errors, makespan, errors)
