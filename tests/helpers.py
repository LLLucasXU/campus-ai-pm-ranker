from __future__ import annotations

from campus_job_ranker.scoring import CRITERIA


def signals(state: str = "strong") -> dict[str, dict[str, object]]:
    return {
        criterion_id: {
            "state": state,
            "evidence": [f"evidence for {criterion_id}"],
        }
        for criterion_id in CRITERIA
    }


def job(
    job_id: str,
    title: str,
    *,
    company: str = "示例科技",
    signal_values: dict[str, dict[str, object]] | None = None,
    similar_group: str | None = None,
    hard_requirements: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "id": job_id,
        "company": company,
        "title": title,
        "department": "AI 产品",
        "location": "北京",
        "url": f"https://careers.example.com/jobs/{job_id}",
        "description": f"{title} 的岗位描述",
        "similar_group": similar_group,
        "hard_requirements": hard_requirements or {"campus_full_time": "pass"},
        "signals": signal_values or signals(),
    }


def run_payload(jobs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "company": {"name": "示例科技", "career_url": "https://careers.example.com/campus"},
        "run": {
            "collected_at": "2026-08-25T10:00:00+08:00",
            "collection_method": "fixture",
            "pagination_complete": True,
            "list_job_count": len(jobs),
            "detail_success_count": len(jobs),
            "detail_failure_count": 0,
            "candidate_profile_refreshed_at": "2026-08-25T09:55:00+08:00",
            "errors": [],
        },
        "profile_evidence": [
            {
                "id": "profile-1",
                "experience": "AI 产品实习",
                "source": "experience_file",
                "source_revision": "2026-08-25T09:55:00+08:00",
                "capabilities": ["产品设计", "评测"],
            }
        ],
        "company_evidence": [
            {
                "id": "company-1",
                "claim": "该业务线近期持续投入",
                "url": "https://example.com/strategy",
                "published_at": "2026-08-01",
            }
        ],
        "jobs": jobs,
    }
