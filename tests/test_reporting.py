from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from campus_job_ranker.models import load_run_input
from campus_job_ranker.reporting import OUTPUT_FILENAMES, generate_outputs
from campus_job_ranker.collection import CollectionRequest, CollectionRuntime, LayerInput
from tests.helpers import job, run_payload, signals


class ReportingTests(unittest.TestCase):
    def test_generates_chinese_auditable_outputs_and_performance_file(self) -> None:
        candidates = []
        for index in range(1, 6):
            candidate_signals = signals()
            for criterion_id in list(candidate_signals)[: index - 1]:
                candidate_signals[criterion_id]["state"] = "conflict"
            candidates.append(job(str(index), f"岗位 {index}", signal_values=candidate_signals))

        run_input = load_run_input(run_payload(candidates))
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            generated = generate_outputs(run_input, output_dir)

            self.assertEqual(set(generated), set(OUTPUT_FILENAMES))
            for filename in OUTPUT_FILENAMES:
                self.assertTrue((output_dir / filename).is_file())

            report = (output_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("仅用于本公司本次候选岗位的内部比较", report)
            self.assertIn("核心推荐（保守前三名 + 高潜破格）", report)
            self.assertIn("原始证据排名第 4–10 名", report)
            self.assertIn("#### 为什么适合", report)
            self.assertIn("#### 最相关的个人经历证据", report)
            self.assertIn("#### 人工智能落地深度判断", report)
            self.assertIn("#### 所属业务与岗位机会前景", report)
            self.assertIn("#### 主要缺口与待确认", report)
            self.assertIn("| 关键标签 | 主要风险 |", report)
            self.assertNotIn("evidence for", report)
            self.assertIn("证据待补充为中文说明", report)

            performance = json.loads((output_dir / "performance.json").read_text(encoding="utf-8"))
            self.assertIn("总耗时毫秒", performance)
            self.assertIn("阶段", performance)

            summary = json.loads((output_dir / "run-summary.json").read_text(encoding="utf-8"))
            self.assertIn("候选人资料版本", summary)
            self.assertNotIn("飞书资料版本", summary)

            all_jobs = (output_dir / "all-jobs.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(all_jobs), 5)
            self.assertEqual(json.loads(all_jobs[0])["公司"], "示例科技")

            with (output_dir / "ranking.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 5)

    def test_includes_collection_runtime_summary_when_present(self) -> None:
        result = CollectionRuntime().collect(
            CollectionRequest(
                career_url="https://careers.example.com/campus",
                api=LayerInput(
                    available=True,
                    pages=[{"jobs": [{"id": "api-1", "title": "AI 产品经理", "url": "/job/1"}]}],
                    pagination_complete=True,
                ),
            )
        )
        payload = run_payload([job("1", "AI 产品经理")])
        payload["run"].update(result.run_summary())
        run_input = load_run_input(payload)
        with tempfile.TemporaryDirectory() as tmp:
            generate_outputs(run_input, Path(tmp))
            report = (Path(tmp) / "report.md").read_text(encoding="utf-8")
            summary = json.loads((Path(tmp) / "run-summary.json").read_text(encoding="utf-8"))
            performance = json.loads((Path(tmp) / "performance.json").read_text(encoding="utf-8"))

        self.assertIn("## 采集状态", report)
        self.assertIn("最终采集层：公开接口", report)
        self.assertEqual(summary["最终采集层"], "公开接口")
        self.assertFalse(summary["产品类筛选已确认"])
        self.assertTrue(summary["分页完整"])
        self.assertIn("采集：公开接口", [stage["名称"] for stage in performance["阶段"]])

    def test_displays_one_high_potential_exception_in_recommendation_area(self) -> None:
        evidence_top_three = []
        for index in range(1, 4):
            value = signals()
            for criterion_id in list(value)[: index - 1]:
                value[criterion_id]["state"] = "partial"
            evidence_top_three.append(job(str(index), f"已验证岗位 {index}", signal_values=value))
        high_potential = signals()
        for criterion_id in (
            "opportunity_growth",
            "opportunity_advantage",
            "opportunity_value_loop",
            "opportunity_differentiation",
        ):
            high_potential[criterion_id] = {"state": "unknown", "evidence": []}
        high_potential["opportunity_investment"]["state"] = "partial"
        run_input = load_run_input(
            run_payload(
                evidence_top_three
                + [job("agent", "AI Agent 产品经理", signal_values=high_potential)]
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            generate_outputs(run_input, Path(tmp))
            report = (Path(tmp) / "report.md").read_text(encoding="utf-8")

        self.assertIn("核心推荐（保守前三名 + 高潜破格）", report)
        self.assertIn("推荐第 4 位（高潜待核验；证据排名 4）｜[AI Agent 产品经理]", report)
        self.assertIn("因业务前景证据不足触发高潜破格推荐", report)

    def test_renders_working_english_conflict_with_human_label(self) -> None:
        run_input = load_run_input(
            run_payload(
                [
                    job(
                        "international",
                        "国际化产品助理",
                        hard_requirements={"language_working_proficiency": "conflict"},
                    )
                ]
            )
        )

        with tempfile.TemporaryDirectory() as tmp:
            generate_outputs(run_input, Path(tmp))
            report = (Path(tmp) / "report.md").read_text(encoding="utf-8")

        self.assertIn("英语工作能力", report)
        self.assertNotIn("language_working_proficiency", report)


if __name__ == "__main__":
    unittest.main()
