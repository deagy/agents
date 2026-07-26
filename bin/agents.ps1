# Entry point for this repository's `agents` CLI. Finds a Python 3.10+
# interpreter and hands off to bin/agents.py, which owns the subcommand
# table, sdlc delegation, usage text, and dispatch logic (kept in one place
# instead of duplicated here and in bin/agents). See README.md "System-wide
# install" for wrapping this in a $PROFILE function so it can be invoked as
# bare `agents`.

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

& $AgentPython.Path @($AgentPython.Args) (Join-Path $PSScriptRoot "agents.py") @args
exit $LASTEXITCODE
