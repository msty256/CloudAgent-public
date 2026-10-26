"""Configuration management for CloudAgent.
Three-level config hierarchy matching TypeScript:
  Global: ~/.cloudagent/config.json
  Project: <git-root>/.cloudagent/config.json
  Local: <git-root>/.cloudagent/config.local.json
Inheritance: local > project > global (deep merge).
The pydantic-settings backend lives in
``cloudagent_ext/settings/pydantic_adapter.py`` (gate controlled by
``CLOUDAGENT_USE_PYDANTIC_SETTINGS``). This module only implements the
legacy JSON backend.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GLOBAL_CONFIG_DIR = Path.home() / '.cloudagent'
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / 'config.json'
HISTORY_FILE = GLOBAL_CONFIG_DIR / 'history.jsonl'

PROJECT_CONFIG_DIR_NAME = '.cloudagent'
LEGACY_PROJECT_CONFIG_DIR_NAME = '.claude'
PROJECT_CONFIG_FILE_NAME = 'config.json'
LOCAL_CONFIG_FILE_NAME = 'config.local.json'


def _find_git_root(cwd: str | Path | None = None) -> Path | None:
    """Find the git root directory starting from *cwd*."""
    start = Path(cwd) if cwd else Path.cwd()
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(start),
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


def get_global_config_path() -> Path:
    return GLOBAL_CONFIG_FILE


def get_project_config_path(cwd: str | Path | None = None) -> Path | None:
    root = _find_git_root(cwd)
    if root is None:
        return None
    return root / PROJECT_CONFIG_DIR_NAME / PROJECT_CONFIG_FILE_NAME


def get_local_config_path(cwd: str | Path | None = None) -> Path | None:
    root = _find_git_root(cwd)
    if root is None:
        return None
    return root / PROJECT_CONFIG_DIR_NAME / LOCAL_CONFIG_FILE_NAME


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Atomic JSON I/O
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file, returning empty dict on any error."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.debug('Failed to read config %s: %s', path, exc)
        return {}
    if not isinstance(data, dict):
        # A non-object top level previously flowed into _deep_merge and
        # raised AttributeError at the call site (C6 review M2) — treat
        # it like any other unreadable config: ignored.
        logger.debug("Ignoring non-object config %s", path)
        return {}
    return data


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically via temp-file + rename, chmod 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, str(path))
        if os.name != 'nt':
            os.chmod(str(path), 0o600)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------


def get_default_config() -> dict[str, Any]:
    """Generate default global configuration."""
    try:
        from cloudagent_ext.providers import PROVIDER_INFO

        from cloudagent_ext.providers import _init_provider_extensions

        _init_provider_extensions()

        providers = {
            name: {
                'api_key': '',
                'base_url': info['default_base_url'],
                'default_model': info['default_model'],
            }
            for name, info in PROVIDER_INFO.items()
        }
    except Exception:
        providers = {}

    return {
        'default_provider': 'anthropic',
        'providers': providers,
        'session': {'auto_save': True, 'max_history': 100},
    }


# Keys a committable project/local config tier may NOT contribute while the
# session is untrusted. ``providers``/``default_provider`` would redirect API
# traffic to a config-controlled host while the user's global credentials
# remain attached; ``env`` is owned by permissions.trust_boundary's gated
# passes. ( has no analogue: its project files contribute settings only.)
_UNTRUSTED_TIER_BLOCKED_KEYS: frozenset[str] = frozenset(
    {"env", "providers", "default_provider"}
)


def _session_trusted(cwd: str | Path | None = None) -> bool:
    """Return the trust verdict for the workspace being loaded.
    The persisted cwd-scoped verdict is required by agent-server children,
    which do not inherit the parent's in-process bootstrap flag.
    """
    try:
        from cloudagent_ext.services.startup_gates import check_trust_accepted

        return check_trust_accepted(cwd)
    except Exception:
        return False


def _strip_untrusted_keys(tier: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in tier.items()
        if key not in _UNTRUSTED_TIER_BLOCKED_KEYS
    }


# ---------------------------------------------------------------------------
# ConfigManager — three-level loading + merge
# ---------------------------------------------------------------------------


@dataclass
class ConfigManager:
    """Manages the three-level config hierarchy."""

    cwd: str | Path | None = None
    _global_cache: dict[str, Any] | None = field(default=None, repr=False)
    _project_cache: dict[str, Any] | None = field(default=None, repr=False)
    _local_cache: dict[str, Any] | None = field(default=None, repr=False)

    def invalidate(self) -> None:
        self._global_cache = None
        self._project_cache = None
        self._local_cache = None

    # --- loaders ---

    def load_global(self) -> dict[str, Any]:
        if self._global_cache is None:
            path = get_global_config_path()
            on_disk = _read_json(path) if path.exists() else {}
            self._global_cache = _deep_merge(get_default_config(), on_disk)
        return dict(self._global_cache)

    def load_project(self) -> dict[str, Any]:
        if self._project_cache is None:
            path = get_project_config_path(self.cwd)
            current = _read_json(path) if path else {}
            root = _find_git_root(self.cwd)
            legacy = (
                _read_json(root / LEGACY_PROJECT_CONFIG_DIR_NAME / PROJECT_CONFIG_FILE_NAME)
                if root
                else {}
            )
            self._project_cache = _deep_merge(legacy, current)
        return dict(self._project_cache)

    def load_local(self) -> dict[str, Any]:
        if self._local_cache is None:
            path = get_local_config_path(self.cwd)
            current = _read_json(path) if path else {}
            root = _find_git_root(self.cwd)
            legacy = (
                _read_json(root / LEGACY_PROJECT_CONFIG_DIR_NAME / LOCAL_CONFIG_FILE_NAME)
                if root
                else {}
            )
            self._local_cache = _deep_merge(legacy, current)
        return dict(self._local_cache)

    def get_merged(self) -> dict[str, Any]:
        """Return fully merged config: global < project < local.
        While the session is untrusted, the project/local tiers are
        stripped of trust-sensitive keys before merging (ch02 round-3
        gap A5): a committable ``.cloudagent/config.json`` must not be able
        to redirect API traffic (``providers.*.base_url`` riding the
        user's global ``api_key``) or inject env before the folder-trust
        gate. Checked at merge time so a mid-session trust grant takes
        effect on the next read. Env application is separately owned by
        ``permissions.trust_boundary``; the ``env`` strip here is
        defense in depth for direct ``get_merged()["env"]`` readers.
        """
        merged = self.load_global()
        project = self.load_project()
        local = self.load_local()
        if not _session_trusted(self.cwd):
            project = _strip_untrusted_keys(project)
            local = _strip_untrusted_keys(local)
        merged = _deep_merge(merged, project)
        merged = _deep_merge(merged, local)
        return merged

    # --- writers ---

    def save_global(self, data: dict[str, Any]) -> None:
        _atomic_write_json(get_global_config_path(), data)
        self._global_cache = None

    def save_project(self, data: dict[str, Any]) -> None:
        path = get_project_config_path(self.cwd)
        if path is None:
            raise RuntimeError('No git root found — cannot save project config')
        _atomic_write_json(path, data)
        self._project_cache = None

    def save_local(self, data: dict[str, Any]) -> None:
        path = get_local_config_path(self.cwd)
        if path is None:
            raise RuntimeError('No git root found — cannot save local config')
        _atomic_write_json(path, data)
        self._local_cache = None

    # --- convenience ---

    def get(self, key: str, default: Any = None) -> Any:
        return self.get_merged().get(key, default)

    def set_global(self, key: str, value: Any) -> None:
        cfg = self.load_global()
        cfg[key] = value
        self.save_global(cfg)

    def set_project(self, key: str, value: Any) -> None:
        cfg = self.load_project()
        cfg[key] = value
        self.save_project(cfg)


# ---------------------------------------------------------------------------
# Per-project state in the GLOBAL config ( config.projects[path])
# ---------------------------------------------------------------------------
# keeps per-project security state (hasTrustDialogAccepted,
# hasClaudeMdExternalIncludesApproved,...) in the USER-owned global
# config keyed by project path — deliberately NOT in the committable
# project config, so a checked-out repo can never pre-accept its own
# trust prompts. Same here: ``~/.cloudagent/config.json`` → "projects".

_PROJECTS_KEY = "projects"


def _global_config_file() -> Path:
    # Resolve through the module attribute at call time so test
    # isolation that re-points GLOBAL_CONFIG_DIR covers these helpers.
    return Path(GLOBAL_CONFIG_DIR) / "config.json"


def normalize_path_for_config_key(path: str | Path) -> str:
    """Canonical absolute path used as a ``projects`` map key."""

    return str(Path(path).resolve())


def get_project_path_for_config(cwd: str | Path | None = None) -> str:
    """Where per-project state is keyed: git root if in a repo, else cwd
    ( ``getProjectPathForConfig``)."""

    root = _find_git_root(cwd)
    if root is not None:
        return normalize_path_for_config_key(root)
    return normalize_path_for_config_key(cwd or Path.cwd())


def get_project_entry(project_path: str | Path) -> dict[str, Any]:
    """The global-config ``projects[path]`` entry ({} if absent)."""

    config = _read_json(_global_config_file())
    projects = config.get(_PROJECTS_KEY)
    if not isinstance(projects, dict):
        return {}
    entry = projects.get(normalize_path_for_config_key(project_path))
    return entry if isinstance(entry, dict) else {}


def update_project_entry(
    project_path: str | Path, updates: dict[str, Any]
) -> bool:
    """Merge *updates* into ``projects[path]`` in the global config."""

    path = _global_config_file()
    config = _read_json(path)
    projects = config.get(_PROJECTS_KEY)
    if not isinstance(projects, dict):
        projects = {}
    key = normalize_path_for_config_key(project_path)
    entry = projects.get(key)
    if not isinstance(entry, dict):
        entry = {}
    entry.update(updates)
    projects[key] = entry
    config[_PROJECTS_KEY] = projects
    try:
        _atomic_write_json(path, config)
    except OSError:
        return False
    _get_default_manager().invalidate()
    try:
        from cloudagent_ext.services.startup_gates import _invalidate_trust_memo

        _invalidate_trust_memo()
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# History (JSONL paste history)
# ---------------------------------------------------------------------------


def append_history_entry(content: str, *, source: str = 'paste') -> None:
    """Append a history entry to the JSONL history file."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {'timestamp': time.time(), 'source': source, 'content': content}
    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def read_history_entries(limit: int = 100) -> list[dict[str, Any]]:
    """Read recent history entries."""
    if not HISTORY_FILE.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        return []
    return entries[-limit:]


# ---------------------------------------------------------------------------
# Backward-compatible API (used by existing code)
# ---------------------------------------------------------------------------

_default_manager: ConfigManager | None = None


def _get_default_manager() -> ConfigManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = ConfigManager()
    return _default_manager


def get_config_path() -> Path:
    """Get the path to the global configuration file."""
    return get_global_config_path()


def load_config() -> dict[str, Any]:
    """Load merged configuration."""
    return _get_default_manager().get_merged()


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to global config file."""
    _get_default_manager().save_global(config)


def get_provider_config(provider: str) -> dict[str, Any]:
    """Get configuration for a specific provider.
    The literal ``provider`` key is tried first, so a pre-rename block such as
    ``[providers.glm]`` still resolves by its own key. When the literal name is
    absent, fall back to the canonical id so an alias (``nim`` -> ``nvidia-nim``,
    ``glm`` -> ``zai``, ``kimi`` -> ``moonshot`` …) passed via ``--provider``
    resolves to the provider's default config block.
    """
    config = load_config()
    providers = config.get('providers', {})
    if provider in providers:
        resolved = provider
    else:
        try:
            from cloudagent_ext.providers import canonical_provider_name

            canonical = canonical_provider_name(provider)
        except Exception:
            canonical = provider
        if canonical != provider and canonical in providers:
            resolved = canonical
        else:
            raise ValueError(f'Unknown provider: {provider}')
    cfg = dict(providers[resolved])
    # Fall back to environment variables when config file has empty values.
    env_key = os.environ.get(f'{provider.upper()}_API_KEY')
    if not cfg.get('api_key') and env_key:
        cfg['api_key'] = env_key
    env_base = os.environ.get(f'{provider.upper()}_BASE_URL')
    if not cfg.get('base_url') and env_base:
        cfg['base_url'] = env_base
    env_model = os.environ.get(f'{provider.upper()}_MODEL')
    if not cfg.get('default_model') and env_model:
        cfg['default_model'] = env_model
    return cfg


def set_api_key(
    provider: str,
    api_key: str,
    base_url: Optional[str] = None,
    default_model: Optional[str] = None,
) -> None:
    """Set API key for a provider."""
    mgr = _get_default_manager()
    config = mgr.load_global()
    if 'providers' not in config:
        config['providers'] = {}
    if provider not in config['providers']:
        config['providers'][provider] = {}
    config['providers'][provider]['api_key'] = api_key
    if base_url is not None:
        config['providers'][provider]['base_url'] = base_url
    if default_model is not None:
        config['providers'][provider]['default_model'] = default_model
        # Maintain a deduplicated models list so config-aware UIs
        # (e.g. REPL /model) can offer the user's known models
        # even when they are not in the built-in ModelRegistry.
        models: list[str] = config['providers'][provider].get('models', [])
        if default_model not in models:
            models.append(default_model)
        config['providers'][provider]['models'] = models
    mgr.save_global(config)


def set_default_provider(provider: str) -> None:
    """Set the default provider."""
    mgr = _get_default_manager()
    config = mgr.load_global()
    config['default_provider'] = provider
    mgr.save_global(config)


def get_default_provider() -> str:
    """Get the default provider."""
    return load_config().get('default_provider', 'anthropic')


def set_theme(name: str) -> None:
    """Persist the selected theme to the global config.
    ``saveGlobalConfig(c => ({...c, theme: setting}))``). Uses ``set_global``
    (global-only) — **not** ``load_config()`` + ``save_config()``, which would
    serialize the *merged* (global+project+local) config back into the global file.
    """
    _get_default_manager().set_global('theme', name)


def set_logo_color(name: str) -> None:
    """Persist the startup logo color palette to the global config.
    top-level config key (like:func:`set_theme`), read via
    ``load_config().get("logoColor")`` by the startup banners — NOT a nested settings
    field.
    """
    _get_default_manager().set_global("logoColor", name)


def set_effort(value: Optional[str]) -> None:
    """Persist the reasoning-effort choice to user settings (``settings.effort``)
    and invalidate the settings read-cache.
    Mirrors ``updateSettingsForSource('userSettings', {effortLevel})``
    . A ``value`` of ``None``/``""`` clears the
    setting (auto). Unlike:func:`set_theme` (a top-level config key), effort is a
    *settings* field (``src/settings/types.py``), read via ``get_settings()``, so it
    lives in the nested ``"settings"`` section of the global config. Pattern copied
    from ``state/app_state._on_advisor_model_change``; the local import avoids a
    config→settings import cycle. After writing, the settings cache is invalidated so
    the next ``get_settings()`` reflects the new value immediately (mid-session).
    """
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    # None / "" both map to "auto" — write empty string for round-trip fidelity
    # with the SettingsSchema default (settings/types.py: effort: str = "").
    section['effort'] = value or ''
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


def set_selection_mode(mode: str) -> None:
    """Persist the selection mode (``"number"`` or ``"arrow"``) to global config.
    Controls whether ``AskUserQuestion`` prompts accept number-key input
    or arrow-key navigation in the TUI. Follows the ``set_theme`` convention:
    writes to the global config file only (not merged).
    """
    _get_default_manager().set_global('selection_mode', mode)


def get_selection_mode() -> str:
    """Read the persisted selection mode. Defaults to ``"arrow"`` (supports both ↑↓ arrow keys and 1-9 digit keys)."""
    return load_config().get('selection_mode') or 'arrow'


# ── F-64 Voice Mode persistence ──────────────────────────────────────────────
# These follow the ``set_effort`` pattern (nested ``"settings"`` section,
# not a top-level key, since the values are read via ``get_settings()``).
# Both clear the settings read-cache so the next ``get_settings()`` reflects
# the change mid-session.

def set_voice_provider(value: Optional[str]) -> None:
    """Persist the STT backend choice (``"anthropic"`` | ``"doubao"`` | None).
    Mirrors ``updateSettingsForSource('userSettings', {voiceProvider})``
    . ``None``/``""`` clears the field (= unset,
    read-side falls back to ``"anthropic"``). Invalid values are coerced to
    ``""`` rather than raising — the read-side default is the safety net.
    F-64 P64-A: gates which STT provider ``connect_voice_stream`` selects
    at recording time. See ``cloudagent_ext.services.voice.voice_mode_enabled``.
    """
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    normalized = (value or '').strip().lower()
    if normalized not in ('anthropic', 'doubao'):
        normalized = ''  # invalid / empty → unset, read-side defaults to anthropic
    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['voice_provider'] = normalized
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


def set_voice_enabled(enabled: bool) -> None:
    """Persist the voice-mode master switch (``settings.voice_enabled``).
    the push-to-talk hotkey is inert regardless of provider configuration.
    Decoupled from:func:`set_voice_provider` so ``/voice doubao`` can flip
    both atomically while ``/voice anthropic`` only touches the provider.
    """
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['voice_enabled'] = bool(enabled)
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


# ── F-64 P64-E: TTS setters ────────────────────────────────────────────────

def set_tts_provider(value: Optional[str]) -> None:
    """Persist the TTS backend choice (``"openai"`` | ``"minimax"`` | ``"gemini"`` | None)."""
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    normalized = (value or '').strip().lower()
    if normalized not in ('openai', 'minimax', 'gemini'):
        normalized = ''
    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['tts_provider'] = normalized
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


def set_tts_enabled(enabled: bool) -> None:
    """Persist the TTS master switch (``settings.tts_enabled``)."""
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['tts_enabled'] = bool(enabled)
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


def set_tts_voice(value: Optional[str]) -> None:
    """Persist the TTS voice id (``settings.tts_voice``)."""
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    normalized = (value or '').strip()
    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['tts_voice'] = normalized
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


# ── F-65 P65-D: dialogue setters ───────────────────────────────────────────


def set_dialogue_provider(value: Optional[str]) -> None:
    """Persist the F-65 dialogue backend choice (``"minimax"`` | None)."""
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    normalized = (value or '').strip().lower()
    if normalized not in ('minimax', 'openai-realtime'):
        normalized = ''
    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['dialogue_provider'] = normalized
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


def set_dialogue_enabled(enabled: bool) -> None:
    """Persist the F-65 full-duplex dialogue master switch."""
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['dialogue_enabled'] = bool(enabled)
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


def set_dialogue_voice(value: Optional[str]) -> None:
    """Persist the F-65 dialogue TTS voice id (``settings.dialogue_voice``)."""
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    normalized = (value or '').strip()
    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['dialogue_voice'] = normalized
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()


def set_dialogue_modality(value: Optional[str]) -> None:
    """Persist the F-65 output modality (``"text"`` | ``"audio"``)."""
    from cloudagent_ext.settings.settings import invalidate_settings_cache

    normalized = (value or '').strip().lower()
    if normalized not in ('text', 'audio'):
        normalized = 'text'
    mgr = _get_default_manager()
    cfg = mgr.load_global()
    section = cfg.get('settings')
    if not isinstance(section, dict):
        section = {}
    section['dialogue_modality'] = normalized
    cfg['settings'] = section
    mgr.save_global(cfg)
    invalidate_settings_cache()
