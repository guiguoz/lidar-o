@echo off
:: LidarO_cli.bat — Terminal de maintenance avec environnement complet.
::
:: Ouvre un cmd.exe avec le meme PATH, GDAL_DATA, PROJ_DATA et LIDAR_OUTPUT_ROOT
:: que LidarO.bat. Utiliser pour les commandes de reprise, diagnostics, etc.
::
:: Usage :
::   Double-clic LidarO_cli.bat          -> terminal interactif
::   LidarO_cli.bat "python main.py ..." -> commande unique (sans pause)
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PYTHON=%ROOT%\python\python.exe"
set "MARKER=%ROOT%\python\lidar-o-env-version.txt"
set "APP=%ROOT%\app"

if not exist "%MARKER%" (
    echo ERREUR : environnement Python non initialise.
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

:: Meme environnement que LidarO.bat
set "PROJ_DATA=%ROOT%\python\Library\share\proj"
set "GDAL_DATA=%ROOT%\python\Library\share\gdal"
set "GDAL_DRIVER_PATH=%ROOT%\python\Library\lib\gdalplugins"
set "PATH=%ROOT%\python\Library\bin;%ROOT%\python\Scripts;%ROOT%\bin;%PATH%"

:: Dossier de sortie Sandbox (herite de LidarO_test.bat si ouvert depuis lui)
if "%LIDAR_OUTPUT_ROOT%"=="" set "LIDAR_OUTPUT_ROOT=C:\sandbox_results"

:: Se placer dans app/
cd /d "%APP%"

echo ============================================================
echo   LidarO CLI  —  terminal de maintenance
echo   APP     : %APP%
echo   PYTHON  : %PYTHON%
echo   OUTPUT  : %LIDAR_OUTPUT_ROOT%
echo ============================================================
echo.
echo Commandes utiles :
echo   python main.py run TERRAIN --tiles-dir DIR --from-step STEP
echo   python main.py run TERRAIN --tiles-dir DIR --from-step assemble
echo   python scripts\test_kp_pipeline.py TERRAIN --tiles-dir DIR --out-root %LIDAR_OUTPUT_ROOT%
echo   python scripts\diagnostic.py
echo.

if "%~1"=="" (
    :: Mode interactif — ouvre un shell
    cmd /k "echo Pret. Taper 'exit' pour fermer."
) else (
    :: Mode commande unique
    %PYTHON% %*
    set "EXITCODE=%errorlevel%"
    if !EXITCODE! neq 0 (
        echo.
        echo ERREUR : code !EXITCODE!
        pause
        exit /b !EXITCODE!
    )
)
exit /b 0
