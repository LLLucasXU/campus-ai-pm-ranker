"""Platform-aware plans for public campus-career-site collection.

Adapters describe visible-page collection steps. They never contain credentials,
cookie state, or hidden API recipes. This keeps a company-neutral adapter safe
to reuse across official sites hosted by the same recruitment platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from html import unescape
import json
import re
from typing import Optional
from urllib.parse import urlparse


class SiteKind(str, Enum):
    FEISHU_HOSTED = "feishu_hosted"
    GENERIC = "generic"


@dataclass(frozen=True)
class SiteInspection:
    kind: SiteKind
    host: str
    campus_path: str = ""
    site_name: str = ""


class SiteAdapter:
    """A reusable visible-browser plan for one recruitment-site family."""

    kind: SiteKind = SiteKind.GENERIC

    def __init__(self, inspection: SiteInspection) -> None:
        self.inspection = inspection

    def browser_plan(self) -> tuple[str, ...]:
        return ("页面可交互", "产品类筛选", "岗位列表", "分页遍历", "岗位详情")


class FeishuHostedAdapter(SiteAdapter):
    kind = SiteKind.FEISHU_HOSTED

    def browser_plan(self) -> tuple[str, ...]:
        return (
            "页面可交互",
            "确认校招入口",
            "产品类筛选",
            "岗位列表",
            "分页遍历",
            "岗位详情",
        )


class GenericAdapter(SiteAdapter):
    kind = SiteKind.GENERIC


def _website_info_payload(page_html: str) -> Optional[dict]:
    """Read only the public website configuration embedded in Feishu pages."""

    match = re.search(
        r'<script[^>]+id=["\']js-websiteInfo["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    try:
        value = json.loads(unescape(match.group(1)).strip())
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def select_site_adapter(career_url: str, page_html: str = "") -> SiteAdapter:
    """Select a platform adapter using the public URL and public page shell."""

    host = (urlparse(career_url).hostname or "").lower()
    website_info = _website_info_payload(page_html)
    is_feishu_host = host.endswith(".jobs.feishu.cn")
    if is_feishu_host:
        config = website_info.get("website_info", {}) if website_info else {}
        path = config.get("path", "") if isinstance(config, dict) else ""
        name = config.get("name", {}) if isinstance(config, dict) else {}
        site_name = name.get("zh_cn", "") if isinstance(name, dict) else ""
        return FeishuHostedAdapter(
            SiteInspection(
                kind=SiteKind.FEISHU_HOSTED,
                host=host,
                campus_path=str(path),
                site_name=str(site_name),
            )
        )
    return GenericAdapter(SiteInspection(kind=SiteKind.GENERIC, host=host))
