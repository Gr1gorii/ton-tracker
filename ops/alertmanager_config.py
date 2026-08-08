"""Validate the private Alertmanager notification boundary."""

from __future__ import annotations

import os
from pathlib import Path
import stat

import yaml


_MAX_CONFIG_BYTES = 262_144
_MAX_RECEIVERS = 100
_MAX_ROUTES = 1_000
_MAX_ROUTE_DEPTH = 20
_INTEGRATION_KEYS = {
    "discord_configs",
    "email_configs",
    "incidentio_configs",
    "jira_configs",
    "kafka_configs",
    "msteams_configs",
    "msteamsv2_configs",
    "opsgenie_configs",
    "pagerduty_configs",
    "pushover_configs",
    "rocketchat_configs",
    "slack_configs",
    "sns_configs",
    "telegram_configs",
    "victorops_configs",
    "webex_configs",
    "webhook_configs",
    "wechat_configs",
}


class AlertmanagerConfigError(RuntimeError):
    """The notification configuration or state directory is unsafe."""


class _NoAliasSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):  # type: ignore[no-untyped-def]
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not accepted")
        return super().compose_node(parent, index)


def validate_alertmanager_config(path: Path) -> None:
    """Require a private bounded config with real routed integrations."""
    payload = _read_private_config(path)
    try:
        config = yaml.load(payload.decode("utf-8"), Loader=_NoAliasSafeLoader)
    except (RecursionError, UnicodeError, yaml.YAMLError) as exc:
        raise AlertmanagerConfigError(
            "Alertmanager configuration is invalid"
        ) from exc
    if not isinstance(config, dict):
        raise AlertmanagerConfigError("Alertmanager configuration is invalid")

    raw_receivers = config.get("receivers")
    route = config.get("route")
    if (
        not isinstance(raw_receivers, list)
        or not 1 <= len(raw_receivers) <= _MAX_RECEIVERS
        or not isinstance(route, dict)
    ):
        raise AlertmanagerConfigError("Alertmanager configuration is invalid")

    receivers: dict[str, dict[str, object]] = {}
    for receiver in raw_receivers:
        if not isinstance(receiver, dict):
            raise AlertmanagerConfigError("Alertmanager configuration is invalid")
        name = receiver.get("name")
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or len(name) > 128
            or any(character.isspace() and character not in {" "} for character in name)
            or name in receivers
        ):
            raise AlertmanagerConfigError("Alertmanager configuration is invalid")
        receivers[name] = receiver

    referenced = _referenced_receivers(route)
    if not referenced or not referenced <= receivers.keys():
        raise AlertmanagerConfigError("Alertmanager configuration is invalid")
    for name in referenced:
        receiver = receivers[name]
        integrations = [
            receiver[key]
            for key in _INTEGRATION_KEYS
            if key in receiver
        ]
        if not integrations or any(
            not isinstance(configs, list)
            or not configs
            or any(not isinstance(entry, dict) or not entry for entry in configs)
            for configs in integrations
        ):
            raise AlertmanagerConfigError(
                "Alertmanager routed receiver has no notification integration"
            )


def prepare_alertmanager_data_directory(path: Path) -> None:
    """Create or validate the private persistent Alertmanager directory."""
    if not path.is_absolute():
        raise AlertmanagerConfigError(
            "Alertmanager data directory must be absolute"
        )
    try:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
        _validate_private_data_directory(path)
        _fsync_directory(path.parent)
    except AlertmanagerConfigError:
        raise
    except OSError as exc:
        raise AlertmanagerConfigError(
            "Alertmanager data directory is unavailable"
        ) from exc


def validate_alertmanager_data_directory(path: Path) -> None:
    """Fail closed unless the persistent directory belongs to this operator."""
    if not path.is_absolute():
        raise AlertmanagerConfigError(
            "Alertmanager data directory must be absolute"
        )
    try:
        _validate_private_data_directory(path)
    except AlertmanagerConfigError:
        raise
    except OSError as exc:
        raise AlertmanagerConfigError(
            "Alertmanager data directory is unavailable"
        ) from exc


def _read_private_config(path: Path) -> bytes:
    if not path.is_absolute():
        raise AlertmanagerConfigError("Alertmanager configuration path is invalid")
    descriptor: int | None = None
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) & 0o077
            or before.st_size < 1
            or before.st_size > _MAX_CONFIG_BYTES
        ):
            raise AlertmanagerConfigError(
                "Alertmanager configuration must be a private bounded file"
            )
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) & 0o077
            or opened.st_size != before.st_size
        ):
            raise AlertmanagerConfigError(
                "Alertmanager configuration changed while it was opened"
            )
        chunks = bytearray()
        while len(chunks) <= _MAX_CONFIG_BYTES:
            chunk = os.read(descriptor, _MAX_CONFIG_BYTES + 1 - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) > _MAX_CONFIG_BYTES:
            raise AlertmanagerConfigError(
                "Alertmanager configuration exceeds the size limit"
            )
        return bytes(chunks)
    except AlertmanagerConfigError:
        raise
    except OSError as exc:
        raise AlertmanagerConfigError(
            "Alertmanager configuration is unavailable"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _referenced_receivers(root: dict[str, object]) -> set[str]:
    referenced: set[str] = set()
    stack: list[tuple[dict[str, object], int]] = [(root, 1)]
    visited = 0
    while stack:
        route, depth = stack.pop()
        visited += 1
        if visited > _MAX_ROUTES or depth > _MAX_ROUTE_DEPTH:
            raise AlertmanagerConfigError("Alertmanager route tree is unbounded")
        receiver = route.get("receiver")
        if receiver is not None:
            if (
                not isinstance(receiver, str)
                or not receiver
                or receiver != receiver.strip()
                or len(receiver) > 128
            ):
                raise AlertmanagerConfigError("Alertmanager route receiver is invalid")
            referenced.add(receiver)
        children = route.get("routes", [])
        if not isinstance(children, list):
            raise AlertmanagerConfigError("Alertmanager route tree is invalid")
        for child in reversed(children):
            if not isinstance(child, dict):
                raise AlertmanagerConfigError("Alertmanager route tree is invalid")
            stack.append((child, depth + 1))
    return referenced


def _validate_private_data_directory(path: Path) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise AlertmanagerConfigError(
            "Alertmanager data directory must be private and owned by the operator"
        )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
