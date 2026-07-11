# Task 8 implementation report

## Outcome

- Removed the public-account wxauto protocol, fake, client, state-machine, runner, route-cache, progress repository, and CLI paths.
- Preserved group wxauto collection and desktop initialization/probing behavior.
- Moved the polling result value object used by RSS/managed collection into the RSS runner.
- Added `20260711_003_drop_article_rpa_state.sql` with backup and continuous 24-hour POC gates; `feed_url` null validation precedes the guarded `NOT NULL` change.

## TDD evidence

- RED: `pytest tests/test_article_rpa_removed.py -v` — 3 expected failures before removal.
- GREEN: focused migration, removal, wxauto group, and group runner suite — 14 passed.

## Verification

- Focused required suite: 14 passed.
- Full suite was run and exposed stale legacy test imports; those tests are being removed or redirected as part of this destructive cleanup. A final full-suite pass remains required before integration.

## Review notes

- The destructive migration must not be executed automatically. Operators must verify backup completion, the 24-hour RSS POC, and zero null/blank `feed_url` rows.
- Historical operational/design documents may still mention removed commands; they are records, not runtime entry points.

## Follow-up cleanup

- Restored `tests/test_source_write_guards.py`; removed only route-cache/progress cases and retained group plus RSS article raw/log source-lock coverage.
- Restored `tests/test_pipeline_isolation.py`; replaced deleted state-machine coverage with RSS/group table and import-isolation assertions.
- Rewrote `tests/test_article_real_poc_readiness.py` to assert legacy POC commands/builders are absent.
- Removed stale public-account RPA cases from `tests/test_main.py` while retaining shared group managed-mode cases.
- Removed obsolete RPA commands from the sensitive-output policy and README runtime instructions.
- Initial follow-up full run: `9 failed, 1573 passed, 2 skipped`; all failures were stale `tests/test_main.py` RPA cases.
- Second full run: `1 failed, 1573 passed, 2 skipped`; remaining failure was the stale sensitive-output command list.
- Removed route-cache/progress dependencies from source-reference and source-mutation repositories, fresh-schema DDL, and collector-role grants; updated durable-history tests accordingly.
- Final verification: `1574 passed, 2 skipped, 1 warning` and `git diff --check` exited zero.

## Human-review corrections

- `_003` now uses an explicit `SIGNAL SQLSTATE '45000'` gate when any `feed_url` is null/blank. It instructs operators to backfill verified real URLs and rerun; it never invents URLs.
- Physically deleted the dormant public-account RPA tests from `test_main.py` and added `article-rpa-probe` to primary removal assertions.
- Parent `test_wxauto_client.py` contained 84 tests: 77 were exclusively for `WxautoArticleRpaClient`, public-account navigation, route caching, article-card discovery, or link extraction and were removed. Seven group/shared tests remain, covering message normalization, scrolling, transient chat retry, wxauto4 preference, prepare-and-retry, bounded initialization, and wrapped initialization errors.
- Focused correction suite: `63 passed`.
