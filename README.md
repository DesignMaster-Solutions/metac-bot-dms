# DMS Metaculus bot

Automatic forecasting with **ChatGPT Codex and Claude subscriptions**, through
`codex exec` and `claude -p`. No human in the forecasting loop. No paid LLM API
keys or SDKs. Derived from [Metaculus's template](ATTRIBUTION.md).

Python 3.11+, macOS, and subscription-authenticated `codex` / `claude` CLIs required.

```sh
uv sync
uv run pytest -q
uv run python metac_bot.py --dry-run
```

The dry run uses three explicitly synthetic API-shaped fixtures, **no web research
and no Metaculus requests**. It still calls the real subscription models. Logs and
state are stored in `runtime/dry-run/`. Repeated runs skip attempted fixtures;
use `--state-dir runtime/another-fixture-run` only for repeatable synthetic tests.
The unit suite is fully offline with mocked subprocesses and HTTP.

Live runs list open single questions from `minibench` and `fall-futureeval-2026`.
Each question gets three independent research/forecast rounds (Codex, Claude,
Codex); live Codex enables web search and Claude enables WebSearch/WebFetch.
A six-process semaphore and 10-minute round timeout bound a batch of ten to about
50 minutes plus API overhead, subject to CLI availability. The deadline is checked
before each round and again before publishing. Quota failures can reduce coverage.

Aggregation uses the median: binary probabilities clipped to 0.03–0.97,
per-option medians normalized with nonzero mass, and pointwise median numeric CDFs.
Numeric CDFs interpolate nominal quantiles on the API's linear/log grid, with 201
points (discrete: inbound outcome count + 1), open/closed endpoints and bin caps.
Malformed rounds are dropped; if all fail, nothing is published.

A durable attempt marker is written **before inference**, and an exclusive lock
prevents overlapping jobs. Existing remote forecasts are skipped. Private comments
are sent before forecasts. Every prompt, raw response, aggregate, payload and API
receipt is appended to per-question JSONL. Interrupted, failed or ambiguous sends
are never automatically retried: this favors avoiding duplicate forecasts over
coverage. Preserve `runtime/live/`; do not delete state to rerun a live question.
A comment can remain without a forecast if the second write fails. The API flow was
verified with an authenticated bot on four bot-testing-area questions (unscored).

## Activate later

A human must create the human Metaculus account, create/link the bot, complete the
participation form and save its token at `~/.config/clauditor/metaculus_token`
with permissions `600`. Do not use `metac-` as the bot account's name: the rules
reserve that prefix for Metaculus-run bots. The repository name is not the account.
The token is read only by the HTTP client, never passed to model subprocesses.
No token means no API calls and no publishing. Environment credentials are removed
from CLI subprocesses, and auth checks require subscription login.

```sh
uv run python metac_bot.py
./install_launchd.sh --print  # inspect only
./install_launchd.sh          # installs StartInterval=1200, no KeepAlive
```

Try it first on unscored questions with
`--tournament bot-testing-area --post-id <id> --state-dir runtime/testing-area`. AskNews is not required;
subscription web search is the default. After free AskNews enrollment, optionally
pass `--asknews-free-token-file /path/to/private-token` (mode 600). The adapter uses
[AskNews news search](https://docs.asknews.app/en/reference), adds context to each
independent round and records failures while continuing subscription web search.
This optional adapter has mocked tests only; no AskNews token was supplied or used.
No paid search fallback is used.

See `evidence/` for actual parser/CDF test failures, passing tests and CLI dry runs.
Private runtime logs are excluded from Git. Keep logs for competition inspection;
Metaculus may publish private comments after questions close.
