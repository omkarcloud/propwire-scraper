"""Propwire transport: plain curl_cffi with browser-impersonated TLS, no
browser. Every surface is JSON the site's own React app calls; a session
first GETs the homepage once, which mints what the calls need:

  * the guest JWT in the Inertia page's `data-page` props (`token`, HS256,
    valid 2 h) — the Bearer every api.propwire.com call and the people
    routes want. It is bound to the session that minted it (a token replayed
    from another exit draws the DataDome captcha), so it is never shared.
  * the `XSRF-TOKEN` cookie, echoed as the X-XSRF-Token header on the
    propwire.com POSTs (Laravel's CSRF check: 419 otherwise), read from the
    jar right before each request because Laravel rotates it.
  * the `datadome` cookie, which api.propwire.com/api/property_search
    requires (a captcha 403 without it).

Two session kinds (config's "--- Propwire ---" block, pod probe
2026-10-31), each a key of ONE process-wide identity_pool.Pool in exclusive
mode (since 2026-11-09): a request borrows a session of its kind for one
call and hands it back, so the next request on any of the pod's 64 threads
reuses its homepage-minted guest JWT instead of minting its own (before,
each thread minted one of each kind). A session is retired on any
retryable failure (`dead`, so the retry mints on a fresh exit), after
PROPWIRE_SESSION_USES calls, or at PROPWIRE_SESSION_TTL (the JWT's life):

  * WEB     propwire.com JSON (property-details, people-search, profiles,
            local_markets) and api.propwire.com/api/auto_complete — open
            from the pod's own IP; config.PROPWIRE_WEB_EXIT ("direct").
  * SEARCH  api.propwire.com/api/property_search — DataDome refuses the
            pod's own IP and every datacenter exit for every curl TLS
            profile, and passes 4 of 6 US residential exits. Since
            2026-11-11 the session rides the shared gateway exit
            (config.PROPWIRE_EXIT = "gateway", exit_gateway.py: every request
            leaves from a fresh gateway address; the guest JWT and the datadome
            cookie the homepage minted from one address are honoured from
            the next ones, numbers in config.py). The residential exit
            stays behind it (config.PROPWIRE_FALLBACK_EXIT = "us", pool key
            SEARCH_FALLBACK, one sticky exit per session as before): the
            LAST retry of a call rides it, and after
            PROPWIRE_GATEWAY_REFUSALS refusals in a row on the gateway
            every search call does for PROPWIRE_GATEWAY_PAUSE seconds.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  PropwireUpstreamError  transport failure / 5xx                — retryable
  PropwireBlocked        DataDome 403 / 401 token / 419 CSRF /  — retryable on a
                         429 / non-JSON                            fresh session
  PropwireBadRequest     400 / 422 validation, a membership-only — never retried
                         lead type (403 *Forbidden)
  PropwireNotFound       404 / an empty record                   — never retried
"""
import json
import os
import sys
import threading
import time
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
import identity_pool
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from propwire import parsers
from propwire.refs import API, SITE

# curl TLS profiles tried in order on the SAME exit when the homepage is
# refused (owner rule: try another fingerprint before blaming the IP). In
# the pod chrome and safari17_0 pass and fail on the same exits (probe
# 2026-10-31); from a home ISP on 2026-11-02 DataDome refused chrome and
# served safari17_0. chrome136 / edge101 / firefox135 are refused outright.
IMPERSONATE_PROFILES = ("chrome", "safari17_0")
IMPERSONATE = IMPERSONATE_PROFILES[0]
# Through the gateway exit the TLS is the gateway's for every profile; what a profile
# changes there is the header set, and DataDome refuses chrome's at the
# homepage (403 on 9 of 9 mints) and serves safari17_0's (200 on 9 of 9),
# 2026-11-11. So a gateway session tries safari17_0 first.
GATEWAY_PROFILES = ("safari17_0", "chrome")
PAGE_TIMEOUT = 30      # the homepage is ~240 KB
JSON_TIMEOUT = 30

# pool keys: SEARCH_FALLBACK = property_search sessions on the exit behind the gateway
WEB, SEARCH, SEARCH_FALLBACK = "web", "search", "search-fallback"

# membership-only lead types: the API's own refusal codes (never retried)
_MEMBERSHIP_ERRORS = ("PremiumLeadsForbidden", "NewPremiumForbidden", "GoldForbidden",
                      "CLPForbidden", "LLPForbidden")


class PropwireUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class PropwireBlocked(PropwireUpstreamError, Blocked):
    """DataDome / token / CSRF refusal — retryable on a fresh session."""


class PropwireBadRequest(BadRequest):
    """The API rejected the parameters — never retried."""


class PropwireNotFound(NotFound):
    """Unknown property / profile — never retried."""


# ---- pooled sessions -------------------------------------------------------------

class _Session(identity_pool.Identity):
    """One warmed curl session (`session`) with the guest JWT (`token`) it
    minted; the pool (identity_pool.Identity) keeps budget / age / refusal.
    The curl handle is used by one request at a time (exclusive lending)."""

    def __init__(self, session, token, proxy):
        super().__init__(exit=proxy)
        self.session, self.token, self.proxy = session, token, proxy
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.session.close()
        except Exception:
            pass


def _proxy_for(kind):
    if kind == SEARCH_FALLBACK:
        return config.propwire_proxy(fallback=True)
    return config.propwire_proxy() if kind == SEARCH else config.propwire_web_proxy()


def _mint(kind, hint=None):
    """The pool's mint: a new curl session on a fresh exit, warmed on the
    homepage. A refused homepage tries the next TLS profile on the same exit
    before raising (the pool passes the error through; nothing is lent)."""
    proxy = _proxy_for(kind)
    blocked = None
    for profile in (GATEWAY_PROFILES if config.gateway_exit(proxy) else IMPERSONATE_PROFILES):
        try:
            return _mint_with(profile, proxy)
        except PropwireBlocked as e:
            blocked = e
    raise blocked


def _mint_with(profile, proxy):
    # None, a proxy URL, or the gateway exit ("gateway")
    sess = egress.new_session(proxy, impersonate=profile, use_thread_local_curl=False)
    headers = {
        "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "accept-language": egress.accept_language(proxy),
        "upgrade-insecure-requests": "1",
    }
    try:
        resp = sess.get(SITE + "/", headers=headers, timeout=PAGE_TIMEOUT)
    except Exception as e:
        sess.close()
        raise PropwireUpstreamError(f"homepage request failed: {type(e).__name__}: {e}")
    if resp.status_code in (401, 403, 429, 503):
        sess.close()
        raise PropwireBlocked(f"homepage HTTP {resp.status_code} (anti-bot) on this exit ({profile})")
    if resp.status_code != 200:
        sess.close()
        raise PropwireUpstreamError(f"homepage HTTP {resp.status_code}")
    try:
        token = parsers.guest_token(resp.text)
    except ValueError as e:
        sess.close()
        raise PropwireBlocked(f"homepage carried no guest token: {e}")
    sess.headers["accept-language"] = headers["accept-language"]
    return _Session(sess, token, proxy)


# Exclusive lending per kind (WEB / SEARCH): a session owns its curl handle,
# so one request at a time; the JWT's life is the pool's max_age.
_sessions = identity_pool.Pool(
    "propwire", _mint, mode="exclusive",
    budget=lambda: config.PROPWIRE_SESSION_USES,
    max_age=lambda: config.PROPWIRE_SESSION_TTL,
    on_retire=lambda ident, reason: ident.close())


# ---- the gateway in front of the residential search exit ---------------------------
# property_search rides config.PROPWIRE_EXIT (the gateway exit) with
# config.PROPWIRE_FALLBACK_EXIT (a sticky US residential exit) behind it.
# The gateway's exit changes every request, so ONE refusal there is no
# verdict on it (the retry leaves from other addresses); a run of them is:
# then the gateway is paused and every search call rides the residential
# exit, as all of them did before 2026-11-11. A gateway session is retired
# after PROPWIRE_GATEWAY_SESSION_USES search calls: DataDome answers the
# captcha 403 once one session (its datadome cookie) has asked from about a
# dozen addresses (3 of 3 sessions: 11, 12 and 11 calls served, the next
# one refused, 2026-11-11), which a sticky residential exit never shows it.
_local = threading.local()          # .last_retry: this thread's call is on its last retry
_gateway = {"refusals": 0, "paused_until": 0.0}
_gateway_lock = threading.Lock()


def _gateway_in_front():
    """True when property_search has the gateway in front of another exit."""
    return bool(config.gateway_exit(config.PROPWIRE_EXIT) and config.PROPWIRE_FALLBACK_EXIT)


def _pool_key(kind):
    """The pool key a call of `kind` borrows from now: a property_search
    call moves to SEARCH_FALLBACK for its last retry and while the gateway
    is paused."""
    if kind == SEARCH and _gateway_in_front() and (
            getattr(_local, "last_retry", False) or time.monotonic() < _gateway["paused_until"]):
        return SEARCH_FALLBACK
    return kind


def _note_gateway(refused):
    """Count a property_search answer through the gateway: a success clears
    the run, the PROPWIRE_GATEWAY_REFUSALS-th refusal in a row pauses the
    gateway for PROPWIRE_GATEWAY_PAUSE seconds."""
    with _gateway_lock:
        if not refused:
            _gateway["refusals"] = 0
            return
        _gateway["refusals"] += 1
        if _gateway["refusals"] < max(1, int(config.PROPWIRE_GATEWAY_REFUSALS)):
            return
        _gateway["refusals"] = 0
        _gateway["paused_until"] = time.monotonic() + config.PROPWIRE_GATEWAY_PAUSE
    print(f"propwire: the gateway exit was refused {config.PROPWIRE_GATEWAY_REFUSALS} times in a row; "
          f"property_search rides {config.PROPWIRE_FALLBACK_EXIT} for {config.PROPWIRE_GATEWAY_PAUSE} s")


def _on_session(kind, fn):
    """fn(state) on a borrowed session of `kind`. A retryable failure
    (PropwireUpstreamError, so Blocked too) marks it dead: retired on
    give-back, and the retry mints a new one (on a fresh exit for SEARCH)."""
    key = _pool_key(kind)
    on_gateway = key == SEARCH and bool(config.gateway_exit(config.PROPWIRE_EXIT))  # a property_search call through the gateway
    counted = on_gateway and _gateway_in_front()        # ... whose refusals pause it (an exit sits behind it)
    try:
        state = _sessions.borrow(key)
    except PropwireBlocked:
        if counted:
            _note_gateway(refused=True)                 # the homepage mint was refused
        raise
    try:
        result = fn(state)
        if on_gateway and state.uses.get("use", 0) >= max(1, int(config.PROPWIRE_GATEWAY_SESSION_USES)):
            state.expires_at = time.time()              # spent: give_back retires it, the next call mints
    except PropwireBlocked:
        state.dead = True
        if counted:
            _note_gateway(refused=True)
        raise
    except PropwireUpstreamError:
        state.dead = True
        raise
    finally:
        _sessions.give_back(state)
    if counted:
        _note_gateway(refused=False)
    return result


def _cookie(sess, name):
    """A cookie's current value from the jar (curl_cffi 0.16 and 0.17 expose
    the jar differently; walking it works on both)."""
    value = None
    try:
        for cookie in (getattr(sess.cookies, "jar", None) or sess.cookies):
            if getattr(cookie, "name", None) == name:
                value = cookie.value
    except Exception:
        value = None
    return unquote(value) if value else ""


def _retrying(fn):
    """Run fn() under the shared retry policy: PropwireUpstreamError (and so
    Blocked) retries — the failed call already retired its session
    (_on_session), or its mint failed and nothing was lent; NotFound /
    BadRequest surface at once. The last retry is flagged (_local.last_retry)
    so a property_search call the gateway keeps failing — refused, or the
    gateway's own errors — ends on the residential exit (_pool_key)."""
    last = None
    try:
        for attempt in range(1, config.MAX_RETRIES + 1):
            _local.last_retry = 1 < attempt == config.MAX_RETRIES
            try:
                return fn()
            except PropwireUpstreamError as e:
                last = e
                if attempt < config.MAX_RETRIES:
                    time.sleep(config.RETRY_BACKOFF * attempt)
        raise last
    finally:
        _local.last_retry = False


# ---- the response taxonomy --------------------------------------------------------

def _json_or_none(resp):
    try:
        return resp.json()
    except Exception:
        return None


def _message(payload, fallback):
    if isinstance(payload, dict):
        for key in ("message", "error"):
            if isinstance(payload.get(key), str) and payload[key]:
                text = payload[key]
                details = payload.get("details") or payload.get("errors")
                if details:
                    text += f": {json.dumps(details, ensure_ascii=False)[:300]}"
                return text
    return fallback


def _classify(resp, label):
    """HTTP status -> the taxonomy; returns the parsed JSON on 200."""
    status = resp.status_code
    payload = _json_or_none(resp)
    if status == 200:
        if payload is None:
            raise PropwireBlocked(f"non-JSON answer for {label}: {resp.text[:120]!r}")
        return payload
    if status == 404:
        raise PropwireNotFound(_message(payload, f"{label} not found"))
    if status in (400, 422):
        raise PropwireBadRequest(_message(payload, f"HTTP {status} for {label}"))
    if status == 403:
        error = payload.get("error") if isinstance(payload, dict) else None
        if error in _MEMBERSHIP_ERRORS:
            raise PropwireBadRequest(_message(payload, "this lead type needs a paid Propwire membership"))
        raise PropwireBlocked(f"HTTP 403 for {label} (anti-bot) on this exit")
    if status in (401, 419, 429, 503):
        raise PropwireBlocked(f"HTTP {status} for {label}")
    raise PropwireUpstreamError(f"HTTP {status} for {label}")


def _api_headers(state):
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "origin": SITE,
        "referer": SITE + "/",
        "authorization": f"Bearer {state.token}",
        "x-api-key": config.PROPWIRE_FRONTEND_KEY,
    }


def _web_headers(state):
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "referer": SITE + "/search",
        "x-requested-with": "XMLHttpRequest",
        "authorization": f"Bearer {state.token}",
        "x-xsrf-token": _cookie(state.session, "XSRF-TOKEN"),
    }


def _post(kind, url, body, label, headers_for):
    def once(state):
        try:
            resp = state.session.post(url, json=body, headers=headers_for(state), timeout=JSON_TIMEOUT)
        except Exception as e:
            raise PropwireUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
        return _classify(resp, label)
    return _retrying(lambda: _on_session(kind, once))


def _get(kind, url, label, headers_for, params=None):
    def once(state):
        try:
            resp = state.session.get(url, headers=headers_for(state), params=params, timeout=JSON_TIMEOUT)
        except Exception as e:
            raise PropwireUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
        return _classify(resp, label)
    return _retrying(lambda: _on_session(kind, once))


# ---- the surfaces ---------------------------------------------------------------------

def fetch_property_search(body):
    """POST api.propwire.com/api/property_search (the SEARCH session). Body
    = the site's own payload: locations / lead_type / ranges / sort / size /
    result_index / count / ids. Returns the raw payload."""
    return _post(SEARCH, API + "/property_search", body, "property search", _api_headers)


def fetch_autocomplete(term, types):
    """POST api/auto_complete: {search, search_types: [C, Z, N, T, A]}."""
    return _post(WEB, API + "/auto_complete", {"search": term, "search_types": list(types)},
                 "autocomplete", _api_headers)


def fetch_property_details(property_id):
    """GET propwire.com/property-details/<id> (JSON). Unknown ids answer 404
    "Property not found."; an empty `response` is treated the same."""
    payload = _get(WEB, f"{SITE}/property-details/{int(property_id)}", f"property {property_id}", _web_headers)
    rows = payload.get("response") if isinstance(payload, dict) else None
    if not rows:
        raise PropwireNotFound(f"property {property_id} not found")
    return payload


def fetch_people_search(body):
    """POST propwire.com/people-search (one people_lead_type, state required)."""
    return _post(WEB, SITE + "/people-search", body, "people search", _web_headers)


def fetch_people_count(body):
    """POST propwire.com/people-search/count -> {"result_count": N}."""
    return _post(WEB, SITE + "/people-search/count", body, "people count", _web_headers)


def fetch_agent_profile(person_id):
    """GET propwire.com/people/agents/<hash>; 404 "No such profile found."."""
    return _get(WEB, f"{SITE}/people/agents/{person_id}", f"agent {person_id}", _web_headers)


def fetch_cash_buyer_profile(person_id):
    """GET propwire.com/people/cash-buyers/<hash>."""
    return _get(WEB, f"{SITE}/people/cash-buyers/{person_id}", f"cash buyer {person_id}", _web_headers)


def fetch_market_stats(place, summary):
    """POST propwire.com/local_markets/search: {zip} | {city, state} |
    {county, state} + summary (true = the market cards, false = the place
    record with demographics and monthly trend rows)."""
    return _post(WEB, SITE + "/local_markets/search", {**place, "summary": bool(summary)},
                 "market stats", _web_headers)
