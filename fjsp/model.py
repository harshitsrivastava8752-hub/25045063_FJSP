"""Core data models for the Flexible Job-Shop Scheduling Problem.

Defines the immutable dataclasses that flow between pipeline stages:
Operation, Instance, ScheduledOperation, ValidationResult.
Also includes serialization helpers for JSON round-tripping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Operation:
    job: int
    index: int
    options: dict[int, int]


@dataclass(frozen=True)
class Instance:
    jobs: int
    machines: int
    operations: list[Operation]
    seed: int | None = None
    parameters: dict[str, Any] | None = None

    @property
    def operations_by_job(self) -> dict[int, list[Operation]]:
        result: dict[int, list[Operation]] = {job: [] for job in range(self.jobs)}
        for operation in self.operations:
            result[operation.job].append(operation)
        for operations in result.values():
            operations.sort(key=lambda item: item.index)
        return result


@dataclass(frozen=True)
class ScheduledOperation:
    job: int
    index: int
    machine: int
    start: int
    end: int


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    makespan: int | None
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def instance_to_dict(instance: Instance) -> dict[str, Any]:
    return {
        "jobs": instance.jobs,
        "machines": instance.machines,
        "seed": instance.seed,
        "parameters": instance.parameters,
        "operations": [asdict(operation) for operation in instance.operations],
    }


def validate_instance(instance: Instance) -> list[str]:
    """Independently check the well-formedness contract for imported instances."""
    errors: list[str] = []
    if not isinstance(instance.jobs, int) or instance.jobs < 1:
        errors.append("jobs must be a positive integer")
    if not isinstance(instance.machines, int) or instance.machines < 1:
        errors.append("machines must be a positive integer")
    expected: dict[tuple[int, int], Operation] = {}
    for operation in instance.operations:
        if not all(isinstance(value, int) and not isinstance(value, bool)
                   for value in (operation.job, operation.index)):
            errors.append("job and operation IDs must be integers")
            continue
        key = (operation.job, operation.index)
        if not 0 <= operation.job < instance.jobs:
            errors.append(f"invalid job ID {operation.job}")
        if operation.index < 0:
            errors.append(f"invalid operation ID {operation.index}")
        if key in expected:
            errors.append(f"duplicate operation J{operation.job}-O{operation.index}")
        expected[key] = operation
        if not operation.options:
            errors.append(f"operation J{operation.job}-O{operation.index} has no machines")
        if not isinstance(operation.options, dict):
            errors.append(f"options for J{operation.job}-O{operation.index} must be an object")
            continue
        for machine, duration in operation.options.items():
            if not isinstance(machine, int) or not 0 <= machine < instance.machines:
                errors.append(f"invalid machine ID M{machine}")
            if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
                errors.append(f"invalid duration for J{operation.job}-O{operation.index}")
    by_job = {job: [] for job in range(max(0, instance.jobs))}
    for operation in instance.operations:
        if 0 <= operation.job < instance.jobs:
            by_job[operation.job].append(operation.index)
    for job, indices in by_job.items():
        if not indices:
            errors.append(f"job {job} has no operations")
        if sorted(indices) != list(range(len(indices))):
            errors.append(f"job {job} operation IDs are not contiguous")
    return errors


def instance_from_dict(data: dict[str, Any]) -> Instance:
    if not isinstance(data, dict):
        raise ValueError("instance JSON must be an object")
    for key in ("jobs", "machines", "operations"):
        if key not in data:
            raise ValueError(f"instance JSON missing required key: '{key}'")
    operations = [
        Operation(item["job"], item["index"], {int(k): v for k, v in item["options"].items()})
        for item in data["operations"]
    ]
    instance = Instance(data["jobs"], data["machines"], operations, data.get("seed"), data.get("parameters"))
    errors = validate_instance(instance)
    if errors:
        raise ValueError("; ".join(errors))
    return instance
