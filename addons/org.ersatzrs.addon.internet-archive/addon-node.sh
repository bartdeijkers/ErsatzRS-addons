#!/bin/sh
# Internet Archive add-on entrypoint for Linux ARMv7, where Deno publishes no
# build. The same sources run under Node.js 22.18 or newer (type stripping).
set -eu
set -f
case $0 in
    */*) script_dir=${0%/*} ;;
    *) script_dir=. ;;
esac
operation=${1:-}
if ! command -v node >/dev/null 2>&1; then
    if [ "$operation" = check ]; then
        printf '%s\n' '{"status":"unavailable","code":"missing-js-runtime","message":"Node.js is required and was not found on PATH."}'
        exit 0
    fi
    printf '%s\n' '{"code":"missing-js-runtime","message":"Node.js is required and was not found on PATH."}' >&2
    exit 69
fi
exec node --no-warnings "$script_dir/libexec/main.mts" "$operation"
