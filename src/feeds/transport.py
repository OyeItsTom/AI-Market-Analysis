"""HTTPS fetching for configured feeds, with the destination actually verified.

Feed URLs come from a local configuration file rather than being hard-coded, so
this module is the difference between "a research tool" and "an SSRF gadget
pointed at your own network". Four rules do that work.

**The address we connect to is the one we check.** Resolving a host and then
letting the stack reconnect leaves a window where the second lookup returns
something private -- classic DNS rebinding. So every resolved address is
validated *and*, after the socket is up, the real peer from
``getpeername()`` is validated again. TLS is untouched throughout: certificate
verification and SNI use the real hostname, and nothing is swapped for a raw IP.

**No redirects.** ``HTTPSConnection`` does not follow them, so a ``3xx`` is a
classified failure. ``Location`` is recorded for diagnosis and never fetched --
which is what closes redirect-to-private-address rather than mitigating it.

**Bounded bytes, after decompression.** A 28 KB gzip response was measured
expanding to 11.6 MB, so a cap on wire bytes would be measuring the wrong
thing. Reads are chunked with a running limit and decompression is bounded by
the same limit, both aborting the moment it is passed.

**Conditional requests are an optimisation only.** A ``304`` means the source
says its representation is unchanged. It is not evidence about the world, and
it creates no records.
"""

from __future__ import annotations

import http.client
import ssl
import time
import zlib
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from .models import MAX_BODY_BYTES, FeedError
from .validation import UnsafeDestination, is_unsafe_address, resolve_safely, validate_url

#: Conservative and per-source. Feeds are small and nothing here needs speed.
TIMEOUT_SECONDS = 20
MAX_RETRIES = 2
REQUESTS_PER_SECOND = 1.0

#: Only these are sent; a feed server never needs anything else from us.
USER_AGENT = "AI-Market-Analysis/0.9 (local research tool)"


class TransportError(FeedError):
    """A feed could not be fetched."""


class PayloadTooLarge(TransportError):
    """The body exceeded the byte limit, measured after decompression."""


class RedirectRefused(TransportError):
    """The source redirected. Deliberately not followed, and never retried.

    Distinct from a generic failure so it is excluded from the retry loop: a
    redirect is a settled answer, not a transient one. Retrying would re-request
    a redirecting endpoint three times and, worse, bury the ``Location`` behind
    a generic "failed after 3 attempts" -- losing the one detail that explains
    why the feed did not load.
    """

    def __init__(self, status: int, location: str) -> None:
        super().__init__(
            f"the source redirected ({status}); redirects are not followed. "
            f"Location was {location[:200]!r}"
        )
        self.status = status
        self.location = location


class NotModified(Exception):
    """The source answered 304. Not an error, and not a record."""

    def __init__(self, etag: str | None, last_modified: str | None) -> None:
        super().__init__("not modified")
        self.etag = etag
        self.last_modified = last_modified


@dataclass(frozen=True)
class FetchResult:
    """A successful 200 response, already bounded and decompressed."""

    body: bytes
    etag: str | None = None
    last_modified: str | None = None
    peer_address: str = ""


#: ``(host, port, timeout, context) -> connection``. Injected so tests exercise
#: the real policy -- peer checks, limits, retries -- without a network.
ConnectionFactory = Callable[..., http.client.HTTPSConnection]

_LAST_REQUEST: list[float] = [0.0]


def _throttle(now: Callable[[], float], sleep: Callable[[float], None]) -> None:
    minimum_gap = 1.0 / REQUESTS_PER_SECOND
    elapsed = now() - _LAST_REQUEST[0]
    if 0 <= elapsed < minimum_gap:
        sleep(minimum_gap - elapsed)
    _LAST_REQUEST[0] = now()


def bounded_read(stream, limit: int = MAX_BODY_BYTES) -> bytes:
    """Read at most ``limit`` bytes, stopping as data arrives.

    Never ``stream.read()`` with no argument followed by a length check: by then
    the oversized body is already in memory, which is the thing the limit exists
    to prevent.
    """
    chunks = bytearray()
    while True:
        want = min(65536, limit - len(chunks) + 1)
        if want <= 0:
            break
        chunk = stream.read(want)
        if not chunk:
            return bytes(chunks)
        chunks += chunk
        if len(chunks) > limit:
            raise PayloadTooLarge(f"response exceeds {limit} bytes")
    raise PayloadTooLarge(f"response exceeds {limit} bytes")


def bounded_decompress(raw: bytes, encoding: str, limit: int = MAX_BODY_BYTES) -> bytes:
    """Decompress with a hard ceiling on the *output*.

    ``decompressobj`` is used rather than ``gzip.decompress`` because it accepts
    a per-call ``max_length``, so a compression bomb is stopped while inflating
    instead of after.
    """
    encoding = (encoding or "").lower().strip()
    if encoding in ("", "identity"):
        if len(raw) > limit:
            raise PayloadTooLarge(f"body exceeds {limit} bytes")
        return raw
    if encoding == "gzip":
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decompressor = zlib.decompressobj()
    else:
        raise TransportError(f"unsupported content encoding {encoding!r}")

    out = bytearray()
    for index in range(0, len(raw), 65536):
        out += decompressor.decompress(raw[index:index + 65536], limit - len(out) + 1)
        if len(out) > limit:
            raise PayloadTooLarge(
                f"decompressed body exceeds {limit} bytes "
                f"(from {len(raw)} compressed bytes)"
            )
    return bytes(out)


def _default_connection(host: str, port: int, timeout: int, context: ssl.SSLContext):
    return http.client.HTTPSConnection(host, port, timeout=timeout, context=context)


def _ssl_context() -> ssl.SSLContext:
    """A normal verifying context. Verification is never relaxed."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover - certifi is pinned
        return ssl.create_default_context()


def fetch_feed(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    connection_factory: ConnectionFactory | None = None,
    sleep: Callable[[float], None] | None = None,
    now: Callable[[], float] | None = None,
    limit: int = MAX_BODY_BYTES,
) -> FetchResult:
    """Fetch one configured feed URL under the full destination policy.

    Raises :class:`NotModified` on 304, :class:`UnsafeDestination` when the host
    or the actual peer is forbidden, :class:`PayloadTooLarge` past the limit, and
    :class:`TransportError` for everything else.
    """
    url = validate_url(url, label="feed url")
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or 443
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    # Pre-connect: refuse a host that resolves anywhere forbidden.
    resolve_safely(host, port)

    sleep = sleep or time.sleep
    now = now or time.monotonic
    connect = connection_factory or _default_connection
    context = _ssl_context()

    _throttle(now, sleep)

    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        connection = None
        try:
            connection = connect(host, port, TIMEOUT_SECONDS, context)
            connection.connect()

            # Post-connect: the address we are actually talking to. This is what
            # closes the rebinding window that pre-resolution alone leaves open.
            #
            # An undeterminable peer is refused, not waved through. This check is
            # the only thing standing between a rebinding DNS answer and the
            # request, so "I could not tell where this socket goes" has to mean
            # stop -- exactly as an unparseable address does in
            # :func:`is_unsafe_address`.
            peer = _peer_address(connection)
            if peer is None:
                raise UnsafeDestination(
                    f"could not determine the address {host!r} is connected to; "
                    "refusing to send a request to an unverified destination"
                )
            if is_unsafe_address(peer):
                raise UnsafeDestination(
                    f"{host!r} connected to {peer}, which is not a permitted destination"
                )

            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            status = response.status

            if status == 304:
                raise NotModified(response.getheader("ETag"), response.getheader("Last-Modified"))
            if status in (301, 302, 303, 307, 308):
                raise RedirectRefused(status, response.getheader("Location") or "")
            if status in (403, 429):
                raise RateLimited(f"the source refused the request ({status})")
            if status != 200:
                raise TransportError(f"unexpected HTTP status {status}")

            raw = bounded_read(response, limit)
            body = bounded_decompress(raw, response.getheader("Content-Encoding") or "", limit)
            return FetchResult(
                body=body,
                etag=response.getheader("ETag"),
                last_modified=response.getheader("Last-Modified"),
                peer_address=peer,
            )
        except (NotModified, UnsafeDestination, PayloadTooLarge, RateLimited,
                RedirectRefused):
            raise
        except Exception as exc:
            last_error = exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:  # pragma: no cover - best effort
                    pass
        if attempt < MAX_RETRIES:
            sleep(delay)
            delay *= 2

    raise TransportError(
        f"feed request failed after {MAX_RETRIES + 1} attempts: "
        f"{type(last_error).__name__ if last_error else 'unknown'}"
    )


class RateLimited(TransportError):
    """The source asked us to stop. Never retried around."""


def _peer_address(connection) -> str | None:
    """The address the socket is actually connected to.

    ``None`` means *could not be determined*, which the caller treats as a
    refusal. It is deliberately distinct from any address string: a caller that
    conflated "unknown" with "fine" would silently disable the peer check.
    """
    sock = getattr(connection, "sock", None)
    if sock is None:
        return None
    try:
        peer = sock.getpeername()
    except (OSError, AttributeError):
        return None
    if not peer or not isinstance(peer[0], str) or not peer[0]:
        return None
    return peer[0]


__all__ = [
    "TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "REQUESTS_PER_SECOND",
    "USER_AGENT",
    "TransportError",
    "PayloadTooLarge",
    "RedirectRefused",
    "RateLimited",
    "NotModified",
    "FetchResult",
    "fetch_feed",
    "bounded_read",
    "bounded_decompress",
]
