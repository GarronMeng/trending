# coding=utf-8
"""Unified hotlist + RSS digest for the browser report.

This module makes the browser report read as one integrated news product instead
of two separate sections. It mixes hotlist signals with RSS summaries in a single
view and hides duplicated legacy hotlist/RSS/theme sections from the main reading
flow. Raw data remains in the generated HTML source, but the primary UI is the
unified digest.
"""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional


_SENSATIONAL_PATTERNS = re.compile(
    r"(震惊|炸裂|刷屏|全网|泪目|反转|曝光|爆料|万万没想到|背后真相|突然|大消息|重磅|冲上热搜|网友炸锅|彻底火了|罕见|惊呆|太突然)",
    re.I,
)

_NOISE_WORDS = (
    "突发", "刚刚", "最新", "快讯", "重磅", "独家", "一图看懂", "图解",
    "冲上热搜", "刷屏", "回应来了", "官方回应", "持续更新",
)


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _strip_html(value: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", str(value or ""), flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clip(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _normalize(title: str) -> str:
    text = str(title or "").strip().lower()
    for word in _NOISE_WORDS:
        text = text.replace(word.lower(), "")
    text = re.sub(r"[#【\[][^#【\]】]{0,24}[#】\]]", "", text)
    text = re.sub(r"（[^）]{0,24}）|\([^)]{0,24}\)", "", text)
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[，。、“”‘’！!？?：:；;,.\-—_｜|/\\]+", "", text)
    return text[:120]


def _ngrams(text: str, n: int = 2) -> set:
    if not text:
        return set()
    if len(text) <= n:
        return {text}
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ga, gb = _ngrams(na), _ngrams(nb)
    jac = len(ga & gb) / max(1, len(ga | gb))
    return max(seq, jac)


def _source(item: Dict) -> str:
    return str(item.get("source_name") or item.get("feed_name") or item.get("source") or item.get("feed_id") or "未知来源")


def _url(item: Dict) -> str:
    return str(item.get("url") or item.get("mobile_url") or item.get("mobileUrl") or "")


def _rank(item: Dict) -> Optional[int]:
    values = []
    for rank in item.get("ranks") or []:
        try:
            value = int(rank)
            if value > 0:
                values.append(value)
        except Exception:
            pass
    return min(values) if values else None


def _summary(item: Dict) -> str:
    for key in ("summary", "description", "content", "abstract", "snippet"):
        value = item.get(key)
        if value:
            return _clip(_strip_html(str(value)), 190)
    return ""


def _flatten_hotlist(report_data: Dict) -> List[Dict]:
    items: List[Dict] = []
    seen = set()
    for stat in report_data.get("stats", []) or []:
        keyword = stat.get("word", "")
        for raw in stat.get("titles", []) or []:
            title = raw.get("title", "")
            if not title:
                continue
            item = dict(raw)
            item["keyword"] = keyword
            item["kind"] = "hotlist"
            key = (_normalize(title), _source(item), _url(item))
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items


def _flatten_rss(rss_items: Optional[List[Dict]]) -> List[Dict]:
    items: List[Dict] = []
    seen = set()
    for group in rss_items or []:
        if not isinstance(group, dict):
            continue
        title_rows = group.get("titles")
        if isinstance(title_rows, list):
            group_name = group.get("word") or group.get("feed_name") or group.get("source_name") or "RSS"
            for raw in title_rows:
                title = raw.get("title", "")
                if not title:
                    continue
                item = dict(raw)
                item.setdefault("source_name", raw.get("source_name") or raw.get("feed_name") or group_name)
                item["keyword"] = group_name
                item["kind"] = "rss"
                key = (_normalize(title), _source(item), _url(item))
                if key not in seen:
                    seen.add(key)
                    items.append(item)
        elif group.get("title"):
            item = dict(group)
            item.setdefault("source_name", group.get("source_name") or group.get("feed_name") or "RSS")
            item["kind"] = "rss"
            key = (_normalize(item.get("title", "")), _source(item), _url(item))
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items


def _choose_representative(items: List[Dict]) -> Dict:
    def score(item: Dict):
        # Prefer RSS with factual summary, then hotlist rank, then concise titles.
        return (0 if _summary(item) else 1, 0 if item.get("kind") == "rss" else 1, _rank(item) or 999, len(str(item.get("title", ""))))
    return sorted(items, key=score)[0]


def _pick_items(items: List[Dict], limit: int = 6) -> List[Dict]:
    picked: List[Dict] = []
    used_sources = set()
    ordered = sorted(items, key=lambda i: (0 if _summary(i) else 1, _rank(i) or 999, _source(i)))
    for item in ordered:
        source = _source(item)
        if source in used_sources and len(used_sources) < len({_source(x) for x in items}):
            continue
        picked.append(item)
        used_sources.add(source)
        if len(picked) >= limit:
            return picked
    for item in ordered:
        if item not in picked:
            picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def build_unified_groups(report_data: Dict, rss_items: Optional[List[Dict]], threshold: float = 0.58, max_groups: int = 24) -> List[Dict]:
    all_items = _flatten_hotlist(report_data) + _flatten_rss(rss_items)
    if not all_items:
        return []

    groups: List[Dict] = []
    for item in all_items:
        title = item.get("title", "")
        best_group = None
        best_score = 0.0
        for group in groups:
            candidates = [group["representative"]] + group["items"][:4]
            score = max(_similarity(title, c.get("title", "")) for c in candidates)
            if score > best_score:
                best_score = score
                best_group = group
        if best_group and best_score >= threshold:
            best_group["items"].append(item)
            best_group["representative"] = _choose_representative(best_group["items"])
        else:
            groups.append({"representative": item, "items": [item]})

    result = []
    for group in groups:
        items = group["items"]
        has_hotlist = any(i.get("kind") == "hotlist" for i in items)
        has_rss = any(i.get("kind") == "rss" for i in items)
        sources = []
        for item in items:
            source = _source(item)
            if source not in sources:
                sources.append(source)
        ranks = [_rank(i) for i in items]
        ranks = [r for r in ranks if r is not None]
        highest_rank = min(ranks) if ranks else None
        evidence_count = sum(1 for i in items if _summary(i))
        title_only_count = len(items) - evidence_count
        title_risk_count = sum(1 for i in items if _SENSATIONAL_PATTERNS.search(str(i.get("title", ""))) and not _summary(i))

        # Keep singleton RSS entries with summaries because they have substance; drop single title-only items.
        if len(items) < 2 and not (has_rss and evidence_count > 0):
            continue

        score = len(sources) * 9 + len(items) * 3 + evidence_count * 9 + (35 - min(highest_rank or 35, 35))
        if has_hotlist and has_rss:
            score += 20
        result.append({
            "theme": _choose_representative(items).get("title", ""),
            "items": _pick_items(items),
            "count": len(items),
            "source_count": len(sources),
            "sources": sources,
            "highest_rank": highest_rank,
            "has_hotlist": has_hotlist,
            "has_rss": has_rss,
            "evidence_count": evidence_count,
            "title_only_count": title_only_count,
            "title_risk_count": title_risk_count,
            "score": score,
        })

    result.sort(key=lambda g: g.get("score", 0), reverse=True)
    return result[:max_groups]


def render_unified_digest(report_data: Dict, rss_items: Optional[List[Dict]]) -> str:
    groups = build_unified_groups(report_data, rss_items)
    if not groups:
        return ""

    cards = []
    for index, group in enumerate(groups, 1):
        badges = []
        if group.get("has_hotlist"):
            badges.append('<span class="unified-badge hotlist">热榜信号</span>')
        if group.get("has_rss"):
            badges.append('<span class="unified-badge rss">RSS 摘要支撑</span>')
        if group.get("title_only_count"):
            badges.append(f'<span class="unified-badge neutral">{group.get("title_only_count")} 条仅标题</span>')
        if group.get("title_risk_count"):
            badges.append('<span class="unified-badge risk">标题党风险</span>')
        rank = group.get("highest_rank")
        rank_text = f"最高排名 #{rank}" if rank else "无热榜排名"
        sources = "、".join(group.get("sources", [])[:7])

        rows = []
        for item in group.get("items", []):
            title = _esc(item.get("title"))
            url = _url(item)
            title_html = f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{title}</a>' if url else title
            kind = "RSS" if item.get("kind") == "rss" else "热榜"
            meta = f"{_esc(_source(item))} · {kind}"
            item_rank = _rank(item)
            if item_rank:
                meta += f" · #{item_rank}"
            if item.get("time_display"):
                meta += f" · {_esc(item.get('time_display'))}"
            summary = _summary(item)
            risk = _SENSATIONAL_PATTERNS.search(str(item.get("title", ""))) and not summary
            risk_html = '<span class="unified-mini-risk">标题待核实</span>' if risk else ""
            summary_html = f'<div class="unified-summary">{_esc(summary)}</div>' if summary else ""
            rows.append(f"""
            <div class="unified-row">
              <div class="unified-row-meta">{meta} {risk_html}</div>
              <div class="unified-row-title">{title_html}</div>
              {summary_html}
            </div>
            """)

        cards.append(f"""
        <div class="unified-card">
          <div class="unified-card-top">
            <div class="unified-index">{index}</div>
            <div class="unified-main">
              <div class="unified-title">{_esc(group.get('theme'))}</div>
              <div class="unified-meta">{group.get('count')} 条信号 · {group.get('source_count')} 个来源 · {rank_text}</div>
              <div class="unified-badges">{''.join(badges)}</div>
            </div>
          </div>
          <div class="unified-sources">覆盖来源：{_esc(sources)}</div>
          <div class="unified-list">{''.join(rows)}</div>
        </div>
        """)

    return f"""
    <style>
      .unified-section {{ margin-bottom: 32px; padding: 20px; border: 1px solid #dbeafe; border-radius: 14px; background: linear-gradient(180deg,#eff6ff 0%,#ffffff 100%); }}
      .unified-section-title {{ font-size: 19px; font-weight: 800; color:#1e3a8a; margin-bottom: 6px; }}
      .unified-section-subtitle {{ color:#64748b; font-size:13px; line-height:1.6; margin-bottom:16px; }}
      .unified-card {{ background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:16px; margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,.04); }}
      .unified-card:last-child {{ margin-bottom:0; }}
      .unified-card-top {{ display:flex; gap:12px; align-items:flex-start; }}
      .unified-index {{ width:28px; height:28px; border-radius:50%; background:#dbeafe; color:#1d4ed8; font-size:13px; font-weight:800; display:flex; align-items:center; justify-content:center; flex-shrink:0; }}
      .unified-main {{ flex:1; min-width:0; }}
      .unified-title {{ font-size:15px; font-weight:700; color:#111827; line-height:1.45; }}
      .unified-meta, .unified-sources, .unified-row-meta {{ color:#64748b; font-size:12px; line-height:1.5; }}
      .unified-badges {{ margin-top:8px; display:flex; gap:6px; flex-wrap:wrap; }}
      .unified-badge {{ font-size:11px; font-weight:700; border-radius:999px; padding:2px 7px; }}
      .unified-badge.hotlist {{ background:#fef3c7; color:#92400e; }}
      .unified-badge.rss {{ background:#dcfce7; color:#166534; }}
      .unified-badge.neutral {{ background:#e5e7eb; color:#4b5563; }}
      .unified-badge.risk {{ background:#fee2e2; color:#991b1b; }}
      .unified-sources {{ margin-top:9px; }}
      .unified-list {{ margin-top:12px; border-top:1px solid #f1f5f9; }}
      .unified-row {{ padding:10px 0; border-bottom:1px solid #f8fafc; }}
      .unified-row:last-child {{ border-bottom:none; padding-bottom:0; }}
      .unified-row-title {{ font-size:13px; line-height:1.45; font-weight:600; color:#1f2937; }}
      .unified-row-title a {{ color:#2563eb; text-decoration:none; }}
      .unified-summary {{ margin-top:5px; color:#475569; font-size:12px; line-height:1.55; }}
      .unified-mini-risk {{ color:#991b1b; background:#fee2e2; border-radius:4px; padding:1px 5px; margin-left:6px; }}

      /* Make unified digest the primary reading flow. Hide duplicated legacy sections below. */
      .unified-section ~ .hotlist-section,
      .unified-section ~ .rss-section,
      .unified-section ~ .theme-section {{ display:none !important; }}

      body.dark-mode .unified-section {{ background:#111827; border-color:#1e3a8a; }}
      body.dark-mode .unified-section-title {{ color:#bfdbfe; }}
      body.dark-mode .unified-card {{ background:#1f1f1f; border-color:#333; }}
      body.dark-mode .unified-title, body.dark-mode .unified-row-title {{ color:#f3f4f6; }}
      body.dark-mode .unified-summary {{ color:#cbd5e1; }}
      body.dark-mode .unified-list, body.dark-mode .unified-row {{ border-color:#333; }}
    </style>
    <section class="unified-section" id="unified-digest">
      <div class="unified-section-title">统一新闻视图 · 热榜 + RSS</div>
      <div class="unified-section-subtitle">这里是主阅读入口：热榜负责发现扩散信号，RSS 摘要负责补充事实背景。后面的原始热榜/RSS分区已从主阅读流隐藏，避免重复和割裂。</div>
      {''.join(cards)}
    </section>
    """


def inject_unified_digest(html_content: str, report_data: Dict, rss_items: Optional[List[Dict]]) -> str:
    if 'id="unified-digest"' in html_content:
        return html_content
    section = render_unified_digest(report_data, rss_items)
    if not section:
        return html_content
    marker = '<div class="content">'
    if marker in html_content:
        return html_content.replace(marker, marker + section, 1)
    return html_content
