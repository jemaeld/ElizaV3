"""
migrar_v2.py -- utilidad de UN SOLO USO: pasa los datos de Eliza V2 (JSON) a
la base de Eliza V3 (eliza.db).

    python app\\migrar_v2.py "S:\\...\\[ ELIZA ]"              migra (eliza.db en la misma carpeta)
    python app\\migrar_v2.py "<carpeta V2>" --simular         solo muestra qué haría
    python app\\migrar_v2.py "<carpeta V2>" --destino <dir>   eliza.db en otra carpeta
    opciones: --reemplazar (si ya hay un eliza.db con datos; se respalda)
              --omitir-danados (sigue aunque algún JSON no se pueda leer)

También la ofrece Eliza V3 en su primer arranque si la carpeta de datos
elegida tiene datos de V2 y todavía no tiene eliza.db.

Qué migra (los archivos de V2 NO se modifican):
  config_json/*.json   -> tabla entradas (categoría = nombre del archivo)
                          name/action/ip/comentario; 'info' se une a comentario
                          (en ACD se descarta: era 'IP | fecha'); otras claves se descartan
  bitacora/*.json      -> NO se migra: V3 usa los mismos archivos JSON (mismo formato)
  eliza_config.json    -> tabla config (vnc_password, vnc_puerto, ...)
  _acd_store/          -> se queda donde está: las entradas ACD conservan su ruta

Nombres repetidos dentro de una categoría (V2 los permitía) se renombran
"Nombre (2)", "Nombre (3)"... y se listan en el reporte.

Seguridad: la base nueva se arma en un archivo temporal y solo al final
reemplaza a eliza.db; luego se verifican los conteos. El reporte queda en
la carpeta destino (migracion_v2_<fecha>.txt).
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

import db

CLAVES_ENTRADA = {'name': 'nombre', 'action': 'accion', 'info': 'info', 'ip': 'ip', 'comentario': 'comentario'}


def unir_comentario(categoria, comentario, info):
    """Misma regla que herramientas/migrar_eliza_db.py."""
    comentario, info = (comentario or '').strip(), (info or '').strip()
    if categoria == 'acd' or not info:
        return comentario
    if not comentario or comentario.lower() == info.lower():
        return comentario or info
    return f"{comentario} · {info}"
CONFIG_OBSOLETA = ('carpeta_destino_acd',)


class ErrorMigracion(Exception):
    pass


class Reporte:
    def __init__(self):
        self.lineas = []
        self.avisos = []

    def info(self, texto):
        self.lineas.append(texto)

    def aviso(self, texto):
        self.avisos.append(texto)
        self.lineas.append(f"[!] {texto}")

    def texto(self):
        return "\n".join(self.lineas)


def es_carpeta_v2(carpeta):
    return os.path.isdir(os.path.join(carpeta, 'config_json'))


def _leer_json(ruta, reporte, omitir_danados):
    try:
        with open(ruta, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        mensaje = f"No se pudo leer {ruta}: {e}"
        if omitir_danados:
            reporte.aviso(mensaje + " (omitido)")
            return None
        raise ErrorMigracion(mensaje + "\nCorrígelo o usa 'omitir dañados'.") from e


def leer_v2(origen, reporte, omitir_danados=False):
    """Lee todo lo de V2 y lo deja listo para insertar. No escribe nada."""
    if not es_carpeta_v2(origen):
        raise ErrorMigracion(f"No parece una carpeta de datos de Eliza V2 (falta config_json\\): {origen}")

    entradas = []
    carpeta_cfg = os.path.join(origen, 'config_json')
    for archivo in sorted(os.listdir(carpeta_cfg)):
        if not archivo.lower().endswith('.json'):
            continue
        categoria = archivo[:-5].lower()
        datos = _leer_json(os.path.join(carpeta_cfg, archivo), reporte, omitir_danados)
        if datos is None:
            continue
        if not isinstance(datos, list):
            reporte.aviso(f"config_json/{archivo} no es una lista; se omitió.")
            continue
        usados = {}
        sin_nombre = 0
        descartadas = set()
        for item in datos:
            if not isinstance(item, dict) or not str(item.get('name', '')).strip():
                sin_nombre += 1
                continue
            entrada = {'categoria': categoria}
            for clave, valor in item.items():
                if clave in CLAVES_ENTRADA:
                    entrada[CLAVES_ENTRADA[clave]] = str(valor if valor is not None else '').strip()
                else:
                    descartadas.add(clave)
            entrada['comentario'] = unir_comentario(categoria, entrada.get('comentario'), entrada.pop('info', ''))
            base = entrada['nombre']
            n = usados.get(base.lower(), 0) + 1
            usados[base.lower()] = n
            if n > 1:
                entrada['nombre'] = f"{base} ({n})"
                reporte.aviso(f"{categoria.upper()}: nombre repetido '{base}' -> '{entrada['nombre']}'")
            entradas.append(entrada)
        if descartadas:
            reporte.aviso(f"config_json/{archivo}: campos sin uso en V3, no se migran: {', '.join(sorted(descartadas))}")
        if sin_nombre:
            reporte.aviso(f"config_json/{archivo}: {sin_nombre} entrada(s) sin 'name' se omitieron.")
        reporte.info(f"{categoria.upper():<6} {sum(1 for e in entradas if e['categoria'] == categoria):>5} entradas")

    carpeta_bit = os.path.join(origen, 'bitacora')
    dias = [a for a in os.listdir(carpeta_bit) if re.match(r'^\d{4}-\d{2}-\d{2}\.json$', a)] \
        if os.path.isdir(carpeta_bit) else []
    reporte.info(f"BITÁCORA {len(dias):>4} día(s): se queda en bitacora\\*.json (V3 usa los mismos archivos)")
    bitacora = []

    config = {}
    ruta_cfg = os.path.join(origen, 'eliza_config.json')
    if os.path.isfile(ruta_cfg):
        datos = _leer_json(ruta_cfg, reporte, omitir_danados) or {}
        for clave, valor in (datos.items() if isinstance(datos, dict) else []):
            if clave in CONFIG_OBSOLETA:
                reporte.info(f"config '{clave}' es de V2 y ya no se usa; no se migra.")
                continue
            config[clave] = valor
    reporte.info(f"CONFIG {len(config):>5} clave(s): {', '.join(sorted(config)) or '-'}")
    if 'vnc_password' not in config:
        reporte.aviso("No hay vnc_password en V2: Eliza V3 la pedirá como contraseña de acceso al primer arranque.")

    return {'entradas': entradas, 'bitacora': bitacora, 'config': config}


def _contar_entradas(ruta):
    """Cuántas entradas tiene una base existente (de cualquier versión del esquema)."""
    import sqlite3
    try:
        con = sqlite3.connect(ruta)
        try:
            return con.execute("SELECT COUNT(*) FROM entradas").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def migrar(origen, destino=None, simular=False, reemplazar=False, omitir_danados=False):
    """Devuelve el Reporte. Lanza ErrorMigracion si no se puede (sin dejar nada a medias)."""
    destino = destino or origen
    reporte = Reporte()
    reporte.info(f"Migración Eliza V2 -> V3  ({datetime.now():%Y-%m-%d %H:%M:%S})")
    reporte.info(f"Origen : {origen}")
    reporte.info(f"Destino: {db.ruta_db(destino)}")
    reporte.info("")

    datos = leer_v2(origen, reporte, omitir_danados)

    if db.existe(destino):
        conteos = _contar_entradas(db.ruta_db(destino))
        if conteos:
            if not reemplazar:
                raise ErrorMigracion(
                    f"Ya existe una base con datos en {db.ruta_db(destino)} ({conteos} entradas). "
                    "La migración es de un solo uso; usa 'reemplazar' solo si quieres empezar de nuevo.")
            if not simular:
                respaldo = db.ruta_db(destino) + f".respaldo-{datetime.now():%Y%m%d-%H%M%S}"
                shutil.copy2(db.ruta_db(destino), respaldo)
                reporte.info(f"Base anterior respaldada en {respaldo}")

    if simular:
        reporte.info("")
        reporte.info("SIMULACIÓN: no se escribió nada.")
        return reporte

    temporal_dir = os.path.join(destino, '_migrando_v3')
    shutil.rmtree(temporal_dir, ignore_errors=True)
    os.makedirs(temporal_dir)
    try:
        bd = db.BaseDatos(temporal_dir).inicializar()
        with bd.conexion(escritura=True) as con:
            ahora = db.ahora()
            for e in datos['entradas']:
                con.execute(
                    "INSERT INTO entradas (categoria, nombre, accion, ip, comentario, creado, modificado)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (e['categoria'], e['nombre'], e.get('accion', ''), e.get('ip', ''),
                     e.get('comentario', ''), ahora, ahora))
            for clave, valor in datos['config'].items():
                con.execute("INSERT INTO config (clave, valor) VALUES (?, ?)",
                            (clave, json.dumps(valor, ensure_ascii=False)))
            con.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES ('bitacora_en_json', 'true')")
            con.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES ('migrado_desde_v2', ?)",
                        (json.dumps({'origen': origen, 'fecha': ahora}, ensure_ascii=False),))

        conteos = bd.conteos()
        if conteos['entradas'] != len(datos['entradas']):
            raise ErrorMigracion(f"Verificación fallida: se esperaban {len(datos['entradas'])} entradas y la base "
                                 f"tiene {conteos['entradas']}. No se instaló la base.")
        os.replace(bd.ruta, db.ruta_db(destino))
    finally:
        shutil.rmtree(temporal_dir, ignore_errors=True)

    reporte.info("")
    reporte.info(f"OK: {conteos['entradas']} entradas y {len(datos['config'])} clave(s) de configuración. "
                 "La bitácora sigue en sus archivos JSON.")
    reporte.info("Los archivos de V2 no se modificaron; V2 puede seguir usándolos.")
    ruta_reporte = os.path.join(destino, f"migracion_v2_{datetime.now():%Y%m%d-%H%M%S}.txt")
    try:
        with open(ruta_reporte, 'w', encoding='utf-8') as f:
            f.write(reporte.texto() + "\n")
        reporte.info(f"Reporte guardado en {ruta_reporte}")
    except OSError:
        pass
    return reporte


def main(argv=None):
    p = argparse.ArgumentParser(description="Migra los datos de Eliza V2 (JSON) a Eliza V3 (eliza.db).")
    p.add_argument('origen', help="Carpeta de datos de V2 (la que tiene config_json\\)")
    p.add_argument('--destino', help="Carpeta donde crear eliza.db (por defecto, la misma)")
    p.add_argument('--simular', action='store_true')
    p.add_argument('--reemplazar', action='store_true')
    p.add_argument('--omitir-danados', action='store_true')
    a = p.parse_args(argv)
    try:
        reporte = migrar(a.origen, a.destino, a.simular, a.reemplazar, a.omitir_danados)
    except (ErrorMigracion, db.ErrorDB, OSError) as e:
        print(f"[!] {e}")
        return 1
    print(reporte.texto())
    return 0


if __name__ == "__main__":
    sys.exit(main())
