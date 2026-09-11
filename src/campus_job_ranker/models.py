from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


VALID_SIGNAL_STATES = frozenset({"strong", "partial", "conflict", "unknown"})
VALID_REQUIREMENT_STATES = frozenset({"pass", "conflict", "unknown"})


class ValidationError(ValueError):
    """Raised when structured run input violates the public contract."""


@dataclass(frozen=True)
class Signal:
    state: str
    evidence: List[str] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class Job:
    id: str
    company: str
    title: str
    department: str
    location: str
    url: str
    description: str
    hard_requirements: Dict[str, str]
    signals: Dict[str, Signal]
    similar_group: Optional[str] = None


@dataclass(frozen=True)
class RunInput:
    company_name: str
    career_url: str
    run: Dict[str, Any]
    profile_evidence: List[Dict[str, Any]]
    company_evidence: List[Dict[str, Any]]
    jobs: List[Job]


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{field_name} 必须是对象")
    return value


def _text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValidationError(f"{field_name} 必须是非空字符串")
    return value.strip()


def _list_of_mappings(value: Any, field_name: str) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} 必须是数组")
    result: List[Dict[str, Any]] = []
    for index, item in enumerate(value):
        result.append(dict(_mapping(item, f"{field_name}[{index}]")))
    return result


def _parse_signals(value: Any, job_id: str) -> Dict[str, Signal]:
    raw = _mapping(value, f"jobs[{job_id}].signals")
    parsed: Dict[str, Signal] = {}
    for criterion_id, item in raw.items():
        if not isinstance(criterion_id, str) or not criterion_id:
            raise ValidationError(f"jobs[{job_id}].signals 的子项 ID 无效")
        signal = _mapping(item, f"jobs[{job_id}].signals.{criterion_id}")
        state = _text(signal.get("state"), f"jobs[{job_id}].signals.{criterion_id}.state")
        if state not in VALID_SIGNAL_STATES:
            raise ValidationError(f"无效评分状态: {state}")
        raw_evidence = signal.get("evidence", [])
        if not isinstance(raw_evidence, list) or not all(isinstance(entry, str) for entry in raw_evidence):
            raise ValidationError(f"jobs[{job_id}].signals.{criterion_id}.evidence 必须是字符串数组")
        parsed[criterion_id] = Signal(
            state=state,
            evidence=[entry.strip() for entry in raw_evidence if entry.strip()],
            note=str(signal.get("note", "")).strip(),
        )
    return parsed


def _parse_requirements(value: Any, job_id: str) -> Dict[str, str]:
    raw = _mapping(value, f"jobs[{job_id}].hard_requirements")
    parsed: Dict[str, str] = {}
    for requirement_id, state_value in raw.items():
        state = _text(state_value, f"jobs[{job_id}].hard_requirements.{requirement_id}")
        if state not in VALID_REQUIREMENT_STATES:
            raise ValidationError(f"无效硬条件状态: {state}")
        parsed[str(requirement_id)] = state
    return parsed


def _parse_job(value: Any, expected_company: str, index: int) -> Job:
    raw = _mapping(value, f"jobs[{index}]")
    job_id = _text(raw.get("id"), f"jobs[{index}].id")
    company = _text(raw.get("company", expected_company), f"jobs[{index}].company")
    if company != expected_company:
        raise ValidationError(
            f"一次运行只能包含一家公司：期望 {expected_company}，但岗位 {job_id} 属于 {company}"
        )
    url = _text(raw.get("url"), f"jobs[{index}].url")
    if not url.startswith(("https://", "http://")):
        raise ValidationError(f"jobs[{index}].url 必须是 HTTP(S) 链接")
    similar_group_value = raw.get("similar_group")
    similar_group = None
    if similar_group_value is not None:
        similar_group = _text(similar_group_value, f"jobs[{index}].similar_group")
    return Job(
        id=job_id,
        company=company,
        title=_text(raw.get("title"), f"jobs[{index}].title"),
        department=_text(raw.get("department", "未知"), f"jobs[{index}].department"),
        location=_text(raw.get("location", "未知"), f"jobs[{index}].location"),
        url=url,
        description=_text(raw.get("description", ""), f"jobs[{index}].description", allow_empty=True),
        hard_requirements=_parse_requirements(raw.get("hard_requirements", {}), job_id),
        signals=_parse_signals(raw.get("signals", {}), job_id),
        similar_group=similar_group,
    )


def load_run_input(payload: Mapping[str, Any]) -> RunInput:
    """Validate a JSON-compatible payload and return an immutable run model."""

    root = _mapping(payload, "root")
    company = _mapping(root.get("company"), "company")
    company_name = _text(company.get("name"), "company.name")
    career_url = _text(company.get("career_url"), "company.career_url")
    if not career_url.startswith(("https://", "http://")):
        raise ValidationError("company.career_url 必须是 HTTP(S) 链接")

    jobs_raw = root.get("jobs")
    if not isinstance(jobs_raw, list):
        raise ValidationError("jobs 必须是数组")
    jobs = [_parse_job(item, company_name, index) for index, item in enumerate(jobs_raw)]
    job_ids = [job.id for job in jobs]
    if len(job_ids) != len(set(job_ids)):
        raise ValidationError("jobs.id 必须在本次运行中唯一")

    return RunInput(
        company_name=company_name,
        career_url=career_url,
        run=dict(_mapping(root.get("run", {}), "run")),
        profile_evidence=_list_of_mappings(root.get("profile_evidence", []), "profile_evidence"),
        company_evidence=_list_of_mappings(root.get("company_evidence", []), "company_evidence"),
        jobs=jobs,
    )
