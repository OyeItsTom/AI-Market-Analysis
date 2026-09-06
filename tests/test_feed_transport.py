"""Phase 9 transport: destination policy, redirects, and bounded bytes.

No test here opens a socket. A fake connection is injected so the real policy --
pre-resolution, the post-connect peer check, redirect refusal, retry behaviour
and the decompression ceiling -- is exercised deterministically.

The measurement behind the ceiling: a 28 KB gzip response was observed expanding
to 11.6 MB, which is why the limit is applied to decompressed output rather than
to bytes on the wire.
"""

from __future__ import annotations

import gzip
import zlib

import pytest

from src.feeds.models import MAX_BODY_BYTES
from src.feeds.transport import (
    MAX_RETRIES,
    USER_AGENT,
    NotModified,
    PayloadTooLarge,
    RateLimited,
    RedirectRefused,
    TransportError,
    bounded_decompress,
    bounded_read,
    fetch_feed,
)
from src.feeds.validation import UnsafeDestination, UrlValidationError

BODY = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>T</title></feed>'


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self._body = body
        self._offset = 0
        self._headers = headers or {}

    def read(self, size=-1):
        if size is None or size < 0:
            chunk = self._body[self._offset:]
            self._offset = len(self._body)
            return chunk
        chunk = self._body[self._offset:self._offset + size]
        self._offset += size
        return chunk

    def getheader(self, name, default=None):
        return self._headers.get(name, default)


class FakeSocket:
    def __init__(self, peer):
        self._peer = peer

    def getpeername(self):
        return (self._peer, 443)


class FakeConnection:
    """A connection that records what was sent and answers with a canned response."""

    def __init__(self, response, peer="93.184.216.34", fail_with=None):
        self._response = response
        self.sock = FakeSocket(peer)
        self.requests = []
        self._fail_with = fail_with
        self.closed = False

    def connect(self):
        return None

    def request(self, method, path, headers=None):
        if self._fail_with is not None:
            raise self._fail_with
        self.requests.append((method, path, dict(headers or {})))

    def getresponse(self):
        return self._response

    def close(self):
        self.closed = True


def factory_for(connection):
    def factory(host, port, timeout, context):
        return connection

    return factory


def public_dns(monkeypatch, address="93.184.216.34"):
    import src.feeds.validation as validation

    monkeypatch.setattr(
        validation.socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", (address, 443))],
    )


def fetch(connection, monkeypatch, url="https://example.com/feed.xml", **kwargs):
    public_dns(monkeypatch)
    return fetch_feed(
        url,
        connection_factory=factory_for(connection),
        sleep=lambda _: None,
        now=lambda: 0.0,
        **kwargs,
    )


# -- the happy path ------------------------------------------------------


def test_a_two_hundred_returns_the_body_and_validators(monkeypatch):
    connection = FakeConnection(
        FakeResponse(200, BODY, {"ETag": 'W/"abc"', "Last-Modified": "Sat, 05 Sep 2026 10:00:00 GMT"})
    )
    result = fetch(connection, monkeypatch)
    assert result.body == BODY
    assert result.etag == 'W/"abc"'
    assert result.last_modified == "Sat, 05 Sep 2026 10:00:00 GMT"


def test_only_the_minimum_headers_are_sent(monkeypatch):
    """A feed server never needs cookies, referrers or an identity from us."""
    connection = FakeConnection(FakeResponse(200, BODY))
    fetch(connection, monkeypatch)
    _, _, headers = connection.requests[0]
    assert headers["User-Agent"] == USER_AGENT
    assert set(headers) <= {"User-Agent", "Accept-Encoding", "Accept"}
    for forbidden in ("Cookie", "Authorization", "Referer", "From"):
        assert forbidden not in headers


def test_validators_are_sent_as_conditional_headers(monkeypatch):
    connection = FakeConnection(FakeResponse(200, BODY))
    fetch(connection, monkeypatch, etag='W/"abc"', last_modified="Sat, 05 Sep 2026 10:00:00 GMT")
    _, _, headers = connection.requests[0]
    assert headers["If-None-Match"] == 'W/"abc"'
    assert headers["If-Modified-Since"] == "Sat, 05 Sep 2026 10:00:00 GMT"


def test_the_connection_is_closed_even_on_success(monkeypatch):
    connection = FakeConnection(FakeResponse(200, BODY))
    fetch(connection, monkeypatch)
    assert connection.closed


# -- destination policy --------------------------------------------------


def test_a_host_resolving_to_a_private_address_is_refused_before_connecting(monkeypatch):
    public_dns(monkeypatch, "10.0.0.5")
    connection = FakeConnection(FakeResponse(200, BODY))
    with pytest.raises(UnsafeDestination):
        fetch_feed(
            "https://internal.example.com/feed.xml",
            connection_factory=factory_for(connection),
            sleep=lambda _: None,
            now=lambda: 0.0,
        )
    assert not connection.requests, "no request may be sent to a refused destination"


@pytest.mark.parametrize("peer", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "::1"])
def test_the_actual_peer_is_checked_after_connecting(monkeypatch, peer):
    """Closes the DNS rebinding window that pre-resolution alone leaves open.

    Resolution returns a public address; the socket lands somewhere private. The
    check that matters is the one on the address we are really talking to.
    """
    connection = FakeConnection(FakeResponse(200, BODY), peer=peer)
    with pytest.raises(UnsafeDestination):
        fetch(connection, monkeypatch)
    assert not connection.requests, "no request may be sent after a bad peer check"


def test_an_unsafe_destination_is_never_retried(monkeypatch):
    connection = FakeConnection(FakeResponse(200, BODY), peer="127.0.0.1")
    with pytest.raises(UnsafeDestination):
        fetch(connection, monkeypatch)


def test_a_plain_http_url_never_reaches_the_transport(monkeypatch):
    connection = FakeConnection(FakeResponse(200, BODY))
    with pytest.raises(UrlValidationError):
        fetch(connection, monkeypatch, url="http://example.com/feed.xml")
    assert not connection.requests


# -- redirects -----------------------------------------------------------


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_refused_and_never_followed(monkeypatch, status):
    """Not following is what closes redirect-to-private-address, rather than mitigating it."""
    connection = FakeConnection(
        FakeResponse(status, b"", {"Location": "https://169.254.169.254/latest/meta-data/"})
    )
    with pytest.raises(RedirectRefused) as caught:
        fetch(connection, monkeypatch)
    assert "redirect" in str(caught.value).lower()
    # A settled answer, not a transient one: exactly one attempt.
    assert len(connection.requests) == 1


def test_the_refused_location_is_reported_for_diagnosis(monkeypatch):
    connection = FakeConnection(
        FakeResponse(302, b"", {"Location": "https://elsewhere.example.com/feed.xml"})
    )
    with pytest.raises(RedirectRefused) as caught:
        fetch(connection, monkeypatch)
    assert "elsewhere.example.com" in str(caught.value)
    assert caught.value.location == "https://elsewhere.example.com/feed.xml"


# -- status handling -----------------------------------------------------


def test_a_three_oh_four_is_raised_as_not_modified_carrying_its_validators(monkeypatch):
    connection = FakeConnection(FakeResponse(304, b"", {"ETag": 'W/"same"'}))
    with pytest.raises(NotModified) as caught:
        fetch(connection, monkeypatch)
    assert caught.value.etag == 'W/"same"'


@pytest.mark.parametrize("status", [403, 429])
def test_being_asked_to_stop_is_not_retried_around(monkeypatch, status):
    connection = FakeConnection(FakeResponse(status, b""))
    with pytest.raises(RateLimited):
        fetch(connection, monkeypatch)
    assert len(connection.requests) == 1, "a rate limit must not be retried"


@pytest.mark.parametrize("status", [400, 404, 418, 500, 503])
def test_an_unexpected_status_is_a_transport_error(monkeypatch, status):
    connection = FakeConnection(FakeResponse(status, b""))
    with pytest.raises(TransportError):
        fetch(connection, monkeypatch)


def test_a_connection_failure_is_retried_then_reported(monkeypatch):
    connection = FakeConnection(FakeResponse(200, BODY), fail_with=OSError("reset"))
    with pytest.raises(TransportError):
        fetch(connection, monkeypatch)


# -- bounded bytes -------------------------------------------------------


def test_reading_stops_at_the_limit_rather_than_after_it():
    class Endless:
        def read(self, size):
            return b"x" * size

    with pytest.raises(PayloadTooLarge):
        bounded_read(Endless(), limit=4096)


def test_a_body_under_the_limit_is_returned_whole():
    class Once:
        def __init__(self):
            self.done = False

        def read(self, size):
            if self.done:
                return b""
            self.done = True
            return b"hello"

    assert bounded_read(Once(), limit=4096) == b"hello"


def test_an_uncompressed_body_over_the_limit_is_refused():
    with pytest.raises(PayloadTooLarge):
        bounded_decompress(b"x" * 100, "identity", limit=10)


def test_a_gzip_bomb_is_stopped_while_inflating_not_after():
    """The wire bytes are tiny; the output is not. The limit is on the output."""
    payload = gzip.compress(b"\0" * (12 * 1024 * 1024))
    assert len(payload) < 64 * 1024, "the test payload must be small on the wire"
    with pytest.raises(PayloadTooLarge):
        bounded_decompress(payload, "gzip", limit=MAX_BODY_BYTES)


def test_a_deflate_bomb_is_stopped_too():
    payload = zlib.compress(b"\0" * (12 * 1024 * 1024))
    with pytest.raises(PayloadTooLarge):
        bounded_decompress(payload, "deflate", limit=MAX_BODY_BYTES)


def test_ordinary_gzip_still_works():
    assert bounded_decompress(gzip.compress(BODY), "gzip", limit=MAX_BODY_BYTES) == BODY


def test_an_unsupported_encoding_is_refused_rather_than_guessed():
    with pytest.raises(TransportError):
        bounded_decompress(b"...", "br", limit=MAX_BODY_BYTES)


def test_an_oversized_response_body_is_refused_end_to_end(monkeypatch):
    connection = FakeConnection(FakeResponse(200, b"x" * (MAX_BODY_BYTES + 1024)))
    with pytest.raises(PayloadTooLarge):
        fetch(connection, monkeypatch)


# -- the peer check must fail closed -------------------------------------


class PeerlessConnection(FakeConnection):
    """A connection whose socket exposes no readable peer."""

    def __init__(self, response, sock):
        super().__init__(response)
        self.sock = sock


class _RaisingSocket:
    def getpeername(self):
        raise OSError("cannot determine peer")


class _EmptySocket:
    def getpeername(self):
        return ()


@pytest.mark.parametrize(
    "sock, label",
    [(None, "no socket"), (_RaisingSocket(), "getpeername raises"),
     (_EmptySocket(), "empty peer tuple")],
)
def test_an_undeterminable_peer_is_refused_rather_than_waved_through(monkeypatch, sock, label):
    """"I cannot tell where this socket goes" must mean stop.

    The peer check is the only thing between a rebinding DNS answer and the
    request. Treating an unreadable peer as acceptable would silently disable
    it -- the same fail-open that :func:`is_unsafe_address` refuses for an
    unparseable address.
    """
    connection = PeerlessConnection(FakeResponse(200, BODY), sock)
    with pytest.raises(UnsafeDestination):
        fetch(connection, monkeypatch)
    assert not connection.requests, f"a request was sent despite {label}"


def test_a_readable_public_peer_still_succeeds(monkeypatch):
    """The strict check must not break the ordinary path."""
    connection = FakeConnection(FakeResponse(200, BODY), peer="93.184.216.34")
    assert fetch(connection, monkeypatch).body == BODY


# -- the body must be read incrementally, not slurped --------------------


class _UnboundedReadForbidden:
    """A response that fails the test if asked for the whole body at once."""

    status = 200

    def __init__(self, total):
        self.remaining = total
        self.max_request = 0

    def read(self, size=-1):
        if size is None or size < 0:
            raise AssertionError("the transport asked for an unbounded read")
        self.max_request = max(self.max_request, size)
        chunk = b"x" * min(size, self.remaining)
        self.remaining -= len(chunk)
        return chunk

    def getheader(self, name, default=None):
        return default


def test_the_transport_never_asks_for_the_whole_body_at_once(monkeypatch):
    """A size check after ``response.read()`` is too late: the bytes are already
    in memory, which is the thing the limit exists to prevent.

    An earlier version of this suite only asserted the final ``PayloadTooLarge``,
    which the decompression guard raises anyway -- so replacing the bounded read
    with ``response.read()`` went undetected.
    """
    response = _UnboundedReadForbidden(MAX_BODY_BYTES * 4)
    connection = FakeConnection(response)
    with pytest.raises(PayloadTooLarge):
        fetch(connection, monkeypatch)
    assert response.max_request <= MAX_BODY_BYTES + 1


def test_an_endless_response_terminates_instead_of_exhausting_memory(monkeypatch):
    response = _UnboundedReadForbidden(10**9)
    with pytest.raises(PayloadTooLarge):
        fetch(FakeConnection(response), monkeypatch)
