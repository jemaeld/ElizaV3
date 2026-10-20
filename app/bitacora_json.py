"""
bitacora_json.py -- la bitácora de V3 se guarda EXACTAMENTE como en V2:

    <carpeta de datos>/bitacora/YYYY-MM-DD.json      (un archivo por día)

    [
        {
            "fecha": "2026-10-20",
            "hora": "07:05:00",
            "linea": "31",
            "estacion": "05",
            "prefijo": "",
            "auditor": "Juan",
            "tiempo": "15",
            "falla": "Sensor sucio",
            "ajuste": "Limpieza",
            "comentarios": ""
        }
    ]

- Mismas 10 claves, mismo orden, todo texto, json.dump(indent=4,
  ensure_ascii=False): idéntico byte a byte a lo que escribe V2.
- El archivo del día se crea al guardar su primer registro; cada registro
  nuevo se agrega al final de la lista del día de SU fecha.
- V2, V3 y otros programas pueden usar los mismos archivos a la vez.

Para convivir con otros programas que leen o escriben estos archivos:
- Antes de escribir se vuelve a leer el archivo (nunca se pisa con una copia
  vieja) y, si no se puede leer, NO se escribe.
- Escritura atómica (archivo temporal + reemplazo) con reintentos si otro
  programa lo tiene abierto en ese instante.
- Editar/borrar verifica que el registro siga igual en el archivo; si alguien
  lo cambió mientras tanto, se pide recargar en vez de sobrescribir.
"""

import json
import os
import re
import time

CARPETA = "bitacora"
CLAVES = ('fecha', 'hora', 'linea', 'estacion', 'prefijo', 'auditor', 'tiempo', 'falla', 'ajuste', 'comentarios')
REINTENTOS = 6


class ErrorBitacora(Exception):
    pass


def carpeta(base):
    ruta = os.path.join(base, CARPETA)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def ruta_dia(base, fecha):
    return os.path.join(carpeta(base), f"{fecha}.json")


def normalizar(registro):
    """Dict con las 10 claves de V2, en su orden, todo como texto."""
    return {c: str(registro.get(c, '') if registro.get(c) is not None else '') for c in CLAVES}


def _leer(ruta, estricto):
    if not os.path.exists(ruta):
        return []
    ultimo = None
    for intento in range(REINTENTOS):
        try:
            with open(ruta, 'r', encoding='utf-8-sig') as f:
                datos = json.load(f)
            break
        except PermissionError as e:       # otro programa lo tiene abierto: reintentar
            ultimo = e
            time.sleep(0.3 * (intento + 1))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            if estricto:
                raise ErrorBitacora(f"No se pudo leer {os.path.basename(ruta)}: {e}. No se modificó.") from e
            return []
    else:
        if estricto:
            raise ErrorBitacora(f"{os.path.basename(ruta)} está ocupado por otro programa: {ultimo}")
        return []
    if not isinstance(datos, list):
        if estricto:
            raise ErrorBitacora(f"{os.path.basename(ruta)} no contiene una lista. No se modificó.")
        return []
    return [r for r in datos if isinstance(r, dict)] if not estricto else datos


def _escribir(ruta, datos):
    temporal = ruta + ".tmp"
    with open(temporal, 'w', encoding='utf-8') as f:
        json.dump(datos, f, indent=4, ensure_ascii=False)
    ultimo = None
    for intento in range(REINTENTOS):
        try:
            os.replace(temporal, ruta)
            return
        except PermissionError as e:       # otro programa lo tiene abierto: reintentar
            ultimo = e
            time.sleep(0.3 * (intento + 1))
    try:
        os.remove(temporal)
    except OSError:
        pass
    raise ErrorBitacora(f"{os.path.basename(ruta)} está ocupado por otro programa; no se guardó: {ultimo}")


# ---------------------------------------------------------
def cargar_dia(base, fecha):
    """Registros del día (lista vacía si no hay archivo o no se puede leer)."""
    return _leer(ruta_dia(base, fecha), estricto=False)


def fechas_disponibles(base, limite=None):
    fechas = sorted((a[:-5] for a in os.listdir(carpeta(base))
                     if re.match(r'^\d{4}-\d{2}-\d{2}\.json$', a)), reverse=True)
    return fechas[:limite] if limite else fechas


def agregar(base, registro):
    """Agrega al final del archivo del día del registro. Devuelve la ruta."""
    registro = normalizar(registro)
    if not registro['fecha']:
        raise ErrorBitacora("El registro necesita fecha.")
    ruta = ruta_dia(base, registro['fecha'])
    datos = _leer(ruta, estricto=True)
    datos.append(registro)
    _escribir(ruta, datos)
    return ruta


def _ubicar(datos, indice, original):
    """Índice del registro 'original' (el que se vio en pantalla) o error si ya cambió."""
    if 0 <= indice < len(datos) and datos[indice] == original:
        return indice
    coincidencias = [i for i, r in enumerate(datos) if r == original]
    if len(coincidencias) == 1:
        return coincidencias[0]
    raise ErrorBitacora("El registro cambió en el archivo (¿otro programa o equipo?). Recarga e intenta de nuevo.")


def actualizar(base, fecha, indice, original, nuevo):
    """Reemplaza el registro. Si cambió la fecha, lo mueve al archivo de la nueva fecha."""
    nuevo = normalizar(nuevo)
    ruta = ruta_dia(base, fecha)
    datos = _leer(ruta, estricto=True)
    i = _ubicar(datos, indice, original)
    if nuevo['fecha'] == fecha:
        datos[i] = nuevo
        _escribir(ruta, datos)
        return
    agregar(base, nuevo)              # primero se guarda en el día nuevo...
    datos = _leer(ruta, estricto=True)
    del datos[_ubicar(datos, i, original)]
    _escribir(ruta, datos)            # ...y luego se quita del anterior


def borrar(base, fecha, indice, original):
    ruta = ruta_dia(base, fecha)
    datos = _leer(ruta, estricto=True)
    del datos[_ubicar(datos, indice, original)]
    _escribir(ruta, datos)


def rescatar_de_db(bd, base):
    """
    Una sola vez por base: la fase 2 de V3 guardaba la bitácora en eliza.db.
    Los registros capturados en V3 (equipo != 'V2') se agregan al JSON de su
    día si no están ya ahí; luego se vacía la tabla de la base (los que venían
    de V2 ya están en sus JSON). Devuelve cuántos registros se pasaron a JSON.
    """
    if bd.config_get('bitacora_en_json'):
        return 0
    pasados = 0
    with bd.conexion() as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM bitacora ORDER BY fecha, hora, id")]
    for fila in filas:
        if fila.get('equipo') == 'V2':
            continue
        registro = normalizar(fila)
        if registro not in [normalizar(r) for r in cargar_dia(base, registro['fecha'])]:
            agregar(base, registro)
            pasados += 1
    with bd.conexion(escritura=True) as con:
        con.execute("DELETE FROM bitacora")
    bd.config_set('bitacora_en_json', True)
    return pasados
