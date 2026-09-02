#!/usr/bin/env bash
set -euo pipefail

TEAMKIT_REPO="${TEAMKIT_REPO:-Jaulous/agents-teamkit}"
TEAMKIT_REF="${TEAMKIT_REF:-v0.3.4}"
TEAMKIT_PYTHON_BIN="${TEAMKIT_PYTHON_BIN:-python3}"
TEAMKIT_PACKAGE_NAME="${TEAMKIT_PACKAGE_NAME:-agents-teamkit-workbench}"
TEAMKIT_SOURCE_DIR="${TEAMKIT_SOURCE_DIR:-}"
TEAMKIT_WORKBUDDY_CONFIG_DIR="${TEAMKIT_WORKBUDDY_CONFIG_DIR:-${WORKBUDDY_CONFIG_DIR:-}}"

log() {
  printf '%s\n' "$*" >&2
}

fail() {
  printf 'TeamKit install failed: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

pip_install() {
  local proxy_env
  proxy_env="${ALL_PROXY:-}${HTTPS_PROXY:-}${HTTP_PROXY:-}${all_proxy:-}${https_proxy:-}${http_proxy:-}"
  if [[ "$proxy_env" == *socks* || "$proxy_env" == *SOCKS* ]]; then
    env -u ALL_PROXY -u HTTPS_PROXY -u HTTP_PROXY -u all_proxy -u https_proxy -u http_proxy \
      PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 "$venv_python" -m pip "$@"
    return $?
  fi
  if env PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 "$venv_python" -m pip "$@"; then
    return 0
  fi
  log "Retrying pip without proxy environment variables..."
  env -u ALL_PROXY -u HTTPS_PROXY -u HTTP_PROXY -u all_proxy -u https_proxy -u http_proxy \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 "$venv_python" -m pip "$@"
}

resolve_local_source() {
  local script_path script_dir source_dir
  script_path="${BASH_SOURCE[0]:-}"
  if [ -z "$script_path" ] || [ "$script_path" = "bash" ] || [ "$script_path" = "-bash" ]; then
    return 1
  fi
  script_dir="$(cd "$(dirname "$script_path")" >/dev/null 2>&1 && pwd -P)" || return 1
  source_dir="$(cd "$script_dir/.." >/dev/null 2>&1 && pwd -P)" || return 1
  if [ -f "$source_dir/bin/teamkit" ] && [ -f "$source_dir/teamkit/cli.py" ]; then
    printf '%s\n' "$source_dir"
    return 0
  fi
  return 1
}

download_source() {
  local tmp_dir archive source_dir
  tmp_dir="$1"
  archive="$tmp_dir/teamkit.tar.gz"
  log "Downloading TeamKit from github.com/$TEAMKIT_REPO ($TEAMKIT_REF)..."
  curl -fsSL "https://codeload.github.com/$TEAMKIT_REPO/tar.gz/$TEAMKIT_REF" -o "$archive"
  tar -xzf "$archive" -C "$tmp_dir"
  source_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [ -n "$source_dir" ] || fail "could not unpack TeamKit source archive"
  [ -f "$source_dir/bin/teamkit" ] || fail "downloaded archive does not look like TeamKit source"
  printf '%s\n' "$source_dir"
}

need_cmd curl
need_cmd tar
need_cmd find
need_cmd "$TEAMKIT_PYTHON_BIN"

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/teamkit-install.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

if [ -n "$TEAMKIT_SOURCE_DIR" ]; then
  source_dir="$TEAMKIT_SOURCE_DIR"
elif source_dir="$(resolve_local_source)"; then
  log "Using local TeamKit source: $source_dir"
else
  source_dir="$(download_source "$tmp_dir")"
fi

[ -f "$source_dir/pyproject.toml" ] || fail "TeamKit source is missing pyproject.toml: $source_dir"

log "Preparing temporary TeamKit Python runtime..."
"$TEAMKIT_PYTHON_BIN" -m venv "$tmp_dir/venv"
venv_python="$tmp_dir/venv/bin/python"
[ -x "$venv_python" ] || fail "venv python was not created at $venv_python"

pip_install install "PyYAML>=6.0" >/dev/null
"$venv_python" -c "import yaml" || fail "PyYAML is not available in the temporary TeamKit runtime"

build_root="$tmp_dir/build/workbuddy"
log "Exporting Agents TeamKit Workbench package..."
"$venv_python" "$source_dir/bin/teamkit" workbuddy export-init \
  --out "$build_root" \
  --name "$TEAMKIT_PACKAGE_NAME" \
  --force >/dev/null

install_args=(
  "$venv_python"
  "$source_dir/bin/teamkit"
  "workbuddy"
  "install"
  "--package"
  "$build_root/$TEAMKIT_PACKAGE_NAME"
  "--force"
  "--json"
)
if [ -n "$TEAMKIT_WORKBUDDY_CONFIG_DIR" ]; then
  install_args+=("--config-dir" "$TEAMKIT_WORKBUDDY_CONFIG_DIR")
fi

log "Installing Agents TeamKit Workbench into WorkBuddy..."
install_output="$("${install_args[@]}")"
log "$install_output"

log ""
log "Agents TeamKit Workbench installed."
log "Open WorkBuddy and look for: Agents TeamKit 工作台"
log ""
log "Update later with the same command. Override source with TEAMKIT_REPO, TEAMKIT_REF, or TEAMKIT_SOURCE_DIR when needed."
