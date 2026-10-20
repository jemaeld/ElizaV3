"""
alta.py -- /add: agregar entradas VNC/APPS desde un archivo .vnc, .lnk o .exe.

1. Explorador de archivos en consola (sin ventanas de Windows).
2. Se detecta categoría, IP (de .vnc) y destino real (de .lnk).
3. Formulario con lo detectado ya lleno: solo se completa lo que falta.
4. Se ofrece agregar otro archivo de la misma carpeta.
"""

import os

import add_tools
import db
from ui.explorador import ExploradorArchivos
from ui.formulario import Campo, Formulario
from ui.modales import Confirmar

EXTENSIONES = ('.vnc', '.lnk', '.exe')


async def alta(app, bd, inicio=None):
    """Corre el flujo completo. Devuelve cuántas entradas se agregaron."""
    agregadas = 0
    carpeta = inicio
    while True:
        ruta = await app.push_screen_wait(ExploradorArchivos("Agregar VNC / APPS: elige el archivo",
                                                             EXTENSIONES, carpeta))
        if not ruta:
            return agregadas
        carpeta = os.path.dirname(ruta)
        datos, error = await app.run_in_thread(add_tools.analizar_archivo, ruta)
        if error:
            app.aviso(error)
            continue
        es_vnc = datos['categoria'] == 'VNC'
        campos = [Campo('nombre', "Nombre", datos['nombre_sugerido'], obligatorio=True),
                  Campo('ip', "IP", datos['ip'], obligatorio=es_vnc),
                  Campo('info', "Info", ""),
                  Campo('comentario', "Comentario", "")]
        if not es_vnc:
            campos.insert(1, Campo('accion', "Acción", datos['action']))
            campos = [c for c in campos if c.clave != 'ip']
        resultado = await app.push_screen_wait(Formulario(
            f"Agregar a {datos['categoria']}", campos, mensaje=os.path.basename(ruta)))
        if resultado:
            accion = f"vnc {resultado['ip']}" if es_vnc else resultado['accion']
            try:
                bd.guardar_entrada({'categoria': datos['categoria'].lower(), 'nombre': resultado['nombre'],
                                    'accion': accion, 'info': resultado['info'],
                                    'ip': resultado.get('ip', ''), 'comentario': resultado['comentario']})
                agregadas += 1
                app.ok(f"Agregado '{resultado['nombre']}' a {datos['categoria']}")
            except db.ErrorDB as e:
                app.aviso(str(e))
        if not await app.push_screen_wait(Confirmar("Agregar", "¿Agregar otro archivo?",
                                                    si="Sí, otro", no="Terminar")):
            return agregadas
