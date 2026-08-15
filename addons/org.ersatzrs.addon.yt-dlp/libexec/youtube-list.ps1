$ErrorActionPreference = 'Stop'

function Availability([object]$entry) {
    switch ([string]$entry.availability) {
        { $_ -in @('public', 'unlisted') } { return 'available' }
        { $_ -in @('private', 'premium_only', 'subscriber_only', 'needs_auth') } { return 'unavailable' }
        default { return 'unknown' }
    }
}

function ContentKind([object]$entry) {
    $text = (@($entry.categories) + @($entry.tags) + @([string]$entry.title) -join ' ').ToLowerInvariant()
    if ($text -match 'advertisement|commercial|reclame') { return 'other_video' }
    if ($text -match 'music video|videoclip|concert|music|muziek') { return 'music_video' }
    if ($text -match 'movie|film|speelfilm') { return 'movie' }
    if ($entry.episode -or $entry.series -or $entry.season_number) { return 'television_episode' }
    return 'auto'
}

function AvailabilityReason([object]$entry) {
    if ([string]$entry.availability -in @(
        'private', 'premium_only', 'subscriber_only', 'needs_auth'
    )) { return 'not_playable' }
    return $null
}

try {
    $uri = [Uri]$env:PLAYLIST_URL
    if ($uri.Scheme -notin @('http', 'https')) { throw 'playlist URL must use HTTP or HTTPS' }
    $json = & $env:YT_DLP_BIN --no-config --no-update --quiet --flat-playlist --dump-single-json $env:PLAYLIST_URL
    if ($LASTEXITCODE -ne 0) { throw 'yt-dlp could not enumerate the playlist' }
    $playlist = $json | ConvertFrom-Json
    $entries = @($playlist.entries)
    if ($env:MEDIA_LIST_MODE -eq '1') {
        [ordered]@{
            record_type = 'list'
            provider_id = $env:PLAYLIST_URL
            name = if ($playlist.title) { [string]$playlist.title } else { 'yt-dlp playlist' }
            description = 'Remote videos selected by the supplied playlist link.'
        } | ConvertTo-Json -Compress
        $rank = 0
        foreach ($entry in $entries) {
            $url = if ($entry.webpage_url) { [string]$entry.webpage_url } elseif ($entry.url) { [string]$entry.url } else { continue }
            $row = [ordered]@{
                record_type = 'item'
                provider_id = [string]$entry.id
                rank = $rank
                display_title = [string]$entry.title
                title = [string]$entry.title
                kind = 'remote_stream'
                guids = @('yt-dlp://' + [string]$entry.id)
                source_url = $url
                availability = Availability $entry
                content_kind = ContentKind $entry
            }
            $reason = AvailabilityReason $entry
            if ($reason) { $row.availability_reason = $reason }
            $row | ConvertTo-Json -Depth 2 -Compress
            $rank++
        }
    } else {
        foreach ($entry in $entries) {
            $url = if ($entry.webpage_url) { [string]$entry.webpage_url } elseif ($entry.url) { [string]$entry.url } else { continue }
            $genres = @($entry.categories | Where-Object { $null -ne $_ })
            $tags = @($entry.tags | Where-Object { $null -ne $_ })
            $row = [ordered]@{
                id = [string]$entry.id
                provider_id = [string]$entry.id
                url = $url
                title = [string]$entry.title
                plot = if ($entry.description) { [string]$entry.description } else { $null }
                genres = $genres
                tags = $tags
                thumbnail_url = if ($entry.thumbnail) { [string]$entry.thumbnail } else { $null }
                availability = Availability $entry
                content_kind = ContentKind $entry
                guids = @('yt-dlp://' + [string]$entry.id)
                is_live = $false
            }
            $reason = AvailabilityReason $entry
            if ($reason) { $row.availability_reason = $reason }
            if ($null -ne $entry.duration) { $row.duration_seconds = [uint64]$entry.duration }
            $row | ConvertTo-Json -Compress
        }
    }
} catch {
    [Console]::Error.WriteLine('youtube-list.ps1: ' + $_.Exception.Message)
    exit 1
}
