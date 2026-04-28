# coding=utf-8
"""Runtime patch for injecting unified hotlist + RSS digest into HTML reports."""

from __future__ import annotations


def install_unified_digest_patch() -> None:
    """Patch AppContext.render_html without touching the large context.py file."""
    try:
        from trendradar.context import AppContext
        from trendradar.report.unified_digest import inject_unified_digest
    except Exception:
        return

    if getattr(AppContext, "_unified_digest_patch_installed", False):
        return

    original_render_html = AppContext.render_html

    def render_html_with_unified_digest(self, report_data, total_titles, mode="daily", update_info=None,
                                        rss_items=None, rss_new_items=None, ai_analysis=None, standalone_data=None):
        html_content = original_render_html(
            self,
            report_data=report_data,
            total_titles=total_titles,
            mode=mode,
            update_info=update_info,
            rss_items=rss_items,
            rss_new_items=rss_new_items,
            ai_analysis=ai_analysis,
            standalone_data=standalone_data,
        )
        try:
            return inject_unified_digest(html_content, report_data, rss_items)
        except Exception as e:
            print(f"[统一新闻视图] 注入失败，已跳过: {e}")
            return html_content

    AppContext.render_html = render_html_with_unified_digest
    AppContext._unified_digest_patch_installed = True
