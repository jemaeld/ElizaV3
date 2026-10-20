"""
Eliza.py -- instalador / actualizador de Eliza V3
=================================================
Se distribuye junto con Eliza.bat (solo esos dos archivos). Usa únicamente la
biblioteca estándar de Python, así que funciona con el Python del sistema
ANTES de que exista el .venv.

Estructura de una instalación (la carpeta donde están Eliza.bat y Eliza.py):

    Eliza.bat              lanzador + instalador (lo que se ejecuta)
    Eliza.py               este archivo
    app/                   el programa (se descarga de GitHub)
      VERSION.json         commit instalado
    .venv/                 entorno de Python (lo crea Eliza.bat)
    datos/                 carpeta de datos LOCAL (si no se usa una remota)
    eliza_local.json       qué carpeta de datos usar (la elige Eliza al primer arranque)
    eliza_github_token.txt token de solo lectura (solo si el repo es privado)

Uso (normalmente lo invocan Eliza.bat o el comando /update, no tú):

    python Eliza.py instalar       descarga e instala la última versión
    python Eliza.py buscar         muestra la versión instalada y la disponible
    python Eliza.py actualizar     instala la última si hay una más nueva

Códigos de salida: 0 = ok/instalado, 1 = error, 2 = ya estaba al día.

Fuente: rama 'main' de github.com/jemaeld/ElizaV3 (público: no requiere
token). "Última versión" = último commit de esa rama. Si algún día el repo
se vuelve privado, se pide un token de solo lectura una vez y se guarda en
eliza_github_token.txt (o variable de entorno ELIZA_GITHUB_TOKEN).
"""

import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

REPO = "jemaeld/ElizaV3"
RAMA = "main"
API = "https://api.github.com"

HOME = os.path.dirname(os.path.abspath(__file__))
CARPETA_APP = os.path.join(HOME, "app")
ARCHIVO_VERSION = os.path.join(CARPETA_APP, "VERSION.json")
ARCHIVO_TOKEN = os.path.join(HOME, "eliza_github_token.txt")
CARPETA_DESCARGA = os.path.join(HOME, "_descarga")

# Archivos de la raíz del repo que también se actualizan en la instalación.
# Eliza.bat NO se sobrescribe directo (está corriendo): se deja como
# Eliza.bat.nuevo y el propio .bat se reemplaza en su siguiente vuelta.
ARCHIVOS_RAIZ = ("Eliza.py", "README.md")


class ErrorActualizacion(Exception):
    pass


# ---------------------------------------------------------
# GitHub

def _leer_token():
    token = os.environ.get("ELIZA_GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        with open(ARCHIVO_TOKEN, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _guardar_token(token):
    with open(ARCHIVO_TOKEN, "w", encoding="utf-8") as f:
        f.write(token.strip())


def _get(url, token, binario=False):
    cabeceras = {"User-Agent": "Eliza-Updater", "Accept": "application/vnd.github+json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    peticion = urllib.request.Request(url, headers=cabeceras)
    with urllib.request.urlopen(peticion, timeout=60) as r:
        datos = r.read()
    return datos if binario else json.loads(datos.decode("utf-8"))


def _get_con_token(url, binario=False, interactivo=True):
    """GET a la API; si responde 401/404 (repo privado sin token válido) pide un token una vez."""
    token = _leer_token()
    try:
        return _get(url, token, binario)
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403, 404):
            raise ErrorActualizacion(f"GitHub respondió {e.code}: {e.reason}") from e
        if e.code == 403 and token:
            raise ErrorActualizacion("GitHub rechazó el token (403). Revisa sus permisos o el límite de consultas.") from e
        if not interactivo:
            raise ErrorActualizacion(
                "No se pudo acceder al repositorio (¿privado?). Falta un token válido en eliza_github_token.txt.") from e

    print("\n[!] No se pudo acceder al repositorio. Si es PRIVADO necesitas un token de GitHub")
    print("    de solo lectura (Settings > Developer settings > Fine-grained tokens,")
    print(f"    repositorio {REPO}, permiso Contents: Read-only).")
    try:
        nuevo = input("    Pega el token (Enter para cancelar): ").strip()
    except EOFError:
        nuevo = ""
    if not nuevo:
        raise ErrorActualizacion("Sin token: no se puede descargar Eliza.")
    try:
        datos = _get(url, nuevo, binario)
    except urllib.error.HTTPError as e:
        raise ErrorActualizacion(f"El token no funcionó (GitHub respondió {e.code}).") from e
    _guardar_token(nuevo)
    print("[*] Token guardado en eliza_github_token.txt")
    return datos


def ultimo_disponible(interactivo=True):
    """Último commit de la rama: {'commit', 'fecha', 'mensaje'}."""
    try:
        info = _get_con_token(f"{API}/repos/{REPO}/commits/{RAMA}", interactivo=interactivo)
    except urllib.error.URLError as e:
        raise ErrorActualizacion(f"Sin conexión con GitHub: {e.reason}") from e
    return {
        "commit": info["sha"],
        "fecha": info["commit"]["committer"]["date"],
        "mensaje": info["commit"]["message"].splitlines()[0],
    }


def version_instalada():
    try:
        with open(ARCHIVO_VERSION, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------
# Instalación

def _es_repo_git():
    return os.path.isdir(os.path.join(HOME, ".git"))


def _borrar(ruta):
    """rmtree tolerante (archivos de solo lectura / ocultos en Windows)."""
    def _quitar_solo_lectura(func, path, _exc):
        try:
            os.chmod(path, 0o666)
            func(path)
        except OSError:
            pass
    if not os.path.isdir(ruta):
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(ruta, onexc=_quitar_solo_lectura)
    else:
        shutil.rmtree(ruta, onerror=_quitar_solo_lectura)


def instalar(disponible=None, interactivo=True):
    """
    Descarga el commit indicado (o el último) y reemplaza app/.
    El reemplazo es por renombrado (app -> app.old, nuevo -> app) para que
    un fallo a medias no deje la instalación rota.
    """
    if _es_repo_git():
        raise ErrorActualizacion("Esta carpeta es un repositorio git (modo desarrollo): usa 'git pull'.")

    disponible = disponible or ultimo_disponible(interactivo)
    commit = disponible["commit"]
    print(f"[*] Descargando Eliza {commit[:7]} ({disponible['mensaje']}) ...")
    try:
        contenido = _get_con_token(f"{API}/repos/{REPO}/zipball/{commit}", binario=True, interactivo=interactivo)
    except urllib.error.URLError as e:
        raise ErrorActualizacion(f"Fallo la descarga: {e.reason}") from e

    _borrar(CARPETA_DESCARGA)
    os.makedirs(CARPETA_DESCARGA)
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            z.extractall(CARPETA_DESCARGA)
    except zipfile.BadZipFile as e:
        raise ErrorActualizacion("El archivo descargado no es un zip válido.") from e

    # El zip de GitHub trae una sola carpeta raíz: <owner>-<repo>-<sha>/
    raices = [d for d in os.listdir(CARPETA_DESCARGA) if os.path.isdir(os.path.join(CARPETA_DESCARGA, d))]
    if len(raices) != 1:
        raise ErrorActualizacion("Estructura inesperada en la descarga.")
    origen = os.path.join(CARPETA_DESCARGA, raices[0])
    app_nueva = os.path.join(origen, "app")
    if not os.path.isfile(os.path.join(app_nueva, "eliza3.py")):
        raise ErrorActualizacion("La descarga no contiene app/eliza3.py.")

    with open(os.path.join(app_nueva, "VERSION.json"), "w", encoding="utf-8") as f:
        json.dump({"commit": commit, "fecha": disponible["fecha"], "mensaje": disponible["mensaje"],
                   "instalado": datetime.now().isoformat(timespec="seconds")}, f, indent=2, ensure_ascii=False)

    app_vieja = CARPETA_APP + ".old"
    _borrar(app_vieja)
    if os.path.exists(app_vieja):  # quedó algo bloqueado de una vez anterior
        app_vieja = f"{CARPETA_APP}.old{int(time.time())}"
    if os.path.isdir(CARPETA_APP):
        for intento in range(5):
            try:
                os.rename(CARPETA_APP, app_vieja)
                break
            except OSError:
                if intento == 4:
                    raise ErrorActualizacion(
                        "No se pudo reemplazar app/ (¿hay un archivo de app/ abierto en otro programa?).")
                time.sleep(1)
    shutil.move(app_nueva, CARPETA_APP)

    for nombre in ARCHIVOS_RAIZ:
        archivo = os.path.join(origen, nombre)
        if os.path.isfile(archivo):
            shutil.copy2(archivo, os.path.join(HOME, nombre))
    bat_nuevo = os.path.join(origen, "Eliza.bat")
    bat_actual = os.path.join(HOME, "Eliza.bat")
    if os.path.isfile(bat_nuevo) and (not os.path.isfile(bat_actual) or _distintos(bat_nuevo, bat_actual)):
        shutil.copy2(bat_nuevo, bat_actual + ".nuevo")

    _borrar(app_vieja)
    _borrar(CARPETA_DESCARGA)
    print(f"[*] Eliza {commit[:7]} instalada.")
    return disponible


def _distintos(a, b):
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() != fb.read()


def hay_actualizacion(interactivo=True):
    """Devuelve (instalada, disponible, hay_nueva)."""
    instalada = version_instalada()
    disponible = ultimo_disponible(interactivo)
    hay_nueva = not instalada or instalada.get("commit") != disponible["commit"]
    return instalada, disponible, hay_nueva


def describir(version):
    if not version:
        return "(no instalada)"
    fecha = (version.get("fecha") or "")[:10]
    return f"{version.get('commit', '')[:7]}  {fecha}  {version.get('mensaje', '')}"


# ---------------------------------------------------------
# Línea de comandos

def main(argv):
    accion = argv[1] if len(argv) > 1 else "buscar"
    try:
        if accion == "instalar":
            instalar()
            return 0
        if accion in ("buscar", "actualizar"):
            instalada, disponible, hay_nueva = hay_actualizacion()
            print(f"Instalada : {describir(instalada)}")
            print(f"Disponible: {describir(disponible)}")
            if not hay_nueva:
                print("[*] Ya tienes la última versión.")
                return 2
            if accion == "actualizar":
                instalar(disponible)
            return 0
        print(__doc__)
        return 1
    except ErrorActualizacion as e:
        print(f"[!] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
