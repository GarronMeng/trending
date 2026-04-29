import unittest

from trendradar.ai.formatter import _compress_for_digest
from trendradar.report.unified_digest import build_unified_groups


class TestDigestQuality(unittest.TestCase):
    def test_compress_for_digest_limits_output(self):
        text = " ".join([f"第{i}条这是很长的描述文本用于验证压缩逻辑是否生效。" for i in range(1, 20)])
        result = _compress_for_digest(text, section_limit=120, line_limit=20)
        self.assertLessEqual(len(result), 120)
        lines = [x for x in result.splitlines() if x.strip()]
        self.assertLessEqual(len(lines), 3)

    def test_unified_groups_prioritize_evidence(self):
        report_data = {
            "stats": [
                {
                    "word": "测试主题A",
                    "titles": [
                        {"title": "A 无摘要标题1", "source_name": "源A", "ranks": [1]},
                        {"title": "A 无摘要标题2", "source_name": "源B", "ranks": [2]},
                    ],
                }
            ]
        }
        rss_items = [
            {
                "word": "测试RSS",
                "titles": [
                    {"title": "B 有摘要主题", "source_name": "RSS1", "summary": "这是可验证的正文摘要内容，长度足够用于证据。"},
                    {"title": "C 有摘要主题", "source_name": "RSS2", "summary": "这是第二条可验证摘要。"},
                ],
            }
        ]

        groups = build_unified_groups(report_data, rss_items, threshold=0.2, max_groups=10)
        # evidence-first: first group should carry evidence
        self.assertTrue(groups)
        self.assertGreater(groups[0].get("evidence_count", 0), 0)


if __name__ == "__main__":
    unittest.main()
