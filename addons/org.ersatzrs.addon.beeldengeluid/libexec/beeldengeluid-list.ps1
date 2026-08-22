$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'beeldengeluid-json.ps1')

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
    & $env:CURL_BIN --fail --silent --show-error --location --max-redirs 5 --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 45 --output $output $url
    if ($LASTEXITCODE -ne 0) { throw $failure }
}

try {
    $uri = [Uri]$env:PLAYLIST_URL
    $isSeries = $uri.AbsolutePath -match '^/(serie|programma)/\d+/[^/]+/?$'
    $isVideo = $uri.AbsolutePath -match '^/serie/\d+/[^/]+/aflevering/\d+/?$'
    $isSharedList = $uri.AbsolutePath -match
        '^/lijst/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/?$'
    $isSearch = $uri.AbsolutePath -eq '/zoeken' -or $uri.AbsolutePath.StartsWith('/zoeken/')
    if (
        $uri.Scheme -notin @('http', 'https') -or
        $uri.Host -ne 'schatkamer.beeldengeluid.nl' -or
        (-not $isSeries -and -not $isVideo -and -not $isSharedList -and -not $isSearch)
    ) {
        throw 'unsupported playlist URL'
    }

    $base = $uri.GetLeftPart([UriPartial]::Path).TrimEnd('/')
    $mediaListMode = $env:BEELDENGELUID_OUTPUT -eq 'media-list'
    $mediaListRows = [Collections.Generic.List[string]]::new()
    $sharedListName = ''
    $listDescription = 'Programmes selected by the supplied Schatkamer link.'
    $listImage = $null
    $work = Join-Path $env:TEMP ('ersatzrs-beeldengeluid-list-' + [Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($work) | Out-Null
    try {
        $pageFile = Join-Path $work 'page.html'
        $episodeFile = Join-Path $work 'episode.html'
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $paths = [Collections.Generic.List[string]]::new()
        $availabilityByPath = @{}

        if ($isVideo) {
            $paths.Add($uri.AbsolutePath.TrimEnd('/'))
            $availabilityByPath[$uri.AbsolutePath.TrimEnd('/')] = 'available'
        } elseif ($isSeries -or $isSearch) {
            for ($page = 1; ; $page++) {
                $pageUrl = if ($isSearch) {
                    $uri.GetLeftPart([UriPartial]::Path) + $uri.Query + '&pagina=' + $page
                } else {
                    $base + '?pagina=' + $page
                }
                Invoke-CurlToFile $pageUrl $pageFile 'programme-list page request failed'
                $html = [IO.File]::ReadAllText($pageFile)
                if ($page -eq 1 -and $isSeries) {
                    foreach ($script in [regex]::Matches(
                        $html,
                        '<script[^>]+type=\x22application/ld[+]json\x22[^>]*>(.*?)</script>',
                        'Singleline'
                    )) {
                        try { $metadata = $script.Groups[1].Value | ConvertFrom-Json } catch { continue }
                        if ($metadata.'@type' -eq 'CreativeWorkSeries') {
                            if ($metadata.name) { $sharedListName = [string]$metadata.name }
                            if ($metadata.description) { $listDescription = [string]$metadata.description }
                            if ($metadata.image) { $listImage = [string]$metadata.image }
                            break
                        }
                    }
                }
                $added = 0
                foreach ($match in [regex]::Matches(
                    $html,
                    'href=\x22(/serie/\d+/[^\x22/]+/aflevering/\d+)\x22'
                )) {
                    $path = $match.Groups[1].Value
                    if ($seen.Add($path)) {
                        $paths.Add($path)
                        $availabilityByPath[$path] = 'available'
                        $added++
                    }
                }
                [Console]::Error.WriteLine(
                    ('beeldengeluid.bat: result page {0} yielded {1} new episode(s)' -f $page, $added)
                )
                if ($added -eq 0) { break }
            }
        } else {
            $skipped = 0
            $pattern = '\\\x22url\\\x22:\\\x22' +
                '(https://schatkamer[.]beeldengeluid[.]nl/serie/\d+/[^\\\x22/]+/aflevering/\d+)' +
                '\\\x22.*?\\\x22isPlayable\\\x22:(true|false)'
            for ($page = 1; ; $page++) {
                Invoke-CurlToFile ($base + '?pagina=' + $page) $pageFile 'shared-list page request failed'
                $html = [IO.File]::ReadAllText($pageFile)
                if ($page -eq 1) {
                    if (-not [regex]::IsMatch(
                        $html,
                        '\\\x22description\\\x22:\\\x22Gedeelde lijst\\\x22'
                    )) { throw 'shared list is unavailable or private' }
                    $nameMatch = [regex]::Match(
                        $html,
                        '\\\x22title\\\x22:\\\x22([^\\\x22]*)\\\x22,\\\x22description\\\x22:\\\x22Gedeelde lijst\\\x22'
                    )
                    if ($nameMatch.Success) {
                        $sharedListName = $nameMatch.Groups[1].Value.
                            Replace('\u0026', '&').Replace('\u003c', '<').
                            Replace('\u003e', '>').Replace('\u0027', "'").Replace('\/', '/')
                    }
                }
                $added = 0
                foreach ($match in [regex]::Matches($html, $pattern, 'Singleline')) {
                    $path = ([Uri]$match.Groups[1].Value).AbsolutePath
                    if (-not $seen.Add($path)) { continue }
                    $paths.Add($path)
                    $added++
                    if ($match.Groups[2].Value -eq 'true') {
                        $availabilityByPath[$path] = 'available'
                    } else {
                        $availabilityByPath[$path] = 'unavailable'
                        $skipped++
                    }
                }
                [Console]::Error.WriteLine(
                    ('beeldengeluid.bat: shared-list page {0} yielded {1} new item(s)' -f $page, $added)
                )
                if ($added -eq 0) { break }
            }
            if ($skipped -gt 0) {
                [Console]::Error.WriteLine(
                    'beeldengeluid.bat: retained {0} unavailable Schatkamer shared-list item(s)' -f $skipped
                )
            }
        }

        if ($paths.Count -eq 0) { throw 'playlist has no episodes' }
        if ($mediaListMode) {
            $listName = if ($sharedListName) {
                $sharedListName
            } else {
                'Beeld & Geluid Schatkamer'
            }
            $listArtwork = @()
            if ($listImage) {
                $listArtwork = @([ordered]@{ role = 'poster'; url = $listImage })
            }
            $listRecord = [ordered]@{
                record_type = 'list'
                provider_id = $uri.AbsolutePath.Trim('/') + $uri.Query
                name = $listName
                description = $listDescription
                metadata = [ordered]@{
                    title = $listName
                    plot = $listDescription
                    artwork = $listArtwork
                    guids = @('beeldengeluid-list://' + $uri.AbsolutePath.Trim('/'))
                }
            }
            $mediaListRows.Add(($listRecord | ConvertTo-Json -Depth 5 -Compress))
        }
        $rank = 0
        foreach ($path in $paths) {
            $episodeUrl = 'https://schatkamer.beeldengeluid.nl' + $path
            $episodeId = $path.Substring($path.LastIndexOf('/') + 1)
            $availability = if ($availabilityByPath.ContainsKey($path)) {
                $availabilityByPath[$path]
            } else { 'available' }
            try {
                Invoke-CurlToFile $episodeUrl $episodeFile 'episode metadata request failed'
            } catch {
                if ($availability -ne 'unavailable') { throw }
                $segments = $path.Trim('/').Split('/')
                $slug = if ($segments.Count -ge 3) {
                    [Uri]::UnescapeDataString($segments[$segments.Count - 3]).Replace('-', ' ').Replace('_', ' ')
                } else { '' }
                $title = if ($slug) { $slug } else { $episodeId }
                if ($mediaListMode) {
                    $item = [ordered]@{
                        record_type = 'item'
                        provider_id = 'episode:' + $episodeId
                        rank = $rank
                        display_title = $title
                        title = $title
                        kind = 'remote_stream'
                        guids = @('beeldengeluid://' + $episodeId)
                        source_url = $episodeUrl
                        availability = 'unavailable'
                        availability_reason = 'not_playable'
                        content_kind = 'auto'
                        metadata = [ordered]@{
                            title = $title
                            guids = @('beeldengeluid://' + $episodeId)
                        }
                    }
                    $mediaListRows.Add(($item | ConvertTo-Json -Depth 2 -Compress))
                    $rank++
                } else {
                    [ordered]@{
                        id = $episodeId
                        provider_id = 'episode:' + $episodeId
                        url = $episodeUrl
                        title = $title
                        availability = 'unavailable'
                        availability_reason = 'not_playable'
                        content_kind = 'auto'
                        guids = @('beeldengeluid://' + $episodeId)
                        is_live = $false
                    } | ConvertTo-Json -Depth 2 -Compress
                }
                continue
            }
            $html = [IO.File]::ReadAllText($episodeFile)
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
            $imageMatch = [regex]::Match(
                $html.Replace('\"', '"'),
                '"image":"(https://schatkamer[.]beeldengeluid[.]nl/[^"]+)"'
            )
            $episodeImage = if ($imageMatch.Success) { $imageMatch.Groups[1].Value } else { $listImage }
            $publishedMatches = [regex]::Matches(
                $programHtml,
                '\\\x22publishedAtISO\\\x22:\\\x22([^\\\x22]+)'
            )
            $published = if ($publishedMatches.Count) {
                $publishedMatches[$publishedMatches.Count - 1].Groups[1].Value
            } else { $null }
            $releaseDate = if ($published -match '^([0-9]{4}-[0-9]{2}-[0-9]{2})(?:T.*)?$') {
                $Matches[1]
            } else { $null }
            $descriptionRaw = JsonSlice $programHtml 'description' 'disclaimer'
            $plot = $null
            if ($descriptionRaw) {
                $plot = [string](ConvertFrom-EscapedJsonValue $descriptionRaw)
                $plot = [Net.WebUtility]::HtmlDecode(
                    $plot.Replace("`r", ' ').Replace("`n", ' ').Replace("`t", ' ')
                )
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

            $genres = @(JsonArrayValues $programHtml 'genres' 'subjects')
            $subjects = @(JsonArrayValues $programHtml 'subjects' 'collection')
            $classificationText = (($genres + $subjects) -join ' ').ToLowerInvariant()
            $contentKind = if ($classificationText -match 'reclame|commercial|advertentie') {
                'other_video'
            } elseif ($classificationText -match 'muziek|music|concert|videoclip|music video') {
                'music_video'
            } elseif ($classificationText -match 'speelfilm|film|movie') {
                'movie'
            } elseif ($series) {
                'television_episode'
            } else {
                'other_video'
            }

            $row = [ordered]@{
                id = $episodeId
                provider_id = 'episode:' + $episodeId
                url = $episodeUrl
                title = $title
                availability = $availability
                content_kind = $contentKind
                guids = @('beeldengeluid://' + $episodeId)
            }
            if ($availability -eq 'unavailable') { $row.availability_reason = 'not_playable' }
            if ($series) { $row.show_title = $series }
            if ($duration.Success) { $row.duration_seconds = [int64]$duration.Groups[1].Value }
            if ($episodeImage) {
                $row.thumbnail_url = $episodeImage
                $row.additional_image_urls = @($episodeImage)
            }
            if ($plot) { $row.plot = $plot }
            if ($releaseDate) {
                $row.release_date = $releaseDate
                $row.year = [int]$releaseDate.Substring(0, 4)
            }
            if ($rating) { $row.content_rating = $rating }
            $row.genres = $genres
            $row.tags = $subjects
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
            $contentRatings = @()
            if ($rating) { $contentRatings = @($rating) }
            $episodeArtwork = @()
            if ($episodeImage) {
                $episodeArtwork = @([ordered]@{ role = 'thumb'; url = $episodeImage })
            }
            $row.is_live = $false
            if ($mediaListMode) {
                $item = [ordered]@{
                    record_type = 'item'
                    provider_id = 'episode:' + $episodeId
                    rank = $rank
                    display_title = $title
                    title = $title
                    kind = 'remote_stream'
                    guids = @('beeldengeluid://' + $episodeId)
                    source_url = $episodeUrl
                    availability = $availability
                    content_kind = $contentKind
                }
                if ($availability -eq 'unavailable') { $item.availability_reason = 'not_playable' }
                if ($releaseDate) { $item.year = [int]$releaseDate.Substring(0, 4) }
                if ($duration.Success) { $item.duration_seconds = [int64]$duration.Groups[1].Value }
                if ($episodeImage) { $item.additional_image_urls = @($episodeImage) }
                $item.metadata = [ordered]@{
                    title = $title
                    plot = $plot
                    show_title = if ($series) { $series } else { $null }
                    year = if ($releaseDate) { [int]$releaseDate.Substring(0, 4) } else { $null }
                    release_date = $releaseDate
                    content_ratings = $contentRatings
                    genres = $genres
                    tags = $subjects
                    people = $people
                    producers = $producers
                    original_broadcasters = $originalBroadcasters
                    broadcasters = $broadcasters
                    collection = if ($collectionMatch.Success) {
                        [Net.WebUtility]::HtmlDecode($collectionMatch.Groups[1].Value)
                    } else { $null }
                    artwork = $episodeArtwork
                    guids = @('beeldengeluid://' + $episodeId)
                }
                $mediaListRows.Add(($item | ConvertTo-Json -Depth 6 -Compress))
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
    [Console]::Error.WriteLine(
        'beeldengeluid.bat: playlist enumeration failed: ' + $_.Exception.Message
    )
    exit 1
}
