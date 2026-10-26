"""Canonical settings-file paths for permission persistence.
, with the project tier
namespaced under ``.cloudagent/`` rather than 's ``.claude/``: the real
CloudAgent harness owns ``<project>/.claude/settings{,.local}.json``, and a
second tool reading/writing the SAME files would inherit and mutate the
harness's live permission rules (review-A finding, C1). The file LAYOUT is
still -parity — standalone settings files with a top-level ``permissions``
key (the shape ``setup.py``/``updates.py`` share) — NOT the config manager's
``"settings"`` sub-key layer and NOT ``~/.cloudagent/config.json``.
"""

from __future__ import annotations

import os

from .types import PermissionUpdateDestination

USER_SETTINGS_FILENAME = os.path.join("~", ".cloudagent", "settings.json")
PROJECT_SETTINGS_DIRNAME = ".cloudagent"


def user_settings_path() -> str:
    return os.path.expanduser(USER_SETTINGS_FILENAME)


def project_settings_path(cwd: str | None = None) -> str:
    base = cwd or os.getcwd()
    return os.path.join(base, PROJECT_SETTINGS_DIRNAME, "settings.json")


def local_settings_path(cwd: str | None = None) -> str:
    base = cwd or os.getcwd()
    return os.path.join(base, PROJECT_SETTINGS_DIRNAME, "settings.local.json")


def settings_path_for_destination(
    destination: PermissionUpdateDestination,
    cwd: str | None = None,
) -> str | None:
    """``SettingsPathResolver`` for:func:`persist_permission_update`.
    ``session`` and ``cliArg`` are in-memory only → ``None`` (the persist
    helpers treat ``None`` as non-persistable, matching ).
    """

    if destination == "userSettings":
        return user_settings_path()
    if destination == "projectSettings":
        return project_settings_path(cwd)
    if destination == "localSettings":
        return local_settings_path(cwd)
    return None


def default_setup_paths(cwd: str | None = None) -> dict[str, str | None]:
    """Keyword arguments for:func:`src.permissions.setup.setup_permissions`.
    ``setup_permissions`` has no default paths of its own — every caller
    must supply them. This is the one canonical place they come from.
    """

    from cloudagent_ext.settings.managed_path import resolve_managed_settings_path

    managed = resolve_managed_settings_path()
    return {
        "user_settings_path": user_settings_path(),
        "project_settings_path": project_settings_path(cwd),
        "local_settings_path": local_settings_path(cwd),
        "managed_settings_path": str(managed) if managed else None,
    }


__all__ = [
    "settings_path_for_destination",
    "default_setup_paths",
    "user_settings_path",
    "project_settings_path",
    "local_settings_path",
]
