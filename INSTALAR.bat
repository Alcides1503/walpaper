@echo off
chcp 65001 >nul
echo Instalando dependencias (precisa do Python 3.10+ instalado)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Pronto! Agora de duplo clique em EXECUTAR.bat
pause
