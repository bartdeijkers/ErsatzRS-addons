$ErrorActionPreference = 'Stop'

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
            [ordered]@{
                record_type = 'item'
                provider_id = [string]$entry.id
                rank = $rank
                display_title = [string]$entry.title
                title = [string]$entry.title
                kind = 'remote_stream'
                guids = @()
                source_url = $url
            } | ConvertTo-Json -Depth 2 -Compress
            $rank++
        }
    } else {
        foreach ($entry in $entries) {
            $url = if ($entry.webpage_url) { [string]$entry.webpage_url } elseif ($entry.url) { [string]$entry.url } else { continue }
            $row = [ordered]@{
                id = [string]$entry.id
                url = $url
                title = [string]$entry.title
                is_live = $false
            }
            if ($null -ne $entry.duration) { $row.duration_seconds = [uint64]$entry.duration }
            $row | ConvertTo-Json -Compress
        }
    }
} catch {
    [Console]::Error.WriteLine('youtube-list.ps1: ' + $_.Exception.Message)
    exit 1
}
