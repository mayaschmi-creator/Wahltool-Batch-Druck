$ErrorActionPreference = "Stop"

python -m venv .venv
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt
& $python -m unittest discover -s tests -v
& $python -m PyInstaller --noconfirm --clean --windowed --onefile --collect-all playwright --name WahltoolBatchDruck wahltool_batch_druck.py

Write-Host "Fertig: dist\WahltoolBatchDruck.exe"