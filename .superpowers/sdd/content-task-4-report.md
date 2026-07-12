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

- `CleanArticleForAnalysis` does not yet carry the WeRSS locator, so production wiring must pair this extractor with a provider that can resolve from the currently available source metadata, or a later migration must add locator propagation.
