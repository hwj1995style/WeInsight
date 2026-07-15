from datetime import datetime

from app.content.article_content import ArticleContent, ProcessShadowMetrics, ShadowArticleContentProvider
from app.domain.article_parsing import ArticleParseSource


class Provider:
    def __init__(self, body, source):
        self.body, self.source, self.calls = body, source, 0

    def parse(self, request):
        self.calls += 1
        return ArticleContent(self.body, "title", None, None, None, self.source)


def test_shadow_returns_web_and_records_only_safe_difference_counts():
    web, werss, metrics = Provider("web body", "web"), Provider("secret body", "werss"), {}
    source = ArticleParseSource("h", "a", "t", "https://mp.weixin.qq.com/s/x", datetime(2026, 1, 1), None, None, "x", "werss_article_view")
    result = ShadowArticleContentProvider(web, werss, metrics).parse(source)
    assert result.body_text == "web body" and result.source == "web"
    assert web.calls == werss.calls == 1
    assert metrics == {"shadow_length_difference_count": 1, "shadow_hash_difference_count": 1}
    assert "web body" not in repr(metrics) and "secret body" not in repr(metrics)


def test_shadow_isolates_unexpected_secondary_exception_and_records_safe_type():
    class BrokenProvider:
        def parse(self, request):
            raise RuntimeError("secret body must not escape")

    metrics = ProcessShadowMetrics()
    result = ShadowArticleContentProvider(Provider("web body", "web"), BrokenProvider(), metrics).parse(
        ArticleParseSource("h", "a", "t", "https://mp.weixin.qq.com/s/x", datetime(2026, 1, 1), None, None, "x", "werss_article_view")
    )
    assert result.body_text == "web body"
    assert metrics.snapshot() == {"shadow_werss_failure_count": 1, "shadow_werss_error_RuntimeError_count": 1}
    assert "secret body" not in repr(metrics.snapshot())


def test_shadow_records_explained_limited_web_response_without_hiding_hash_difference():
    metrics = {}
    ShadowArticleContentProvider(Provider("x" * 65, "web"), Provider("y" * 1278, "werss"), metrics).parse(
        ArticleParseSource("h", "a", "t", "https://mp.weixin.qq.com/s/x", datetime(2026, 1, 1), None, None, "x", "werss_article_view")
    )
    assert metrics == {"shadow_length_difference_count": 1, "shadow_hash_difference_count": 1, "shadow_web_limited_response_count": 1}
