$ErrorActionPreference = "Stop"
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m py_compile wahltool_batch_druck.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m PyInstaller --noconfirm --clean --windowed --onefile --collect-all playwright --collect-all pypdf --collect-all pdfplumber --collect-all pdfminer --name WahltoolBatchDruck wahltool_batch_druck.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
