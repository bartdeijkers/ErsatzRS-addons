#!/bin/sh

set -eu
set -f

operation=${1:-}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
curl_bin=${ERSATZRS_ADDON_SETTING_CURL_BIN:-curl}
export CURL_BIN=$curl_bin
if [ -n "${ERSATZRS_ADDON_SETTING_ACTION_ID:-}" ]; then
    export BEELDENGELUID_ACTION_ID=$ERSATZRS_ADDON_SETTING_ACTION_ID
fi

have_program() {
    [ -x "$1" ] || command -v "$1" >/dev/null 2>&1
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
            exec /bin/sh "$script_dir/libexec/beeldengeluid.sh" list "$ERSATZRS_MEDIA_LIST_URL"
        fi
        : "${ERSATZRS_REMOTE_STREAM_PLAYLIST_URL:?playlist URL is required}"
        exec /bin/sh "$script_dir/libexec/beeldengeluid.sh" list "$ERSATZRS_REMOTE_STREAM_PLAYLIST_URL"
        ;;
    play)
        : "${ERSATZRS_REMOTE_STREAM_URL:?remote stream URL is required}"
        seek=${ERSATZRS_REMOTE_STREAM_SEEK:-0}
        exec /bin/sh "$script_dir/libexec/beeldengeluid.sh" play "$ERSATZRS_REMOTE_STREAM_URL" "$seek"
        ;;
    *)
        echo "unsupported add-on operation" >&2
        exit 64
        ;;
esac
