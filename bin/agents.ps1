# Dispatcher for this repository's Python tools. Run `agents.ps1 help` for the
# subcommand list. See README.md "System-wide install" for wrapping this in a
# $PROFILE function so it can be invoked as bare `agents`.

$RepoRoot = Split-Path -Parent $PSScriptRoot

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
  @"
Usage: agents <subcommand> [args...]

Subcommands:
  select           Deterministic agent/gate selection (select_agents.py)
  knowledge        Vectorized knowledge store CLI (knowledge-store/src/cli.py)
  sdlc             Portable Agentic SDLC CLI (agentic_sdlc.py)
  validate-run     Validate a repository-suite run record (validate_run_record.py)
  generate-plugin  Regenerate plugins/secure-cloud-agents/ (generate_global_plugin.py)
  help             Show this message

Each subcommand's own --help documents its arguments, e.g. `agents sdlc plan --help`.
"@
}

$Command, $Rest = $args
if (-not $Command) { $Command = "help" }

switch ($Command) {
  "select"          { & $AgentPython.Path @($AgentPython.Args) "$RepoRoot\agents\orchestration\src\select_agents.py" @Rest }
  "knowledge"       { & $AgentPython.Path @($AgentPython.Args) "$RepoRoot\agents\knowledge-store\src\cli.py" @Rest }
  "sdlc"            { & $AgentPython.Path @($AgentPython.Args) "$RepoRoot\plugins\agentic-sdlc\scripts\agentic_sdlc.py" @Rest }
  "validate-run"    { & $AgentPython.Path @($AgentPython.Args) "$RepoRoot\agents\orchestration\src\validate_run_record.py" @Rest }
  "generate-plugin" { & $AgentPython.Path @($AgentPython.Args) "$RepoRoot\agents\orchestration\src\generate_global_plugin.py" @Rest }
  { $_ -in "help", "-h", "--help" } { Show-Usage }
  default {
    Write-Error "agents: unknown subcommand '$Command'"
    Show-Usage
    exit 1
  }
}
exit $LASTEXITCODE
