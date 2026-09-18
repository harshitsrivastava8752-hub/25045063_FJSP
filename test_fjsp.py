import unittest

from fjsp import (Instance, Operation, ScheduledOperation, exact_optimum,
                  generate_instance, instance_from_dict, metrics, solve, validate)


class FjspTests(unittest.TestCase):
    def test_generation_is_reproducible(self):
        first = generate_instance(3, 4, 2, flexibility=.75, seed=7)
        second = generate_instance(3, 4, 2, flexibility=.75, seed=7)
        self.assertEqual(first, second)

    def test_solver_returns_valid_schedule(self):
        instance = generate_instance(6, 4, 3, flexibility=.6, bottleneck_probability=.8, seed=11)
        result = validate(instance, solve(instance, seed=11, iterations=10))
        self.assertTrue(result.valid, result.errors)
        self.assertGreater(result.makespan, 0)

    def test_validator_detects_overlap(self):
        instance = generate_instance(2, 1, 1, seed=1)
        operation_a, operation_b = instance.operations
        schedule = [
            ScheduledOperation(operation_a.job, operation_a.index, 0, 0, operation_a.options[0]),
            ScheduledOperation(operation_b.job, operation_b.index, 0, 0, operation_b.options[0]),
        ]
        result = validate(instance, schedule)
        self.assertFalse(result.valid)
        self.assertTrue(any("overlap" in error.lower() for error in result.errors))

    def test_validator_rejects_malformed_entries_without_crashing(self):
        instance = generate_instance(1, 1, 1, seed=3)
        for malformed in (None, {}, ["bad"], [None]):
            result = validate(instance, malformed)
            self.assertFalse(result.valid)
            self.assertTrue(result.errors)

    def test_validator_detects_duration_and_precedence(self):
        instance = generate_instance(1, 1, 2, seed=4)
        first, second = instance.operations
        schedule = [
            ScheduledOperation(0, 0, 0, 5, 5 + first.options[0] - 1),
            ScheduledOperation(0, 1, 0, 0, second.options[0]),
        ]
        result = validate(instance, schedule)
        self.assertFalse(result.valid)
        self.assertTrue(any("duration" in error.lower() for error in result.errors))
        self.assertTrue(any("precedence" in error.lower() for error in result.errors))

    def test_instance_classes_apply_directly(self):
        extreme = generate_instance(2, 3, 2, instance_class="extreme", seed=5)
        self.assertEqual(extreme.parameters["processing_time_max"], 10000)
        self.assertEqual(extreme.parameters["flexibility"], .95)
        self.assertTrue(validate(extreme, solve(extreme, seed=5)).valid)

    def test_metrics_include_machine_critical_path(self):
        instance = generate_instance(2, 1, 2, seed=8)
        schedule = solve(instance, seed=8, local_search_iterations=0)
        values = metrics(instance, schedule)
        self.assertGreaterEqual(values["critical_path"], values["job_chain_lower_bound"])
        self.assertIn("max_machine_workload", values)

    def test_exact_solver_matches_single_machine_sum(self):
        instance = generate_instance(2, 1, 2, seed=9)
        self.assertEqual(exact_optimum(instance), sum(
            operation.options[0] for operation in instance.operations
        ))

    def test_instance_import_rejects_invalid_structure(self):
        with self.assertRaises(ValueError):
            instance_from_dict({"jobs": 1, "machines": 1, "operations": []})
        with self.assertRaises(ValueError):
            instance_from_dict({
                "jobs": 1, "machines": 1,
                "operations": [{"job": 0, "index": 0, "options": {"9": 1}}],
            })

    def test_unbalanced_instance_class(self):
        inst = generate_instance(4, 3, (1, 8), instance_class="unbalanced", seed=42)
        self.assertEqual(inst.parameters["instance_class"], "unbalanced")
        sched = solve(inst, seed=42)
        result = validate(inst, sched)
        self.assertTrue(result.valid, result.errors)
        self.assertGreater(result.makespan, 0)

    def test_enriched_validator_error_messages(self):
        inst = generate_instance(2, 2, 2, seed=10)
        bad_sched = [
            ScheduledOperation(0, 0, 0, 5, 12),
            ScheduledOperation(1, 0, 0, 8, 15),
        ]
        result = validate(inst, bad_sched)
        self.assertFalse(result.valid)
        overlap_errors = [e for e in result.errors if "overlap" in e.lower()]
        self.assertTrue(len(overlap_errors) > 0)
        self.assertIn("Overlap on M0", overlap_errors[0])
        self.assertIn("J0-O0 [5, 12)", overlap_errors[0])
        self.assertIn("J1-O0 [8, 15)", overlap_errors[0])


if __name__ == "__main__":
    unittest.main()
