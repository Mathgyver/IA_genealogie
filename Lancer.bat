@echo off
title Assistant Genealogie IA
cls
echo ===================================================
echo   Lancement de l'Assistant Genealogie IA...
echo ===================================================
echo.

:: Démarre l'interface en ciblant le Python embarqué local
"%~dp0python-3.11.9\python.exe" "%~dp0assistant_gui.py"

if %errorlevel% neq 0 (
    echo.
    echo [ERREUR] Une erreur est survenue lors de l'execution.
    pause
)