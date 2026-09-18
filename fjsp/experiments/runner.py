"""Experiment runner and CLI for the FJSP pipeline.

Provides ``run_experiment()`` for parametric multi-seed experiments,
``function_one()`` for the first-milestone artifact, and a CLI entrypoint.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict
from typing import Any

from fjsp.model import (
    Instance, ScheduledOperation, instance_from_dict, instance_to_dict,
)
from fjsp.generator.instance_generator import (
    generate_instance, named_instance_parameters,
)
from fjsp.environment.validator import validate
from fjsp.environment.metrics import metrics
from fjsp.algorithms.solver import solve


# All instance classes available in the system
INSTANCE_CLASSES = [
    "average", "low_flexibility", "high_flexibility", "bottleneck",
    "balanced", "high_variance", "machine_advantage", "extreme",
    "unbalanced",
]


def function_one(jobs: int = 5, machines: int = 3, operations: int = 4,
                 instance_class: str = "average", seed: int = 42,
                 starts: int = 30, local_search: int = 100,
                 tabu_tenure: int = 7) -> dict[str, Any]:
    """Run the complete first milestone and return submission-ready JSON data."""
    instance = generate_instance(jobs, machines, operations,
                                 instance_class=instance_class, seed=seed)
    schedule = solve(instance, seed, starts, local_search, tabu_tenure)
    validation = validate(instance, schedule)
    if not validation.valid:
        raise RuntimeError("Function 1 produced an invalid schedule")
    return {
        "instance": instance_to_dict(instance),
        "schedule": [asdict(item) for item in schedule],
        "validation": validation.to_dict(),
        "metrics": metrics(instance, schedule),
        "algorithm": {
            "name": "tabu_search_N1_N2",
            "seed": seed,
            "starts": starts,
            "local_search_iterations": local_search,
            "tabu_tenure": tabu_tenure,
        },
    }


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    runtimes: list[float] = []
    for offset in range(args.repetitions):
        parameters = named_instance_parameters(args.instance_class)
        parameters.setdefault("flexibility", args.flexibility)
        parameters.setdefault("processing_time_noise_scale", args.noise_scale)
        parameters.setdefault("bottleneck_probability", args.bottleneck)
        parameters.setdefault("processing_time_max", args.time_max)
        instance = generate_instance(
            args.jobs, args.machines, args.operations, seed=args.seed + offset,
            processing_time_min=args.time_min,
            instance_class=args.instance_class, **parameters,
        )
        started = time.perf_counter()
        schedule = solve(instance, args.seed + offset, args.iterations, args.local_search, args.tabu_tenure)
        runtimes.append(time.perf_counter() - started)
        result = validate(instance, schedule)
        if not result.valid or result.makespan is None:
            raise RuntimeError("experiment produced an invalid schedule")
        record = metrics(instance, schedule)
        record.update({
            "seed": args.seed + offset,
            "instance_class": args.instance_class,
            "jobs": instance.jobs,
            "machines": instance.machines,
            "operations": len(instance.operations),
            "runtime_ms": runtimes[-1] * 1000,
        })
        records.append(record)
    makespans = [record["makespan"] for record in records]
    n = len(makespans)
    ci_half = 1.96 * statistics.stdev(makespans) / (n ** 0.5) if n > 1 else 0.0
    return {
        "repetitions": args.repetitions,
        "instance_class": args.instance_class,
        "average_makespan": statistics.mean(makespans),
        "makespan_ci_95_half": ci_half,
        "makespan_mean_lower": statistics.mean(makespans) - ci_half,
        "makespan_mean_upper": statistics.mean(makespans) + ci_half,
        "best_makespan": min(makespans),
        "worst_makespan": max(makespans),
        "average_runtime_ms": statistics.mean(runtimes) * 1000,
        "average_lower_bound_gap": statistics.mean(record["lower_bound_gap"] for record in records),
        "makespan_stddev": statistics.stdev(makespans) if len(makespans) > 1 else 0.0,
        "makespans": makespans,
        "records": records,
        "algorithm": {
            "name": "tabu_search_N1_N2",
            "seed_base": args.seed,
            "iterations": args.iterations,
            "local_search_iterations": args.local_search,
            "tabu_tenure": args.tabu_tenure,
            "python_version": sys.version.split()[0],
        },
        "generator": {
            "jobs": args.jobs,
            "machines": args.machines,
            "operations_per_job": args.operations,
            "seed_base": args.seed,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and solve flexible job-shop scheduling instances."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--jobs", type=int, default=5)
    common.add_argument("--machines", type=int, default=3)
    common.add_argument("--operations", type=int, default=4)
    common.add_argument("--flexibility", type=float, default=0.5)
    common.add_argument("--time-min", type=int, default=1)
    common.add_argument("--time-max", type=int, default=20)
    common.add_argument("--noise-scale", type=float, default=0.0)
    common.add_argument("--bottleneck", type=float, default=0.0)
    common.add_argument("--machine-advantage", type=float, default=0.0)
    common.add_argument("--instance-class", default="average", choices=INSTANCE_CLASSES)
    common.add_argument("--seed", type=int, default=42)
    common.add_argument("--iterations", type=int, default=20)
    common.add_argument("--local-search", type=int, default=100)
    common.add_argument("--tabu-tenure", type=int, default=7)

    generate = sub.add_parser("generate", parents=[common])
    generate.add_argument("--output", default="-")

    solve_parser = sub.add_parser("solve")
    solve_parser.add_argument("instance")
    solve_parser.add_argument("--iterations", type=int, default=20)
    solve_parser.add_argument("--local-search", type=int, default=100)
    solve_parser.add_argument("--tabu-tenure", type=int, default=7)

    validate_parser = sub.add_parser("validate", help="independently referee a schedule JSON file")
    validate_parser.add_argument("instance")
    validate_parser.add_argument("schedule")

    function_parser = sub.add_parser("function-one", help="run the complete first milestone")
    function_parser.add_argument("--jobs", type=int, default=5)
    function_parser.add_argument("--machines", type=int, default=3)
    function_parser.add_argument("--operations", type=int, default=4)
    function_parser.add_argument("--instance-class", default="average", choices=INSTANCE_CLASSES)
    function_parser.add_argument("--seed", type=int, default=42)
    function_parser.add_argument("--starts", type=int, default=30)
    function_parser.add_argument("--local-search", type=int, default=100)
    function_parser.add_argument("--tabu-tenure", type=int, default=7)
    function_parser.add_argument("--output", default="-")

    experiment = sub.add_parser("experiment", parents=[common])
    experiment.add_argument("--repetitions", type=int, default=10)

    args = parser.parse_args()

    try:
        if args.command == "generate":
            data = json.dumps(instance_to_dict(generate_instance(
                args.jobs, args.machines, args.operations, args.flexibility,
                args.time_min, args.time_max, args.noise_scale, args.bottleneck,
                machine_advantage=args.machine_advantage,
                seed=args.seed, instance_class=args.instance_class,
            )), indent=2)
            if args.output == "-":
                print(data)
            else:
                with open(args.output, "w", encoding="utf-8") as file:
                    file.write(data + "\n")
        elif args.command == "solve":
            with open(args.instance, encoding="utf-8-sig") as file:
                instance = instance_from_dict(json.load(file))
            schedule = solve(instance, instance.seed, args.iterations, args.local_search, args.tabu_tenure)
            result = validate(instance, schedule)
            print(json.dumps({"schedule": [asdict(item) for item in schedule],
                              "validation": result.to_dict(),
                              "metrics": metrics(instance, schedule)}, indent=2))
        elif args.command == "validate":
            with open(args.instance, encoding="utf-8-sig") as file:
                instance = instance_from_dict(json.load(file))
            with open(args.schedule, encoding="utf-8-sig") as file:
                raw_schedule = json.load(file)
            if isinstance(raw_schedule, dict):
                raw_schedule = raw_schedule.get("schedule")
            if not isinstance(raw_schedule, list):
                raise ValueError("malformed schedule JSON: expected a list")
            schedule = [ScheduledOperation(
                item["job"], item["index"], item["machine"], item["start"], item["end"]
            ) for item in raw_schedule]
            result = validate(instance, schedule)
            if result.valid:
                print("VALID")
                print(f"Makespan: {result.makespan}")
            else:
                print("INVALID")
                for error in result.errors:
                    print(f"Error: {error}")
                raise SystemExit(1)
        else:
            if args.command == "function-one":
                data = json.dumps(function_one(
                    args.jobs, args.machines, args.operations,
                    args.instance_class, args.seed,
                    args.starts, args.local_search, args.tabu_tenure
                ), indent=2)
                if args.output == "-":
                    print(data)
                else:
                    with open(args.output, "w", encoding="utf-8") as file:
                        file.write(data + "\n")
            else:
                print(json.dumps(run_experiment(args), indent=2))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
