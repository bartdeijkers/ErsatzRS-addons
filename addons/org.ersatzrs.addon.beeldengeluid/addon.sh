#!/bin/sh

set -eu
set -f

operation=${1:-}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
curl_bin=${ERSATZRS_ADDON_SETTING_CURL_BIN:-curl}
export CURL_BIN=$curl_bin

have_program() {
    [ -x "$1" ] || command -v "$1" >/dev/null 2>&1
}

fail() {
    code=$1
    message=$2
    status=${3:-70}
    printf '{"code":"%s","message":"%s"}\n' "$code" "$message" >&2
    exit "$status"
}

run_provider() {
    if /bin/sh "$script_dir/libexec/beeldengeluid.sh" "$@"; then
        return 0
    else
        status=$?
        fail provider-unreachable "The media provider request failed." "$status"
    fi
}

check() {
    for program in "$FFMPEG_BIN" "$curl_bin" awk grep dd sed mktemp; do
        if ! have_program "$program"; then
            printf '%s\n' '{"status":"unavailable","code":"missing-command","message":"A required executable is unavailable."}'
            exit 0
        fi
    done
    printf '%s\n' '{"status":"ready","code":"ready","message":"Beeld & Geluid is ready."}'
}

case "$operation" in
    check)
        check
        ;;
    list)
        if [ -n "${ERSATZRS_MEDIA_LIST_URL:-}" ]; then
            export BEELDENGELUID_OUTPUT=media-list
            run_provider list "$ERSATZRS_MEDIA_LIST_URL"
            exit 0
        fi
        [ -n "${ERSATZRS_REMOTE_STREAM_PLAYLIST_URL:-}" ] || fail missing-setting "A playlist URL is required." 64
        run_provider list "$ERSATZRS_REMOTE_STREAM_PLAYLIST_URL"
        ;;
    play)
        [ -n "${ERSATZRS_REMOTE_STREAM_URL:-}" ] || fail missing-setting "A remote stream URL is required." 64
        seek=${ERSATZRS_REMOTE_STREAM_SEEK:-0}
        run_provider play "$ERSATZRS_REMOTE_STREAM_URL" "$seek"
        ;;
    *)
        fail operation-failed "Unsupported add-on operation." 64
        ;;
esac
