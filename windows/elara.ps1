# Elara - PowerShell launcher
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPy = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$EntryPy = Join-Path $ScriptDir "elara.py"

if (Test-Path $VenvPy) {
    & $VenvPy $EntryPy @args
} else {
    & python $EntryPy @args
}
