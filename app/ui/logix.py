"""
logix.py -- /logix [ip|nombre]: MONITOR DE VARIABLES Allen-Bradley.

    CONEX | IP | POLL | TAG | VALOR | ESCRITURA | COMENTARIO

Teclas:
    a           agregar tag (asistente con programas/tags leídos del PLC)
    Enter / w   escribir en la variable 1..N veces (ventana de escritura)
    e           editar el tag de la fila (asistente)
    Espacio     conectar / desconectar la fila
    Supr        quitar la fila           s   detener todas las escrituras
    g           guardar el conjunto de tags en la base (con nombre)
    l           cargar un conjunto guardado (o importar un .json de Eliza V2)
    /           filtrar                  Esc cerrar (desconecta todo)

La línea de estado muestra el detalle (error exacto, escritura) de la fila
seleccionada. La fila se pinta en ámbar mientras escribe.
"""

import os

from rich.text import Text
from textual import work
from textual.binding import Binding

import db
import logix_explorador
import logix_monitor as lm
import logix_tools
from ui.explorador import ExploradorArchivos
from ui.logix_escritura import VentanaEscritura
from ui.logix_tag import AsistenteTag
from ui.modales import Confirmar, Menu, PedirTexto
from ui.pantalla import PantallaTabla

SIMBOLOS = {lm.OFF: ("○ OFF", "#ffcc00"), lm.CONECTANDO: ("… ", "#ffcc00"),
            lm.ON: ("● ON", "#00ff00"), lm.ERROR: ("× ERR", "#ff5555")}


class PantallaLogix(PantallaTabla):
    COLUMNAS = [('conexion', "CONEX", 7), ('ip', "IP", 16), ('polling', "POLL", 6), ('tag', "TAG", 42),
                ('valor', "VALOR", 18), ('escritura', "ESCRITURA", 22), ('comentario', "COMENTARIO", None)]
    ACCION_ENTER = "escribir"
    BINDINGS = PantallaTabla.BINDINGS + [
        Binding("a", "agregar", "Agregar"),
        Binding("e", "editar", "Editar tag"),
        Binding("space", "conectar", "Conectar", key_display="Espacio"),
        Binding("w", "escribir", "Escribir", show=False),
        Binding("delete", "quitar", "Quitar", key_display="Supr"),
        Binding("s", "detener", "Detener escrituras"),
        Binding("g", "guardar", "Guardar"),
        Binding("l", "cargar", "Cargar"),
    ]

    def __init__(self, bd, ip_inicial="", fabrica_plc=None):
        super().__init__()
        self.bd = bd
        self.ip_inicial = ip_inicial
        self.monitor = lm.MonitorLogix(fabrica_plc)
        self.explorador = logix_explorador.ExploradorPLC(fabrica_plc)
        self.ultima_ip = ip_inicial
        self._ids_pintados = []

    # ---------------------------------------------------------
    def filas(self):
        for f in self.monitor.instantanea():
            yield f['id'], self._celdas(f)

    def _celdas(self, f):
        simbolo, color = SIMBOLOS[f['conexion']]
        t = f['trabajo']
        escribiendo = t['estado'] == logix_tools.WORKING
        estilo = "bold #ffe066 on #4a3b00" if escribiendo else ""
        escritura = t['columna'] if (t['corrida'] or t['estado'] != logix_tools.IDLE) else ""
        return [Text(simbolo, style=f"bold {color}"), Text(f['ip'], style=estilo), Text(str(f['polling_ms']), style=estilo),
                Text(f['tag'], style=estilo), Text(f['valor'], style=f"bold {'#ffe066' if escribiendo else '#00ffff'}"),
                Text(escritura, style="bold #ffcc00" if escribiendo else ("#ff5555" if t['errores'] else "#00ff00")),
                Text(f['comentario'], style=estilo)]

    def despues_de_montar(self):
        self.set_interval(0.2, self._tic)
        if not self.monitor.disponible:
            self.estado("Falta la librería pylogix: no se puede conectar a PLCs.", error=True)
        elif self.ip_inicial:
            self.action_agregar()

    def al_refrescar(self):
        self._ids_pintados = [str(f['id']) for f in self.monitor.instantanea()]
        self.titulo(f"MONITOR DE VARIABLES  ·  {len(self._ids_pintados)} variable(s)")

    def _tic(self):
        """Actualiza las celdas en su lugar (sin reconstruir la tabla: no parpadea)."""
        tabla = self.tabla
        instantanea = self.monitor.instantanea()
        if [str(f['id']) for f in instantanea] != self._ids_pintados:
            self.refrescar()
            return
        for f in instantanea:
            clave = str(f['id'])
            try:
                indice = tabla.get_row_index(clave)
            except Exception:
                continue  # oculta por el filtro
            for (columna, _, _), celda in zip(self.COLUMNAS, self._celdas(f)):
                if tabla.get_cell_at((indice, [c[0] for c in self.COLUMNAS].index(columna))) != celda:
                    tabla.update_cell(clave, columna, celda)
        self._barra_estado()

    def _barra_estado(self):
        f = self._actual()
        if f is None:
            if not self.monitor.filas:
                self.estado("Sin variables. Presiona 'a' para agregar un tag.")
            return
        texto = f"{f['tag'] or '(sin tag)'}  @ {f['ip']}  ·  {f['estado_texto']}"
        t = f['trabajo']
        if t['estado'] != logix_tools.IDLE or t['mensaje']:
            texto += f"  ·  escritura {t['estado']} {t['progreso']}"
            if t['ultimo_status'] and t['ultimo_status'] != 'Success':
                texto += f" (última: {t['ultimo_status']})"
        self.estado(texto, error=f['conexion'] == lm.ERROR)

    def _actual(self):
        clave = self.fila_actual()
        return self.monitor.fila(int(clave)) if clave is not None else None

    # ---------------------------------------------------------
    @work(exclusive=True, group="logix", exit_on_error=False)
    async def action_agregar(self):
        actual = self._actual()
        ip = (actual or {}).get('ip') or self.ultima_ip
        datos = await self.app.push_screen_wait(AsistenteTag(self.explorador, ip=ip))
        if datos:
            self.ultima_ip = datos['ip']
            id_fila = self.monitor.agregar(datos['ip'], datos['tag'], datos['polling_ms'], datos['comentario'])
            self.refrescar()
            self._ir_a(id_fila)
            self._conectar(id_fila)

    @work(exclusive=True, group="logix", exit_on_error=False)
    async def action_editar(self):
        f = self._actual()
        if not f:
            return
        datos = await self.app.push_screen_wait(AsistenteTag(
            self.explorador, ip=f['ip'], tag=f['tag'], polling_ms=f['polling_ms'], comentario=f['comentario'],
            editar=True))
        if datos:
            self.ultima_ip = datos['ip']
            self.monitor.actualizar(f['id'], **datos)
            self.refrescar()

    def _ir_a(self, id_fila):
        try:
            self.tabla.move_cursor(row=self.tabla.get_row_index(str(id_fila)))
        except Exception:
            pass

    def _conectar(self, id_fila):
        try:
            self.monitor.conectar(id_fila)
        except (ValueError, RuntimeError) as e:
            self.estado(str(e), error=True)

    def action_conectar(self):
        f = self._actual()
        if not f:
            return
        if self.monitor.conectada(f['id']):
            self.monitor.desconectar(f['id'])
        else:
            self._conectar(f['id'])

    def action_escribir(self):
        f = self._actual()
        if f:
            self.app.push_screen(VentanaEscritura(self.monitor, f['id']))

    @work(exclusive=True, group="logix", exit_on_error=False)
    async def action_quitar(self):
        f = self._actual()
        if not f:
            return
        if f['trabajo']['estado'] == logix_tools.WORKING and not await self.app.push_screen_wait(Confirmar(
                "Quitar variable", f"'{f['tag']}' está escribiendo. ¿Detener y quitar?", si="Quitar", no="Cancelar")):
            return
        self.monitor.quitar(f['id'])
        self.refrescar()

    def action_detener(self):
        self.monitor.detener_todas()
        self.estado("Todas las escrituras detenidas.")

    # ---------------------------------------------------------
    # Conjuntos de tags guardados en la base
    @work(exclusive=True, group="logix", exit_on_error=False)
    async def action_guardar(self):
        filas = self.monitor.instantanea()
        if not filas:
            self.estado("No hay variables para guardar.", error=True)
            return
        nombre = await self.app.push_screen_wait(PedirTexto(
            "Guardar conjunto de tags", "Nombre del conjunto (si ya existe, se reemplaza):",
            placeholder="ej. Soldadora L31"))
        if not (nombre or '').strip():
            return
        tags = [{'ip': f['ip'], 'polling_ms': f['polling_ms'], 'tag': f['tag'], 'comentario': f['comentario']}
                for f in filas]
        try:
            self.bd.guardar_logix_registro(nombre, tags)
        except db.ErrorDB as e:
            self.estado(str(e), error=True)
            return
        self.estado(f"Guardado '{nombre.strip()}' con {len(tags)} tag(s). Las escrituras no se guardan.")

    @work(exclusive=True, group="logix", exit_on_error=False)
    async def action_cargar(self):
        registros = self.bd.logix_registros()
        opciones = [(r['nombre'], f"{r['nombre']}  ({len(r['tags'])} tags · {r['modificado'][:10]})") for r in registros]
        opciones.append(("__json__", "Importar archivo .json (registro de Eliza V2)…"))
        if registros:
            opciones.append(("__borrar__", "Borrar un conjunto guardado…"))
        eleccion = await self.app.push_screen_wait(Menu("Cargar conjunto de tags", "Elige qué cargar:", opciones))
        if not eleccion:
            return
        if eleccion == "__borrar__":
            nombre = await self.app.push_screen_wait(Menu(
                "Borrar conjunto", "¿Cuál?", [(r['nombre'], r['nombre']) for r in registros]))
            if nombre and await self.app.push_screen_wait(Confirmar("Borrar conjunto", f"¿Borrar '{nombre}'?",
                                                                     si="Borrar", no="Cancelar")):
                self.bd.borrar_logix_registro(nombre)
                self.estado(f"Conjunto '{nombre}' borrado.")
            return
        if eleccion == "__json__":
            ruta = await self.app.push_screen_wait(ExploradorArchivos(
                "Importar registro .json", ('.json',), self.bd.carpeta))
            if not ruta:
                return
            try:
                tags = logix_tools.cargar_registro(ruta)
            except (OSError, ValueError) as e:
                self.estado(f"No se pudo leer {os.path.basename(ruta)}: {e}", error=True)
                return
        else:
            tags = next(r['tags'] for r in registros if r['nombre'] == eleccion)
        if not tags:
            self.estado("El conjunto está vacío.", error=True)
            return
        if self.monitor.filas:
            modo = await self.app.push_screen_wait(Menu(
                "Cargar conjunto", f"Hay {len(self.monitor.filas)} variable(s) en el monitor.",
                [("reemplazar", "Reemplazar las actuales (se desconectan y se detienen sus escrituras)"),
                 ("agregar", "Agregar al final")]))
            if not modo:
                return
            if modo == "reemplazar":
                for id_fila in list(self.monitor.filas):
                    self.monitor.quitar(id_fila)
        for t in tags:
            self.monitor.agregar(t.get('ip', ''), t.get('tag', ''), t.get('polling_ms', 100), t.get('comentario', ''))
        self.refrescar()
        self.estado(f"Cargados {len(tags)} tag(s), desconectados. Espacio conecta cada fila.")

    # ---------------------------------------------------------
    @work(exclusive=True, group="logix", exit_on_error=False)
    async def action_cerrar(self):
        if self.monitor.hay_escrituras() and not await self.app.push_screen_wait(Confirmar(
                "Cerrar monitor", "Hay escrituras en curso. ¿Detenerlas y cerrar?", si="Cerrar", no="Seguir aquí")):
            return
        self.monitor.cerrar()
        self.dismiss(None)
