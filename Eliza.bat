@echo off
setlocal
rem ==================================================================
rem  ELIZA v3 - instalador + lanzador
rem
rem  Para instalar en un equipo nuevo basta con copiar Eliza.bat y
rem  Eliza.py a una carpeta y ejecutar Eliza.bat. La primera vez:
rem    1. busca Python en el equipo
rem    2. descarga la ultima version de Eliza desde GitHub (app\)
rem    3. crea el entorno .venv e instala dependencias
rem    4. arranca Eliza (que pregunta la carpeta de datos)
rem  Las siguientes veces solo arranca. /update dentro de Eliza descarga
rem  la ultima version y este .bat la vuelve a lanzar solo.
rem ==================================================================
cd /d "%~dp0"
title ELIZA v3

:inicio
rem --- Si una actualizacion trajo un Eliza.bat nuevo, se reemplaza aqui.
rem     El bloque entre parentesis ya esta leido en memoria, asi que es
rem     seguro sobrescribir este archivo y saltar al nuevo.
if exist "%~dp0Eliza.bat.nuevo" (
    move /y "%~dp0Eliza.bat.nuevo" "%~dp0Eliza.bat" >nul
    "%~dp0Eliza.bat" %*
)

rem --- 1. Python del sistema
set "SYSPY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "SYSPY=py -3"
if defined SYSPY goto python_ok
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "SYSPY=python"
if not defined SYSPY goto sin_python
:python_ok

rem --- 2. Programa
if exist "app\eliza3.py" goto app_ok
echo [*] Instalando Eliza desde GitHub...
%SYSPY% "%~dp0Eliza.py" instalar
if errorlevel 1 goto error_descarga
:app_ok

rem --- 3. Entorno virtual (se recrea si no existe o si quedo roto
rem        por copiarlo de otra carpeta/equipo)
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" goto crear_venv
"%PY%" -c "import sys" >nul 2>&1
if not errorlevel 1 goto venv_ok
echo [!] El entorno .venv no funciona en esta carpeta. Se va a recrear...
rmdir /s /q ".venv"
:crear_venv
echo [*] Creando entorno .venv ...
%SYSPY% -m venv ".venv"
if not exist "%PY%" goto sin_python
:venv_ok

rem --- 4. Dependencias: solo si requirements.txt cambio desde la ultima vez
fc /b "app\requirements.txt" ".venv\requirements.instalado" >nul 2>&1
if not errorlevel 1 goto deps_ok
echo [*] Instalando dependencias...
"%PY%" -m pip install --disable-pip-version-check -q -r "app\requirements.txt"
if errorlevel 1 goto error_pip
copy /y "app\requirements.txt" ".venv\requirements.instalado" >nul
:deps_ok

rem --- 5. Ejecutar. Codigo 10 = se actualizo con /update: volver a empezar.
"%PY%" "app\eliza3.py" %*
if errorlevel 11 goto fin_con_error
if errorlevel 10 goto inicio
if errorlevel 1 goto fin_con_error
exit /b 0

:fin_con_error
pause
exit /b 1

:sin_python
echo [!] No se encontro Python 3 en este equipo.
echo     Instalalo desde https://www.python.org/downloads/ marcando
echo     "Add python.exe to PATH" e incluyendo tcl/tk, y vuelve a ejecutar Eliza.bat
pause
exit /b 1

:error_descarga
echo [!] No se pudo descargar Eliza. Revisa la conexion a internet o el proxy
echo     y vuelve a ejecutar Eliza.bat
pause
exit /b 1

:error_pip
echo [!] No se pudieron instalar las dependencias. Revisa la conexion o el proxy
echo     y vuelve a ejecutar Eliza.bat
pause
exit /b 1
