# HTTP response-loss lab

A server can save a record and lose the connection before its reply reaches the client. Retrying that POST can create a second record.

This Python experiment closes a real loopback TCP connection **after the write**, then compares a blind retry, recovery using a provider-supported operation key, and an explicit review state.

**[Read the measured report](https://jackspiece.github.io/http-retry-lab/)** · [Raw run](docs/run.json) · [Tests](test_retry_lab.py)

## Run

Use Python 3.12 or 3.13. There are no third-party packages or external service accounts.

```sh
python -m unittest -v
python run_demo.py
```

The second command starts a temporary server on `127.0.0.1`, runs five cases, stops the server, and regenerates `docs/index.html` and `docs/run.json`. Open the HTML file in a browser.

| Case | Requests | Records saved | Client result |
| --- | ---: | ---: | --- |
| Blind retry after a lost response | 2 | 2 | A receipt for the second record |
| Same key with provider support | 2 | 1 | The original receipt |
| Stop after an uncertain outcome | 1 | 1 | Review required |
| Header sent to a provider that ignores it | 2 | 2 | A receipt, despite the duplicate |
| Validation rejected before a write | 1 | 0 | Rejected |

The record count is measured inside the fixture server. A real client does not gain that knowledge merely because it received an error.

## The assumption that matters

`provider_supports_keys=True` is a declared contract, not automatic capability detection. A header alone does not prevent duplicates. The provider must associate the same key and request with the original operation and retain that association for the retry window.

In this fixture, reusing a key with another payload returns 409. A validation failure returns 422 before a write. Other APIs can define different contracts; review their semantics rather than importing these status-code assumptions.

The fixture holds records and keys in memory for one case. The client has no durable operation store, backoff scheduler, rate-limit handling or automatic crash recovery. A production adapter needs those decisions made for its actual destination, including key retention, operation reconciliation and who can authorize a retry. The transport is deliberately limited to loopback HTTP.

## What the tests exercise

The tests use real HTTP requests. They check the server's stored records separately from the client's result: response loss after a write, duplicate creation, keyed recovery, repeated calls, changed payloads, unusable receipts, retry exhaustion, rejection and redirects. Invalid input and external destinations must fail before a request is sent.

`docs/run.json` includes client events, server observations, runtime details and SHA-256 hashes of the source files used for that run.

The HTTP-level distinction is described in [RFC 9110, section 9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2): an automatic retry of a non-idempotent method requires knowledge about the operation's semantics or evidence that the first request was not applied. This experiment makes the first condition explicit and shows the cost of assuming it incorrectly.

Built as an independent example by [jackspiece](https://github.com/jackspiece). The data is fictional.
