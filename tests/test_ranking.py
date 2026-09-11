from __future__ import annotations

import unittest

from campus_job_ranker.models import load_run_input
from campus_job_ranker.ranking import rank_jobs, select_recommendations
from tests.helpers import job, run_payload, signals


class RankingTests(unittest.TestCase):
    def test_dense_ties_and_similar_jobs_are_preserved(self) -> None:
        first = signals()
        tied_a = signals()
        tied_b = signals()
        third = signals()
        tied_a["personal_relevant_context"]["state"] = "partial"
        tied_b["personal_relevant_context"]["state"] = "partial"
        third["personal_relevant_context"]["state"] = "conflict"

        payload = run_payload(
            [
                job("1", "AI 产品经理", signal_values=first),
                job("2", "大模型产品经理", signal_values=tied_a, similar_group="llm-pm"),
                job("3", "大模型产品经理-平台", signal_values=tied_b, similar_group="llm-pm"),
                job("4", "策略产品经理", signal_values=third),
            ]
        )
        ranked = rank_jobs(load_run_input(payload))

        self.assertEqual([item.rank for item in ranked], [1, 2, 2, 3])
        self.assertEqual(len(ranked), 4)
        self.assertEqual([item.job.id for item in ranked if item.job.similar_group == "llm-pm"], ["2", "3"])

    def test_hard_conflict_is_kept_but_not_ranked(self) -> None:
        payload = run_payload(
            [
                job("1", "AI 产品经理"),
                job(
                    "2",
                    "社招产品经理",
                    hard_requirements={"campus_full_time": "conflict"},
                ),
            ]
        )
        ranked = rank_jobs(load_run_input(payload))

        self.assertEqual(len(ranked), 2)
        excluded = next(item for item in ranked if item.job.id == "2")
        self.assertTrue(excluded.excluded)
        self.assertIsNone(excluded.rank)
        self.assertIn("campus_full_time", excluded.exclusion_reasons)

    def test_adds_one_high_potential_exception_after_evidence_top_three(self) -> None:
        top_three = []
        for index in range(1, 4):
            value = signals()
            for criterion_id in (
                "personal_relevant_context",
                "personal_owner",
                "personal_ai_mechanism",
                "personal_results",
                "personal_transfer",
            )[: index - 1]:
                value[criterion_id]["state"] = "partial"
            top_three.append(job(str(index), f"已验证岗位 {index}", signal_values=value))

        high_potential = signals()
        for criterion_id in (
            "opportunity_growth",
            "opportunity_advantage",
            "opportunity_value_loop",
            "opportunity_differentiation",
        ):
            high_potential[criterion_id] = {"state": "unknown", "evidence": []}
        high_potential["opportunity_investment"]["state"] = "partial"
        payload = run_payload(
            top_three + [job("4", "AI Agent 产品经理", signal_values=high_potential)]
        )

        selections = select_recommendations(rank_jobs(load_run_input(payload)))

        self.assertEqual([selection.position for selection in selections], [1, 2, 3, 4])
        self.assertEqual(selections[-1].item.job.id, "4")
        self.assertEqual(selections[-1].kind, "high_potential_exception")
        self.assertEqual(selections[-1].item.rank, 4)


if __name__ == "__main__":
    unittest.main()
