"""
alta.py -- /add: agregar entradas VNC/APPS/DIR desde un archivo .vnc, .lnk o .exe,
o una carpeta (Ctrl+S en el explorador) que se abrirá en el Explorador de Windows.

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
        ruta = await app.push_screen_wait(ExploradorArchivos(
            "Agregar: archivo VNC / APPS (Enter) o carpeta DIR (Ctrl+S)", EXTENSIONES, carpeta,
            elegir_carpeta=True, texto_carpeta="agregar la carpeta"))
        if not ruta:
            return agregadas
        if isinstance(ruta, dict):   # Ctrl+S: la carpeta misma
            ruta = ruta['carpeta']
            carpeta = os.path.dirname(ruta.rstrip('\\/')) or ruta
            datos, error = add_tools.datos_carpeta(ruta), None
        else:
            carpeta = os.path.dirname(ruta)
            datos, error = await app.run_in_thread(add_tools.analizar_archivo, ruta)
        if error:
            app.aviso(error)
            continue
        es_vnc = datos['categoria'] == 'VNC'
        campos = [Campo('nombre', "Nombre", datos['nombre_sugerido'], obligatorio=True),
                  Campo('ip', "IP", datos['ip'], obligatorio=es_vnc),
                  Campo('comentario', "Comentario", "", ayuda="qué equipo es, ej. Estación del Robot")]
        if not es_vnc:
            campos.insert(1, Campo('accion', "Acción", datos['action'],
                                   ayuda='open "S:\\ruta\\carpeta"' if datos['categoria'] == 'DIR' else ''))
            campos = [c for c in campos if c.clave != 'ip']
        resultado = await app.push_screen_wait(Formulario(
            f"Agregar a {datos['categoria']}", campos, mensaje=os.path.basename(ruta)))
        if resultado:
            accion = f"vnc {resultado['ip']}" if es_vnc else resultado['accion']
            try:
                bd.guardar_entrada({'categoria': datos['categoria'].lower(), 'nombre': resultado['nombre'],
                                    'accion': accion,
                                    'ip': resultado.get('ip', ''), 'comentario': resultado['comentario']})
                agregadas += 1
                app.ok(f"Agregado '{resultado['nombre']}' a {datos['categoria']}")
            except db.ErrorDB as e:
                app.aviso(str(e))
        if not await app.push_screen_wait(Confirmar("Agregar", "¿Agregar otro archivo o carpeta?",
                                                    si="Sí, otro", no="Terminar")):
            return agregadas
