@echo off
:: ============================================================
:: build.bat ? Construit l'archive LidarO-vX.Y.Z-Windows-x64.zip
:: Prerequis : conda, conda-pack, Python 3.13 (miniconda3)
:: Usage     : build.bat [--skip-pack [--pack-src CHEMIN\python.tar.gz]]
::   --skip-pack          : ne relance pas conda-pack
::   --pack-src CHEMIN    : copie un python.tar.gz existant (implicite --skip-pack)
:: ============================================================
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "REPO=%SCRIPT_DIR%\..\.."

:: Version applicative ? mettre a jour manuellement avant chaque release
set "APP_VERSION=v0.4.0"

set "DIST=%SCRIPT_DIR%\dist\LidarO-%APP_VERSION%-Windows-x64"

set "CONDA_CMD=C:\Users\glemi\miniconda3\Scripts\conda.exe"
set "CONDA_PACK_CMD=C:\Users\glemi\miniconda3\Scripts\conda-pack.exe"
set "ENV_NAME=lidar-o-dist"

:: Lire les param?tres
set "SKIP_PACK=0"
set "PACK_SRC="
set "_NEXT_SRC=0"
for %%a in (%*) do (
    if "!_NEXT_SRC!"=="1" (set "PACK_SRC=%%a" & set "_NEXT_SRC=0" & set "SKIP_PACK=1")
    if "%%a"=="--skip-pack" set "SKIP_PACK=1"
    if "%%a"=="--pack-src"  set "_NEXT_SRC=1"
)

echo ============================================================
echo   LidarO %APP_VERSION% ? Build archive Windows
echo ============================================================

:: Verifier que la distribution n'est pas bloquee
if exist "%REPO%\DISTRIBUTION_BLOCKED.md" (
    echo.
    echo ERREUR : distribution bloquee.
    echo   %REPO%\DISTRIBUTION_BLOCKED.md est present.
    echo   Lire ce fichier pour connaitre la raison et les conditions de levee.
    echo.
    exit /b 1
)

:: 1. Creer la structure dist/
echo.
echo [1/5] Structure dist...
if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%\app\gui"
mkdir "%DIST%\app\src"
mkdir "%DIST%\app\scripts"
mkdir "%DIST%\app\assets"
mkdir "%DIST%\app\experiments\loto_v1"
mkdir "%DIST%\app\experiments\bois_dupont\supervised_v1"
mkdir "%DIST%\bin"
mkdir "%DIST%\models"
mkdir "%DIST%\docs"

:: 2. Copier les sources
echo [2/5] Copie des sources...
xcopy /s /q /y "%REPO%\gui\"     "%DIST%\app\gui\"     >nul
xcopy /s /q /y "%REPO%\src\"     "%DIST%\app\src\"     >nul
xcopy /s /q /y "%REPO%\scripts\" "%DIST%\app\scripts\" >nul
xcopy /q /y    "%REPO%\main.py"  "%DIST%\app\"         >nul
xcopy /q /y    "%REPO%\assets\"  "%DIST%\app\assets\"  >nul
:: Exclure les georef de test/developpement (non destines a la distribution publique)
del /q "%DIST%\app\assets\georef_grimbosq_validation_relief.xml"      >nul 2>nul
del /q "%DIST%\app\assets\georef_mon_projet.xml"                       >nul 2>nul
del /q "%DIST%\app\assets\georef_grimbosq_kp_validation_v2.xml"       >nul 2>nul

:: Modules n?cessaires ? src/supervised_e.py (imports transitifs)
copy /y "%REPO%\experiments\loto_v1\descriptors_ext.py" "%DIST%\app\experiments\loto_v1\" >nul
if !errorlevel! neq 0 (echo ERREUR : experiments\loto_v1\descriptors_ext.py absent. & exit /b 1)
copy /y "%REPO%\experiments\bois_dupont\supervised_v1\descriptors.py" "%DIST%\app\experiments\bois_dupont\supervised_v1\" >nul
if !errorlevel! neq 0 (echo ERREUR : experiments\bois_dupont\supervised_v1\descriptors.py absent. & exit /b 1)
copy /y "%REPO%\experiments\bois_dupont\supervised_v1\config.py"      "%DIST%\app\experiments\bois_dupont\supervised_v1\" >nul
if !errorlevel! neq 0 (echo ERREUR : experiments\bois_dupont\supervised_v1\config.py absent. & exit /b 1)

:: config_default.yaml (sans terrains personnels)
if exist "%REPO%\config_default.yaml" (
    copy /y "%REPO%\config_default.yaml" "%DIST%\app\" >nul
) else (
    echo AVERTISSEMENT : config_default.yaml absent -- a creer avant distribution.
)

:: Binaire KP + licence GPL-3.0 obligatoire
if exist "%REPO%\bin\pullauta.exe" (
    copy /y "%REPO%\bin\pullauta.exe"              "%DIST%\bin\" >nul
) else (
    echo AVERTISSEMENT : bin\pullauta.exe absent.
)
if exist "%REPO%\bin\LICENSE.karttapullautin" (
    copy /y "%REPO%\bin\LICENSE.karttapullautin"   "%DIST%\bin\" >nul
) else (
    echo ERREUR : bin\LICENSE.karttapullautin absent -- obligatoire pour GPL-3.0.
    exit /b 1
)

:: Modele
if exist "%REPO%\experiments\loto_v1\final_model\model_e_final.pkl" (
    copy /y "%REPO%\experiments\loto_v1\final_model\model_e_final.pkl" "%DIST%\models\" >nul
) else (
    echo ERREUR : model_e_final.pkl absent.
    exit /b 1
)

:: Lanceurs publics (LidarO_test.bat exclu ? Sandbox uniquement)
copy /y "%SCRIPT_DIR%\setup.bat"             "%DIST%\" >nul
copy /y "%SCRIPT_DIR%\LidarO.bat"            "%DIST%\" >nul
copy /y "%SCRIPT_DIR%\LidarO_cli.bat"        "%DIST%\" >nul
copy /y "%SCRIPT_DIR%\LidarO_diagnostic.bat" "%DIST%\" >nul
:: Script de diagnostic ? appel? par LidarO_diagnostic.bat
copy /y "%SCRIPT_DIR%\diagnostic.py"         "%DIST%\app\scripts\" >nul
if !errorlevel! neq 0 (echo ERREUR : diagnostic.py absent. & exit /b 1)

:: Documentation utilisateur ? obligatoire
if exist "%SCRIPT_DIR%\docs\DEMARRER.html" (
    copy /y "%SCRIPT_DIR%\docs\DEMARRER.html" "%DIST%\docs\" >nul
) else (
    echo ERREUR : docs\DEMARRER.html absent -- a creer avant distribution.
    exit /b 1
)

:: Version applicative (versioning semantique)
echo %APP_VERSION%> "%DIST%\VERSION.txt"

:: Commit de build (identifiant du code ayant produit ce paquet)
git -C "%REPO%" rev-parse --short HEAD > "%DIST%\COMMIT.txt" 2>nul || echo unknown> "%DIST%\COMMIT.txt"
set "COMMIT_CONTENT="
for /f "usebackq delims=" %%c in ("%DIST%\COMMIT.txt") do set "COMMIT_CONTENT=%%c"
echo build_commit : !COMMIT_CONTENT!

:: 3. Paquet Python
if "%SKIP_PACK%"=="1" (
    echo [3/5] Pack Python -- IGNORE ^(--skip-pack^).
    if not "%PACK_SRC%"=="" (
        echo Copie python.tar.gz depuis %PACK_SRC%...
        copy /y "%PACK_SRC%" "%DIST%\python.tar.gz" >nul
        if !errorlevel! neq 0 (
            echo ERREUR : copie de python.tar.gz echouee.
            exit /b 1
        )
    ) else if not exist "%DIST%\python.tar.gz" (
        echo ERREUR : --skip-pack sans --pack-src et python.tar.gz absent du staging.
        echo Usage : build.bat --skip-pack --pack-src chemin\python.tar.gz
        exit /b 1
    )
) else (
    echo [3/5] Pack Python ^(peut prendre 2-3 min^)...
    "%CONDA_PACK_CMD%" -n %ENV_NAME% -o "%DIST%\python.tar.gz" --ignore-editable-packages
    if !errorlevel! neq 0 (
        echo ERREUR conda-pack ^(code !errorlevel!^).
        exit /b 1
    )
)

:: Version du runtime Python ? liee au contenu de python.tar.gz, pas a la date de build.
:: Un changement de SHA ? setup.bat re-extrait l'env ; meme SHA ? extraction ignoree.
set "SHA_TAR="
for /f "skip=1 tokens=1" %%h in ('certutil -hashfile "%DIST%\python.tar.gz" SHA256 2^>nul') do (
    if "!SHA_TAR!"=="" set "SHA_TAR=%%h"
)
set "SHA_TAR=!SHA_TAR: =!"
if "!SHA_TAR!"=="" (
    echo ERREUR : SHA-256 de python.tar.gz non calculable.
    exit /b 1
)
set "RUNTIME_VER=lidar-o-dist-!SHA_TAR:~0,12!"
echo !RUNTIME_VER!> "%DIST%\python_env_version.txt"
echo python_env_version : !RUNTIME_VER!

:: Metadonnees du paquet ? versions app / modele / runtime pour tracabilite des runs
set "MODEL_SHA256=48da30428cb0f42479ad5d28d668174a5e710bfdde02fa44c5f539aad320eeb5"
(
echo {
echo   "app_version": "%APP_VERSION%",
echo   "build_commit": "!COMMIT_CONTENT!",
echo   "model_file": "model_e_final.pkl",
echo   "model_sha256": "!MODEL_SHA256!",
echo   "runtime_version": "!RUNTIME_VER!"
echo }
) > "%DIST%\app\metadata.json"
echo metadata.json genere.

:: 4. Manifeste SHA-256 (sources .py + binaires + ressources)
echo [4/5] Manifeste...
"%CONDA_CMD%\..\..\python.exe" "%DIST%\app\scripts\verify_manifest.py" --generate
if !errorlevel! neq 0 (
    echo ERREUR manifeste.
    exit /b 1
)
:: Sidecar SHA-256 de python.tar.gz (reference independante du manifeste source)
if not "!SHA_TAR!"=="" (
    echo !SHA_TAR!  python.tar.gz> "%DIST%\python.tar.gz.sha256"
    echo   python.tar.gz : !SHA_TAR!
)

:: 5. ZIP
echo [5/5] Archive ZIP...
set "ZIP_OUT=%SCRIPT_DIR%\dist\LidarO-%APP_VERSION%-Windows-x64.zip"
powershell -Command "Compress-Archive -Path '%DIST%' -DestinationPath '%ZIP_OUT%' -Force"
if !errorlevel! neq 0 (
    echo ERREUR ZIP.
    exit /b 1
)

:: SHA-256 du ZIP
set "SHA_ZIP="
for /f "skip=1 tokens=1" %%h in ('certutil -hashfile "%ZIP_OUT%" SHA256 2^>nul') do (
    if "!SHA_ZIP!"=="" set "SHA_ZIP=%%h"
)
if not "!SHA_ZIP!"=="" (
    echo !SHA_ZIP!  LidarO-%APP_VERSION%-Windows-x64.zip> "%ZIP_OUT%.sha256"
    echo ZIP SHA-256 : !SHA_ZIP!
)
for /f %%s in ('powershell -Command "(Get-Item \"%ZIP_OUT%\").length / 1MB"') do echo ZIP taille : %%s Mo

echo.
echo ============================================================
echo   Build termine : %ZIP_OUT%
echo ============================================================
exit /b 0
