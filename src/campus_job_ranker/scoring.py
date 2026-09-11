from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Union

from .models import Signal, ValidationError


PERSONAL_MATCH = "personal_match"
AI_DEPTH = "ai_depth"
OPPORTUNITY = "business_and_role_opportunity"
GROWTH = "role_growth"

DIMENSION_LABELS = {
    PERSONAL_MATCH: "个人能力匹配",
    AI_DEPTH: "人工智能落地深度",
    OPPORTUNITY: "所属业务与岗位机会前景",
    GROWTH: "岗位成长空间",
}

DIMENSION_WEIGHTS = {
    PERSONAL_MATCH: 30.0,
    AI_DEPTH: 27.5,
    OPPORTUNITY: 27.5,
    GROWTH: 15.0,
}


@dataclass(frozen=True)
class Criterion:
    dimension: str
    label: str
    points: float


CRITERIA: Dict[str, Criterion] = {
    "personal_relevant_context": Criterion(PERSONAL_MATCH, "相关业务或产品场景经历", 8.0),
    "personal_owner": Criterion(PERSONAL_MATCH, "端到端产品负责程度", 7.0),
    "personal_ai_mechanism": Criterion(PERSONAL_MATCH, "相关人工智能或产品机制经验", 6.0),
    "personal_results": Criterion(PERSONAL_MATCH, "可验证的量化结果", 5.0),
    "personal_transfer": Criterion(PERSONAL_MATCH, "产品或技术能力迁移", 4.0),
    "ai_core": Criterion(AI_DEPTH, "人工智能是否为产品核心能力", 7.5),
    "ai_agent_workflow": Criterion(AI_DEPTH, "智能体、模型策略或工作流参与深度", 6.5),
    "ai_evaluation_loop": Criterion(AI_DEPTH, "评测、问题案例与数据闭环", 5.5),
    "ai_live_value": Criterion(AI_DEPTH, "真实上线和业务价值闭环", 4.5),
    "ai_cross_function": Criterion(AI_DEPTH, "算法、工程和数据协同深度", 3.5),
    "opportunity_growth": Criterion(OPPORTUNITY, "业务线或产品的增量空间", 7.5),
    "opportunity_investment": Criterion(OPPORTUNITY, "公司对该方向的近期投入", 6.5),
    "opportunity_advantage": Criterion(OPPORTUNITY, "独特场景、数据或生态优势", 5.5),
    "opportunity_value_loop": Criterion(OPPORTUNITY, "岗位可影响的价值闭环", 4.5),
    "opportunity_differentiation": Criterion(OPPORTUNITY, "差异化和出业绩空间", 3.5),
    "growth_zero_to_one": Criterion(GROWTH, "0 到 1 或高速迭代机会", 5.0),
    "growth_scope": Criterion(GROWTH, "职责边界和决策参与度", 4.0),
    "growth_complexity": Criterion(GROWTH, "跨团队和问题复杂度", 3.0),
    "growth_visibility": Criterion(GROWTH, "结果可见性和出业绩空间", 3.0),
}


@dataclass(frozen=True)
class ScoreBreakdown:
    conservative_score: float
    theoretical_upper: float
    coverage: float
    confidence: str
    dimension_scores: Dict[str, float]
    dimension_upper: Dict[str, float]
    effective_states: Dict[str, str]


SignalLike = Union[Signal, Mapping[str, object]]


def _state_and_evidence(value: SignalLike) -> tuple:
    if isinstance(value, Signal):
        return value.state, value.evidence
    state = str(value.get("state", "unknown"))
    evidence_value = value.get("evidence", [])
    evidence = evidence_value if isinstance(evidence_value, list) else []
    return state, [str(item) for item in evidence if str(item).strip()]


def score_signals(signals: Mapping[str, SignalLike]) -> ScoreBreakdown:
    """Calculate evidence-gated conservative and upper-bound scores."""

    unknown_ids = set(signals) - set(CRITERIA)
    if unknown_ids:
        raise ValidationError(f"未知评分子项: {', '.join(sorted(unknown_ids))}")

    dimension_scores = {dimension: 0.0 for dimension in DIMENSION_WEIGHTS}
    dimension_upper = {dimension: 0.0 for dimension in DIMENSION_WEIGHTS}
    effective_states: Dict[str, str] = {}
    known_weight = 0.0

    for criterion_id, criterion in CRITERIA.items():
        value = signals.get(criterion_id, {"state": "unknown", "evidence": []})
        state, evidence = _state_and_evidence(value)
        if state not in {"strong", "partial", "conflict", "unknown"}:
            raise ValidationError(f"无效评分状态: {state}")
        if state != "unknown" and not evidence:
            state = "unknown"
        effective_states[criterion_id] = state

        awarded = 0.0
        if state == "strong":
            awarded = criterion.points
        elif state == "partial":
            awarded = criterion.points * 0.5

        dimension_scores[criterion.dimension] += awarded
        dimension_upper[criterion.dimension] += awarded
        if state == "unknown":
            dimension_upper[criterion.dimension] += criterion.points
        else:
            known_weight += criterion.points

    conservative = round(sum(dimension_scores.values()), 1)
    upper = round(sum(dimension_upper.values()), 1)
    coverage = round(known_weight / 100.0, 4)
    confidence = "high" if coverage >= 0.8 else "medium" if coverage >= 0.5 else "low"
    return ScoreBreakdown(
        conservative_score=conservative,
        theoretical_upper=upper,
        coverage=coverage,
        confidence=confidence,
        dimension_scores={key: round(value, 1) for key, value in dimension_scores.items()},
        dimension_upper={key: round(value, 1) for key, value in dimension_upper.items()},
        effective_states=effective_states,
    )
