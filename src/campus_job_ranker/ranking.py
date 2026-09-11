from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .models import Job, RunInput
from .scoring import AI_DEPTH, CRITERIA, OPPORTUNITY, PERSONAL_MATCH, ScoreBreakdown, score_signals


@dataclass(frozen=True)
class RankedJob:
    job: Job
    score: ScoreBreakdown
    excluded: bool
    exclusion_reasons: List[str]
    rank: Optional[int] = None


@dataclass(frozen=True)
class RecommendationSelection:
    """One displayed recommendation, distinct from the auditable score rank."""

    item: RankedJob
    position: int
    kind: str = "evidence_top_three"


def _unknown_weight_in_dimension(item: RankedJob, dimension: str) -> float:
    return sum(
        criterion.points
        for criterion_id, criterion in CRITERIA.items()
        if criterion.dimension == dimension
        and item.score.effective_states.get(criterion_id) == "unknown"
    )


def select_recommendations(ranked: List[RankedJob]) -> List[RecommendationSelection]:
    """Keep evidence Top 3 and optionally add one high-potential exception.

    A high-potential exception never changes the deterministic score rank.  It
    is for jobs whose fit and AI depth are already verified, but whose
    business-line facts are still too incomplete to receive opportunity
    points.  At most one job receives the additional display slot.
    """

    evidence_top_three = [
        item for item in ranked if not item.excluded and item.rank is not None and item.rank <= 3
    ]
    selected = [
        RecommendationSelection(item=item, position=index)
        for index, item in enumerate(evidence_top_three, start=1)
    ]
    if not evidence_top_three:
        return selected

    cutoff = min(item.score.conservative_score for item in evidence_top_three)
    candidates = [
        item
        for item in ranked
        if (
            not item.excluded
            and item.rank is not None
            and item.rank > 3
            and item.score.dimension_scores[PERSONAL_MATCH] >= 25.0
            and item.score.dimension_scores[AI_DEPTH] >= 22.0
            and item.score.theoretical_upper >= cutoff
            and _unknown_weight_in_dimension(item, OPPORTUNITY) >= 12.0
        )
    ]
    if not candidates:
        return selected

    exception = sorted(
        candidates,
        key=lambda item: (
            -item.score.theoretical_upper,
            -item.score.conservative_score,
            item.rank or 0,
            item.job.title,
            item.job.id,
        ),
    )[0]
    selected.append(
        RecommendationSelection(
            item=exception,
            position=len(selected) + 1,
            kind="high_potential_exception",
        )
    )
    return selected


def rank_jobs(run_input: RunInput) -> List[RankedJob]:
    """Rank eligible jobs and append excluded jobs without dropping them."""

    evaluated: List[RankedJob] = []
    for job in run_input.jobs:
        reasons = sorted(
            requirement_id
            for requirement_id, state in job.hard_requirements.items()
            if state == "conflict"
        )
        evaluated.append(
            RankedJob(
                job=job,
                score=score_signals(job.signals),
                excluded=bool(reasons),
                exclusion_reasons=reasons,
            )
        )

    eligible = sorted(
        (item for item in evaluated if not item.excluded),
        key=lambda item: (
            -item.score.conservative_score,
            -item.score.coverage,
            item.job.title,
            item.job.id,
        ),
    )

    ranked: List[RankedJob] = []
    previous_key = None
    dense_rank = 0
    for item in eligible:
        rank_key = (item.score.conservative_score, item.score.coverage)
        if rank_key != previous_key:
            dense_rank += 1
            previous_key = rank_key
        ranked.append(
            RankedJob(
                job=item.job,
                score=item.score,
                excluded=False,
                exclusion_reasons=[],
                rank=dense_rank,
            )
        )

    excluded = sorted(
        (item for item in evaluated if item.excluded),
        key=lambda item: (item.job.title, item.job.id),
    )
    return ranked + excluded
