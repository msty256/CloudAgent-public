#!/usr/bin/env bash

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

set -euo pipefail
# ERR trap: if a command fails under set -e, print the line number and
# failing command before exit.  Makes headless / TTY / CI failures
# self-diagnosing without requiring "bash -x".
set -E
trap 'log_err "Installer crash at line $LINENO: $BASH_COMMAND"' ERR

# ============================================================================
#  Config (read-only defaults)
# ============================================================================
# Versioning scheme
# -----------------
#   INSTALLER_VERSION  — version of this install.sh script
#   CLOUDAGENT_VERSION  — version of cloudagent that THIS install.sh installs
#   REPO_REF           — git ref (tag/branch) the install clones
#
# The install.sh script is released alongside the cloudagent tag it ships
# with, so INSTALLER_VERSION == CLOUDAGENT_VERSION for the bundle. Small
# script changes (typo fixes, log tweaks, new flags) do NOT bump the
# installer version — the version moves only when a new cloudagent tag
# is cut. To install a different cloudagent version, fetch the install.sh
# from that version's tag; an old install.sh still installs the old
# cloudagent (with its old uv.lock), never the bleeding edge.
# If REPO_REF doesn't resolve on the remote, the install falls back to the
# default branch with a loud warning — useful during the pre-tag period of
# a release but should never ship in a tagged installer.
readonly INSTALLER_VERSION="2026.6.24"
readonly CLOUDAGENT_VERSION="2026.6.24"
# REPO_REF is intentionally NOT readonly — it gets reassigned when the user
# passes --ref. Same for CLOUDAGENT_HOME / CLOUDAGENT_PARENT_DIR / CONFIG_DIR
# (derived from overridable defaults below).
REPO_REF="main"
readonly REPO_URL="https://github.com/msty256/cloudAgent"
# --- Overridable paths (defaults; overridden by --install-dir / --config-dir) ---
# Install dir = where the project source is cloned and (by default) the .venv lives.
# Config dir  = where cloudagent stores its runtime state (sessions, auth, history).
#               Exposed to the runtime via $CLOUDAGENT_CONFIG_DIR; the wrapper scripts
#               below set that env var on every invocation.
readonly DEFAULT_INSTALL_DIR="$HOME/.cloudagent/cloudagent"
readonly DEFAULT_CONFIG_DIR="$HOME/.cloudagent"
readonly LOCAL_BIN="$HOME/.local/bin"
readonly PYTHON_MIN_VERSION="3.11"
readonly PYTHON_MAX_SUPPORTED="3.13"
# Minimum disk space required for venv + dependencies (~500 MB)
readonly MIN_DISK_KB=$((512 * 1024))
readonly ENTRY_POINT="cloudagent"   # the single registered entry in pyproject.toml
readonly RC_MARKER="# cloudagent installer — managed by install.sh"
# --- Source layout ---
# cloudagent is a single-layer codebase: the former upstream ``src/``
# tree has been merged into ``cloudagent_ext/``.  There is no upstream fetch and
# no patch hydration step — the repo *is* the complete, runnable source.
# Directory this install.sh lives in — used for local-source detection.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || echo "$PWD")"
# ============================================================================
#  UI helpers
# ============================================================================
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
    C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[1;33m'
    C_BLUE=$'\033[0;34m'; C_BOLD=$'\033[1m'; C_RESET=$'\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_BOLD=''; C_RESET=''
fi

# Agent-friendly line prefix. Emitted only when stdout/stderr is not a TTY
# (i.e. when the script is being driven by another process, an agent, a CI
# runner, or a piped tee). Interactive users see clean output.
_script_p1() { [[ ! -t 1 ]] && printf '[install.sh] '; return 0; }
_script_p2() { [[ ! -t 2 ]] && printf '[install.sh] ' >&2; return 0; }

log_info() { _script_p1; echo -e "${C_BLUE}==>${C_RESET} ${C_BOLD}$1${C_RESET}"; }
log_ok()   { _script_p1; echo -e "  ${C_GREEN}✓${C_RESET} $1"; }
log_warn() { _script_p1; echo -e "  ${C_YELLOW}!${C_RESET} $1"; }
log_err()  { _script_p2; echo -e "${C_RED}✗${C_RESET} $1" >&2; }
log_step() { _script_p1; echo -e "\n${C_BOLD}${C_BLUE}>>>${C_RESET} ${C_BOLD}$1${C_RESET}"; }
die() { log_err "$1"; exit 1; }
# Like die(), but accepts 0+ "next steps" lines that are printed in a clear
# "what to do next" block. Designed for agent-driven installs where the
# failure handler needs to know what to retry.
#
# Usage: die_with_help "primary error message" \
#                      "try this first" \
#                      "or this second"
die_with_help() {
    local header="$1"; shift
    _script_p2
    echo -e "${C_RED}✗${C_RESET} $header" >&2
    if [[ $# -gt 0 ]]; then
        echo "" >&2
        echo "  Next steps to try:" >&2
        for step in "$@"; do
            echo "    → $step" >&2
        done
    fi
    echo "" >&2
    echo "  For diagnosis, run:    $0 doctor" >&2
    echo "  For full usage, run:    $0 --help" >&2
    exit 1
}

# Path to the interpreter inside a project virtualenv.
#
# Windows venvs put it at ``<venv>/Scripts/python.exe``; POSIX uses
# ``<venv>/bin/python``. Four call sites used to hardcode the POSIX spelling,
# which made ``uv sync`` fail on Windows (Git Bash) with
# "No interpreter found at path `.venv/bin/python`" — i.e. the one-click
# installer could not complete there at all.
#
# Usage: py=$(venv_python "$CLOUDAGENT_HOME/.venv") || die "..."
venv_python() {
    local venv_dir="$1"
    local candidate
    for candidate in "$venv_dir/Scripts/python.exe" "$venv_dir/Scripts/python" "$venv_dir/bin/python"; do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Wrap a command: if DRY_RUN=1, just print what would happen. Otherwise run it.
# Returns the exit status of the wrapped command.
run_or_dry() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would run: $*"
        return 0
    fi
    "$@"
}

# Exit-time summary. Emitted by the EXIT trap after the script's main work
# is done (success or failure). Agents tail the log for this line to know
# whether the install succeeded.
_on_exit_summary() {
    local rc=$1
    local elapsed=$(( $(date +%s) - SCRIPT_START_TS ))
    if [[ $rc -eq 0 ]]; then
        _script_p1
        echo "DONE: success in ${elapsed}s"
        if [[ -n "${LOG_FILE:-}" ]]; then
            _script_p1
            echo "DONE: full log saved to: $LOG_FILE"
        fi
    else
        _script_p2
        echo "DONE: FAILED (exit $rc) after ${elapsed}s" >&2
        if [[ -n "${LOG_FILE:-}" ]]; then
            _script_p2
            echo "DONE: failure log saved to: $LOG_FILE" >&2
        else
            _script_p2
            echo "DONE: re-run with --log-file <path> to capture full output." >&2
        fi
    fi
}

# ============================================================================
#  OS detection
# ============================================================================
detect_os() {
    local ostype="${OSTYPE:-}"
    if [[ "$ostype" == "linux-gnu"* || "$ostype" == "linux-musl"* ]]; then
        # Distinguish WSL from native Linux
        if [[ -r /proc/version ]] && grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
            echo "wsl"
        else
            echo "linux"
        fi
    elif [[ "$ostype" == "darwin"* ]]; then
        echo "macos"
    elif [[ "$ostype" == "msys"* || "$ostype" == "cygwin"* || "$ostype" == "win32" ]]; then
        echo "windows-like"
    elif [[ -r /proc/version ]] && grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
        echo "wsl"
    else
        echo "unknown"
    fi
}

os_install_hint() {
    case "$1" in
        linux|wsl)
            cat <<'EOF'
    Install Git for your distro, e.g.:
        Debian/Ubuntu : sudo apt update && sudo apt install -y git
        Fedora/RHEL   : sudo dnf install -y git
        Arch          : sudo pacman -S --noconfirm git
        openSUSE      : sudo zypper install -y git
EOF
            ;;
        macos)
            cat <<'EOF'
    Install Git on macOS:
        xcode-select --install          # Apple Command Line Tools
        — or —
        brew install git
EOF
            ;;
        windows-like)
            cat <<'EOF'
    On Windows, install one of:
        Git for Windows : https://git-scm.com/download/win  (then run from Git Bash)
        WSL             : https://learn.microsoft.com/windows/wsl/install  (recommended)
EOF
            ;;
    esac
}

# One-liner variant for the doctor output.
os_install_hint_oneliner() {
    case "$1" in
        linux|wsl) echo "sudo apt install -y git   (or your distro's package manager)" ;;
        macos)     echo "xcode-select --install    (or: brew install git)" ;;
        windows-like) echo "install Git for Windows or WSL" ;;
        *)         echo "install git via your package manager" ;;
    esac
}

# ============================================================================
#  Prerequisite: Git
# ============================================================================
check_git() {
    if ! command -v git >/dev/null 2>&1; then
        log_err "Git is not installed."
        os_install_hint "$OS"
        exit 1
    fi
    local version
    version=$(git --version)
    log_ok "$version"
}

# ============================================================================
#  Install / locate uv (Astral's Python package manager, via pip)
# ============================================================================
install_uv() {
    if command -v uv >/dev/null 2>&1; then
        log_ok "uv $(uv --version | awk '{print $2}') already installed"
        return
    fi

    log_info "Installing uv via pip (trusted PyPI source)..."
    local py
    py=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "python3")
    if ! run_or_dry "$py" -m pip install uv 2>&1; then
        die_with_help "Failed to install uv via pip." \
                      "Check your network connection and proxy settings." \
                      "Retry:    $0" \
                      "Manual:   pip install uv"
    fi

    # Make uv visible to this session, then verify.
    export PATH="$HOME/.local:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if [[ "${DRY_RUN:-0}" -eq 0 ]] && ! command -v uv >/dev/null 2>&1; then
        die_with_help "uv still not on PATH after install." \
                      "Check:    ls -la $HOME/.local/bin/uv" \
                      "Or:       export PATH=\$HOME/.local:\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH" \
                      "Then:     $0"
    fi
    log_ok "uv $(uv --version | awk '{print $2}') installed"
}

# ============================================================================
#  Python 3.10+ provisioning (via uv)
# ============================================================================
ensure_python() {
    # Ask uv for any 3.10+ interpreter it can see (system or uv-managed).
    local py
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would check for Python $PYTHON_MIN_VERSION+ via uv"
        return 0
    fi
    if py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null) && [[ -n "$py" && -x "$py" ]]; then
        log_ok "Python $($py --version 2>&1 | awk '{print $1, $2}')"
        return
    fi

    log_info "Python $PYTHON_MIN_VERSION+ not found — provisioning via uv (no sudo)..."
    if ! run_or_dry uv python install "$PYTHON_MIN_VERSION"; then
        die_with_help "Failed to install Python $PYTHON_MIN_VERSION via uv." \
                      "Retry:    $0" \
                      "Manual:   uv python install $PYTHON_MIN_VERSION" \
                      "Or:       install Python $PYTHON_MIN_VERSION+ from https://python.org"
    fi
    py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null || true)
    if [[ -z "$py" || ! -x "$py" ]]; then
        die_with_help "Python $PYTHON_MIN_VERSION still not found after uv install." \
                      "Retry:    $0" \
                      "Diagnose: $0 doctor"
    fi
    log_ok "Python $($py --version 2>&1 | awk '{print $1, $2}')"
}

# ============================================================================
#  Python 3.14+ pyo3-ffi compatibility guard
#  Detects Python >= 3.14 (too new for pyo3-ffi used by outlines-core) and
#  auto-mitigates by switching to a compatible version (3.11 - 3.13).
#  If no compatible version is found, fails with actionable instructions.
# ============================================================================
ensure_python_pyo3_compat() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would check Python <= $PYTHON_MAX_SUPPORTED for pyo3-ffi compatibility"
        return 0
    fi

    local py
    py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null || true)
    if [[ -z "$py" || ! -x "$py" ]]; then return 0; fi

    local ver major minor
    ver=$($py -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)

    # No mitigation needed for Python <= 3.13
    if [[ "$major" -lt 3 ]] || { [[ "$major" -eq 3 && "$minor" -le 13 ]]; }; then
        return 0
    fi

    log_warn "Python $ver detected, but pyo3-ffi (used by outlines-core) only supports up to $PYTHON_MAX_SUPPORTED"
    log_info "Searching for a compatible Python ($PYTHON_MIN_VERSION - $PYTHON_MAX_SUPPORTED)..."

    local compat_py compat_ver
    for target in 3.13 3.12 3.11; do
        compat_py=$(uv python find "$target" 2>/dev/null || true)
        if [[ -n "$compat_py" && -x "$compat_py" ]]; then
            compat_ver=$($compat_py -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            log_ok "Found compatible Python: $compat_py ($compat_ver)"
            export UV_PYTHON="$compat_py"
            return 0
        fi
    done

    # No compatible interpreter locally — try uv provisioning
    log_info "No compatible Python found locally — provisioning Python $PYTHON_MAX_SUPPORTED via uv..."
    if run_or_dry uv python install "$PYTHON_MAX_SUPPORTED"; then
        compat_py=$(uv python find "$PYTHON_MAX_SUPPORTED" 2>/dev/null || true)
        if [[ -n "$compat_py" && -x "$compat_py" ]]; then
            compat_ver=$($compat_py -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            log_ok "Python $PYTHON_MAX_SUPPORTED installed via uv ($compat_py)"
            export UV_PYTHON="$compat_py"
            return 0
        fi
    fi

    # Auto-mitigation failed — defensive error with clear next steps
    die_with_help "Python $ver is incompatible with cloudagent dependencies" \
        "The detected Python ($ver) is too new for pyo3-ffi (max $PYTHON_MAX_SUPPORTED)." \
        "outlines-core will fail to compile with Rust errors." \
        "" \
        "Recommended fixes (pick one):" \
        "  1. uv python install 3.13   (then re-run install.sh)" \
        "  2. pyenv install 3.13 && pyenv local 3.13" \
        "  3. Install Python 3.11-3.13 from https://python.org" \
        "  4. Set PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 and retry (risky)" \
        "The installer attempted to auto-provision a compatible Python but failed."
}

# ============================================================================
#  Helper: adjust CLOUDAGENT_HOME to cloudagent subdir if present
# ============================================================================
_adjust_to_subdir() {
    if [[ -d "$CLOUDAGENT_HOME/cloudagent" ]]; then
        CLOUDAGENT_HOME="$CLOUDAGENT_HOME/cloudagent"
        CLOUDAGENT_PARENT_DIR="$(dirname -- "$CLOUDAGENT_HOME")"
    fi
}

# ============================================================================
#  本地源码（standalone）部署
#  ---------------------------------------------------------------------------
#  本地 checkout 自包含完整源码（cloudagent_ext/ 单层），直接复制到安装目录。
#  不 clone gitcode.com 的 cloudAgent，也不拉取任何上游源码。
# ============================================================================
deploy_standalone_source() {
    if [[ "$STANDALONE" -eq 0 ]]; then
        return
    fi

    if [[ -z "$SOURCE_DIR" || ! -d "$SOURCE_DIR" ]]; then
        die_with_help "Standalone source is not available." \
                      "Run this script from the cloudagent checkout directory."
    fi
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would deploy standalone source: $SOURCE_DIR -> $CLOUDAGENT_HOME"
        return 0
    fi

    mkdir -p "$CLOUDAGENT_PARENT_DIR"
    if [[ ! -d "$CLOUDAGENT_HOME" ]]; then
        mkdir -p "$CLOUDAGENT_HOME"
        log_info "Deploying standalone source: $SOURCE_DIR -> $CLOUDAGENT_HOME"
        if (cd "$SOURCE_DIR" && tar \
                --exclude='./.venv' --exclude='./.git' --exclude='./__pycache__' \
                --exclude='./.pytest_cache' --exclude='./.ruff_cache' --exclude='./.mypy_cache' \
                --exclude='./.idea' --exclude='./.vscode' --exclude='./cloudagent.egg-info' \
                --exclude='./dist' --exclude='./build' --exclude='*.egg-info' \
                --exclude='*.pyc' --exclude='*.pyo' --exclude='*.log' \
                -cf - .) | (cd "$CLOUDAGENT_HOME" && tar -xf -); then
            log_ok "Standalone source deployed to $CLOUDAGENT_HOME"
        else
            die_with_help "Failed to deploy standalone source." \
                          "Copy the checkout to $CLOUDAGENT_HOME manually and retry."
        fi
    else
        # 已存在：增量覆盖（保留 .venv 与用户生成物）
        log_info "Updating standalone source at $CLOUDAGENT_HOME ..."
        if (cd "$SOURCE_DIR" && tar \
                --exclude='./.venv' --exclude='./.git' --exclude='./__pycache__' \
                --exclude='./.pytest_cache' --exclude='./.ruff_cache' --exclude='./.mypy_cache' \
                --exclude='./.idea' --exclude='./.vscode' --exclude='./cloudagent.egg-info' \
                --exclude='./dist' --exclude='./build' --exclude='*.egg-info' \
                --exclude='*.pyc' --exclude='*.pyo' --exclude='*.log' \
                -cf - .) | (cd "$CLOUDAGENT_HOME" && tar -xf -); then
            log_ok "Standalone source updated at $CLOUDAGENT_HOME"
        else
            die_with_help "Failed to update standalone source." \
                          "Copy the checkout to $CLOUDAGENT_HOME manually and retry."
        fi
    fi
}

# ============================================================================
#  Clone or update the repo
# ============================================================================
clone_or_update_repo() {
    # 本地源码（standalone）：跳过 cloudAgent git clone，直接从本地 checkout 部署
    if [[ "$STANDALONE" -eq 1 ]]; then
        deploy_standalone_source
        return
    fi
    # Only auto-detect repo location when --install-dir was NOT explicitly set
    if [[ "$CLOUDAGENT_HOME" == "$DEFAULT_INSTALL_DIR" ]]; then
        # Try to detect if we're already inside an cloudAgent git repo
        local repo_root
        repo_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
        if [[ -n "$repo_root" && -f "$repo_root/README.md" ]]; then
            # We are inside a git repo — use it directly
            CLOUDAGENT_HOME="$repo_root"
            _adjust_to_subdir
            log_info "Using existing repo at $CLOUDAGENT_HOME"
        if [[ -d "$CLOUDAGENT_HOME/.git" ]]; then
            log_info "Pulling latest changes..."
            if (cd "$CLOUDAGENT_HOME" && git pull --ff-only) >/dev/null 2>&1; then
                log_ok "Updated via fast-forward"
            else
                die_with_help "git pull failed — the local repository has diverged or has uncommitted changes." \
                              "To resolve:  cd $CLOUDAGENT_HOME && git status" \
                              "             git stash && git pull --ff-only  (save local changes first)" \
                              "             git pull --rebase               (rebase your changes)" \
                              "Then re-run: $0 update"
            fi
        fi
        return
    fi
    fi
    # --- End of auto-detect block (--install-dir check above) ---

    if [[ -d "$CLOUDAGENT_HOME/.git" ]]; then
        log_info "Existing repo found at $CLOUDAGENT_HOME — pulling latest changes..."
        if (cd "$CLOUDAGENT_HOME" && git pull --ff-only) >/dev/null 2>&1; then
            log_ok "Updated via fast-forward"
        else
            die_with_help "git pull failed — the local repository has diverged or has uncommitted changes." \
                          "To resolve:  cd $CLOUDAGENT_HOME && git status" \
                          "             git stash && git pull --ff-only  (save local changes first)" \
                          "             git pull --rebase               (rebase your changes)" \
                          "Then re-run: $0 update"
        fi
        _adjust_to_subdir
        return
    fi

    if [[ -e "$CLOUDAGENT_HOME" ]]; then
        # Exists but isn't a git repo — back it up so we don't clobber user work.
        local stamp
        stamp=$(date +%Y%m%d%H%M%S)
        log_warn "$CLOUDAGENT_HOME exists but is not a git checkout. Backing up to ${CLOUDAGENT_HOME}.bak.${stamp}"
        mv "$CLOUDAGENT_HOME" "${CLOUDAGENT_HOME}.bak.${stamp}"
    fi

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would create parent dir: $CLOUDAGENT_PARENT_DIR"
        _script_p1
        echo "[DRY-RUN] would clone: $REPO_URL (ref: $REPO_REF) -> $CLOUDAGENT_HOME"
        return 0
    fi

    mkdir -p "$CLOUDAGENT_PARENT_DIR"
    log_info "Cloning $REPO_URL (ref: $REPO_REF) → $CLOUDAGENT_HOME"
    # Try the pinned ref first. This is what makes the install version-stable:
    # the matching uv.lock at REPO_REF pins every transitive dep to a known-good
    # version, so old install.sh + old cloudagent + old deps always line up.
    if git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$CLOUDAGENT_HOME" 2>/dev/null; then
        log_ok "Cloned ref $REPO_REF (cloudagent $CLOUDAGENT_VERSION)"
        _adjust_to_subdir
        return
    fi

    # The ref doesn't exist on the remote yet (e.g. tag not pushed). Loud
    # warning, then fall back to the default branch so install can still
    # succeed in dev / pre-release scenarios.
    log_warn "Ref '$REPO_REF' not found on $REPO_URL — falling back to default branch."
    log_warn "  This install will pull the LATEST cloudagent, not v$CLOUDAGENT_VERSION."
    log_warn "  Push a '$REPO_REF' git tag (or update REPO_REF) to enforce the version."
    if ! git clone --depth 1 "$REPO_URL" "$CLOUDAGENT_HOME"; then
        die_with_help "git clone failed." \
                      "Check your network connection." \
                      "Verify:  curl -I $REPO_URL" \
                      "Retry:   $0" \
                      "Diagnose: $0 doctor"
    fi
    log_ok "Cloned default branch (cloudagent version NOT pinned)"
    _adjust_to_subdir
}

# ============================================================================
#  Runtime payload validation (fail-closed)
# ============================================================================
# Mirrors install.ps1:Assert-RuntimePayload. The single-layering migration moved
# the whole runtime into cloudagent_ext/; if the deployed payload is incomplete
# (e.g. a partial copy, or a checkout that predates the migration) the installer
# must stop here with an actionable message instead of failing later inside
# `uv sync` with an error that points at the wrong thing.
assert_runtime_payload() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would require pyproject.toml, uv.lock, and cloudagent_ext/ in $CLOUDAGENT_HOME"
        return 0
    fi

    local required=(pyproject.toml uv.lock cloudagent_ext)
    local missing=()
    local item
    for item in "${required[@]}"; do
        if [[ ! -e "$CLOUDAGENT_HOME/$item" ]]; then
            missing+=("$item")
        fi
    done

    if (( ${#missing[@]} > 0 )); then
        die_with_help "cloudagent runtime payload migration is incomplete." \
                      "Missing: ${missing[*]}" \
                      "The installer is intentionally fail-closed until these files are migrated." \
                      "Re-copy the full checkout, then re-run this installer."
    fi
    log_ok "Runtime payload complete (pyproject.toml, uv.lock, cloudagent_ext/)"
}


# ============================================================================
#  Initialize local release environment
# ============================================================================
ensure_local_env_file() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would create $CLOUDAGENT_HOME/.env from .env.example if missing"
        return 0
    fi

    cd "$CLOUDAGENT_HOME"
    if [[ -f ".env" ]]; then
        log_ok "Local .env already exists (not modified)"
        return 0
    fi

    if [[ -f ".env.example" ]]; then
        cp ".env.example" ".env"
    else
        cat > ".env" <<'EOF'
# Local release credentials. Never commit real token values.
GITCODE_TOKEN=
TEST_PYPI_TOKEN=
# PYPI_TOKEN=
GITCODE_OWNER=
GITCODE_REPO=
GITCODE_API_ROOT=https://api.gitcode.com
EOF
    fi
    chmod 600 ".env" 2>/dev/null || true
    log_ok "Created local .env template (fill tokens before release publishing)"
}

# ============================================================================
#  Create venv
# ============================================================================
create_venv() {
    if [[ "$USE_VENV" -eq 0 ]]; then
        log_info "--no-venv specified — skipping venv creation (deps will install to system Python)"
        return
    fi
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would run: uv venv --python $PYTHON_MIN_VERSION .venv   (in $CLOUDAGENT_HOME)"
        return 0
    fi
    cd "$CLOUDAGENT_HOME"
    if [[ -d ".venv" ]]; then
        log_ok "Existing venv at $CLOUDAGENT_HOME/.venv"
        return
    fi
    log_info "Creating venv with Python $PYTHON_MIN_VERSION..."
    if ! run_or_dry uv venv --python "$PYTHON_MIN_VERSION" .venv; then
        die_with_help "uv venv failed." \
                      "Check:    uv --version" \
                      "Retry:    $0" \
                      "Diagnose: $0 doctor"
    fi
    log_ok "Venv created"
}

# ============================================================================
#  Install dependencies
# ============================================================================
install_deps() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        log_info "Installing project + [all] extra (lock-pinned when possible)..."
        _script_p1
        echo "[DRY-RUN] would run: uv sync --extra all   (in $CLOUDAGENT_HOME)"
        return 0
    fi
    cd "$CLOUDAGENT_HOME"
    log_info "Installing project + [all] extra (lock-pinned to uv.lock when possible)..."

    # Two-stage install: prefer `uv sync` (honors uv.lock → exact transitive
    # versions), fall back to `uv pip install` if the project doesn't declare
    # the [all] extra or the lock is out of sync.
    #
    # Why a fallback?
    #   - Production (matched install.sh + cloudagent release): uv sync uses
    #     the lock file from the matching git tag, giving every user the
    #     SAME resolved dep set. This is what prevents "old install.sh
    #     picks up latest deps and breaks" — the dep versions are baked
    #     into uv.lock at release time.
    #   - Mismatch (new install.sh running on old cloudagent, OR a cloudagent
    #     release that pre-dates the [all] extra): uv sync rejects
    #     `--extra all` because the extra doesn't exist in pyproject.toml.
    #     We fall back to uv pip install, which is lenient about missing
    #     extras. Deps are no longer lock-pinned in this case, but the
    #     install at least succeeds.

    # --- With venv: uv sync operates on the venv created by create_venv.
    # --- Without venv (--no-venv): install to the active Python via --system.
    local install_target_args=()
    if [[ "$USE_VENV" -eq 1 ]]; then
        [[ -d ".venv" ]] || die "Venv missing at $CLOUDAGENT_HOME/.venv — run without --no-venv or re-clone."
        local venv_py
        venv_py=$(venv_python ".venv") || die "No interpreter found inside .venv (expected Scripts/python.exe or bin/python)."
        install_target_args=(--python "$venv_py")
    else
        install_target_args=(--system)
    fi

    local uv_sync_log uv_pip_log
    uv_sync_log=$(mktemp -t uv-sync-XXXXXX 2>/dev/null || mktemp)
    uv_pip_log=$(mktemp -t uv-pip-XXXXXX 2>/dev/null || mktemp)

    if uv sync --extra all "${install_target_args[@]}" 2>"$uv_sync_log"; then
        log_ok "Dependencies installed (lock-pinned to uv.lock at $REPO_REF)"
        rm -f "$uv_sync_log" "$uv_pip_log"
        return
    fi

    # uv sync failed — inspect why and decide.
    local sync_err
    sync_err=$(cat "$uv_sync_log" 2>/dev/null || true)

    # Dump full log to stderr so --log-file (tee) captures it
    log_warn "uv sync failed — full error log:"
    cat "$uv_sync_log" >&2 2>/dev/null || true

    rm -f "$uv_sync_log"

    if echo "$sync_err" | grep -qE 'Extra `all` is not defined'; then
        # The cloudagent version we're installing doesn't have the [all]
        # extra in its pyproject.toml. This is expected for any release
        # that pre-dates the [all] extra (added with install.sh v1.1).
        log_warn "This cloudagent version has no [all] extra — falling back to uv pip install."
        log_warn "  Dependency versions will be resolved fresh (NOT lock-pinned)."
        log_warn "  For strict version pinning, use an install.sh whose"
        log_warn "  CLOUDAGENT_VERSION matches a release that includes [all]."
    else
        log_warn "uv sync failed; falling back to uv pip install."
        log_warn "  Sync error was: ${sync_err:-<no stderr captured>}"
    fi

    if ! uv pip install "${install_target_args[@]}" -e ".[all]" 2>"$uv_pip_log"; then
        local pip_err
        pip_err=$(cat "$uv_pip_log" 2>/dev/null || true)
        log_warn "uv pip install failed — full error log:"
        cat "$uv_pip_log" >&2 2>/dev/null || true
        rm -f "$uv_pip_log"
        # uv's PEP 668 message has changed wording across versions; match
        # both the structured error code ("externally-managed-environment")
        # and the human message ("externally managed") defensively.
        if [[ "$USE_VENV" -eq 0 ]] && echo "$pip_err" | grep -qiE 'externally[ -]managed'; then
            log_warn "System Python is externally managed (PEP 668). Retrying with --break-system-packages."
            if ! uv pip install "${install_target_args[@]}" --break-system-packages -e ".[all]"; then
                die_with_help "uv pip install to system failed even with --break-system-packages." \
                              "Inspect the error above for missing system libraries." \
                              "Retry:    $0" \
                              "Or:       $0 uninstall && $0   (fresh install with venv)"
            fi
        else
            log_err "uv pip install failed: ${pip_err:-<no stderr captured>}"
            die_with_help "Both uv sync and uv pip install failed." \
                          "Re-run with --log-file <path> to capture full output." \
                          "Retry:    $0" \
                          "Diagnose: $0 doctor" \
                          "Clean:    $0 uninstall && $0"
        fi
    fi
    rm -f "$uv_pip_log"
    log_ok "Dependencies installed (fresh-resolve, NOT lock-pinned; target: $([[ $USE_VENV -eq 1 ]] && echo .venv || echo system))"
}

# ============================================================================
#  Locate the venv's entry-point binary
# ============================================================================
find_venv_entry() {
    local venv_dir="$1" name="$2"
    # Linux/macOS layout
    if [[ -x "$venv_dir/bin/$name" ]]; then
        echo "$venv_dir/bin/$name"; return 0
    fi
    # Windows layout (Git Bash / WSL interop)
    if [[ -x "$venv_dir/Scripts/$name.exe" ]]; then
        echo "$venv_dir/Scripts/$name.exe"; return 0
    fi
    if [[ -x "$venv_dir/Scripts/$name" ]]; then
        echo "$venv_dir/Scripts/$name"; return 0
    fi
    return 1
}

# ============================================================================
#  Register global commands
#  - We write tiny wrapper scripts in ~/.local/bin (more portable than symlinks
#    on Windows / Git Bash, and survives venv re-creation).
#  - `cloudagent` is registered as an alias for `cloudagent` (the only
#    declared entry point in pyproject.toml).
# ============================================================================
register_commands() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would register: $LOCAL_BIN/cloudagent, $LOCAL_BIN/cloudagent"
        return 0
    fi
    mkdir -p "$LOCAL_BIN"

    local entry
    if [[ "$USE_VENV" -eq 1 ]]; then
        # Venv mode: look for the entry inside the project's .venv
        if ! entry=$(find_venv_entry "$CLOUDAGENT_HOME/.venv" "$ENTRY_POINT"); then
            die "Entry point '$ENTRY_POINT' not found inside $CLOUDAGENT_HOME/.venv — dependency install may have failed."
        fi
    else
        # --no-venv mode: look for the entry on PATH (uv pip install --system
        # drops scripts in /usr/local/bin or ~/.local/bin). We check a few
        # common locations explicitly so we don't depend on the just-installed
        # PATH being effective in this very shell.
        entry=""
        for candidate in \
            "$HOME/.local/bin/$ENTRY_POINT" \
            "/usr/local/bin/$ENTRY_POINT" \
            "$(command -v "$ENTRY_POINT" 2>/dev/null || true)"; do
            if [[ -n "$candidate" && ( -x "$candidate" || -L "$candidate" ) ]]; then
                entry="$candidate"; break
            fi
        done
        [[ -n "$entry" ]] || die "Entry point '$ENTRY_POINT' not found on PATH after system install — check 'which $ENTRY_POINT'."
    fi

    write_wrapper() {
        local name="$1" target="$2"
        local wrapper="$LOCAL_BIN/$name"

        # Always (re)write so the wrapper reflects any new install dir.
        if [[ -L "$wrapper" || -e "$wrapper" ]]; then
            rm -f "$wrapper"
        fi

        cat > "$wrapper" <<EOF
#!/usr/bin/env bash
# Auto-generated by cloudagent install.sh — do not edit by hand.
# Regenerate by re-running install.sh.
# Point the runtime at the configured config dir; the wrapper itself is
# pinned to the install dir baked in at generation time, but the config
# dir can be re-pointed at runtime by the user via this env var.
export CLOUDAGENT_CONFIG_DIR="\${CLOUDAGENT_CONFIG_DIR:-${CONFIG_DIR}}"
exec "$target" "\$@"
EOF
        chmod +x "$wrapper"
        log_ok "$wrapper → $target  (CLOUDAGENT_CONFIG_DIR=${CONFIG_DIR})"
    }

    write_wrapper "cloudagent" "$entry"
    write_wrapper "cloudagent"    "$entry"
}

# ============================================================================
#  Patch shell rc files to include ~/.local/bin in PATH
# ============================================================================
update_shell_rc() {
    local path_line='export PATH="$HOME/.local:$HOME/.local/bin:$PATH"'
    local current_shell
    current_shell=$(basename "${SHELL:-bash}" 2>/dev/null || echo "bash")
    local rc_file=""

    case "$current_shell" in
        bash) rc_file="$HOME/.bashrc" ;;
        zsh)  rc_file="$HOME/.zshrc"  ;;
        *)    rc_file="$HOME/.profile" ;;
    esac

    if [[ ! -f "$rc_file" ]]; then
        log_warn "Shell rc file $rc_file not found — please add '$path_line' to your shell's startup file."
        return
    fi

    if grep -qF '$HOME/.local/bin' "$rc_file" 2>/dev/null; then
        log_ok "PATH already contains ~/.local/bin in $rc_file"
        return
    fi

    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would append PATH entry to: $rc_file"
        return
    fi

    {
        echo ""
        echo "$RC_MARKER"
        echo "$path_line"
    } >> "$rc_file"
    log_ok "Patched $rc_file (added ~/.local/bin to PATH)"
}

# ============================================================================
#  Post-install setup wizard (the interactive first-run configuration)
# ============================================================================
run_post_install_setup() {
    if [[ "$RUN_SETUP" -eq 0 ]]; then
        log_warn "Setup wizard skipped (--no-setup). Run 'cloudagent' manually to configure."
        return
    fi

    log_info "Post-install setup wizard is available — launching cloudagent setup…"
    # We intentionally do NOT exec a blocking interactive REPL here. The
    # install script must remain non-interactive so it can run unattended
    # in CI / Docker / by orchestrators. The wizard itself (if present) is
    # a subcommand the user runs themselves; we just announce it.
    if command -v cloudagent >/dev/null 2>&1; then
        log_ok "Run one of:"
        echo -e "    ${C_BOLD}cloudagent${C_RESET}          # start the interactive REPL (triggers first-run setup if config is empty)"
        echo -e "    ${C_BOLD}cloudagent --help${C_RESET}  # see all options"
    else
        log_warn "cloudagent not on PATH yet — run 'source ~/.bashrc' (or ~/.zshrc) first."
    fi
}

# ============================================================================
#  Install pipeline
# ============================================================================
install_main() {
    echo -e "${C_BOLD}cloudagent installer v${INSTALLER_VERSION}${C_RESET}"
    echo -e "  ${C_BOLD}OS:${C_RESET}          $OS"
    echo -e "  ${C_BOLD}Install dir:${C_RESET} $CLOUDAGENT_HOME"
    echo -e "  ${C_BOLD}Config dir:${C_RESET}  $CONFIG_DIR"
    echo -e "  ${C_BOLD}Git ref:${C_RESET}     $REPO_REF"
    echo -e "  ${C_BOLD}Venv:${C_RESET}        $([[ $USE_VENV -eq 1 ]] && echo "create at $CLOUDAGENT_HOME/.venv" || echo "${C_YELLOW}skipped (--no-venv, system Python)${C_RESET}")"
    echo -e "  ${C_BOLD}Setup wizard:${C_RESET} $([[ $RUN_SETUP -eq 1 ]] && echo "announce only (non-blocking)" || echo "${C_YELLOW}skipped (--no-setup)${C_RESET}")"
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        echo -e "  ${C_BOLD}Mode:${C_RESET}        ${C_YELLOW}DRY-RUN (no changes will be made)${C_RESET}"
    fi
    if [[ -n "${LOG_FILE:-}" ]]; then
        echo -e "  ${C_BOLD}Log file:${C_RESET}    $LOG_FILE"
    fi
    if [[ "${DEBUG:-0}" -eq 1 ]]; then
        echo -e "  ${C_BOLD}Debug:${C_RESET}       ${C_YELLOW}ON (set -x trace)${C_RESET}"
    fi

    log_step "1/10  Checking prerequisites"
    check_git

    log_step "2/10  Installing uv (Astral, no sudo)"
    # Re-source in case it wasn't on PATH at the top of the script.
    export PATH="$HOME/.local:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    install_uv

    log_step "3/10  Provisioning Python $PYTHON_MIN_VERSION+"
    ensure_python
    ensure_python_pyo3_compat

    log_step "4/10  Cloning / updating repository"
    clone_or_update_repo

    log_step "5/10  Validating runtime payload"
    assert_runtime_payload

    log_step "6/10  Initializing local release .env"
    ensure_local_env_file

    log_step "7/10  $([[ $USE_VENV -eq 1 ]] && echo "Creating virtual environment" || echo "Preparing (no venv — using system Python)")"
    create_venv

    log_step "8/10  Installing dependencies (uv sync --extra all, lock-pinned)"
    install_deps

    log_step "9/10  Installing local Git hooks"
    install_git_hooks

    log_step "10/10  Registering global commands & patching PATH"
    register_commands
    update_shell_rc

    echo ""
    log_ok "Installation complete!"
    echo ""
    echo -e "  ${C_BOLD}Try it:${C_RESET}"
    echo -e "    cloudagent --help      # primary command"
    echo -e "    cloudagent    --help       # alias of cloudagent"
    echo ""
    echo -e "  ${C_BOLD}Installed at:${C_RESET}  $CLOUDAGENT_HOME"
    echo -e "  ${C_BOLD}Config at:${C_RESET}    $CONFIG_DIR"
    echo -e "  ${C_BOLD}Commands at:${C_RESET}   $LOCAL_BIN/{cloudagent,cloudagent}"
    echo ""

    # Post-install setup lives outside the numbered pipeline because it is
    # optional and varies the most.
    run_post_install_setup

    log_warn "Open a new shell, or run:  source ~/.bashrc   (or ~/.zshrc)"
}

# ============================================================================
#  CLI argument parser — populates the *OVERRIDE globals, then they're
#  resolved into the actual install/config/ref variables below.
# ============================================================================
REF_OVERRIDE=""
INSTALL_DIR_OVERRIDE=""
CONFIG_DIR_OVERRIDE=""
USE_VENV=1       # --no-venv flips to 0
RUN_SETUP=1      # --no-setup flips to 0
DRY_RUN=0        # --dry-run flips to 1
FORCE_SRC=0      # 兼容保留：旧版用于强制重建 src/（单层代码库后已无作用）
ASSUME_YES=0     # --yes/-y flips to 1
LOG_FILE=""      # --log-file <path>
DEBUG=0          # --debug flips to 1 (set -x trace)
SUBCOMMAND=""    # positional verb
SCRIPT_START_TS=$(date +%s)

print_usage_hint() {
    echo "Try '$0 --help' for usage." >&2
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            # --- Subcommands ---
            install|status|doctor|verify|update|uninstall|help)
                SUBCOMMAND="$1"; shift ;;

            # --- Option flags ---
            --ref)
                [[ $# -ge 2 ]] || { log_err "--ref requires a value (commit/tag/branch)"; print_usage_hint; exit 1; }
                REF_OVERRIDE="$2"; shift 2 ;;
            --install-dir)
                [[ $# -ge 2 ]] || { log_err "--install-dir requires a path"; print_usage_hint; exit 1; }
                INSTALL_DIR_OVERRIDE="$2"; shift 2 ;;
            --config-dir)
                [[ $# -ge 2 ]] || { log_err "--config-dir requires a path"; print_usage_hint; exit 1; }
                CONFIG_DIR_OVERRIDE="$2"; shift 2 ;;
            --log-file)
                [[ $# -ge 2 ]] || { log_err "--log-file requires a path"; print_usage_hint; exit 1; }
                LOG_FILE="$2"; shift 2 ;;
            --dry-run)
                DRY_RUN=1; shift ;;
            --force-src)
                FORCE_SRC=1; shift ;;
            --yes|-y)
                ASSUME_YES=1; shift ;;
            --no-venv)
                USE_VENV=0; shift ;;
            --no-setup)
                RUN_SETUP=0; shift ;;
            --debug)
                DEBUG=1; shift ;;
            --version|-v)
                echo "install.sh v${INSTALLER_VERSION} (installs cloudagent v${CLOUDAGENT_VERSION})"
                exit 0 ;;
            --uninstall|-u)
                SUBCOMMAND="uninstall"; shift ;;
            --help|-h)
                SUBCOMMAND="help"; shift ;;
            --help-zh)
                SUBCOMMAND="help-zh"; shift ;;

            --)
                shift; break ;;
            -*)
                log_err "Unknown option: $1"; print_usage_hint; exit 1 ;;
            *)
                log_err "Unexpected positional argument: $1"; print_usage_hint; exit 1 ;;
        esac
    done
}

# ============================================================================
#  Entry point
# ============================================================================
parse_args "$@"

# Resolve overrides → effective install/config paths. Must run AFTER
# parse_args, otherwise INSTALL_DIR_OVERRIDE / REF_OVERRIDE are still
# empty when CLOUDAGENT_HOME / REPO_REF get resolved and the flags are
# silently ignored.
CLOUDAGENT_HOME="${INSTALL_DIR_OVERRIDE:-$DEFAULT_INSTALL_DIR}"
CLOUDAGENT_PARENT_DIR="$(dirname -- "$CLOUDAGENT_HOME")"
CONFIG_DIR="${CONFIG_DIR_OVERRIDE:-$DEFAULT_CONFIG_DIR}"
[[ -n "$REF_OVERRIDE" ]] && REPO_REF="$REF_OVERRIDE"

# --- 本地源码（standalone）mode detection -----------------------------------
# 当 install.sh 运行于本地 cloudagent checkout 时直接从本地部署：
# 不再 clone gitcode.com 的 cloudAgent，也不拉取任何上游源码（源码即仓库）。
STANDALONE=0
SOURCE_DIR=""
_standalone_candidates=("$SCRIPT_DIR")
if [[ -d "$SCRIPT_DIR/cloudagent" ]]; then
    _standalone_candidates+=("$SCRIPT_DIR/cloudagent")
fi
for _cand in "${_standalone_candidates[@]}"; do
    if [[ -f "$_cand/pyproject.toml" && -d "$_cand/cloudagent_ext" ]]; then
        STANDALONE=1
        SOURCE_DIR="$_cand"
        break
    fi
done
unset _standalone_candidates _cand
if [[ "$STANDALONE" -eq 1 ]]; then
    # 产品目录固定为 ~/.cloudagent/cloudagent/cloudagent（与 install.ps1 一致），
    # 除非用户显式传了 --install-dir。
    if [[ -z "$INSTALL_DIR_OVERRIDE" ]]; then
        CLOUDAGENT_HOME="$DEFAULT_INSTALL_DIR/cloudagent"
        CLOUDAGENT_PARENT_DIR="$DEFAULT_INSTALL_DIR"
    fi
    log_info "Local-source mode: installing from $SOURCE_DIR"
fi

OS=$(detect_os)

# Bail out for native Windows shells — this script targets bash, not cmd/PS.
if [[ "$OS" == "unknown" ]] && [[ -n "${COMSPEC:-}" || -n "${WINDIR:-}" ]]; then
    cat >&2 <<'END_MSG'
✗ Native Windows shell detected (cmd.exe or PowerShell).

  install.sh is a bash script and cannot run directly in cmd or PowerShell.
  Please use one of the following options:

  Option A — Git Bash (recommended, zero-config):
    1. Install Git for Windows from https://git-scm.com/download/win
    2. Open "Git Bash" from the Start menu
    3. In Git Bash, run:    bash install.sh

  Option B — WSL2 (full Linux environment):
    1. Open PowerShell as Administrator and run:
         wsl --install -d Ubuntu
    2. Restart your computer
    3. Open the Ubuntu terminal and run:
         sudo apt update && sudo apt install -y git curl
         bash install.sh

  Option C — Install manually from source:
    1. Install Git, Python 3.11+, and curl
    2. Run:
         git clone https://github.com/msty256/cloudAgent %TEMP%/cloudagent
         cd %TEMP%/cloudagent/cloudagent
         pip install -e ".[all]"
    (See https://github.com/msty256/cloudAgent for details)
    On Linux/macOS, replace %TEMP% with /tmp.

END_MSG
    exit 1
fi

# Make uv visible early in case it's already installed but not on PATH for this shell.
export PATH="$HOME/.local:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# Set up log-file tee if requested. Must happen AFTER parse_args so LOG_FILE
# is set, but BEFORE any other output. After this exec, [[ -t 1 ]] is false
# (it's a pipe), so the [install.sh] prefix is added on every line.
if [[ -n "$LOG_FILE" ]]; then
    log_file_dir=$(dirname -- "$LOG_FILE")
    if [[ ! -d "$log_file_dir" ]]; then
        mkdir -p "$log_file_dir" 2>/dev/null || { log_warn "Cannot create log dir $log_file_dir; --log-file ignored"; LOG_FILE=""; }
    fi
    if [[ -n "$LOG_FILE" ]]; then
        exec > >(tee -a "$LOG_FILE") 2>&1
    fi
fi

# Install the EXIT trap. Runs on every exit (normal, error, or signal).
# Emits a structured "DONE: success|FAILED" line plus log-file location.
trap '_on_exit_summary $?' EXIT

# Activate debug mode (set -x) if --debug was passed.  Must come after the
# trap setup so the trace output is visible from the very first command.
if [[ "$DEBUG" -eq 1 ]]; then
    set -x
fi
find_project_python() {
    if [[ "$USE_VENV" -eq 1 ]]; then
        venv_python "$CLOUDAGENT_HOME/.venv"
        return $?
    fi

    for candidate in \
        "$(command -v python3 2>/dev/null || true)" \
        "$(command -v python 2>/dev/null || true)"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

install_git_hooks() {
    log_info "Installing local Git hooks (pre-commit, best-effort)..."
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] would run: python -m pre_commit install   (in $CLOUDAGENT_HOME)"
        return 0
    fi

    local repo_root
    repo_root=$(dirname "$CLOUDAGENT_HOME" 2>/dev/null || echo "$CLOUDAGENT_HOME")
    if [[ ! -d "$CLOUDAGENT_HOME/.git" && ! -d "$repo_root/.git" ]] || \
       [[ ! -f "$CLOUDAGENT_HOME/.pre-commit-config.yaml" && ! -f "$repo_root/.pre-commit-config.yaml" ]]; then
        log_warn "Skipping pre-commit hook install (not a Git worktree with .pre-commit-config.yaml)."
        return 0
    fi

    local git_root="$CLOUDAGENT_HOME"
    if [[ -f "$repo_root/.pre-commit-config.yaml" ]]; then
        git_root="$repo_root"
    fi

    local python_bin
    if ! python_bin=$(find_project_python); then
        log_warn "Skipping pre-commit hook install (project Python not found)."
        return 0
    fi

    if ! "$python_bin" -m pre_commit --version >/dev/null 2>&1; then
        log_warn "Skipping pre-commit hook install (pre-commit is not available in the install environment)."
        return 0
    fi

    if (cd "$git_root" && "$python_bin" -m pre_commit install --hook-type pre-commit >/dev/null); then
        log_ok "Installed .git/hooks/pre-commit"
    else
        log_warn "Could not install .git/hooks/pre-commit; run 'python -m pre_commit install' manually if you develop in this checkout."
    fi
}

# ============================================================================
#  Inspection subcommands (read-only diagnostics — safe for agents to call,
#  except for empty directory creation during write-permission checks)
# ============================================================================

# Show current install state. No side effects.
cmd_status() {
    echo "=== cloudagent install status ==="
    echo "  Installer   : v${INSTALLER_VERSION}  (would install cloudagent v${CLOUDAGENT_VERSION})"
    echo "  Repo URL    : $REPO_URL"
    echo "  Git ref     : $REPO_REF"
    echo "  Install dir : $CLOUDAGENT_HOME"
    echo "  Config dir  : $CONFIG_DIR"
    echo "  Local bin   : $LOCAL_BIN"
    echo ""
    if [[ -d "$CLOUDAGENT_HOME/.git" ]]; then
        local installed_sha installed_branch
        installed_sha=$(cd "$CLOUDAGENT_HOME" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
        installed_branch=$(cd "$CLOUDAGENT_HOME" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
        echo "  Git state   :"
        echo "    branch    : $installed_branch"
        echo "    commit    : $installed_sha"
        if [[ -d "$CLOUDAGENT_HOME/.venv" ]]; then
            local py_ver
            local venv_py
            if venv_py=$(venv_python "$CLOUDAGENT_HOME/.venv"); then
                py_ver=$("$venv_py" --version 2>&1 | head -1 || echo "missing")
            else
                py_ver="missing"
            fi
            echo "  Venv        : present (Python: $py_ver)"
        else
            echo "  Venv        : MISSING (run '$0 update' to recreate)"
        fi
    else
        echo "  Git state   : NOT INSTALLED (run '$0 install')"
    fi
    echo ""
    echo "  Commands:"
    for cmd in cloudagent cloudagent; do
        if [[ -x "$LOCAL_BIN/$cmd" ]]; then
            echo "    $LOCAL_BIN/$cmd : present"
        else
            echo "    $LOCAL_BIN/$cmd : MISSING"
        fi
    done
    echo ""
    if command -v cloudagent >/dev/null 2>&1; then
        echo "  cloudagent resolves to: $(command -v cloudagent)"
    else
        echo "  cloudagent NOT on PATH (run: source ~/.bashrc)"
    fi
    echo ""
    echo "=== end of status ==="
}

# Diagnose the environment. No side effects (only reads).
# Exit 0 if all critical checks pass, 1 if any fail.
cmd_doctor() {
    local fail=0 warn=0
    echo "=== cloudagent environment doctor ==="
    echo ""

    # 1. OS
    echo "[1/10] OS detection"
    if [[ "$OS" == "unknown" ]]; then
        echo "        ✗ unknown OS"
        fail=$((fail+1))
    else
        echo "        ✓ $OS"
    fi

    # 2. Git
    echo "[2/10] Git"
    if command -v git >/dev/null 2>&1; then
        echo "        ✓ $(git --version)"
    else
        echo "        ✗ git not found"
        echo "          install: $(os_install_hint_oneliner "$OS")"
        fail=$((fail+1))
    fi

    # 3. Python
    echo "[3/10] Python >= $PYTHON_MIN_VERSION"
    if command -v uv >/dev/null 2>&1; then
        local py
        if py=$(uv python find "$PYTHON_MIN_VERSION" 2>/dev/null) && [[ -n "$py" ]]; then
            echo "        ✓ $py ($($py --version 2>&1))"
        else
            echo "        ! no Python $PYTHON_MIN_VERSION+ found (uv will provision on install)"
            warn=$((warn+1))
        fi
    else
        echo "        ! uv not on PATH yet (Python check deferred to install time)"
        warn=$((warn+1))
    fi

    # 4. uv
    echo "[4/10] uv"
    if command -v uv >/dev/null 2>&1; then
        echo "        ✓ $(uv --version)"
    else
        echo "        ! uv not on PATH (will be installed by $0)"
        warn=$((warn+1))
    fi

    # 5. Network
    echo "[5/10] Network reachability"
    if curl -sSf --connect-timeout 5 --max-time 10 -o /dev/null "$REPO_URL" 2>/dev/null; then
        echo "        ✓ repo reachable: $REPO_URL"
    else
        echo "        ✗ cannot reach $REPO_URL"
        echo "          check: proxy settings, VPN, DNS, firewall"
        fail=$((fail+1))
    fi

    # 6. Write access to install dir
    echo "[6/10] Write access to install dir"
    local parent
    parent=$(dirname -- "$CLOUDAGENT_HOME")
    # Walk up to find the nearest existing parent directory for write check
    local check_dir="$parent"
    while [[ ! -d "$check_dir" && "$check_dir" != "/" ]]; do
        check_dir=$(dirname -- "$check_dir")
    done
    if [[ -w "$check_dir" ]]; then
        echo "        ✓ writable: $parent (parent $check_dir is writable)"
    else
        echo "        ✗ cannot write: $parent"
        echo "          fix: sudo chown -R \$USER $parent   (or pick a different --install-dir)"
        fail=$((fail+1))
    fi

    # 7. Write access to config dir
    echo "[7/10] Write access to config dir"
    local cfg_check="$CONFIG_DIR"
    while [[ ! -d "$cfg_check" && "$cfg_check" != "/" ]]; do
        cfg_check=$(dirname -- "$cfg_check")
    done
    if [[ -w "$cfg_check" ]]; then
        echo "        ✓ writable: $CONFIG_DIR"
    else
        echo "        ✗ cannot write: $CONFIG_DIR"
        fail=$((fail+1))
    fi

    # 8. Disk space
    echo "[8/10] Disk space"
    local avail_kb
    avail_kb=$(df -Pk "$CLOUDAGENT_PARENT_DIR" 2>/dev/null | awk 'NR==2 {print $4}')
    if [[ -n "$avail_kb" ]] && [[ $avail_kb -gt $MIN_DISK_KB ]]; then
        echo "        ✓ $(( avail_kb / 1024 ))MB available"
    else
        echo "        ✗ < $(( MIN_DISK_KB / 1024 ))MB available at $CLOUDAGENT_PARENT_DIR (need ~$(( MIN_DISK_KB / 1024 ))MB for venv + deps)"
        fail=$((fail+1))
    fi

    # 9. PATH
    echo "[9/10] ~/.local/bin in PATH"
    if [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
        echo "        ✓ $HOME/.local/bin is in current PATH"
    else
        echo "        ! $HOME/.local/bin NOT in current PATH (will be patched on install)"
        warn=$((warn+1))
    fi

    # 10. Existing install
    echo "[10/10] Existing install"
    if [[ -d "$CLOUDAGENT_HOME/.git" ]]; then
        echo "        ✓ installed at $CLOUDAGENT_HOME"
        echo "          (run '$0 verify' to check health, '$0 update' to refresh)"
    else
        echo "        ! not installed yet"
        warn=$((warn+1))
    fi

    echo ""
    echo "=== summary ==="
    echo "  critical : $fail"
    echo "  warnings : $warn"
    echo ""
    if [[ $fail -gt 0 ]]; then
        echo "  Result: NOT READY ($fail critical issue(s))"
        exit 1
    else
        echo "  Result: READY to install (or already installed)"
        exit 0
    fi
}

# Health check an existing install. No side effects.
cmd_verify() {
    local fail=0 warn=0
    echo "=== cloudagent install verification ==="
    echo ""

    # 1. Repo
    echo "[1/6] Repo"
    if [[ -d "$CLOUDAGENT_HOME/.git" ]]; then
        echo "      ✓ present at $CLOUDAGENT_HOME"
    else
        echo "      ✗ NOT FOUND at $CLOUDAGENT_HOME"
        echo "        run: $0 install"
        fail=$((fail+1))
    fi

    # 2. Venv
    echo "[2/6] Venv"
    if [[ -d "$CLOUDAGENT_HOME/.venv" ]]; then
        echo "      ✓ present at $CLOUDAGENT_HOME/.venv"
        local venv_py
        if venv_py=$(venv_python "$CLOUDAGENT_HOME/.venv"); then
            echo "      ✓ python works: $("$venv_py" --version 2>&1)"
        else
            echo "      ✗ python missing in venv"
            fail=$((fail+1))
        fi
    else
        echo "      ✗ venv MISSING at $CLOUDAGENT_HOME/.venv"
        echo "        run: $0 update   (or: $0 install)"
        fail=$((fail+1))
    fi

    # 3. Entry point
    echo "[3/6] Entry point"
    local entry=""
    if [[ -d "$CLOUDAGENT_HOME/.venv" ]]; then
        entry=$(find_venv_entry "$CLOUDAGENT_HOME/.venv" "$ENTRY_POINT" 2>/dev/null || true)
    fi
    if [[ -n "$entry" && -x "$entry" ]]; then
        echo "      ✓ $ENTRY_POINT at $entry"
    else
        echo "      ✗ $ENTRY_POINT not found in venv"
        echo "        run: $0 update"
        fail=$((fail+1))
    fi

    # 4. Wrappers
    echo "[4/6] Command wrappers"
    for cmd in cloudagent cloudagent; do
        if [[ -x "$LOCAL_BIN/$cmd" ]]; then
            echo "      ✓ $LOCAL_BIN/$cmd"
        else
            echo "      ✗ $LOCAL_BIN/$cmd MISSING"
            echo "        run: $0 install"
            fail=$((fail+1))
        fi
    done

    # 5. PATH
    echo "[5/6] PATH"
    if command -v cloudagent >/dev/null 2>&1; then
        echo "      ✓ cloudagent resolves to: $(command -v cloudagent)"
    else
        echo "      ! cloudagent NOT on PATH (wrappers exist but not exported)"
        echo "        run: source ~/.bashrc   (or ~/.zshrc)"
        warn=$((warn+1))
    fi

    # 6. Smoke test
    echo "[6/6] Smoke test (cloudagent --version)"
    if command -v cloudagent >/dev/null 2>&1; then
        if cloudagent --version >/dev/null 2>&1; then
            echo "      ✓ cloudagent --version works"
        else
            echo "      ✗ cloudagent --version FAILED (exit $?)"
            fail=$((fail+1))
        fi
    else
        echo "      ! skipped (not on PATH)"
        warn=$((warn+1))
    fi

    echo ""
    if [[ $fail -gt 0 ]]; then
        echo "=== Result: UNHEALTHY ($fail issue(s), $warn warning(s)) ==="
        echo ""
        echo "Try:"
        echo "  $0 update                                  # re-pull and re-install deps"
        echo "  $0 uninstall && $0                         # full clean reinstall"
        exit 1
    else
        echo "=== Result: HEALTHY ($warn warning(s)) ==="
        exit 0
    fi
}

# Update: pull latest and reinstall deps. Side effects: yes.
cmd_update() {
    log_info "Updating cloudagent at $CLOUDAGENT_HOME (ref: $REPO_REF)..."
    if [[ "$STANDALONE" -eq 1 ]]; then
        # 本地源码安装没有 git 仓库，检查产品目录本身
        if [[ ! -d "$CLOUDAGENT_HOME" ]]; then
            die_with_help "No existing install at $CLOUDAGENT_HOME." \
                          "Run: $0 install   (fresh install)" \
                          "Or:  $0 doctor    (diagnose environment)"
        fi
    elif [[ ! -d "$CLOUDAGENT_HOME/.git" ]]; then
        die_with_help "No existing install at $CLOUDAGENT_HOME." \
                      "Run: $0 install   (fresh install)" \
                      "Or:  $0 doctor    (diagnose environment)"
    fi
    clone_or_update_repo
    ensure_local_env_file
    install_deps
    install_git_hooks
    register_commands
    log_ok "Update complete."
    log_info "Run '$0 verify' to confirm health."
}

# ============================================================================
#  Uninstall — only removes what this script created
# ============================================================================
uninstall() {
    log_info "Uninstalling cloudagent..."
    log_info "  Install dir : $CLOUDAGENT_HOME"
    log_info "  Config dir  : $CONFIG_DIR"
    log_info "  Local bin   : $LOCAL_BIN"

    for f in cloudagent cloudagent; do
        local wrapper="$LOCAL_BIN/$f"
        if [[ -e "$wrapper" || -L "$wrapper" ]]; then
            # Safety check: only remove wrappers that point inside THIS
            # install dir. This protects multi-install users from
            # cascading deletes when they uninstall one install while
            # another (sharing $LOCAL_BIN) is still active. It also
            # prevents `uninstall --install-dir /tmp/test` from wiping
            # the production wrappers in $HOME/.local/bin.
            if grep -qF "$CLOUDAGENT_HOME" "$wrapper" 2>/dev/null; then
                rm -f "$wrapper"
                log_ok "Removed $wrapper"
            else
                log_warn "Skipped $wrapper — does not point inside $CLOUDAGENT_HOME (other install?)"
            fi
        fi
    done

    if [[ -d "$CLOUDAGENT_HOME" ]]; then
        # Safety check: prevent accidental rm -rf of system directories
        local _abort=""
        if [[ ${#CLOUDAGENT_HOME} -lt 8 ]]; then
            log_err "Safety check FAILED: install dir path is too short (${#CLOUDAGENT_HOME} chars)."
            _abort=1
        fi
        case "$CLOUDAGENT_HOME" in
            /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/sbin|/sys|/usr|/var)
                log_err "Safety check FAILED: refusing to remove system directory '$CLOUDAGENT_HOME'."
                _abort=1 ;;
        esac
        if [[ -z "$_abort" ]]; then
            rm -rf "$CLOUDAGENT_HOME"
            log_ok "Removed $CLOUDAGENT_HOME"
        else
            log_err "Uninstall aborted — re-run with a valid --install-dir."
            return 1
        fi
    fi
    # Only auto-remove the install's parent dir if it's empty AND it's NOT
    # also the config dir. Otherwise --config-dir == --install-dir-parent
    # would nuke the runtime state we explicitly keep.
    if [[ -d "$CLOUDAGENT_PARENT_DIR" ]] \
        && [[ "$CLOUDAGENT_PARENT_DIR" != "$CONFIG_DIR" ]] \
        && [[ -z "$(ls -A "$CLOUDAGENT_PARENT_DIR" 2>/dev/null)" ]]; then
        rmdir "$CLOUDAGENT_PARENT_DIR" 2>/dev/null || true
        log_ok "Removed empty $CLOUDAGENT_PARENT_DIR"
    fi

    # Config dir is preserved by design — it contains the user's sessions,
    # auth tokens, history, etc. Removing it requires an explicit rm.
    if [[ -d "$CONFIG_DIR" ]]; then
        log_warn "Preserved config dir: $CONFIG_DIR  (delete manually with 'rm -rf' if desired)"
    fi

    log_warn "Note: this script does not edit your shell rc files. To remove the"
    log_warn "PATH entry, search for '$RC_MARKER' in ~/.bashrc / ~/.zshrc / ~/.profile"
    log_warn "and delete the two lines under it."

    # Auto-clean rc files when --yes is passed
    if [[ "${ASSUME_YES:-0}" -eq 1 ]]; then
        for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
            if [[ -f "$rc" ]] && grep -qF "$RC_MARKER" "$rc" 2>/dev/null; then
                log_info "Cleaning cloudagent PATH entry from $rc..."
                # Using sed to delete lines from RC_MARKER to the next line
                sed -i "/$RC_MARKER/,+1d" "$rc" 2>/dev/null && \
                    log_ok "Cleaned $rc" || \
                    log_warn "Could not auto-clean $rc — please remove the cloudagent PATH entry manually."
            fi
        done
    fi

    log_ok "Uninstall complete."
}

# ============================================================================
print_help() {
    cat <<EOF
cloudagent installer v${INSTALLER_VERSION}  (installs cloudagent v${CLOUDAGENT_VERSION})

USAGE
    $0 [SUBCOMMAND] [OPTIONS]

SUBCOMMANDS
    (none) / install   Install cloudagent (default action).
    status             Show current install state — no side effects.
    doctor             Diagnose the environment (git, python, network, disk,
                       permissions) — no side effects.
    verify             Health-check an existing install (venv, entry point,
                       PATH, smoke test) — no side effects.
    update             Pull latest from the configured ref and reinstall deps.
    uninstall          Remove everything this installer created.
    help               Show this help.

OPTIONS
    --ref <ref>            Override the git ref to install (commit SHA, tag, or
                           branch). Default: ${REPO_REF} (derived from
                           CLOUDAGENT_VERSION). Useful for pinning to an exact
                           commit during bisection or for testing unreleased
                           code.
    --install-dir <path>   Override the project clone + venv location.
                           Default: ${DEFAULT_INSTALL_DIR}
    --config-dir <path>    Override the runtime config directory
                           (sessions, auth, history). Default: ${DEFAULT_CONFIG_DIR}
                           Exposed to cloudagent via the CLOUDAGENT_CONFIG_DIR
                           env var injected by the wrapper scripts.
    --no-venv              Skip virtual-environment creation. Dependencies are
                           installed into the active system Python via
                           'uv pip install --system'. Use this in Docker
                           images, system-Python distros, or any environment
                           where the venv would be redundant.
    --no-setup             Skip the post-install configuration-wizard prompt.
                           Use for non-interactive / CI / Docker installs.
                           You can configure later by running 'cloudagent'.
    --debug                Enable shell trace mode (set -x) for debugging
                           installer failures.  Produces verbose output of
                           every command executed.
    --dry-run              Preview every change without applying it. Prints
                           each command that would run as '[DRY-RUN] would
                           run: ...'. Combines well with status / doctor.
    --yes, -y              Assume 'yes' for any interactive prompts.
    --log-file <path>      Tee all output (stdout + stderr) to <path>. The
                           EXIT summary prints the log file path on success
                           and on failure.
    --uninstall, -u        Alias for the 'uninstall' subcommand.
    --help, -h             Show this help (English).
    --help-zh              Show help in Chinese (中文帮助).
    --version, -v          Print installer version.

DEFAULTS
    Repo         : ${REPO_URL}
    Git ref      : ${REPO_REF}  (override with --ref)
    Install path : ${DEFAULT_INSTALL_DIR}  (override with --install-dir)
    Config path  : ${DEFAULT_CONFIG_DIR}  (override with --config-dir)
    Python       : ${PYTHON_MIN_VERSION} - ${PYTHON_MAX_SUPPORTED}  (provisioned by uv if missing)
    Tooling      : uv (Astral's package manager — installed user-local, no sudo)

LOCAL-SOURCE MODE
    When this script is run from a cloudagent checkout, it deploys that
    local source directly — no cloudAgent gitcode clone and no upstream GitHub
    fetch. Auto-detected; --install-dir still overrides where the product is
    deployed.

EXAMPLES
    # First-time install (most common):
    $0

    # Check if install is healthy (agent / CI / post-deploy check):
    $0 verify

    # See what's installed and where:
    $0 status

    # Diagnose the environment before installing:
    $0 doctor

    # Install a specific tag (e.g. for bisection):
    $0 --ref v0.5.0

    # Custom install + config directories (e.g. system-wide):
    sudo $0 --install-dir /opt/cloudagent --config-dir /var/lib/cloudagent

    # Non-interactive install for CI / Docker (no venv, no setup wizard):
    $0 --no-venv --no-setup --yes --log-file /tmp/install.log

    # Preview what an install would do without applying:
    $0 --dry-run

    # Re-run after a failed install to capture full output for bug reports:
    $0 --log-file /tmp/install.log
    # ... and read /tmp/install.log

    # Remove everything this script installed (preserves config dir):
    $0 uninstall

TROUBLESHOOTING
    "Git is not installed"
        Install Git for your platform (apt/dnf/brew/xcode-select). Re-run $0.

    "uv installer failed to download" / network errors
        Check your network, proxy, or VPN. Retry: $0.
        Manual uv install: pip install uv

    "git clone failed"
        Verify network: curl -I ${REPO_URL}
        If behind a firewall, configure a proxy or use a mirror.

    "uv venv failed" / "uv sync failed" / "uv pip install failed"
        Re-run with --log-file to capture full output: $0 --log-file /tmp/out.log
        Diagnose: $0 doctor
        Clean reinstall: $0 uninstall && $0

    "Python 3.14+ detected — pyo3-ffi version mismatch"
        Python 3.14 is not yet supported by the pyo3-ffi dependency used
        by outlines-core. The installer auto-detects this and attempts to
        provision Python 3.13. If it fails, manually install 3.11-3.13:
            uv python install 3.13
            pyenv install 3.13 && pyenv local 3.13
        Or set PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 and retry (risky).

    "cloudagent: command not found" after install
        Your shell hasn't picked up the new PATH yet. Run:
            source ~/.bashrc   # or: source ~/.zshrc
        Or open a new terminal.

    Permission errors when writing to $HOME/.local/bin or $HOME/.cloudagent
        Pick a writable location: $0 --install-dir ~/apps/cloudagent

    Stale install (changes don't take effect)
        Pull latest + reinstall: $0 update
        Hard reset:             $0 uninstall && $0

EXIT CODES
    0    Success.
    1    Installation / verification / doctor found a problem.
    2    Invalid CLI argument (unknown flag, missing value).
    3    Doctor / verify found critical issues.

VERSIONING
    This install.sh is paired 1:1 with a cloudagent release. CLOUDAGENT_VERSION and
    REPO_REF are the version pin; the matching uv.lock pins every transitive
    dependency. To install a different cloudagent version, download the
    install.sh that ships with that release — do NOT just edit these constants
    in isolation, since the lock file is what actually pins the dependency
    versions. The --ref flag is a deliberate escape hatch for testing specific
    commits and is NOT a substitute for shipping a properly tagged installer.

NOTES
    - Re-running this script is safe: existing repos are fast-forwarded,
      existing venvs are reused, command wrappers are regenerated.
    - install/update creates a local .env template when missing and attempts
      to install .git/hooks/pre-commit after deps are available. Hook
      installation is best-effort and never blocks CLI setup.
    - On Windows, run from Git Bash or WSL. To set up:
        Git Bash : install Git for Windows (https://git-scm.com/download/win),
                   open "Git Bash" from the Start menu, then run this script.
        WSL2     : open PowerShell as Admin, run 'wsl --install -d Ubuntu',
                   then run this script in the Ubuntu terminal.
        The script detects native cmd.exe / PowerShell and exits with a
        clear instruction — it does NOT support those shells directly.
    - In non-TTY mode (piped / agent / CI), every emitted line is prefixed
      with '[install.sh]'. The EXIT trap emits a 'DONE: success|FAILED'
      line on its own, so you can grep the tail of any captured log.
EOF
}

print_help_zh() {
    cat <<EOF
cloudagent 安装脚本 v${INSTALLER_VERSION}  (安装 cloudagent v${CLOUDAGENT_VERSION})

用法
    $0 [子命令] [选项]

子命令
    （无） / install   安装 cloudagent（默认动作）。
    status             显示当前安装状态——无副作用。
    doctor             诊断环境（git、python、网络、磁盘、权限）——无副作用。
    verify             健康检查已有安装（venv、入口、PATH、烟雾测试）——无副作用。
    update             拉取最新代码并重装依赖。
    uninstall          卸载本脚本创建的所有内容。
    help               显示本帮助。

选项
    --ref <引用>           覆盖要安装的 git 引用（commit SHA、tag 或分支）。
                           默认：${REPO_REF}（由 CLOUDAGENT_VERSION 推导得出）。
                           常用于 bisect 时精确锁定 commit，或测试未发布代码。
    --install-dir <路径>   覆盖项目克隆和 venv 所在的位置。
                           默认：${DEFAULT_INSTALL_DIR}
    --config-dir <路径>    覆盖运行时配置目录（会话、鉴权、历史记录）。
                           默认：${DEFAULT_CONFIG_DIR}
                           通过 wrapper 脚本注入的 CLOUDAGENT_CONFIG_DIR
                           环境变量暴露给 cloudagent。
    --no-venv              跳过虚拟环境的创建。依赖直接安装到当前系统
                           Python（使用 'uv pip install --system'）。适用
                           于 Docker 镜像、发行版自带 Python、或任何 venv
                           多余的环境。
    --no-setup             跳过安装后的交互式配置向导。适用于非交互 / CI
                           / Docker 场景。之后可随时手动运行
                           'cloudagent' 进行配置。
    --debug                启用 shell 追踪模式（set -x），用于调试安装
                           失败原因。会输出每一条执行的命令。
    --dry-run              预览所有改动但不实际执行。把每条会运行的命令打
                           印为 '[DRY-RUN] would run: ...'。与 status /
                           doctor 配合使用效果更佳。
    --yes, -y              对所有交互式提示默认回答 yes。
    --log-file <路径>      把所有输出（stdout + stderr）同时写入 <路径>。
                           退出摘要会在成功 / 失败时都打印日志路径。
    --uninstall, -u        'uninstall' 子命令的简写。
    --help, -h             显示英文版帮助。
    --help-zh              显示本中文版帮助。
    --version, -v          打印安装脚本版本。

默认值
    仓库地址   ：${REPO_URL}
    Git 引用  ：${REPO_REF}  （用 --ref 覆盖）
    安装路径  ：${DEFAULT_INSTALL_DIR}  （用 --install-dir 覆盖）
    配置路径  ：${DEFAULT_CONFIG_DIR}  （用 --config-dir 覆盖）
    Python    ：${PYTHON_MIN_VERSION} - ${PYTHON_MAX_SUPPORTED}  （缺失时由 uv 自动提供）
    工具链    ：uv（Astral 的包管理器——用户级安装，无需 sudo）

本地源码模式
    当本脚本运行于 cloudagent checkout 时，直接从本地部署——
    不再 clone gitcode.com 的 cloudAgent，也不拉取任何上游源码。
    该模式自动检测；--install-dir 仍可覆盖产品部署位置。

示例
    # 首次安装（最常见）：
    $0

    # 检查安装是否健康（agent / CI / 部署后检查）：
    $0 verify

    # 查看已安装的内容和位置：
    $0 status

    # 安装前诊断环境：
    $0 doctor

    # 安装特定 tag（例如 bisect 时）：
    $0 --ref v0.5.0

    # 自定义安装和配置目录（例如系统级）：
    sudo $0 --install-dir /opt/cloudagent --config-dir /var/lib/cloudagent

    # CI / Docker 环境的非交互式安装（无 venv、无配置向导）：
    $0 --no-venv --no-setup --yes --log-file /tmp/install.log

    # 预览安装流程而不实际执行：
    $0 --dry-run

    # 安装失败后重新运行以捕获完整输出供排查：
    $0 --log-file /tmp/install.log
    # ... 然后查看 /tmp/install.log

    # 移除本脚本安装的所有内容（保留配置目录）：
    $0 uninstall

故障排查
    "Git is not installed"
        安装 Git：apt/dnf/brew/xcode-select，然后重新运行 $0。

    "uv installer failed to download" / 网络错误
        检查网络、代理、VPN。重试：$0。
        手动安装 uv：pip install uv

    "git clone failed"
        验证网络：curl -I ${REPO_URL}
        如果在防火墙后，配置代理或使用镜像。

    "uv venv failed" / "uv sync failed" / "uv pip install failed"
        重新运行并用 --log-file 捕获完整输出：$0 --log-file /tmp/out.log
        诊断：$0 doctor
        干净重装：$0 uninstall && $0

    "检测到 Python 3.14+ — pyo3-ffi 版本不兼容"
        Python 3.14 尚不被 outlines-core 依赖的 pyo3-ffi 支持。
        安装脚本会自动检测并尝试安装 Python 3.13。如果自动修复失败，
        请手动安装 3.11-3.13：
            uv python install 3.13
            pyenv install 3.13 && pyenv local 3.13
        或者设置 PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 后重试（有风险）。

    安装后提示 "cloudagent: command not found"
        当前 shell 还没加载新的 PATH。运行：
            source ~/.bashrc   # 或：source ~/.zshrc
        或新开一个终端。

    写入 $HOME/.local/bin 或 $HOME/.cloudagent 时权限错误
        选择可写位置：$0 --install-dir ~/apps/cloudagent

    安装版本陈旧（修改不生效）
        拉取最新 + 重装：$0 update
        硬重置：        $0 uninstall && $0

退出码
    0    成功。
    1    安装 / 验证 / 诊断发现问题。
    2    无效的 CLI 参数（未知选项、缺少值）。
    3    doctor / verify 发现严重问题。

版本控制
    本 install.sh 与 cloudagent 的某个发布版本一一对应。CLOUDAGENT_VERSION
    和 REPO_REF 是版本钉子；对应的 uv.lock 把所有传递依赖一并锁定。要
    安装不同版本的 cloudagent，请下载该发布版自带的 install.sh——不要
    单独修改这些常量，因为真正钉住依赖版本的是 lock 文件。--ref 标志
    是用于测试特定 commit 的有意保留的逃生口，**不能**替代正规打 tag
    的安装脚本。

注意事项
    - 重复运行本脚本是安全的：已存在的仓库会 fast-forward，已存在的
      venv 会复用，命令 wrapper 会重新生成。
    - install/update 会在缺失时创建本地 .env 模板，并在依赖可用后尝试
      安装 .git/hooks/pre-commit。hook 安装是 best-effort，不会阻断
      CLI 安装。
    - 在 Windows 上请从 Git Bash 或 WSL 运行。设置方式：
        Git Bash : 安装 Git for Windows (https://git-scm.com/download/win)，
                   在开始菜单中打开 "Git Bash"，然后运行本脚本。
        WSL2     : 以管理员身份打开 PowerShell，执行 'wsl --install -d Ubuntu'，
                   重启后在 Ubuntu 终端中运行本脚本。
        原生 cmd.exe / PowerShell 不支持本脚本——运行时会被检测到并给出
        明确的提示信息。
    - 在非 TTY 模式（管道 / agent / CI）下，每一行输出都会加上
      '[install.sh]' 前缀。EXIT trap 会单独输出一行
      'DONE: success|FAILED'，所以你可以直接 grep 日志末尾判断结果。
EOF
}

setup_upstream_src() {
    # 单层代码库：src/ 已并入 cloudagent_ext/，没有需要水合的上游源码。
    # 保留该函数作为安装流程中的兼容占位。
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        _script_p1
        echo "[DRY-RUN] source is self-contained (cloudagent_ext/ only, no upstream fetch)"
    fi
    return 0
}

# Dispatch to subcommand. Default to 'install' when none was given.
case "${SUBCOMMAND:-install}" in
    install)   install_main ;;
    status)    cmd_status ;;
    doctor)    cmd_doctor ;;
    verify)    cmd_verify ;;
    update)    cmd_update ;;
    uninstall) uninstall ;;
    help)      print_help ;;
    help-zh)   print_help_zh ;;
    *)
        log_err "Unknown subcommand: $SUBCOMMAND"
        echo "Usage: $0 {install|status|doctor|verify|update|uninstall|help}"
        exit 1
        ;;
esac
