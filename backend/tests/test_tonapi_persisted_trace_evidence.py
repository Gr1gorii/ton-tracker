"""Focused adapter tests for bounded persisted trace/message candidates."""

from __future__ import annotations

import copy
import json

import pytest

from adapters.tonapi import TonapiAdapter
from config import DEFAULT_TONAPI_BASE_URL, ProviderResult, Settings


ROOT_HASH = "11" * 32
CHILD_HASH = "22" * 32
ROOT_ACCOUNT = "0:" + "33" * 32
CHILD_ACCOUNT = "0:" + "44" * 32
OTHER_ACCOUNT = "0:" + "55" * 32
ROOT_IN_HASH = "66" * 32
CHILD_IN_HASH = "77" * 32
ROOT_OUT_HASH = "88" * 32
ROOT_LT = "89156526000001"
CHILD_LT = "89156526000003"


def _settings(mode: str = "real") -> Settings:
    return Settings(
        data_mode=mode,
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        ton_api_base_url="",
        ton_api_key="",
        bitquery_api_url="",
        bitquery_api_key="",
        stonfi_base_url="https://api.ston.fi",
        tonapi_base_url=DEFAULT_TONAPI_BASE_URL,
        tonapi_api_key="",
        wallet_activity_provider="tonapi",
        wallet_activity_live_enabled=True,
        ton_network="mainnet",
    )


def _message(
    message_hash: str,
    message_type: str,
    *,
    source: str | None,
    destination: str | None,
    created_lt: int | str,
) -> dict:
    result = {
        "hash": message_hash,
        "msg_type": message_type,
        "created_lt": created_lt,
        "created_at": 1_717_236_000,
        "value": 1_000_000_000,
        "fwd_fee": "15",
        "ihr_fee": 0,
        "import_fee": "0",
        "ihr_disabled": True,
        "bounce": False,
        "bounced": False,
        "raw_body": "forbidden-raw-body-boc",
        "decoded_body": {"forbidden": True},
        "decoded_op_name": "forbidden-operation",
    }
    if source is not None:
        result["source"] = {"address": source, "name": "not persisted"}
    if destination is not None:
        result["destination"] = {
            "address": destination,
            "is_scam": False,
        }
    return result


def _transaction(
    transaction_hash: str,
    logical_time: str,
    account: str,
    *,
    in_message: dict | None,
    out_messages: list[dict] | None = None,
    success: bool = True,
    aborted: bool = False,
) -> dict:
    return {
        "hash": transaction_hash,
        "lt": logical_time,
        "account": {"address": account, "name": "not persisted"},
        "utime": 1_717_236_000,
        "success": success,
        "aborted": aborted,
        "in_msg": in_message,
        "out_msgs": out_messages or [],
        "raw": "forbidden-raw-transaction-boc",
        "action_phase": {"result_code": 0},
    }


def _node(
    transaction_hash: str,
    logical_time: str,
    account: str,
    *,
    in_message: dict | None,
    out_messages: list[dict] | None = None,
    children: list[dict] | None = None,
    success: bool = True,
    aborted: bool = False,
) -> dict:
    return {
        "transaction": _transaction(
            transaction_hash,
            logical_time,
            account,
            in_message=in_message,
            out_messages=out_messages,
            success=success,
            aborted=aborted,
        ),
        "interfaces": ["forbidden-interface"],
        "emulated": False,
        "children": children or [],
    }


def _finalized_trace() -> dict:
    child_in = _message(
        CHILD_IN_HASH,
        "int_msg",
        source=ROOT_ACCOUNT,
        destination=CHILD_ACCOUNT,
        created_lt=89156526000002,
    )
    child = _node(
        CHILD_HASH,
        CHILD_LT,
        CHILD_ACCOUNT,
        in_message=child_in,
        success=False,
        aborted=True,
    )
    root_in = _message(
        ROOT_IN_HASH,
        "ext_in_msg",
        source=None,
        destination=ROOT_ACCOUNT,
        created_lt=0,
    )
    root_out = _message(
        ROOT_OUT_HASH,
        "ext_out_msg",
        source=ROOT_ACCOUNT,
        destination=None,
        created_lt="89156526000004",
    )
    return _node(
        ROOT_HASH,
        ROOT_LT,
        ROOT_ACCOUNT,
        in_message=root_in,
        out_messages=[root_out],
        children=[child],
    )


def _normalize(payload: dict | None = None) -> dict:
    return TonapiAdapter.normalize_transaction_trace_persisted_evidence_response(
        payload or _finalized_trace(),
        requested_transaction_hash=ROOT_HASH,
        network="ton-mainnet",
    )


def test_persisted_trace_normalizer_returns_exact_preorder_graph_and_counts():
    result = _normalize()

    assert set(result) == {"trace_state", "anchor", "summary", "nodes"}
    assert result["trace_state"] == "finalized"
    assert result["anchor"] == {
        "transaction_hash": ROOT_HASH,
        "logical_time": ROOT_LT,
        "account_canonical": ROOT_ACCOUNT,
    }
    assert result["summary"] == {
        "root_transaction_hash": ROOT_HASH,
        "transaction_count": 2,
        "max_depth": 1,
        "message_count": 3,
        "root_inbound_message_count": 1,
        "child_internal_message_count": 1,
        "remaining_out_message_count": 1,
        "internal_message_count": 1,
        "external_in_message_count": 1,
        "external_out_message_count": 1,
        "successful_transaction_count": 1,
        "failed_transaction_count": 1,
        "aborted_transaction_count": 1,
        "unique_account_count": 2,
    }
    assert [node["preorder_index"] for node in result["nodes"]] == [0, 1]
    assert [node["parent_preorder_index"] for node in result["nodes"]] == [
        None,
        0,
    ]
    assert [node["depth"] for node in result["nodes"]] == [0, 1]
    assert set(result["nodes"][0]) == {
        "preorder_index",
        "parent_preorder_index",
        "depth",
        "transaction_hash",
        "account_canonical",
        "logical_time",
        "unix_time",
        "success",
        "aborted",
        "in_message",
        "out_messages",
    }

    root_in = result["nodes"][0]["in_message"]
    child_in = result["nodes"][1]["in_message"]
    root_out = result["nodes"][0]["out_messages"][0]
    assert root_in["role"] == "root_inbound"
    assert child_in["role"] == "child_inbound"
    assert root_out["role"] == "remaining_outbound"
    assert child_in["source_account_canonical"] == ROOT_ACCOUNT
    assert child_in["destination_account_canonical"] == CHILD_ACCOUNT
    assert root_in["created_logical_time"] == "0"
    assert root_out["value_nanoton"] == "1000000000"
    assert root_out["forward_fee_nanoton"] == "15"
    assert set(root_in) == {
        "role",
        "ordinal",
        "message_hash",
        "message_type",
        "source_account_canonical",
        "destination_account_canonical",
        "created_logical_time",
        "unix_time",
        "value_nanoton",
        "forward_fee_nanoton",
        "ihr_fee_nanoton",
        "import_fee_nanoton",
        "ihr_disabled",
        "bounce",
        "bounced",
        "observation_identity_key",
    }
    assert root_in["observation_identity_key"] == "|".join(
        (
            "tonapi_trace_message_obs_v1",
            "ton-mainnet",
            ROOT_HASH,
            "0",
            "root_inbound",
            "0",
            ROOT_IN_HASH,
        )
    )


def test_persisted_trace_output_omits_raw_and_semantic_provider_fields():
    serialized = json.dumps(_normalize())

    for forbidden in (
        "forbidden-raw-body-boc",
        "forbidden-raw-transaction-boc",
        "forbidden-interface",
        "forbidden-operation",
        "decoded_body",
        "action_phase",
        "is_scam",
    ):
        assert forbidden not in serialized


def test_persisted_trace_normalizer_allows_optional_root_inbound():
    payload = _finalized_trace()
    payload["transaction"]["in_msg"] = None

    result = _normalize(payload)

    assert result["nodes"][0]["in_message"] is None
    assert result["summary"]["root_inbound_message_count"] == 0
    assert result["summary"]["message_count"] == 2


def test_persisted_trace_normalizer_returns_pending_candidate_for_service_gate():
    payload = _finalized_trace()
    pending = _message(
        "99" * 32,
        "int_msg",
        source=ROOT_ACCOUNT,
        destination=OTHER_ACCOUNT,
        created_lt="89156526000005",
    )
    payload["transaction"]["out_msgs"] = [pending]

    result = _normalize(payload)

    assert result["trace_state"] == "pending"
    assert result["summary"]["remaining_out_message_count"] == 1
    assert result["summary"]["internal_message_count"] == 2


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["children"][0]["transaction"].update(
            {"in_msg": None}
        ),
        lambda payload: payload["children"][0]["transaction"][
            "in_msg"
        ].update({"msg_type": "ext_in_msg"}),
        lambda payload: payload["children"][0]["transaction"][
            "in_msg"
        ].update({"source": {"address": OTHER_ACCOUNT}}),
        lambda payload: payload["children"][0]["transaction"][
            "in_msg"
        ].update({"destination": {"address": OTHER_ACCOUNT}}),
    ],
)
def test_persisted_trace_normalizer_rejects_incoherent_child_edge(mutation):
    payload = _finalized_trace()
    mutation(payload)

    with pytest.raises(ValueError, match="child|inbound"):
        _normalize(payload)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("hash", "x", "hash"),
        ("msg_type", "unknown", "type"),
        ("created_lt", "01", "logical time"),
        ("created_lt", str(2**64), "logical time"),
        ("created_at", True, "unix time"),
        ("created_at", -1, "unix time"),
        ("created_at", 2**63, "unix time"),
        ("value", -1, "value"),
        ("value", str(2**64), "value"),
        ("fwd_fee", "01", "fwd_fee"),
        ("ihr_fee", True, "ihr_fee"),
        ("import_fee", None, "import_fee"),
        ("ihr_disabled", 1, "ihr_disabled"),
        ("bounce", "false", "bounce"),
        ("bounced", 0, "bounced"),
    ],
)
def test_persisted_trace_normalizer_rejects_invalid_message_fields(
    field,
    invalid,
    message,
):
    payload = _finalized_trace()
    payload["transaction"]["in_msg"][field] = invalid

    with pytest.raises(ValueError, match=message):
        _normalize(payload)


@pytest.mark.parametrize("field", ["source", "destination"])
def test_persisted_trace_normalizer_rejects_malformed_optional_account(field):
    payload = _finalized_trace()
    payload["transaction"]["in_msg"][field] = {"address": "invalid"}

    with pytest.raises(ValueError, match=field):
        _normalize(payload)


def test_persisted_trace_normalizer_calls_preview_validation_first():
    payload = _finalized_trace()
    payload.pop("interfaces")

    with pytest.raises(ValueError, match="interfaces"):
        _normalize(payload)


def test_persisted_trace_normalizer_accepts_exact_2304_message_boundary():
    root_in = _message(
        ROOT_IN_HASH,
        "ext_in_msg",
        source=None,
        destination=ROOT_ACCOUNT,
        created_lt=0,
    )
    children = []
    for index in range(255):
        child_account = f"0:{index + 1:064x}"
        child = _node(
            f"{index + 10_000:064x}",
            str(index + 10_000),
            child_account,
            in_message=_message(
                f"{index + 20_000:064x}",
                "int_msg",
                source=ROOT_ACCOUNT,
                destination=child_account,
                created_lt=index + 1,
            ),
        )
        children.append(child)
    remaining = [
        _message(
            f"{index + 30_000:064x}",
            "ext_out_msg",
            source=ROOT_ACCOUNT,
            destination=None,
            created_lt=index + 1,
        )
        for index in range(2048)
    ]
    payload = _node(
        ROOT_HASH,
        ROOT_LT,
        ROOT_ACCOUNT,
        in_message=root_in,
        out_messages=remaining,
        children=children,
    )

    result = _normalize(payload)

    assert result["summary"]["transaction_count"] == 256
    assert result["summary"]["message_count"] == 2304
    assert result["summary"]["child_internal_message_count"] == 255
    assert result["summary"]["remaining_out_message_count"] == 2048


def test_persisted_trace_adapter_makes_exactly_one_provider_call(monkeypatch):
    calls: list[tuple[str, object, str, object]] = []

    def fake_fetch(self, path, query=None, method="GET", body=None, timeout=10):
        calls.append((path, query, method, body))
        return ProviderResult.success(_finalized_trace(), source="real")

    monkeypatch.setattr(TonapiAdapter, "fetch_json", fake_fetch)
    result = TonapiAdapter(_settings()).get_transaction_trace_persisted_evidence(
        ROOT_HASH,
        "ton-mainnet",
    )

    assert result.ok is True
    assert result.data == _normalize()
    assert calls == [(f"/v2/traces/{ROOT_HASH}", None, "GET", None)]


@pytest.mark.parametrize(
    ("transaction_hash", "network", "mode"),
    [
        ("AB" * 32, "ton-mainnet", "real"),
        (ROOT_HASH, "ton-unknown", "real"),
        (ROOT_HASH, "ton-mainnet", "mock"),
    ],
)
def test_persisted_trace_adapter_rejects_ineligible_input_without_call(
    monkeypatch,
    transaction_hash,
    network,
    mode,
):
    monkeypatch.setattr(
        TonapiAdapter,
        "fetch_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not be called")
        ),
    )

    result = TonapiAdapter(
        _settings(mode)
    ).get_transaction_trace_persisted_evidence(
        transaction_hash,
        network,
    )

    assert result.ok is False


def test_persisted_trace_normalizer_does_not_mutate_provider_payload():
    payload = _finalized_trace()
    before = copy.deepcopy(payload)

    _normalize(payload)

    assert payload == before
