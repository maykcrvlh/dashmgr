@echo off
REM dashmgr - Copyright (C) 2026 mayk.cloud e luniobr.com - SPDX-License-Identifier: GPL-3.0-or-later
setlocal
title Gerar instalador - dashmgr
cd /d "%~dp0"
echo ============================================================
echo   GERAR INSTALADOR - DASHMGR
echo   Rode NESTE PC (que tem Python). Leve o .zip para o PC final.
echo   Arquivos temporarios ficam em _build (pode apagar depois).
echo ============================================================
echo.
where python >nul 2>&1 || (echo ERRO: Python nao encontrado neste PC. & pause & exit /b 1)

:gerar
if exist _build rmdir /s /q _build
python preparar_versao.py >nul || goto erro
set /p VERSAO=<_build\versao.txt
for /f "tokens=1 delims=." %%a in ("%VERSAO%") do set "MAJOR=%%a"
set "SETUP=dashmgr_instalador_v%MAJOR%"
set "B=%~dp0_build"
set "PYI=--noconfirm --onedir --noconsole --icon "%~dp0dashmgr.ico" --version-file "%B%\version_info.txt" --workpath "%B%\work" --distpath "%B%\dist" --specpath "%B%" --log-level WARN"
echo   Versao: v%VERSAO%   Instalador: %SETUP%
echo.
python -m pip install --upgrade --quiet --no-warn-script-location pyinstaller || goto erro

echo [1/4] Gerando o programa dashmgr ...
python -m PyInstaller %PYI% --name dashmgr "%~dp0dashmgr.py" || goto erro
timeout /t 5 /nobreak >nul
if not exist "%B%\dist\dashmgr\dashmgr.exe" goto antivirus

echo [2/4] Montando o conteudo do instalador ...
python empacotar.py payload || goto antivirus

echo [3/4] Gerando o instalador %SETUP%.exe ...
python -m PyInstaller %PYI% --uac-admin --name %SETUP% --add-data "%B%\payload\payload.zip;." "%~dp0instalador.py" || goto erro
timeout /t 5 /nobreak >nul
if not exist "%B%\dist\%SETUP%\%SETUP%.exe" goto antivirus

echo [4/4] Compactando ...
python empacotar.py zip %SETUP% || goto erro

echo.
echo ============================================================
echo   PRONTO: %~dp0%SETUP%.zip
echo   No PC definitivo: extraia o .zip, abra a pasta %SETUP%
echo   e de duplo clique em %SETUP%.exe
echo ============================================================
pause
exit /b 0

:antivirus
echo.
echo ************************************************************
echo   O ANTIVIRUS APAGOU UM DOS PROGRAMAS GERADOS (falso positivo
echo   comum em programas feitos com PyInstaller).
echo.
echo   Opcao 1: adicionar esta pasta como excecao no Windows Defender
echo            (pede permissao de administrador) e gerar de novo.
echo   Opcao 2: se o antivirus for corporativo, peca a excecao da pasta
echo            abaixo ao responsavel e rode este arquivo de novo:
echo            %~dp0
echo ************************************************************
choice /c SN /m "Adicionar a excecao no Windows Defender agora e tentar de novo"
if errorlevel 2 (pause & exit /b 1)
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile','-Command','Add-MpPreference -ExclusionPath ''%~dp0'''"
echo Excecao adicionada. Gerando de novo...
echo.
goto gerar

:erro
echo.
echo *** Falhou. Veja a mensagem acima. ***
pause
exit /b 1
