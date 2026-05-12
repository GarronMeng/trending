#!/usr/bin/env python3
"""AI News Radar pipeline for GarronMeng/trending.

This script adds a lightweight, serverless, AI-news-specific pipeline on top of the
existing TrendRadar fork:

source strategy -> fetch -> normalize -> deduplicate -> relevance filter ->
source health -> JSON snapshot -> static HTML report.

It intentionally avoids model calls and private credentials by default so the core
flow can run on GitHub Actions and GitHub Pages/R2 without API keys.
"""

from __future__ import annotations

import argparse
import base64
import html
import hashlib
import json
import os
import re
import sys
import textwrap
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import requests
import yaml
from zoneinfo import ZoneInfo

UTC = timezone.utc
DEFAULT_CONFIG = Path("config/source_strategy.yaml")
DEFAULT_OUTPUT_DIR = Path("data")
DEFAULT_REPORT_DIR = Path("reports")
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class RadarSource:
    id: str
    name: str
    type: str
    url: str
    homepage: str | None = None
    enabled: bool = True
    group: str = "default"
    weight: int = 1
    include_keywords: list[str] | None = None
    note: str | None = None


@dataclass
class RadarItem:
    id: str
    source_id: str
    source_name: str
    source_type: str
    source_group: str
    source_weight: int
    title: str
    url: str
    published_at: str | None
    summary: str | None
    relevance_score: int
    relevance_reasons: list[str]
    is_ai_related: bool


@dataclass
class SourceHealth:
    source_id: str
    source_name: str
    source_type: str
    enabled: bool
    ok: bool
    fetched_count: int = 0
    kept_count: int = 0
    error: str | None = None
    latency_ms: int | None = None
    checked_at: str | None = None


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None

    # feedparser time tuple
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=UTC)

    try:
        dt = parsedate_to_datetime(text)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        pass

    # Conservative ISO-ish fallback without adding an extra dependency.
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except Exception:
            continue
    return None


def normalize_url(raw_url: str) -> str:
    raw_url = (raw_url or "").strip()
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url)
        if not parsed.scheme:
            return raw_url
        query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lk = key.lower()
            if lk.startswith("utm_") or lk in {
                "ref",
                "fbclid",
                "gclid",
                "igshid",
                "mc_cid",
                "mc_eid",
                "mkt_tok",
                "spm",
                "_hsenc",
                "_hsmi",
            }:
                continue
            query.append((key, value))
        parsed = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            query=urlencode(query, doseq=True),
            fragment="",
        )
        return urlunparse(parsed).rstrip("/")
    except Exception:
        return raw_url


def stable_id(*parts: str) -> str:
    key = "||".join((p or "").strip().lower() for p in parts)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(path: Path) -> dict[str, Any]:
    cfg = load_yaml(path)
    if "radar" not in cfg or "sources" not in cfg:
        raise ValueError(f"Invalid radar config: {path}")
    return cfg


def load_sources(cfg: dict[str, Any], include_disabled: bool = False) -> list[RadarSource]:
    out: list[RadarSource] = []
    for raw in cfg.get("sources", []):
        src = RadarSource(
            id=str(raw.get("id", "")).strip(),
            name=str(raw.get("name", "")).strip(),
            type=str(raw.get("type", "official_rss")).strip(),
            url=str(raw.get("url", "")).strip(),
            homepage=raw.get("homepage"),
            enabled=bool(raw.get("enabled", True)),
            group=str(raw.get("group", "default")).strip(),
            weight=int(raw.get("weight", 1)),
            include_keywords=list(raw.get("include_keywords") or []),
            note=raw.get("note"),
        )
        if not src.id or not src.name or not src.url:
            continue
        if src.enabled or include_disabled:
            out.append(src)
    return out


def create_session(timeout: int = 25) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": BROWSER_UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    session.request_timeout = timeout  # type: ignore[attr-defined]
    return session


def feed_entry_datetime(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        value = getattr(entry, attr, None) or entry.get(attr)
        if value:
            try:
                return datetime(*value[:6], tzinfo=UTC)
            except Exception:
                pass
    for attr in ("published", "updated", "created", "date"):
        value = getattr(entry, attr, None) or entry.get(attr)
        dt = parse_dt(value)
        if dt:
            return dt
    return None


def fetch_rss_source(session: requests.Session, src: RadarSource) -> list[dict[str, Any]]:
    timeout = getattr(session, "request_timeout", 25)
    response = session.get(src.url, timeout=timeout)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        raise RuntimeError(f"Feed parse failed: {getattr(parsed, 'bozo_exception', 'unknown error')}")

    items: list[dict[str, Any]] = []
    for entry in parsed.entries:
        title = strip_html(entry.get("title", ""))
        url = normalize_url(entry.get("link", ""))
        if not title or not url:
            continue
        summary = strip_html(entry.get("summary") or entry.get("description") or "")
        published = feed_entry_datetime(entry)
        items.append(
            {
                "title": title,
                "url": url,
                "summary": summary,
                "published_at": published,
            }
        )
    return items


def parse_opml_feeds(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    feeds: list[dict[str, str]] = []
    for outline in root.findall(".//outline"):
        xml_url = outline.attrib.get("xmlUrl") or outline.attrib.get("xmlurl")
        if not xml_url:
            continue
        title = outline.attrib.get("title") or outline.attrib.get("text") or xml_url
        html_url = outline.attrib.get("htmlUrl") or outline.attrib.get("htmlurl")
        feeds.append({"title": title, "xml_url": xml_url, "html_url": html_url or ""})
    return feeds


def materialize_private_opml_from_env(path: Path) -> bool:
    """Decode FOLLOW_OPML_B64 into an ignored local file when available."""
    encoded = os.getenv("FOLLOW_OPML_B64", "").strip()
    if not encoded:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(encoded))
        return True
    except Exception as exc:
        print(f"WARN: failed to decode FOLLOW_OPML_B64: {exc}", file=sys.stderr)
        return False


def fetch_opml_source(session: requests.Session, src: RadarSource) -> list[dict[str, Any]]:
    opml_path = Path(src.url)
    materialize_private_opml_from_env(opml_path)
    feeds = parse_opml_feeds(opml_path)
    items: list[dict[str, Any]] = []
    for feed in feeds:
        feed_src = RadarSource(
            id=f"{src.id}:{stable_id(feed['xml_url'])[:8]}",
            name=f"{src.name} · {feed['title']}",
            type="opml_rss",
            url=feed["xml_url"],
            homepage=feed.get("html_url") or None,
            enabled=True,
            group=src.group,
            weight=src.weight,
            include_keywords=src.include_keywords,
        )
        try:
            for item in fetch_rss_source(session, feed_src):
                item["opml_feed_title"] = feed["title"]
                item["opml_feed_url"] = feed["xml_url"]
                items.append(item)
        except Exception as exc:
            print(f"WARN: OPML feed failed {feed['xml_url']}: {exc}", file=sys.stderr)
    return items


def score_relevance(
    title: str,
    summary: str,
    src: RadarSource,
    strong_keywords: list[str],
    weak_keywords: list[str],
) -> tuple[int, list[str]]:
    text = f"{title}\n{summary}".lower()
    score = 0
    reasons: list[str] = []

    for kw in strong_keywords:
        k = kw.lower().strip()
        if k and k in text:
            score += 2
            reasons.append(f"strong:{kw}")
            if score >= 8:
                break

    for kw in weak_keywords:
        k = kw.lower().strip()
        if k and k in text:
            score += 1
            reasons.append(f"weak:{kw}")
            if score >= 10:
                break

    for kw in src.include_keywords or []:
        k = kw.lower().strip()
        if k and k in text:
            score += 2
            reasons.append(f"source:{kw}")

    # Official AI-specific feeds get a small prior, but still need recency/window checks.
    if src.type == "official_rss" and src.group == "official":
        score += 1
        reasons.append("source_prior:official_ai")

    if src.type == "public_feed":
        score -= 1
        reasons.append("source_penalty:aggregate_noise")

    return max(0, score), reasons[:12]


def fetch_source(session: requests.Session, src: RadarSource) -> list[dict[str, Any]]:
    if src.type in {"official_rss", "public_feed"}:
        return fetch_rss_source(session, src)
    if src.type == "opml_rss":
        return fetch_opml_source(session, src)
    raise RuntimeError(f"Unsupported source type for current MVP: {src.type}")


def build_items(
    cfg: dict[str, Any],
    sources: list[RadarSource],
    window_hours: int,
    min_score: int,
) -> tuple[list[RadarItem], list[SourceHealth]]:
    session = create_session()
    cutoff = now_utc() - timedelta(hours=window_hours)
    relevance_cfg = cfg.get("relevance", {})
    strong_keywords = [str(x) for x in relevance_cfg.get("strong_keywords", [])]
    weak_keywords = [str(x) for x in relevance_cfg.get("weak_keywords", [])]

    all_items: list[RadarItem] = []
    health: list[SourceHealth] = []

    for src in sources:
        started = time.monotonic()
        raw_items: list[dict[str, Any]] = []
        ok = False
        error: str | None = None
        try:
            raw_items = fetch_source(session, src)
            ok = True
        except Exception as exc:
            error = str(exc)[:500]

        latency_ms = int((time.monotonic() - started) * 1000)
        kept_count = 0

        for raw in raw_items:
            title = strip_html(raw.get("title"))
            url = normalize_url(raw.get("url"))
            if not title or not url:
                continue
            published_dt = raw.get("published_at")
            if isinstance(published_dt, str):
                published_dt = parse_dt(published_dt)
            if published_dt and published_dt < cutoff:
                continue

            summary = strip_html(raw.get("summary"))
            score, reasons = score_relevance(title, summary, src, strong_keywords, weak_keywords)
            is_ai_related = score >= min_score
            if not is_ai_related:
                continue
            kept_count += 1
            all_items.append(
                RadarItem(
                    id=stable_id(src.id, title, url),
                    source_id=src.id,
                    source_name=src.name,
                    source_type=src.type,
                    source_group=src.group,
                    source_weight=src.weight,
                    title=title,
                    url=url,
                    published_at=iso(published_dt),
                    summary=summary[:360] if summary else None,
                    relevance_score=score,
                    relevance_reasons=reasons,
                    is_ai_related=True,
                )
            )

        health.append(
            SourceHealth(
                source_id=src.id,
                source_name=src.name,
                source_type=src.type,
                enabled=src.enabled,
                ok=ok,
                fetched_count=len(raw_items),
                kept_count=kept_count,
                error=error,
                latency_ms=latency_ms,
                checked_at=iso(now_utc()),
            )
        )

    deduped = deduplicate_items(all_items)
    return deduped, health


def deduplicate_items(items: list[RadarItem]) -> list[RadarItem]:
    by_key: dict[str, RadarItem] = {}
    for item in items:
        # Prefer URL-level identity, fallback to normalized title.
        key = normalize_url(item.url) or re.sub(r"\W+", "", item.title.lower())[:120]
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
            continue
        # Keep stronger source / higher relevance version.
        existing_rank = (existing.source_weight, existing.relevance_score, bool(existing.published_at))
        item_rank = (item.source_weight, item.relevance_score, bool(item.published_at))
        if item_rank > existing_rank:
            by_key[key] = item

    def sort_key(item: RadarItem) -> tuple[int, str, int, str]:
        return (
            item.relevance_score + item.source_weight,
            item.published_at or "",
            item.source_weight,
            item.title,
        )

    return sorted(by_key.values(), key=sort_key, reverse=True)


def summarize_groups(items: list[RadarItem]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        g = groups.setdefault(
            item.source_group,
            {"group": item.source_group, "count": 0, "top_sources": {}, "top_keywords": {}},
        )
        g["count"] += 1
        g["top_sources"][item.source_name] = g["top_sources"].get(item.source_name, 0) + 1
        for reason in item.relevance_reasons:
            label = reason.split(":", 1)[-1]
            g["top_keywords"][label] = g["top_keywords"].get(label, 0) + 1

    for g in groups.values():
        g["top_sources"] = sorted(g["top_sources"].items(), key=lambda x: x[1], reverse=True)[:8]
        g["top_keywords"] = sorted(g["top_keywords"].items(), key=lambda x: x[1], reverse=True)[:12]
    return groups


def write_json_snapshot(
    output_dir: Path,
    cfg: dict[str, Any],
    items: list[RadarItem],
    health: list[SourceHealth],
    window_hours: int,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "garron-ai-news-radar-v1",
        "generated_at": iso(now_utc()),
        "window_hours": window_hours,
        "source_count": len(health),
        "healthy_source_count": sum(1 for h in health if h.ok),
        "item_count": len(items),
        "groups": summarize_groups(items),
        "items": [asdict(i) for i in items],
        "source_health": [asdict(h) for h in health],
        "control_notes": {
            "objective": "Reduce daily AI information overload into a deduplicated, high-signal 24h radar.",
            "controlled_variables": ["source list", "source weight", "window_hours", "min_relevance_score", "private OPML"],
            "feedback_metrics": ["item_count", "healthy_source_count", "dedupe ratio", "false positive rate by manual review"],
        },
    }
    path = output_dir / "ai-news-radar.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = output_dir / "latest-ai-news-radar.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def render_item_card(item: RadarItem) -> str:
    published = item.published_at or "unknown time"
    summary = f"<p class='summary'>{html.escape(item.summary)}</p>" if item.summary else ""
    reasons = "".join(
        f"<span>{html.escape(reason)}</span>" for reason in item.relevance_reasons[:5]
    )
    return f"""
    <article class="card">
      <div class="meta">
        <span>{html.escape(item.source_name)}</span>
        <span>{html.escape(item.source_type)}</span>
        <span>{html.escape(published)}</span>
        <strong>Score {item.relevance_score}</strong>
      </div>
      <h3><a href="{html.escape(item.url)}" target="_blank" rel="noreferrer">{html.escape(item.title)}</a></h3>
      {summary}
      <div class="tags">{reasons}</div>
    </article>
    """


def render_health_table(health: list[SourceHealth]) -> str:
    rows = []
    for h in health:
        status = "OK" if h.ok else "ERR"
        rows.append(
            "<tr>"
            f"<td>{html.escape(h.source_name)}</td>"
            f"<td>{html.escape(h.source_type)}</td>"
            f"<td class='{status.lower()}'>{status}</td>"
            f"<td>{h.fetched_count}</td>"
            f"<td>{h.kept_count}</td>"
            f"<td>{h.latency_ms or 0}ms</td>"
            f"<td>{html.escape(h.error or '')}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def write_html_report(
    report_dir: Path,
    radar_name: str,
    items: list[RadarItem],
    health: list[SourceHealth],
    window_hours: int,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    generated_at = iso(now_utc())
    official_count = sum(1 for i in items if i.source_group == "official")
    aggregate_count = sum(1 for i in items if i.source_group == "aggregate")
    cards = "\n".join(render_item_card(i) for i in items[:80])
    health_rows = render_health_table(health)

    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(radar_name)}</title>
  <style>
    :root {{ color-scheme: light dark; --bg: #f6f7fb; --panel: #ffffff; --text: #172033; --muted: #667085; --line: #e5e7eb; --accent: #2454ff; }}
    @media (prefers-color-scheme: dark) {{ :root {{ --bg: #0b1020; --panel: #131a2a; --text: #eef2ff; --muted: #98a2b3; --line: #263044; --accent: #8ea2ff; }} }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 42px 20px 26px; background: radial-gradient(circle at top left, rgba(36,84,255,.18), transparent 36%), var(--panel); border-bottom: 1px solid var(--line); }}
    .wrap {{ max-width: 1120px; margin: 0 auto; }}
    h1 {{ margin: 0 0 10px; font-size: clamp(30px, 6vw, 56px); letter-spacing: -0.04em; }}
    .subtitle {{ color: var(--muted); max-width: 760px; line-height: 1.7; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 24px; }}
    .stat {{ background: var(--bg); border: 1px solid var(--line); border-radius: 18px; padding: 16px; }}
    .stat b {{ display: block; font-size: 28px; margin-bottom: 4px; }}
    main {{ padding: 24px 20px 56px; }}
    .section-title {{ display: flex; justify-content: space-between; align-items: end; gap: 12px; margin: 28px 0 14px; }}
    .section-title h2 {{ margin: 0; font-size: 22px; }}
    .section-title p {{ margin: 0; color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 20px; padding: 18px; box-shadow: 0 10px 30px rgba(15,23,42,.04); }}
    .card h3 {{ margin: 10px 0 8px; font-size: 18px; line-height: 1.45; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: 12px; }}
    .meta span, .meta strong, .tags span {{ border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; }}
    .summary {{ color: var(--muted); line-height: 1.65; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; color: var(--muted); font-size: 12px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 18px; overflow: hidden; border: 1px solid var(--line); }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; font-size: 13px; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; }}
    .ok {{ color: #059669; font-weight: 700; }} .err {{ color: #dc2626; font-weight: 700; }}
    footer {{ color: var(--muted); font-size: 13px; padding: 26px 20px 42px; }}
    @media (max-width: 760px) {{ .stats, .grid {{ grid-template-columns: 1fr; }} table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>{html.escape(radar_name)}</h1>
      <p class="subtitle">基于 AI News Radar 逻辑重构：先判断信源，再抓取、归一化、去重、AI 强相关过滤、健康监测，最后输出静态 JSON 和 HTML。当前页面不依赖任何 LLM API Key。</p>
      <div class="stats">
        <div class="stat"><b>{len(items)}</b><span>24h 高信号条目</span></div>
        <div class="stat"><b>{official_count}</b><span>官方源条目</span></div>
        <div class="stat"><b>{aggregate_count}</b><span>聚合源条目</span></div>
        <div class="stat"><b>{sum(1 for h in health if h.ok)}/{len(health)}</b><span>健康信源</span></div>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section>
      <div class="section-title"><h2>AI 强相关</h2><p>窗口：最近 {window_hours} 小时；生成：{generated_at}</p></div>
      <div class="grid">{cards or '<p>本轮没有抓到达到阈值的条目。</p>'}</div>
    </section>
    <section>
      <div class="section-title"><h2>信源健康状态</h2><p>用来决定下一轮要增删哪些源。</p></div>
      <table>
        <thead><tr><th>Source</th><th>Type</th><th>Status</th><th>Fetched</th><th>Kept</th><th>Latency</th><th>Error</th></tr></thead>
        <tbody>{health_rows}</tbody>
      </table>
    </section>
  </main>
  <footer class="wrap">Generated by scripts/ai_news_radar.py · data/ai-news-radar.json</footer>
</body>
</html>
"""
    path = report_dir / "ai-news-radar.html"
    path.write_text(body, encoding="utf-8")
    latest = report_dir / "latest.html"
    latest.write_text(body, encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AI News Radar pipeline")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--window-hours", type=int, default=None)
    parser.add_argument("--min-relevance-score", type=int, default=None)
    parser.add_argument("--include-disabled", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    radar_cfg = cfg.get("radar", {})
    window_hours = int(args.window_hours or radar_cfg.get("window_hours", 24))
    min_score = int(args.min_relevance_score or radar_cfg.get("min_relevance_score", 2))
    output_dir = args.output_dir or Path(radar_cfg.get("output_dir", "data"))
    report_dir = args.report_dir or Path(radar_cfg.get("report_dir", "reports"))
    radar_name = str(radar_cfg.get("name", "Garron AI News Radar"))

    sources = load_sources(cfg, include_disabled=args.include_disabled)
    if not sources:
        raise RuntimeError("No enabled sources found in source_strategy.yaml")

    items, health = build_items(cfg, sources, window_hours=window_hours, min_score=min_score)
    json_path = write_json_snapshot(output_dir, cfg, items, health, window_hours=window_hours)
    html_path = write_html_report(report_dir, radar_name, items, health, window_hours=window_hours)

    print(f"AI News Radar generated: {json_path} and {html_path}")
    print(f"items={len(items)} healthy_sources={sum(1 for h in health if h.ok)}/{len(health)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
