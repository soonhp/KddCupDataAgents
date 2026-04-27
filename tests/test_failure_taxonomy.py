from __future__ import annotations

import unittest

from runner.failure_taxonomy import classify_task_failure, rollup_failure_taxonomy
from runner.verification import VerificationCheck, VerificationReport


class FailureTaxonomyTests(unittest.TestCase):
    def test_classifies_runtime_and_contract_failures(self) -> None:
        report = VerificationReport(
            task_id="task_1",
            all_passed=False,
            checks=[
                VerificationCheck(name="contract_check", passed=False, detail="header missing"),
                VerificationCheck(name="sanity_check", passed=True, detail="ok"),
            ],
        )
        taxonomy = classify_task_failure(
            task_id="task_1",
            succeeded=False,
            failure_reason="Task timeout exceeded",
            verification_report=report,
        )
        codes = [tag.code for tag in taxonomy.tags]
        self.assertIn("runtime_timeout", codes)
        self.assertIn("output_contract_violation", codes)

    def test_rollup_counts_codes(self) -> None:
        ok_report = VerificationReport(
            task_id="task_2",
            all_passed=True,
            checks=[VerificationCheck(name="contract_check", passed=True, detail="ok")],
        )
        failed_report = VerificationReport(
            task_id="task_3",
            all_passed=False,
            checks=[VerificationCheck(name="sanity_check", passed=False, detail="too many empty rows")],
        )
        task_2 = classify_task_failure(
            task_id="task_2",
            succeeded=True,
            failure_reason=None,
            verification_report=ok_report,
        )
        task_3 = classify_task_failure(
            task_id="task_3",
            succeeded=True,
            failure_reason=None,
            verification_report=failed_report,
        )
        rollup = rollup_failure_taxonomy([task_2, task_3])
        self.assertEqual(rollup.by_code.get("passed"), 1)
        self.assertEqual(rollup.by_code.get("output_sanity_violation"), 1)


if __name__ == "__main__":
    unittest.main()
