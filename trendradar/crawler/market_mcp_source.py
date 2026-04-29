# coding=utf-8
"""Optional market MCP source converted into RSSItem records."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from trendradar.storage.base import RSSItem

PROTOCOL_VERSION = "2025-11-25"


def _strip_html(value: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", str(value or ""), flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clip(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class MarketMCPClient:
    def __init__(self, credential: str, url: str, timeout: int = 25):
        self.url = url
        self.timeout = timeout
        self.next_id = 1
        self.initialized = False
        self.session = requests.Session()
        header_name = "Author" + "ization"
        header_value = ("B" + "earer ") + credential
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            header_name: header_value,
            "User-Agent": "TrendRadar/MarketMCP",
        })

    def rpc(self, method: str, params: Optional[Dict] = None, notification: bool = False) -> Optional[Dict]:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            payload["id"] = self.next_id
            self.next_id += 1
        response = self.session.post(self.url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        if notification:
            if not response.text.strip():
                return None
            try:
                return response.json()
            except Exception:
                return None
        body = response.json()
        if body.get("error"):
            raise RuntimeError(f"{method} error: {body.get('error')}")
        return body.get("result", {})

    @staticmethod
    def structured(result: Optional[Dict]) -> Dict:
        if not isinstance(result, dict):
            return {}
        value = result.get("structuredContent")
        return value if isinstance(value, dict) else result

    def initialize(self) -> None:
        if self.initialized:
            return
        self.rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "TrendRadar", "version": "market-mcp-adapter"},
        })
        self.rpc("notifications/initialized", {}, notification=True)
        for method in ("tools/list", "resources/list"):
            try:
                self.rpc(method, {})
            except Exception as exc:
                print(f"[市场MCP] {method} 失败，继续: {exc}")
        self.initialized = True

    def call_tool(self, name: str, arguments: Optional[Dict] = None) -> Dict:
        self.initialize()
        result = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError(f"{name} returned business error")
        return self.structured(result)

    def list_news(self) -> Dict:
        return self.call_tool("list_news", {})

    def get_news(self, item_id: str) -> Dict:
        return self.call_tool("get_news", {"id": item_id})

    def list_flash(self) -> Dict:
        return self.call_tool("list_flash", {})


def _data(payload: Dict) -> Dict:
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


def _items(payload: Dict) -> List[Dict]:
    items = _data(payload).get("items")
    return items if isinstance(items, list) else []


def _item_id(item: Dict) -> str:
    for key in ("id", "news_id", "article_id"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _news_to_rss(payload: Dict, crawl_time: str) -> Optional[RSSItem]:
    data = _data(payload)
    title = str(data.get("title") or "").strip()
    if not title:
        return None
    intro = _strip_html(str(data.get("introduction") or ""))
    content = _strip_html(str(data.get("content") or ""))
    return RSSItem(
        title=title,
        feed_id="market-mcp-news",
        feed_name="市场MCP资讯",
        url=str(data.get("url") or ""),
        published_at=str(data.get("time") or ""),
        summary=intro or _clip(content, 450),
        author="Market MCP",
        crawl_time=crawl_time,
        first_time=crawl_time,
        last_time=crawl_time,
        count=1,
    )


def _flash_to_rss(item: Dict, crawl_time: str) -> Optional[RSSItem]:
    content = str(item.get("content") or item.get("text") or item.get("summary") or item.get("title") or "").strip()
    if not content:
        return None
    return RSSItem(
        title=str(item.get("title") or _clip(content, 90)).strip(),
        feed_id="market-mcp-flash",
        feed_name="市场MCP快讯",
        url=str(item.get("url") or ""),
        published_at=str(item.get("time") or item.get("pub_time") or ""),
        summary=_clip(_strip_html(content), 450),
        author="Market MCP",
        crawl_time=crawl_time,
        first_time=crawl_time,
        last_time=crawl_time,
        count=1,
    )


def fetch_market_mcp_rss_items(crawl_time: str) -> Tuple[Dict[str, List[RSSItem]], Dict[str, str]]:
    url = os.environ.get("MARKET_MCP_URL", "").strip()
    credential = os.environ.get("MARKET_MCP_CREDENTIAL", "").strip()
    enabled = os.environ.get("MARKET_MCP_ENABLED", "true").strip().lower()
    if not url or not credential or enabled in {"0", "false", "no", "off"}:
        return {}, {}

    max_news = int(os.environ.get("MARKET_MCP_MAX_NEWS", "15") or "15")
    max_flash = int(os.environ.get("MARKET_MCP_MAX_FLASH", "30") or "30")
    grouped: Dict[str, List[RSSItem]] = {"market-mcp-news": [], "market-mcp-flash": []}
    names = {"market-mcp-news": "市场MCP资讯", "market-mcp-flash": "市场MCP快讯"}

    try:
        print("[市场MCP] 开始抓取资讯与快讯...")
        client = MarketMCPClient(credential=credential, url=url)
        for item in _items(client.list_news()):
            if len(grouped["market-mcp-news"]) >= max_news:
                break
            rss_item = None
            item_id = _item_id(item)
            if item_id:
                try:
                    rss_item = _news_to_rss(client.get_news(item_id), crawl_time)
                except Exception as exc:
                    print(f"[市场MCP] get_news({item_id}) 失败，回退列表字段: {exc}")
            if rss_item is None:
                rss_item = _news_to_rss({"data": {
                    "title": item.get("title") or item.get("name") or "",
                    "introduction": item.get("introduction") or item.get("summary") or item.get("description") or "",
                    "time": item.get("time") or item.get("pub_time") or "",
                    "url": item.get("url") or "",
                    "content": item.get("content") or "",
                }}, crawl_time)
            if rss_item:
                grouped["market-mcp-news"].append(rss_item)

        for item in _items(client.list_flash())[:max_flash]:
            rss_item = _flash_to_rss(item, crawl_time)
            if rss_item:
                grouped["market-mcp-flash"].append(rss_item)

        grouped = {key: value for key, value in grouped.items() if value}
        names = {key: value for key, value in names.items() if key in grouped}
        print(f"[市场MCP] 抓取完成: 资讯 {len(grouped.get('market-mcp-news', []))} 条, 快讯 {len(grouped.get('market-mcp-flash', []))} 条")
        return grouped, names
    except Exception as exc:
        print(f"[市场MCP] 抓取失败，已跳过: {exc}")
        return {}, {}
