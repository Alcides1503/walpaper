@echo off
chcp 65001 >nul
where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em python.org marcando "Add Python to PATH" e rode de novo.
  pause & exit /b 1
)
echo [1/3] Instalando dependencias...
python -m pip install --upgrade pip
python -m pip install pyinstaller -r requirements.txt || goto erro
echo [2/3] Gerando o .exe (pode demorar alguns minutos)...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name WallpaperAnimado --add-data "videos;videos" app.py || goto erro
echo [3/3] Pronto!
copy /y dist\WallpaperAnimado.exe "%~dp0WallpaperAnimado.exe" >nul
start "" "%~dp0"
pause & exit /b 0
:erro
echo Deu erro na criacao do exe.
pause & exit /b 1
