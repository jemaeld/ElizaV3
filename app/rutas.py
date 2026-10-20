"""
rutas.py
---------
Rutas de la instalación y de la carpeta de DATOS de Eliza V3.

Instalación (carpeta donde están Eliza.bat y Eliza.py):
    Eliza.bat, Eliza.py
    app/                el programa (este archivo vive aquí)
    .venv/
    datos/              carpeta de datos LOCAL
    eliza_local.json    qué carpeta de datos usa este equipo + huella de licencia
    eliza_error.log

Carpeta de datos (local o remota/compartida):
    eliza.db            base de datos SQLite (ver db.py)
    _acd_store/         proyectos ACD copiados (igual que V2)

La V3 se instala en una carpeta distinta a la V2: cada una tiene su propio
eliza_local.json. Pueden apuntar a la MISMA carpeta remota: V2 usa sus JSON
y V3 usa eliza.db, sin pisarse.
"""

import json
import os
import sys

NOMBRE_LOCAL = "eliza_local.json"
NOMBRE_DATOS_LOCALES = "datos"


def ruta_instalacion():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def carpeta_local():
    return os.path.join(ruta_instalacion(), NOMBRE_DATOS_LOCALES)


def ruta_archivo_local():
    return os.path.join(ruta_instalacion(), NOMBRE_LOCAL)


def leer_local():
    """Contenido de eliza_local.json ({} si no existe o está dañado)."""
    try:
        with open(ruta_archivo_local(), 'r', encoding='utf-8') as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def guardar_local(**cambios):
    """Actualiza claves de eliza_local.json conservando las demás."""
    datos = leer_local()
    datos.update(cambios)
    with open(ruta_archivo_local(), 'w', encoding='utf-8') as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)


def es_primer_arranque():
    return 'carpeta_eliza' not in leer_local()


def mismo_directorio(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def carpeta_remota():
    """Carpeta remota guardada, o None si este equipo usa la local."""
    carpeta = (leer_local().get('carpeta_eliza') or '').strip()
    if not carpeta or mismo_directorio(carpeta, carpeta_local()):
        return None
    return carpeta


def establecer_carpeta(remota):
    """None -> datos locales. Devuelve la carpeta que se usará."""
    if not remota or mismo_directorio(remota, carpeta_local()):
        guardar_local(carpeta_eliza="")
        os.makedirs(carpeta_local(), exist_ok=True)
        return carpeta_local()
    guardar_local(carpeta_eliza=remota)
    return remota


def remota_disponible(carpeta):
    try:
        return os.path.isdir(carpeta)
    except OSError:
        return False


def resolver_carpeta():
    """
    (carpeta, remota_caida):
      remota configurada y disponible -> (remota, None)
      remota configurada NO disponible -> (None, remota)  [la interfaz decide]
      sin remota                       -> (local, None)
    """
    remota = carpeta_remota()
    if remota:
        return (remota, None) if remota_disponible(remota) else (None, remota)
    os.makedirs(carpeta_local(), exist_ok=True)
    return carpeta_local(), None
