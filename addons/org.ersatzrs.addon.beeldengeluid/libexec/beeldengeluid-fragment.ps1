$ErrorActionPreference = 'Stop'

try {
    $uri = [Uri]$env:EPISODE_URL
    $pageUri = $uri.GetLeftPart([UriPartial]::Path)
    $parameters = @{}
    foreach ($part in $uri.Query.TrimStart('?').Split('&', [StringSplitOptions]::RemoveEmptyEntries)) {
        $pair = $part.Split('=', 2)
        $parameters[[Uri]::UnescapeDataString($pair[0])] = if ($pair.Count -eq 2) {
            [Uri]::UnescapeDataString($pair[1])
        } else { '' }
    }
    $seek = $env:SEEK_POSITION
    $seekSeconds = if ($seek -eq '0') {
        0.0
    } else {
        $parts = $seek.Split(':')
        ([uint64]$parts[0] * 3600) + ([uint64]$parts[1] * 60) +
            [double]::Parse($parts[2], [Globalization.CultureInfo]::InvariantCulture)
    }
    $duration = ''
    if ($parameters.ContainsKey('start')) {
        [uint64]$start = 0
        if (-not [uint64]::TryParse($parameters.start, [ref]$start)) {
            throw 'fragment start must be whole seconds'
        }
        $seekSeconds += $start
        if ($parameters.ContainsKey('end')) {
            [uint64]$end = 0
            if (-not [uint64]::TryParse($parameters.end, [ref]$end) -or $end -le $start) {
                throw 'fragment end must be after fragment start'
            }
            $duration = $end - $start - ($seekSeconds - $start)
            if ($duration -le 0) { throw 'seek position is outside the fragment' }
        }
    } elseif ($parameters.ContainsKey('end')) {
        throw 'fragment end requires fragment start'
    }
    'EPISODE_PAGE_URL=' + $pageUri
    'SEEK_POSITION=' + $seekSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
    'FRAGMENT_DURATION=' + $duration
} catch {
    [Console]::Error.WriteLine('beeldengeluid.bat: invalid fragment parameters: ' + $_.Exception.Message)
    exit 64
}
