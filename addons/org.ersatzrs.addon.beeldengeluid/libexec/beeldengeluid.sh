#!/bin/sh

# Enumerate or stream Beeld & Geluid "Schatkamer" media for ErsatzRS.

set -eu
set -f

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
adapter_script="$script_dir/media-list-adapter.ts"

usage() {
    echo "Usage: beeldengeluid.sh list <Schatkamer series or shared-list URL>" >&2
    echo "       beeldengeluid.sh play <Schatkamer episode URL> [seek timestamp]" >&2
    echo "       beeldengeluid.sh <Schatkamer episode URL> [seek timestamp]" >&2
}

html_decode() {
    sed \
        -e 's/&amp;/\&/g' \
        -e 's/&quot;/"/g' \
        -e "s/&#x27;/'/g" \
        -e 's/&#39;/'"'"'/g' \
        -e 's/&lt;/</g' \
        -e 's/&gt;/>/g'
}

json_escape() {
    sed \
        -e 's/\\/\\\\/g' \
        -e 's/"/\\"/g' \
        -e 's/	/\\t/g' \
        -e 's//\\r/g'
}

escaped_json_slice() {
    start=$1
    end=$2
    file=$3
    awk -v start_name="$start" -v end_name="$end" '
        BEGIN {
            slash = sprintf("%c", 92)
            start = slash "\"" start_name slash "\":"
            end = "," slash "\"" end_name slash "\":"
        }
        {
            rest = $0
            while ((found = index(rest, start)) > 0) {
                candidate = substr(rest, found + length(start))
                finish = index(candidate, end)
                if (finish > 0) result = substr(candidate, 1, finish - 1)
                rest = candidate
            }
        }
        END {
            if (length(result)) print result
        }
    ' "$file"
}

json_object_names() {
    escaped_json_slice "$1" "$2" "$3" \
        | grep -o '\\"name\\":\\"[^\"]*' \
        | sed 's/^.*\\"//' \
        | html_decode
}

json_array_values() {
    escaped_json_slice "$1" "$2" "$3" \
        | grep -o '\\"[^\"]*\\"' \
        | sed -e 's/^\\"//' -e 's/\\"$//' \
        | html_decode
}

json_scalar_value() {
    escaped_json_slice "$1" "$2" "$3" \
        | sed \
            -e 's/^\\"//' \
            -e 's/\\"$//' \
            -e 's/\\\\n/ /g' \
            -e 's/\\\\r/ /g' \
            -e 's/\\\\t/ /g' \
            -e 's/\\\\\\"/"/g' \
            -e 's/\\u0026/\&/g' \
        | html_decode
}

json_ld_series_value() {
    field=$1
    file=$2
    awk -v field="$field" '
        {
            type_at = index($0, "\"@type\":\"CreativeWorkSeries\"")
            if (!type_at) next
            rest = substr($0, type_at)
            marker = "\"" field "\":\""
            value_at = index(rest, marker)
            if (!value_at) next
            value = substr(rest, value_at + length(marker))
            result = ""
            escaped = 0
            for (i = 1; i <= length(value); i++) {
                character = substr(value, i, 1)
                if (escaped) {
                    if (character == "n" || character == "r" || character == "t") result = result " "
                    else result = result character
                    escaped = 0
                } else if (character == "\\") escaped = 1
                else if (character == "\"") { print result; exit }
                else result = result character
            }
        }
    ' "$file" | html_decode
}

write_json_array() {
    field=$1
    file=$2
    [ -s "$file" ] || return 0
    printf ',"%s":[' "$field"
    separator=
    awk '!seen[tolower($0)]++' "$file" | while IFS= read -r value; do
        [ -n "$value" ] || continue
        escaped=$(printf '%s' "$value" | json_escape)
        printf '%s"%s"' "$separator" "$escaped"
        separator=,
    done
    printf ']'
}

extract_card_images() {
    page_file=$1
    deno run --quiet --allow-read="$page_file" "$adapter_script" \
        --extract-cards "$page_file" >>"$list_work_dir/card-images.tsv" \
        || fail "episode card metadata was invalid"
}

discover_series_paths() {
    series_base=$1
    page_number=1
    while :; do
        page_url="$series_base?pagina=$page_number"
        "$curl_bin" --fail --silent --show-error --location --max-redirs 5 --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 45 \
            --output "$list_work_dir/page.html" "$page_url" \
            || fail "the Schatkamer series page request failed"
        extract_card_images "$list_work_dir/page.html"
        if [ "$page_number" -eq 1 ]; then
            sed '' "$list_work_dir/page.html" >"$list_work_dir/source-page.html"
        fi
        grep -o 'href="/serie/[0-9][0-9]*/[^"/]*/aflevering/[0-9][0-9]*"' \
            "$list_work_dir/page.html" \
            | sed -e 's/^href="//' -e 's/"$//' \
            | awk '!seen[$0]++' >"$list_work_dir/page-links.txt"
        : >"$list_work_dir/new-links.txt"
        while IFS= read -r episode_path; do
            if ! grep -Fqx "$episode_path" "$list_work_dir/seen.txt"; then
                printf '%s\n' "$episode_path" >>"$list_work_dir/seen.txt"
                printf '%s\n' "$episode_path" >>"$list_work_dir/new-links.txt"
            fi
        done <"$list_work_dir/page-links.txt"
        page_new_count=$(awk 'END { print NR + 0 }' "$list_work_dir/new-links.txt")
        printf 'beeldengeluid.sh: series page %s yielded %s new episode(s)\n' \
            "$page_number" "$page_new_count" >&2
        [ -s "$list_work_dir/new-links.txt" ] || break
        page_number=$((page_number + 1))
    done
    [ -s "$list_work_dir/seen.txt" ] \
        || fail "the Schatkamer series did not contain playable episodes"
}

discover_search_paths() {
    search_url=$1
    page_number=1
    while :; do
        case "$search_url" in
            *\?*) page_url="$search_url&pagina=$page_number" ;;
            *) page_url="$search_url?pagina=$page_number" ;;
        esac
        "$curl_bin" --fail --silent --show-error --location --max-redirs 5 --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 45 \
            --output "$list_work_dir/page.html" "$page_url" \
            || fail "the Schatkamer search page request failed"
        extract_card_images "$list_work_dir/page.html"
        grep -o 'href="/serie/[0-9][0-9]*/[^"/]*/aflevering/[0-9][0-9]*"' \
            "$list_work_dir/page.html" \
            | sed -e 's/^href="//' -e 's/"$//' \
            | awk '!seen[$0]++' >"$list_work_dir/page-links.txt"
        : >"$list_work_dir/new-links.txt"
        while IFS= read -r episode_path; do
            if ! grep -Fqx "$episode_path" "$list_work_dir/seen.txt"; then
                printf '%s\n' "$episode_path" >>"$list_work_dir/seen.txt"
                printf '%s\n' "$episode_path" >>"$list_work_dir/new-links.txt"
            fi
        done <"$list_work_dir/page-links.txt"
        page_new_count=$(awk 'END { print NR + 0 }' "$list_work_dir/new-links.txt")
        printf 'beeldengeluid.sh: search page %s yielded %s new result(s)\n' \
            "$page_number" "$page_new_count" >&2
        [ -s "$list_work_dir/new-links.txt" ] || break
        page_number=$((page_number + 1))
    done
    [ -s "$list_work_dir/seen.txt" ] \
        || fail "the Schatkamer search did not contain playable episodes"
}

discover_shared_list_paths() {
    shared_list_url=$1
    : >"$list_work_dir/list-entries.txt"
    unavailable_count=0
    page_number=1
    while :; do
        page_url="$shared_list_url?pagina=$page_number"
        "$curl_bin" --fail --silent --show-error --location --max-redirs 5 --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 45 \
            --output "$list_work_dir/page.html" "$page_url" \
            || fail "the Schatkamer shared-list page request failed"
        extract_card_images "$list_work_dir/page.html"
        sed 's/\\"/"/g' "$list_work_dir/page.html" \
            >"$list_work_dir/normalized-list.html"
        if [ "$page_number" -eq 1 ]; then
            grep -Fq '"description":"Gedeelde lijst"' \
                "$list_work_dir/normalized-list.html" \
                || fail "the Schatkamer shared list is unavailable or private"
            shared_list_name=$(grep -o '"title":"[^"]*","description":"Gedeelde lijst"' \
                "$list_work_dir/normalized-list.html" \
                | sed -n '1{s/^"title":"//;s/","description":"Gedeelde lijst"$//;p;}' \
                | sed -e 's/\\u0026/\&/g' -e 's/\\u003c/</g' -e 's/\\u003e/>/g' \
                    -e "s/\\\\u0027/'/g" -e 's|\\/|/|g')
        fi
        awk '
            BEGIN {
                marker = "\"url\":\"https://schatkamer.beeldengeluid.nl/serie/"
                playable_marker = "\"isPlayable\":"
            }
            {
                rest = $0
                while ((start = index(rest, marker)) > 0) {
                    candidate = substr(rest, start + length(marker))
                    finish = index(candidate, "\"")
                    if (finish == 0) break
                    suffix = substr(candidate, 1, finish - 1)
                    after_url = substr(candidate, finish + 1)
                    playable_at = index(after_url, playable_marker)
                    next_url = index(after_url, marker)
                    if (playable_at > 0 && (next_url == 0 || playable_at < next_url)) {
                        state = substr(after_url, playable_at + length(playable_marker), 5)
                        if (state ~ /^true/) print "playable|/serie/" suffix
                        else if (state ~ /^false/) print "unavailable|/serie/" suffix
                    }
                    rest = after_url
                }
            }
        ' "$list_work_dir/normalized-list.html" >"$list_work_dir/page-entries.txt"
        page_new=0
        while IFS='|' read -r state episode_path; do
            [ -n "$episode_path" ] || continue
            if ! printf '%s\n' "$episode_path" \
                | LC_ALL=C grep -Eq '^/serie/[0-9]+/[^/]+/aflevering/[0-9]+$'; then
                continue
            fi
            if grep -Fqx "$episode_path" "$list_work_dir/seen-all.txt"; then
                continue
            fi
            printf '%s\n' "$episode_path" >>"$list_work_dir/seen-all.txt"
            printf '%s\n' "$episode_path" >>"$list_work_dir/seen.txt"
            printf '%s|%s\n' "$state" "$episode_path" >>"$list_work_dir/list-entries.txt"
            page_new=$((page_new + 1))
            if [ "$state" != playable ]; then
                unavailable_count=$((unavailable_count + 1))
            fi
        done <"$list_work_dir/page-entries.txt"
        printf 'beeldengeluid.sh: shared-list page %s yielded %s new item(s)\n' \
            "$page_number" "$page_new" >&2
        [ "$page_new" -gt 0 ] || break
        page_number=$((page_number + 1))
    done

    [ -s "$list_work_dir/seen.txt" ] \
        || fail "the Schatkamer shared list did not contain episodes"
    if [ "$unavailable_count" -gt 0 ]; then
        printf 'beeldengeluid.sh: retained %s unavailable Schatkamer shared-list item(s)\n' \
            "$unavailable_count" >&2
    fi
}

list_playlist() {
    [ "$#" -eq 1 ] || { usage; exit 64; }
    playlist_url=${1%%\#*}
    output_mode=${BEELDENGELUID_OUTPUT:-remote-stream}
    case "$output_mode" in
        remote-stream | media-list) ;;
        *) fail "unsupported list output contract" 64 ;;
    esac
    source_kind=${ERSATZRS_MEDIA_LIST_SOURCE_KIND:-}
    case "$playlist_url" in
        https://schatkamer.beeldengeluid.nl/zoeken | \
            https://schatkamer.beeldengeluid.nl/zoeken/* | \
            https://schatkamer.beeldengeluid.nl/zoeken\?* | \
            http://schatkamer.beeldengeluid.nl/zoeken | \
            http://schatkamer.beeldengeluid.nl/zoeken/* | \
            http://schatkamer.beeldengeluid.nl/zoeken\?*)
            source_kind=search
            ;;
        https://schatkamer.beeldengeluid.nl/serie/*/* | \
            http://schatkamer.beeldengeluid.nl/serie/*/* | \
            https://schatkamer.beeldengeluid.nl/programma/*/* | \
            http://schatkamer.beeldengeluid.nl/programma/*/*)
            playlist_url=${playlist_url%%\?*}
            playlist_url=${playlist_url%/}
            case "$playlist_url" in
                */aflevering/*) source_kind=video ;;
                *) source_kind=series ;;
            esac
            ;;
        https://schatkamer.beeldengeluid.nl/lijst/* | \
            http://schatkamer.beeldengeluid.nl/lijst/*)
            playlist_url=${playlist_url%%\?*}
            playlist_url=${playlist_url%/}
            list_id=${playlist_url##*/}
            if ! printf '%s\n' "$list_id" \
                | LC_ALL=C grep -Eq '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'; then
                fail "the Schatkamer shared-list ID must be a UUID" 64
            fi
            source_kind=shared_list
            ;;
        *)
            fail "unsupported Schatkamer playlist URL" 64
            ;;
    esac
    curl_bin=${CURL_BIN:-curl}
    find_program "$curl_bin" "curl"
    find_program grep "grep"
    find_program sed "sed"
    find_program awk "awk"
    find_program mktemp "mktemp"
    find_program deno "Deno"

    list_work_dir=$(mktemp -d "${TMPDIR:-/tmp}/ersatzrs-beeldengeluid-list.XXXXXX") \
        || fail "unable to create a temporary directory"
    list_cleanup() {
        rm -f "$list_work_dir"/*
        rmdir "$list_work_dir" 2>/dev/null || true
    }
    trap list_cleanup EXIT HUP INT TERM
    : >"$list_work_dir/seen.txt"
    : >"$list_work_dir/seen-all.txt"
    : >"$list_work_dir/card-images.tsv"
    shared_list_name=
    list_description='Programmes selected by the supplied Schatkamer link.'
    list_image=
    if [ "$source_kind" = video ]; then
        episode_path=${playlist_url#*://schatkamer.beeldengeluid.nl}
        printf '%s\n' "$episode_path" >"$list_work_dir/seen.txt"
    elif [ "$source_kind" = series ]; then
        discover_series_paths "$playlist_url"
        shared_list_name=$(json_ld_series_value name "$list_work_dir/source-page.html")
        series_description=$(json_ld_series_value description "$list_work_dir/source-page.html")
        list_image=$(json_ld_series_value image "$list_work_dir/source-page.html")
        [ -z "$series_description" ] || list_description=$series_description
    elif [ "$source_kind" = search ]; then
        discover_search_paths "$playlist_url"
    else
        discover_shared_list_paths "$playlist_url"
    fi
    rank=0
    if [ "$output_mode" = media-list ]; then
        provider_id=${playlist_url#*://schatkamer.beeldengeluid.nl/}
        provider_id=$(printf '%s' "$provider_id" | json_escape)
        list_name=${shared_list_name:-Beeld & Geluid Schatkamer}
        list_name=$(printf '%s' "$list_name" | json_escape)
        list_description_json=$(printf '%s' "$list_description" | json_escape)
        printf '%s\n' \
            "{\"record_type\":\"list\",\"provider_id\":\"$provider_id\",\"name\":\"$list_name\",\"description\":\"$list_description_json\",\"metadata\":{\"title\":\"$list_name\",\"plot\":\"$list_description_json\",\"guids\":[\"beeldengeluid-list://$provider_id\"]}}" \
            >"$list_work_dir/media-list.ndjson"
    fi
    while IFS= read -r episode_path; do
        episode_id=${episode_path##*/}
        episode_url="https://schatkamer.beeldengeluid.nl$episode_path"
        availability=available
        availability_reason=
        if [ "$source_kind" = shared_list ] \
            && grep -Fqx "unavailable|$episode_path" "$list_work_dir/list-entries.txt"; then
            availability=unavailable
            availability_reason=not_playable
        fi
        if ! "$curl_bin" --fail --silent --show-error --location --max-redirs 5 --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 45 \
            --output "$list_work_dir/episode.html" "$episode_url"; then
            if [ "$availability" != unavailable ]; then
                fail "a Schatkamer episode metadata request failed"
            fi
            episode_slug=$(printf '%s' "$episode_path" \
                | sed -n 's|^/serie/[0-9][0-9]*/\([^/]*\)/aflevering/[0-9][0-9]*$|\1|p' \
                | sed 's/[-_]/ /g')
            title=$(printf '%s' "${episode_slug:-$episode_id}" | json_escape)
            if [ "$output_mode" = media-list ]; then
                printf '%s\n' \
                    "{\"record_type\":\"item\",\"provider_id\":\"episode:$episode_id\",\"rank\":$rank,\"display_title\":\"$title\",\"title\":\"$title\",\"kind\":\"remote_stream\",\"guids\":[\"beeldengeluid://$episode_id\"],\"source_url\":\"$episode_url\",\"availability\":\"unavailable\",\"availability_reason\":\"not_playable\",\"content_kind\":\"auto\"}" \
                    >>"$list_work_dir/media-list.ndjson"
                rank=$((rank + 1))
            else
                printf '%s\n' \
                    "{\"id\":\"$episode_id\",\"provider_id\":\"episode:$episode_id\",\"url\":\"$episode_url\",\"title\":\"$title\",\"availability\":\"unavailable\",\"availability_reason\":\"not_playable\",\"content_kind\":\"auto\",\"guids\":[\"beeldengeluid://$episode_id\"],\"is_live\":false}"
            fi
            continue
        fi
        series_title=$(grep -o '<h1[^>]*>[^<]*' "$list_work_dir/episode.html" \
            | sed -n '1{s/^.*>//;p;}')
        episode_title=$(grep -o '<h3[^>]*>[^<]*' "$list_work_dir/episode.html" \
            | sed -n '1{s/^.*>//;p;}')
        [ -n "$episode_title" ] || episode_title=$episode_id
        series_json=$(printf '%s' "$series_title" | html_decode | json_escape)
        if [ -n "$series_title" ]; then
            title="$series_title - $episode_title"
        else
            title=$episode_title
        fi
        title=$(printf '%s' "$title" | html_decode | json_escape)
        detail_image=$(sed 's/\\"/"/g' "$list_work_dir/episode.html" \
            | grep -o '"image":"https://schatkamer.beeldengeluid.nl/[^"]*"' \
            | sed -n '1{s/^"image":"//;s/"$//;p;}')
        episode_image=$(awk -F '\t' -v path="$episode_path" \
            '$1 == path { print $2; exit }' "$list_work_dir/card-images.tsv")
        [ -n "$episode_image" ] || episode_image=$detail_image
        [ -n "$episode_image" ] || episode_image=$list_image
        plot=$(json_scalar_value description disclaimer \
            "$list_work_dir/episode.html" | json_escape)
        duration_seconds=$(grep -o '\\"durationNumber\\":[0-9][0-9]*' \
            "$list_work_dir/episode.html" \
            | sed -n '1{s/^.*://;p;}')
        release_date=$(grep -o '\\"publishedAtISO\\":\\"[0-9][0-9][0-9][0-9]-[^\"]*' \
            "$list_work_dir/episode.html" \
            | sed -n '$ s/^.*\\"\([0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\).*$/\1/p')
        year=$(printf '%s' "$release_date" | sed -n 's/^\([0-9][0-9][0-9][0-9]\)-.*/\1/p')
        age_rating=$(grep -o '\\"ageRating\\":\\"[^\"]*' \
            "$list_work_dir/episode.html" \
            | sed -n '$ { s/^.*\\"//; p; }' \
            | html_decode)
        case "$age_rating" in
            'Leeftijdsadvies onbekend') content_rating='nl:unknown' ;;
            'Alle leeftijden') content_rating='nl:AL' ;;
            *'onder de '*[0-9]*' jaar')
                content_rating=$(printf '%s' "$age_rating" \
                    | sed -n 's/.*onder de \([0-9][0-9]*\) jaar.*/nl:\1/p')
                ;;
            *) content_rating=$age_rating ;;
        esac

        : >"$list_work_dir/genres.txt"
        : >"$list_work_dir/subjects.txt"
        json_array_values genres subjects "$list_work_dir/episode.html" \
            >"$list_work_dir/genres.txt" || true
        json_array_values subjects collection "$list_work_dir/episode.html" \
            >"$list_work_dir/subjects.txt" || true
        collection=$(grep -o 'href="/zoeken?collectie=[^"]*"[^>]*>[^<]*' \
            "$list_work_dir/episode.html" \
            | sed -n '1{s/^.*>//;p;}' | html_decode | json_escape)

        : >"$list_work_dir/people.txt"
        for role_and_list in \
            'presenter:program-info-presenters-list' \
            'actor:program-info-actors-list' \
            'guest:program-info-guests-list' \
            'director:program-info-directors-list' \
            'performer:program-info-performers-list' \
            'person:program-info-others-list'
        do
            role=${role_and_list%%:*}
            case "$role" in
                presenter) json_field=presenters; next_field=actors ;;
                actor) json_field=actors; next_field=guests ;;
                guest) json_field=guests; next_field=directors ;;
                director) json_field=directors; next_field=performers ;;
                performer) json_field=performers; next_field=others ;;
                person) json_field=others; next_field=productionCompanies ;;
            esac
            json_object_names "$json_field" "$next_field" \
                "$list_work_dir/episode.html" \
                | while IFS= read -r person; do
                    [ -n "$person" ] && printf '%s|%s\n' "$role" "$person"
                done >>"$list_work_dir/people.txt"
        done
        json_array_values productionCompanies genres \
            "$list_work_dir/episode.html" >"$list_work_dir/producers.txt" || true
        json_object_names originalBroadcasters broadcaster \
            "$list_work_dir/episode.html" >"$list_work_dir/original-broadcasters.txt" || true
        json_object_names broadcasters url \
            "$list_work_dir/episode.html" >"$list_work_dir/broadcasters.txt" || true

        content_kind=other_video
        if grep -Eiq 'reclame|commercial|advertentie' \
            "$list_work_dir/genres.txt" "$list_work_dir/subjects.txt"; then
            content_kind=other_video
        elif grep -Eiq 'muziek|music|concert|videoclip|music video' \
            "$list_work_dir/genres.txt" "$list_work_dir/subjects.txt"; then
            content_kind=music_video
        elif grep -Eiq 'speelfilm|film|movie' \
            "$list_work_dir/genres.txt" "$list_work_dir/subjects.txt"; then
            content_kind=movie
        elif [ -n "$series_title" ]; then
            content_kind=television_episode
        fi

        if [ "$output_mode" = media-list ]; then
            printf '{"record_type":"item","provider_id":"episode:%s","rank":%s,"display_title":"%s","title":"%s","kind":"remote_stream","guids":["beeldengeluid://%s"],"source_url":"%s","availability":"%s","content_kind":"%s"' \
                "$episode_id" "$rank" "$title" "$title" "$episode_id" "$episode_url" "$availability" "$content_kind" \
                >>"$list_work_dir/media-list.ndjson"
            [ -z "$availability_reason" ] \
                || printf ',"availability_reason":"%s"' "$availability_reason" >>"$list_work_dir/media-list.ndjson"
            [ -z "$year" ] \
                || printf ',"year":%s' "$year" >>"$list_work_dir/media-list.ndjson"
            [ -z "$duration_seconds" ] \
                || printf ',"duration_seconds":%s' "$duration_seconds" >>"$list_work_dir/media-list.ndjson"
            [ -z "$episode_image" ] \
                || printf ',"additional_image_urls":["%s"]' \
                    "$(printf '%s' "$episode_image" | json_escape)" >>"$list_work_dir/media-list.ndjson"
            printf ',"metadata":{"title":"%s"' "$title" >>"$list_work_dir/media-list.ndjson"
            [ -z "$series_json" ] || printf ',"show_title":"%s"' "$series_json" >>"$list_work_dir/media-list.ndjson"
            [ -z "$plot" ] || printf ',"plot":"%s"' "$plot" >>"$list_work_dir/media-list.ndjson"
            [ -z "$year" ] || printf ',"year":%s' "$year" >>"$list_work_dir/media-list.ndjson"
            [ -z "$release_date" ] || printf ',"release_date":"%s"' "$release_date" >>"$list_work_dir/media-list.ndjson"
            [ -z "$content_rating" ] || printf ',"content_ratings":["%s"]' "$(printf '%s' "$content_rating" | json_escape)" >>"$list_work_dir/media-list.ndjson"
            write_json_array genres "$list_work_dir/genres.txt" >>"$list_work_dir/media-list.ndjson"
            write_json_array tags "$list_work_dir/subjects.txt" >>"$list_work_dir/media-list.ndjson"
            [ -z "$collection" ] || printf ',"collection":"%s"' "$collection" >>"$list_work_dir/media-list.ndjson"
            [ -z "$episode_image" ] || printf ',"artwork":[{"role":"thumb","url":"%s"}]' "$(printf '%s' "$episode_image" | json_escape)" >>"$list_work_dir/media-list.ndjson"
            printf ',"guids":["beeldengeluid://%s"]}}\n' "$episode_id" >>"$list_work_dir/media-list.ndjson"
            rank=$((rank + 1))
            continue
        fi

        printf '{"id":"%s","provider_id":"episode:%s","url":"%s","title":"%s","availability":"%s","content_kind":"%s","guids":["beeldengeluid://%s"]' \
            "$episode_id" "$episode_id" "$episode_url" "$title" "$availability" "$content_kind" "$episode_id"
        [ -z "$availability_reason" ] \
            || printf ',"availability_reason":"%s"' "$availability_reason"
        [ -z "$series_json" ] || printf ',"show_title":"%s"' "$series_json"
        [ -z "$duration_seconds" ] \
            || printf ',"duration_seconds":%s' "$duration_seconds"
        [ -z "$plot" ] || printf ',"plot":"%s"' "$plot"
        [ -z "$episode_image" ] \
            || printf ',"thumbnail_url":"%s","additional_image_urls":["%s"]' \
                "$(printf '%s' "$episode_image" | json_escape)" \
                "$(printf '%s' "$episode_image" | json_escape)"
        [ -z "$year" ] || printf ',"year":%s' "$year"
        [ -z "$release_date" ] || printf ',"release_date":"%s"' "$release_date"
        [ -z "$content_rating" ] \
            || printf ',"content_rating":"%s"' "$(printf '%s' "$content_rating" | json_escape)"
        write_json_array genres "$list_work_dir/genres.txt"
        write_json_array tags "$list_work_dir/subjects.txt"
        [ -z "$collection" ] || printf ',"collection":"%s"' "$collection"
        if [ -s "$list_work_dir/people.txt" ]; then
            printf ',"people":['
            separator=
            while IFS='|' read -r role person; do
                [ -n "$person" ] || continue
                printf '%s{"name":"%s","role":"%s"}' "$separator" \
                    "$(printf '%s' "$person" | json_escape)" "$role"
                separator=,
            done <"$list_work_dir/people.txt"
            printf ']'
        fi
        write_json_array producers "$list_work_dir/producers.txt"
        write_json_array original_broadcasters "$list_work_dir/original-broadcasters.txt"
        write_json_array broadcasters "$list_work_dir/broadcasters.txt"
        printf ',"is_live":false}\n'
    done <"$list_work_dir/seen.txt"
    if [ "$output_mode" = media-list ]; then
        deno run --quiet --allow-read="$list_work_dir/media-list.ndjson" \
            "$adapter_script" --normalize "$list_work_dir/media-list.ndjson" \
            || fail "the metadata adapter rejected provider output"
    fi
    exit 0
}

fail() {
    echo "beeldengeluid.sh: $1" >&2
    exit "${2:-1}"
}

find_program() {
    program=$1
    description=$2
    if ! command -v "$program" >/dev/null 2>&1; then
        fail "$description was not found: $program" 69
    fi
}

query_value() {
    query_string=$1
    wanted_name=$2
    old_ifs=$IFS
    IFS='&'
    set -- $query_string
    IFS=$old_ifs
    for query_part do
        case "$query_part" in
            "$wanted_name="*)
                printf '%s' "${query_part#*=}"
                return 0
                ;;
        esac
    done
    return 1
}

# CloudFront uses a URL-safe Base64 alphabet, but signed query values may
# percent-encode padding or the standard Base64 characters. Decode exactly
# those characters before moving the values from the query into cookies.
decode_cloudfront_value() {
    printf '%s' "$1" | sed \
        -e 's/%2[Bb]/+/g' \
        -e 's/%2[Ff]/\//g' \
        -e 's/%3[Dd]/=/g' \
        -e 's/%2[Dd]/-/g' \
        -e 's/%5[Ff]/_/g' \
        -e 's/%7[Ee]/~/g' \
        -e 's/%25/%/g'
}

if [ "${1:-}" = "list" ]; then
    shift
    list_playlist "$@"
fi
if [ "${1:-}" = "play" ]; then
    shift
fi
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    usage
    exit 64
fi

episode_url=$1
seek_position=${2:-0}
# An older ErsatzRS build passes the opt-in marker through literally. Treat it
# as zero so definitions remain backward compatible while upgrading.
[ "$seek_position" = "{seek}" ] && seek_position=0
case "$episode_url" in
    https://schatkamer.beeldengeluid.nl/serie/*/*/aflevering/* | \
        http://schatkamer.beeldengeluid.nl/serie/*/*/aflevering/*)
        ;;
    *)
        fail "unsupported Schatkamer episode URL: $episode_url" 64
        ;;
esac

url_without_query=${episode_url%%\?*}
url_without_query=${url_without_query%%\#*}
fragment_duration=
case "$episode_url" in
    *\?*)
        fragment_query=${episode_url#*\?}
        fragment_query=${fragment_query%%\#*}
        fragment_start=$(query_value "$fragment_query" start || true)
        fragment_end=$(query_value "$fragment_query" end || true)
        if [ -n "$fragment_start" ]; then
            case "$fragment_start" in *[!0-9]*) fail "fragment start must be whole seconds" 64 ;; esac
            if [ "$seek_position" = 0 ]; then
                seek_position=$fragment_start
            fi
        fi
        if [ -n "$fragment_end" ]; then
            case "$fragment_end" in *[!0-9]*) fail "fragment end must be whole seconds" 64 ;; esac
            [ -n "$fragment_start" ] || fail "fragment end requires fragment start" 64
            [ "$fragment_end" -gt "$fragment_start" ] \
                || fail "fragment end must be after fragment start" 64
            fragment_duration=$((fragment_end - fragment_start))
        fi
        ;;
esac
video_id=${url_without_query##*/}
case "$video_id" in
    '' | *[!0-9]*)
        fail "the Schatkamer episode ID must be numeric" 64
        ;;
esac

curl_bin=${CURL_BIN:-curl}
ffmpeg_bin=${FFMPEG_BIN:-ffmpeg}
find_program "$curl_bin" "curl"
find_program "$ffmpeg_bin" "FFmpeg"
find_program grep "grep"
find_program dd "dd"
find_program sed "sed"
find_program mktemp "mktemp"
if ! printf '%s\n' "$seek_position" \
    | LC_ALL=C grep -Eq '^(0|[0-9]+:[0-9]{2}:[0-9]{2}([.][0-9]+)?)$'; then
    fail "the seek timestamp is invalid" 64
fi

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/ersatzrs-beeldengeluid.XXXXXX") \
    || fail "unable to create a temporary directory"
response_file=$work_dir/response.rsc
markers_file=$work_dir/markers.txt
streams_file=$work_dir/streams.txt
page_file=$work_dir/page.html
chunks_file=$work_dir/chunks.txt
chunk_file=$work_dir/chunk.js
cookies_file=$work_dir/cookies.txt

cleanup() {
    rm -f \
        "$response_file" \
        "$markers_file" \
        "$streams_file" \
        "$page_file" \
        "$chunks_file" \
        "$chunk_file" \
        "$cookies_file"
    rmdir "$work_dir" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

"$curl_bin" \
    --fail \
    --silent \
    --show-error \
    --location \
    --max-redirs 5 \
    --proto '=https' \
    --proto-redir '=https' \
    --cookie-jar "$cookies_file" \
    --output "$page_file" \
    "$url_without_query" \
    || fail "the Schatkamer episode page request failed"

LC_ALL=C grep -aoE 'src="[^"]+\.js[^"]*"' "$page_file" \
    | sed -e 's/^src="//' -e 's/"$//' \
    >"$chunks_file" || true

stream_action_id=
while IFS= read -r chunk_path; do
    case "$chunk_path" in
        /_next/static/chunks/*.js*)
            ;;
        *)
            continue
            ;;
    esac

    "$curl_bin" \
        --fail \
        --silent \
        --show-error \
        --location \
        --max-redirs 5 \
        --proto '=https' \
        --proto-redir '=https' \
        --cookie "$cookies_file" \
        --output "$chunk_file" \
        "https://schatkamer.beeldengeluid.nl$chunk_path" \
        || continue

    action_reference=$(LC_ALL=C grep -aoE \
        '"[0-9a-f]{32,64}"[^;]{0,300}"getProgramStreamById"' \
        "$chunk_file" \
        | sed -n '1p' \
        || true)
    if [ -n "$action_reference" ]; then
        stream_action_id=$(printf '%s' "$action_reference" \
            | sed -n 's/^"\([0-9a-f]\{32,64\}\)".*/\1/p')
        [ -n "$stream_action_id" ] && break
    fi
done <"$chunks_file"

if [ "${#stream_action_id}" -lt 32 ] || [ "${#stream_action_id}" -gt 64 ]; then
    fail "unable to discover a valid getProgramStreamById action"
fi
case "$stream_action_id" in
    *[!0-9a-f]*)
        fail "unable to discover a valid getProgramStreamById action"
        ;;
esac

payload="[\"$video_id\",false]"
"$curl_bin" \
    --fail \
    --silent \
    --show-error \
    --request POST \
    --cookie "$cookies_file" \
    --cookie-jar "$cookies_file" \
    --header 'Content-Type: text/plain;charset=UTF-8' \
    --header "Next-Action: $stream_action_id" \
    --header 'Accept: text/x-component' \
    --data-binary "$payload" \
    --output "$response_file" \
    "$url_without_query" \
    || fail "the Schatkamer stream request failed"

# RSC text chunks use "<row>:T<hex-size>,<content>". Locate each marker by
# byte offset, then use dd to read the declared number of bytes so adjacent
# chunks cannot corrupt a signed URL.
LC_ALL=C grep -aobE '[0-9]+:T[0-9a-fA-F]+,' "$response_file" >"$markers_file" || true
: >"$streams_file"

while IFS= read -r marker_match; do
    [ -n "$marker_match" ] || continue
    marker_offset=${marker_match%%:*}
    marker=${marker_match#*:}
    hex_size=${marker#*T}
    hex_size=${hex_size%,}
    chunk_size=$((0x$hex_size))
    chunk_start=$((marker_offset + ${#marker}))
    chunk=$(dd if="$response_file" bs=1 skip="$chunk_start" count="$chunk_size" 2>/dev/null)

    case "$chunk" in
        *sk-video.cdn.beeldengeluid.nl*.m3u8*)
            printf '%s\n' "$chunk" \
                | sed \
                    -e 's/^[[:space:]]*//' \
                    -e 's/[[:space:]]*$//' \
                    -e 's/\\u0026/\&/g' \
                >>"$streams_file"
            ;;
    esac
done <"$markers_file"

[ -s "$streams_file" ] || fail "no signed HLS stream URL was found"

while IFS= read -r signed_url; do
    [ -n "$signed_url" ] || continue
    case "$signed_url" in
        https://sk-video.cdn.beeldengeluid.nl/*.m3u8\?*)
            ;;
        *)
            fail "the Server Action returned an unexpected stream URL"
            ;;
    esac

    base_url=${signed_url%%\?*}
    query=${signed_url#*\?}
    policy_raw=$(query_value "$query" CloudFront-Policy) \
        || fail "the stream URL has no CloudFront-Policy"
    signature_raw=$(query_value "$query" CloudFront-Signature) \
        || fail "the stream URL has no CloudFront-Signature"
    key_pair_id_raw=$(query_value "$query" CloudFront-Key-Pair-Id) \
        || fail "the stream URL has no CloudFront-Key-Pair-Id"

    policy=$(decode_cloudfront_value "$policy_raw")
    signature=$(decode_cloudfront_value "$signature_raw")
    key_pair_id=$(decode_cloudfront_value "$key_pair_id_raw")
    cookie_header="Cookie: CloudFront-Policy=$policy; CloudFront-Signature=$signature; CloudFront-Key-Pair-Id=$key_pair_id"

    # Keep stdout media-only. ErsatzRS forwards it as video/mp2t.
    if [ -n "$fragment_duration" ]; then
        "$ffmpeg_bin" \
            -nostdin -hide_banner -loglevel error \
            -ss "$seek_position" -headers "$cookie_header" -i "$base_url" \
            -t "$fragment_duration" -map 0:v:0? -map 0:a:0? \
            -c copy -f mpegts pipe:1 \
            || fail "FFmpeg could not stream the signed HLS fragment"
    else
        "$ffmpeg_bin" \
            -nostdin -hide_banner -loglevel error \
            -ss "$seek_position" -headers "$cookie_header" -i "$base_url" \
            -map 0:v:0? -map 0:a:0? -c copy -f mpegts pipe:1 \
            || fail "FFmpeg could not stream the signed HLS source"
    fi
done <"$streams_file"
