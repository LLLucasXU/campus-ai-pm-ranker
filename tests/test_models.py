from __future__ import annotations

import unittest

from campus_job_ranker.models import ValidationError, load_run_input
from tests.helpers import job, run_payload


class RunInputValidationTests(unittest.TestCase):
    def test_accepts_one_company(self) -> None:
        run_input = load_run_input(run_payload([job("1", "AI 产品经理")]))
        self.assertEqual(run_input.company_name, "示例科技")
        self.assertEqual(len(run_input.jobs), 1)

    def test_rejects_cross_company_candidate_pool(self) -> None:
        payload = run_payload(
            [job("1", "AI 产品经理"), job("2", "策略产品经理", company="另一家公司")]
        )
        with self.assertRaisesRegex(ValidationError, "一次运行只能包含一家公司"):
            load_run_input(payload)

    def test_rejects_invalid_signal_state(self) -> None:
        candidate = job("1", "AI 产品经理")
        candidate["signals"]["personal_relevant_context"]["state"] = "great"
        with self.assertRaisesRegex(ValidationError, "无效评分状态"):
            load_run_input(run_payload([candidate]))


if __name__ == "__main__":
    unittest.main()
