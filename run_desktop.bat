@echo off
setlocal
if exist "%~dp0dist\CardProof.exe" (
  start "" "%~dp0dist\CardProof.exe"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
  start "" "%~dp0dist\CardProof.exe"
)
