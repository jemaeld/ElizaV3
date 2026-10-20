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
"""

import os
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DirectoryTree, Input, Label

from ui.modales import SugeridorCarpetas, _Base


class ArbolFiltrado(DirectoryTree):
    BINDINGS = [Binding("backspace", "screen.subir", show=False)]

    def __init__(self, ruta, extensiones, **kw):
        self.extensiones = tuple(e.lower() for e in extensiones)
        super().__init__(ruta, **kw)

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
    def __init__(self, titulo, extensiones, inicio=None):
        super().__init__(titulo, "Enter elige · Backspace sube · Tab ruta/árbol · Esc cancela")
        self.extensiones = extensiones
        self.inicio = inicio if inicio and os.path.isdir(inicio) else str(Path.home())

    def compose(self) -> ComposeResult:
        caja = self.marco(
            Input(value=self.inicio, suggester=SugeridorCarpetas(), id="ruta"),
            ArbolFiltrado(self.inicio, self.extensiones, id="arbol"),
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

    def action_subir(self):
        actual = str(self.query_one("#arbol", ArbolFiltrado).path)
        padre = os.path.dirname(actual.rstrip("\\/")) or actual
        if padre != actual:
            self._ir(padre)
