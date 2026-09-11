"""Generic, privacy-preserving collection runtime for campus career sites.

The runtime deliberately does not drive a browser or retain authentication
state. A Skill or browser layer supplies public API payloads, static HTML, a
scoped DOM snapshot, or verified public browser steps. This module validates
the observed steps, normalizes public job data, and records a safe checkpoint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
from time import monotonic
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse


COLLECTION_LAYERS = ("api", "html", "scoped_dom", "assisted_browser")
BROWSER_STEP_OUTCOMES = frozenset({"success", "failed", "timeout", "blocked", "skipped"})

DEFAULT_LAYER_BUDGET_MS = {
    "api": 8_000,
    "html": 5_000,
    "scoped_dom": 15_000,
    "assisted_browser": 75_000,
}


class CollectionError(ValueError):
    """Raised when a supplied collection payload cannot yield job records."""


class BrowserCollectionError(CollectionError):
    """Collection error retaining safe observations made before a browser stop."""

    def __init__(self, message: str, attempts: Sequence["CollectionAttempt"] = ()) -> None:
        super().__init__(message)
        self.attempts = tuple(attempts)


@dataclass(frozen=True)
class SiteRecipe:
    host: str
    recipe_id: str
    capabilities: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectionCheckpoint:
    career_url: str
    page_number: int = 1
    cursor: str = ""
    seen_job_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CollectedJob:
    id: str
    title: str
    url: str
    description: str = ""
    department: str = "未知"
    location: str = "未知"
    category: str = "未知"
    collection_layer: str = ""


@dataclass(frozen=True)
class CollectionAttempt:
    layer: str
    outcome: str
    duration_ms: int
    message: str = ""


@dataclass(frozen=True)
class LayerInput:
    """Already-read, non-sensitive source material for one collection layer."""

    available: bool = False
    pages: Sequence[Any] = ()
    pagination_complete: bool = False
    next_page_number: Optional[int] = None
    next_cursor: str = ""
    detail_url_template: str = ""


@dataclass(frozen=True)
class BrowserStep:
    """One observable, public browser-state transition.

    Browser drivers must only report information visible to a normal visitor.
    ``filter_confirmed`` is required for the product-category step so a click
    without a visible effect is not mistaken for a completed filter.
    """

    phase: str
    outcome: str
    duration_ms: int = 0
    message: str = ""
    filter_confirmed: Optional[bool] = None
    pagination_complete: Optional[bool] = None


@dataclass(frozen=True)
class BrowserLayerInput:
    """Non-sensitive result of one browser-driven public collection attempt."""

    available: bool = False
    steps: Sequence[BrowserStep] = ()
    pages: Sequence[Any] = ()
    pagination_complete: bool = False
    details_complete: bool = False
    next_page_number: Optional[int] = None
    next_cursor: str = ""
    detail_url_template: str = ""


@dataclass(frozen=True)
class CollectionRequest:
    career_url: str
    api: LayerInput = field(default_factory=LayerInput)
    html: LayerInput = field(default_factory=LayerInput)
    scoped_dom: LayerInput = field(default_factory=LayerInput)
    assisted_browser: BrowserLayerInput = field(default_factory=BrowserLayerInput)
    checkpoint: Optional[CollectionCheckpoint] = None
    user_action: str = ""
    total_budget_ms: int = 90_000
    layer_budget_ms: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LAYER_BUDGET_MS))


@dataclass(frozen=True)
class CollectionResult:
    jobs: Tuple[CollectedJob, ...]
    collection_layer: str
    pagination_complete: bool
    checkpoint: CollectionCheckpoint
    attempts: Tuple[CollectionAttempt, ...]
    user_action: str = ""
    budget_exhausted: bool = False
    details_complete: bool = False
    product_category_confirmed: Optional[bool] = None

    def run_summary(self) -> Dict[str, Any]:
        """Return safe fields that can be embedded in ``run-summary.json``."""

        return {
            "collection_layer": self.collection_layer,
            "pagination_complete": self.pagination_complete,
            "list_job_count": len(self.jobs),
            "details_complete": self.details_complete,
            "product_category_confirmed": self.product_category_confirmed,
            "collection_attempts": [asdict(attempt) for attempt in self.attempts],
            "collection_duration_ms": sum(attempt.duration_ms for attempt in self.attempts),
            "resume_checkpoint": {
                "page_number": self.checkpoint.page_number,
                "cursor": self.checkpoint.cursor,
                "seen_job_count": len(self.checkpoint.seen_job_ids),
            },
            "user_action": self.user_action or None,
            "budget_exhausted": self.budget_exhausted,
        }


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int):
        return str(value)
    return ""


def _first_text(record: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = _text(record.get(key))
        if value:
            return value
    return ""


def _stable_id(title: str, url: str) -> str:
    return sha256(f"{title}\n{url}".encode("utf-8")).hexdigest()[:16]


def _normalize_record(record: Mapping[str, Any], base_url: str, layer: str, detail_url_template: str = "") -> Optional[CollectedJob]:
    title = _first_text(record, ("title", "name", "positionName", "jobName", "positionTitle"))
    raw_url = _first_text(record, ("url", "link", "detailUrl", "detail_url", "jobUrl", "positionUrl"))
    job_id = _first_text(record, ("id", "jobId", "job_id", "positionId", "position_id"))
    if not raw_url and job_id and detail_url_template:
        raw_url = detail_url_template.replace("{id}", job_id)
    if not title or not raw_url:
        return None
    url = urljoin(base_url, raw_url)
    if urlparse(url).scheme not in {"http", "https"}:
        return None
    return CollectedJob(
        id=job_id or _stable_id(title, url),
        title=title,
        url=url,
        description=_first_text(
            record,
            (
                "description",
                "detail",
                "jobDescription",
                "job_description",
                "positionDemand",
                "position_demand",
                "desc",
            ),
        ),
        department=_first_text(record, ("department", "departmentName", "businessLine", "business_line")) or "未知",
        location=_first_text(record, ("location", "city", "workLocation", "work_location")) or "未知",
        category=_first_text(record, ("category", "positionCategory", "position_category")) or "未知",
        collection_layer=layer,
    )


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _deduplicate(jobs: Iterable[CollectedJob]) -> Tuple[CollectedJob, ...]:
    deduplicated: Dict[str, CollectedJob] = {}
    for job in jobs:
        deduplicated.setdefault(job.id, job)
    return tuple(deduplicated.values())


class JsonApiCollector:
    layer = "api"

    def collect(self, source: LayerInput, career_url: str) -> Tuple[CollectedJob, ...]:
        jobs: List[CollectedJob] = []
        for page in source.pages:
            for record in _walk_mappings(page):
                normalized = _normalize_record(record, career_url, self.layer, source.detail_url_template)
                if normalized is not None:
                    jobs.append(normalized)
        result = _deduplicate(jobs)
        if not result:
            raise CollectionError("公开接口响应中未发现可标准化职位")
        return result


class _JobLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._anchor: Optional[Dict[str, str]] = None
        self._parts: List[str] = []
        self.records: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag != "a" or self._anchor is not None:
            return
        attr_map = {key: value or "" for key, value in attrs}
        href = attr_map.get("href", "")
        if href and not href.startswith(("javascript:", "#")):
            self._anchor = attr_map
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._anchor is None:
            return
        title = " ".join(part.strip() for part in self._parts if part.strip())
        href = self._anchor.get("href", "")
        normalized_href = href.lower()
        if title and any(token in normalized_href for token in ("job", "position", "career", "recruit")):
            self.records.append(
                {
                    "id": self._anchor.get("data-job-id") or self._anchor.get("data-position-id") or "",
                    "title": title,
                    "url": href,
                    "department": self._anchor.get("data-department", ""),
                    "location": self._anchor.get("data-location", ""),
                }
            )
        self._anchor = None
        self._parts = []


class HtmlCollector:
    layer = "html"

    def collect(self, source: LayerInput, career_url: str) -> Tuple[CollectedJob, ...]:
        jobs: List[CollectedJob] = []
        for page in source.pages:
            if not isinstance(page, str):
                continue
            parser = _JobLinkParser()
            parser.feed(page)
            for record in parser.records:
                normalized = _normalize_record(record, career_url, self.layer)
                if normalized is not None:
                    jobs.append(normalized)
        result = _deduplicate(jobs)
        if not result:
            raise CollectionError("HTML 页面中未发现职位链接")
        return result


class ScopedDomCollector:
    layer = "scoped_dom"

    def collect(self, source: LayerInput, career_url: str) -> Tuple[CollectedJob, ...]:
        jobs: List[CollectedJob] = []
        for page in source.pages:
            candidates: Sequence[Any]
            if isinstance(page, Mapping):
                candidates = (page,)
            elif isinstance(page, list):
                candidates = page
            else:
                continue
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                normalized = _normalize_record(candidate, career_url, self.layer)
                if normalized is not None:
                    jobs.append(normalized)
        result = _deduplicate(jobs)
        if not result:
            raise CollectionError("局部页面快照中未发现职位卡片")
        return result


class BrowserCollector:
    """Validate a controlled-browser collection without controlling the browser.

    The actual browser action belongs to the caller (for example, the Codex
    browser skill). Keeping this class declarative prevents cookies, tokens,
    credentials, or anti-bot workarounds from entering the project state.
    """

    layer = "assisted_browser"
    _REQUIRED_PHASES = ("页面可交互", "产品类筛选", "岗位列表", "分页遍历")

    def collect(
        self, source: BrowserLayerInput, career_url: str
    ) -> Tuple[Tuple[CollectedJob, ...], Tuple[CollectionAttempt, ...], bool, str]:
        if not source.steps:
            raise CollectionError("浏览器采集未返回可验证的页面步骤")

        attempts: List[CollectionAttempt] = []
        steps_by_phase: Dict[str, BrowserStep] = {}

        def fail(message: str) -> None:
            raise BrowserCollectionError(message, attempts)

        for step in source.steps:
            phase = step.phase.strip()
            if not phase:
                fail("浏览器采集存在未命名步骤")
            if step.outcome not in BROWSER_STEP_OUTCOMES:
                fail(f"浏览器步骤状态无效：{step.outcome}")
            if step.duration_ms < 0:
                fail("浏览器步骤耗时不能为负数")
            if phase in steps_by_phase:
                fail(f"浏览器步骤重复：{phase}")
            steps_by_phase[phase] = step
            outcome = "needs_user" if step.outcome == "blocked" else step.outcome
            attempts.append(
                CollectionAttempt(
                    layer=self.layer,
                    outcome=outcome,
                    duration_ms=step.duration_ms,
                    message=f"{phase}：{step.message}".rstrip("："),
                )
            )
            if step.outcome == "blocked":
                return (), tuple(attempts), False, step.message or f"{phase}需要人工操作"
            if step.outcome in {"failed", "timeout"}:
                fail(f"{phase}未完成：{step.message or '页面状态未满足'}")

        for phase in self._REQUIRED_PHASES[:2]:
            step = steps_by_phase.get(phase)
            if step is None:
                fail(f"浏览器采集缺少必要步骤：{phase}")
            if step.outcome != "success":
                fail(f"{phase}未成功完成")

        product_filter = steps_by_phase["产品类筛选"]
        if product_filter.filter_confirmed is not True:
            fail("产品类筛选未被页面状态确认，不能进行岗位排名")

        for phase in self._REQUIRED_PHASES[2:]:
            step = steps_by_phase.get(phase)
            if step is None:
                fail(f"浏览器采集缺少必要步骤：{phase}")
            if step.outcome != "success":
                fail(f"{phase}未成功完成")

        pagination_step = steps_by_phase["分页遍历"]
        pagination_complete = source.pagination_complete and pagination_step.pagination_complete is True
        if not pagination_complete:
            fail("分页遍历未到达明确终止状态")

        scoped_source = LayerInput(
            available=True,
            pages=source.pages,
            pagination_complete=pagination_complete,
            next_page_number=source.next_page_number,
            next_cursor=source.next_cursor,
            detail_url_template=source.detail_url_template,
        )
        jobs = ScopedDomCollector().collect(scoped_source, career_url)
        return jobs, tuple(attempts), pagination_complete, ""


class CollectionRuntime:
    """Run generic source layers in order without browser-side state changes."""

    def __init__(self, clock=monotonic) -> None:
        self._clock = clock
        self._collectors = (
            ("api", JsonApiCollector()),
            ("html", HtmlCollector()),
            ("scoped_dom", ScopedDomCollector()),
        )
        self._browser_collector = BrowserCollector()

    def collect(self, request: CollectionRequest) -> CollectionResult:
        if urlparse(request.career_url).scheme not in {"http", "https"}:
            raise CollectionError("career_url 必须是 HTTP(S) 链接")
        if request.total_budget_ms <= 0:
            raise CollectionError("采集总时间预算必须大于零")
        checkpoint = request.checkpoint or CollectionCheckpoint(career_url=request.career_url)
        if checkpoint.career_url != request.career_url:
            raise CollectionError("断点必须属于当前官网入口")

        attempts: List[CollectionAttempt] = []
        started_at = self._clock()

        def remaining_budget_ms() -> int:
            elapsed_ms = int((self._clock() - started_at) * 1000)
            return max(0, request.total_budget_ms - elapsed_ms)

        for layer, collector in self._collectors:
            source = getattr(request, layer)
            if not source.available:
                continue
            layer_budget_ms = int(request.layer_budget_ms.get(layer, request.total_budget_ms))
            if layer_budget_ms <= 0 or remaining_budget_ms() == 0:
                attempts.append(
                    CollectionAttempt(
                        layer=layer,
                        outcome="timeout",
                        duration_ms=0,
                        message="采集时间预算已耗尽",
                    )
                )
                return CollectionResult(
                    jobs=(),
                    collection_layer="none",
                    pagination_complete=False,
                    checkpoint=checkpoint,
                    attempts=tuple(attempts),
                    user_action=request.user_action,
                    budget_exhausted=True,
                )
            started = self._clock()
            try:
                collected = collector.collect(source, request.career_url)
            except (CollectionError, TimeoutError, ValueError) as exc:
                duration_ms = int((self._clock() - started) * 1000)
                attempts.append(
                    CollectionAttempt(
                        layer=layer,
                        outcome="timeout" if duration_ms > layer_budget_ms else "failed",
                        duration_ms=duration_ms,
                        message=str(exc),
                    )
                )
                continue

            duration_ms = int((self._clock() - started) * 1000)
            if duration_ms > layer_budget_ms:
                attempts.append(
                    CollectionAttempt(
                        layer=layer,
                        outcome="timeout",
                        duration_ms=duration_ms,
                        message="该采集层耗时超过预算，结果未被采用",
                    )
                )
                continue

            unseen = tuple(job for job in collected if job.id not in checkpoint.seen_job_ids)
            next_checkpoint = CollectionCheckpoint(
                career_url=request.career_url,
                page_number=source.next_page_number or checkpoint.page_number,
                cursor=source.next_cursor or checkpoint.cursor,
                seen_job_ids=tuple(dict.fromkeys((*checkpoint.seen_job_ids, *(job.id for job in collected)))),
            )
            attempts.append(
                CollectionAttempt(
                    layer=layer,
                    outcome="success",
                    duration_ms=duration_ms,
                )
            )
            return CollectionResult(
                jobs=unseen,
                collection_layer=layer,
                pagination_complete=source.pagination_complete,
                checkpoint=next_checkpoint,
                attempts=tuple(attempts),
            )

        browser_source = request.assisted_browser
        if browser_source.available:
            layer = "assisted_browser"
            layer_budget_ms = int(request.layer_budget_ms.get(layer, request.total_budget_ms))
            if layer_budget_ms <= 0 or remaining_budget_ms() == 0:
                attempts.append(
                    CollectionAttempt(layer=layer, outcome="timeout", duration_ms=0, message="采集时间预算已耗尽")
                )
                return CollectionResult(
                    jobs=(),
                    collection_layer="none",
                    pagination_complete=False,
                    checkpoint=checkpoint,
                    attempts=tuple(attempts),
                    budget_exhausted=True,
                )
            try:
                collected, browser_attempts, pagination_complete, user_action = self._browser_collector.collect(
                    browser_source, request.career_url
                )
            except BrowserCollectionError as exc:
                attempts.extend(exc.attempts)
                attempts.append(
                    CollectionAttempt(layer=layer, outcome="failed", duration_ms=0, message=str(exc))
                )
            except (CollectionError, TimeoutError, ValueError) as exc:
                attempts.append(
                    CollectionAttempt(layer=layer, outcome="failed", duration_ms=0, message=str(exc))
                )
            else:
                browser_duration_ms = sum(attempt.duration_ms for attempt in browser_attempts)
                attempts.extend(browser_attempts)
                if user_action:
                    return CollectionResult(
                        jobs=(),
                        collection_layer=layer,
                        pagination_complete=False,
                        checkpoint=checkpoint,
                        attempts=tuple(attempts),
                        user_action=user_action,
                        budget_exhausted=False,
                    )
                if browser_duration_ms > layer_budget_ms:
                    attempts.append(
                        CollectionAttempt(
                            layer=layer,
                            outcome="timeout",
                            duration_ms=browser_duration_ms,
                            message="浏览器采集耗时超过预算，结果未被采用",
                        )
                    )
                else:
                    unseen = tuple(job for job in collected if job.id not in checkpoint.seen_job_ids)
                    next_checkpoint = CollectionCheckpoint(
                        career_url=request.career_url,
                        page_number=browser_source.next_page_number or checkpoint.page_number,
                        cursor=browser_source.next_cursor or checkpoint.cursor,
                        seen_job_ids=tuple(
                            dict.fromkeys((*checkpoint.seen_job_ids, *(job.id for job in collected)))
                        ),
                    )
                    return CollectionResult(
                        jobs=unseen,
                        collection_layer=layer,
                        pagination_complete=pagination_complete,
                        checkpoint=next_checkpoint,
                        attempts=tuple(attempts),
                        details_complete=browser_source.details_complete,
                        product_category_confirmed=True,
                    )

        if request.user_action.strip():
            attempts.append(
                CollectionAttempt(
                    layer="assisted_browser",
                    outcome="needs_user",
                    duration_ms=0,
                    message=request.user_action.strip(),
                )
            )
            return CollectionResult(
                jobs=(),
                collection_layer="assisted_browser",
                pagination_complete=False,
                checkpoint=checkpoint,
                attempts=tuple(attempts),
                user_action=request.user_action.strip(),
                budget_exhausted=remaining_budget_ms() == 0,
            )

        return CollectionResult(
            jobs=(),
            collection_layer="none",
            pagination_complete=False,
            checkpoint=checkpoint,
            attempts=tuple(attempts),
            budget_exhausted=remaining_budget_ms() == 0,
        )
