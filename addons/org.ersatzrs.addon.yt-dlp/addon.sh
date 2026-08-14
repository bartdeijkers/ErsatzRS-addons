#!/bin/sh

set -eu
set -f

operation=${1:-}
yt_dlp=${ERSATZRS_ADDON_SETTING_YT_DLP_BIN:-yt-dlp}

have_program() {
    [ -x "$1" ] || command -v "$1" >/dev/null 2>&1
}

case "$operation" in
    check)
        if ! have_program "$yt_dlp" || ! have_program "$FFMPEG_BIN"; then
            printf '%s\n' '{"status":"unavailable","code":"missing-command","message":"yt-dlp or managed FFmpeg is unavailable."}'
        else
            printf '%s\n' '{"status":"ready","code":"ready","message":"yt-dlp Remote Streams is ready."}'
        fi
        ;;
    list)
        playlist_url=${ERSATZRS_MEDIA_LIST_URL:-${ERSATZRS_REMOTE_STREAM_PLAYLIST_URL:-}}
        : "${playlist_url:?playlist URL is required}"
        case "$playlist_url" in
            http://*|https://*) ;;
            *) echo "playlist URL must use HTTP or HTTPS" >&2; exit 64 ;;
        esac
        case "$playlist_url" in
            *[\"\\]*) echo "playlist URL contains unsupported characters" >&2; exit 64 ;;
        esac
        if [ -n "${ERSATZRS_MEDIA_LIST_URL:-}" ]; then
            printf '%s\n' "{\"record_type\":\"list\",\"provider_id\":\"$playlist_url\",\"name\":\"yt-dlp playlist\",\"description\":\"Remote videos selected by the supplied playlist link.\"}"
            exec "$yt_dlp" \
                --no-config \
                --no-update \
                --quiet \
                --flat-playlist \
                --print '{"record_type":"item","provider_id":%(id)j,"rank":%(playlist_autonumber)d,"display_title":%(title)j,"title":%(title)j,"kind":"remote_stream","guids":[],"source_url":%(webpage_url)j}' \
                "$playlist_url"
        fi
        exec "$yt_dlp" \
            --no-config \
            --no-update \
            --quiet \
            --flat-playlist \
            --print '{"id":%(id)j,"url":%(webpage_url)j,"title":%(title)j,"duration_seconds":%(duration)j,"is_live":false}' \
            "$playlist_url"
        ;;
    play)
        : "${ERSATZRS_REMOTE_STREAM_URL:?remote stream URL is required}"
        seek=${ERSATZRS_REMOTE_STREAM_SEEK:-0}
        case "$seek" in
            ''|*[!0-9:.]*)
                echo "seek timestamp is invalid" >&2
                exit 64
                ;;
        esac
        exec "$yt_dlp" \
            --no-config \
            --no-update \
            --quiet \
            --no-playlist \
            --ffmpeg-location "$FFMPEG_BIN" \
            --downloader ffmpeg \
            --downloader-args "ffmpeg_i:-ss $seek" \
            --hls-use-mpegts \
            --format 'best[ext=mp4][vcodec*=avc1][acodec*=mp4a]/best[acodec!=none][vcodec!=none]' \
            --output - \
            "$ERSATZRS_REMOTE_STREAM_URL"
        ;;
    *)
        echo "unsupported add-on operation" >&2
        exit 64
        ;;
esac
