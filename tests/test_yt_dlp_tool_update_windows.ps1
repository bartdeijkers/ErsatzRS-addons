param([string]$Package = (Join-Path $PSScriptRoot '..\addons\org.ersatzrs.addon.yt-dlp'))
$ErrorActionPreference = 'Stop'
$stage = Join-Path $env:TEMP ('ersatzrs-tool-update-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    # Imported package paths can be UNC paths. Run this fixture from the local
    # temporary stage so Deno receives unambiguous file URLs for module imports.
    $candidate = Join-Path $stage 'candidate'
    Copy-Item -Recurse -LiteralPath (Resolve-Path -LiteralPath $Package).Path -Destination $candidate
    $fake = Join-Path $stage 'fixture.exe'
    Add-Type -OutputAssembly $fake -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.IO;
public class ToolUpdateFixture {
    public static int Main(string[] args) {
        File.AppendAllText(Environment.GetEnvironmentVariable("UPDATE_CALLS"), String.Join("|", args) + "\n");
        string mode = Environment.GetEnvironmentVariable("UPDATE_MODE");
        string state = Environment.GetEnvironmentVariable("UPDATE_STATE");
        if (Array.IndexOf(args, "--version") >= 0) {
            if (mode == "malformed" || (mode == "after-malformed" && File.Exists(state))) {
                Console.WriteLine("SYNTHETIC_PRIVATE_DIAGNOSTIC");
            } else {
                Console.WriteLine(File.Exists(state) ? "2026.09.08" : "2026.09.01");
            }
            return 0;
        }
        if (Array.IndexOf(args, "-U") < 0) return 90;
        string release = Environment.GetEnvironmentVariable("UPDATE_RELEASE");
        if (!String.IsNullOrEmpty(release)) Console.WriteLine(release);
        if (mode == "timeout") System.Threading.Thread.Sleep(60000);
        if (mode == "manual") {
            Console.Error.WriteLine("ERROR: You installed yt-dlp from a manual build or with a package manager; Use that to update");
            return 100;
        }
        if (mode == "readonly") {
            Console.Error.WriteLine("ERROR: Insufficient permissions to write to SYNTHETIC_PRIVATE_PATH");
            return 100;
        }
        if (mode == "network") {
            Console.Error.WriteLine("ERROR: Unable to obtain version info: SYNTHETIC_PRIVATE_DIAGNOSTIC");
            return 100;
        }
        if (mode == "unknown") {
            Console.Error.WriteLine("ERROR: network text mentions package manager and permissions");
            return 100;
        }
        if (mode == "limit") Console.Write(new string('x', 17000));
        if (mode == "updated" || mode == "after-malformed") File.WriteAllText(state, "updated");
        return 0;
    }
}
'@
    $env:ERSATZRS_ADDON_SETTING_YT_DLP_BIN = $fake
    $env:YT_DLP_BIN = $fake
    $env:UPDATE_CALLS = Join-Path $stage 'calls.txt'
    $env:UPDATE_STATE = Join-Path $stage 'state.txt'
    $entrypoint = Join-Path $candidate 'addon.bat'
    $request = '{"schema":"tool.update.v1","tool_key":"YT_DLP_BIN"}'
    function Invoke-Update([string]$Mode, [switch]$Deadline) {
        $env:UPDATE_MODE = $Mode
        Remove-Item -LiteralPath $env:UPDATE_STATE -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $env:UPDATE_CALLS -ErrorAction SilentlyContinue
        if ($Deadline) {
            $raw = & deno.exe run --quiet --allow-env=YT_DLP_BIN --allow-run $driver
        } else {
            $raw = $request | & $entrypoint update
        }
        if ($LASTEXITCODE -ne 0) { throw 'update entrypoint failed' }
        $json = $raw -join "\n"
        if ($json.Length -gt 2048 -or $json.Contains('SYNTHETIC_PRIVATE')) { throw 'unsafe update result' }
        $result = $json | ConvertFrom-Json
        if ($result -is [array] -or $result.schema -ne 'tool.update.v1' -or $result.tool_key -ne 'YT_DLP_BIN') {
            throw 'invalid update result envelope'
        }
        return $result
    }
    $result = Invoke-Update 'updated'
    if ($result.outcome -ne 'updated' -or $result.before_version -ne '2026.09.01' -or $result.after_version -ne '2026.09.08' -or $result.diagnostic_code) {
        throw 'updated result mismatch'
    }
    $probe = '--no-config|--no-plugin-dirs|--no-update|--version'
    $calls = [IO.File]::ReadAllLines($env:UPDATE_CALLS)
    if ($calls.Count -ne 3 -or $calls[0] -ne $probe -or $calls[1] -ne '--no-config|--no-plugin-dirs|-U' -or $calls[2] -ne $probe) {
        throw 'native arguments mismatch'
    }
    $result = Invoke-Update 'noop'
    if ($result.outcome -ne 'already_current' -or $result.before_version -ne $result.after_version) { throw 'noop mismatch' }
    foreach ($mode in @('manual', 'readonly')) {
        $result = Invoke-Update $mode
        if ($result.outcome -ne 'manual_update_required' -or $result.diagnostic_code -ne 'unsupported_installation') { throw 'manual outcome mismatch' }
    }
    foreach ($mode in @('network', 'unknown', 'limit')) {
        $result = Invoke-Update $mode
        if ($result.outcome -ne 'failed' -or $result.diagnostic_code -ne 'update_failed') { throw 'failure outcome mismatch' }
    }
    foreach ($mode in @('malformed', 'after-malformed')) {
        $result = Invoke-Update $mode
        if ($result.outcome -ne 'failed' -or $result.diagnostic_code -ne 'version_probe_failed') { throw 'version outcome mismatch' }
    }
    # Only the synthetic driver shortens the deadline; it still exercises the
    # shared boundedCommand against a real native Windows child process.
    $driver = Join-Path $stage 'deadline.ts'
    $moduleUri = [System.Uri]::new((Join-Path $candidate 'libexec\tool-update.ts'), [System.UriKind]::Absolute).AbsoluteUri | ConvertTo-Json -Compress
    $commandUri = [System.Uri]::new((Join-Path $candidate 'libexec\item-options.ts'), [System.UriKind]::Absolute).AbsoluteUri | ConvertTo-Json -Compress
    if (!$moduleUri -or !$commandUri) { throw 'fixture module URL could not be constructed' }
    $source = @'
import { updateTool } from MODULE_URI;
import { boundedCommand } from COMMAND_URI;
const run = (exe: string, args: string[], _ms?: number, cap?: number) =>
  boundedCommand(exe, args, args.includes("-U") ? 50 : 10000, cap);
console.log(JSON.stringify(await updateTool({schema:"tool.update.v1",tool_key:"YT_DLP_BIN"}, Deno.env.get("YT_DLP_BIN")!, run)));
'@
    [IO.File]::WriteAllText($driver, $source.Replace('MODULE_URI', $moduleUri).Replace('COMMAND_URI', $commandUri))
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $result = Invoke-Update 'timeout' -Deadline
    if ($result.outcome -ne 'failed' -or $result.diagnostic_code -ne 'update_failed' -or $watch.Elapsed.TotalSeconds -gt 15) {
        throw 'native deadline mismatch'
    }
    $env:ERSATZRS_ADDON_DATA_DIR = Join-Path $stage 'missing\provider data'
    $env:FFMPEG_BIN = $fake
    $env:UPDATE_RELEASE = "Current version: stable@2026.09.01 from yt-dlp/yt-dlp`nLatest version: stable@2026.09.08 from yt-dlp/yt-dlp"
    $result = Invoke-Update 'manual'
    $health = (& $entrypoint check) | ConvertFrom-Json
    if ($health.status -ne 'warning' -or $health.code -ne 'tool-update-failed-stale') { throw 'missing stale update warning' }
    if ($health.PSObject.Properties.Name -contains 'tool_update') { throw 'legacy host received extended context' }
    $env:ERSATZRS_ADDON_CHECK_CONTEXT_VERSION = '1'
    $health = (& $entrypoint check) | ConvertFrom-Json
    if ($health.tool_update.program -ne 'yt-dlp' -or $health.tool_update.installed_version -ne '2026.09.01' -or $health.tool_update.latest_version -ne '2026.09.08') { throw 'missing advertised update context' }
    $healthPath = Join-Path $env:ERSATZRS_ADDON_DATA_DIR 'tool-update-health.json'
    $saved = [IO.File]::ReadAllText($healthPath)
    if ($saved.Length -gt 1024 -or $saved.Contains($fake) -or $saved.Contains('SYNTHETIC_PRIVATE')) { throw 'unsafe saved health' }
    $calls = [IO.File]::ReadAllLines($env:UPDATE_CALLS)
    if ($calls.Count -ne 5 -or $calls[3] -ne $probe -or $calls[4] -ne $probe) { throw 'readiness must only observe local version' }
    $result = Invoke-Update 'noop'
    $health = (& $entrypoint check) | ConvertFrom-Json
    if ($health.status -ne 'ready') { throw 'success did not clear warning' }
    if ($health.PSObject.Properties.Name -contains 'tool_update') { throw 'ready health retained update context' }
    $result = Invoke-Update 'manual'
    [IO.File]::WriteAllText($env:UPDATE_STATE, 'manual repair')
    $health = (& $entrypoint check) | ConvertFrom-Json
    if ($health.status -ne 'ready') { throw 'manual repair did not clear warning' }
    $result = Invoke-Update 'manual'
    $env:UPDATE_RELEASE = ''
    $result = Invoke-Update 'network'
    $health = (& $entrypoint check) | ConvertFrom-Json
    if ($health.status -ne 'ready') { throw 'unknown latest did not clear warning' }
    Write-Output 'PASS: synthetic Windows native update outcomes, arguments, privacy, deadline, and stale health clearance.'
} finally {
    Get-Process -Name fixture -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $fake } | Stop-Process -Force
    Remove-Item -LiteralPath $stage -Recurse -Force
}
