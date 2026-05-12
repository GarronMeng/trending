# AI News Radar Skill

## Mission

Maintain Garron's AI News Radar as a control loop:

1. define the information objective;
2. classify sources before ingestion;
3. fetch with the lowest-risk method;
4. normalize and deduplicate;
5. filter for AI relevance;
6. expose source health;
7. publish static artifacts;
8. use feedback to adjust source weights and thresholds.

## Source Intake Protocol

When the user provides a new source, do not add it immediately. First classify it:

- `official_rss`: official blog, changelog, documentation RSS, GitHub Atom.
- `opml_rss`: user-owned OPML/RSS bundle.
- `public_feed`: third-party aggregator feed or public JSON.
- `static_page`: public page without RSS.
- `private_mail`: newsletter or mailbox digest.
- `skip`: login-only, cookie-only, token-only, high-cost, high-noise, or unsafe source.

Then decide:

| Type | Default decision |
|---|---|
| official_rss | Add to `config/source_strategy.yaml`, weight 4–5 |
| opml_rss | Keep private, use `FOLLOW_OPML_B64`, do not commit private OPML |
| public_feed | Add only as low-weight aggregate source |
| static_page | Add to backlog unless the source is uniquely valuable |
| private_mail | Publish only sanitized summaries |
| skip | Explain why it should not be added |

## Editing Rules

- Prefer configuration changes over code changes.
- Do not commit API keys, cookies, tokens, private OPML, or email contents.
- Do not make LLM access required for the core pipeline.
- Keep `scripts/ai_news_radar.py` runnable without secrets.
- Keep old TrendRadar workflow intact until the new radar is validated.
- If the user asks for a full migration, first run the AI News Radar workflow in parallel for at least several cycles.

## Feedback Loop

Use these metrics after every run:

- `item_count`: too high means the radar is noisy; too low means it is blind.
- `healthy_source_count`: falling source health means ingestion is unstable.
- `source_health[].kept_count`: high fetch/low keep means a source is noisy.
- false positives: remove broad keywords or lower aggregate weight.
- false negatives: add official sources or source-specific include keywords.

## Minimum Validation

Run:

```bash
uv sync --frozen --no-dev
uv run python scripts/ai_news_radar.py --window-hours 24 --min-relevance-score 2
```

Expected outputs:

```text
data/ai-news-radar.json
reports/latest.html
```

Review:

- Are official sources visible?
- Are aggregator items overrepresented?
- Are there obvious non-AI false positives?
- Did any source fail repeatedly?
- Is the final static HTML readable on mobile?

## Escalation Path

Only after the MVP is stable:

1. add topic clustering;
2. add multi-source resonance scoring;
3. add optional LLM summaries;
4. add source coverage documentation;
5. connect the output to existing notification channels.
