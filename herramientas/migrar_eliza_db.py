"""
migrar_eliza_db.py -- migración ÚNICA de eliza.db al esquema 2.

Independiente de Eliza: solo usa la librería estándar de Python.

    python migrar_eliza_db.py "S:\\...\\[ ELIZA ]\\eliza.db"
    python migrar_eliza_db.py "S:\\...\\[ ELIZA ]"          (la carpeta también sirve)
    python migrar_eliza_db.py                               (pregunta la ruta)

Opciones:
    --simular   solo muestra lo que haría, no escribe nada
    --si        no pide confirmación (para pruebas)

Cambios en la tabla 'entradas':
    se quedan   id, categoria, nombre, accion, ip, comentario, creado, modificado
    nuevos      ultimo_abierto, ultimo_usuario   (vacíos hasta que se abra algo)
    se quitan   info, extra
    comentario  ACD: se conserva tal cual; su 'info' (IP | fecha del archivo) se descarta.
                VNC/APPS/otras: si el comentario está vacío toma el texto de 'info';
                si ambos tienen texto distinto quedan "comentario · info".
Además se elimina la tabla 'bitacora' (sin uso: la bitácora vive en JSON).

'accion' (la referencia a los ACD), 'ip', 'nombre', 'creado' y 'modificado'
se copian EXACTOS y se verifica renglón por renglón.

Seguridad:
    1. Respaldo completo antes de tocar nada: eliza.db.respaldo-AAAAMMDD-HHMMSS
    2. Bloqueo exclusivo: si otra PC está escribiendo, espera o se detiene.
    3. Todo en una sola transacción.
    4. Verificación contra el respaldo; si algo no cuadra, se restaura el respaldo.
    5. Reporte .txt junto a la base.
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime

VERSION_ORIGEN = 1
VERSION_DESTINO = 2
SEPARADOR = " · "

NUEVA_TABLA = """
CREATE TABLE entradas_nueva (
    id              INTEGER PRIMARY KEY,
    categoria       TEXT NOT NULL,
    nombre          TEXT NOT NULL,
    accion          TEXT NOT NULL DEFAULT '',
    ip              TEXT NOT NULL DEFAULT '',
    comentario      TEXT NOT NULL DEFAULT '',
    creado          TEXT NOT NULL,
    modificado      TEXT NOT NULL,
    ultimo_abierto  TEXT NOT NULL DEFAULT '',
    ultimo_usuario  TEXT NOT NULL DEFAULT ''
)"""
COPIADOS_EXACTOS = ('id', 'categoria', 'nombre', 'accion', 'ip', 'creado', 'modificado')


class Reporte:
    def __init__(self):
        self.lineas = []

    def __call__(self, texto=""):
        print(texto)
        self.lineas.append(texto)

    def guardar(self, ruta):
        try:
            with open(ruta, 'w', encoding='utf-8') as f:
                f.write("\n".join(self.lineas) + "\n")
            return True
        except OSError:
            return False


def unir_comentario(categoria, comentario, info):
    comentario = (comentario or '').strip()
    info = (info or '').strip()
    if categoria == 'acd' or not info:
        return comentario
    if not comentario or comentario.lower() == info.lower():
        return comentario or info
    return f"{comentario}{SEPARADOR}{info}"


def ruta_archivo_acd(accion, carpeta_db):
    """Devuelve (ruta_registrada, ruta_encontrada_o_None)."""
    texto = accion.strip()
    if texto.lower().startswith('open '):
        texto = texto[5:].strip()
    texto = texto.strip('"')
    registrada = texto if os.path.isabs(texto) else os.path.join(carpeta_db, texto)
    candidatas = [registrada, os.path.join(carpeta_db, '_acd_store', os.path.basename(texto.replace('\\', '/')))]
    for c in candidatas:
        if os.path.isfile(c):
            return registrada, c
    return registrada, None


def columnas(con, tabla):
    return [f[1] for f in con.execute(f"PRAGMA table_info({tabla})")]


def leer_entradas(con):
    con.row_factory = sqlite3.Row
    filas = [dict(f) for f in con.execute("SELECT * FROM entradas ORDER BY id")]
    con.row_factory = None
    return filas


def resolver_ruta(argumento):
    ruta = argumento.strip().strip('"')
    if os.path.isdir(ruta):
        ruta = os.path.join(ruta, 'eliza.db')
    return ruta


def pausa(interactivo):
    if interactivo:
        try:
            input("\nEnter para salir...")
        except EOFError:
            pass


def main(argv):
    simular = '--simular' in argv
    sin_preguntar = '--si' in argv
    args = [a for a in argv if not a.startswith('--')]
    interactivo = not sin_preguntar
    rep = Reporte()

    ruta = resolver_ruta(args[0]) if args else resolver_ruta(input("Ruta de eliza.db (o de su carpeta): "))
    if not os.path.isfile(ruta):
        print(f"No existe: {ruta}")
        pausa(interactivo)
        return 2
    carpeta = os.path.dirname(os.path.abspath(ruta))
    sello = datetime.now().strftime('%Y%m%d-%H%M%S')

    rep(f"Migración eliza.db -> esquema {VERSION_DESTINO}   ({datetime.now():%Y-%m-%d %H:%M:%S})")
    rep(f"Base: {ruta}")
    rep("")

    con = sqlite3.connect(ruta, timeout=30, isolation_level=None)
    try:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        cols = columnas(con, 'entradas')
        if version >= VERSION_DESTINO or 'ultimo_abierto' in cols:
            rep(f"La base YA está migrada (versión {version}). No se hizo nada.")
            pausa(interactivo)
            return 0
        if version != VERSION_ORIGEN or 'info' not in cols:
            rep(f"Versión inesperada ({version}, columnas {cols}). No se hizo nada.")
            pausa(interactivo)
            return 3
        integridad = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integridad != 'ok':
            rep(f"La base está dañada ({integridad}). No se hizo nada.")
            pausa(interactivo)
            return 4

        antes = leer_entradas(con)
        nuevas = []
        for e in antes:
            n = {c: e[c] for c in COPIADOS_EXACTOS}
            n['comentario'] = unir_comentario(e['categoria'], e['comentario'], e['info'])
            n['ultimo_abierto'] = ''
            n['ultimo_usuario'] = ''
            nuevas.append(n)

        # ---------- Resumen / simulación
        por_cat = {}
        for e in antes:
            por_cat[e['categoria']] = por_cat.get(e['categoria'], 0) + 1
        rep("Entradas: " + ", ".join(f"{c.upper()} {n}" for c, n in sorted(por_cat.items())) + f"  (total {len(antes)})")
        extra = [e for e in antes if (e.get('extra') or '{}').strip() not in ('{}', '')]
        rep(f"Campo 'extra' con datos: {len(extra)}" + ("" if not extra else "  ->  " + ", ".join(e['nombre'] for e in extra)))
        bit = con.execute("SELECT COUNT(*) FROM bitacora").fetchone()[0] if 'bitacora' in [
            t[0] for t in con.execute("SELECT name FROM sqlite_master WHERE type='table'")] else None
        if bit is not None:
            rep(f"Tabla 'bitacora': {bit} registro(s) -> se elimina" + ("" if bit == 0 else "  ¡TIENE DATOS!"))
        rep("")
        rep("Comentarios que cambian:")
        cambios = 0
        for e, n in zip(antes, nuevas):
            if n['comentario'] != e['comentario']:
                cambios += 1
                rep(f"  {e['categoria'].upper():<5} {e['nombre']:<28} '{e['comentario']}'  ->  '{n['comentario']}'")
        if not cambios:
            rep("  (ninguno)")
        descartados = [e for e in antes if e['categoria'] == 'acd' and e['info'].strip()]
        rep(f"ACD: se descarta 'info' (IP | fecha del archivo) en {len(descartados)} entrada(s); su IP ya está en 'ip'.")
        difieren = [e for e in descartados if e['info'].split('|')[0].strip() != e['ip'].strip()]
        for e in difieren:
            rep(f"  aviso: {e['nombre']}: la IP de info ('{e['info'].split('|')[0].strip()}') "
                f"no es igual a 'ip' ('{e['ip']}'). Se queda 'ip'.")
        rep("")
        rep("Archivos ACD referenciados:")
        faltan = 0
        for e in antes:
            if e['categoria'] != 'acd':
                continue
            registrada, encontrada = ruta_archivo_acd(e['accion'], carpeta)
            if encontrada is None:
                faltan += 1
                rep(f"  NO ENCONTRADO  {e['nombre']:<24} {registrada}")
        acd_total = por_cat.get('acd', 0)
        rep(f"  {acd_total - faltan} de {acd_total} encontrados en esta PC."
            + ("" if not faltan else "  (La referencia se conserva igual; solo es aviso.)"))
        rep("")

        if simular:
            rep("SIMULACIÓN: no se escribió nada.")
            rep.guardar(os.path.join(carpeta, f"migracion_esquema2-SIMULACION-{sello}.txt"))
            pausa(interactivo)
            return 0

        if not sin_preguntar:
            print("Cierra Eliza en TODAS las PCs antes de continuar.")
            if input("Escribe MIGRAR para continuar: ").strip().upper() != 'MIGRAR':
                rep("Cancelado por el usuario. No se escribió nada.")
                pausa(interactivo)
                return 5

        # ---------- Bloqueo exclusivo + respaldo
        try:
            con.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as e:
            rep(f"La base está en uso por otra PC ({e}). Cierra Eliza en todas y vuelve a intentar.")
            pausa(interactivo)
            return 6
        # Con el candado exclusivo nadie más puede escribir: copiar el archivo es seguro.
        # (con.backup() se bloquea si la misma conexión tiene el candado.)
        respaldo = f"{ruta}.respaldo-{sello}"
        try:
            shutil.copy2(ruta, respaldo)
            prueba = sqlite3.connect(f"file:{respaldo}?mode=ro", uri=True)
            try:
                ok = prueba.execute("PRAGMA integrity_check").fetchone()[0] == 'ok' and \
                    prueba.execute("SELECT COUNT(*) FROM entradas").fetchone()[0] == len(antes)
            finally:
                prueba.close()
            if not ok:
                raise OSError("la copia de respaldo no pasó la verificación")
        except (OSError, sqlite3.Error) as e:
            con.execute("ROLLBACK")
            rep(f"No se pudo crear el respaldo ({e}). No se hizo nada.")
            pausa(interactivo)
            return 6
        rep(f"Respaldo: {respaldo}")

        # ---------- Migración (una transacción)
        try:
            con.execute(NUEVA_TABLA)
            con.executemany(
                "INSERT INTO entradas_nueva (id, categoria, nombre, accion, ip, comentario, creado, modificado,"
                " ultimo_abierto, ultimo_usuario) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(n['id'], n['categoria'], n['nombre'], n['accion'], n['ip'], n['comentario'], n['creado'],
                  n['modificado'], n['ultimo_abierto'], n['ultimo_usuario']) for n in nuevas])
            con.execute("DROP TABLE entradas")
            con.execute("ALTER TABLE entradas_nueva RENAME TO entradas")
            con.execute("CREATE UNIQUE INDEX entradas_unicas ON entradas(categoria, nombre COLLATE NOCASE)")
            con.execute("DROP TABLE IF EXISTS bitacora")
            con.execute("INSERT INTO config (clave, valor) VALUES ('migrado_esquema2', ?)"
                        " ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                        (f'"{datetime.now().isoformat(timespec="seconds")}"',))
            con.execute(f"PRAGMA user_version={VERSION_DESTINO}")
            con.execute("COMMIT")
        except Exception as e:
            con.execute("ROLLBACK")
            rep(f"ERROR durante la migración: {e}. Se deshizo todo; la base quedó como estaba.")
            pausa(interactivo)
            return 7
        con.execute("VACUUM")

        # ---------- Verificación
        errores = []
        despues = {f['id']: f for f in leer_entradas(con)}
        if len(despues) != len(antes):
            errores.append(f"Había {len(antes)} entradas y quedaron {len(despues)}.")
        for e, n in zip(antes, nuevas):
            d = despues.get(e['id'])
            if d is None:
                errores.append(f"Falta la entrada id={e['id']} ({e['nombre']}).")
                continue
            for c in COPIADOS_EXACTOS:
                if d[c] != e[c]:
                    errores.append(f"id={e['id']} {e['nombre']}: '{c}' cambió.")
            if d['comentario'] != n['comentario']:
                errores.append(f"id={e['id']} {e['nombre']}: comentario distinto al esperado.")
        if con.execute("PRAGMA integrity_check").fetchone()[0] != 'ok':
            errores.append("integrity_check falló.")
        if columnas(con, 'entradas') != ['id', 'categoria', 'nombre', 'accion', 'ip', 'comentario', 'creado',
                                         'modificado', 'ultimo_abierto', 'ultimo_usuario']:
            errores.append(f"Columnas inesperadas: {columnas(con, 'entradas')}")
    finally:
        con.close()

    if errores:
        rep("")
        rep("VERIFICACIÓN FALLÓ:")
        for e in errores:
            rep(f"  {e}")
        shutil.copy2(respaldo, ruta)
        rep("Se restauró el respaldo: la base quedó como estaba.")
        rep.guardar(os.path.join(carpeta, f"migracion_esquema2-ERROR-{sello}.txt"))
        pausa(interactivo)
        return 8

    rep("")
    rep(f"OK: {len(antes)} entradas migradas y verificadas (accion, ip, nombre y fechas idénticas).")
    rep("Siguiente paso: abre Eliza y usa /update (o reinstala) para tener la versión que usa este formato.")
    ruta_rep = os.path.join(carpeta, f"migracion_esquema2-{sello}.txt")
    if rep.guardar(ruta_rep):
        print(f"Reporte: {ruta_rep}")
    pausa(interactivo)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
