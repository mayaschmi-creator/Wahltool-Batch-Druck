$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Check-ExitCode {
    if ($LASTEXITCODE -ne 0) {
        throw "Ein Build-Schritt ist fehlgeschlagen (Exitcode $LASTEXITCODE)."
    }
}

python -m venv .venv
Check-ExitCode
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
Check-ExitCode
& $python -m pip install -r requirements.txt
Check-ExitCode
& $python -m py_compile wahltool_batch_druck.py
Check-ExitCode
& $python -m unittest discover -s tests -v
Check-ExitCode
& $python -m PyInstaller --noconfirm --clean --windowed --onefile --noupx --collect-all playwright --collect-all pypdf --name WahltoolBatchDruck wahltool_batch_druck.py
Check-ExitCode

Write-Host "Fertig: dist\WahltoolBatchDruck.exe"
