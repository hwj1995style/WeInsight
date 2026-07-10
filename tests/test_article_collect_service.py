from __future__ import annotations

from datetime import date, datetime

from app.rpa.fake_clients import FakeArticleRpaClient
from app.storage.article_raw_repo import ArticleRawInsertResult


class FakeArticleRawRepo:
    def __init__(self) -> None:
        self.articles = []
        self.crawl_date: date | None = None

    def insert_today_raw_ignore_duplicates(self, articles, *, crawl_date: date) -> ArticleRawInsertResult:
        self.articles = list(articles)
        self.crawl_date = crawl_date
        return ArticleRawInsertResult(
            read_count=len(self.articles),
            inserted_count=1,
            duplicate_count=max(0, len(self.articles) - 1),
            skipped_count=0,
            task_created_count=1,
        )


def test_article_collect_service_uses_fake_rpa_and_saves_links_as_today_raw() -> None:
    from app.pipelines.article_collect_service import ArticleCollectService

    collect_time = datetime(2026, 7, 6, 9, 0)
    rpa = FakeArticleRpaClient(
        links_by_account={
            "行业观察": [
                "https://mp.weixin.qq.com/s/1",
                "https://mp.weixin.qq.com/s/2",
            ]
        }
    )
    repo = FakeArticleRawRepo()
    service = ArticleCollectService(rpa=rpa, raw_repo=repo)

    result = service.collect_once(
        account_name="行业观察",
        batch_id="article-batch-1",
        collect_time=collect_time,
        max_articles=2,
    )

    assert rpa.opened_accounts == ["行业观察"]
    assert repo.crawl_date == date(2026, 7, 6)
    assert [article.article_url for article in repo.articles] == [
        "https://mp.weixin.qq.com/s/1",
        "https://mp.weixin.qq.com/s/2",
    ]
    assert repo.articles[0].account_name == "行业观察"
    assert repo.articles[0].title == "行业观察 article 1"
    assert repo.articles[0].publish_time == collect_time
    assert repo.articles[0].collect_batch_id == "article-batch-1"
    assert result.account_name == "行业观察"
    assert result.batch_id == "article-batch-1"
    assert result.link_count == 2
    assert result.insert_count == 1
    assert result.duplicate_count == 1
    assert result.skipped_count == 0


def test_article_collect_service_limits_fake_links_per_account() -> None:
    from app.pipelines.article_collect_service import ArticleCollectService

    rpa = FakeArticleRpaClient(
        links_by_account={
            "行业观察": [
                "https://mp.weixin.qq.com/s/1",
                "https://mp.weixin.qq.com/s/2",
                "https://mp.weixin.qq.com/s/3",
            ]
        }
    )
    repo = FakeArticleRawRepo()
    service = ArticleCollectService(rpa=rpa, raw_repo=repo)

    result = service.collect_once(
        account_name="行业观察",
        batch_id="article-batch-2",
        collect_time=datetime(2026, 7, 6, 10, 0),
        max_articles=1,
    )

    assert [article.article_url for article in repo.articles] == ["https://mp.weixin.qq.com/s/1"]
    assert result.link_count == 1


def test_collect_once_uses_collect_time_as_temporary_publish_time_for_real_links() -> None:
    from app.pipelines.article_collect_service import ArticleCollectService

    rpa = FakeArticleRpaClient(
        {"行业观察": ["https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"]}
    )
    repo = FakeArticleRawRepo()
    service = ArticleCollectService(rpa=rpa, raw_repo=repo)
    collect_time = datetime(2026, 7, 7, 8, 30)

    service.collect_once(
        account_name="行业观察",
        batch_id="batch-1",
        collect_time=collect_time,
        max_articles=1,
    )

    assert repo.articles[0].publish_time == collect_time
    assert repo.articles[0].title == "行业观察 article 1"
