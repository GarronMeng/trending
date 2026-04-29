# coding=utf-8
"""Runtime patches loaded automatically by Python when running from repo root."""

try:
    from trendradar.report.unified_only import install_analysis_first_report_patch

    install_analysis_first_report_patch()
except Exception as e:
    print(f"[sitecustomize] analysis-first report patch skipped: {e}")

try:
    from trendradar.report.unified_patch import install_unified_digest_patch

    install_unified_digest_patch()
except Exception as e:
    print(f"[sitecustomize] legacy unified digest patch skipped: {e}")
