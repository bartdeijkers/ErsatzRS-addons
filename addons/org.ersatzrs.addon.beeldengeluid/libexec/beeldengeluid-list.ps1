$ErrorActionPreference = 'Stop'

function JsonSlice([string]$html, [string]$start, [string]$end) {
    $pattern = '\\' + [char]34 + [regex]::Escape($start) + '\\' + [char]34 +
        ':(.*?),\\' + [char]34 + [regex]::Escape($end) + '\\' + [char]34 + ':'
    $matches = [regex]::Matches($html, $pattern, 'Singleline')
    if (-not $matches.Count) { return $null }
    return $matches[$matches.Count - 1].Groups[1].Value
}

function JsonObjectNames([string]$html, [string]$start, [string]$end) {
    $slice = JsonSlice $html $start $end
    if (-not $slice) { return @() }
    return @(
        [regex]::Matches($slice, '\\\x22name\\\x22:\\\x22([^\\\x22]*)') |
            ForEach-Object { [Net.WebUtility]::HtmlDecode($_.Groups[1].Value) } |
            Select-Object -Unique
    )
}

function JsonArrayValues([string]$html, [string]$start, [string]$end) {
    $slice = JsonSlice $html $start $end
    if (-not $slice) { return @() }
    return @(
        [regex]::Matches($slice, '\\\x22([^\\\x22]*)\\\x22') |
            ForEach-Object { [Net.WebUtility]::HtmlDecode($_.Groups[1].Value) } |
            Select-Object -Unique
    )
}

function Invoke-CurlToFile([string]$url, [string]$output, [string]$failure) {
    & $env:CURL_BIN --fail --silent --show-error --location --output $output $url
    if ($LASTEXITCODE -ne 0) { throw $failure }
}

try {
    $uri = [Uri]$env:PLAYLIST_URL
    $isSeries = $uri.AbsolutePath -match '^/serie/\d+/[^/]+/?$'
    $isSharedList = $uri.AbsolutePath -match
        '^/lijst/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/?$'
    $isSearch = $uri.AbsolutePath -eq '/zoeken' -and $uri.Query.Length -gt 1
    if (
        $uri.Scheme -notin @('http', 'https') -or
        $uri.Host -ne 'schatkamer.beeldengeluid.nl' -or
        (-not $isSeries -and -not $isSharedList -and -not $isSearch)
    ) {
        throw 'unsupported playlist URL'
    }

    $base = $uri.GetLeftPart([UriPartial]::Path).TrimEnd('/')
    $mediaListMode = $env:BEELDENGELUID_OUTPUT -eq 'media-list'
    $mediaListRows = [Collections.Generic.List[string]]::new()
    if ($mediaListMode) {
        $listRecord = [ordered]@{
            record_type = 'list'
            provider_id = $uri.AbsolutePath.Trim('/') + $uri.Query
            name = 'Beeld & Geluid Schatkamer'
            description = 'Programmes selected by the supplied Schatkamer link.'
        }
        $mediaListRows.Add(($listRecord | ConvertTo-Json -Compress))
    }
    $work = Join-Path $env:TEMP ('ersatzrs-beeldengeluid-list-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($work) | Out-Null
    try {
        $pageFile = Join-Path $work 'page.html'
        $episodeFile = Join-Path $work 'episode.html'
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $paths = [Collections.Generic.List[string]]::new()

        if ($isSeries -or $isSearch) {
            for ($page = 1; $page -le 100; $page++) {
                $pageUrl = if ($isSearch) {
                    $uri.GetLeftPart([UriPartial]::Path) + $uri.Query + '&pagina=' + $page
                } else {
                    $base + '?pagina=' + $page
                }
                Invoke-CurlToFile $pageUrl $pageFile 'programme-list page request failed'
                $html = [IO.File]::ReadAllText($pageFile)
                $added = 0
                foreach ($match in [regex]::Matches(
                    $html,
                    'href=\x22(/serie/\d+/[^\x22/]+/aflevering/\d+)\x22'
                )) {
                    $path = $match.Groups[1].Value
                    if ($seen.Add($path)) { $paths.Add($path); $added++ }
                }
                if ($added -eq 0) { break }
            }
        } else {
            Invoke-CurlToFile $base $pageFile 'shared-list page request failed'
            $html = [IO.File]::ReadAllText($pageFile)
            if (-not [regex]::IsMatch(
                $html,
                '\\\x22description\\\x22:\\\x22Gedeelde lijst\\\x22'
            )) {
                throw 'shared list is unavailable or private'
            }
            $skipped = 0
            $pattern = '\\\x22url\\\x22:\\\x22' +
                '(https://schatkamer[.]beeldengeluid[.]nl/serie/\d+/[^\\\x22/]+/aflevering/\d+)' +
                '\\\x22.*?\\\x22isPlayable\\\x22:(true|false)'
            foreach ($match in [regex]::Matches($html, $pattern, 'Singleline')) {
                $path = ([Uri]$match.Groups[1].Value).AbsolutePath
                if (-not $seen.Add($path)) { continue }
                if ($match.Groups[2].Value -eq 'true') { $paths.Add($path) } else { $skipped++ }
            }
            if ($skipped -gt 0) {
                [Console]::Error.WriteLine(
                    'beeldengeluid.bat: skipped {0} unavailable Schatkamer shared-list item(s)' -f $skipped
                )
            }
        }

        if ($paths.Count -eq 0) { throw 'playlist has no playable episodes' }
        $rank = 0
        foreach ($path in $paths) {
            $episodeUrl = 'https://schatkamer.beeldengeluid.nl' + $path
            Invoke-CurlToFile $episodeUrl $episodeFile 'episode metadata request failed'
            $html = [IO.File]::ReadAllText($episodeFile)
            $episodeId = $path.Substring($path.LastIndexOf('/') + 1)
            $programMarker = '\' + [char]34 + 'program\' + [char]34 +
                ':{\' + [char]34 + 'id\' + [char]34 + ':\' + [char]34 +
                $episodeId + '\' + [char]34
            $programStart = $html.IndexOf($programMarker, [StringComparison]::Ordinal)
            if ($programStart -lt 0) { throw 'episode program metadata was not found' }
            $programHtml = $html.Substring($programStart)
            $series = [regex]::Match($html, '<h1[^>]*>([^<]*)').Groups[1].Value
            $title = [regex]::Match($html, '<h3[^>]*>([^<]*)').Groups[1].Value
            if (-not $title) { $title = $path.Substring($path.LastIndexOf('/') + 1) }
            $series = [Net.WebUtility]::HtmlDecode($series)
            $title = [Net.WebUtility]::HtmlDecode($title)
            if ($series) { $title = $series + ' - ' + $title }

            $duration = [regex]::Match($programHtml, '\\\x22durationNumber\\\x22:(\d+)')
            $publishedMatches = [regex]::Matches(
                $programHtml,
                '\\\x22publishedAtISO\\\x22:\\\x22([^\\\x22]+)'
            )
            $published = if ($publishedMatches.Count) {
                $publishedMatches[$publishedMatches.Count - 1].Groups[1].Value
            } else { $null }
            $descriptionRaw = JsonSlice $programHtml 'description' 'disclaimer'
            $plot = $null
            if ($descriptionRaw -and $descriptionRaw.Length -ge 4) {
                $jsonDescription = $descriptionRaw.Remove($descriptionRaw.Length - 2, 1).Remove(0, 1)
                $plot = $jsonDescription.Replace('\\', '\') | ConvertFrom-Json
                $plot = $plot.Replace("`r", ' ').Replace("`n", ' ').Replace("`t", ' ')
            }
            $ageMatches = [regex]::Matches(
                $programHtml,
                '\\\x22ageRating\\\x22:\\\x22([^\\\x22]*)'
            )
            $age = if ($ageMatches.Count) {
                [Net.WebUtility]::HtmlDecode($ageMatches[$ageMatches.Count - 1].Groups[1].Value)
            } else { $null }
            $rating = switch -Regex ($age) {
                '^Leeftijdsadvies onbekend$' { 'nl:unknown'; break }
                '^Alle leeftijden$' { 'nl:AL'; break }
                'onder de (\d+) jaar' { 'nl:' + $Matches[1]; break }
                default { $age }
            }
            $collectionMatch = [regex]::Match(
                $html,
                'href=\x22/zoeken[?]collectie=[^\x22]*\x22[^>]*>([^<]*)'
            )

            $row = [ordered]@{
                id = $episodeId
                url = $episodeUrl
                title = $title
            }
            if ($duration.Success) { $row.duration_seconds = [int64]$duration.Groups[1].Value }
            if ($plot) { $row.plot = $plot }
            if ($published) {
                $row.release_date = $published
                $row.year = [int]$published.Substring(0, 4)
            }
            if ($rating) { $row.content_rating = $rating }
            $row.genres = @(JsonArrayValues $programHtml 'genres' 'subjects')
            $row.tags = @(JsonArrayValues $programHtml 'subjects' 'collection')
            if ($collectionMatch.Success) {
                $row.collection = [Net.WebUtility]::HtmlDecode($collectionMatch.Groups[1].Value)
            }

            $people = @()
            foreach ($triple in @(
                @('presenter', 'presenters', 'actors'),
                @('actor', 'actors', 'guests'),
                @('guest', 'guests', 'directors'),
                @('director', 'directors', 'performers'),
                @('performer', 'performers', 'others'),
                @('person', 'others', 'productionCompanies')
            )) {
                foreach ($person in @(JsonObjectNames $programHtml $triple[1] $triple[2])) {
                    $people += [ordered]@{ name = $person; role = $triple[0] }
                }
            }
            if ($people.Count) { $row.people = $people }
            $producers = @(JsonArrayValues $programHtml 'productionCompanies' 'genres')
            if ($producers.Count) { $row.producers = $producers }
            $originalBroadcasters = @(
                JsonObjectNames $programHtml 'originalBroadcasters' 'broadcaster'
            )
            if ($originalBroadcasters.Count) { $row.original_broadcasters = $originalBroadcasters }
            $broadcasters = @(JsonObjectNames $programHtml 'broadcasters' 'url')
            if ($broadcasters.Count) { $row.broadcasters = $broadcasters }
            $row.is_live = $false
            if ($mediaListMode) {
                $item = [ordered]@{
                    record_type = 'item'
                    provider_id = 'episode:' + $episodeId
                    rank = $rank
                    display_title = $title
                    title = $title
                    kind = 'remote_stream'
                    guids = @()
                    source_url = $episodeUrl
                }
                if ($published) { $item.year = [int]$published.Substring(0, 4) }
                $mediaListRows.Add(($item | ConvertTo-Json -Depth 2 -Compress))
                $rank++
            } else {
                [Console]::Out.WriteLine(($row | ConvertTo-Json -Depth 4 -Compress))
            }
        }
        if ($mediaListMode) {
            foreach ($record in $mediaListRows) {
                [Console]::Out.WriteLine($record)
            }
        }
    } finally {
        if (Test-Path -LiteralPath $work) {
            Remove-Item -LiteralPath $work -Recurse -Force
        }
    }
} catch {
    [Console]::Error.WriteLine('beeldengeluid.bat: playlist enumeration failed')
    exit 1
}
