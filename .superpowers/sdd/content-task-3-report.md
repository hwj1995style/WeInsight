# Content Task 3 Report

## RED

- Added fallback-matrix tests and safe persistence/error-boundary tests.
- Initial command failed during collection with `ModuleNotFoundError: app.content.fallback_provider`, confirming the requested interface was absent.

## GREEN

- Added `FallbackArticleContentProvider`; only `ContentFetchError(recoverable=True)` reaches the web provider.
- Added `PlaywrightArticleContentProvider` returning `ArticleContent(source="web")`.
- Provider-based parsing normalizes whitespace, calculates SHA-256 over UTF-8 text, and persists only length/hash/source metadata.
- Provider errors persist only `ContentFetchError.code` or the safe exception type. Legacy `parser=` calls remain compatible.
- Verification: `19 passed in 0.45s`; `git diff --check` exited 0.

## Commit

- `feat: prefer WeRSS content with safe web fallback`

## Self-check

- Recoverable matrix includes locator missing, 404, empty content, timeout, and ordinary HTTP error.
- Security matrix includes blocked endpoint/redirect, oversized response, and blocked content type.
- `CleanArticleRecord` has no body field; error messages on the new provider boundary cannot contain body or URL payloads.

## Concerns

- The legacy `parser=` compatibility path necessarily retains its historical free-form error string; only the new provider boundary enforces safe error types. Existing callers should migrate to `provider=`.
