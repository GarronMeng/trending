# coding=utf-8
"""Gmail-friendly email body patch.

The default email sender attaches the full interactive browser HTML report as
`text/html`. Gmail accepts it as HTML, but strips scripts and much of the complex
browser-oriented UI, which makes the message look like plain text. This module
keeps the existing SMTP implementation and replaces the email body with a simple,
email-safe HTML summary plus a button linking to the full R2 report.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Optional


def _build_email_safe_html(report_type: str, html_file_path: str, get_time_func: Optional[Callable]) -> str:
    now = get_time_func() if get_time_func else None
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S") if now else ""

    public_base_url = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
    report_url = f"{public_base_url}/reports/latest.html" if public_base_url else ""

    file_name = Path(html_file_path).name if html_file_path else ""

    button_html = ""
    if report_url:
        button_html = f"""
        <tr>
          <td align="center" style="padding: 22px 0 8px 0;">
            <a href="{report_url}" target="_blank" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:13px 22px;border-radius:8px;">
              打开完整交互版报告
            </a>
          </td>
        </tr>
        <tr>
          <td style="padding: 8px 0 0 0; font-size:12px; line-height:1.6; color:#6b7280; word-break:break-all;">
            完整报告链接：<a href="{report_url}" target="_blank" style="color:#4f46e5;text-decoration:none;">{report_url}</a>
          </td>
        </tr>
        """
    else:
        button_html = """
        <tr>
          <td style="padding: 16px; background:#fff7ed; border:1px solid #fed7aa; border-radius:8px; color:#9a3412; font-size:14px; line-height:1.6;">
            未配置 R2_PUBLIC_BASE_URL，因此邮件无法生成完整报告链接。请在 GitHub Secrets 中配置该变量。
          </td>
        </tr>
        """

    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TrendRadar 热点分析报告</title>
  </head>
  <body style="margin:0;padding:0;background:#f6f7fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,'Microsoft YaHei',sans-serif;color:#111827;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f6f7fb;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:620px;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;">
            <tr>
              <td style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:28px 24px;text-align:center;color:#ffffff;">
                <div style="font-size:22px;font-weight:800;letter-spacing:.02em;">TrendRadar 热点分析报告</div>
                <div style="font-size:13px;opacity:.9;margin-top:8px;">邮件摘要版 · 完整交互 UI 请在浏览器打开</div>
              </td>
            </tr>
            <tr>
              <td style="padding:24px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td style="padding:14px 16px;background:#f9fafb;border:1px solid #edf0f5;border-radius:10px;">
                      <div style="font-size:13px;color:#6b7280;margin-bottom:6px;">报告类型</div>
                      <div style="font-size:16px;font-weight:700;color:#111827;">{report_type}</div>
                    </td>
                  </tr>
                  <tr><td style="height:12px;"></td></tr>
                  <tr>
                    <td style="padding:14px 16px;background:#f9fafb;border:1px solid #edf0f5;border-radius:10px;">
                      <div style="font-size:13px;color:#6b7280;margin-bottom:6px;">生成时间</div>
                      <div style="font-size:16px;font-weight:700;color:#111827;">{generated_at}</div>
                    </td>
                  </tr>
                  <tr><td style="height:12px;"></td></tr>
                  <tr>
                    <td style="padding:14px 16px;background:#f9fafb;border:1px solid #edf0f5;border-radius:10px;">
                      <div style="font-size:13px;color:#6b7280;margin-bottom:6px;">本地报告文件</div>
                      <div style="font-size:14px;color:#374151;">{file_name}</div>
                    </td>
                  </tr>
                  {button_html}
                  <tr>
                    <td style="padding-top:22px;font-size:13px;line-height:1.7;color:#6b7280;">
                      Gmail 会清理完整网页报告中的脚本和复杂样式，因此邮件内只保留摘要入口。完整 UI、搜索、Tab、宽屏、暗色模式和截图导出，请点击上方按钮在浏览器中查看。
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def install_email_summary_patch() -> None:
    """Patch notification email sending to use an email-safe body."""
    try:
        import trendradar.notification.senders as senders
        import trendradar.notification.dispatcher as dispatcher
    except Exception:
        return

    if getattr(senders, "_email_summary_patch_installed", False):
        return

    original_send_to_email = senders.send_to_email

    def send_to_email_summary(
        from_email: str,
        password: str,
        to_email: str,
        report_type: str,
        html_file_path: str,
        custom_smtp_server=None,
        custom_smtp_port=None,
        *,
        get_time_func=None,
    ) -> bool:
        public_base_url = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not public_base_url:
            # Fall back to original behavior when there is no public report URL.
            return original_send_to_email(
                from_email,
                password,
                to_email,
                report_type,
                html_file_path,
                custom_smtp_server,
                custom_smtp_port,
                get_time_func=get_time_func,
            )

        summary_html = _build_email_safe_html(report_type, html_file_path, get_time_func)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".html", delete=False) as tmp:
                tmp.write(summary_html)
                temp_path = tmp.name

            print(f"[邮件] 使用邮件安全摘要版 HTML，完整报告: {public_base_url}/reports/latest.html")
            return original_send_to_email(
                from_email,
                password,
                to_email,
                report_type,
                temp_path,
                custom_smtp_server,
                custom_smtp_port,
                get_time_func=get_time_func,
            )
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    senders.send_to_email = send_to_email_summary
    dispatcher.send_to_email = send_to_email_summary
    senders._email_summary_patch_installed = True
