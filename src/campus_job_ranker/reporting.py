from __future__ import annotations

import csv
import json
import re
from time import monotonic
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .models import RunInput
from .performance import (
    DEFAULT_TOTAL_BUDGET_MS,
    LAYER_LABELS,
    PerformanceTracker,
    localized_collection_attempts,
)
from .ranking import RankedJob, RecommendationSelection, rank_jobs, select_recommendations
from .scoring import (
    AI_DEPTH,
    CRITERIA,
    DIMENSION_LABELS,
    DIMENSION_WEIGHTS,
    GROWTH,
    OPPORTUNITY,
    PERSONAL_MATCH,
)


OUTPUT_FILENAMES = (
    "run-summary.json",
    "performance.json",
    "profile-evidence.json",
    "company-evidence.json",
    "all-jobs.jsonl",
    "ranking.csv",
    "report.md",
)

OUTPUT_DISPLAY_NAMES = {
    "run-summary.json": "运行摘要",
    "performance.json": "性能监控",
    "profile-evidence.json": "候选人证据",
    "company-evidence.json": "公司证据",
    "all-jobs.jsonl": "全量岗位审计数据",
    "ranking.csv": "岗位排名",
    "report.md": "筛选报告",
}

DISCLAIMER = (
    "当前分数和排名仅用于本公司本次候选岗位的内部比较，"
    "不可与其他公司的岗位得分横向比较；分数也不是录用概率。"
)

HARD_REQUIREMENT_LABELS = {
    "campus_full_time": "应届全职身份",
    "graduation_year": "毕业届别",
    "education": "学历",
    "major": "专业",
    "location_preference": "地点偏好",
    "language_working_proficiency": "英语工作能力",
}

SIGNAL_STATE_LABELS = {
    "strong": "证据充分",
    "partial": "证据部分支持",
    "conflict": "存在冲突",
    "unknown": "待确认",
}

SOURCE_LABELS = {
    "resume": "简历",
    "experience_file": "本地经历文档",
    "feishu": "飞书经历文档",
}

COLLECTION_METHOD_LABELS = {
    "api": "公开接口",
    "html": "静态页面",
    "browser": "浏览器",
    "mixed": "混合采集",
    "fixture": "测试样例",
    "external_sync_preliminary": "公开同步源预筛",
}


def _localized_text(value: Any, *, fallback: str = "证据待补充为中文说明") -> str:
    """避免将英文模板说明直接写入面向用户的交付文件。"""

    text = str(value or "").strip()
    if not text:
        return ""
    # 含中文的句子可以保留必要的技术名词、产品名和缩写；不能因其中
    # 出现 Agent、MCP 等词而把一整条中文证据替换成占位符。
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    if text.startswith(("http://", "https://")):
        return text
    english_words = re.findall(r"[A-Za-z]{3,}", text)
    allowed_terms = {
        "AI",
        "RAG",
        "LLM",
        "SQL",
        "Agent",
        "Prompt",
        "VLA",
        "Robotaxi",
        "AIGC",
        "MCP",
    }
    if english_words and any(word not in allowed_terms for word in english_words):
        return fallback
    return fallback


def _localized_error(value: Any) -> str:
    text = str(value or "").strip()
    if "10039" in text or "anti-automation" in text.lower():
        return "官网公开接口触发反自动化拦截，系统未绕过访问控制。"
    if "JD texts were read" in text:
        return "岗位说明来自公开同步源，每条岗位均保留官网链接，需在官网人工复核。"
    if "sync page states" in text:
        return "公开同步源声明本次为产品类岗位集合，官网分页完整性尚未独立验证。"
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    return "采集过程出现待人工核验的问题。"


def _confidence_label(value: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(value, "低")


def _localized_version(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("revision "):
        return "版本 " + text.removeprefix("revision ")
    if text.startswith("revision:"):
        return "版本 " + text.removeprefix("revision:").strip()
    return text


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ranked_job_dict(item: RankedJob) -> Dict[str, Any]:
    job = item.job
    return {
        "岗位编号": job.id,
        "公司": job.company,
        "岗位名称": job.title,
        "部门": job.department,
        "地点": job.location,
        "官网链接": job.url,
        "岗位描述": job.description,
        "硬条件": {
            _requirement_label(key): SIGNAL_STATE_LABELS.get(value, "待确认")
            for key, value in job.hard_requirements.items()
        },
        "评分信号": {
            CRITERIA[criterion_id].label: {
                "状态": SIGNAL_STATE_LABELS.get(signal.state, "待确认"),
                "证据": [_localized_text(entry) for entry in signal.evidence],
                "说明": _localized_text(signal.note),
            }
            for criterion_id, signal in job.signals.items()
        },
        "相似岗位组": job.similar_group or "无",
        "证据排名": item.rank,
        "是否排除": "是" if item.excluded else "否",
        "排除原因": [_requirement_label(reason) for reason in item.exclusion_reasons],
        "保守分": item.score.conservative_score,
        "理论上限": item.score.theoretical_upper,
        "证据覆盖率": item.score.coverage,
        "置信度": _confidence_label(item.score.confidence),
        "维度得分": {
            DIMENSION_LABELS[key]: value for key, value in item.score.dimension_scores.items()
        },
        "有效状态": {
            CRITERIA[key].label: SIGNAL_STATE_LABELS.get(value, "待确认")
            for key, value in item.score.effective_states.items()
        },
    }


def _dimension_text(item: RankedJob) -> str:
    return "；".join(
        f"{DIMENSION_LABELS[key]} {value:g}"
        for key, value in item.score.dimension_scores.items()
    )


def _dimension_evidence(item: RankedJob, dimension: str, limit: int = 5) -> List[str]:
    evidence: List[str] = []
    for criterion_id, signal in item.job.signals.items():
        criterion = CRITERIA.get(criterion_id)
        if (
            criterion is not None
            and criterion.dimension == dimension
            and item.score.effective_states.get(criterion_id) in {"strong", "partial"}
        ):
            evidence.extend(signal.evidence)
        if len(evidence) >= limit:
            break
    localized: List[str] = []
    for entry in evidence:
        text = _localized_text(entry)
        if text and text not in localized:
            localized.append(text)
        if len(localized) >= limit:
            break
    return localized


def _criterion_labels(item: RankedJob, states: set, limit: int = 3) -> List[str]:
    labels = [
        criterion.label
        for criterion_id, criterion in CRITERIA.items()
        if item.score.effective_states.get(criterion_id) in states
    ]
    return labels[:limit]


def _requirement_label(requirement_id: str) -> str:
    return HARD_REQUIREMENT_LABELS.get(requirement_id, "其他硬条件")


def _risk_labels(item: RankedJob, limit: int = 4) -> List[str]:
    labels = [
        f"{'明确冲突' if state == 'conflict' else '待确认'}：{CRITERIA[criterion_id].label}"
        for criterion_id, state in item.score.effective_states.items()
        if state in {"conflict", "unknown"}
    ][:limit]
    unknown_requirements = [
        f"硬条件待确认：{_requirement_label(requirement_id)}"
        for requirement_id, state in item.job.hard_requirements.items()
        if state == "unknown"
    ]
    return (labels + unknown_requirements)[:limit]


def _evidence_lines(evidence: List[str]) -> List[str]:
    return [f"- {entry}" for entry in evidence if entry] or ["- 暂无已验证证据"]


def _recommendation_heading(selection: RecommendationSelection) -> str:
    item = selection.item
    if selection.kind == "high_potential_exception":
        return (
            f"### 推荐第 {selection.position} 位（高潜待核验；证据排名 {item.rank}）｜"
            f"[{item.job.title}]({item.job.url})"
        )
    return f"### 推荐第 {selection.position} 位｜[{item.job.title}]({item.job.url})"


def _render_report(run_input: RunInput, ranked: Iterable[RankedJob]) -> str:
    items = list(ranked)
    recommendations = select_recommendations(items)
    detailed_item_ids = {selection.item.job.id for selection in recommendations}
    brief = [
        item
        for item in items
        if item.rank is not None and 4 <= item.rank <= 10 and item.job.id not in detailed_item_ids
    ]
    excluded = [item for item in items if item.excluded]

    lines = [
        f"# {run_input.company_name} 校招人工智能产品岗位筛选",
        "",
        f"> {DISCLAIMER}",
        "",
        f"官方校招入口：{run_input.career_url}",
        "",
    ]
    scope = str(run_input.run.get("scope", "")).strip()
    if scope or run_input.run.get("pagination_complete") is not True:
        lines.extend(
            [
                "## 本次范围与完整性",
                "",
                f"- 本次范围：{_localized_text(scope, fallback='本次指定候选范围')}" if scope else "- 本次范围：本次指定候选范围。",
                (
                    "- 已完整读取本次范围内的岗位详情；该结果不代表覆盖该公司全部产品类岗位。"
                    if run_input.run.get("pagination_complete") is True
                    else "- 当前结果为指定候选范围内的部分结果，未宣称覆盖该公司全部产品类岗位。"
                ),
                f"- 已读取详情：{run_input.run.get('detail_success_count', 0)} 个；详情失败：{run_input.run.get('detail_failure_count', 0)} 个。",
            ]
        )
    errors = run_input.run.get("errors")
    if isinstance(errors, list):
        for error in errors:
            lines.append(f"- 采集说明：{_localized_error(error)}")
    if scope or run_input.run.get("pagination_complete") is not True:
        lines.append("")
    collection_layer = str(run_input.run.get("collection_layer", "")).strip()
    if collection_layer:
        pagination_complete = run_input.run.get("pagination_complete")
        layer_label = LAYER_LABELS.get(collection_layer, "其他采集方式")
        lines.extend(
            [
                "## 采集状态",
                "",
                f"- 最终采集层：{layer_label}",
                f"- 产品类筛选已确认：{'是' if run_input.run.get('product_category_confirmed') is True else '否或待确认'}",
                f"- 分页完整：{'是' if pagination_complete is True else '否或待确认'}",
                f"- 候选详情已完整读取：{'是' if run_input.run.get('details_complete') is True else '否或待确认'}",
            ]
        )
        user_action = run_input.run.get("user_action")
        if isinstance(user_action, str) and user_action.strip():
            lines.append(f"- 需要人工操作：{_localized_text(user_action, fallback='请在官网页面完成必要操作后继续')}")
        if run_input.run.get("budget_exhausted"):
            lines.append("- 自动采集时间预算已耗尽，已生成部分结果。")
        performance = run_input.run.get("performance")
        if isinstance(performance, dict):
            total_ms = performance.get("总耗时毫秒")
            longest = performance.get("最长阶段")
            if isinstance(total_ms, int):
                lines.append(f"- 本次已记录耗时：{total_ms} 毫秒")
            if isinstance(longest, str) and longest:
                lines.append(f"- 最长阶段：{longest}")
        lines.append("")
    lines.extend(["## 核心推荐（保守前三名 + 高潜破格）", ""])
    lines.extend(
        [
            "保守前三名按已验证证据排序；最多额外展示 1 个高潜岗位。高潜岗位不改变原始证据排名，"
            "只表示其个人匹配和人工智能落地深度已很强，但业务前景仍需人工核验。",
            "",
        ]
    )
    if not recommendations:
        lines.extend(["没有可进入核心推荐区的岗位。", ""])
    for selection in recommendations:
        item = selection.item
        lines.extend(
            [
                _recommendation_heading(selection),
                "",
                f"- 部门/地点：{item.job.department} / {item.job.location}",
                f"- 保守分/上限：{item.score.conservative_score:g} / {item.score.theoretical_upper:g}",
                f"- 证据覆盖率/置信度：{item.score.coverage:.0%} / "
                f"{_confidence_label(item.score.confidence)}",
                f"- 四维得分：{_dimension_text(item)}",
                f"- 相似岗位组：{item.job.similar_group or '无'}",
                "",
                "#### 为什么适合",
                "",
                *(
                    [
                        "因业务前景证据不足触发高潜破格推荐：个人能力匹配和人工智能落地深度均已达到高阈值，"
                        "理论上限可进入保守 Top 3 门槛；请优先核验其业务归属、产品阶段与结果责任。",
                        "",
                    ]
                    if selection.kind == "high_potential_exception"
                    else []
                ),
                f"个人能力匹配得分为 {item.score.dimension_scores[PERSONAL_MATCH]:g} / "
                f"{DIMENSION_WEIGHTS[PERSONAL_MATCH]:g}；当前已验证优势包括："
                f"{'、'.join(_criterion_labels(item, {'strong', 'partial'})) or '暂无'}。",
                "",
                "#### 最相关的个人经历证据",
                "",
            ]
        )
        lines.extend(_evidence_lines(_dimension_evidence(item, PERSONAL_MATCH)))
        lines.extend(
            [
                "",
                "#### 人工智能落地深度判断",
                "",
                f"得分 {item.score.dimension_scores[AI_DEPTH]:g} / {DIMENSION_WEIGHTS[AI_DEPTH]:g}。",
            ]
        )
        lines.extend(_evidence_lines(_dimension_evidence(item, AI_DEPTH)))
        lines.extend(
            [
                "",
                "#### 所属业务与岗位机会前景",
                "",
                f"得分 {item.score.dimension_scores[OPPORTUNITY]:g} / {DIMENSION_WEIGHTS[OPPORTUNITY]:g}。",
            ]
        )
        lines.extend(_evidence_lines(_dimension_evidence(item, OPPORTUNITY)))
        lines.extend(
            [
                "",
                "#### 岗位成长空间",
                "",
                f"得分 {item.score.dimension_scores[GROWTH]:g} / {DIMENSION_WEIGHTS[GROWTH]:g}。",
            ]
        )
        lines.extend(_evidence_lines(_dimension_evidence(item, GROWTH)))
        lines.extend(["", "#### 主要缺口与待确认", ""])
        risks = _risk_labels(item)
        lines.extend([f"- {risk}" for risk in risks] or ["- 暂无明确缺口"])
        lines.append("")

    lines.extend(["## 原始证据排名第 4–10 名（简表）", ""])
    if brief:
        lines.extend(
            [
                "| 证据排名 | 岗位 | 部门 | 保守分 | 上限 | 证据覆盖 | 关键标签 | 主要风险 | 官方链接 |",
                "|---:|---|---|---:|---:|---:|---|---|---|",
            ]
        )
        for item in brief:
            key_labels = "、".join(_criterion_labels(item, {"strong", "partial"})) or "暂无"
            risks = "、".join(_risk_labels(item, limit=2)) or "暂无"
            lines.append(
                f"| {item.rank} | {item.job.title} | {item.job.department} | "
                f"{item.score.conservative_score:g} | {item.score.theoretical_upper:g} | "
                f"{item.score.coverage:.0%} | {key_labels} | {risks} | [查看岗位说明]({item.job.url}) |"
            )
    else:
        lines.append("没有第 4–10 名岗位。")
    lines.append("")

    if excluded:
        lines.extend(["## 硬条件排除（仍保留供复核）", ""])
        for item in excluded:
            reasons = "、".join(_requirement_label(reason) for reason in item.exclusion_reasons)
            lines.append(f"- [{item.job.title}]({item.job.url})：{reasons}")
        lines.append("")

    lines.extend(
        [
            "## 人工复核提示",
            "",
            "相似岗位不会合并或删除；并列岗位会保留相同排名。请在正式投递前核查官网状态、硬条件未知项和所有原始 JD。",
            "",
        ]
    )
    return "\n".join(lines)


def _localized_profile_evidence(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "编号": str(entry.get("id", "")),
            "经历": _localized_text(entry.get("experience")),
            "业务场景": _localized_text(entry.get("situation")),
            "本人动作": _localized_text(entry.get("action")),
            "产品或技术机制": [_localized_text(value) for value in entry.get("mechanism", [])],
            "结果": [_localized_text(value) for value in entry.get("result", [])],
            "能力标签": [_localized_text(value) for value in entry.get("capabilities", [])],
            "来源": SOURCE_LABELS.get(str(entry.get("source", "")), "其他来源"),
            "来源版本": str(entry.get("source_revision", "")),
            "置信度": _confidence_label(str(entry.get("confidence", ""))),
        }
        for entry in entries
    ]


def _localized_company_evidence(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    scope_labels = {
        "company": "公司",
        "business_line": "业务线",
        "product": "产品",
        "role": "岗位",
    }
    return [
        {
            "编号": str(entry.get("id", "")),
            "结论": _localized_text(entry.get("claim")),
            "来源链接": str(entry.get("url", "")),
            "发布日期或获取日期": str(entry.get("published_at", "")),
            "证据范围": scope_labels.get(str(entry.get("scope", "")), "其他范围"),
        }
        for entry in entries
    ]


def _localized_run_summary(run: Dict[str, Any], performance: Dict[str, Any], run_input: RunInput, ranked: List[RankedJob]) -> Dict[str, Any]:
    collection_attempts = run.get("collection_attempts", [])
    return {
        "公司": run_input.company_name,
        "官方校招入口": run_input.career_url,
        "采集时间": str(run.get("collected_at", "")),
        "采集方式": COLLECTION_METHOD_LABELS.get(
            str(run.get("collection_method", "")), "其他采集方式"
        ),
        "最终采集层": LAYER_LABELS.get(str(run.get("collection_layer", "none")), "未采集"),
        "产品类筛选已确认": run.get("product_category_confirmed") is True,
        "分页完整": run.get("pagination_complete") is True,
        "候选详情已完整读取": run.get("details_complete") is True,
        "列表岗位数": int(run.get("list_job_count", 0)),
        "详情成功数": int(run.get("detail_success_count", 0)),
        "详情失败数": int(run.get("detail_failure_count", 0)),
        "候选人资料版本": _localized_version(
            run.get("candidate_profile_refreshed_at", run.get("feishu_refreshed_at", ""))
        ),
        "自动采集预算耗尽": bool(run.get("budget_exhausted", False)),
        "采集尝试": localized_collection_attempts(
            collection_attempts if isinstance(collection_attempts, list) else []
        ),
        "问题": [_localized_error(value) for value in run.get("errors", [])],
        "岗位总数": len(run_input.jobs),
        "可参与排名岗位数": sum(not item.excluded for item in ranked),
        "硬条件排除岗位数": sum(item.excluded for item in ranked),
        "排名范围": "同一家公司、同一次筛选",
        "说明": DISCLAIMER,
        "性能监控": performance,
    }


def generate_outputs(run_input: RunInput, output_dir: Path) -> Dict[str, Path]:
    """生成中文、可审计的岗位筛选交付文件。"""

    output_dir.mkdir(parents=True, exist_ok=True)
    budget_ms = int(run_input.run.get("performance_budget_ms", DEFAULT_TOTAL_BUDGET_MS))
    tracker = PerformanceTracker(budget_ms=budget_ms)
    collection_attempts = run_input.run.get("collection_attempts", [])
    if isinstance(collection_attempts, list):
        for attempt in collection_attempts:
            if not isinstance(attempt, dict):
                continue
            layer = str(attempt.get("layer", "none"))
            raw_reason = str(attempt.get("message", "")).strip()
            tracker.record(
                f"采集：{LAYER_LABELS.get(layer, '其他采集方式')}",
                int(attempt.get("duration_ms", 0)),
                int(run_input.run.get("layer_budget_ms", 0)),
                str(attempt.get("outcome", "failed")),
                layer=layer,
                reason=_localized_error(raw_reason) if raw_reason else "",
            )
    scoring_started_at = monotonic()
    ranked = rank_jobs(run_input)
    output_paths = {filename: output_dir / filename for filename in OUTPUT_FILENAMES}

    tracker.record_elapsed("确定性评分与报告生成", scoring_started_at, 5_000, "success", layer="reporting")
    collection = {
        "列表岗位数": int(run_input.run.get("list_job_count", len(run_input.jobs))),
        "详情成功数": int(run_input.run.get("detail_success_count", 0)),
        "详情失败数": int(run_input.run.get("detail_failure_count", 0)),
        "缓存命中数": int(run_input.run.get("cache_hit_count", 0)),
        "缓存未命中数": int(run_input.run.get("cache_miss_count", 0)),
    }
    performance = tracker.as_user_dict(collection)
    performance["监控覆盖范围"] = (
        "覆盖采集与报告阶段"
        if isinstance(collection_attempts, list) and collection_attempts
        else "本次为历史运行重生成，仅记录评分与报告阶段；采集阶段原始耗时未留存。"
    )
    run_input.run["performance"] = performance

    _write_json(output_paths["performance.json"], performance)
    _write_json(
        output_paths["run-summary.json"],
        _localized_run_summary(run_input.run, performance, run_input, ranked),
    )
    _write_json(output_paths["profile-evidence.json"], _localized_profile_evidence(run_input.profile_evidence))
    _write_json(output_paths["company-evidence.json"], _localized_company_evidence(run_input.company_evidence))

    with output_paths["all-jobs.jsonl"].open("w", encoding="utf-8") as handle:
        for item in ranked:
            handle.write(json.dumps(_ranked_job_dict(item), ensure_ascii=False) + "\n")

    fieldnames = [
        "证据排名",
        "是否排除",
        "排除原因",
        "岗位编号",
        "岗位名称",
        "部门",
        "地点",
        "保守分",
        "理论上限",
        "证据覆盖率",
        "置信度",
        "相似岗位组",
        "官网链接",
    ]
    with output_paths["ranking.csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in ranked:
            writer.writerow(
                {
                    "证据排名": "" if item.rank is None else item.rank,
                    "是否排除": "是" if item.excluded else "否",
                    "排除原因": "；".join(_requirement_label(reason) for reason in item.exclusion_reasons),
                    "岗位编号": item.job.id,
                    "岗位名称": item.job.title,
                    "部门": item.job.department,
                    "地点": item.job.location,
                    "保守分": item.score.conservative_score,
                    "理论上限": item.score.theoretical_upper,
                    "证据覆盖率": item.score.coverage,
                    "置信度": _confidence_label(item.score.confidence),
                    "相似岗位组": item.job.similar_group or "无",
                    "官网链接": item.job.url,
                }
            )

    output_paths["report.md"].write_text(
        _render_report(run_input, ranked), encoding="utf-8"
    )
    return output_paths
