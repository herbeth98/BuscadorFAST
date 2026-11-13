@echo off
rem Monta dist\BuscadorFAST-Instalador-<versao>.exe   (uso: montar.bat 1.0.0)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0montar.ps1" %*
if errorlevel 1 pause
