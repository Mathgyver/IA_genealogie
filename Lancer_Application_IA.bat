title Assistant Genealogie IA
cls
echo ===================================================
echo   Tentative de lancement de l'application...
echo ===================================================
echo.

echo 1. Verification et activation de l'environnement virtuel...
call "F:\Genealogie_IA\.venv\Scripts\activate.bat"

echo.
echo 2. Lancement du script graphique avec Python...
python "F:\Genealogie_IA\assistant_gui.py"

echo.
echo ===================================================
echo   Fin d'execution ou erreur detectee.
echo ===================================================
pause