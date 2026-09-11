from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from campus_job_ranker.collection import (
    BrowserLayerInput,
    BrowserStep,
    CollectionCheckpoint,
    CollectedJob,
    CollectionRequest,
    CollectionRuntime,
    LayerInput,
)
from campus_job_ranker.collection_store import CollectionStore, SensitiveCollectionDataError
from campus_job_ranker.collection import SiteRecipe
from campus_job_ranker.site_adapters import SiteKind, select_site_adapter


class CollectionRuntimeTests(unittest.TestCase):
    class _FakeClock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            return self.now

        def advance_ms(self, value: int) -> None:
            self.now += value / 1000

    def test_prefers_public_api_before_other_sources(self) -> None:
        request = CollectionRequest(
            career_url="https://careers.example.com/campus/jobs",
            api=LayerInput(
                available=True,
                pages=[
                    {
                        "data": {
                            "jobs": [
                                {
                                    "jobId": "api-1",
                                    "positionName": "AI Agent 产品经理",
                                    "detailUrl": "/jobs/api-1",
                                    "description": "负责 Agent 工作流与评测闭环",
                                    "location": "北京",
                                }
                            ]
                        }
                    }
                ],
                pagination_complete=True,
            ),
            html=LayerInput(
                available=True,
                pages=['<a href="/jobs/html-1">传统产品经理</a>'],
                pagination_complete=True,
            ),
        )

        result = CollectionRuntime().collect(request)

        self.assertEqual(result.collection_layer, "api")
        self.assertEqual([job.id for job in result.jobs], ["api-1"])
        self.assertEqual(result.jobs[0].url, "https://careers.example.com/jobs/api-1")
        self.assertEqual([attempt.layer for attempt in result.attempts], ["api"])
        self.assertTrue(result.pagination_complete)

    def test_falls_back_to_scoped_html_after_unusable_api_payload(self) -> None:
        request = CollectionRequest(
            career_url="https://careers.example.com/campus/jobs",
            api=LayerInput(available=True, pages=[{"data": {"items": []}}]),
            html=LayerInput(
                available=True,
                pages=[
                    '<section><a data-job-id="html-1" href="/jobs/html-1">'
                    "AI 产品经理</a></section>"
                ],
                pagination_complete=False,
            ),
        )

        result = CollectionRuntime().collect(request)

        self.assertEqual(result.collection_layer, "html")
        self.assertEqual([job.id for job in result.jobs], ["html-1"])
        self.assertEqual([attempt.outcome for attempt in result.attempts], ["failed", "success"])
        self.assertFalse(result.pagination_complete)

    def test_returns_user_handoff_without_treating_it_as_collection_failure(self) -> None:
        checkpoint = CollectionCheckpoint(
            career_url="https://careers.example.com/campus/jobs",
            page_number=2,
            cursor="next-page-token",
            seen_job_ids=("one", "two"),
        )
        request = CollectionRequest(
            career_url=checkpoint.career_url,
            checkpoint=checkpoint,
            user_action="请在当前页面完成登录后继续",
        )

        result = CollectionRuntime().collect(request)

        self.assertEqual(result.collection_layer, "assisted_browser")
        self.assertEqual(result.user_action, "请在当前页面完成登录后继续")
        self.assertEqual(result.checkpoint, checkpoint)
        self.assertEqual(result.attempts[-1].outcome, "needs_user")

    def test_respects_checkpoint_seen_ids(self) -> None:
        request = CollectionRequest(
            career_url="https://careers.example.com/campus/jobs",
            checkpoint=CollectionCheckpoint(
                career_url="https://careers.example.com/campus/jobs",
                page_number=1,
                seen_job_ids=("one",),
            ),
            api=LayerInput(
                available=True,
                pages=[
                    {
                        "jobs": [
                            {"id": "one", "title": "AI 产品经理", "url": "/jobs/one"},
                            {"id": "two", "title": "策略产品经理", "url": "/jobs/two"},
                        ]
                    }
                ],
                pagination_complete=True,
                next_page_number=2,
            ),
        )

        result = CollectionRuntime().collect(request)

        self.assertEqual([job.id for job in result.jobs], ["two"])
        self.assertEqual(result.checkpoint.page_number, 2)
        self.assertEqual(result.checkpoint.seen_job_ids, ("one", "two"))

    def test_supports_numeric_api_id_and_detail_url_template(self) -> None:
        """Campus APIs may only return a numeric ID rather than a JD URL."""
        request = CollectionRequest(
            career_url="https://careers.example.com/campus/jobs",
            api=LayerInput(
                available=True,
                pages=[
                    {
                        "result": {
                            "list": [
                                {
                                    "id": 13195,
                                    "name": "平台产品经理-大模型 AIGC",
                                    "positionDemand": "负责模型平台与产品落地",
                                    "workLocation": "北京",
                                }
                            ]
                        }
                    }
                ],
                pagination_complete=True,
                detail_url_template="/campus/job-info/{id}",
            ),
        )

        result = CollectionRuntime().collect(request)

        self.assertEqual(result.collection_layer, "api")
        self.assertEqual(result.jobs[0].id, "13195")
        self.assertEqual(
            result.jobs[0].url,
            "https://careers.example.com/campus/job-info/13195",
        )
        self.assertEqual(result.jobs[0].description, "负责模型平台与产品落地")

    def test_discards_layer_result_after_its_time_budget_and_falls_back(self) -> None:
        clock = self._FakeClock()

        class SlowCollector:
            def collect(self, source, career_url):
                clock.advance_ms(9)
                return (
                    CollectedJob(
                        id="slow",
                        title="慢速岗位",
                        url="https://careers.example.com/jobs/slow",
                    ),
                )

        class FastCollector:
            def collect(self, source, career_url):
                return (
                    CollectedJob(
                        id="fast",
                        title="备用岗位",
                        url="https://careers.example.com/jobs/fast",
                    ),
                )

        runtime = CollectionRuntime(clock=clock)
        runtime._collectors = (("api", SlowCollector()), ("html", FastCollector()))
        result = runtime.collect(
            CollectionRequest(
                career_url="https://careers.example.com/campus",
                api=LayerInput(available=True),
                html=LayerInput(available=True),
                layer_budget_ms={"api": 8, "html": 8},
            )
        )

        self.assertEqual([attempt.outcome for attempt in result.attempts], ["timeout", "success"])
        self.assertEqual([job.id for job in result.jobs], ["fast"])

    def test_stops_before_next_layer_when_total_budget_is_exhausted(self) -> None:
        clock = self._FakeClock()

        class SlowCollector:
            def collect(self, source, career_url):
                clock.advance_ms(10)
                raise ValueError("模拟超时")

        runtime = CollectionRuntime(clock=clock)
        runtime._collectors = (("api", SlowCollector()),)
        result = runtime.collect(
            CollectionRequest(
                career_url="https://careers.example.com/campus",
                api=LayerInput(available=True),
                total_budget_ms=5,
                layer_budget_ms={"api": 8},
                user_action="请在官网页面完成操作",
            )
        )

        self.assertTrue(result.budget_exhausted)
        self.assertEqual(result.attempts[0].outcome, "timeout")

    def test_uses_verified_browser_steps_after_static_layers_fail(self) -> None:
        request = CollectionRequest(
            career_url="https://xiaopeng.jobs.feishu.cn/campus/position/list",
            html=LayerInput(available=True, pages=["<html>动态页面外壳</html>"]),
            assisted_browser=BrowserLayerInput(
                available=True,
                steps=(
                    BrowserStep("页面可交互", "success", 120),
                    BrowserStep("产品类筛选", "success", 80, filter_confirmed=True),
                    BrowserStep("岗位列表", "success", 100),
                    BrowserStep("分页遍历", "success", 100, pagination_complete=True),
                    BrowserStep("岗位详情", "success", 150),
                ),
                pages=(
                    {
                        "id": "xp-1",
                        "title": "智能座舱 AI 产品经理",
                        "url": "/campus/position/detail/xp-1",
                        "description": "负责智能座舱人工智能能力落地",
                        "location": "广州",
                        "category": "产品类",
                    },
                ),
                pagination_complete=True,
                details_complete=True,
            ),
        )

        result = CollectionRuntime().collect(request)

        self.assertEqual(result.collection_layer, "assisted_browser")
        self.assertTrue(result.pagination_complete)
        self.assertTrue(result.product_category_confirmed)
        self.assertEqual([job.id for job in result.jobs], ["xp-1"])
        self.assertEqual(result.attempts[-5].layer, "assisted_browser")
        self.assertEqual(result.attempts[-1].outcome, "success")

    def test_rejects_browser_output_when_product_filter_is_not_verified(self) -> None:
        request = CollectionRequest(
            career_url="https://xiaopeng.jobs.feishu.cn/campus/position/list",
            assisted_browser=BrowserLayerInput(
                available=True,
                steps=(
                    BrowserStep("页面可交互", "success", 20),
                    BrowserStep("产品类筛选", "success", 20, filter_confirmed=False),
                ),
                pages=(
                    {"id": "not-product", "title": "算法工程师", "url": "/jobs/1"},
                ),
            ),
        )

        result = CollectionRuntime().collect(request)

        self.assertEqual(result.collection_layer, "none")
        self.assertFalse(result.pagination_complete)
        self.assertEqual(result.attempts[-1].outcome, "failed")
        self.assertIn("产品类筛选", result.attempts[-1].message)

    def test_marks_browser_blocker_without_attempting_to_bypass_it(self) -> None:
        request = CollectionRequest(
            career_url="https://careers.example.com/campus",
            assisted_browser=BrowserLayerInput(
                available=True,
                steps=(BrowserStep("页面可交互", "blocked", 30, message="需要登录或验证码"),),
            ),
        )

        result = CollectionRuntime().collect(request)

        self.assertEqual(result.collection_layer, "assisted_browser")
        self.assertEqual(result.attempts[-1].outcome, "needs_user")
        self.assertIn("登录", result.user_action)


class SiteAdapterTests(unittest.TestCase):
    def test_detects_feishu_hosted_campus_site_and_emits_reusable_plan(self) -> None:
        adapter = select_site_adapter(
            "https://xiaopeng.jobs.feishu.cn/campus/position/list",
            '<script id="js-websiteInfo">{"website_info":{"path":"campus","name":{"zh_cn":"校招官网"}}}</script>',
        )

        self.assertEqual(adapter.kind, SiteKind.FEISHU_HOSTED)
        self.assertEqual(
            adapter.browser_plan(),
            ("页面可交互", "确认校招入口", "产品类筛选", "岗位列表", "分页遍历", "岗位详情"),
        )

    def test_uses_generic_adapter_for_non_feishu_site(self) -> None:
        adapter = select_site_adapter(
            "https://careers.example.com/campus/jobs",
            "<html><body>校园招聘</body></html>",
        )

        self.assertEqual(adapter.kind, SiteKind.GENERIC)
        self.assertIn("产品类筛选", adapter.browser_plan())


class CollectionStoreTests(unittest.TestCase):
    def test_persists_non_sensitive_recipe_and_checkpoint(self) -> None:
        recipe = SiteRecipe(
            host="careers.example.com",
            recipe_id="example-html-v1",
            capabilities={"pagination": "next_button", "job_link_selector": "a[data-job-id]"},
        )
        checkpoint = CollectionCheckpoint(
            career_url="https://careers.example.com/campus/jobs",
            page_number=3,
            seen_job_ids=("one", "two"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CollectionStore(Path(temp_dir))
            store.save_recipe(recipe)
            store.save_checkpoint("example-run", checkpoint)

            self.assertEqual(store.load_recipe("careers.example.com"), recipe)
            self.assertEqual(store.load_checkpoint("example-run"), checkpoint)

    def test_rejects_sensitive_recipe_data(self) -> None:
        recipe = SiteRecipe(
            host="careers.example.com",
            recipe_id="bad",
            capabilities={"authorization": "Bearer private-value"},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(SensitiveCollectionDataError):
                CollectionStore(Path(temp_dir)).save_recipe(recipe)

    def test_reads_only_unexpired_non_sensitive_cache_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CollectionStore(Path(temp_dir))
            store.save_cache_entry(
                "示例科技|2027|产品类",
                {"岗位数": 12, "内容指纹": "abc"},
                ttl_seconds=60,
            )
            self.assertEqual(
                store.load_cache_entry("示例科技|2027|产品类", now_unix=0),
                {"岗位数": 12, "内容指纹": "abc"},
            )
            self.assertIsNone(store.load_cache_entry("示例科技|2027|产品类", now_unix=9_999_999_999))

    def test_rejects_sensitive_cache_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CollectionStore(Path(temp_dir))
            with self.assertRaises(SensitiveCollectionDataError):
                store.save_cache_entry("示例", {"cookie": "private"}, ttl_seconds=60)


if __name__ == "__main__":
    unittest.main()
