"""Instance generator for the Flexible Job-Shop Scheduling Problem.

Produces reproducible, always-solvable FJSP instances with configurable
stress parameters and named instance classes.
"""

from __future__ import annotations

import random
from typing import Any

from fjsp.model import Instance, Operation, validate_instance


def generate_instance(
    jobs: int,
    machines: int,
    operations_per_job: int | tuple[int, int],
    flexibility: float = 0.5,
    processing_time_min: int = 1,
    processing_time_max: int = 20,
    processing_time_noise_scale: float = 0.0,
    bottleneck_probability: float = 0.0,
    machine_advantage: float = 0.0,
    seed: int | None = None,
    instance_class: str = "average",
) -> Instance:
    """Generate a reproducible, always-solvable FJSP instance.

    Parameters
    ----------
    jobs : int
        Number of jobs (>= 1).
    machines : int
        Number of machines (>= 1).
    operations_per_job : int or (int, int)
        Fixed count or (min, max) range of operations per job.
    flexibility : float
        Fraction of machines eligible per operation, in [0, 1].
    processing_time_min, processing_time_max : int
        Bounds for processing time sampling.
    processing_time_noise_scale : float
        Gaussian noise multiplier applied to processing times:
        value = center * (1 + N(0, noise_scale))
        Actual std-dev of output ≈ center * noise_scale.
        Set to 0 for uniform integers, ~0.15 for mild variance, 1.0 for high variance.
    bottleneck_probability : float
        Probability of forcibly including the bottleneck machine, in [0, 1].
    machine_advantage : float
        Speedup factor for the specialist (bottleneck) machine (>= 0).
    seed : int | None
        Random seed for exact reproducibility.
    instance_class : str
        Named preset that overrides individual parameters.

    Returns
    -------
    Instance
        A valid, solvable FJSP instance.
    """
    if jobs < 1 or machines < 1:
        raise ValueError("jobs, machines, and operations_per_job must be positive")
    if isinstance(operations_per_job, tuple):
        min_operations, max_operations = operations_per_job
    else:
        min_operations = max_operations = operations_per_job
    if min_operations < 1 or min_operations > max_operations:
        raise ValueError("operations_per_job must be a positive integer or (min, max)")
    if not 0 <= flexibility <= 1 or not 0 <= bottleneck_probability <= 1:
        raise ValueError("flexibility and bottleneck_probability must be in [0, 1]")
    if processing_time_noise_scale < 0 or machine_advantage < 0:
        raise ValueError("processing_time_noise_scale and machine_advantage must be non-negative")
    if processing_time_min < 1 or processing_time_min > processing_time_max:
        raise ValueError("processing time bounds are invalid")

    rng = random.Random(seed)
    operations: list[Operation] = []
    bottleneck = rng.randrange(machines)
    # Specialist machine may be the same as bottleneck or different.
    # Use a separate draw so the two effects can be decoupled.
    specialist = rng.randrange(machines)
    class_settings: dict[str, dict[str, Any]] = {
        "low_flexibility": {"flexibility": .05},
        "high_flexibility": {"flexibility": .95},
        "bottleneck": {"bottleneck_probability": .85},
        "high_variance": {"processing_time_noise_scale": 1.0, "processing_time_max": 100},
        "machine_advantage": {"machine_advantage": .8},
        "extreme": {"flexibility": .95, "processing_time_noise_scale": 1.5,
                    "processing_time_max": 10000, "bottleneck_probability": .8},
        "balanced": {"bottleneck_probability": 0.0},
        "unbalanced": {"flexibility": 0.5, "operations_per_job": (1, 8)},
        "average": {},
        "small": {},
        "large": {},
    }
    if instance_class not in class_settings:
        raise ValueError(f"unknown instance class: {instance_class}")
    settings = class_settings[instance_class]

    # Apply class overrides
    flexibility = settings.get("flexibility", flexibility)
    processing_time_noise_scale = settings.get("processing_time_noise_scale", processing_time_noise_scale)
    processing_time_max = max(processing_time_max, settings.get("processing_time_max", processing_time_max))
    bottleneck_probability = max(bottleneck_probability, settings.get("bottleneck_probability", 0.0))
    machine_advantage = max(machine_advantage, settings.get("machine_advantage", 0.0))

    # Unbalanced class overrides operations_per_job range
    if "operations_per_job" in settings:
        ops_range = settings["operations_per_job"]
        if isinstance(ops_range, tuple):
            min_operations, max_operations = ops_range
        else:
            min_operations = max_operations = ops_range

    option_count = max(1, min(machines, round(1 + flexibility * (machines - 1))))
    for job in range(jobs):
        count = rng.randint(min_operations, max_operations)
        for index in range(count):
            eligible = set(rng.sample(range(machines), option_count))
            if rng.random() < bottleneck_probability:
                eligible.add(bottleneck)
            options = {}
            for machine in sorted(eligible):
                if processing_time_noise_scale:
                    center = rng.uniform(processing_time_min, processing_time_max)
                    value = center * (1 + rng.gauss(0, processing_time_noise_scale))
                else:
                    value = rng.randint(processing_time_min, processing_time_max)
                if machine_advantage and machine == specialist:
                    value *= max(0.05, 1 - machine_advantage)
                options[machine] = max(1, int(round(min(processing_time_max, value))))
            operations.append(Operation(job, index, options))
    parameters = {
        "jobs": jobs,
        "machines": machines,
        "operations_per_job": operations_per_job,
        "flexibility": flexibility,
        "processing_time_min": processing_time_min,
        "processing_time_max": processing_time_max,
        "processing_time_noise_scale": processing_time_noise_scale,
        "bottleneck_probability": bottleneck_probability,
        "bottleneck_machine": bottleneck,
        "specialist_machine": specialist,
        "machine_advantage": machine_advantage,
        "instance_class": instance_class,
    }
    instance = Instance(jobs, machines, operations, seed, parameters)
    # Belt-and-suspenders: every generated instance must be well-formed.
    _errors = validate_instance(instance)
    if _errors:
        raise RuntimeError(f"generate_instance produced invalid instance: {_errors}")
    return instance


def named_instance_parameters(instance_class: str) -> dict[str, Any]:
    """Concrete presets used by the report and repeatable experiment runner."""
    presets: dict[str, dict[str, Any]] = {
        "average": dict(flexibility=.5, processing_time_noise_scale=.15, bottleneck_probability=.1),
        "low_flexibility": dict(flexibility=.05),
        "high_flexibility": dict(flexibility=.95),
        "bottleneck": dict(flexibility=.7, bottleneck_probability=.9),
        "balanced": dict(flexibility=.5, bottleneck_probability=0),
        "high_variance": dict(flexibility=.5, processing_time_noise_scale=1.0, processing_time_max=100),
        "machine_advantage": dict(flexibility=.8, machine_advantage=.8),
        "extreme": dict(flexibility=.95, processing_time_noise_scale=1.5, processing_time_max=10000,
                        bottleneck_probability=.8),
        "unbalanced": dict(flexibility=.5, processing_time_noise_scale=.2,
                           bottleneck_probability=.15),
    }
    if instance_class not in presets:
        raise ValueError(f"unknown instance class: {instance_class}")
    return presets[instance_class]
