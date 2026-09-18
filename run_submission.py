"""Generate the reproducible result bundle included with the submission."""

import argparse
import json
import shutil
import csv
import statistics
from pathlib import Path

from fjsp import (exact_optimum, generate_instance, instance_to_dict,
                  function_one, run_experiment, solve, validate)
from fjsp.model import Instance, ScheduledOperation


def spt_schedule(instance: Instance) -> list[ScheduledOperation]:
    """Shortest-processing-time greedy baseline (always pick min duration option)."""
    ops_by_job = instance.operations_by_job
    next_idx   = {j: 0 for j in range(instance.jobs)}
    job_end    = {j: 0 for j in range(instance.jobs)}
    mach_end   = {m: 0 for m in range(instance.machines)}
    result     = []
    total      = sum(len(v) for v in ops_by_job.values())
    while len(result) < total:
        candidates = []
        for job, idx in next_idx.items():
            ops = ops_by_job[job]
            if idx >= len(ops):
                continue
            op = ops[idx]
            best_m, best_d = min(op.options.items(), key=lambda x: x[1])
            start  = max(job_end[job], mach_end[best_m])
            finish = start + best_d
            candidates.append((finish, op, best_m, start, finish))
        _, op, machine, start, finish = min(candidates, key=lambda x: x[0])
        result.append(ScheduledOperation(op.job, op.index, machine, start, finish))
        job_end[op.job] = finish
        next_idx[op.job] += 1
        mach_end[machine] = finish
    return result


def main(seed_base: int = 20260910, clean: bool = False) -> None:
    output = Path("results")
    if clean and output.exists():
        shutil.rmtree(output)
    output.mkdir(exist_ok=True)
    (output / "function_one.json").write_text(
        json.dumps(function_one(instance_class="average", seed=seed_base), indent=2) + "\n",
        encoding="utf-8",
    )
    classes = ["average", "low_flexibility", "high_flexibility", "bottleneck",
               "balanced", "high_variance", "machine_advantage", "extreme",
               "unbalanced"]
    for name in classes:
        ops = (1, 8) if name == "unbalanced" else 5
        args = argparse.Namespace(
            jobs=12, machines=6, operations=ops, flexibility=.5,
            time_min=1, time_max=30, noise_scale=.15, bottleneck=.1,
            instance_class=name, seed=seed_base, iterations=30, repetitions=10,
            local_search=100, tabu_tenure=7,
        )
        result = run_experiment(args)
        (output / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    sweep_rows = []
    for parameter, values in (("flexibility", [0.0, .2, .4, .6, .8, 1.0]),
                              ("bottleneck_probability", [0.0, .2, .4, .6, .8, 1.0]),
                              ("processing_time_noise_scale", [0.0, 0.3, 0.6, 1.0, 1.5]),
                              ("machine_advantage", [0.0, 0.2, 0.5, 0.8, 1.0])):
        for value in values:
            makespans = []
            for seed in range(seed_base, seed_base + 20):
                kwargs = {parameter: value}
                instance = generate_instance(10, 5, 4, seed=seed, **kwargs)
                schedule = solve(instance, seed, 20, 50)
                result = validate(instance, schedule)
                if not result.valid or result.makespan is None:
                    raise RuntimeError("sweep generated an invalid schedule")
                makespans.append(result.makespan)
            sweep_rows.append({
                "parameter": parameter, "value": value,
                "mean_makespan": sum(makespans) / len(makespans),
                "stddev": (statistics.stdev(makespans) if len(makespans) > 1 else 0.0),
                "seeds": len(makespans),
            })
    with (output / "controlled_sweeps.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=sweep_rows[0])
        writer.writeheader()
        writer.writerows(sweep_rows)

    exact_rows = []
    for seed in range(10):
        instance = generate_instance(3, 2, 2, flexibility=.7, seed=seed)
        heuristic = validate(instance, solve(instance, seed, 30, 50)).makespan
        optimum = exact_optimum(instance)
        exact_rows.append({"seed": seed, "heuristic": heuristic, "optimum": optimum,
                           "gap": (heuristic - optimum) / optimum})
    (output / "exact_small_instances.json").write_text(
        json.dumps(exact_rows, indent=2) + "\n", encoding="utf-8"
    )

    ablation_rows = []
    for name, local_search in (("spt_baseline", -1), ("greedy_multistart", 0), ("greedy_plus_local_search", 100)):
        values = []
        for seed in range(seed_base, seed_base + 20):
            instance = generate_instance(10, 5, 4, instance_class="average", seed=seed)
            if local_search == -1:
                schedule = spt_schedule(instance)
            else:
                schedule = solve(instance, seed, 30, local_search)
            result = validate(instance, schedule)
            if not result.valid or result.makespan is None:
                raise RuntimeError("ablation generated an invalid schedule")
            values.append(result.makespan)
        ablation_rows.append({
            "algorithm": name, "mean_makespan": sum(values) / len(values),
            "stddev": statistics.stdev(values), "seeds": len(values),
        })
    (output / "ablation.csv").write_text(
        "algorithm,mean_makespan,stddev,seeds\n" +
        "\n".join(f"{row['algorithm']},{row['mean_makespan']},{row['stddev']},{row['seeds']}"
                  for row in ablation_rows) + "\n", encoding="utf-8"
    )

    fixtures = Path("instances") / "edge_cases"
    fixtures.mkdir(parents=True, exist_ok=True)
    edge_specs = {
        "single_machine":        (5, 1, 3, {"flexibility": 0.0}),
        "single_job":            (1, 4, 4, {"flexibility": 1.0}),
        "many_machines":         (3, 8, 2, {"flexibility": 1.0}),
        "extreme_gap":           (2, 2, 2, {"processing_time_min": 1, "processing_time_max": 10000}),
        "long_chain":            (2, 1, 12, {"flexibility": 0.0}),
        "identical_times":       (3, 2, 3, {"processing_time_min": 5, "processing_time_max": 5,
                                            "processing_time_noise_scale": 0.0}),
        "many_jobs_bottleneck":  (20, 4, 2, {"bottleneck_probability": 1.0, "flexibility": 0.3}),
    }
    for name, (jobs, machines, operations, kwargs) in edge_specs.items():
        instance = generate_instance(jobs, machines, operations, seed=seed_base, **kwargs)
        (fixtures / f"{name}.json").write_text(
            json.dumps(instance_to_dict(instance), indent=2) + "\n",
            encoding="utf-8",
        )

    import hashlib
    manifest = {"seed_base": seed_base, "files": {}}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            manifest["files"][str(path.relative_to(output)).replace("\\", "/")] = digest

    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print("Results written to results/. Manifest saved to results/manifest.json.")


if __name__ == "__main__":
    import sys
    clean_flag = "--clean" in sys.argv
    if clean_flag:
        sys.argv.remove("--clean")
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20260910
    main(seed, clean=clean_flag)
