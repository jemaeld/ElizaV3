"""
editor.py -- /edit [categoría]: editor de la base (VNC, APPS, ACD...).

Teclas en la tabla:
    Enter / e   editar la entrada        n   nueva entrada
    Supr        borrar (pide confirmar)  c   cambiar categoría (Todas → VNC → APPS → ACD ...)
    o           cambiar orden (nombre / IP / categoría)
    r           ACD: reescanear fechas de todos los archivos
    /           filtrar                  Esc volver

Los cambios se guardan en la base al momento (no hay "guardar" aparte).
"""

import re

from rich.text import Text
from textual import work
from textual.binding import Binding

import acd_tools
import db
from ui.formulario import Campo, Formulario
from ui.modales import Confirmar
from ui.pantalla import PantallaTabla

COLORES = {'vnc': "#00ffff", 'apps': "#ffff66", 'acd': "#ff66ff"}
ORDENES = [('nombre', "nombre"), ('ip', "IP"), ('categoria', "categoría")]


def orden_natural(texto):
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in re.split(r'(\d+)', str(texto or '').lower())]


class PantallaEditor(PantallaTabla):
    COLUMNAS = [('cat', "CAT", 6), ('nombre', "NOMBRE", 26), ('ip', "IP", 16), ('info', "INFO", 34),
                ('comentario', "COMENTARIO", 30), ('accion', "ACCIÓN", None)]
    ACCION_ENTER = "editar"
    BINDINGS = PantallaTabla.BINDINGS + [
        Binding("enter", "editar", "Editar"),
        Binding("e", "editar", show=False),
        Binding("n", "nueva", "Nueva"),
        Binding("delete", "borrar", "Borrar", key_display="Supr"),
        Binding("c", "categoria", "Categoría"),
        Binding("o", "orden", "Orden"),
        Binding("r", "reescanear", "Reescanear ACD"),
    ]

    def __init__(self, bd, categoria=None):
        super().__init__()
        self.bd = bd
        self.categoria = (categoria or '').lower() or None
        self.orden = 0
        self.entradas = {}
        self.hubo_cambios = False

    def preparar(self):
        self.cargar()

    def cargar(self):
        self.entradas = {e['id']: e for e in self.bd.entradas()}

    def categorias(self):
        base = ['vnc', 'apps', 'acd']
        return base + sorted({e['categoria'] for e in self.entradas.values()} - set(base))

    def filas(self):
        campo = ORDENES[self.orden][0]
        lista = [e for e in self.entradas.values() if not self.categoria or e['categoria'] == self.categoria]
        lista.sort(key=lambda e: (orden_natural(e[campo]), orden_natural(e['nombre'])))
        for e in lista:
            yield e['id'], [Text(e['categoria'].upper(), style=f"bold {COLORES.get(e['categoria'], '#ffffff')}"),
                            e['nombre'], e['ip'], e['info'], e['comentario'], e['accion']]

    def al_refrescar(self):
        cat = self.categoria.upper() if self.categoria else "TODAS"
        self.titulo(f"EDITOR DE LA BASE  ·  {cat}  ·  {self.tabla.row_count} entrada(s)  ·  "
                    f"orden: {ORDENES[self.orden][1]}")

    # ---------------------------------------------------------
    def _seleccionada(self):
        clave = self.fila_actual()
        return self.entradas.get(int(clave)) if clave is not None else None

    def _formulario(self, entrada=None):
        e = entrada or {'categoria': self.categoria or 'vnc'}
        opciones = [(c, c.upper()) for c in self.categorias()]
        return Formulario(
            "Editar entrada" if entrada else "Nueva entrada",
            [Campo('categoria', "Categoría", e.get('categoria', 'vnc'), opciones=opciones),
             Campo('nombre', "Nombre", e.get('nombre', ''), obligatorio=True),
             Campo('ip', "IP", e.get('ip', '')),
             Campo('accion', "Acción", e.get('accion', ''), ayuda='vnc <ip>  ·  open "C:\\ruta\\programa.exe"'),
             Campo('info', "Info", e.get('info', '')),
             Campo('comentario', "Comentario", e.get('comentario', ''))])

    @work(exclusive=True, group="editor")
    async def action_editar(self):
        entrada = self._seleccionada()
        if not entrada:
            return
        await self._guardar(await self.app.push_screen_wait(self._formulario(entrada)), entrada['id'])

    @work(exclusive=True, group="editor")
    async def action_nueva(self):
        await self._guardar(await self.app.push_screen_wait(self._formulario()), None)

    async def _guardar(self, datos, id_entrada):
        if not datos:
            return
        if datos['categoria'] == 'vnc' and not datos['accion'] and datos['ip']:
            datos['accion'] = f"vnc {datos['ip']}"
        try:
            nuevo_id = self.bd.guardar_entrada(datos, id_entrada)
        except db.ErrorDB as e:
            self.estado(str(e), error=True)
            return
        self.hubo_cambios = True
        self.cargar()
        self.refrescar(conservar=False)
        try:
            self.tabla.move_cursor(row=self.tabla.get_row_index(str(nuevo_id)))
        except Exception:
            pass
        self.estado(f"Guardado: {datos['nombre']}")

    @work(exclusive=True, group="editor")
    async def action_borrar(self):
        entrada = self._seleccionada()
        if not entrada:
            return
        if await self.app.push_screen_wait(Confirmar(
                "Borrar entrada", f"¿Borrar '{entrada['nombre']}' ({entrada['categoria'].upper()}) de la base?\n"
                "Si es ACD, el archivo en _acd_store NO se borra.", si="Borrar", no="Cancelar")):
            self.bd.borrar_entrada(entrada['id'])
            self.hubo_cambios = True
            self.cargar()
            self.refrescar()
            self.estado(f"Borrada: {entrada['nombre']}")

    def action_categoria(self):
        ciclo = [None] + self.categorias()
        self.categoria = ciclo[(ciclo.index(self.categoria) + 1) % len(ciclo)] if self.categoria in ciclo else None
        self.refrescar(conservar=False)

    def action_orden(self):
        self.orden = (self.orden + 1) % len(ORDENES)
        self.refrescar()

    def action_reescanear(self):
        acd = [e for e in self.entradas.values() if e['categoria'] == 'acd']
        if not acd:
            self.estado("No hay entradas ACD.")
            return
        actualizados, errores = 0, []
        for e in acd:
            ruta = acd_tools.resolver_ruta_action(e['accion'], self.bd.carpeta)
            info, error = acd_tools.reescanear(ruta, e['ip'])
            if error:
                errores.append(e['nombre'])
                continue
            if info != e['info']:
                self.bd.guardar_entrada({**e, 'info': info}, e['id'])
                actualizados += 1
        self.hubo_cambios = self.hubo_cambios or bool(actualizados)
        self.cargar()
        self.refrescar()
        texto = f"Reescaneo: {actualizados} fecha(s) actualizada(s) de {len(acd)}."
        if errores:
            texto += f" Sin archivo: {', '.join(errores[:8])}{'…' if len(errores) > 8 else ''}"
        self.estado(texto, error=bool(errores))

    def action_cerrar(self):
        self.dismiss(self.hubo_cambios)
