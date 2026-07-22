# Dispatcher for this repository's Python tools. Run `agents.ps1 help` for the
# subcommand list. See README.md "System-wide install" for wrapping this in a
# $PROFILE function so it can be invoked as bare `agents`.

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SubcommandsPath = Join-Path $PSScriptRoot "subcommands.tsv"
$Subcommands = Get-Content $SubcommandsPath | Where-Object { $_ -ne "" } | ForEach-Object {
  $Fields = $_ -split "`t"
  [pscustomobject]@{ Name = $Fields[0]; Script = $Fields[1]; Description = $Fields[2] }
}

$AgentPython = $null
foreach ($Candidate in @(
  [pscustomobject]@{ Name = "python"; Args = @() },
  [pscustomobject]@{ Name = "python3"; Args = @() },
  [pscustomobject]@{ Name = "py"; Args = @("-3") }
)) {
  $Command = Get-Command $Candidate.Name -ErrorAction SilentlyContinue
  if ($Command) {
    & $Command.Source @($Candidate.Args) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $AgentPython = [pscustomobject]@{ Path = $Command.Source; Args = $Candidate.Args }; break }
  }
}
if (-not $AgentPython) { throw "agents: Python 3.10+ is required (checked python, python3, py -3)" }

function Show-Usage {
  Write-Output "Usage: agents <subcommand> [args...]"
  Write-Output ""
  Write-Output "Subcommands:"
  foreach ($Sub in $Subcommands) {
    Write-Output ("  {0,-16} {1}" -f $Sub.Name, $Sub.Description)
  }
  Write-Output ("  {0,-16} {1}" -f "help", "Show this message")
  Write-Output ""
  Write-Output "Each subcommand's own --help documents its arguments, e.g. ``agents sdlc plan --help``."
}

$Command, $Rest = $args
if (-not $Command) { $Command = "help" }

if ($Command -in @("help", "-h", "--help")) {
  Show-Usage
} else {
  $Match = $Subcommands | Where-Object { $_.Name -eq $Command } | Select-Object -First 1
  if ($Match) {
    $ScriptPath = Join-Path $RepoRoot ($Match.Script -replace "/", [System.IO.Path]::DirectorySeparatorChar)
    & $AgentPython.Path @($AgentPython.Args) $ScriptPath @Rest
  } else {
    Write-Error "agents: unknown subcommand '$Command'"
    Show-Usage
    exit 1
  }
}
exit $LASTEXITCODE
