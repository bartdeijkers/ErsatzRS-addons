#!/bin/sh

set -eu
set -f

operation=${1:-}
yt_dlp=${ERSATZRS_ADDON_SETTING_YT_DLP_BIN:-yt-dlp}

have_program() {
    [ -x "$1" ] || command -v "$1" >/dev/null 2>&1
}

enumerate_playlist() {
    output_template=$1
    playlist_url=$2
    exec "$yt_dlp" \
        --no-config \
        --no-update \
        --quiet \
        --flat-playlist \
        --output-na-placeholder null \
        --parse-metadata '%(series&ERSATZRS_TV|)s %(episode&ERSATZRS_TV|)s %(track&ERSATZRS_MUSIC|)s %(artist&ERSATZRS_MUSIC|)s %(categories)l %(tags)l %(title)s:%(ersatzrs_content_kind)s' \
        --replace-in-metadata ersatzrs_content_kind '(?i).*(advertisement|commercial|reclame).*' other_video \
        --replace-in-metadata ersatzrs_content_kind '(?i).*(ERSATZRS_MUSIC|music video|videoclip|concert|music|muziek).*' music_video \
        --replace-in-metadata ersatzrs_content_kind '(?i).*(movie|film|speelfilm).*' movie \
        --replace-in-metadata ersatzrs_content_kind '(?i).*ERSATZRS_TV.*' television_episode \
        --replace-in-metadata ersatzrs_content_kind '^(?!(other_video|music_video|movie|television_episode)$).*$' auto \
        --print "$output_template" \
        "$playlist_url"
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
            enumerate_playlist \
                '{"record_type":"item","provider_id":%(id)j,"rank":%(playlist_autonumber)d,"display_title":%(title)j,"title":%(title)j,"kind":"remote_stream","guids":["yt-dlp://%(id)s"],"source_url":%(webpage_url,original_url,url)j,"availability":%(availability)j,"content_kind":%(ersatzrs_content_kind)j}' \
                "$playlist_url"
        fi
        enumerate_playlist \
            '{"id":%(id)j,"provider_id":%(id)j,"url":%(webpage_url,original_url,url)j,"title":%(title)j,"plot":%(description)j,"duration_seconds":%(duration)j,"year":%(release_year)j,"genres":%(categories)j,"tags":%(tags)j,"thumbnail_url":%(thumbnail)j,"availability":%(availability)j,"content_kind":%(ersatzrs_content_kind)j,"guids":["yt-dlp://%(id)s"],"is_live":false}' \
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
