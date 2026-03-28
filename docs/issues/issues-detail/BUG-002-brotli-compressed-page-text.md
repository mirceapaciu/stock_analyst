# BUG-002 Garbled page_text when server returns Brotli-compressed response

## Metadata
- Type: bug
- Priority: high
- Status: resolved
- Area: recommendation workflow (fetch -> parse -> extraction)

## Problem Statement
When scraping pages whose servers respond with Brotli (`br`) content encoding, the `page_text`
stored in the workflow state contains raw binary garbage instead of readable HTML text.
The `requests` library does **not** decompress Brotli responses natively, so compressed bytes
flow unchanged into BeautifulSoup and then into the `page_text` field. As a result the LLM
extraction step receives unreadable content and produces no stock recommendations.

## Verified Evidence
From `logs/workflow_state/workflow_state_20260328171325.json` (lines ~31020-31050):

URL:
```
https://www.fool.com/investing/2026/03/28/meet-the-value-stock-with-a-66-dividend-yield-that/
```

`page_text` value (excerpt):
```
+\ufffd\u0000Q0\ufffd\ufffd\u0413V\ufffd\u0007E$\ufffd?\u0004\ufffdZ$d^...
```

This is characteristic of Brotli-compressed binary data. The same URL opened in a browser
displays a readable English-language stock recommendation article.

`stock_recommendations` for this page: `[]` (empty — no extraction was possible).

Root cause in `src/recommendations/workflow.py` (scrape node, around line 1377):
```python
headers = {
    ...
    'Accept-Encoding': 'gzip, deflate, br',   # <-- advertises Brotli support
    ...
}
```

Then in `fetch_webpage_content` (non-browser path, around line 1001):
```python
html_content = response.content   # raw bytes — NOT decompressed if Brotli
soup = BeautifulSoup(html_content, 'html.parser')
```

`requests` decompresses `gzip` and `deflate` automatically, but Brotli requires the optional
`brotli` (or `brotlicffi`) package. If that package is absent when the server returns
`Content-Encoding: br`, `response.content` contains raw compressed bytes and BeautifulSoup
silently produces garbage output.

## Expected Behavior
`page_text` contains the readable article text. Stock recommendations are extracted and saved.

## Scope
In scope:
- Fix Brotli decompression in the plain-`requests` fetch path so that text arrives readable.
- Add a guard / detection so that binary-looking `page_text` is caught early and logged as a
  fetch failure rather than silently passed to the LLM.

Out of scope:
- Browser-based (Playwright) fetch path — Playwright handles encoding transparently.
- Changing the extraction prompt or LLM model.

## Acceptance Criteria
- `page_text` for Brotli-served pages (e.g. fool.com) is human-readable plain text.
- Binary/non-UTF-8 `page_text` is detected and the page is classified as a fetch failure
  (logged, no LLM call attempted).
- Existing unit and integration tests continue to pass.
- A regression test covers the Brotli decompression scenario (mock or real).

## Suggested Fix Options
1. **Remove `br` from `Accept-Encoding`** — servers will fall back to gzip/deflate which
   `requests` handles natively. Simplest fix, lowest risk.
2. **Install `brotli` or `brotlicffi`** — add to `pyproject.toml` dependencies; `urllib3`
   (used by `requests`) picks it up automatically and decompresses `br` responses.
3. **Use `response.text` instead of `response.content`** — `requests` applies charset
   decoding on `.text`, but this alone does not decompress Brotli; still needs option 1 or 2.

## Test Plan
1. Unit test:
   - Mock `requests.Session.get` to return a Brotli-compressed response with
     `Content-Encoding: br`. Assert that `page_text` is non-empty readable text (fix option 2)
     or that the page is classified as a fetch failure with a clear log message (guard).
2. Integration check:
   - Run workflow against `https://www.fool.com/investing/2026/03/28/meet-the-value-stock-with-a-66-dividend-yield-that/`
     and verify `page_text` is readable and at least one stock recommendation is extracted.

## Resolution

### Root Cause
`Accept-Encoding: gzip, deflate, br` was advertised in the HTTP request headers inside
`scrape_node` (`src/recommendations/workflow.py`). When fool.com (and potentially other servers)
honoured the `br` token, they responded with a Brotli-compressed body. The `requests` library
decompresses gzip/deflate automatically but requires the optional `brotli`/`brotlicffi` package
for Brotli. Without that package, `response.content` contained raw compressed bytes which
BeautifulSoup silently turned into garbage text.

### Steps Taken
1. **Removed `br` from `Accept-Encoding`** in `scrape_node` headers
   (`src/recommendations/workflow.py` ~line 1385): servers now fall back to gzip/deflate which
   `requests` handles natively.
2. **Added a defensive guard** in `fetch_webpage_content` (non-browser path): after
   `response.raise_for_status()`, checks `Content-Encoding` response header and raises a
   `ValueError` with a clear message if the server still returns Brotli, preventing silent
   garbage from reaching the LLM.
3. **Added `tests/test_fetch_webpage_content.py`** with 5 unit tests covering:
   - Brotli response raises `ValueError` with message and URL
   - gzip/no-encoding responses parse to readable text
   - `scrape_node` headers do not include `br`

### Remaining Risks / Follow-up
- If a server only supports Brotli (and not gzip/deflate), the new guard will raise an error
  and the page will be skipped. This is safer than the previous silent corruption. A future
  improvement could install `brotli` as a hard dependency so Brotli responses are transparently
  decompressed.
