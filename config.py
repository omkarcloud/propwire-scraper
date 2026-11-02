"""Configuration for the Propwire Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT             port the API listens on (default 8000)
    PROPWIRE_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                     (default: none — direct). Propwire sits behind DataDome:
                     a home connection is usually served, but cloud servers
                     and datacenter proxies are refused on the property
                     search. On a server, or if you start seeing 502
                     "blocked" errors, set a US residential proxy here.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request). A block
# drops the session, so the retry starts from a fresh homepage visit.
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# The public key propwire.com's own web app sends as x-api-key.
PROPWIRE_FRONTEND_KEY = "b697fa27-fe7a-4f86-b3d8-024d57804125"

# A session re-visits the homepage for a new guest token before the token's
# 2-hour expiry.
PROPWIRE_SESSION_TTL = 100 * 60

PROPWIRE_PROXY = os.environ.get("PROPWIRE_PROXY") or None


def propwire_proxy():
    """The proxy for one property-search session (None = direct)."""
    return os.environ.get("PROPWIRE_PROXY") or None


def propwire_web_proxy():
    """The proxy for one session on every other surface (None = direct)."""
    return os.environ.get("PROPWIRE_PROXY") or None
