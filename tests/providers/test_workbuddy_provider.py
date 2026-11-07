"""Unit tests for the WorkBuddy provider (no network, no real credentials)."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from cloudagent_ext.providers import workbuddy_provider as wb
from cloudagent_ext.providers.workbuddy_provider import (
    WorkBuddyCredential,
    WorkBuddyProvider,
    _credential_from_auth,
    _parse_credit_multiplier,
    _region_of_domain,
    _region_of_provider,
    _rewrite_fingerprints,
    fetch_workbuddy_models,
)


# ---------------------------------------------------------------------------
# Region routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("www.workbuddy.cn", "cn"),
        ("www.codebuddy.cn", "cn"),
        ("www.workbuddy.ai", "global"),
        ("www.codebuddy.ai", "global"),
        ("", None),
        ("example.com", None),
    ],
)
def test_region_of_domain(domain, expected):
    assert _region_of_domain(domain) == expected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("workbuddy", "cn"), ("workbuddy-global", "global"), (None, "cn")],
)
def test_region_of_provider(provider, expected):
    assert _region_of_provider(provider) == expected


# ---------------------------------------------------------------------------
# Catalog parsing helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("x0.79", 0.79),
        ("x0.00", 0.0),
        ("X1.5", 1.5),
        (0.25, 0.25),
        ("", None),
        (None, None),
        ("free", None),
    ],
)
def test_parse_credit_multiplier(raw, expected):
    assert _parse_credit_multiplier(raw) == expected


# ---------------------------------------------------------------------------
# Credential handling
# ---------------------------------------------------------------------------


def test_credential_from_auth_accepts_plain_token():
    cred = _credential_from_auth(
        {
            "accessToken": "plain-token",
            "refreshToken": "refresh-token",
            "expiresAt": 4_000_000_000,
            "domain": "www.workbuddy.cn",
        },
        source="test",
        region="cn",
    )
    assert cred is not None
    assert cred.access_token == "plain-token"
    assert cred.refresh_token == "refresh-token"
    assert cred.region == "cn"


def test_credential_from_auth_rejects_encrypted_envelope():
    """The AES envelope needs the desktop build's keys; we must not guess."""
    assert _credential_from_auth({"accessToken": {"$wbEncrypted": 1, "envelope": "x"}}, source="t", region="cn") is None
    assert _credential_from_auth({"accessToken": '{"$wbEncrypted":1}'}, source="t", region="cn") is None


def test_credential_expiry():
    assert WorkBuddyCredential(access_token="t", expires_at=0).is_expired() is False
    assert WorkBuddyCredential(access_token="t", expires_at=1).is_expired() is True


# ---------------------------------------------------------------------------
# Fingerprint rewriting — the channel-check workaround
# ---------------------------------------------------------------------------


def test_rewrite_removes_the_known_fingerprint():
    text = "Intro\nMain branch (you will usually use this for PRs): main\nOutro"
    rewritten = _rewrite_fingerprints(text)
    assert "Main branch (you will usually use this for PRs)" not in rewritten
    assert "Default branch for pull requests" in rewritten
    # Surrounding content is untouched.
    assert rewritten.startswith("Intro\n")
    assert rewritten.endswith("\nOutro")


def test_rewrite_is_idempotent_and_leaves_other_text_byte_identical():
    once = _rewrite_fingerprints("Main branch (you will usually use this for PRs): main")
    assert _rewrite_fingerprints(once) == once

    untouched = "You are CloudAgent.\nBranch: main\n"
    assert _rewrite_fingerprints(untouched) == untouched


def test_rewrite_is_safe_on_empty_input():
    assert _rewrite_fingerprints("") == ""


# ---------------------------------------------------------------------------
# Provider behaviour
# ---------------------------------------------------------------------------


def _provider(**kwargs) -> WorkBuddyProvider:
    provider = WorkBuddyProvider(**kwargs)
    # Never touch the network / local credential store in unit tests.
    provider._static_credential = WorkBuddyCredential(access_token="test-token", region="cn")
    return provider


def test_prepare_messages_rewrites_system_prompt_only():
    provider = _provider()
    messages = [
        {"role": "system", "content": "Main branch (you will usually use this for PRs): main"},
        {"role": "user", "content": "Main branch (you will usually use this for PRs): keep me"},
    ]
    prepared = provider._prepare_messages(messages)
    assert "Default branch for pull requests" in prepared[0]["content"]
    # A user message is data, not scaffolding — it must not be rewritten.
    assert "Main branch (you will usually use this for PRs)" in prepared[1]["content"]


def test_prepare_messages_fills_empty_assistant_content():
    provider = _provider()
    prepared = provider._prepare_messages(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
        ]
    )
    assert prepared[1]["content"]


def test_stream_promotes_reasoning_only_answer_to_content():
    """A model that answers entirely in reasoning_content must stay usable."""
    from cloudagent_ext.providers.base import ChatResponse

    provider = _provider()
    reasoning_only = ChatResponse(
        content="",
        model="hy3",
        usage={},
        finish_reason="stop",
        reasoning_content="the actual answer",
    )
    with mock.patch.object(
        type(provider).__mro__[1],  # OpenAICompatibleProvider
        "chat_stream_response",
        return_value=reasoning_only,
    ):
        response = provider.chat_stream_response([{"role": "user", "content": "hi"}])

    assert response.content == "the actual answer"
    assert response.reasoning_content is None


def test_stream_keeps_content_when_both_channels_are_used():
    from cloudagent_ext.providers.base import ChatResponse

    provider = _provider()
    mixed = ChatResponse(
        content="visible",
        model="deepseek-v4.1-flash",
        usage={},
        finish_reason="stop",
        reasoning_content="thinking",
    )
    with mock.patch.object(
        type(provider).__mro__[1],
        "chat_stream_response",
        return_value=mixed,
    ):
        response = provider.chat_stream_response([{"role": "user", "content": "hi"}])

    assert response.content == "visible"
    assert response.reasoning_content == "thinking"


def test_channel_reject_becomes_an_actionable_error():
    provider = _provider()
    gateway_error = RuntimeError(
        "Error code: 400 - {'code': 11128, 'msg': 'Illegal API invocation from an unapproved channel'}"
    )
    with mock.patch.object(
        type(provider).__mro__[1],
        "chat_stream_response",
        side_effect=gateway_error,
    ):
        with pytest.raises(RuntimeError, match="unapproved channel"):
            provider.chat_stream_response([{"role": "user", "content": "hi"}])


def test_usage_limit_6004_becomes_a_visible_non_429_error():
    """A 6004 must not reach CloudAgent as a 429.

    CloudAgent treats 429 as retryable and, once the budget is exhausted,
    records the turn as an *API error message* that is deliberately kept out of
    the visible output — the run then reports success with an empty result.
    Converting it here is what makes the reset time reach the user.
    """
    provider = _provider()
    gateway_error = RuntimeError(
        "Error code: 429 - {'code': 6004, 'msg': '您的使用量已超出频率限制，"
        "将在 2026-11-08 00:47:35 UTC+8 重置，您也可以切换其他模型继续使用。'}"
    )
    with mock.patch.object(
        type(provider).__mro__[1],
        "chat_stream_response",
        side_effect=gateway_error,
    ):
        with pytest.raises(RuntimeError) as excinfo:
            provider.chat_stream_response([{"role": "user", "content": "hi"}])

    message = str(excinfo.value)
    assert "6004" in message
    assert "2026-11-08 00:47:35" in message, "the reset time must survive"
    # Load-bearing: these substrings would send it back down CloudAgent's
    # retryable-429 lane, which is exactly what hides the failure.
    assert "429" not in message
    assert "rate_limit" not in message.lower()


def test_plain_429_is_left_to_the_host_retry_policy():
    """Only the usage-limit flavour is converted; ordinary 429s stay retryable."""
    provider = _provider()
    transient = RuntimeError("Error code: 429 - too many requests, please slow down")
    with mock.patch.object(
        type(provider).__mro__[1],
        "chat_stream_response",
        side_effect=transient,
    ):
        with pytest.raises(RuntimeError) as excinfo:
            provider.chat_stream_response([{"role": "user", "content": "hi"}])

    assert "too many requests" in str(excinfo.value)


def test_401_triggers_one_forced_refresh_and_retry():
    from cloudagent_ext.providers.base import ChatResponse

    provider = _provider()
    provider._static_credential = None  # allow refreshing
    ok = ChatResponse(content="ok", model="m", usage={}, finish_reason="stop")
    auth_error = RuntimeError("401 unauthorized token")

    calls = {"stream": 0}

    def fake_stream(*_a, **_k):
        calls["stream"] += 1
        if calls["stream"] == 1:
            raise auth_error
        return ok

    with mock.patch.object(type(provider).__mro__[1], "chat_stream_response", side_effect=fake_stream), \
         mock.patch.object(provider, "_force_refresh", return_value=True) as refreshed:
        response = provider.chat_stream_response([{"role": "user", "content": "hi"}])

    assert response.content == "ok"
    assert refreshed.call_count == 1
    assert calls["stream"] == 2


# ---------------------------------------------------------------------------
# Catalog fetch (HTTP mocked)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_models_maps_upstream_fields_and_drops_routers(monkeypatch):
    payload = {
        "code": 0,
        "data": {
            "models": [
                {"id": "auto", "name": "Auto", "maxInputTokens": 256000, "maxOutputTokens": 32000},
                {
                    "id": "deepseek-v4.1-flash",
                    "name": "DeepSeek V4.1 Flash",
                    "maxInputTokens": 1000000,
                    "maxOutputTokens": 384000,
                    "credits": "x0.11",
                    "supportsImages": True,
                },
                {"id": "dead-model", "maxInputTokens": 1000, "maxOutputTokens": 100, "disabled": True},
            ]
        },
    }

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _FakeResponse(payload)

    monkeypatch.setattr(wb.httpx, "Client", _Client)

    rows = fetch_workbuddy_models(
        WorkBuddyCredential(access_token="t", region="cn"), region="cn"
    )

    ids = [row["id"] for row in rows]
    assert "auto" not in ids, "router ids are not selectable models"
    assert "dead-model" not in ids, "disabled models are dropped"
    row = next(r for r in rows if r["id"] == "deepseek-v4.1-flash")
    assert row["context_window"] == 1000000
    assert row["max_tokens"] == 384000
    assert row["credit_multiplier"] == 0.11
    assert row["supports_images"] is True


def test_fetch_models_raises_when_catalog_is_empty(monkeypatch):
    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _FakeResponse({"data": {"models": []}})

    monkeypatch.setattr(wb.httpx, "Client", _Client)

    with pytest.raises(RuntimeError):
        fetch_workbuddy_models(WorkBuddyCredential(access_token="t", region="cn"), region="cn")


def test_get_available_models_falls_back_to_static_list(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        wb, "fetch_workbuddy_models", mock.Mock(side_effect=RuntimeError("offline"))
    )
    models = provider.get_available_models()
    assert models == list(wb.FALLBACK_MODELS["cn"])


def test_discovery_uses_the_config_catalog_not_the_missing_models_route(monkeypatch):
    """`/v2/models` does not exist on this gateway; discovery must not try it."""
    provider = _provider()
    monkeypatch.setattr(provider, "get_available_models", lambda: ["deepseek-v4.1-flash", "hy3"])

    # The inherited implementation would reach for ``client.models.list()``.
    def _boom():
        raise AssertionError("must not call client.models.list()")

    monkeypatch.setattr(type(provider), "client", property(lambda self: _boom()))

    assert provider.discover_available_models() == ["deepseek-v4.1-flash", "hy3"]


# ---------------------------------------------------------------------------
# Registration / credential gates
# ---------------------------------------------------------------------------


def test_provider_is_registered():
    # Importing the factory is what runs `_init_provider_extensions()`; it avoids
    # pulling in the whole tool system just to inspect the registry.
    import cloudagent_ext.providers.factory  # noqa: F401
    from cloudagent_ext.providers import PROVIDER_INFO

    assert "workbuddy" in PROVIDER_INFO
    assert "workbuddy-global" in PROVIDER_INFO


def test_workbuddy_does_not_require_an_api_key():
    """There is no key to mint — the credential is the desktop session."""
    from cloudagent_ext.providers._upstream_catalog import provider_requires_api_key

    assert provider_requires_api_key("workbuddy") is False
    assert provider_requires_api_key("workbuddy-global") is False


def test_has_credentials_follows_local_credential_discovery(monkeypatch):
    from cloudagent_ext.providers._upstream_catalog import provider_has_credentials

    monkeypatch.setattr(
        wb, "discover_workbuddy_credentials", lambda region: [WorkBuddyCredential(access_token="t", region=region)]
    )
    assert provider_has_credentials("workbuddy", "") is True

    monkeypatch.setattr(wb, "discover_workbuddy_credentials", lambda region: [])
    assert provider_has_credentials("workbuddy", "") is False
    # An explicit key always counts.
    assert provider_has_credentials("workbuddy", "explicit-key") is True


def test_provider_list_reports_workbuddy_as_configured(monkeypatch):
    """`cloudagent provider list` must not claim "configured=no" when a local
    WorkBuddy sign-in exists — there is simply no API key to look at."""
    import cloudagent_ext.providers.factory  # noqa: F401
    from cloudagent_ext.cli.model_cmd.registry import ModelRegistry

    monkeypatch.setattr(
        wb,
        "discover_workbuddy_credentials",
        lambda region: [WorkBuddyCredential(access_token="t", region=region)],
    )
    statuses = {status.name: status for status in ModelRegistry().provider_statuses()}
    assert statuses["workbuddy"].authenticated is True


def test_dsh_vault_entries_are_read_without_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "_dsh_home", lambda: tmp_path)
    region_dir = tmp_path / "workbuddy-vault" / "cn"
    region_dir.mkdir(parents=True)
    (region_dir / "acc.json").write_text(
        json.dumps(
            {
                "accountId": "acc",
                "auth": {"accessToken": "vault-token", "domain": "www.workbuddy.cn", "expiresAt": 4_000_000_000},
                "account": {"nickname": "tester"},
            }
        ),
        encoding="utf-8",
    )

    creds = wb._vault_credentials("cn")
    assert len(creds) == 1
    assert creds[0].access_token == "vault-token"
    assert creds[0].nickname == "tester"
    # Nothing was written back.
    assert sorted(p.name for p in region_dir.iterdir()) == ["acc.json"]
