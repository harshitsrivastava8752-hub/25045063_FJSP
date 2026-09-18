"""Flexible Job-Shop Scheduling Problem toolkit.

This package provides a complete pipeline: Generate → Validate → Solve →
Analyze → Improve.  All public symbols are re-exported here so that
``from fjsp import generate_instance, solve, validate`` continues to work.
"""

# --- Data model ---
from fjsp.model import (
    Operation,
    Instance,
    ScheduledOperation,
    ValidationResult,
    instance_to_dict,
    instance_from_dict,
    validate_instance,
)

# --- Generator ---
from fjsp.generator.instance_generator import (
    generate_instance,
    named_instance_parameters,
)

# --- Environment ---
from fjsp.environment.validator import validate
from fjsp.environment.metrics import metrics, exact_optimum

# --- Algorithms ---
from fjsp.algorithms.solver import solve

# --- Experiments ---
from fjsp.experiments.runner import function_one, run_experiment, main

__all__ = [
    # model
    "Operation", "Instance", "ScheduledOperation", "ValidationResult",
    "instance_to_dict", "instance_from_dict", "validate_instance",
    # generator
    "generate_instance", "named_instance_parameters",
    # environment
    "validate", "metrics", "exact_optimum",
    # algorithms
    "solve",
    # experiments
    "function_one", "run_experiment", "main",
]
