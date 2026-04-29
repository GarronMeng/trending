import tempfile
import unittest
from pathlib import Path

from trendradar.notification.email_summary import _read_digest_from_report


SAMPLE_HTML = '''
<section>
  <div class="unified-card">
    <div class="unified-title">主题A</div>
    <div class="unified-why">入选理由：2条正文证据 · 3个来源交叉</div>
    <div class="unified-badge rss">RSS 摘要支撑</div>
    <div class="unified-brief"><ul><li>要点一</li><li>要点二</li></ul></div>
    <div class="unified-summary">这是一条用于RSS速览的摘要信息，应该被提取。</div>
  </div>
  <div class="unified-card">
    <div class="unified-title">主题A</div>
    <div class="unified-badge rss">RSS 摘要支撑</div>
    <div class="unified-summary">这是一条用于RSS速览的摘要信息，应该被提取。</div>
  </div>
</section>
'''


class TestEmailSummaryDigest(unittest.TestCase):
    def test_read_digest_extracts_why_and_dedup_rss(self):
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
            tmp.write(SAMPLE_HTML)
            tmp_path = tmp.name
        try:
            ai_digest, top_news, rss_highlights = _read_digest_from_report(tmp_path)
            self.assertEqual(ai_digest, [])
            self.assertTrue(top_news)
            self.assertIn("入选理由", top_news[0][1])
            # duplicate RSS card should be deduped to one row
            self.assertEqual(len(rss_highlights), 1)
            self.assertEqual(rss_highlights[0][0], "主题A")
        finally:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
