# Native Windows Remote Stream listing fixture; never contacts a provider.
param([string]$Package = (Join-Path $PSScriptRoot '../addons/org.ersatzrs.addon.yt-dlp'))
$ErrorActionPreference = 'Stop'
$stage = Join-Path $env:TEMP ('ersatzrs-playlist-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    $candidate = Join-Path $stage 'youtube-list.ps1'
    Copy-Item -LiteralPath (Join-Path $Package 'libexec/youtube-list.ps1') -Destination $candidate
    $fake = Join-Path $stage 'fixture.exe'
    Add-Type -OutputAssembly $fake -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.IO;
public class PlaylistFixture {
    public static int Main(string[] args) {
        Console.Write(File.ReadAllText(Environment.GetEnvironmentVariable("PLAYLIST_FIXTURE_DATA")));
        return 0;
    }
}
'@
    $env:YT_DLP_BIN = $fake
    $env:YT_DLP_CACHE_DIR = Join-Path $stage 'cache'
    $env:PLAYLIST_URL = 'https://www.youtube.com/playlist?list=fixture'
    $env:MEDIA_LIST_MODE = '0'
    $env:PLAYLIST_FIXTURE_DATA = Join-Path $stage 'data.json'
    $entries = @(
        @{id='named';url='https://media.example.test/named';title='Named video';availability='public';duration=60},
        @{id='missing';url='https://media.example.test/missing';availability='unknown'},
        @{id='null';url='https://media.example.test/null';title=$null;availability='private'},
        @{id='blank';url='https://media.example.test/blank';title='  ';availability='unlisted';duration=120}
    )
    [IO.File]::WriteAllText($env:PLAYLIST_FIXTURE_DATA, (@{entries=$entries}|ConvertTo-Json -Depth 4 -Compress))
    $lines = @(& $candidate)
    if ($LASTEXITCODE -ne 0) { throw 'listing failed' }
    $rows = @($lines | ForEach-Object { $_ | ConvertFrom-Json })
    if ($rows.Count -ne 4) { throw 'listing dropped an addressable entry' }
    if (($rows.id -join ',') -ne 'named,missing,null,blank') { throw 'identity/order changed' }
    if ($rows[0].title -ne 'Named video') { throw 'known title changed' }
    foreach ($index in @(1,2,3)) {
        if ($rows[$index].title -ne ('Untitled video (' + $entries[$index].id + ')')) { throw 'missing fallback title' }
    }
    if (($rows.availability -join ',') -ne 'available,unknown,unavailable,available') { throw 'availability changed' }
    if ($rows[2].availability_reason -ne 'not_playable') { throw 'restriction lost' }
    if ($rows[0].duration_seconds -ne 60 -or $rows[3].duration_seconds -ne 120) { throw 'duration changed' }
    if ($rows[1].PSObject.Properties.Name -contains 'duration_seconds') { throw 'unknown duration invented' }
    if (($rows.liveness -join ',') -ne 'finite,unknown,unknown,finite') { throw 'liveness changed' }
    Write-Output 'PASS: native Windows listing retains named/missing/null/blank titles, order, identities, availability, restrictions, durations and liveness.'
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
