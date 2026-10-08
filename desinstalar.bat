@echo off
REM dashmgr - Copyright (C) 2026 mayk.cloud e luniobr.com - SPDX-License-Identifier: GPL-3.0-or-later
setlocal
title Desinstalar - dashmgr
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "DESTINO=C:\dashmgr"
echo Desinstalando o dashmgr...
taskkill /F /IM dashmgr.exe >nul 2>&1
del "%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp\dashmgr.lnk" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\dashmgr.lnk" >nul 2>&1
del "%PUBLIC%\Desktop\dashmgr.lnk" >nul 2>&1
netsh advfirewall firewall delete rule name="dashmgr (Web)" >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\dashmgr" /f /reg:64 >nul 2>&1
REM nomes da versao "Telas NOC"
taskkill /F /IM TelasNOC.exe >nul 2>&1
del "%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp\Telas NOC.lnk" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Telas NOC.lnk" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PainelMultiTelas.cmd" >nul 2>&1
del "%PUBLIC%\Desktop\Telas NOC.lnk" >nul 2>&1
netsh advfirewall firewall delete rule name="Telas NOC (Web)" >nul 2>&1
powershell -NoProfile -Command "Remove-MpPreference -ExclusionPath '%DESTINO%'" >nul 2>&1
REM nomes da versao antiga
taskkill /F /IM PainelMultiTelas.exe >nul 2>&1
del "%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp\Painel Multi-Telas.lnk" >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Painel Multi-Telas.lnk" >nul 2>&1
del "%PUBLIC%\Desktop\Painel Multi-Telas.lnk" >nul 2>&1
netsh advfirewall firewall delete rule name="Painel Multi-Telas (Web)" >nul 2>&1
echo - Inicio automatico, atalho e regra de firewall removidos.
echo.
echo Os logins salvos do Chrome ficam em %%LOCALAPPDATA%%\PainelMultiTelas (nao foram apagados).
choice /c SN /m "Apagar tambem a pasta %DESTINO% (programa e configuracao)"
if errorlevel 2 goto fim
cd /d "%TEMP%"
start "" /min cmd /c "timeout /t 2 /nobreak >nul & rmdir /s /q %DESTINO%"
echo - Pasta sera apagada.
:fim
echo Concluido.
pause
