#!/usr/bin/env python3
"""Offline smoke test for scripts/ai_news_radar.py.

This does not hit the network. It monkeypatches the fetch layer with synthetic
items, then validates the core control loop:

config -> source loading -> relevance scoring -> dedupe -> JSON -> HTML.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ai_news_radar.py"
CONFIG_PATH = ROOT / "config" / "source_strategy.yaml"


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("ai_news_radar", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses + postponed annotations need the module to exist in sys.modules
    # while class decorators execute.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    radar = load_module()
    cfg = radar.load_config(CONFIG_PATH)
    sources = radar.load_sources(cfg)

    if not sources:
        raise AssertionError("Expected at least one enabled source")
    if not any(s.group == "official" for s in sources):
        raise AssertionError("Expected at least one official source")

    now = datetime.now(tz=timezone.utc)

    def fake_fetch_source(session: Any, src: Any) -> list[dict[str, Any]]:
        if src.id != "openai-news":
            return []
        return [
            {
                "title": "OpenAI launches new Codex agent workflow",
                "url": "https://openai.com/news/codex?utm_source=test#fragment",
                "summary": "Developer tool update for AI coding agents and workflow automation.",
                "published_at": now,
            },
            {
                "title": "OpenAI launches new Codex agent workflow",
                "url": "https://openai.com/news/codex?utm_campaign=duplicate",
                "summary": "Duplicate item should collapse after URL normalization.",
                "published_at": now,
            },
            {
                "title": "Local sports update",
                "url": "https://example.com/sports?utm_source=test",
                "summary": "Not an AI item and should be filtered out.",
                "published_at": now,
            },
        ]

    radar.fetch_source = fake_fetch_source

    items, health = radar.build_items(cfg, sources, window_hours=24, min_score=2)
    if len(items) != 1:
        raise AssertionError(f"Expected 1 deduplicated AI item, got {len(items)}")

    item = items[0]
    if "utm_" in item.url or "#" in item.url:
        raise AssertionError(f"URL was not normalized: {item.url}")
    if item.relevance_score < 2:
        raise AssertionError(f"Relevance score too low: {item.relevance_score}")
    if not any(h.source_id == "openai-news" and h.ok for h in health):
        raise AssertionError("Expected openai-news health to be OK")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        data_dir = tmp_path / "data"
        report_dir = tmp_path / "reports"
        json_path = radar.write_json_snapshot(data_dir, cfg, items, health, window_hours=24)
        html_path = radar.write_html_report(report_dir, "Smoke Test Radar", items, health, window_hours=24)

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "garron-ai-news-radar-v1":
            raise AssertionError("Unexpected schema version")
        if payload.get("item_count") != 1:
            raise AssertionError("Unexpected item_count")
        if "OpenAI launches new Codex agent workflow" not in html_path.read_text(encoding="utf-8"):
            raise AssertionError("HTML report missing expected item")

    print("AI News Radar smoke test passed")
    print(f"enabled_sources={len(sources)} official_sources={sum(1 for s in sources if s.group == 'official')}")
    print(f"item_title={item.title}")
    print(f"normalized_url={item.url}")
    print(f"relevance_score={item.relevance_score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
