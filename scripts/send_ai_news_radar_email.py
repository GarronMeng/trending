#!/usr/bin/env python3
"""Send AI News Radar digest email.

Uses the same email secret names as the existing TrendRadar workflow:

- EMAIL_FROM
- EMAIL_TO
- EMAIL_PASSWORD
- EMAIL_SMTP_SERVER
- EMAIL_SMTP_PORT

If any required secret is missing, the script exits successfully and prints a
clear skip message, so the radar pipeline remains usable without email.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any

DATA_PATH = Path("data/ai-news-radar.json")
HTML_PATH = Path("reports/latest.html")


def getenv(name: str) -> str:
    return os.getenv(name, "").strip()


def required_email_config() -> dict[str, str] | None:
    config = {
        "from": getenv("EMAIL_FROM"),
        "to": getenv("EMAIL_TO"),
        "password": getenv("EMAIL_PASSWORD"),
        "smtp_server": getenv("EMAIL_SMTP_SERVER"),
        "smtp_port": getenv("EMAIL_SMTP_PORT") or "587",
    }
    missing = [k for k, v in config.items() if not v]
    if missing:
        print(f"AI News Radar email skipped: missing {', '.join(missing)}")
        return None
    return config


def load_payload() -> dict[str, Any]:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing {DATA_PATH}")
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def build_fallback_html(payload: dict[str, Any]) -> str:
    items = payload.get("items", [])[:15]
    rows = []
    for item in items:
        title = escape(str(item.get("title", "")))
        url = escape(str(item.get("url", "")))
        source = escape(str(item.get("source_name", "")))
        score = escape(str(item.get("relevance_score", "")))
        summary = escape(str(item.get("summary") or ""))
        rows.append(
            f"""
            <article style="padding:16px 0;border-bottom:1px solid #e5e7eb;">
              <div style="font-size:13px;color:#667085;">{source} · Score {score}</div>
              <h3 style="margin:6px 0 8px;font-size:18px;line-height:1.4;"><a href="{url}">{title}</a></h3>
              <p style="margin:0;color:#475467;line-height:1.6;">{summary}</p>
            </article>
            """
        )
    return f"""
    <html>
      <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#172033;">
        <h1>AI News Radar</h1>
        <p>Generated at: <code>{escape(str(payload.get('generated_at')))}</code></p>
        <p>Items: <strong>{payload.get('item_count')}</strong> · Healthy sources: <strong>{payload.get('healthy_source_count')}/{payload.get('source_count')}</strong></p>
        {''.join(rows) if rows else '<p>本轮没有符合阈值的 AI 新闻。</p>'}
      </body>
    </html>
    """


def build_email_body(payload: dict[str, Any]) -> str:
    if HTML_PATH.exists():
        return HTML_PATH.read_text(encoding="utf-8")
    return build_fallback_html(payload)


def send_email(config: dict[str, str], payload: dict[str, Any], html_body: str) -> None:
    generated_at = payload.get("generated_at", "unknown")
    item_count = payload.get("item_count", 0)
    healthy = f"{payload.get('healthy_source_count')}/{payload.get('source_count')}"
    subject = f"AI News Radar · {item_count} items · {generated_at}"

    msg = EmailMessage()
    msg["From"] = config["from"]
    msg["To"] = config["to"]
    msg["Subject"] = subject
    msg.set_content(
        f"AI News Radar generated at {generated_at}.\n"
        f"Items: {item_count}\n"
        f"Healthy sources: {healthy}\n\n"
        "HTML email is attached/rendered below if supported.\n"
    )
    msg.add_alternative(html_body, subtype="html")

    smtp_server = config["smtp_server"]
    smtp_port = int(config["smtp_port"])
    password = config["password"]

    if smtp_port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
            server.login(config["from"], password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(config["from"], password)
            server.send_message(msg)

    print(f"AI News Radar email sent to {config['to']} with {item_count} items")


def main() -> int:
    config = required_email_config()
    if not config:
        return 0
    payload = load_payload()
    html_body = build_email_body(payload)
    send_email(config, payload, html_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
