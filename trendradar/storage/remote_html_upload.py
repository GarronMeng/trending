# coding=utf-8
"""Upload generated HTML reports to S3-compatible public storage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def install_remote_html_upload_patch() -> None:
    """Patch RemoteStorageBackend.save_html_report to also upload HTML to R2/S3."""
    try:
        from trendradar.storage.remote import RemoteStorageBackend
    except Exception:
        return

    original_save_html_report = getattr(RemoteStorageBackend, "save_html_report", None)
    if not original_save_html_report:
        return

    if getattr(RemoteStorageBackend, "_html_upload_patch_installed", False):
        return

    def save_html_report_with_upload(self, html_content: str, filename: str) -> Optional[str]:
        local_path = original_save_html_report(self, html_content, filename)
        if not local_path:
            return local_path

        public_base_url = os.environ.get("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not public_base_url:
            print("[远程存储] 未配置 R2_PUBLIC_BASE_URL，HTML 报告仅保存到临时目录")
            return local_path

        try:
            body = html_content.encode("utf-8")
            date_folder = self._format_date_folder()
            history_key = f"reports/{date_folder}/{Path(filename).name}"
            latest_key = "reports/latest.html"

            for key in (history_key, latest_key):
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=body,
                    ContentLength=len(body),
                    ContentType="text/html; charset=utf-8",
                    CacheControl="no-cache" if key == latest_key else "public, max-age=31536000",
                )
                print(f"[远程存储] HTML 报告已上传: {key}")

            latest_url = f"{public_base_url}/{latest_key}"
            history_url = f"{public_base_url}/{history_key}"
            print(f"[远程存储] 最新 HTML 报告链接: {latest_url}")
            print(f"[远程存储] 历史 HTML 报告链接: {history_url}")
            return latest_url
        except Exception as e:
            print(f"[远程存储] 上传 HTML 报告到 R2 失败: {e}")
            return local_path

    RemoteStorageBackend.save_html_report = save_html_report_with_upload
    RemoteStorageBackend._html_upload_patch_installed = True
