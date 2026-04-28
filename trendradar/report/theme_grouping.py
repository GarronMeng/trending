# coding=utf-8
"""Theme-level grouping for HTML reports.

This module intentionally works at the presentation layer only. It keeps the
original report data unchanged and builds a compact "same story, multiple
sources" view for the browser HTML report.
"""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple


_NOISE_PATTERNS = [
    r"^\s*(突发|刚刚|最新|快讯|重磅|独家|一图看懂|图解|直播)[:：｜|\s]*",
    r"(冲上热搜|刷屏|回应来了|官方回应|最新回应|持续更新|详情公布)$",
    r"[#【\[][^#【\]】]{0,24}[#】\]]",
    r"（[^）]{0,24}）",
    r"\([^)]{0,24}\)",
]

_STOP_TOKENS = {
    "新闻", "消息", "最新", "快讯", "回应", "官方", "表示", "称", "网友", "热议",
    "视频", "现场", "发布", "公布", "来看", "一图", "如何", "为何", "什么",
}


def _escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _normalize_title(title: str) -> str:
    text = str(title or "").strip().lower()
    for pattern in _NOISE_PATTERNS:
        text = re.sub(pattern, "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[，。、“”‘’！!？?：:；;,.\-—_｜|/\\]+", "", text)
    return text[:120]


def _char_ngrams(text: str, n: int = 2) -> set:
    if len(text) <= n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _word_tokens(title: str) -> set:
    tokens = set()
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+.-]{1,}|\d+(?:\.\d+)?%?|[\u4e00-\u9fff]{2,}", title or ""):
        token = token.lower().strip()
        if not token or token in _STOP_TOKENS:
            continue
        # Long Chinese spans are too coarse. Keep the span plus short character shingles.
        if re.fullmatch(r"[\u4e00-\u9fff]{5,}", token):
            tokens.update(_char_ngrams(token, 2))
        else:
            tokens.add(token)
    return tokens


def _title_similarity(a: str, b: str) -> float:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0

    sequence_score = SequenceMatcher(None, na, nb).ratio()
    grams_a, grams_b = _char_ngrams(na, 2), _char_ngrams(nb, 2)
    gram_score = len(grams_a & grams_b) / max(1, len(grams_a | grams_b))

    tokens_a, tokens_b = _word_tokens(a), _word_tokens(b)
    token_score = 0.0
    if tokens_a and tokens_b:
        token_score = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))

    return max(sequence_score, gram_score * 0.9 + token_score * 0.1, token_score)


def _top_rank(item: Dict) -> Optional[int]:
    ranks = item.get("ranks") or []
    nums = []
    for rank in ranks:
        try:
            value = int(rank)
            if value > 0:
                nums.append(value)
        except Exception:
            continue
    return min(nums) if nums else None


def _source_name(item: Dict) -> str:
    return str(item.get("source_name") or item.get("feed_name") or item.get("source") or "未知来源")


def _item_url(item: Dict) -> str:
    return str(item.get("url") or item.get("mobile_url") or item.get("mobileUrl") or "")


def _flatten_report_items(report_data: Dict, rss_items: Optional[List[Dict]] = None) -> List[Dict]:
    items: List[Dict] = []
    seen = set()

    for stat in report_data.get("stats", []) or []:
        word = stat.get("word", "")
        for title in stat.get("titles", []) or []:
            item = dict(title)
            item["keyword"] = word
            item["kind"] = "hotlist"
            key = (_normalize_title(item.get("title", "")), _source_name(item), _item_url(item))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)

    # RSS items have a less uniform schema, so only add the fields needed for grouping/rendering.
    for raw in rss_items or []:
        title = raw.get("title", "")
        if not title:
            continue
        item = {
            "title": title,
            "source_name": raw.get("source_name") or raw.get("feed_name") or raw.get("feed_id") or "RSS",
            "time_display": raw.get("time_display") or raw.get("published_at") or "",
            "count": raw.get("count", 1),
            "ranks": raw.get("ranks", []),
            "url": raw.get("url", ""),
            "keyword": raw.get("keyword") or raw.get("word") or "RSS",
            "kind": "rss",
        }
        key = (_normalize_title(item.get("title", "")), _source_name(item), _item_url(item))
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    return items


def _choose_representative(items: List[Dict]) -> Dict:
    def score(item: Dict) -> Tuple[int, int, int]:
        rank = _top_rank(item)
        rank_score = 999 if rank is None else rank
        title_len = len(str(item.get("title", "")))
        kind_score = 0 if item.get("kind") == "hotlist" else 1
        return (rank_score, kind_score, title_len)

    return sorted(items, key=score)[0]


def build_theme_groups(
    report_data: Dict,
    rss_items: Optional[List[Dict]] = None,
    *,
    similarity_threshold: float = 0.64,
    min_group_size: int = 2,
    max_groups: int = 30,
    max_items_per_group: int = 6,
) -> List[Dict]:
    """Build theme groups from report data without mutating the source data."""
    flat_items = _flatten_report_items(report_data, rss_items)
    if not flat_items:
        return []

    groups: List[Dict[str, Any]] = []

    for item in flat_items:
        title = item.get("title", "")
        best_group = None
        best_score = 0.0

        for group in groups:
            rep = group["representative"]
            score = _title_similarity(title, rep.get("title", ""))
            # Also compare with the first few titles in the group to catch wording drift.
            for existing in group["items"][:4]:
                score = max(score, _title_similarity(title, existing.get("title", "")))
            if score > best_score:
                best_score = score
                best_group = group

        if best_group is not None and best_score >= similarity_threshold:
            best_group["items"].append(item)
            best_group["representative"] = _choose_representative(best_group["items"])
        else:
            groups.append({"representative": item, "items": [item]})

    theme_groups = []
    for group in groups:
        items = group["items"]
        if len(items) < min_group_size:
            continue

        sources = []
        seen_sources = set()
        for item in items:
            source = _source_name(item)
            if source not in seen_sources:
                seen_sources.add(source)
                sources.append(source)

        rep = _choose_representative(items)
        ranks = [_top_rank(item) for item in items]
        ranks = [rank for rank in ranks if rank is not None]
        highest_rank = min(ranks) if ranks else None
        keywords = []
        for item in items:
            keyword = item.get("keyword")
            if keyword and keyword not in keywords:
                keywords.append(keyword)

        # Prefer source diversity in displayed examples.
        display_items = []
        used_sources = set()
        for item in sorted(items, key=lambda x: (_top_rank(x) or 999, _source_name(x))):
            source = _source_name(item)
            if source in used_sources and len(used_sources) < len(sources):
                continue
            used_sources.add(source)
            display_items.append(item)
            if len(display_items) >= max_items_per_group:
                break
        if len(display_items) < min(max_items_per_group, len(items)):
            for item in items:
                if item not in display_items:
                    display_items.append(item)
                if len(display_items) >= max_items_per_group:
                    break

        score = len(sources) * 10 + len(items) * 3 + (50 - min(highest_rank or 50, 50))
        theme_groups.append({
            "theme": rep.get("title", ""),
            "count": len(items),
            "source_count": len(sources),
            "sources": sources,
            "highest_rank": highest_rank,
            "keywords": keywords[:5],
            "items": display_items,
            "score": score,
        })

    theme_groups.sort(key=lambda g: g.get("score", 0), reverse=True)
    return theme_groups[:max_groups]


def render_theme_groups_html(theme_groups: List[Dict]) -> str:
    """Render theme groups as a standalone HTML section."""
    if not theme_groups:
        return ""

    cards = []
    for idx, group in enumerate(theme_groups, 1):
        highest_rank = group.get("highest_rank")
        rank_text = f"最高排名 #{highest_rank}" if highest_rank else "暂无排名"
        source_text = "、".join(group.get("sources", [])[:6])
        if len(group.get("sources", [])) > 6:
            source_text += f" 等 {len(group.get('sources', []))} 个来源"
        keyword_text = " / ".join(group.get("keywords", [])[:4])

        item_rows = []
        for item in group.get("items", []):
            title = _escape(item.get("title", ""))
            url = _item_url(item)
            source = _escape(_source_name(item))
            kind = "RSS" if item.get("kind") == "rss" else "热榜"
            rank = _top_rank(item)
            meta_bits = [source, kind]
            if rank:
                meta_bits.append(f"#{rank}")
            if item.get("time_display"):
                meta_bits.append(_escape(item.get("time_display")))
            meta = " · ".join(meta_bits)
            if url:
                title_html = f'<a href="{_escape(url)}" target="_blank" rel="noopener noreferrer">{title}</a>'
            else:
                title_html = title
            item_rows.append(
                f"""
                <div class="theme-source-row">
                    <div class="theme-source-meta">{meta}</div>
                    <div class="theme-source-title">{title_html}</div>
                </div>
                """
            )

        cards.append(
            f"""
            <div class="theme-card" id="theme-{idx}">
                <div class="theme-card-header">
                    <div class="theme-index">{idx}</div>
                    <div class="theme-main">
                        <div class="theme-title">{_escape(group.get('theme', ''))}</div>
                        <div class="theme-meta">
                            {group.get('count', 0)} 条相关报道 · {group.get('source_count', 0)} 个来源 · {rank_text}
                        </div>
                    </div>
                </div>
                <div class="theme-sources">覆盖来源：{_escape(source_text)}</div>
                {f'<div class="theme-keywords">关联标签：{_escape(keyword_text)}</div>' if keyword_text else ''}
                <div class="theme-source-list">
                    {''.join(item_rows)}
                </div>
            </div>
            """
        )

    return f"""
    <style>
        .theme-section {{ margin-bottom: 32px; padding-bottom: 24px; border-bottom: 2px solid #e5e7eb; }}
        .theme-section-header {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 18px; }}
        .theme-section-title {{ font-size: 18px; font-weight: 700; color: #111827; }}
        .theme-section-count {{ color: #6b7280; font-size: 13px; }}
        .theme-card {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; margin-bottom: 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
        .theme-card-header {{ display: flex; gap: 12px; align-items: flex-start; margin-bottom: 10px; }}
        .theme-index {{ width: 26px; height: 26px; border-radius: 50%; background: #eef2ff; color: #4f46e5; font-size: 13px; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
        .theme-main {{ flex: 1; min-width: 0; }}
        .theme-title {{ font-size: 15px; font-weight: 650; color: #111827; line-height: 1.45; }}
        .theme-meta {{ margin-top: 4px; color: #6b7280; font-size: 12px; }}
        .theme-sources, .theme-keywords {{ color: #4b5563; font-size: 12px; margin: 8px 0; line-height: 1.5; }}
        .theme-source-list {{ margin-top: 12px; border-top: 1px solid #f3f4f6; }}
        .theme-source-row {{ padding: 10px 0; border-bottom: 1px solid #f7f7f8; }}
        .theme-source-row:last-child {{ border-bottom: none; padding-bottom: 0; }}
        .theme-source-meta {{ color: #6b7280; font-size: 11px; margin-bottom: 4px; }}
        .theme-source-title {{ font-size: 13px; line-height: 1.45; color: #1f2937; }}
        .theme-source-title a {{ color: #2563eb; text-decoration: none; }}
        .theme-source-title a:hover {{ text-decoration: underline; }}
        body.dark-mode .theme-section {{ border-bottom-color: #2d2d2d; }}
        body.dark-mode .theme-section-title {{ color: #e5e7eb; }}
        body.dark-mode .theme-card {{ background: #1f1f1f; border-color: #333; }}
        body.dark-mode .theme-title {{ color: #f3f4f6; }}
        body.dark-mode .theme-sources, body.dark-mode .theme-keywords, body.dark-mode .theme-source-title {{ color: #d1d5db; }}
        body.dark-mode .theme-source-list, body.dark-mode .theme-source-row {{ border-color: #333; }}
    </style>
    <section class="theme-section" id="theme-groups">
        <div class="theme-section-header">
            <div class="theme-section-title">主题聚合</div>
            <div class="theme-section-count">{len(theme_groups)} 个重复/多源主题</div>
        </div>
        {''.join(cards)}
    </section>
    """


def inject_theme_groups_section(html_content: str, report_data: Dict, rss_items: Optional[List[Dict]] = None) -> str:
    """Inject the theme grouping section near the top of the report content."""
    try:
        groups = build_theme_groups(report_data, rss_items)
        section = render_theme_groups_html(groups)
        if not section:
            return html_content
        marker = '<div class="content">'
        if marker in html_content:
            return html_content.replace(marker, marker + section, 1)
        return html_content
    except Exception as e:
        print(f"[主题聚合] 渲染失败，已跳过: {e}")
        return html_content
