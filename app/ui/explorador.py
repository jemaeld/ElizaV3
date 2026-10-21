"""
explorador.py -- elegir un archivo sin salir de la consola.

    ┌ Elegir archivo ───────────────────────────────┐
    │ Ruta: [C:\\Users\\...\\Desktop\\        ]          │  escribir + Enter = ir ahí
    │ 📁 ..                                         │
    │ 📁 Accesos                                    │  ↑/↓ moverse · → / ← abrir/cerrar
    │    Planta L31.vnc                             │  Enter: entrar a carpeta / elegir archivo
    └───────────────────────────────────────────────┘

Solo muestra carpetas y archivos con las extensiones pedidas.
Backspace sube un nivel. Tab alterna entre la ruta y el árbol.

Opciones:
    mostrar_fechas    junto a cada archivo, su fecha de modificación
    elegir_carpeta    Ctrl+S devuelve {'carpeta': ruta} (la carpeta resaltada,
                      o la del archivo resaltado) en vez de un archivo
"""

import os
from datetime import datetime
from pathlib import Path

from rich.text import Text

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DirectoryTree, Input, Label

from ui.modales import SugeridorCarpetas, _Base


class ArbolFiltrado(DirectoryTree):
    BINDINGS = [Binding("backspace", "screen.subir", show=False)]

    def __init__(self, ruta, extensiones, mostrar_fechas=False, **kw):
        self.extensiones = tuple(e.lower() for e in extensiones)
        self.mostrar_fechas = mostrar_fechas
        self._fechas = {}
        super().__init__(ruta, **kw)

    def _populate_node(self, nodo, contenido):
        # Con fechas: carpetas por nombre y luego archivos del MÁS RECIENTE al más viejo.
        if self.mostrar_fechas:
            def fecha(p):
                try:
                    return p.stat().st_mtime
                except OSError:
                    return 0
            contenido = list(contenido)
            carpetas = [p for p in contenido if self._safe_is_dir(p)]
            archivos = sorted((p for p in contenido if not self._safe_is_dir(p)), key=fecha, reverse=True)
            contenido = carpetas + archivos
        super()._populate_node(nodo, contenido)

    def render_label(self, nodo, estilo_base, estilo):
        etiqueta = super().render_label(nodo, estilo_base, estilo)
        ruta = getattr(nodo.data, 'path', None)
        if not self.mostrar_fechas or ruta is None or nodo.allow_expand:
            return etiqueta
        clave = str(ruta)
        if clave not in self._fechas:
            try:
                self._fechas[clave] = datetime.fromtimestamp(os.path.getmtime(ruta)).strftime('%Y-%m-%d %H:%M')
            except OSError:
                self._fechas[clave] = ""
        return Text.assemble(etiqueta, ("   " + self._fechas[clave], "#888888"))

    def filter_paths(self, rutas):
        visibles = []
        for p in rutas:
            try:
                if p.name.startswith('.') or p.name.startswith('$'):
                    continue
                if p.is_dir() or p.suffix.lower() in self.extensiones:
                    visibles.append(p)
            except OSError:
                continue
        return visibles


class ExploradorArchivos(_Base):
    BINDINGS = [Binding("ctrl+s", "elegir_carpeta", show=False, priority=True)]

    def __init__(self, titulo, extensiones, inicio=None, mostrar_fechas=False, elegir_carpeta=False):
        ayuda = "Enter elige · Backspace sube · Tab ruta/árbol · Esc cancela"
        if elegir_carpeta:
            ayuda = "Enter abre/elige · Ctrl+S buscar en la carpeta · Backspace sube · Esc"
        super().__init__(titulo, ayuda)
        self.extensiones = extensiones
        self.mostrar_fechas = mostrar_fechas
        self.permite_carpeta = elegir_carpeta
        self.inicio = inicio if inicio and os.path.isdir(inicio) else str(Path.home())

    def compose(self) -> ComposeResult:
        caja = self.marco(
            Input(value=self.inicio, suggester=SugeridorCarpetas(), id="ruta"),
            ArbolFiltrado(self.inicio, self.extensiones, mostrar_fechas=self.mostrar_fechas, id="arbol"),
            Label(f"Archivos: {'  '.join(self.extensiones)}", classes="mensaje"),
        )
        caja.add_class("explorador")
        yield caja

    def on_mount(self):
        self.query_one("#arbol").focus()

    def on_input_submitted(self, evento: Input.Submitted):
        ruta = evento.value.strip().strip('"')
        if os.path.isfile(ruta) and ruta.lower().endswith(tuple(self.extensiones)):
            self.dismiss(ruta)
            return
        if os.path.isdir(ruta):
            self._ir(ruta)

    def _ir(self, ruta):
        arbol = self.query_one("#arbol", ArbolFiltrado)
        arbol.path = ruta
        self.query_one("#ruta", Input).value = ruta
        arbol.focus()

    def on_directory_tree_file_selected(self, evento: DirectoryTree.FileSelected):
        self.dismiss(str(evento.path))

    def action_elegir_carpeta(self):
        if not self.permite_carpeta:
            return
        arbol = self.query_one("#arbol", ArbolFiltrado)
        nodo = arbol.cursor_node
        ruta = getattr(getattr(nodo, 'data', None), 'path', None) if nodo else None
        if ruta is None:
            carpeta = str(arbol.path)
        elif os.path.isdir(ruta):
            carpeta = str(ruta)
        else:
            carpeta = os.path.dirname(str(ruta))
        self.dismiss({'carpeta': carpeta})

    def action_subir(self):
        actual = str(self.query_one("#arbol", ArbolFiltrado).path)
        padre = os.path.dirname(actual.rstrip("\\/")) or actual
        if padre != actual:
            self._ir(padre)
