import json
import math
import pytest
from metac_bot import (
    parse_forecast,
    aggregate,
    numeric_cdf,
    clean_env,
    already_forecast,
)


def q(kind="binary", **kwargs):
    return dict(
        type=kind,
        scaling={
            "range_min": 0,
            "range_max": 100,
            "zero_point": None,
            "inbound_outcome_count": 10 if kind == "discrete" else 200,
        },
        open_lower_bound=False,
        open_upper_bound=False,
        options=["A", "B", "C"],
        **kwargs,
    )


def response(**kw):
    return json.dumps(
        {"rationale": "Base rate and status quo, resolution criteria considered.", **kw}
    )


@pytest.mark.parametrize("p,want", [(0, 0.03), (1, 0.97), (0.4, 0.4)])
def test_binary(p, want):
    assert parse_forecast(response(probability_yes=p), q())[0] == want


@pytest.mark.parametrize(
    "raw",
    [
        "garbage",
        "{}",
        '{"rationale":"x", "probability_yes":NaN}',
        response(probability_yes=-1),
        response(probability_yes=True),
        response(probability_yes=2),
    ],
)
def test_malformed(raw):
    with pytest.raises(ValueError):
        parse_forecast(raw, q())


def test_fenced_json():
    assert (
        parse_forecast("```json\n" + response(probability_yes=0.5) + "\n```", q())[0]
        == 0.5
    )


def test_multiple():
    v, _ = parse_forecast(
        response(probabilities={"A": 0, "B": 0.3, "C": 0.7}), q("multiple_choice")
    )
    assert sum(v.values()) == pytest.approx(1)
    assert all(0 < x < 1 for x in v.values())
    with pytest.raises(ValueError):
        parse_forecast(response(probabilities={"A": 1}), q("multiple_choice"))


@pytest.mark.parametrize("kind,n", [("numeric", 201), ("discrete", 11)])
@pytest.mark.parametrize(
    "lo,hi", [(False, False), (True, False), (False, True), (True, True)]
)
def test_cdf(kind, n, lo, hi):
    question = q(kind)
    question.update(open_lower_bound=lo, open_upper_bound=hi)
    cdf = numeric_cdf({"10": 10, "50": 50, "90": 90}, question)
    assert len(cdf) == n
    assert all(math.isfinite(x) and 0 <= x <= 1 for x in cdf)
    assert all(b - a >= 0.000049 for a, b in zip(cdf, cdf[1:]))
    assert all(b - a <= 40 / (n - 1) + 1e-9 for a, b in zip(cdf, cdf[1:]))
    assert (0 < cdf[0] < 1) if lo else cdf[0] == 0
    assert (0 < cdf[-1] < 1) if hi else cdf[-1] == 1


def test_cdf_narrow_and_tails():
    question = q("numeric")
    cdf = numeric_cdf({"10": 49.99, "50": 50, "90": 50.01}, question)
    assert max(b - a for a, b in zip(cdf, cdf[1:])) <= 0.2
    question.update(open_lower_bound=True, open_upper_bound=True)
    cdf = numeric_cdf({"10": 1000, "50": 1100, "90": 1200}, question)
    assert 0 < cdf[0] < cdf[-1] < 1


def test_bad_quantiles():
    for values in ({"10": 90, "90": 10}, {"10": float("nan"), "90": 10}, {"10": 20}):
        with pytest.raises(ValueError):
            numeric_cdf(values, q("numeric"))


def test_log_grid():
    question = q("numeric")
    question["scaling"].update(range_min=1, range_max=100, zero_point=0)
    cdf = numeric_cdf({"10": 2, "50": 10, "90": 80}, question)
    assert cdf[100] == pytest.approx(0.5, abs=0.02)


def test_medians():
    assert aggregate([0.1, 0.2, 0.9], q()) == 0.2
    v = aggregate(
        [
            {"A": 0.1, "B": 0.2, "C": 0.7},
            {"A": 0.2, "B": 0.7, "C": 0.1},
            {"A": 0.8, "B": 0.1, "C": 0.1},
        ],
        q("multiple_choice"),
    )
    assert v == pytest.approx({"A": 0.4, "B": 0.4, "C": 0.2})


def test_env():
    e = clean_env(
        {
            "PATH": "/bin",
            "HOME": "/h",
            "OPENAI_API_KEY": "secret",
            "ANTHROPIC_AUTH_TOKEN": "secret",
            "AWS_ACCESS_KEY_ID": "secret",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "METACULUS_TOKEN": "secret",
        }
    )
    assert e == {"PATH": "/bin", "HOME": "/h"}


def test_remote_skip():
    assert already_forecast(
        {"my_forecasts": {"latest": {"forecast_values": [0.5, 0.5]}}}
    )
    assert not already_forecast({"my_forecasts": None})


def test_round_failures_and_durable_skip(tmp_path, monkeypatch):
    import asyncio
    import metac_bot as bot

    calls = []

    async def fake(provider, prompt, timeout, offline):
        calls.append(provider)
        if provider == "claude":
            raise RuntimeError("quota unavailable")
        return response(probability_yes=0.25)

    monkeypatch.setattr(bot, "run_cli", fake)
    question = q()
    question["id"] = 99
    post = {"id": 9, "question": question}

    async def exercise():
        assert (
            await bot.process(post, None, tmp_path, asyncio.Semaphore(3), 10, True)
            == "success"
        )
        assert (
            await bot.process(post, None, tmp_path, asyncio.Semaphore(3), 10, True)
            == "skipped"
        )

    asyncio.run(exercise())
    assert calls == ["codex", "claude", "codex"]
    state = json.loads((tmp_path / "99.json").read_text())
    assert state["forecast"][0]["probability_yes"] == 0.25
    assert state["comment"]["is_private"] is True
    assert "2/3" in state["comment"]["text"]


def test_all_fail_no_publish(tmp_path, monkeypatch):
    import asyncio
    import metac_bot as bot

    async def fake(*args):
        return "not json"

    monkeypatch.setattr(bot, "run_cli", fake)
    question = q()
    question["id"] = 100
    assert (
        asyncio.run(
            bot.process(
                {"id": 10, "question": question},
                None,
                tmp_path,
                asyncio.Semaphore(3),
                10,
                True,
            )
        )
        == "failed"
    )
    assert (
        json.loads((tmp_path / "100.json").read_text())["status"] == "all_rounds_failed"
    )


def test_publish_private_comment_first_and_never_retry_uncertain(tmp_path, monkeypatch):
    import asyncio
    import metac_bot as bot

    async def fake(*args):
        return response(probability_yes=0.5)

    monkeypatch.setattr(bot, "run_cli", fake)
    question = q()
    question.update(id=101, status="open", scheduled_close_time="2099-01-01T00:00:00Z")
    post = {"id": 11, "question": question}

    class Client:
        def __init__(self):
            self.writes = []

        def request(self, path, body=None):
            if body is None:
                return post
            self.writes.append((path, body))
            if path == "/questions/forecast/":
                raise TimeoutError("ambiguous delivery")
            return {"id": 1}

    client = Client()

    async def exercise():
        assert (
            await bot.process(post, client, tmp_path, asyncio.Semaphore(3), 10, False)
            == "failed"
        )
        assert (
            await bot.process(post, client, tmp_path, asyncio.Semaphore(3), 10, False)
            == "skipped"
        )

    asyncio.run(exercise())
    assert [x[0] for x in client.writes] == [
        "/comments/create/",
        "/questions/forecast/",
    ]
    assert client.writes[0][1]["is_private"] is True
    assert (
        json.loads((tmp_path / "101.json").read_text())["status"]
        == "forecast_uncertain"
    )


def test_ten_questions_batch(tmp_path, monkeypatch):
    import asyncio
    import metac_bot as bot

    active = 0
    peak = 0

    async def fake(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return response(probability_yes=0.5)

    monkeypatch.setattr(bot, "run_cli", fake)

    async def exercise():
        sem = asyncio.Semaphore(6)
        posts = [{"id": i, "question": dict(q(), id=i)} for i in range(10)]
        results = await asyncio.gather(
            *(bot.process(p, None, tmp_path, sem, 10, True) for p in posts)
        )
        assert results == ["success"] * 10

    asyncio.run(exercise())
    assert peak == 6


def test_auth_failure_isolated(monkeypatch):
    import metac_bot as bot
    import subprocess

    def fake(cmd, **kwargs):
        return (
            subprocess.CompletedProcess(cmd, 1, "", "subscription unavailable")
            if cmd[0] == "claude"
            else subprocess.CompletedProcess(cmd, 0, "Logged in using ChatGPT", "")
        )

    monkeypatch.setattr(bot.subprocess, "run", fake)
    assert bot.subscription_preflight() == {
        "claude": "claude: subscription login unavailable"
    }


def test_uniform_cdf_preserves_declared_quantiles():
    cdf = numeric_cdf({"10": 10, "25": 25, "50": 50, "75": 75, "90": 90}, q("numeric"))
    assert cdf[20] == pytest.approx(0.1)
    assert cdf[180] == pytest.approx(0.9)


def test_discrete_minimum_mass():
    question = q("discrete")
    cdf = numeric_cdf({"10": 49.99, "50": 50, "90": 50.01}, question)
    assert min(b - a for a, b in zip(cdf, cdf[1:])) >= 0.01 / 10 - 1e-10


def test_no_token_no_network(tmp_path, monkeypatch, capsys):
    import asyncio
    from types import SimpleNamespace
    import metac_bot as bot

    monkeypatch.setattr(bot, "TOKEN_PATH", tmp_path / "absent")
    monkeypatch.setattr(
        bot.APIClient, "posts", lambda self: pytest.fail("Network must not run")
    )
    assert (
        asyncio.run(bot.run(SimpleNamespace(state_dir=str(tmp_path), dry_run=False)))
        == 0
    )
    assert "NO TOKEN: no API calls" in capsys.readouterr().out


def test_asknews_off_by_default_and_free_opt_in(tmp_path, monkeypatch):
    import metac_bot as bot

    assert bot.asknews_context("test", None) == ""
    path = tmp_path / "token"
    path.write_text("free-test-token")
    path.chmod(0o600)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"as_string":"News with source URL"}'

    def fake(request, timeout):
        assert request.full_url.startswith("https://api.asknews.app/v1/news/search?")
        assert request.get_header("Authorization") == "Bearer free-test-token"
        return Response()

    monkeypatch.setattr(bot.urllib.request, "urlopen", fake)
    assert bot.asknews_context("test", path) == "News with source URL"


def test_discrete_minimum_mass_at_bound():
    cdf = numeric_cdf({"10": 100, "50": 100, "90": 100}, q("discrete"))
    assert min(b - a for a, b in zip(cdf, cdf[1:])) >= 0.001 - 1e-10


def test_multiple_extremes_meet_actual_api_bounds():
    from metac_bot import normalize

    for raw in ({"A": 0, "B": 0, "C": 1}, {"A": 0, "B": 1}):
        result = normalize(raw)
        assert all(0.001 <= v <= 0.999 for v in result.values())
        assert sum(result.values()) == pytest.approx(1)


def test_numeric_honors_api_point_count():
    question = q("numeric")
    question["scaling"]["inbound_outcome_count"] = 50
    assert len(numeric_cdf({"10": 10, "90": 90}, question)) == 51


def test_posts_lists_requested_tournaments(monkeypatch):
    import metac_bot as bot

    seen = []

    def request(self, path, payload=None):
        seen.append(path)
        return {"results": [], "next": None}

    monkeypatch.setattr(bot.APIClient, "request", request)
    bot.APIClient("t").posts(("bot-testing-area",))
    assert len(seen) == 1 and "tournaments=bot-testing-area" in seen[0]
    seen.clear()
    bot.APIClient("t").posts()
    assert len(seen) == 3 and "tournaments=minibench" in seen[0]
    assert "tournaments=market-pulse-26q4" in seen[2]


def test_group_subquestions_forecast_with_shared_texts(tmp_path, monkeypatch):
    """Market Pulse is all groups: each OPEN subquestion is forecast on its own id."""
    import asyncio
    import metac_bot as bot

    sub = dict(
        q("numeric"),
        id=201,
        status="open",
        title="VIX max? (Nov 9 - Nov 20)",
        description="",
        resolution_criteria="",
        fine_print="",
        scheduled_close_time="2099-01-01T00:00:00Z",
    )
    group = {
        "id": 20,
        "title": "VIX max?",
        "group_of_questions": {
            "description": "VIX description",
            "resolution_criteria": "Highest HIGH in the CBOE CSV",
            "fine_print": "Closed days are skipped",
            "questions": [sub, dict(sub, id=202, status="upcoming")],
        },
    }
    seen = []

    def request(self, path, payload=None):
        seen.append(path)
        return {"results": [group], "next": None}

    monkeypatch.setattr(bot.APIClient, "request", request)
    posts = bot.APIClient("t").posts(("market-pulse-26q4",))
    assert "group_of_questions" in urllib_unquote(seen[0])
    assert [(p["id"], p["question"]["id"]) for p in posts] == [(20, 201)]

    prompts = []

    async def fake(provider, prompt, *args):
        prompts.append(prompt)
        return response(quantiles={"10": 20, "50": 30, "90": 40})

    monkeypatch.setattr(bot, "run_cli", fake)

    class Client:
        def __init__(self):
            self.writes = []

        def request(self, path, body=None):
            if body is None:
                return group
            self.writes.append((path, body))
            return {"id": 1}

    client = Client()
    result = asyncio.run(
        bot.process(posts[0], client, tmp_path, asyncio.Semaphore(3), 10, False)
    )
    assert result == "success"
    assert "Highest HIGH in the CBOE CSV" in prompts[0]
    (_, comment), (_, forecast) = client.writes
    assert comment["on_post"] == 20
    assert forecast[0]["question"] == 201 and len(forecast[0]["continuous_cdf"]) == 201


def urllib_unquote(s):
    import urllib.parse

    return urllib.parse.unquote(s)


def _http_429():
    import email.message
    import urllib.error

    headers = email.message.Message()
    headers["Retry-After"] = "7"
    return urllib.error.HTTPError("u", 429, "Too Many Requests", headers, None)


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def test_get_retries_429_but_post_never(monkeypatch):
    import metac_bot as bot

    waits, calls = [], []

    def urlopen(request, timeout):
        calls.append(request.get_method())
        if len(calls) == 1:
            raise _http_429()
        return _Resp()

    monkeypatch.setattr(bot.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(bot.time, "sleep", waits.append)
    assert bot.APIClient("t").request("/x") == {}
    assert calls == ["GET", "GET"] and waits == [7]

    calls.clear()
    with pytest.raises(bot.urllib.error.HTTPError):
        bot.APIClient("t").request("/x", {"a": 1})
    assert calls == ["POST"]


def test_posts_stops_on_empty_page_even_with_next(monkeypatch):
    import metac_bot as bot

    pages = [{"results": [{"id": 1, "question": {"id": 1}}], "next": "u"}, {"results": [], "next": "u"}]

    def request(self, path, payload=None):
        return pages.pop(0)  # IndexError if pagination does not stop

    monkeypatch.setattr(bot.APIClient, "request", request)
    assert [p["id"] for p in bot.APIClient("t").posts(("x",))] == [1]


def test_market_pulse_refreshes_once_on_the_eve_bot_only_never(tmp_path, monkeypatch):
    """Spot scoring counts only the forecast standing at close: redo it once near close."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    import metac_bot as bot

    async def fake(provider, prompt, *args):
        return response(quantiles={"10": 20, "50": 30, "90": 40})

    monkeypatch.setattr(bot, "run_cli", fake)
    close = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
    sub = dict(
        q("numeric"),
        id=301,
        status="open",
        scheduled_close_time=close,
        my_forecasts={"latest": {"forecast_values": [0.5]}, "history": [1]},
    )
    group = {"id": 30, "group_of_questions": {"questions": [sub]}}

    class Client:
        def __init__(self):
            self.writes = []

        def request(self, path, body=None):
            if body is None:
                return group
            self.writes.append((path, body))
            return {"id": 1}

    def run(tournament, state_dir):
        state_dir.mkdir()
        (state_dir / "301.json").write_text('{"status": "published"}')
        client = Client()
        post = {**group, "question": sub, "tournament": tournament}
        results = [
            asyncio.run(bot.process(post, client, state_dir, asyncio.Semaphore(3), 10, False))
            for _ in range(2)
        ]
        return results, [w[0] for w in client.writes]

    assert run("market-pulse-26q4", tmp_path / "mp") == (
        ["success", "skipped"],
        ["/comments/create/", "/questions/forecast/"],
    )
    assert run("minibench", tmp_path / "mb") == (["skipped", "skipped"], [])


@pytest.mark.parametrize(
    "wrap",
    [
        "I've finished the research; here is the forecast.\n\n%s",
        "```json\n%s\n```\n\nSources:\n- [SRS](https://example.org/a)",
        "About 30%% {roughly}.\n\n```json\n%s\n```\n\nSources:\n- x",
        "%s\n\nSources:\n- [x](https://example.org) {not json}",
    ],
)
def test_json_with_prose_around(wrap):
    # real claude replies from runtime/live (46525, 46660, 46524, 46279)
    assert parse_forecast(wrap % response(probability_yes=0.5), q())[0] == 0.5


def test_all_failed_is_retried_until_cap(tmp_path, monkeypatch):
    # 46660 (03/11): codex out of quota + malformed claude JSON = never forecast again
    import asyncio
    import metac_bot as bot

    healthy = False

    async def fake(provider, prompt, timeout, offline):
        if not healthy:
            raise RuntimeError("usage limit")
        return response(probability_yes=0.25)

    monkeypatch.setattr(bot, "run_cli", fake)
    question = q()
    question["id"] = 77
    post = {"id": 7, "question": question}
    run = lambda: asyncio.run(
        bot.process(post, None, tmp_path, asyncio.Semaphore(3), 10, True)
    )
    assert run() == "failed"
    healthy = True
    assert run() == "success"
    assert run() == "skipped"

    healthy = False
    question["id"] = 78
    assert [run() for _ in range(bot.MAX_FAILED_TRIES + 1)] == [
        "failed"
    ] * bot.MAX_FAILED_TRIES + ["skipped"]
