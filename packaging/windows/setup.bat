@echo off
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "PYTHON_DIR=%ROOT%\python"
set "PYTHON=%PYTHON_DIR%\python.exe"
set "UNPACK=%PYTHON_DIR%\Scripts\conda-unpack.exe"
set "MARKER=%PYTHON_DIR%\lidar-o-env-version.txt"
set "ENV_VERSION_FILE=%ROOT%\python_env_version.txt"

set "PYTHON_NEW_DIR=%ROOT%\python_new"
set "PYTHON_OLD_DIR=%ROOT%\python_old"

echo ============================================================
echo   LidarO -- Installation / Mise a jour
echo ============================================================
echo.

:: ================================================================
:: 1. Version de l'archive
:: ================================================================
if not exist "%ENV_VERSION_FILE%" (
    echo ERREUR : python_env_version.txt introuvable dans %ROOT%
    echo Archive incomplete ou corrompue.
    pause
    exit /b 1
)
set /p ARCHIVE_VER=<"%ENV_VERSION_FILE%"

:: ================================================================
:: 2. Nettoyage demarrage
::    - python_new\ : extraction jamais activee -- toujours safe
::    - python_old\ : traitement selon etat de python\
::      * python\ a un marqueur valide  --> python_old\ est obsolete
::      * python\ sans marqueur         --> update interrompue apres renommage
::                                          python_old\ est la copie fonctionnelle
:: ================================================================
if exist "%PYTHON_NEW_DIR%" (
    echo Nettoyage de python_new\ ^(extraction interrompue^)...
    rmdir /s /q "%PYTHON_NEW_DIR%"
)

if exist "%PYTHON_OLD_DIR%" (
    if exist "%MARKER%" (
        echo Nettoyage de python_old\ ^(sauvegarde obsolete -- python\ est valide^)...
        rmdir /s /q "%PYTHON_OLD_DIR%"
    ) else (
        :: python\ existe mais sans marqueur : rename vers python\ s'est fait
        :: mais conda-unpack ou la validation ont echoue/ete interrompus.
        :: python_old\ est la seule copie fonctionnelle -- la restaurer.
        echo Recuperation : python\ sans marqueur, python_old\ est la copie fonctionnelle.
        if exist "%PYTHON_DIR%" (
            ren "%ROOT%\python" python_incomplete 2>nul
            rmdir /s /q "%ROOT%\python_incomplete" 2>nul
        )
        ren "%ROOT%\python_old" python 2>nul
        echo Ancien environnement restaure -- poursuite de l'installation.
        echo.
    )
)

:: ================================================================
:: 3. Version installee (lue apres le nettoyage -- python\ peut avoir change)
:: ================================================================
set "INSTALLED_VER="
if exist "%MARKER%" set /p INSTALLED_VER=<"%MARKER%"

if "!INSTALLED_VER!"=="!ARCHIVE_VER!" (
    echo [OK] L'environnement est deja a jour ^(!ARCHIVE_VER!^).
    echo      Aucune action requise.
    goto :done
)

if "!INSTALLED_VER!"=="" (
    echo Premiere installation ^(!ARCHIVE_VER!^)...
) else (
    echo Mise a jour de ^(!INSTALLED_VER!^) vers ^(!ARCHIVE_VER!^)...
)
echo.

:: ================================================================
:: 4. Verifier l'archive
:: ================================================================
set "ARCHIVE=%ROOT%\python.tar.gz"
if not exist "%ARCHIVE%" (
    echo ERREUR : python.tar.gz introuvable dans %ROOT%
    echo Verifiez que l'archive est complete.
    pause
    exit /b 1
)

:: ================================================================
:: 5. Extraire dans python_new\
::    conda-unpack sera execute APRES le renommage vers python\
::    pour que les chemins absolus soient fixes vers l'emplacement definitif.
:: ================================================================
echo Extraction de l'environnement Python dans python_new\...
echo ^(Operation de ~2 min -- ne pas fermer cette fenetre^)
echo.

mkdir "%PYTHON_NEW_DIR%"

:: Utiliser %SystemRoot%\System32\tar.exe : le tar GNU (Git/MSYS) echoue
:: sur les archives conda-pack avec "unexpected end of file" (bogue connu).
set "TAR=%SystemRoot%\System32\tar.exe"
if not exist "%TAR%" (
    echo ERREUR : tar.exe introuvable ^(%TAR%^).
    echo Ce programme requiert Windows 10 ^(1803^) ou ulterieur.
    rmdir /s /q "%PYTHON_NEW_DIR%" 2>nul
    pause
    exit /b 1
)
"%TAR%" -xzf "%ARCHIVE%" -C "%PYTHON_NEW_DIR%"
if !errorlevel! neq 0 (
    echo ERREUR : extraction echouee ^(code !errorlevel!^).
    rmdir /s /q "%PYTHON_NEW_DIR%" 2>nul
    pause
    exit /b 1
)

:: ================================================================
:: 6. Renommage vers le chemin definitif AVANT conda-unpack
::    conda-unpack lit son propre chemin pour fixer les prefixes --
::    il doit etre appele depuis python\ et non depuis python_new\.
:: ================================================================
echo Activation du chemin definitif...

if exist "%PYTHON_DIR%" (
    ren "%ROOT%\python" python_old
    if !errorlevel! neq 0 (
        echo ERREUR : impossible de renommer python\ en python_old\.
        echo   Verifiez qu'aucun processus LidarO n'est en cours.
        rmdir /s /q "%PYTHON_NEW_DIR%" 2>nul
        pause
        exit /b 1
    )
)

ren "%ROOT%\python_new" python
if !errorlevel! neq 0 (
    echo ERREUR : impossible de renommer python_new\ en python\.
    :: Restaurer python_old\ si disponible
    if exist "%PYTHON_OLD_DIR%" ren "%ROOT%\python_old" python 2>nul
    rmdir /s /q "%PYTHON_NEW_DIR%" 2>nul
    pause
    exit /b 1
)

:: ================================================================
:: 7. conda-unpack depuis le chemin definitif python\
::    Fixe tous les chemins absolus pour pointer vers python\
::
::    IMPORTANT : PATH etendu ICI, avant conda-unpack.
::    conda-unpack.exe est dans python\Scripts\ ; Windows cherche
::    les DLLs dans le dossier de l'exe puis dans PATH.
::    vcruntime140.dll se trouve dans python\Library\bin\ et python\
::    mais ces dossiers ne sont pas dans PATH par defaut --
::    sans ce PATH, conda-unpack echoue avec "VCRUNTIME140.dll introuvable".
:: ================================================================
set "PROJ_DATA=%PYTHON_DIR%\Library\share\proj"
set "GDAL_DATA=%PYTHON_DIR%\Library\share\gdal"
set "PATH=%PYTHON_DIR%\Library\bin;%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PATH%"

if not exist "%UNPACK%" (
    echo ERREUR : conda-unpack.exe absent dans python\Scripts\
    goto :restore_and_abort
)
echo Initialisation des chemins ^(conda-unpack depuis python\^)...
"%UNPACK%"
if !errorlevel! neq 0 (
    echo ERREUR : conda-unpack a echoue ^(code !errorlevel!^).
    goto :restore_and_abort
)

:: ================================================================
:: 8. Validation depuis python\ (chemin definitif, apres conda-unpack)
:: ================================================================

echo Validation de l'environnement...
"%PYTHON%" -c "import sklearn, rasterio, pdal, geopandas; print('[OK] sklearn + rasterio + pdal + geopandas importes')"
if !errorlevel! neq 0 (
    echo ERREUR : validation des imports echouee.
    goto :restore_and_abort
)

:: ================================================================
:: 9. SHA-256 du modele (certutil -- aucune dependance externe)
:: ================================================================
set "MODEL=%ROOT%\models\model_e_final.pkl"
if exist "%MODEL%" (
    echo.
    echo Verification du modele...
    set "MODEL_SHA="
    for /f "skip=1 tokens=1" %%h in ('certutil -hashfile "%MODEL%" SHA256 2^>nul') do (
        if "!MODEL_SHA!"=="" set "MODEL_SHA=%%h"
    )
    set "MODEL_SHA=!MODEL_SHA: =!"
    if /i "!MODEL_SHA!"=="48da30428cb0f42479ad5d28d668174a5e710bfdde02fa44c5f539aad320eeb5" (
        echo [OK] Modele verifie.
    ) else (
        echo ERREUR : SHA-256 modele incorrect.
        echo   Obtenu   : !MODEL_SHA!
        echo   Attendu  : 48da30428cb0f42479ad5d28d668174a5e710bfdde02fa44c5f539aad320eeb5
        goto :restore_and_abort
    )
)

:: ================================================================
:: 10. Succes -- marquer et nettoyer
:: ================================================================
echo !ARCHIVE_VER!> "%MARKER%"

if exist "%PYTHON_OLD_DIR%" (
    echo Suppression de python_old\ ^(tous les controles sont passes^)...
    rmdir /s /q "%PYTHON_OLD_DIR%" 2>nul
)

echo.
echo ============================================================
echo   Installation terminee ^(!ARCHIVE_VER!^).
echo   Lancez LidarO.bat pour ouvrir l'interface.
echo ============================================================
echo.
goto :done

:: ================================================================
:: Restauration apres echec post-renommage
::   python\      --> python_failed\ (en cours de suppression)
::   python_old\  --> python\        (si disponible)
:: ================================================================
:restore_and_abort
echo.
echo Restauration de l'ancien environnement...
if exist "%PYTHON_DIR%" ren "%ROOT%\python" python_failed 2>nul
if exist "%PYTHON_OLD_DIR%" (
    ren "%ROOT%\python_old" python 2>nul
    if !errorlevel! equ 0 (
        echo [OK] Ancien environnement restaure.
    ) else (
        echo ERREUR : restauration de python_old\ impossible.
    )
) else (
    echo Aucun ancien environnement disponible pour la restauration.
)
if exist "%ROOT%\python_failed" rmdir /s /q "%ROOT%\python_failed" 2>nul
pause
exit /b 1

:done
pause
exit /b 0
