@echo off
title BuscadorFAST
cd /d "%~dp0"
".venv\Scripts\python.exe" -m buscador %*
if errorlevel 1 pause
