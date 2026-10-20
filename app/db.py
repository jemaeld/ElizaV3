"""
db.py
------
Base de datos de Eliza V3: un solo archivo SQLite, eliza.db, dentro de la
carpeta de datos (local o compartida en red). Reemplaza a los JSON de V2
(config_json/*.json, bitacora/*.json, eliza_config.json).

Pensado para una carpeta de RED compartida por varios equipos:
- journal_mode=DELETE (WAL no es seguro sobre SMB/carpetas de red).
- Conexiones de vida corta: se abren, hacen su trabajo y se cierran, para
  no dejar el archivo bloqueado mientras Eliza está abierta.
- busy_timeout + reintentos si otro equipo está escribiendo en ese momento.
- Cada escritura es una transacción: o se guarda completa o no se guarda.

Los proyectos ACD NO van dentro de la base: siguen siendo archivos en
_acd_store/ (la base guarda la ruta, igual que V2).

Tablas:
    entradas  (VNC, APPS, ACD y cualquier categoría futura)
    bitacora  (registros de turno)
    config    (clave -> valor JSON)
    logix_registros (conjuntos de tags guardados del monitor)
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime

NOMBRE_DB = "eliza.db"
VERSION_ESQUEMA = 1
REINTENTOS = 5

ESQUEMA = """
CREATE TABLE IF NOT EXISTS entradas (
    id          INTEGER PRIMARY KEY,
    categoria   TEXT NOT NULL,                 -- 'vnc', 'apps', 'acd', ...
    nombre      TEXT NOT NULL,
    accion      TEXT NOT NULL DEFAULT '',      -- 'vnc <ip>' / 'open "<ruta>"'
    info        TEXT NOT NULL DEFAULT '',
    ip          TEXT NOT NULL DEFAULT '',
    comentario  TEXT NOT NULL DEFAULT '',
    extra       TEXT NOT NULL DEFAULT '{}',    -- campos adicionales (JSON)
    creado      TEXT NOT NULL,
    modificado  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS entradas_unicas ON entradas(categoria, nombre COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS bitacora (
    id          INTEGER PRIMARY KEY,
    fecha       TEXT NOT NULL,                 -- YYYY-MM-DD
    hora        TEXT NOT NULL,                 -- HH:MM:SS
    linea       TEXT NOT NULL DEFAULT '',
    estacion    TEXT NOT NULL DEFAULT '',
    prefijo     TEXT NOT NULL DEFAULT '',
    auditor     TEXT NOT NULL DEFAULT '',
    tiempo      TEXT NOT NULL DEFAULT '',
    falla       TEXT NOT NULL DEFAULT '',
    ajuste      TEXT NOT NULL DEFAULT '',
    comentarios TEXT NOT NULL DEFAULT '',
    equipo      TEXT NOT NULL DEFAULT '',      -- PC que capturó
    usuario     TEXT NOT NULL DEFAULT '',
    creado      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bitacora_fecha ON bitacora(fecha, hora);

CREATE TABLE IF NOT EXISTS config (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL                        -- JSON
);

CREATE TABLE IF NOT EXISTS logix_registros (
    id          INTEGER PRIMARY KEY,
    nombre      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    tags        TEXT NOT NULL,                 -- JSON: [{ip, polling_ms, tag, comentario}]
    modificado  TEXT NOT NULL
);
"""

CAMPOS_ENTRADA = ('categoria', 'nombre', 'accion', 'info', 'ip', 'comentario')
CAMPOS_BITACORA = ('fecha', 'hora', 'linea', 'estacion', 'prefijo', 'auditor', 'tiempo',
                   'falla', 'ajuste', 'comentarios', 'equipo', 'usuario')


class ErrorDB(Exception):
    """Error de la base de datos explicado para el usuario."""


class NombreRepetido(ErrorDB):
    pass


def ahora():
    return datetime.now().isoformat(timespec='seconds')


def ruta_db(carpeta_datos):
    return os.path.join(carpeta_datos, NOMBRE_DB)


def existe(carpeta_datos):
    return os.path.isfile(ruta_db(carpeta_datos))


class BaseDatos:
    def __init__(self, carpeta_datos):
        self.carpeta = carpeta_datos
        self.ruta = ruta_db(carpeta_datos)

    # ---------------------------------------------------------
    @contextmanager
    def conexion(self, escritura=False):
        """
        Conexión de vida corta. Con escritura=True abre una transacción
        inmediata (BEGIN IMMEDIATE) y reintenta si otro equipo tiene la base
        ocupada; hace commit al salir o rollback si hubo error.
        """
        ultimo_error = None
        for intento in range(REINTENTOS):
            con = None
            try:
                con = sqlite3.connect(self.ruta, timeout=10, isolation_level=None)
                con.row_factory = sqlite3.Row
                con.execute("PRAGMA journal_mode=DELETE")
                con.execute("PRAGMA synchronous=FULL")
                con.execute("PRAGMA foreign_keys=ON")
                if escritura:
                    con.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as e:
                ultimo_error = e
                if con is not None:
                    con.close()
                if 'locked' not in str(e).lower() and 'busy' not in str(e).lower():
                    raise ErrorDB(f"No se pudo abrir la base de datos ({self.ruta}): {e}") from e
                time.sleep(0.5 * (intento + 1))
        else:
            raise ErrorDB(f"La base de datos está ocupada por otro equipo. Intenta de nuevo. ({ultimo_error})")
        try:
            yield con
            if escritura:
                con.execute("COMMIT")
        except Exception:
            if escritura:
                try:
                    con.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise
        finally:
            con.close()

    def inicializar(self):
        """Crea el archivo y las tablas si no existen (idempotente)."""
        os.makedirs(self.carpeta, exist_ok=True)
        with self.conexion(escritura=True) as con:
            # Sentencia por sentencia: executescript() haría commit por su cuenta
            # y rompería la transacción.
            for sentencia in ESQUEMA.split(';'):
                if sentencia.strip():
                    con.execute(sentencia)
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                con.execute(f"PRAGMA user_version={VERSION_ESQUEMA}")
            elif version > VERSION_ESQUEMA:
                raise ErrorDB("La base de datos es de una versión más nueva de Eliza. Actualiza con /update.")
        return self

    # ---------------------------------------------------------
    # Entradas
    def entradas(self, categoria=None):
        sql = "SELECT * FROM entradas"
        args = ()
        if categoria:
            sql += " WHERE categoria = ?"
            args = (categoria.lower(),)
        with self.conexion() as con:
            return [_fila_a_dict(f) for f in con.execute(sql + " ORDER BY categoria, nombre COLLATE NOCASE", args)]

    def categorias(self):
        with self.conexion() as con:
            filas = con.execute("SELECT categoria, COUNT(*) n FROM entradas GROUP BY categoria ORDER BY categoria")
            return {f['categoria']: f['n'] for f in filas}

    def guardar_entrada(self, datos, id_entrada=None):
        """Crea (id_entrada=None) o actualiza una entrada. Devuelve el id."""
        valores = {c: str(datos.get(c, '') or '').strip() for c in CAMPOS_ENTRADA}
        valores['categoria'] = valores['categoria'].lower()
        if not valores['categoria'] or not valores['nombre']:
            raise ErrorDB("La entrada necesita categoría y nombre.")
        extra = json.dumps(datos.get('extra') or {}, ensure_ascii=False)
        try:
            with self.conexion(escritura=True) as con:
                if id_entrada is None:
                    cur = con.execute(
                        "INSERT INTO entradas (categoria, nombre, accion, info, ip, comentario, extra, creado, modificado)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (*[valores[c] for c in CAMPOS_ENTRADA], extra, ahora(), ahora()))
                    return cur.lastrowid
                if 'extra' not in datos:  # sin 'extra' se conservan los campos adicionales guardados
                    fila = con.execute("SELECT extra FROM entradas WHERE id=?", (id_entrada,)).fetchone()
                    extra = fila[0] if fila else extra
                con.execute(
                    "UPDATE entradas SET categoria=?, nombre=?, accion=?, info=?, ip=?, comentario=?, extra=?,"
                    " modificado=? WHERE id=?",
                    (*[valores[c] for c in CAMPOS_ENTRADA], extra, ahora(), id_entrada))
                return id_entrada
        except sqlite3.IntegrityError as e:
            raise NombreRepetido(
                f"Ya existe una entrada '{valores['nombre']}' en {valores['categoria'].upper()}.") from e

    def borrar_entrada(self, id_entrada):
        with self.conexion(escritura=True) as con:
            con.execute("DELETE FROM entradas WHERE id=?", (id_entrada,))

    def buscar_entrada(self, categoria, nombre):
        with self.conexion() as con:
            fila = con.execute("SELECT * FROM entradas WHERE categoria=? AND nombre=? COLLATE NOCASE",
                               (categoria.lower(), nombre.strip())).fetchone()
            return _fila_a_dict(fila) if fila else None

    # ---------------------------------------------------------
    # Bitácora
    def agregar_bitacora(self, registro):
        valores = {c: str(registro.get(c, '') or '') for c in CAMPOS_BITACORA}
        if not valores['fecha'] or not valores['hora']:
            raise ErrorDB("El registro de bitácora necesita fecha y hora.")
        with self.conexion(escritura=True) as con:
            cur = con.execute(
                f"INSERT INTO bitacora ({', '.join(CAMPOS_BITACORA)}, creado) VALUES ({', '.join('?' * len(CAMPOS_BITACORA))}, ?)",
                (*[valores[c] for c in CAMPOS_BITACORA], ahora()))
            return cur.lastrowid

    def bitacora_dia(self, fecha):
        with self.conexion() as con:
            return [dict(f) for f in con.execute("SELECT * FROM bitacora WHERE fecha=? ORDER BY hora, id", (fecha,))]

    def bitacora_fechas(self, limite=60):
        with self.conexion() as con:
            return [f[0] for f in con.execute(
                "SELECT DISTINCT fecha FROM bitacora ORDER BY fecha DESC LIMIT ?", (limite,))]

    def actualizar_bitacora(self, id_registro, registro):
        campos = [c for c in CAMPOS_BITACORA if c in registro]
        with self.conexion(escritura=True) as con:
            con.execute(f"UPDATE bitacora SET {', '.join(c + '=?' for c in campos)} WHERE id=?",
                        (*[str(registro[c] or '') for c in campos], id_registro))

    def borrar_bitacora(self, id_registro):
        with self.conexion(escritura=True) as con:
            con.execute("DELETE FROM bitacora WHERE id=?", (id_registro,))

    # ---------------------------------------------------------
    # Config
    def config(self):
        with self.conexion() as con:
            return {f['clave']: json.loads(f['valor']) for f in con.execute("SELECT clave, valor FROM config")}

    def config_get(self, clave, defecto=None):
        with self.conexion() as con:
            fila = con.execute("SELECT valor FROM config WHERE clave=?", (clave,)).fetchone()
            return json.loads(fila[0]) if fila else defecto

    def config_set(self, clave, valor):
        with self.conexion(escritura=True) as con:
            con.execute("INSERT INTO config (clave, valor) VALUES (?, ?)"
                        " ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                        (clave, json.dumps(valor, ensure_ascii=False)))

    # ---------------------------------------------------------
    # Registros de logix
    def logix_registros(self):
        with self.conexion() as con:
            return [{'nombre': f['nombre'], 'tags': json.loads(f['tags']), 'modificado': f['modificado']}
                    for f in con.execute("SELECT * FROM logix_registros ORDER BY nombre COLLATE NOCASE")]

    def guardar_logix_registro(self, nombre, tags):
        with self.conexion(escritura=True) as con:
            con.execute("INSERT INTO logix_registros (nombre, tags, modificado) VALUES (?,?,?)"
                        " ON CONFLICT(nombre) DO UPDATE SET tags=excluded.tags, modificado=excluded.modificado",
                        (nombre.strip(), json.dumps(tags, ensure_ascii=False), ahora()))

    def borrar_logix_registro(self, nombre):
        with self.conexion(escritura=True) as con:
            con.execute("DELETE FROM logix_registros WHERE nombre=?", (nombre,))

    # ---------------------------------------------------------
    def conteos(self):
        with self.conexion() as con:
            return {
                'entradas': con.execute("SELECT COUNT(*) FROM entradas").fetchone()[0],
                'bitacora': con.execute("SELECT COUNT(*) FROM bitacora").fetchone()[0],
                'config': con.execute("SELECT COUNT(*) FROM config").fetchone()[0],
            }


def _fila_a_dict(fila):
    d = dict(fila)
    try:
        d['extra'] = json.loads(d.get('extra') or '{}')
    except json.JSONDecodeError:
        d['extra'] = {}
    return d
