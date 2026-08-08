"""Private Alertmanager configuration and data-boundary tests."""

from __future__ import annotations

import os

import pytest

from ops.alertmanager_config import (
    AlertmanagerConfigError,
    prepare_alertmanager_data_directory,
    validate_alertmanager_config,
    validate_alertmanager_data_directory,
)


VALID_CONFIG = """\
route:
  receiver: primary
  routes:
    - receiver: security
      matchers:
        - 'severity="critical"'
receivers:
  - name: primary
    webhook_configs:
      - url: https://alerts.example/primary
  - name: security
    pagerduty_configs:
      - routing_key: private-routing-key
"""


def _private_config(tmp_path, payload: str = VALID_CONFIG):
    path = tmp_path / "alertmanager.yml"
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_private_config_requires_integrations_for_every_routed_receiver(tmp_path):
    config = _private_config(tmp_path)
    validate_alertmanager_config(config)

    config.write_text(
        "route:\n  receiver: sink\nreceivers:\n  - name: sink\n",
        encoding="utf-8",
    )
    with pytest.raises(AlertmanagerConfigError, match="no notification integration"):
        validate_alertmanager_config(config)

    config.write_text(
        "route:\n  receiver: missing\nreceivers:\n  - name: configured\n"
        "    webhook_configs:\n      - url: https://alerts.example\n",
        encoding="utf-8",
    )
    with pytest.raises(AlertmanagerConfigError, match="invalid"):
        validate_alertmanager_config(config)

    config.write_text(
        "route:\n  receiver: empty\nreceivers:\n  - name: empty\n"
        "    webhook_configs:\n      - {}\n",
        encoding="utf-8",
    )
    with pytest.raises(AlertmanagerConfigError, match="no notification integration"):
        validate_alertmanager_config(config)


def test_config_rejects_public_symlinked_aliased_and_unbounded_inputs(tmp_path):
    config = _private_config(tmp_path)
    config.chmod(0o640)
    with pytest.raises(AlertmanagerConfigError, match="private bounded"):
        validate_alertmanager_config(config)

    config.chmod(0o600)
    linked = tmp_path / "linked.yml"
    linked.symlink_to(config)
    with pytest.raises(AlertmanagerConfigError, match="private bounded"):
        validate_alertmanager_config(linked)

    config.write_text(
        "route: &route\n  receiver: primary\ncopy: *route\nreceivers:\n"
        "  - name: primary\n    webhook_configs:\n"
        "      - url: https://alerts.example\n",
        encoding="utf-8",
    )
    with pytest.raises(AlertmanagerConfigError, match="invalid"):
        validate_alertmanager_config(config)

    config.write_text("x" * 262_145, encoding="utf-8")
    with pytest.raises(AlertmanagerConfigError, match="private bounded"):
        validate_alertmanager_config(config)


def test_config_rejects_duplicate_receivers_and_invalid_route_shapes(tmp_path):
    duplicate = _private_config(
        tmp_path,
        "route:\n  receiver: primary\nreceivers:\n"
        "  - name: primary\n    webhook_configs:\n      - url: https://one.example\n"
        "  - name: primary\n    webhook_configs:\n      - url: https://two.example\n",
    )
    with pytest.raises(AlertmanagerConfigError, match="invalid"):
        validate_alertmanager_config(duplicate)

    duplicate.write_text(
        "route:\n  receiver: primary\n  routes: invalid\nreceivers:\n"
        "  - name: primary\n    webhook_configs:\n      - url: https://one.example\n",
        encoding="utf-8",
    )
    with pytest.raises(AlertmanagerConfigError, match="route tree"):
        validate_alertmanager_config(duplicate)


def test_alertmanager_data_directory_is_private_absolute_and_owned(tmp_path):
    directory = tmp_path / "alertmanager-data"
    prepare_alertmanager_data_directory(directory)
    validate_alertmanager_data_directory(directory)
    assert directory.stat().st_mode & 0o777 == 0o700
    assert directory.stat().st_uid == os.getuid()

    directory.chmod(0o755)
    with pytest.raises(AlertmanagerConfigError, match="private and owned"):
        validate_alertmanager_data_directory(directory)

    with pytest.raises(AlertmanagerConfigError, match="absolute"):
        prepare_alertmanager_data_directory(type(directory)("relative-data"))
