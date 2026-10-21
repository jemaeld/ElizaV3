"""
scan_acd.py -- /scan_acd [carpeta]: busca proyectos ACD/L5K y los registra.

Sin carpeta abre el explorador (igual que /add) mostrando carpetas y
archivos .ACD/.L5K con su fecha:
    Ctrl+S  buscar en la carpeta resaltada (y subcarpetas) -> tabla de abajo,
            del más reciente al más viejo
    Enter   sobre un archivo: registrarlo directo
Recuerda la última carpeta usada en esta PC.

Teclas en la tabla de resultados:
    Enter   registrar en la base (pide Línea, Estación e IP; la IP detectada ya viene)
    a       abrir el archivo           u   abrir su ubicación
    o       ordenar por fecha / nombre s   escanear otra carpeta
    /       filtrar                    Esc volver

El archivo se copia a _acd_store/ de la carpeta de datos (nombre codificado y
oculto, igual que V2) y la entrada guarda la ruta relativa. Si ya existe
L#E#, pregunta y la actualiza conservando su comentario.
"""

import os

from textual import work
from textual.binding import Binding

import acd_tools
import rutas
from ui.explorador import ExploradorArchivos
from ui.formulario import Campo, Formulario
from ui.modales import Confirmar
from ui.pantalla import PantallaTabla


def _truncar_ruta(ruta):
    partes = os.path.normpath(ruta).split(os.sep)
    return os.path.join("…", *partes[-3:]) if len(partes) > 3 else ruta


class PantallaScanACD(PantallaTabla):
    COLUMNAS = [('archivo', "ARCHIVO", 40), ('fecha', "ÚLTIMA FECHA", 20), ('ip', "IP DETECTADA", 16),
                ('ubicacion', "UBICACIÓN", None)]
    ACCION_ENTER = "registrar"
    BINDINGS = PantallaTabla.BINDINGS + [
        Binding("enter", "registrar", "Registrar"),
        Binding("a", "abrir", "Abrir archivo"),
        Binding("u", "ubicacion", "Abrir ubicación"),
        Binding("o", "orden", "Orden"),
        Binding("s", "otra_carpeta", "Explorar"),
    ]

    def __init__(self, bd, carpeta=None):
        super().__init__()
        self.bd = bd
        self.carpeta = carpeta
        self.resultados = []
        self.por_fecha = True
        self.hubo_cambios = False

    def despues_de_montar(self):
        if self.carpeta and os.path.isdir(self.carpeta):
            self.escanear(self.carpeta)
        else:
            self.action_otra_carpeta()

    def filas(self):
        lista = sorted(self.resultados, key=lambda r: r['latest_ts_str'], reverse=True) if self.por_fecha \
            else sorted(self.resultados, key=lambda r: r['file'].lower())
        for r in lista:
            yield r['fullpath'], [r['file'], r['latest_ts_str'], r['ip_detectada'],
                                  _truncar_ruta(os.path.dirname(r['fullpath']))]

    def al_refrescar(self):
        self.titulo(f"SCAN ACD  ·  {self.carpeta or '(sin carpeta)'}  ·  {self.tabla.row_count} archivo(s)  ·  "
                    f"orden: {'fecha' if self.por_fecha else 'nombre'}")

    @work(exclusive=True, group="scan", exit_on_error=False)
    async def action_otra_carpeta(self):
        inicio = self.carpeta or rutas.leer_local().get('ultima_carpeta_acd') or None
        eleccion = await self.app.push_screen_wait(ExploradorArchivos(
            "Scan ACD: elige la carpeta (Ctrl+S) o el archivo (Enter)", acd_tools.VALID_EXTS, inicio,
            mostrar_fechas=True, elegir_carpeta=True))
        if not eleccion:
            if not self.resultados:
                self.estado("Sin carpeta. Presiona 's' para explorar.")
            return
        if isinstance(eleccion, dict):
            self.escanear(eleccion['carpeta'])
            return
        # Un archivo: se muestra en la tabla y se registra directo.
        self._recordar(os.path.dirname(eleccion))
        info = acd_tools.analyze_file(eleccion)
        if not info:
            self.estado(f"No se pudo leer {eleccion}", error=True)
            return
        info['ip_detectada'] = acd_tools.find_ip_in_string(info['file']) or ""
        self.carpeta = os.path.dirname(eleccion)
        self.resultados = [info]
        self.refrescar(conservar=False)
        await self._registrar(info)

    def _recordar(self, carpeta):
        try:
            rutas.guardar_local(ultima_carpeta_acd=carpeta)
        except OSError:
            pass

    @work(exclusive=True, group="scan", exit_on_error=False)
    async def escanear(self, carpeta):
        self.carpeta = carpeta
        self._recordar(carpeta)
        self.estado("Buscando… (las carpetas de red pueden tardar)")
        self.resultados = await self.app.run_in_thread(acd_tools.buscar_archivos_acd, carpeta)
        self.refrescar(conservar=False)
        self.estado(f"{len(self.resultados)} archivo(s) encontrados." if self.resultados
                    else f"No se encontraron archivos {', '.join(acd_tools.VALID_EXTS)}.")

    def _actual(self):
        clave = self.fila_actual()
        return next((r for r in self.resultados if r['fullpath'] == clave), None)

    def action_orden(self):
        self.por_fecha = not self.por_fecha
        self.refrescar()

    def _abrir(self, ruta):
        try:
            os.startfile(ruta)
        except OSError as e:
            self.estado(f"No se pudo abrir: {e}", error=True)

    def action_abrir(self):
        r = self._actual()
        if r:
            self._abrir(r['fullpath'])

    def action_ubicacion(self):
        r = self._actual()
        if r:
            self._abrir(os.path.dirname(r['fullpath']))

    @work(exclusive=True, group="scan", exit_on_error=False)
    async def action_registrar(self):
        r = self._actual()
        if r:
            await self._registrar(r)

    async def _registrar(self, r):
        datos = await self.app.push_screen_wait(Formulario(
            "Registrar proyecto ACD",
            [Campo('linea', "Línea", obligatorio=True), Campo('estacion', "Estación", obligatorio=True),
             Campo('ip', "IP principal", r['ip_detectada'], obligatorio=True)],
            mensaje=f"{r['file']}\n{r['latest_ts_str']}", texto_guardar="registrar"))
        if not datos:
            return
        nombre = acd_tools.nombre_entrada(datos['linea'], datos['estacion'])
        if self.bd.buscar_entrada('acd', nombre) and not await self.app.push_screen_wait(Confirmar(
                "Ya existe", f"Ya hay una entrada '{nombre}' en ACD.\n¿Reemplazarla con este archivo? "
                "(se conserva su comentario)", si="Reemplazar", no="Cancelar")):
            return
        self.estado("Copiando a _acd_store…")
        entrada, reemplazada, destino, error = await self.app.run_in_thread(
            acd_tools.registrar_acd, self.bd, r['fullpath'], datos['linea'], datos['estacion'], datos['ip'])
        if error:
            self.estado(error, error=True)
            return
        self.hubo_cambios = True
        self.estado(f"{'Actualizada' if reemplazada else 'Registrada'} {entrada['nombre']} → {destino}")

    def action_cerrar(self):
        self.dismiss(self.hubo_cambios)

