# AI News Radar Maintenance Skill

这个 Skill 给 Codex / Claude Code / Hermes / ChatGPT 接手本仓库时使用。

它的目标不是继续堆新闻源，而是维护一条可控、可观测、可纠偏的 AI 新闻 pipeline。

## 接手顺序

1. 先读 `docs/AI_NEWS_RADAR_REFACTOR.md`。
2. 再读 `config/source_strategy.yaml`。
3. 再读 `scripts/ai_news_radar.py`。
4. 最后看 `.github/workflows/ai-news-radar.yml`。

不要一上来改旧的 `trendradar` 主流程。当前重构以并行验证为主。

## 判断一个新信源

给定一个新信源时，先判断类型：

| 类型 | 判断标准 | 动作 |
|---|---|---|
| official_rss | 官方博客、官方 changelog、官方 GitHub Atom | 直接加入主配置，权重 4–5 |
| opml_rss | 用户个人订阅包 | 放入 OPML，不直接提交私人文件 |
| public_feed | 第三方聚合源 | 权重 1–2，必须降权和去重 |
| static_page | 公开网页但没有 feed | 先写入观察清单，不急于抓取 |
| private_mail | Newsletter 邮箱 | 默认不发布原文，只输出脱敏摘要 |
| skip | 需要 cookie/token/登录态或噪音极高 | 跳过 |

## 修改原则

- 优先改 `config/source_strategy.yaml`，不要把信源硬编码进脚本。
- 能用 RSS/Atom 就不要爬网页。
- 能用公开源就不要用登录态。
- 能不调用 LLM 就先不调用 LLM。
- 如果加入 LLM 摘要，必须保证无 API Key 时主流程仍然可运行。
- 私有 token、cookie、邮箱原文、OPML 私人列表不能提交到仓库。

## 质量检查

每次改完至少检查：

```bash
uv sync --frozen --no-dev
uv run python scripts/ai_news_radar.py --window-hours 24 --min-relevance-score 2
```

看这两个文件是否生成：

```text
data/ai-news-radar.json
reports/latest.html
```

然后检查 JSON 中：

- `item_count` 是否过多或过少；
- `healthy_source_count` 是否异常下降；
- `source_health[].error` 是否出现连续失败；
- 官方源是否被聚合源淹没；
- 是否有明显非 AI 内容混入。

## 调参 SOP

| 现象 | 优先动作 |
|---|---|
| 内容太多 | 提高 `min_relevance_score` 或降低聚合源权重 |
| 内容太少 | 降低阈值、增加官方源、启用 OPML |
| 非 AI 内容混入 | 删除误伤关键词、提高聚合源阈值、加入 source include keywords |
| 同一新闻重复 | 检查 URL normalize 和标题去重 |
| 官方大事漏掉 | 新增官方 RSS / changelog，而不是依赖聚合源 |
| Actions 失败 | 先看 source health 和依赖安装，再看网络问题 |

## 后续增强方向

1. `topic clustering`：把同一事件的多源报道合并。
2. `multi-source resonance`：识别多源共振，而不是简单按时间排序。
3. `optional LLM summary`：只在有 key 时生成主题摘要。
4. `source coverage report`：为每个源建立价值、噪音、成本、风险记录。
5. `push digest`：推送只发摘要和链接，深度阅读回到静态页面。
