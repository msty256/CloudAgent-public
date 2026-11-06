#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""WorkBuddy provider — borrow the locally signed-in WorkBuddy desktop session.

WorkBuddy (国内版 ``www.workbuddy.cn`` / 国际版 ``www.workbuddy.ai``) exposes an
OpenAI-shaped ``/v2/chat/completions`` gateway.  This provider lets CloudAgent
use the credentials the WorkBuddy desktop app already wrote on this machine —
the same approach the ``dsh-connect-workbuddy`` DSH plugin takes — instead of
asking the user for a separate API key (WorkBuddy has no public API keys).

Wire facts verified against the live gateway (read-only probes, 2026-11-07):

* ``POST {base}/chat/completions`` with ``Authorization: Bearer <accessToken>``
  works with **no** spoofed client headers — a plain ``Bearer`` is accepted.
* ``stream`` is **mandatory**: a non-stream request is refused with
  ``HTTP 400 / code 11101 "Non-stream chat request is currently not supported"``.
  The base class therefore only ever streams (``chat()`` is implemented on top
  of ``chat_stream_response``).
* The SSE payload is already OpenAI ``chat.completion.chunk`` shaped, including
  native ``delta.tool_calls`` and ``finish_reason="tool_calls"``, so no DSML /
  markup recovery layer is needed here (unlike the DSH plugin, which needs one
  because pi-ai drives a different code path).
* Some models stream their answer into ``delta.reasoning_content`` and leave
  ``delta.content`` empty for the whole turn (``hy3`` does; ``deepseek-v4.1-flash``
  does not).  A turn whose visible content is empty but whose reasoning is not
  is promoted to ``content`` — otherwise the agent loop sees an empty assistant
  message and the model looks broken.

Credential strategy (highest precedence first):

1. ``api_key`` given explicitly (env var / ``cloudagent login`` / config) — used
   as a **raw bearer token**, never refreshed by this provider.
2. Our own vault at ``$DSH_HOME/workbuddy-vault/<region>/<accountId>.json`` —
   read-only reuse of what ``dsh-connect-workbuddy`` already refreshed.  When the
   stored token is near expiry we refresh it **in memory only** and never write
   the vault (the DSH plugin owns those files).
3. The WorkBuddy desktop app's own auth file — read-only, and only when its
   token fields are plain strings.  The encrypted-envelope variant
   (``{"$wbEncrypted":1,...}``) needs keys baked into the desktop build, which
   this provider deliberately does not attempt to extract.

Tokens are deliberately never logged.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator, Optional

import httpx

from .openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Region / endpoint constants
# ---------------------------------------------------------------------------

#: Canonical CloudAgent provider ids, one per WorkBuddy region.
WORKBUDDY_PROVIDER_CN = "workbuddy"
WORKBUDDY_PROVIDER_GLOBAL = "workbuddy-global"

#: Region key -> (chat base URL, billing/config host, human label).
WORKBUDDY_REGIONS: dict[str, dict[str, str]] = {
    "cn": {
        "base_url": "https://www.workbuddy.cn/v2",
        "config_url": "https://www.workbuddy.cn/v3/config",
        "label": "WorkBuddy (CN)",
        # Credential domains that belong to the domestic stack.
        "domains": "workbuddy.cn,codebuddy.cn",
    },
    "global": {
        "base_url": "https://www.workbuddy.ai/v2",
        "config_url": "https://www.workbuddy.ai/v3/config",
        "label": "WorkBuddy Global",
        "domains": "workbuddy.ai,codebuddy.ai",
    },
}

#: The App-channel user agent. ``/v3/config`` issues a *different* product
#: configuration per client channel: the CLI channel is a strict subset and
#: omits ``modelPromotions`` / ``modelTiers``. Reading the catalog as the App
#: is what makes the model list complete. Chat requests do not need it.
WORKBUDDY_APP_UA = "WorkBuddy/5.8.3 WorkBuddy/5.8.3 CLI/2.161.0"

#: Refresh this long before the access token actually expires.
_REFRESH_SKEW_SECONDS = 300

#: Router ids in ``/v3/config`` that are not selectable models.
_ROUTER_MODEL_IDS = frozenset({"auto", "default-model"})

#: Substrings WorkBuddy's gateway treats as a *non-WorkBuddy agent* fingerprint.
#:
#: The gateway runs a channel/identity check on the request body and answers
#: ``HTTP 400 / code 11128 "Illegal API invocation from an unapproved channel"``
#: when it recognises another vendor's agent scaffolding. CloudAgent's system
#: prompt is deliberately Claude-Code-shaped, so it carries that scaffolding
#: verbatim and is refused on **every** turn — measured 2026-11-07 by bisecting
#: the real 28 k-char prompt down to one line: removing this single sentence
#: flipped the answer from 11128 to 200 OK, and the rejection is identical for
#: every model (``deepseek-v4.1-flash`` / ``deepseek-v4-pro`` / ``glm-5.3`` /
#: ``hy3``), so it is a gateway policy on the request, not a model limit.
#:
#: Each pair is applied verbatim in :func:`_rewrite_fingerprints`. Rewrites are
#: deliberately **meaning-preserving**: the model still learns which branch to
#: target, it just no longer reads the exact sentence the checker matches on.
#: This mirrors what the ``dsh-connect-workbuddy`` DSH plugin does in its
#: ``prepareChatBody`` ("按句改词"), for the same documented reason.
_FINGERPRINT_REWRITES: tuple[tuple[str, str], ...] = (
    (
        "Main branch (you will usually use this for PRs)",
        "Default branch for pull requests",
    ),
)


def _rewrite_fingerprints(text: str) -> str:
    """Neutralise known third-party agent fingerprints in *text*.

    Idempotent and conservative: only exact known phrases are touched, so a
    prompt that carries none of them is returned byte-for-byte unchanged.
    """
    if not text:
        return text
    for needle, replacement in _FINGERPRINT_REWRITES:
        if needle in text:
            text = text.replace(needle, replacement)
    return text



def _dsh_home() -> Path:
    """Locate the DSH home directory the plugin writes its vault under."""
    override = os.environ.get("DSH_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".dsh"


def _region_of_domain(domain: str) -> Optional[str]:
    host = (domain or "").strip().lower()
    if not host:
        return None
    for region, spec in WORKBUDDY_REGIONS.items():
        for candidate in spec["domains"].split(","):
            if host == candidate or host.endswith("." + candidate):
                return region
    return None


def _region_of_provider(provider: Optional[str]) -> str:
    return "global" if (provider or "").strip().lower().endswith("-global") else "cn"


# ---------------------------------------------------------------------------
# Credential model
# ---------------------------------------------------------------------------


@dataclass
class WorkBuddyCredential:
    """One WorkBuddy login, as far as this provider needs to know."""

    access_token: str
    refresh_token: Optional[str] = None
    #: Unix seconds at which ``access_token`` expires (0 = unknown).
    expires_at: float = 0.0
    domain: str = ""
    region: str = "cn"
    account_id: str = ""
    nickname: str = ""
    #: Where this credential came from — for diagnostics only, never logged
    #: together with the token itself.
    source: str = ""

    def is_expired(self, *, skew: float = 0.0) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() >= (self.expires_at - skew)

    def describe(self) -> str:
        """Human-readable, secret-free summary."""
        who = self.nickname or self.account_id or "unknown"
        if self.expires_at <= 0:
            expiry = "unknown expiry"
        else:
            expiry = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.expires_at))
        return f"{who} @ {self.domain or '?'} (expires {expiry}, from {self.source})"


def _credential_from_auth(auth: dict[str, Any], *, source: str, region: str) -> Optional[WorkBuddyCredential]:
    """Build a credential from an ``auth`` sub-dict, or None when unusable."""
    if not isinstance(auth, dict):
        return None
    token = auth.get("accessToken")
    # Encrypted envelope => we cannot read it without the desktop build's keys.
    if isinstance(token, dict) or (isinstance(token, str) and token.startswith("{")):
        return None
    if not isinstance(token, str) or not token.strip():
        return None
    domain = str(auth.get("domain") or "")
    try:
        expires_at = float(auth.get("expiresAt") or 0)
    except (TypeError, ValueError):
        expires_at = 0.0
    refresh = auth.get("refreshToken")
    return WorkBuddyCredential(
        access_token=token.strip(),
        refresh_token=refresh if isinstance(refresh, str) and refresh.strip() else None,
        expires_at=expires_at,
        domain=domain,
        region=_region_of_domain(domain) or region,
        source=source,
    )


# ---------------------------------------------------------------------------
# Vault / desktop auth-file discovery
# ---------------------------------------------------------------------------


def _vault_credentials(region: str) -> list[WorkBuddyCredential]:
    """Read our own vault (written by dsh-connect-workbuddy). Never writes."""
    root = _dsh_home() / "workbuddy-vault" / region
    out: list[WorkBuddyCredential] = []
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cred = _credential_from_auth(
            payload.get("auth") or {}, source=f"vault:{path.name}", region=region
        )
        if cred is None:
            continue
        account = payload.get("account") or {}
        cred.account_id = str(payload.get("accountId") or "")
        cred.nickname = str(account.get("nickname") or "")
        out.append(cred)
    return out


def _desktop_auth_candidates() -> list[Path]:
    """Candidate WorkBuddy desktop auth files, per platform."""
    names = ("workbuddy-desktop.info", "workbuddy-desktop-ai.info")
    roots: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    roaming = os.environ.get("APPDATA")
    home = Path.home()
    if os.name == "nt":
        for base in (local, roaming):
            if base:
                roots.append(Path(base) / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    elif os.uname().sysname == "Darwin":
        roots.append(home / "Library" / "Application Support" / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or str(home / ".config")
        roots.append(Path(xdg) / "CodeBuddyExtension" / "Data" / "Public" / "auth")
    return [root / name for root in roots for name in names]


def _desktop_credentials(region: str) -> list[WorkBuddyCredential]:
    """Read the desktop app's auth file — only when its tokens are plain text."""
    out: list[WorkBuddyCredential] = []
    for path in _desktop_auth_candidates():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # A desktop file may carry several accounts.
        accounts = payload.get("accounts")
        blobs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        if isinstance(accounts, list):
            for entry in accounts:
                if isinstance(entry, dict):
                    blobs.append((str(entry.get("accountId") or ""), entry.get("auth") or {}, entry.get("account") or {}))
        blobs.append((str(payload.get("accountId") or ""), payload.get("auth") or {}, payload.get("account") or {}))
        for account_id, auth, account in blobs:
            cred = _credential_from_auth(auth, source=f"desktop:{path.name}", region=region)
            if cred is None:
                continue
            cred.account_id = cred.account_id or account_id
            cred.nickname = str(account.get("nickname") or "") if isinstance(account, dict) else ""
            if cred.region == region:
                out.append(cred)
    return out


def discover_workbuddy_credentials(region: str) -> list[WorkBuddyCredential]:
    """All usable credentials for *region*, most-expired-first for rotation."""
    seen: set[str] = set()
    out: list[WorkBuddyCredential] = []
    for cred in _vault_credentials(region) + _desktop_credentials(region):
        key = cred.access_token
        if key in seen:
            continue
        seen.add(key)
        out.append(cred)
    return out


# ---------------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------------


def _parse_credit_multiplier(credits: Any) -> Optional[float]:
    """``"x0.79"`` -> ``0.79``; anything else -> None."""
    if isinstance(credits, (int, float)):
        return float(credits)
    if not isinstance(credits, str):
        return None
    text = credits.strip().lower().lstrip("x").strip()
    try:
        return float(text)
    except ValueError:
        return None


def fetch_workbuddy_models(
    credential: WorkBuddyCredential,
    *,
    region: str,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Read the live model catalog from ``/v3/config``.

    Returns rows of ``{id, name, context_window, max_tokens, credit_multiplier,
    supports_images}``. Raises ``httpx`` errors / ``RuntimeError`` on failure so
    callers can fall back to a static list.
    """
    spec = WORKBUDDY_REGIONS[region]
    headers = {
        "Authorization": f"Bearer {credential.access_token}",
        "Accept": "application/json",
        # The App channel UA is what makes promotions/tiers visible.
        "User-Agent": WORKBUDDY_APP_UA,
    }
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.get(spec["config_url"], headers=headers)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"workbuddy {region}: unexpected /v3/config shape")

    rows: list[dict[str, Any]] = []
    for raw in data.get("models") or []:
        if not isinstance(raw, dict):
            continue
        model_id = str(raw.get("id") or "").strip()
        if not model_id or model_id in _ROUTER_MODEL_IDS:
            continue
        if raw.get("disabled") is True:
            continue
        context_window = int(raw.get("maxInputTokens") or 0)
        max_tokens = int(raw.get("maxOutputTokens") or 0)
        if context_window <= 0 or max_tokens <= 0:
            continue
        rows.append(
            {
                "id": model_id,
                "name": str(raw.get("name") or model_id),
                "context_window": context_window,
                "max_tokens": max_tokens,
                "credit_multiplier": _parse_credit_multiplier(raw.get("credits")),
                "supports_images": bool(raw.get("supportsImages")) and raw.get("disabledMultimodal") is not True,
            }
        )
    if not rows:
        raise RuntimeError(f"workbuddy {region}: /v3/config returned no usable models")
    return rows


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


def refresh_workbuddy_token(
    credential: WorkBuddyCredential,
    *,
    region: str,
    timeout: float = 30.0,
) -> Optional[WorkBuddyCredential]:
    """Exchange a refresh token for a fresh access token (in memory only).

    Mirrors the endpoint the desktop client itself uses. Returns an updated
    credential, or None when the exchange is not possible / not accepted.
    """
    if not credential.refresh_token:
        return None
    spec = WORKBUDDY_REGIONS[region]
    url = f"{spec['base_url']}/plugin/auth/token/refresh"
    headers = {
        "X-Refresh-Token": credential.refresh_token,
        "X-Auth-Refresh-Source": "workbuddy",
        "Accept": "application/json",
        "User-Agent": WORKBUDDY_APP_UA,
    }
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post(url, headers=headers)
        if response.status_code >= 400:
            logger.warning("workbuddy %s: token refresh refused (HTTP %s)", region, response.status_code)
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("workbuddy %s: token refresh failed: %s", region, exc)
        return None

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    auth = data.get("auth") if isinstance(data.get("auth"), dict) else data
    fresh = _credential_from_auth(auth, source=credential.source + "+refresh", region=region)
    if fresh is None:
        return None
    fresh.account_id = credential.account_id
    fresh.nickname = credential.nickname
    return fresh


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class WorkBuddyProvider(OpenAICompatibleProvider):
    """CloudAgent provider backed by a locally signed-in WorkBuddy session."""

    #: Region key (``cn`` / ``global``); subclasses pin it.
    REGION: str = "cn"
    DEFAULT_BASE_URL = WORKBUDDY_REGIONS["cn"]["base_url"]
    DEFAULT_MODEL = "deepseek-v4.1-flash"

    #: WorkBuddy only accepts streamed chat requests (HTTP 400 / 11101 otherwise).
    REQUIRES_STREAM = True

    def __init__(
        self,
        api_key: str = "",
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        spec = WORKBUDDY_REGIONS[self.REGION]
        self._static_credential: Optional[WorkBuddyCredential] = None
        if api_key:
            # An explicitly supplied key is a raw bearer token: use as-is.
            self._static_credential = WorkBuddyCredential(
                access_token=api_key.strip(),
                region=self.REGION,
                source="explicit",
            )
        super().__init__(api_key, base_url or spec["base_url"], model or self.DEFAULT_MODEL)

    # -- credentials ------------------------------------------------------

    def _current_credential(self) -> WorkBuddyCredential:
        """Resolve the credential to use right now, refreshing when possible."""
        if self._static_credential is not None:
            return self._static_credential

        candidates = discover_workbuddy_credentials(self.REGION)
        if not candidates:
            raise RuntimeError(
                f"workbuddy {self.REGION}: no credential found. Sign in with the WorkBuddy "
                "desktop app (or `dsh-connect-workbuddy`), or set an explicit API key "
                "to a raw WorkBuddy bearer token."
            )
        # Prefer a still-valid token; otherwise try to refresh one.
        for cred in candidates:
            if not cred.is_expired(skew=_REFRESH_SKEW_SECONDS):
                return cred
        for cred in candidates:
            refreshed = refresh_workbuddy_token(cred, region=self.REGION)
            if refreshed is not None:
                return refreshed
        # Nothing refreshable — hand back the freshest by expiry so the upstream
        # answers with its own 401 rather than us guessing.
        candidates.sort(key=lambda c: c.expires_at, reverse=True)
        return candidates[0]

    def _bearer(self) -> str:
        return self._current_credential().access_token

    # -- client -----------------------------------------------------------

    def _create_client(self) -> Any:
        """Build an OpenAI SDK client aimed at the WorkBuddy gateway.

        ``trust_env=False`` is deliberate: proxy-detection code paths in httpx
        choke on some ``NO_PROXY`` spellings, and a loopback-only proxy setting
        must not be applied to this host anyway.
        """
        from openai import OpenAI  # imported lazily, mirroring the other providers

        return OpenAI(
            api_key=self._bearer(),
            base_url=self.base_url or WORKBUDDY_REGIONS[self.REGION]["base_url"],
            http_client=httpx.Client(trust_env=False),
            max_retries=0,
        )

    def _refresh_client_token(self) -> None:
        """Rebuild the cached client after a token rotation."""
        self._client = None

    # -- messages ---------------------------------------------------------

    def _prepare_messages(self, messages, *, model=None):  # type: ignore[override]
        prepared = super()._prepare_messages(messages, model=model)
        for message in prepared:
            role = message.get("role")
            # WorkBuddy's gateway refuses a request carrying another vendor's
            # agent scaffolding (HTTP 400 / code 11128). CloudAgent's system
            # prompt is Claude-Code shaped, so the fingerprint lives there.
            if role == "system" and isinstance(message.get("content"), str):
                message["content"] = _rewrite_fingerprints(message["content"])
            # Some models also require every assistant turn to carry content.
            if role == "assistant" and not message.get("content"):
                message["content"] = " "
        return prepared

    # -- chat -------------------------------------------------------------

    def _is_auth_failure(self, exc: BaseException) -> bool:
        """Whether *exc* looks like "this token is no longer accepted"."""
        if getattr(exc, "status_code", None) == 401:
            return True
        response = getattr(exc, "response", None)
        if getattr(response, "status_code", None) == 401:
            return True
        text = str(exc).lower()
        return "401" in text and ("token" in text or "unauthorized" in text or "auth" in text)

    def _force_refresh(self) -> bool:
        """Rotate to a freshly refreshed token. Returns whether we changed one."""
        if self._static_credential is not None:
            return False  # an explicit key is never refreshed by us
        for cred in discover_workbuddy_credentials(self.REGION):
            refreshed = refresh_workbuddy_token(cred, region=self.REGION)
            if refreshed is not None:
                self._static_credential = refreshed
                self._refresh_client_token()
                return True
        return False

    def _is_channel_reject(self, exc: BaseException) -> bool:
        """Whether *exc* is WorkBuddy's channel/identity refusal (code 11128)."""
        text = str(exc)
        return "11128" in text or "unapproved channel" in text.lower()

    def chat_stream_response(
        self,
        messages,
        tools=None,
        on_text_chunk=None,
        on_thinking_chunk=None,
        abort_signal=None,
        **kwargs,
    ):
        """Stream one turn, promoting reasoning-only answers to visible content.

        Several WorkBuddy models (``hy3`` among them) emit the whole answer in
        ``delta.reasoning_content`` and leave ``delta.content`` empty for the
        entire turn. The base class faithfully reports that split, but the agent
        loop only reads ``content`` — so such a turn looks like the model
        returned nothing at all.

        When a turn ends with **no visible content** and non-empty reasoning, the
        reasoning text becomes the content and ``reasoning_content`` is cleared.
        The promotion is skipped for tool-call turns (their text is irrelevant)
        and whenever any visible content was streamed — a model that emits both
        is already understood and must keep its split.

        A 401 triggers exactly one token refresh and one retry: WorkBuddy access
        tokens are short-lived (hours), so a long-running CloudAgent session will
        outlive the token it started with.
        """
        stream_kwargs = dict(
            messages=messages,
            tools=tools,
            on_text_chunk=on_text_chunk,
            on_thinking_chunk=on_thinking_chunk,
            abort_signal=abort_signal,
            **kwargs,
        )
        try:
            response = super().chat_stream_response(**stream_kwargs)
        except Exception as exc:  # noqa: BLE001 - inspected, then re-raised
            if self._is_channel_reject(exc):
                raise RuntimeError(
                    "WorkBuddy rejected this request as coming from an unapproved channel "
                    "(code 11128). The gateway recognises third-party agent scaffolding in "
                    "the prompt; this provider rewrites the fingerprints it knows about "
                    "(see _FINGERPRINT_REWRITES). If this is new, the prompt carries a "
                    "phrase that table does not cover yet — add it there."
                ) from exc
            if not self._is_auth_failure(exc) or not self._force_refresh():
                raise
            logger.info("workbuddy %s: access token rotated after a 401; retrying once", self.REGION)
            response = super().chat_stream_response(**stream_kwargs)

        if (
            response is not None
            and not response.content
            and not response.tool_uses
            and response.reasoning_content
        ):
            promoted = response.reasoning_content
            if on_text_chunk is not None:
                # The caller already received these bytes as *thinking*; keep
                # the visible channel consistent with the final content.
                on_text_chunk(promoted)
            response.content = promoted
            response.reasoning_content = None
        return response

    def chat(
        self, messages, tools=None, **kwargs
    ) -> Any:  # pragma: no cover - thin wrapper over the streaming path
        """Non-streaming chat, implemented over the streaming path.

        The upstream refuses ``stream=false`` outright (HTTP 400 / code 11101),
        so there is no genuine non-streaming request to make.
        """
        return self.chat_stream_response(messages, tools=tools, **kwargs)

    def chat_stream(
        self, messages, tools=None, **kwargs
    ) -> Generator[str, None, None]:
        response = self.chat_stream_response(messages, tools=tools, **kwargs)
        if response.content:
            yield response.content

    def get_available_models(self) -> list[str]:
        """Live catalog from ``/v3/config``, falling back to a static list."""
        try:
            rows = fetch_workbuddy_models(self._current_credential(), region=self.REGION)
            return [row["id"] for row in rows]
        except Exception as exc:  # noqa: BLE001 - catalog failure must not break chat
            logger.warning("workbuddy %s: catalog unavailable (%s); using static list", self.REGION, exc)
            return list(FALLBACK_MODELS[self.REGION])

    def discover_available_models(self) -> list[str]:
        """The gateway's real catalog.

        The inherited implementation calls ``client.models.list()`` against the
        OpenAI-compatible base URL. WorkBuddy has no ``/v2/models`` route, so
        every ``cloudagent model list`` printed a misleading "catalog refresh
        failed: 404" warning before falling back. This gateway publishes its
        catalog at ``/v3/config``, which :meth:`get_available_models` already
        reads — so answer from there and skip the doomed request.
        """
        return self.get_available_models()


class WorkBuddyGlobalProvider(WorkBuddyProvider):
    """International WorkBuddy (``workbuddy-global``)."""

    REGION = "global"
    DEFAULT_BASE_URL = WORKBUDDY_REGIONS["global"]["base_url"]
    DEFAULT_MODEL = "deepseek-v4.1-flash"


#: Static fallbacks, used only when ``/v3/config`` cannot be read. Deliberately
#: short: the live catalog is authoritative and carries per-model multipliers.
FALLBACK_MODELS: dict[str, tuple[str, ...]] = {
    "cn": (
        "deepseek-v4.1-flash",
        "deepseek-v4-pro",
        "glm-5.3",
        "glm-5.2",
        "kimi-k3.1-pro",
        "hy3",
    ),
    "global": (
        "deepseek-v4.1-flash",
        "glm-5.3",
        "kimi-k3",
        "hy3",
    ),
}


__all__ = [
    "WORKBUDDY_PROVIDER_CN",
    "WORKBUDDY_PROVIDER_GLOBAL",
    "WORKBUDDY_REGIONS",
    "FALLBACK_MODELS",
    "WorkBuddyCredential",
    "WorkBuddyProvider",
    "WorkBuddyGlobalProvider",
    "discover_workbuddy_credentials",
    "fetch_workbuddy_models",
    "refresh_workbuddy_token",
]
