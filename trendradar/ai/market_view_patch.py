# coding=utf-8
"""Compatibility patch for market_view in AI analysis responses."""

from __future__ import annotations


def enable_market_view_output() -> None:
    """Ensure prompt field `market_view` is parsed and visible in existing renderers."""
    try:
        from trendradar.ai.analyzer import AIAnalyzer, AIAnalysisResult
    except Exception:
        return

    if getattr(AIAnalyzer, "_market_view_patch_enabled", False):
        return

    original_parse_response = AIAnalyzer._parse_response

    def parse_response_with_market_view(self, response: str):
        result = original_parse_response(self, response)

        try:
            import json
            data = None
            json_str = response or ""
            if "```json" in json_str:
                json_str = json_str.split("```json", 1)[1]
                json_str = json_str.split("```", 1)[0]
            elif "```" in json_str:
                parts = json_str.split("```", 2)
                if len(parts) >= 2:
                    json_str = parts[1]
            json_str = json_str.strip()

            try:
                data = json.loads(json_str)
            except Exception:
                try:
                    from json_repair import repair_json
                    repaired = repair_json(json_str, return_objects=True)
                    if isinstance(repaired, dict):
                        data = repaired
                except Exception:
                    data = None

            market_view = ""
            if isinstance(data, dict):
                market_view = str(data.get("market_view", "") or "")

            setattr(result, "market_view", market_view)

            if market_view:
                if result.outlook_strategy:
                    result.outlook_strategy = (
                        f"【市场映射与交易洞察】\n{market_view}\n\n"
                        f"【研判与行动建议】\n{result.outlook_strategy}"
                    )
                else:
                    result.outlook_strategy = f"【市场映射与交易洞察】\n{market_view}"
        except Exception:
            pass

        return result

    AIAnalysisResult.market_view = ""
    AIAnalyzer._parse_response = parse_response_with_market_view
    AIAnalyzer._market_view_patch_enabled = True
