@echo off
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PYTHON=%ROOT%\python\python.exe"
set "MARKER=%ROOT%\python\lidar-o-env-version.txt"
set "APP=%ROOT%\app"

:: Verifier que setup.bat a ete execute
if not exist "%MARKER%" (
    echo ERREUR : environnement Python non initialise.
    echo.
    echo Lancez setup.bat une premiere fois avant d'utiliser LidarO.
    pause
    exit /b 1
)

if not exist "%PYTHON%" (
    echo ERREUR : python.exe introuvable dans python\
    echo Supprimer le dossier python\ et relancer setup.bat.
    pause
    exit /b 1
)

:: Variables GDAL/PROJ — chemins verifies dans le paquet construit
set "PROJ_DATA=%ROOT%\python\Library\share\proj"
set "GDAL_DATA=%ROOT%\python\Library\share\gdal"
set "GDAL_DRIVER_PATH=%ROOT%\python\Library\lib\gdalplugins"
set "PATH=%ROOT%\python\Library\bin;%ROOT%\python\Scripts;%ROOT%\bin;%PATH%"

:: Verifier que les donnees PROJ existent
if not exist "%PROJ_DATA%\proj.db" (
    echo AVERTISSEMENT : PROJ_DATA introuvable (%PROJ_DATA%)
    echo  Les projections cartographiques peuvent etre incorrectes.
)

:: Lancer la GUI
cd /d "%APP%"
"%PYTHON%" main.py gui
set "EXITCODE=%errorlevel%"

if !EXITCODE! neq 0 (
    echo.
    echo ERREUR : LidarO a quitte avec le code !EXITCODE!.
    echo Consulter le journal ci-dessus pour le detail.
    pause
    exit /b !EXITCODE!
)
exit /b 0
