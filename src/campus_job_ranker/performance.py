"""本地、非敏感的岗位筛选运行性能记录。"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from time import monotonic
from typing import Callable, Dict, Iterable, List, Mapping, Optional


DEFAULT_TOTAL_BUDGET_MS = 90_000

OUTCOME_LABELS = {
    "success": "成功",
    "failed": "失败",
    "timeout": "超时",
    "skipped": "跳过",
    "needs_user": "需要人工操作",
}

LAYER_LABELS = {
    "api": "公开接口",
    "html": "静态页面",
    "scoped_dom": "受限页面快照",
    "assisted_browser": "浏览器协助",
    "none": "未采集",
    "reporting": "评分与报告",
    "public_sync_fallback": "公开同步源预筛",
}


@dataclass(frozen=True)
class PerformanceStage:
    """一个不包含正文、凭据或原始页面的耗时阶段。"""

    name: str
    duration_ms: int
    budget_ms: int
    outcome: str
    layer: str = ""
    reason: str = ""

    def as_user_dict(self) -> Dict[str, object]:
        return {
            "名称": self.name,
            "耗时毫秒": self.duration_ms,
            "预算毫秒": self.budget_ms,
            "结果": OUTCOME_LABELS.get(self.outcome, "失败"),
            "采集层": LAYER_LABELS.get(self.layer, self.layer or "不适用"),
            "原因": self.reason or "无",
        }


@dataclass
class PerformanceTracker:
    """为单次运行记录阶段耗时，并生成中文审计摘要。"""

    budget_ms: int = DEFAULT_TOTAL_BUDGET_MS
    clock: Callable[[], float] = monotonic
    _started_at: float = field(init=False)
    _stages: List[PerformanceStage] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.budget_ms <= 0:
            raise ValueError("总时间预算必须大于零")
        self._started_at = self.clock()

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((self.clock() - self._started_at) * 1000))

    @property
    def remaining_ms(self) -> int:
        return max(0, self.budget_ms - self.elapsed_ms)

    @property
    def exhausted(self) -> bool:
        return self.remaining_ms == 0

    @property
    def stages(self) -> List[PerformanceStage]:
        return list(self._stages)

    def record(
        self,
        name: str,
        duration_ms: int,
        budget_ms: int,
        outcome: str,
        *,
        layer: str = "",
        reason: str = "",
    ) -> PerformanceStage:
        stage = PerformanceStage(
            name=name,
            duration_ms=max(0, int(duration_ms)),
            budget_ms=max(0, int(budget_ms)),
            outcome=outcome,
            layer=layer,
            reason=reason,
        )
        self._stages.append(stage)
        return stage

    def record_elapsed(
        self,
        name: str,
        started_at: float,
        budget_ms: int,
        outcome: str,
        *,
        layer: str = "",
        reason: str = "",
    ) -> PerformanceStage:
        duration_ms = max(0, int((self.clock() - started_at) * 1000))
        if duration_ms > budget_ms and outcome == "success":
            outcome = "timeout"
            reason = reason or "阶段耗时超过预算"
        return self.record(
            name,
            duration_ms,
            budget_ms,
            outcome,
            layer=layer,
            reason=reason,
        )

    def as_user_dict(self, collection: Optional[Mapping[str, int]] = None) -> Dict[str, object]:
        elapsed_ms = max(self.elapsed_ms, sum(stage.duration_ms for stage in self._stages))
        longest = max(self._stages, key=lambda stage: stage.duration_ms, default=None)
        return {
            "版本": 1,
            "总耗时毫秒": elapsed_ms,
            "总预算毫秒": self.budget_ms,
            "是否在预算内完成": elapsed_ms <= self.budget_ms,
            "最长阶段": longest.name if longest else "无",
            "阶段": [stage.as_user_dict() for stage in self._stages],
            "采集统计": dict(collection or {}),
        }


def localized_collection_attempts(attempts: Iterable[Mapping[str, object]]) -> List[Dict[str, object]]:
    """把内部采集尝试转为安全的中文运行摘要。"""

    result: List[Dict[str, object]] = []
    for attempt in attempts:
        layer = str(attempt.get("layer", "none"))
        outcome = str(attempt.get("outcome", "failed"))
        reason = str(attempt.get("message", "")).strip()
        if "10039" in reason or "anti-automation" in reason.lower():
            reason = "官网公开接口触发反自动化拦截，系统未绕过访问控制。"
        elif reason and not re.search(r"[\u4e00-\u9fff]", reason):
            reason = "采集失败，需结合官网页面人工核验。"
        result.append(
            {
                "采集层": LAYER_LABELS.get(layer, layer),
                "结果": OUTCOME_LABELS.get(outcome, "失败"),
                "耗时毫秒": int(attempt.get("duration_ms", 0)),
                "原因": reason or "无",
            }
        )
    return result
