"""Cross-process error-taxonomy regressions for the pinned TON config."""

import pytest

from services import ton_liteclient_jetton_verifier as jetton_service
from services import ton_transaction_inclusion_proof as inclusion_service
from services import ton_wallet_public_key as public_key_service
from services.ton_liteclient_config import (
    TonLiteclientConfigFailure,
    load_pinned_liteclient_config,
)
from services.ton_liteclient_process import (
    TonLiteclientProcessFailure,
    child_error_envelope,
    validated_child_envelope,
)


class _StatusResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def iter_content(self, *, chunk_size: int):
        assert chunk_size == 64 * 1024
        return iter(())

    def close(self) -> None:
        pass


def _status_get(status_code: int):
    def get(*_args, **_kwargs):
        return _StatusResponse(status_code)

    return get


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404])
def test_permanent_config_http_statuses_remain_nonretryable_across_child_ipc(
    status: int,
):
    with pytest.raises(TonLiteclientConfigFailure) as failure:
        load_pinned_liteclient_config(
            "ton-mainnet",
            timeout_seconds=2,
            http_get=_status_get(status),
        )
    assert failure.value.code == "liteserver_config_unavailable"
    assert failure.value.retryable is False

    safe_code_sets = (
        inclusion_service._SAFE_CHILD_CODES,
        public_key_service._SAFE_CODES,
        jetton_service._SAFE_CODES,
    )
    for safe_codes in safe_code_sets:
        envelope = child_error_envelope(
            failure.value,
            safe_error_codes=safe_codes,
        )
        assert envelope == {
            "version": 1,
            "ok": False,
            "code": "liteserver_config_unavailable",
            "retryable": False,
        }
        with pytest.raises(TonLiteclientProcessFailure) as parent_failure:
            validated_child_envelope(envelope, safe_error_codes=safe_codes)
        assert parent_failure.value.code == "liteserver_config_unavailable"
        assert parent_failure.value.retryable is False
    assert inclusion_service._safe_child_code(failure.value.code) == (
        "liteserver_config_unavailable"
    )


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (408, "http_408"),
        (425, "http_425"),
        (429, "http_429"),
        (500, "http_500"),
        (502, "http_502"),
        (503, "http_503"),
        (504, "http_504"),
        (501, "liteserver_config_unavailable"),
    ],
)
def test_transient_config_http_statuses_keep_retryable_safe_taxonomy(
    status: int,
    expected_code: str,
):
    with pytest.raises(TonLiteclientConfigFailure) as failure:
        load_pinned_liteclient_config(
            "ton-testnet",
            timeout_seconds=2,
            http_get=_status_get(status),
        )
    assert failure.value.code == expected_code
    assert failure.value.retryable is True
