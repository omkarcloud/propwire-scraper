"""propwire/fetch.py on the pooled sessions: no network (a fake curl session
inside a real fetch._Session; the pool's mint, which is the homepage GET
that reads the guest JWT, is faked and counted). Since 2026-11-11 also the
property_search egress: the gateway exit (config.PROPWIRE_EXIT) with the
residential exit behind it (config.PROPWIRE_FALLBACK_EXIT).

    python -m pytest propwire/test_fetch.py -q
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from propwire import fetch  # noqa: E402
from scraper_utils.testing import hosted_only


class Resp:
    def __init__(self, status=200, text="", payload=None):
        self.status_code, self.text, self._payload = status, text, payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeCurl:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.cookies = []
        self.closed = False

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw.get("headers") or {}))
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw.get("headers") or {}))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setattr(fetch.config, "MAX_RETRIES", 1)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    queue, minted = [], []

    def fake_mint(kind, hint=None):
        sess = fetch._Session(FakeCurl(queue.pop(0) if queue else []), f"jwt-{kind}-{len(minted) + 1}", None)
        minted.append(sess)
        return sess

    p = fetch._sessions
    p.clear()
    p._mint_fn = fake_mint
    p.minted = minted
    p.script = lambda *per_session: queue.extend(list(r) for r in per_session)
    yield p
    p.clear()
    p._mint_fn = fetch._mint


def test_three_threads_share_one_minted_session_and_a_block_retires_it(pool):
    """Three sequential calls on three different threads ride ONE pooled WEB
    session: the homepage mint (guest JWT) happens once (before: once per
    thread) and every call carries that JWT. A DataDome 403 then retires it
    (closed, nothing idle); the SEARCH kind has its own sessions."""
    pool.script([Resp(payload={"n": i}) for i in (1, 2, 3)] + [Resp(status=403, text="captcha")],
                [Resp(payload={"search": True})])
    results = []
    for _ in range(3):
        t = threading.Thread(target=lambda: results.append(fetch.fetch_autocomplete("aus", ["C"])))
        t.start()
        t.join()
    assert results == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert len(pool.minted) == 1
    sess = pool.minted[0]
    assert all(c[2]["authorization"] == "Bearer jwt-web-1" for c in sess.session.calls)
    assert pool.stats(fetch.WEB)["idle"] == 1 and not sess.closed
    with pytest.raises(fetch.PropwireBlocked):
        fetch.fetch_autocomplete("aus", ["C"])
    assert sess.dead and sess.closed and pool.stats(fetch.WEB)["idle"] == 0
    assert fetch.fetch_property_search({"size": 1}) == {"search": True}
    assert len(pool.minted) == 2 and pool.minted[1].key == fetch.SEARCH


def test_failed_mint_lends_nothing_and_the_retry_mints_again(pool, monkeypatch):
    monkeypatch.setattr(fetch.config, "MAX_RETRIES", 2)
    real = pool._mint_fn
    state = {"n": 0}

    def flaky(kind, hint=None):
        state["n"] += 1
        if state["n"] == 1:
            raise fetch.PropwireBlocked("homepage HTTP 403 (anti-bot)")
        return real(kind, hint)
    pool._mint_fn = flaky
    pool.script([Resp(payload={"ok": True})])
    assert fetch.fetch_autocomplete("aus", ["C"]) == {"ok": True}
    assert state["n"] == 2 and len(pool.minted) == 1 and pool.stats(fetch.WEB)["idle"] == 1


# ---- property_search egress: the gateway exit, the residential exit behind it (2026-11-11) ----

RESI = "http://resi-us:1"
OK, CAPTCHA = Resp(payload={"ok": True}), Resp(status=403, text='{"url":"https://geo.captcha-delivery.com/captcha/"}')


@pytest.fixture
def gateway(pool, monkeypatch):
    """The pool with the search knobs as shipped, MAX_RETRIES 3 and a clean
    refusal count; `pool.keys()` = the pool key of every mint so far."""
    config = fetch.config
    monkeypatch.setattr(config, "MAX_RETRIES", 3)
    monkeypatch.setattr(config, "PROPWIRE_EXIT", "gateway")
    monkeypatch.setattr(config, "PROPWIRE_FALLBACK_EXIT", "us")
    monkeypatch.setattr(config, "PROPWIRE_WEB_EXIT", "direct")
    monkeypatch.setattr(config, "PROPWIRE_GATEWAY_SESSION_USES", 8)
    monkeypatch.setattr(config, "PROPWIRE_GATEWAY_REFUSALS", 2)
    monkeypatch.setattr(config, "PROPWIRE_GATEWAY_PAUSE", 900)
    monkeypatch.setattr(config, "residential_proxy", lambda c, states=None: f"http://resi-{c}:1")
    monkeypatch.setitem(fetch._gateway, "refusals", 0)
    monkeypatch.setitem(fetch._gateway, "paused_until", 0.0)
    monkeypatch.setattr(fetch._local, "last_retry", False, raising=False)
    pool.keys = lambda: [s.key for s in pool.minted]
    return pool


@hosted_only
def test_search_knobs_as_shipped():
    config = fetch.config
    assert (config.PROPWIRE_EXIT, config.PROPWIRE_FALLBACK_EXIT, config.PROPWIRE_WEB_EXIT) == ("gateway", "us", "direct")
    assert config.PROPWIRE_GATEWAY_SESSION_USES <= 10       # the 12th or 13th call of a gateway session is refused


@hosted_only
def test_exit_per_pool_key(gateway, monkeypatch):
    assert fetch._proxy_for(fetch.SEARCH) == "gateway"
    assert fetch._proxy_for(fetch.SEARCH_FALLBACK) == RESI
    assert fetch._proxy_for(fetch.WEB) is None
    monkeypatch.setattr(fetch.config, "PROPWIRE_EXIT", "us")            # the exit before the gateway
    assert fetch._proxy_for(fetch.SEARCH) == RESI and fetch._pool_key(fetch.SEARCH) == fetch.SEARCH


@hosted_only
def test_a_gateway_mint_tries_the_safari_headers_first(gateway, monkeypatch):
    tried = []

    def mint_with(profile, proxy):
        tried.append((profile, proxy))
        raise fetch.PropwireBlocked("homepage HTTP 403")
    monkeypatch.setattr(fetch, "_mint_with", mint_with)
    for kind in (fetch.SEARCH, fetch.SEARCH_FALLBACK, fetch.WEB):
        with pytest.raises(fetch.PropwireBlocked):
            fetch._mint(kind)
    assert tried == [("safari17_0", "gateway"), ("chrome", "gateway"), ("chrome", RESI), ("safari17_0", RESI),
                     ("chrome", None), ("safari17_0", None)]


@hosted_only
def test_search_rides_the_gateway_and_a_session_serves_eight_calls(gateway):
    gateway.script([OK] * 8, [OK] * 2)
    for _ in range(10):
        assert fetch.fetch_property_search({"size": 1}) == {"ok": True}
    assert gateway.keys() == [fetch.SEARCH, fetch.SEARCH]   # no residential traffic while the gateway answers
    first, second = gateway.minted
    assert len(first.session.calls) == 8 and first.closed and not second.closed
    gateway.script([OK])
    assert fetch.fetch_autocomplete("aus", ["C"]) == {"ok": True}       # the WEB kind: its own session, own IP
    assert gateway.keys()[-1] == fetch.WEB and gateway.minted[-1].uses == {"use": 1}


@hosted_only
def test_one_refusal_retries_on_the_gateway_and_does_not_pause_it(gateway):
    gateway.script([CAPTCHA], [OK, OK])
    assert fetch.fetch_property_search({"size": 1}) == {"ok": True}
    assert gateway.keys() == [fetch.SEARCH, fetch.SEARCH] and gateway.minted[0].closed
    assert fetch._gateway["refusals"] == 0 and fetch._pool_key(fetch.SEARCH) == fetch.SEARCH
    fetch.fetch_property_search({"size": 1})
    assert len(gateway.minted) == 2


@hosted_only
def test_last_retry_rides_residential_and_two_refusals_in_a_row_pause_the_gateway(gateway):
    gateway.script([CAPTCHA], [CAPTCHA], [OK, OK, OK])
    assert fetch.fetch_property_search({"size": 1}) == {"ok": True}
    assert gateway.keys() == [fetch.SEARCH, fetch.SEARCH, fetch.SEARCH_FALLBACK]
    assert fetch._gateway["paused_until"] > time.monotonic()
    fetch.fetch_property_search({"size": 1})                # paused: every search call on the residential session
    fetch.fetch_property_search({"size": 1})
    assert len(gateway.minted) == 3 and len(gateway.minted[2].session.calls) == 3
    fetch._gateway["paused_until"] = time.monotonic() - 1   # the pause is over: the gateway again
    gateway.script([OK])
    fetch.fetch_property_search({"size": 1})
    assert gateway.keys()[-1] == fetch.SEARCH


@hosted_only
def test_a_refused_gateway_homepage_counts_as_a_refusal(gateway):
    real, state = gateway._mint_fn, {"n": 0}

    def mint(kind, hint=None):
        state["n"] += 1
        if kind == fetch.SEARCH:
            raise fetch.PropwireBlocked("homepage HTTP 403 (anti-bot)")
        return real(kind, hint)
    gateway._mint_fn = mint
    gateway.script([OK])
    assert fetch.fetch_property_search({"size": 1}) == {"ok": True}
    assert state["n"] == 3 and gateway.keys() == [fetch.SEARCH_FALLBACK]
    assert fetch._gateway["paused_until"] > time.monotonic()


@hosted_only
def test_api_gateway_errors_end_on_residential_without_a_pause(gateway):
    boom = RuntimeError("GatewayError: gateway 504")
    gateway.script([boom], [boom], [OK], [OK])
    assert fetch.fetch_property_search({"size": 1}) == {"ok": True}
    assert gateway.keys() == [fetch.SEARCH, fetch.SEARCH, fetch.SEARCH_FALLBACK]
    assert fetch._gateway["paused_until"] == 0.0 and fetch._gateway["refusals"] == 0    # no verdict on the exit
    fetch.fetch_property_search({"size": 1})
    assert gateway.keys()[-1] == fetch.SEARCH               # the next call starts on the gateway again


@hosted_only
def test_without_a_fallback_exit_every_search_attempt_rides_the_configured_exit(gateway, monkeypatch):
    monkeypatch.setattr(fetch.config, "PROPWIRE_FALLBACK_EXIT", None)
    gateway.script([CAPTCHA], [CAPTCHA], [OK])
    assert fetch.fetch_property_search({"size": 1}) == {"ok": True}
    assert gateway.keys() == [fetch.SEARCH] * 3 and fetch._gateway["paused_until"] == 0.0
    monkeypatch.setattr(fetch.config, "PROPWIRE_EXIT", "us")            # the residential exit alone, as before
    monkeypatch.setattr(fetch.config, "PROPWIRE_FALLBACK_EXIT", "us")
    gateway.clear()
    gateway.script([CAPTCHA], [CAPTCHA], [OK] * 12)
    for _ in range(10):
        fetch.fetch_property_search({"size": 1})
    assert gateway.keys()[3:] == [fetch.SEARCH] * 3 and fetch._gateway["paused_until"] == 0.0
    assert len(gateway.minted[-1].session.calls) == 10      # PROPWIRE_SESSION_USES bounds it, not the gateway's 8


@hosted_only
def test_a_gateway_session_serves_eight_calls_without_a_fallback_exit_too(gateway, monkeypatch):
    monkeypatch.setattr(fetch.config, "PROPWIRE_FALLBACK_EXIT", None)
    gateway.script([OK] * 8, [OK])
    for _ in range(9):
        assert fetch.fetch_property_search({"size": 1}) == {"ok": True}
    first, second = gateway.minted
    assert len(first.session.calls) == 8 and first.closed and not second.closed


@hosted_only
def test_web_calls_never_move_to_the_fallback_exit(gateway):
    gateway.script([CAPTCHA], [CAPTCHA], [CAPTCHA])
    with pytest.raises(fetch.PropwireBlocked):
        fetch.fetch_autocomplete("aus", ["C"])
    assert gateway.keys() == [fetch.WEB] * 3 and fetch._gateway["paused_until"] == 0.0
