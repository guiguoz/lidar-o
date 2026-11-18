@echo off
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PYTHON=%ROOT%\python\python.exe"
set "MARKER=%ROOT%\python\lidar-o-env-version.txt"
set "APP=%ROOT%\app"
set "DIAG=%APP%\scripts\diagnostic.py"

echo ============================================================
echo   LidarO -- Diagnostic
echo ============================================================
echo.

:: ----------------------------------------------------------------
:: 1. Verifier l'etat de l'installation
::    Ordre de priorite :
::      a) python_new\ existe  : extraction en cours
::      b) python\    existe, marqueur absent : initialisation en cours ou echouee
::      c) python\    absent   : installation jamais demarree
::      d) marqueur   present  : installation complete -> continuer
:: ----------------------------------------------------------------

if exist "%ROOT%\python_new\" (
    echo   Installation en cours : extraction de l'environnement Python.
    echo.
    echo   Attendez que la fenetre setup.bat affiche "Installation terminee",
    echo   puis relancez ce diagnostic.
    echo.
    pause
    exit /b 1
)

if exist "%ROOT%\python\" (
    if not exist "%MARKER%" (
        echo   Installation en cours ou interrompue.
        echo.
        echo   - Si la fenetre setup.bat est toujours ouverte :
        echo       attendez "Installation terminee", puis relancez ce diagnostic.
        echo   - Si setup.bat ne tourne plus ^(fenetre fermee ou erreur affichee^) :
        echo       relancez setup.bat pour reprendre l'installation.
        echo.
        pause
        exit /b 1
    )
) else (
    echo   Installation absente.
    echo.
    echo   Double-cliquez setup.bat, attendez "Installation terminee",
    echo   puis relancez ce diagnostic.
    echo.
    pause
    exit /b 1
)

:: ----------------------------------------------------------------
:: 2. Installation complete (marqueur present) -- coherence
:: ----------------------------------------------------------------

if not exist "%PYTHON%" (
    echo   ERREUR : marqueur present mais python\python.exe introuvable.
    echo   Archive incomplete ou corrompue -- relancez setup.bat.
    echo.
    pause
    exit /b 1
)

if not exist "%DIAG%" (
    echo   ERREUR : app\scripts\diagnostic.py introuvable.
    echo   Archive incomplete.
    echo.
    pause
    exit /b 1
)

:: ----------------------------------------------------------------
:: 3. Lancer le diagnostic Python
:: ----------------------------------------------------------------

set "PROJ_DATA=%ROOT%\python\Library\share\proj"
set "GDAL_DATA=%ROOT%\python\Library\share\gdal"
set "GDAL_DRIVER_PATH=%ROOT%\python\Library\lib\gdalplugins"
set "PATH=%ROOT%\python\Library\bin;%ROOT%\python\Scripts;%ROOT%\bin;%PATH%"

cd /d "%APP%"

:: Verification manifeste (facultatif -- skippee si absent)
set "MANIFEST=%ROOT%\manifest.json"
if exist "%MANIFEST%" (
    echo Verification manifeste sources...
    "%PYTHON%" "%APP%\scripts\verify_manifest.py" --verify --strict
    if !errorlevel! neq 0 (
        echo AVERTISSEMENT : paquet modifie depuis assemblage. Voir ci-dessus.
    )
    echo.
) else (
    echo Manifeste absent -- verification skippee.
    echo.
)

"%PYTHON%" "%DIAG%"
set "EXITCODE=!errorlevel!"

echo.
if !EXITCODE! equ 0 (
    echo Diagnostic termine : TOUT OK
) else (
    echo Diagnostic termine : ECHECS DETECTES -- voir le journal sur le Bureau
)
echo.
pause
exit /b !EXITCODE!
