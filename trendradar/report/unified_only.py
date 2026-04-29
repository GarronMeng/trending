# coding=utf-8
"""Analysis-first unified report patch.

The full hotlist/RSS/new/standalone sections are not rendered into the main HTML.
The page keeps the shell and AI analysis, then injects the unified digest built
from the real hotlist/RSS data.
"""

from __future__ import annotations


def _shell_report_data(report_data):
    if not isinstance(report_data, dict):
        return report_data
    data = dict(report_data)
    data["stats"] = []
    data["new_titles"] = []
    data["total_new_count"] = 0
    return data


def install_analysis_first_report_patch() -> None:
    try:
        from trendradar.context import AppContext
        from trendradar.report.unified_digest import inject_unified_digest
    except Exception:
        return

    if getattr(AppContext, "_analysis_first_report_patch_installed", False):
        return

    original_render_html = AppContext.render_html

    def render_html_analysis_first(self, report_data, total_titles, mode="daily", update_info=None,
                                   rss_items=None, rss_new_items=None, ai_analysis=None, standalone_data=None):
        shell_html = original_render_html(
            self,
            report_data=_shell_report_data(report_data),
            total_titles=total_titles,
            mode=mode,
            update_info=update_info,
            rss_items=None,
            rss_new_items=None,
            ai_analysis=ai_analysis,
            standalone_data=None,
        )
        try:
            html_content = inject_unified_digest(shell_html, report_data, rss_items)
            print("[统一新闻视图] 分析优先模式：旧热榜/RSS/新增/独立分区未渲染")
            return html_content
        except Exception as exc:
            print(f"[统一新闻视图] 分析优先模式失败，回退原始完整视图: {exc}")
            return original_render_html(
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

    AppContext.render_html = render_html_analysis_first
    AppContext._analysis_first_report_patch_installed = True
