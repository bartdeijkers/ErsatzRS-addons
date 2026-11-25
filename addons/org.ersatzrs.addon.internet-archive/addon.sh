#!/bin/sh
# Internet Archive add-on entrypoint (Deno).
set -eu
set -f
case $0 in
    */*) script_dir=${0%/*} ;;
    *) script_dir=. ;;
esac
operation=${1:-}
main="$script_dir/libexec/main.mts"

fail() {
    printf '{"code":"%s","message":"%s"}\n' "$1" "$2" >&2
    exit "${3:-70}"
}

command -v deno >/dev/null 2>&1 || {
    if [ "$operation" = check ]; then
        printf '%s\n' '{"status":"unavailable","code":"missing-js-runtime","message":"Deno is required and was not found on PATH."}'
        exit 0
    fi
    fail missing-js-runtime "Deno is required and was not found on PATH." 69
}

env_names=ERSATZRS_MEDIA_LIST_URL,ERSATZRS_REMOTE_STREAM_PLAYLIST_URL,ERSATZRS_REMOTE_STREAM_URL,ERSATZRS_REMOTE_STREAM_SEEK,FFMPEG_BIN
case "$operation" in
    check)
        if [ -n "${FFMPEG_BIN:-}" ]; then
            exec deno run --quiet --no-prompt "--allow-env=$env_names" "--allow-read=$FFMPEG_BIN" "$main" check
        fi
        exec deno run --quiet --no-prompt "--allow-env=$env_names" "$main" check
        ;;
    list)
        exec deno run --quiet --no-prompt "--allow-env=$env_names" --allow-net=archive.org "$main" list
        ;;
    play)
        [ -n "${FFMPEG_BIN:-}" ] || fail missing-command "The managed FFmpeg runtime is unavailable." 69
        # The FFmpeg child inherits the (host-cleared) environment, which
        # Deno's process spawning reads in full.
        exec deno run --quiet --no-prompt --allow-env --allow-net=archive.org \
            "--allow-run=$FFMPEG_BIN" "$main" play
        ;;
    *)
        fail operation-failed "Unsupported add-on operation." 64
        ;;
esac
