#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_bin=${ERSATZRS_ADDON_SETTING_PYTHON_BIN:-python3}
if ! { [ -x "$python_bin" ] || command -v "$python_bin" >/dev/null 2>&1; }; then
    if [ "${1:-}" = check ]; then
        printf '%s\n' '{"status":"unavailable","code":"missing-command","message":"The configured Python executable is unavailable."}'
        exit 0
    fi
    printf '%s\n' 'configured Python executable is unavailable' >&2
    exit 69
fi
exec "$python_bin" "$script_dir/trakt.py" "${1:-}"
