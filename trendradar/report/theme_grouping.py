# coding=utf-8
"""Lightweight theme grouping for the browser HTML report.

This is a presentation-layer helper: it never mutates stored news data. It only
builds a compact "same story, multiple sources" section above the original list.
"""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional


_NOISE_WORDS = (
    "突发", "刚刚", "最新", "快讯", "重磅", "独家", "一图看懂", "图解",
    "冲上热搜", "刷屏", "回应来了", "官方回应", "持续更新",
)


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


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


def _rank(item: Dict) -> Optional[int]:
    values = []
    for rank in item.get("ranks") or []:
        try:
            rank_int = int(rank)
            if rank_int > 0:
                values.append(rank_int)
        except Exception:
            pass
    return min(values) if values else None


def _source(item: Dict) -> str:
    return str(item.get("source_name") or item.get("feed_name") or item.get("source") or "未知来源")


def _url(item: Dict) -> str:
    return str(item.get("url") or item.get("mobile_url") or item.get("mobileUrl") or "")


def _flatten(report_data: Dict) -> List[Dict]:
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
            key = (_normalize(title), _source(item), _url(item))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def build_theme_groups(report_data: Dict, threshold: float = 0.64, min_size: int = 2, max_groups: int = 24) -> List[Dict]:
    groups: List[Dict] = []
    for item in _flatten(report_data):
        title = item.get("title", "")
        best_group = None
        best_score = 0.0
        for group in groups:
            candidates = [group["representative"]] + group["items"][:3]
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
        if len(items) < min_size:
            continue
        sources = []
        for item in items:
            source = _source(item)
            if source not in sources:
                sources.append(source)
        ranks = [_rank(i) for i in items]
        ranks = [r for r in ranks if r is not None]
        highest_rank = min(ranks) if ranks else None
        score = len(sources) * 10 + len(items) * 3 + (50 - min(highest_rank or 50, 50))
        result.append({
            "theme": group["representative"].get("title", ""),
            "items": _pick_display_items(items),
            "count": len(items),
            "source_count": len(sources),
            "sources": sources,
            "highest_rank": highest_rank,
            "score": score,
        })
    result.sort(key=lambda g: g["score"], reverse=True)
    return result[:max_groups]


def _choose_representative(items: List[Dict]) -> Dict:
    return sorted(items, key=lambda i: (_rank(i) or 999, len(str(i.get("title", "")))))[0]


def _pick_display_items(items: List[Dict], limit: int = 5) -> List[Dict]:
    picked = []
    used_sources = set()
    for item in sorted(items, key=lambda i: (_rank(i) or 999, _source(i))):
        source = _source(item)
        if source in used_sources and len(picked) < len(items) - 1:
            continue
        picked.append(item)
        used_sources.add(source)
        if len(picked) >= limit:
            return picked
    for item in items:
        if item not in picked:
            picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def render_theme_groups_section(report_data: Dict) -> str:
    groups = build_theme_groups(report_data)
    if not groups:
        return ""

    cards = []
    for index, group in enumerate(groups, 1):
        rank = group.get("highest_rank")
        rank_text = f"最高排名 #{rank}" if rank else "暂无排名"
        sources = "、".join(group.get("sources", [])[:6])
        rows = []
        for item in group.get("items", []):
            title = _esc(item.get("title"))
            url = _url(item)
            link = f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{title}</a>' if url else title
            meta = f"{_esc(_source(item))}"
            item_rank = _rank(item)
            if item_rank:
                meta += f" · #{item_rank}"
            if item.get("time_display"):
                meta += f" · {_esc(item.get('time_display'))}"
            rows.append(f'<div class="theme-row"><div class="theme-row-meta">{meta}</div><div class="theme-row-title">{link}</div></div>')
        cards.append(f"""
        <div class="theme-card">
          <div class="theme-card-top">
            <div class="theme-index">{index}</div>
            <div>
              <div class="theme-title">{_esc(group.get('theme'))}</div>
              <div class="theme-meta">{group.get('count')} 条相关报道 · {group.get('source_count')} 个来源 · {rank_text}</div>
            </div>
          </div>
          <div class="theme-sources">覆盖来源：{_esc(sources)}</div>
          <div class="theme-list">{''.join(rows)}</div>
        </div>
        """)

    return f"""
    <style>
      .theme-section {{ margin-bottom: 32px; padding-bottom: 24px; border-bottom: 2px solid #e5e7eb; }}
      .theme-section-title {{ font-size: 18px; font-weight: 700; color: #111827; margin-bottom: 14px; }}
      .theme-card {{ background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:16px; margin-bottom:14px; box-shadow:0 1px 3px rgba(0,0,0,.04); }}
      .theme-card-top {{ display:flex; gap:12px; align-items:flex-start; }}
      .theme-index {{ width:26px; height:26px; border-radius:50%; background:#eef2ff; color:#4f46e5; font-size:13px; font-weight:700; display:flex; align-items:center; justify-content:center; flex-shrink:0; }}
      .theme-title {{ font-size:15px; font-weight:650; color:#111827; line-height:1.45; }}
      .theme-meta, .theme-sources, .theme-row-meta {{ color:#6b7280; font-size:12px; line-height:1.5; }}
      .theme-sources {{ margin-top:8px; }}
      .theme-list {{ margin-top:12px; border-top:1px solid #f3f4f6; }}
      .theme-row {{ padding:9px 0; border-bottom:1px solid #f7f7f8; }}
      .theme-row:last-child {{ border-bottom:none; padding-bottom:0; }}
      .theme-row-title {{ font-size:13px; line-height:1.45; color:#1f2937; }}
      .theme-row-title a {{ color:#2563eb; text-decoration:none; }}
      body.dark-mode .theme-section {{ border-bottom-color:#2d2d2d; }}
      body.dark-mode .theme-card {{ background:#1f1f1f; border-color:#333; }}
      body.dark-mode .theme-title, body.dark-mode .theme-row-title {{ color:#f3f4f6; }}
      body.dark-mode .theme-list, body.dark-mode .theme-row {{ border-color:#333; }}
    </style>
    <section class="theme-section" id="theme-groups">
      <div class="theme-section-title">主题聚合 · 多源共振</div>
      {''.join(cards)}
    </section>
    """


def inject_theme_groups(html_content: str, report_data: Dict) -> str:
    section = render_theme_groups_section(report_data)
    if not section or "id=\"theme-groups\"" in html_content:
        return html_content
    marker = '<div class="content">'
    if marker in html_content:
        return html_content.replace(marker, marker + section, 1)
    return html_content
