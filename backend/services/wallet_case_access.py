"""Temporary local-only boundary for the pre-authentication Wallet Case slice."""

from __future__ import annotations

from ipaddress import ip_address
import re
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


_PORT = re.compile(r"^[0-9]{1,5}$")


def _valid_port(value: str) -> bool:
    return bool(_PORT.fullmatch(value)) and 0 < int(value) <= 65535


def _host_name(value: str) -> str | None:
    """Parse a strict HTTP Host value without accepting DNS-rebind names."""
    candidate = value.strip().lower()
    if not candidate or any(char in candidate for char in "/\\@, \t\r\n"):
        return None
    if candidate.startswith("["):
        closing = candidate.find("]")
        if closing < 0:
            return None
        host = candidate[1:closing]
        suffix = candidate[closing + 1 :]
        if suffix and (
            not suffix.startswith(":") or not _valid_port(suffix[1:])
        ):
            return None
    else:
        if candidate.count(":") > 1:
            return None
        host, separator, port = candidate.partition(":")
        if separator and not _valid_port(port):
            return None
    return host[:-1] if host.endswith(".") else host


def _is_local_host(value: str) -> bool:
    host = _host_name(value)
    if host == "localhost":
        return True
    if not host:
        return False
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _has_safe_local_origin(request: Request) -> bool:
    origins = request.headers.getlist("origin")
    if not origins:
        return True
    if len(origins) != 1:
        return False
    try:
        parsed = urlsplit(origins[0])
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and parsed.query == ""
        and parsed.fragment == ""
        and parsed.path == ""
        and parsed.hostname is not None
        and _is_local_host(
            (
                f"[{parsed.hostname}]"
                if ":" in parsed.hostname
                else parsed.hostname
            )
            + (f":{port}" if port is not None else "")
        )
    )


def wallet_case_access_available(request: Request) -> bool:
    """Require both a direct loopback peer and a non-rebindable local Host."""
    client = request.client
    if client is None:
        return False
    peer = client.host.strip().lower()
    host_headers = request.headers.getlist("host")
    if len(host_headers) != 1:
        return False
    if peer == "testclient":
        peer_and_host_are_local = (
            _is_local_host(host_headers[0])
            or _host_name(host_headers[0]) == "testserver"
        )
    else:
        try:
            peer_is_loopback = ip_address(peer).is_loopback
        except ValueError:
            return False
        peer_and_host_are_local = peer_is_loopback and _is_local_host(
            host_headers[0]
        )
    return peer_and_host_are_local and _has_safe_local_origin(request)


def require_local_wallet_case_access(request: Request) -> None:
    """Block hosted access until owner scope comes from real authentication."""
    if wallet_case_access_available(request):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Wallet Cases are local-only until authenticated owner scopes "
            "are available."
        ),
        headers={"Cache-Control": "no-store"},
    )
