# Gera a pasta dist\AudioSwitchBT com o executável standalone AudioSwitchBT.exe
$ErrorActionPreference = "Stop"

python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name "AudioSwitchBT" `
    --add-data "graphics.py;." `
    --add-data "audio_backend.py;." `
    audio_widget.py

Write-Host "`nBuild concluído! Executável gerado em: dist\AudioSwitchBT\AudioSwitchBT.exe" -ForegroundColor Green
