"""
acd_tools.py
------------
Lógica pura (sin GUI) para detectar, analizar y registrar proyectos ACD/L5K.

PROTECCIÓN DE LOS ARCHIVOS COPIADOS: como la carpeta de datos puede ser
compartida entre varios equipos, los ACD copiados con nombres reconocibles
corrían el riesgo de que alguien los borrara pensando que eran copias
redundantes. Por eso:
  1. Se guardan en _acd_store/ dentro de la carpeta de datos.
  2. El nombre de archivo se codifica en base64 (conservando la extensión,
     que Windows necesita para saber con qué programa abrirlo).
  3. La carpeta y cada archivo se marcan con el atributo OCULTO de Windows.

RUTAS PORTABLES: el 'action' de las entradas nuevas se guarda RELATIVO a la
carpeta de datos ('open "_acd_store/XXXX.ACD"'), así la carpeta se puede
mover o copiar sin romper nada. resolver_ruta_action() entiende ambos
formatos y además rescata entradas viejas con ruta absoluta a un
_acd_store/ de otra ubicación (las busca en el _acd_store/ actual).
"""

import os
import re
import shutil
import base64
import subprocess
import datetime as dt


VALID_EXTS = ('.acd', '.l5k')
NOMBRE_CARPETA_PROTEGIDA = "_acd_store"


def analyze_file(filepath):
    """Obtiene información básica de un archivo (nombre, fecha de modificación, ruta)."""
    try:
        mtime = os.path.getmtime(filepath)
    except OSError:
        return {}
    return {
        'file': os.path.basename(filepath),
        'latest_ts_str': dt.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'fullpath': filepath,
    }


def find_ip_in_string(text):
    """Encuentra la primera dirección IPv4 dentro de una cadena de texto."""
    match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', text)
    return match.group(0) if match else None


def buscar_archivos_acd(carpeta_origen):
    """
    Recorre recursivamente 'carpeta_origen' buscando archivos .acd/.l5k.
    Devuelve una lista de dicts: file, latest_ts_str, fullpath, ip_detectada.
    Omite el propio _acd_store/ (son copias ya registradas).
    """
    resultados = []
    for dirpath, dirnames, filenames in os.walk(carpeta_origen):
        dirnames[:] = [d for d in dirnames if d != NOMBRE_CARPETA_PROTEGIDA]
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in VALID_EXTS:
                info = analyze_file(os.path.join(dirpath, filename))
                if info:
                    info['ip_detectada'] = find_ip_in_string(info['file']) or ""
                    resultados.append(info)
    return resultados


# ---------------------------------------------------------
# Rutas de 'action'

def extraer_ruta_de_action(action):
    """De 'open "C:\\ruta\\archivo.ACD"' saca solo 'C:\\ruta\\archivo.ACD'."""
    texto = (action or '').strip()
    if texto.lower().startswith('open '):
        texto = texto[5:].strip()
    return texto.strip('"').strip()


def resolver_ruta_action(action, base_dir):
    """
    Devuelve la ruta real a abrir para un 'action' tipo 'open ...':
    - Relativa (p. ej. '_acd_store/XXX.ACD') -> se une a la carpeta de datos.
    - Absoluta que existe -> tal cual.
    - Absoluta que NO existe pero apunta a un '_acd_store' (de una carpeta de
      datos anterior) -> se busca el mismo archivo en el _acd_store/ actual.
    - Cualquier otra cosa (p. ej. 'ncpa.cpl') -> tal cual.
    """
    ruta = extraer_ruta_de_action(action)
    if not ruta:
        return ruta

    normal = ruta.replace('\\', '/')
    if normal.lower().startswith(NOMBRE_CARPETA_PROTEGIDA.lower() + '/'):
        return os.path.normpath(os.path.join(base_dir, ruta))

    if not os.path.exists(ruta):
        partes = [p.lower() for p in normal.split('/')]
        if NOMBRE_CARPETA_PROTEGIDA.lower() in partes:
            candidata = os.path.join(base_dir, NOMBRE_CARPETA_PROTEGIDA, os.path.basename(normal))
            if os.path.exists(candidata):
                return candidata
    return ruta


# ---------------------------------------------------------
# Almacenamiento protegido

def _codificar_nombre_archivo(nombre_legible, extension):
    """Nombre irreconocible (base64 URL-safe, sin '='), conservando la extensión real."""
    codificado = base64.urlsafe_b64encode(nombre_legible.encode('utf-8')).decode('ascii').rstrip('=')
    return f"{codificado}{extension}"


def _attrib(ruta, bandera):
    """Aplica '+h' / '-h' con attrib de Windows. No hace nada en otros SO."""
    if os.name != 'nt':
        return
    try:
        subprocess.run(['attrib', bandera, ruta], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        pass


def carpeta_protegida(base_dir):
    """_acd_store/ dentro de la carpeta de datos, marcada oculta."""
    ruta = os.path.join(base_dir, NOMBRE_CARPETA_PROTEGIDA)
    es_nueva = not os.path.isdir(ruta)
    os.makedirs(ruta, exist_ok=True)
    if es_nueva:
        _attrib(ruta, '+h')
    return ruta


def nombre_entrada(linea, estacion):
    return f"L{linea}E{estacion}"


def registrar_acd(bd, original_filepath, linea, estacion, ip):
    """
    Copia el archivo a _acd_store/ (nombre codificado + oculto) y agrega o
    ACTUALIZA la entrada ACD en la base. Si ya existe una entrada con el
    mismo nombre (L#E#), se reemplaza conservando su comentario.

    Devuelve (entrada, reemplazada, ruta_real, None) o (None, False, None, error).
    """
    import db as _db
    _, ext = os.path.splitext(original_filepath)
    nombre_archivo = _codificar_nombre_archivo(f"L{linea}E{estacion} - [{ip}]", ext)
    try:
        carpeta = carpeta_protegida(bd.carpeta)
        destino = os.path.join(carpeta, nombre_archivo)
        # Windows no deja sobrescribir un archivo OCULTO: se le quita antes.
        if os.path.exists(destino):
            _attrib(destino, '-h')
        shutil.copy2(original_filepath, destino)
        _attrib(destino, '+h')
    except Exception as e:
        return None, False, None, f"No se pudo copiar el archivo: {e}"

    info = analyze_file(destino)
    nombre = nombre_entrada(linea, estacion)
    entrada = {
        "categoria": "acd",
        "nombre": nombre,
        "accion": f'open "{NOMBRE_CARPETA_PROTEGIDA}/{nombre_archivo}"',
        "info": f"{ip} | {info.get('latest_ts_str', 'N/A')}",
        "ip": ip,
        "comentario": "",
    }
    try:
        existente = bd.buscar_entrada('acd', nombre)
        if existente:
            entrada['comentario'] = existente.get('comentario', '')
            bd.guardar_entrada(entrada, existente['id'])
        else:
            bd.guardar_entrada(entrada)
    except _db.ErrorDB as e:
        return None, False, destino, f"El archivo se copió, pero no se pudo guardar en la base: {e}"
    return entrada, existente is not None, destino, None


def reescanear(destino, ip):
    """
    Relee la fecha de modificación del archivo ya protegido y arma el 'info'
    de nuevo. Devuelve (info_string_nuevo, None) o (None, mensaje_error).
    """
    if not destino or not os.path.isfile(destino):
        return None, f"No se encontró el archivo: {destino or '(ruta vacía)'}"
    file_info = analyze_file(destino)
    return f"{ip} | {file_info.get('latest_ts_str', 'N/A')}", None
