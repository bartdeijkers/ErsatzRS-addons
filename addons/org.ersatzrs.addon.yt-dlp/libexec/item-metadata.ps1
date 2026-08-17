$ErrorActionPreference = 'Stop'

function Chapter-Time([long]$seconds) {
    $hours = [Math]::Floor($seconds / 3600)
    $minutes = [Math]::Floor(($seconds % 3600) / 60)
    $remainder = $seconds % 60
    if ($hours -gt 0) { return ('{0}:{1:D2}:{2:D2}' -f $hours, $minutes, $remainder) }
    return ('{0}:{1:D2}' -f $minutes, $remainder)
}

foreach ($itemId in @($env:ERSATZRS_REMOTE_STREAM_ITEM_IDS -split "`r?`n")) {
    if (-not $itemId -or $itemId -match '["\\]' -or $itemId.StartsWith('-')) { continue }
    $json = & $env:YT_DLP_BIN --no-config --no-update --quiet --no-playlist --skip-download --dump-single-json ('https://www.youtube.com/watch?v=' + $itemId)
    if ($LASTEXITCODE -ne 0) { continue }
    $item = $json | ConvertFrom-Json
    $availability = switch ([string]$item.availability) {
        { $_ -in @('public', 'unlisted') } { 'available'; break }
        { $_ -in @('private', 'premium_only', 'subscriber_only', 'needs_auth') } { 'unavailable'; break }
        default { 'unknown' }
    }
    $rawDate = if ($item.upload_date) { [string]$item.upload_date } elseif ($item.release_date) { [string]$item.release_date } else { $null }
    $releaseDate = if ($rawDate -match '^\d{8}$') { $rawDate.Substring(0, 4) + '-' + $rawDate.Substring(4, 2) + '-' + $rawDate.Substring(6, 2) } else { $rawDate }
    $row = [ordered]@{
        provider_id = [string]$item.id
        plot = if ($item.description) { [string]$item.description } else { $null }
        release_date = $releaseDate
        year = if ($item.release_year) { [int]$item.release_year } elseif ($rawDate) { [int]$rawDate.Substring(0, 4) } else { $null }
        genres = @($item.categories | Where-Object { $null -ne $_ })
        tags = @($item.tags | Where-Object { $null -ne $_ })
        thumbnail_url = if ($item.thumbnail) { [string]$item.thumbnail } else { $null }
        availability = $availability
        availability_reason = if ($availability -eq 'unavailable') { 'not_playable' } else { $null }
    }
    $lines = @()
    $lastStart = -1
    foreach ($chapter in @($item.chapters)) {
        if ($null -eq $chapter.start_time -or -not ([string]$chapter.title).Trim()) { continue }
        $start = [long][Math]::Round([double]$chapter.start_time, [MidpointRounding]::AwayFromZero)
        if ($start -le $lastStart) { continue }
        $lines += ((Chapter-Time $start) + ' ' + ([string]$chapter.title).Trim())
        $lastStart = $start
    }
    if ($lines.Count -gt 0) { $row.chapter_input = $lines -join "`n" }
    $row | ConvertTo-Json -Depth 4 -Compress
}
