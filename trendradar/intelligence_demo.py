# coding=utf-8
"""Standalone demo for Jin10-anchored intelligence cards.

Run locally or in GitHub Actions with:
    uv run python -m trendradar.intelligence_demo

This demo does not affect the production report. It reads the optional market MCP
source, builds event-style cards from returned news/flash records, and writes a
separate HTML file:
    output/html/latest/intelligence_demo.html
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from trendradar.crawler.market_mcp_source import fetch_market_mcp_rss_items
from trendradar.utils.time import get_configured_time, DEFAULT_TIMEZONE


@dataclass
class Evidence:
    title: str
    source: str
    summary: str
    url: str = ""
    time: str = ""


@dataclass
class IntelligenceCard:
    topic: str
    what_happened: List[str] = field(default_factory=list)
    why_it_matters: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    score: float = 0.0


def _esc(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def _clip(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _split_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?])\s*|(?<=[.!?])\s+|；|;", text)
    return [p.strip() for p in parts if len(p.strip()) >= 16]


def _importance_hint(text: str) -> str:
    text = str(text or "")
    rules = [
        (("美联储", "降息", "利率", "通胀", "非农", "PCE", "CPI"), "可能影响美元、美债收益率、黄金以及成长股估值。"),
        (("原油", "OPEC", "欧佩克", "库存", "供给", "制裁"), "可能影响油价、能源股、通胀预期和航空化工等成本敏感行业。"),
        (("黄金", "金价", "避险"), "可能反映实际利率、美元和避险情绪变化，需要结合美元与美债收益率观察。"),
        (("日元", "日本央行", "美元/日元", "汇率"), "可能影响外汇波动、套息交易和亚洲风险资产情绪。"),
        (("人民币", "离岸人民币", "美元/人民币", "汇率"), "可能影响港股/A股风险偏好、出口链和外资情绪。"),
        (("关税", "贸易", "制裁", "地缘"), "可能影响全球供应链、风险偏好和相关行业估值。"),
    ]
    for keywords, hint in rules:
        if any(k.lower() in text.lower() for k in keywords):
            return hint
    return "事件本身具有财经信息价值，但是否形成交易线索仍需观察后续数据、价格反应和多源确认。"


def _build_cards() -> List[IntelligenceCard]:
    now = get_configured_time(DEFAULT_TIMEZONE)
    crawl_time = now.strftime("%H:%M")
    grouped, _ = fetch_market_mcp_rss_items(crawl_time)

    items = []
    for feed_id, feed_items in grouped.items():
        for item in feed_items:
            items.append(item)

    cards: List[IntelligenceCard] = []
    for item in items[:18]:
        summary = item.summary or ""
        facts = []
        for sentence in _split_sentences(summary):
            facts.append(_clip(sentence, 110))
            if len(facts) >= 3:
                break
        if not facts:
            facts = ["当前仅获得标题或短文本，需点击原文确认细节。"]

        title_summary = f"{item.title} {summary}"
        risk_flags = []
        if not item.summary:
            risk_flags.append("仅标题信号")
        if len(summary) < 30:
            risk_flags.append("正文摘要不足")

        cards.append(IntelligenceCard(
            topic=item.title,
            what_happened=facts,
            why_it_matters=_importance_hint(title_summary),
            evidence=[Evidence(
                title=item.title,
                source=item.feed_name,
                summary=_clip(summary, 180),
                url=item.url,
                time=item.published_at or item.crawl_time,
            )],
            risk_flags=risk_flags,
            score=(2 if item.feed_id.endswith("news") else 1) + (2 if item.summary else 0),
        ))

    cards.sort(key=lambda c: c.score, reverse=True)
    return cards[:12]


def _render(cards: List[IntelligenceCard]) -> str:
    card_html = []
    for idx, card in enumerate(cards, 1):
        facts = "".join(f"<li>{_esc(f)}</li>" for f in card.what_happened[:3])
        risks = "".join(f"<span class='badge risk'>{_esc(r)}</span>" for r in card.risk_flags) or "<span class='badge ok'>摘要支撑</span>"
        evidence_rows = []
        for ev in card.evidence[:3]:
            title = _esc(ev.title)
            link = f"<a href='{_esc(ev.url)}' target='_blank' rel='noopener noreferrer'>{title}</a>" if ev.url else title
            evidence_rows.append(f"""
            <div class='evidence-row'>
              <div class='meta'>{_esc(ev.source)} · {_esc(ev.time)}</div>
              <div class='ev-title'>{link}</div>
              <div class='summary'>{_esc(ev.summary)}</div>
            </div>
            """)
        card_html.append(f"""
        <article class='card'>
          <div class='card-head'>
            <div class='index'>{idx}</div>
            <div>
              <h2>{_esc(card.topic)}</h2>
              <div class='badges'>{risks}</div>
            </div>
          </div>
          <section>
            <h3>这件事讲了什么</h3>
            <ul>{facts}</ul>
          </section>
          <section>
            <h3>为什么重要</h3>
            <p>{_esc(card.why_it_matters)}</p>
          </section>
          <details>
            <summary>展开证据</summary>
            {''.join(evidence_rows)}
          </details>
        </article>
        """)

    empty = "" if cards else "<div class='empty'>没有拿到市场 MCP 数据。请检查 MARKET_MCP_URL / MARKET_MCP_CREDENTIAL 是否传入运行环境。</div>"
    return f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>Intelligence Card Demo</title>
  <style>
    body {{ margin:0; padding:24px; background:#f8fafc; color:#0f172a; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif; }}
    main {{ max-width:920px; margin:0 auto; }}
    .hero {{ background:linear-gradient(135deg,#1e3a8a,#4338ca); color:white; border-radius:18px; padding:28px; margin-bottom:20px; }}
    .hero h1 {{ margin:0 0 8px; font-size:24px; }}
    .hero p {{ margin:0; opacity:.9; line-height:1.6; }}
    .card {{ background:white; border:1px solid #e2e8f0; border-radius:16px; padding:20px; margin-bottom:16px; box-shadow:0 1px 3px rgba(15,23,42,.06); }}
    .card-head {{ display:flex; gap:12px; align-items:flex-start; margin-bottom:14px; }}
    .index {{ width:30px; height:30px; border-radius:50%; background:#dbeafe; color:#1d4ed8; display:flex; align-items:center; justify-content:center; font-weight:800; flex-shrink:0; }}
    h2 {{ margin:0 0 8px; font-size:17px; line-height:1.45; }}
    h3 {{ margin:14px 0 6px; font-size:13px; color:#1e40af; }}
    p, li {{ font-size:14px; line-height:1.65; }}
    ul {{ margin:0; padding-left:20px; }}
    .badges {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .badge {{ font-size:11px; font-weight:700; border-radius:999px; padding:3px 8px; }}
    .badge.ok {{ background:#dcfce7; color:#166534; }}
    .badge.risk {{ background:#fee2e2; color:#991b1b; }}
    details {{ margin-top:12px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:12px; }}
    summary {{ cursor:pointer; color:#475569; font-size:13px; font-weight:700; }}
    .evidence-row {{ padding:10px 0; border-bottom:1px solid #e2e8f0; }}
    .evidence-row:last-child {{ border-bottom:none; }}
    .meta {{ font-size:12px; color:#64748b; margin-bottom:4px; }}
    .ev-title {{ font-size:14px; font-weight:700; line-height:1.5; }}
    .ev-title a {{ color:#2563eb; text-decoration:none; }}
    .summary {{ margin-top:4px; color:#475569; font-size:13px; line-height:1.55; }}
    .empty {{ background:#fff7ed; border:1px solid #fed7aa; color:#9a3412; border-radius:12px; padding:16px; }}
  </style>
</head>
<body>
  <main>
    <section class='hero'>
      <h1>金十基点 · 事件情报卡 Demo</h1>
      <p>验证逻辑：先用金十资讯/快讯作为事实锚点，再生成“这件事讲了什么 / 为什么重要 / 证据”的分析卡。此页面不影响正式报告。</p>
    </section>
    {empty}
    {''.join(card_html)}
  </main>
</body>
</html>"""


def main() -> None:
    cards = _build_cards()
    html_content = _render(cards)
    out_dir = Path("output/html/latest")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "intelligence_demo.html"
    out_file.write_text(html_content, encoding="utf-8")
    print(f"[情报卡Demo] 已生成: {out_file}，卡片数: {len(cards)}")


if __name__ == "__main__":
    main()
