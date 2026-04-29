# coding=utf-8
"""Gmail-friendly email body patch.

The default email sender attaches the full interactive browser HTML report as
`text/html`. Gmail accepts it as HTML, but strips scripts and much of the complex
browser-oriented UI, which makes the message look like plain text. This module
keeps the existing SMTP implementation and replaces the email body with a simple,
email-safe HTML digest plus a button linking to the full R2 report.
"""

from __future__ import annotations

import html
import os
import re
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple


def _strip_tags(value: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", value or "", flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _extract_ai_digest(full_html: str, max_items: int = 3) -> List[str]:
    blocks = re.findall(r'<div class="ai-block-content">([\s\S]*?)</div>', full_html or "", flags=re.I)
    digest: List[str] = []
    for block in blocks:
        text = _strip_tags(block)
        if not text:
            continue
        parts = re.split(r"(?<=[。！？!?])\s*|\n+|；|;", text)
        for part in parts:
            part = part.strip(" -•·\t\n")
            if len(part) < 18:
                continue
            digest.append(_clip(part, 96))
            if len(digest) >= max_items:
                return digest
    return digest[:max_items]


def _extract_unified_theme_digest(full_html: str, max_items: int = 5) -> List[Tuple[str, str]]:
    """Extract Top themes from the unified digest cards.

    The report no longer renders legacy `.news-item/.news-link` lists as the main
    view. Email should therefore summarize the unified theme cards, especially
    their `内容要点`, instead of trying to scrape old news links.
    """
    items: List[Tuple[str, str]] = []
    cards = re.findall(r'<div class="unified-card">([\s\S]*?)(?=<div class="unified-card">|</section>)', full_html or "", flags=re.I)
    for card in cards:
        title_match = re.search(r'<div class="unified-title">([\s\S]*?)</div>', card, flags=re.I)
        title = _clip(_strip_tags(title_match.group(1)) if title_match else "", 42)
        if not title:
            continue

        bullets = re.findall(r'<div class="unified-brief[^"]*">[\s\S]*?<li>([\s\S]*?)</li>', card, flags=re.I)
        if not bullets:
            bullets = re.findall(r'<li>([\s\S]*?)</li>', card, flags=re.I)
        brief = "；".join(_strip_tags(b) for b in bullets[:2] if _strip_tags(b))

        why_match = re.search(r'<div class="unified-why">([\s\S]*?)</div>', card, flags=re.I)
        why = _clip(_strip_tags(why_match.group(1)) if why_match else "", 90)

        if not brief:
            empty_match = re.search(r'<div class="unified-brief unified-brief-empty">([\s\S]*?)</div>\s*</div>', card, flags=re.I)
            brief = _strip_tags(empty_match.group(1)) if empty_match else "暂无可用正文摘要，需打开完整报告查看证据。"
        if why:
            brief = f"{brief}（{why}）"

        items.append((title, _clip(brief, 110)))
        if len(items) >= max_items:
            return items
    return items


def _extract_rss_highlights(full_html: str, max_items: int = 3) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    cards = re.findall(r'<div class="unified-card">([\s\S]*?)(?=<div class="unified-card">|</section>)', full_html or "", flags=re.I)
    seen = set()
    for card in cards:
        if "RSS 摘要支撑" not in card:
            continue
        title_match = re.search(r'<div class="unified-title">([\s\S]*?)</div>', card, flags=re.I)
        title = _clip(_strip_tags(title_match.group(1)) if title_match else "", 36)
        summary_match = re.search(r'<div class="unified-summary">([\s\S]*?)</div>', card, flags=re.I)
        summary = _clip(_strip_tags(summary_match.group(1)) if summary_match else "", 60)
        key = f"{title}|{summary}"
        if title and summary and key not in seen:
            seen.add(key)
            items.append((title, summary))
        if len(items) >= max_items:
            break
    return items


def _extract_top_news(full_html: str, max_items: int = 5) -> List[Tuple[str, str]]:
    unified = _extract_unified_theme_digest(full_html, max_items=max_items)
    if unified:
        return unified

    items: List[Tuple[str, str]] = []
    pattern = re.compile(
        r'<div class="news-item[^"]*"[\s\S]*?'
        r'<span class="source-name">([\s\S]*?)</span>[\s\S]*?'
        r'<[^>]*class="news-link"[^>]*>([\s\S]*?)</a>',
        flags=re.I,
    )
    for source_html, title_html in pattern.findall(full_html or ""):
        source = _clip(_strip_tags(source_html), 18)
        title = _clip(_strip_tags(title_html), 72)
        if title and (source, title) not in items:
            items.append((source or "热榜", title))
        if len(items) >= max_items:
            return items
    return items


def _read_digest_from_report(html_file_path: str) -> Tuple[List[str], List[Tuple[str, str]], List[Tuple[str, str]]]:
    try:
        full_html = Path(html_file_path).read_text(encoding="utf-8")
    except Exception:
        return [], [], []
    return _extract_ai_digest(full_html), _extract_top_news(full_html), _extract_rss_highlights(full_html)


def _render_ai_digest_rows(ai_digest: List[str]) -> str:
    if not ai_digest:
        return """
        <tr><td style="padding:14px 16px;background:#f9fafb;border:1px solid #edf0f5;border-radius:10px;color:#6b7280;font-size:14px;line-height:1.6;">本轮未抽取到 AI 快读内容，请点击完整报告查看详细分析。</td></tr>
        """
    return "".join(f"""
        <tr><td style="padding:7px 0;font-size:14px;line-height:1.6;color:#374151;"><span style="color:#4f46e5;font-weight:700;">•</span> {html.escape(item)}</td></tr>
        """ for item in ai_digest)


def _render_top_news_rows(top_news: List[Tuple[str, str]]) -> str:
    if not top_news:
        return """
        <tr><td style="padding:14px 16px;background:#f9fafb;border:1px solid #edf0f5;border-radius:10px;color:#6b7280;font-size:14px;line-height:1.6;">本轮未抽取到主题卡片，请点击完整报告查看。</td></tr>
        """
    rows = []
    for idx, (theme, brief) in enumerate(top_news, 1):
        rows.append(f"""
        <tr>
          <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
              <tr>
                <td width="28" valign="top" style="font-size:13px;color:#4f46e5;font-weight:800;padding-top:1px;">{idx}</td>
                <td valign="top">
                  <div style="font-size:14px;color:#111827;line-height:1.45;font-weight:700;margin-bottom:4px;">{html.escape(theme)}</div>
                  <div style="font-size:13px;color:#4b5563;line-height:1.55;">{html.escape(brief)}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """)
    return "".join(rows)


def _render_rss_rows(rss_rows: List[Tuple[str, str]]) -> str:
    if not rss_rows:
        return ""
    rows = []
    for theme, brief in rss_rows:
        rows.append(f"""<tr><td style="padding:6px 0;font-size:13px;line-height:1.55;color:#374151;"><span style="color:#0ea5e9;font-weight:700;">RSS</span> <b>{html.escape(theme)}</b>：{html.escape(brief)}</td></tr>""")
    return "".join(rows)


def _build_email_safe_html(report_type: str, html_file_path: str, get_time_func: Optional[Callable]) -> str:
    now = get_time_func() if get_time_func else None
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S") if now else ""
    public_base_url = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    report_url = f"{public_base_url}/reports/latest.html" if public_base_url else ""
    file_name = Path(html_file_path).name if html_file_path else ""
    ai_digest, top_news, rss_highlights = _read_digest_from_report(html_file_path)

    button_html = f"""
        <tr><td align="center" style="padding: 22px 0 8px 0;"><a href="{report_url}" target="_blank" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:13px 22px;border-radius:8px;">打开完整交互版报告</a></td></tr>
        <tr><td style="padding: 8px 0 0 0; font-size:12px; line-height:1.6; color:#6b7280; word-break:break-all;">完整报告链接：<a href="{report_url}" target="_blank" style="color:#4f46e5;text-decoration:none;">{report_url}</a></td></tr>
        """ if report_url else """
        <tr><td style="padding: 16px; background:#fff7ed; border:1px solid #fed7aa; border-radius:8px; color:#9a3412; font-size:14px; line-height:1.6;">未配置 R2_PUBLIC_BASE_URL，因此邮件无法生成完整报告链接。请在 GitHub Secrets 中配置该变量。</td></tr>
        """

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>TrendRadar 热点分析报告</title></head>
<body style="margin:0;padding:0;background:#f6f7fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,'Microsoft YaHei',sans-serif;color:#111827;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f6f7fb;padding:24px 12px;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:620px;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;">
<tr><td style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:28px 24px;text-align:center;color:#ffffff;"><div style="font-size:22px;font-weight:800;letter-spacing:.02em;">TrendRadar 热点分析报告</div><div style="font-size:13px;opacity:.9;margin-top:8px;">30 秒快读 · 完整交互 UI 请在浏览器打开</div></td></tr>
<tr><td style="padding:24px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
<tr><td style="padding:14px 16px;background:#f9fafb;border:1px solid #edf0f5;border-radius:10px;"><div style="font-size:13px;color:#6b7280;margin-bottom:6px;">报告类型</div><div style="font-size:16px;font-weight:700;color:#111827;">{html.escape(report_type)}</div></td></tr>
<tr><td style="height:12px;"></td></tr>
<tr><td style="padding:14px 16px;background:#f9fafb;border:1px solid #edf0f5;border-radius:10px;"><div style="font-size:13px;color:#6b7280;margin-bottom:6px;">生成时间</div><div style="font-size:16px;font-weight:700;color:#111827;">{html.escape(generated_at)}</div></td></tr>
<tr><td style="height:18px;"></td></tr>
<tr><td style="font-size:16px;font-weight:800;color:#111827;padding-bottom:8px;">AI 快读</td></tr>
{_render_ai_digest_rows(ai_digest)}
<tr><td style="height:18px;"></td></tr>
<tr><td style="font-size:16px;font-weight:800;color:#111827;padding-bottom:8px;">Top 5 主题要点</td></tr>
{_render_top_news_rows(top_news)}
<tr><td style="height:14px;"></td></tr>
<tr><td style="font-size:16px;font-weight:800;color:#111827;padding-bottom:8px;">RSS 重点速览</td></tr>
{_render_rss_rows(rss_highlights)}
{button_html}
<tr><td style="padding-top:22px;font-size:12px;line-height:1.7;color:#6b7280;">邮件内仅保留快读摘要和主题要点，完整分析、证据来源和交互功能请点击上方按钮在浏览器中查看。源文件：{html.escape(file_name)}</td></tr>
</table></td></tr></table></td></tr></table></body></html>"""


def install_email_summary_patch() -> None:
    try:
        import trendradar.notification.senders as senders
        import trendradar.notification.dispatcher as dispatcher
    except Exception:
        return
    if getattr(senders, "_email_summary_patch_installed", False):
        return
    original_send_to_email = senders.send_to_email

    def send_to_email_summary(from_email: str, password: str, to_email: str, report_type: str, html_file_path: str,
                              custom_smtp_server=None, custom_smtp_port=None, *, get_time_func=None) -> bool:
        public_base_url = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not public_base_url:
            return original_send_to_email(from_email, password, to_email, report_type, html_file_path,
                                          custom_smtp_server, custom_smtp_port, get_time_func=get_time_func)
        summary_html = _build_email_safe_html(report_type, html_file_path, get_time_func)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".html", delete=False) as tmp:
                tmp.write(summary_html)
                temp_path = tmp.name
            print(f"[邮件] 使用邮件安全摘要版 HTML，完整报告: {public_base_url}/reports/latest.html")
            return original_send_to_email(from_email, password, to_email, report_type, temp_path,
                                          custom_smtp_server, custom_smtp_port, get_time_func=get_time_func)
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    senders.send_to_email = send_to_email_summary
    dispatcher.send_to_email = send_to_email_summary
    senders._email_summary_patch_installed = True
