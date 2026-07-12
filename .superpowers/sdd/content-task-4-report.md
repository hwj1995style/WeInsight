# Content Task 4 Report

## Status

Completed.

## TDD

- RED: `python -m pytest tests/test_article_transient_extractor.py tests/test_article_analysis_service.py -q` failed during collection because `ProviderBackedArticleTransientExtractor` did not exist.
- GREEN: `python -m pytest tests/test_article_transient_extractor.py tests/test_article_analysis_service.py tests/test_article_egg_price_extraction.py -q` passed with 27 tests.

## Implementation

- Added a provider-backed transient extractor that maps analysis metadata to `ArticleParseSource`, obtains content only for the current call, and uses `dataclasses.replace` to attach body text plus empty safe table/OCR lists.
- Analysis persistence continues to receive only `AnalyzedArticle`; transient body text is not part of the repository persistence API.
- Analysis task failures now persist only `ContentFetchError.code` or the exception class name, never arbitrary exception text.

## Verification

- Brief test suite: 27 passed.
- `git diff --check`: clean.

## Concerns

- None.

## Review Fix

- RED: the four requested suites reported 3 failures because `CleanArticleForAnalysis` had no locator fields and the repository could not return them.
- Added `content_locator` and `content_locator_type` to the analysis DTO, selected them from `wechat_article_raw`, and passed them into `ArticleParseSource`.
- Added a provider → transient extractor → analysis service → egg quotation integration test; it also asserts the body is absent from persisted analysis JSON.
- Added a repository-level retry-policy regression test covering pending-before-third-attempt behavior, retry increment, 60-second delay, and structured error persistence.
- GREEN: the four requested suites pass with 32 tests.
