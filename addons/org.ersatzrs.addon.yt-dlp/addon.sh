#!/bin/sh

set -eu
set -f

operation=${1:-}
yt_dlp=${ERSATZRS_ADDON_SETTING_YT_DLP_BIN:-yt-dlp}
js_runtime=deno

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

enumerate_playlist() {
    output_template=$1
    playlist_url=$2
    if "$yt_dlp" \
        --no-config \
        --no-update \
        --quiet \
        --flat-playlist \
        --output-na-placeholder null \
        --parse-metadata 'availability:(?P<ersatzrs_unavailable>private|premium_only|subscriber_only|needs_auth)' \
        --parse-metadata '%(availability|unknown)s:%(ersatzrs_availability)s' \
        --replace-in-metadata ersatzrs_availability '^(public|unlisted)$' available \
        --replace-in-metadata ersatzrs_availability '^(private|premium_only|subscriber_only|needs_auth)$' unavailable \
        --replace-in-metadata ersatzrs_availability '^(?!(available|unavailable|unknown)$).*$' unknown \
        --parse-metadata '%(series&ERSATZRS_TV|)s %(episode&ERSATZRS_TV|)s %(track&ERSATZRS_MUSIC|)s %(artist&ERSATZRS_MUSIC|)s %(categories)l %(tags)l %(title)s:%(ersatzrs_content_kind)s' \
        --replace-in-metadata ersatzrs_content_kind '(?i).*(advertisement|commercial|reclame).*' other_video \
        --replace-in-metadata ersatzrs_content_kind '(?i).*(ERSATZRS_MUSIC|music video|videoclip|concert|music|muziek).*' music_video \
        --replace-in-metadata ersatzrs_content_kind '(?i).*(movie|film|speelfilm).*' movie \
        --replace-in-metadata ersatzrs_content_kind '(?i).*ERSATZRS_TV.*' television_episode \
        --replace-in-metadata ersatzrs_content_kind '^(?!(other_video|music_video|movie|television_episode)$).*$' auto \
        --print "$output_template" \
        "$playlist_url"
    then
        return 0
    else
        status=$?
        fail provider-unreachable "The video provider request failed." "$status"
    fi
}

enumerate_media_list() {
    playlist_url=$1
    if "$yt_dlp" \
        --no-config \
        --no-update \
        --quiet \
        --skip-download \
        --ignore-errors \
        --dump-single-json \
        "$playlist_url" \
        | deno run --quiet --allow-env=ERSATZRS_MEDIA_LIST_URL,PLAYLIST_URL \
            "$(dirname "$0")/libexec/media-list.ts"
    then
        return 0
    else
        status=$?
        fail provider-unreachable "The video provider request failed." "$status"
    fi
}

case "$operation" in
    check)
        if ! have_program "$yt_dlp" || ! have_program "$FFMPEG_BIN"; then
            printf '%s\n' '{"status":"unavailable","code":"missing-command","message":"yt-dlp or managed FFmpeg is unavailable."}'
        elif ! have_program "$js_runtime"; then
            # yt-dlp enables only this runtime by default. Without it the
            # provider hands back a player response whose media URL is bound to
            # a restricted client, and the managed FFmpeg downloader is refused
            # when it fetches that URL, so playback cannot succeed.
            printf '%s\n' '{"status":"unavailable","code":"missing-js-runtime","message":"A JavaScript runtime is required for playback and was not found."}'
        else
            printf '%s\n' '{"status":"ready","code":"ready","message":"yt-dlp Remote Streams is ready."}'
        fi
        ;;
    list)
        playlist_url=${ERSATZRS_MEDIA_LIST_URL:-${ERSATZRS_REMOTE_STREAM_PLAYLIST_URL:-}}
        [ -n "$playlist_url" ] || fail missing-setting "A playlist URL is required." 64
        case "$playlist_url" in
            http://*|https://*) ;;
            *) fail unsupported-url "The playlist URL must use HTTP or HTTPS." 64 ;;
        esac
        case "$playlist_url" in
            *[\"\\]*) fail unsupported-url "The playlist URL contains unsupported characters." 64 ;;
        esac
        if [ -n "${ERSATZRS_MEDIA_LIST_URL:-}" ]; then
            enumerate_media_list "$playlist_url"
            exit 0
        fi
        enumerate_playlist \
            '{"id":%(id)j,"provider_id":%(id)j,"url":%(webpage_url,original_url,url)j,"title":%(title)j,"plot":%(description)j,"duration_seconds":%(duration)j,"year":%(release_year)j,"genres":%(categories)j,"tags":%(tags)j,"thumbnail_url":%(thumbnail)j,"availability":%(ersatzrs_availability)j,"availability_reason":%(ersatzrs_unavailable&"not_playable"|null)s,"content_kind":%(ersatzrs_content_kind)j,"guids":["yt-dlp://%(id)s"],"is_live":false}' \
            "$playlist_url"
        ;;
    item)
        [ -n "${ERSATZRS_REMOTE_STREAM_ITEM_IDS:-}" ] || fail missing-setting "At least one item identity is required." 64
        # The host has already applied its item limit, filters, and exclusions,
        # so this describes only the entries it kept. Unlike enumeration this
        # is a full extraction, which is what makes the descriptive fields
        # available at all.
        metadata_file=$(mktemp)
        trap 'rm -f "$metadata_file"' EXIT HUP INT TERM
        if printf '%s\n' "$ERSATZRS_REMOTE_STREAM_ITEM_IDS" \
            | while IFS= read -r item_id; do
                  [ -n "$item_id" ] || continue
                  case "$item_id" in
                      *[\"\\]*|-*) continue ;;
                  esac
                  printf 'https://www.youtube.com/watch?v=%s\n' "$item_id"
              done \
            | "$yt_dlp" \
                --no-config \
                --no-update \
                --quiet \
                --no-playlist \
                --ignore-errors \
                --skip-download \
                --dump-json \
                --batch-file - >"$metadata_file"
        then
            if deno run --quiet "$(dirname "$0")/libexec/item-metadata.ts" <"$metadata_file"; then
                rm -f "$metadata_file"
                trap - EXIT HUP INT TERM
                exit 0
            fi
            status=$?
        else
            status=$?
        fi
        rm -f "$metadata_file"
        trap - EXIT HUP INT TERM
        fail provider-unreachable "The video provider request failed." "$status"
        ;;
    play)
        [ -n "${ERSATZRS_REMOTE_STREAM_URL:-}" ] || fail missing-setting "A remote stream URL is required." 64
        YT_DLP_BIN=$yt_dlp export YT_DLP_BIN
        if deno run --quiet --allow-env --allow-run "$(dirname "$0")/libexec/fragment-playback.ts"
        then
            exit 0
        else
            status=$?
            fail provider-unreachable "The video provider request failed." "$status"
        fi
        ;;
    *)
        fail operation-failed "Unsupported add-on operation." 64
        ;;
esac
