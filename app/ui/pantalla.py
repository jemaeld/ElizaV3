"""
pantalla.py -- base de las pantallas de trabajo de Eliza V3 (editor, scan_acd,
bitácora, logix): título, línea de filtro, tabla, línea de estado y pie.

Teclado común:
    /  o  Ctrl+F   ir al filtro (escribe para filtrar; Enter o ↓ vuelven a la tabla)
    Esc            en el filtro: vuelve a la tabla; en la tabla: cierra la pantalla
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static


class FiltroTabla(Input):
    BINDINGS = [Binding("down", "screen.a_tabla", show=False), Binding("escape", "screen.a_tabla", show=False)]


class PantallaTabla(Screen):
    TITULO = ""
    COLUMNAS = []            # [(clave, encabezado, ancho o None)]
    BINDINGS = [
        Binding("escape", "cerrar", "Volver"),
        Binding("slash", "a_filtro", "Filtrar", key_display="/"),
        Binding("ctrl+f", "a_filtro", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static(self.TITULO, classes="pantalla-titulo", id="titulo")
        yield FiltroTabla(placeholder="/ para filtrar…", classes="pantalla-filtro", id="filtro")
        tabla = DataTable(classes="pantalla-tabla", id="tabla", cursor_type="row", zebra_stripes=True)
        yield tabla
        yield Static("", classes="pantalla-estado", id="estado")
        yield Footer()

    def on_mount(self):
        # Textual llama on_mount de CADA clase de la jerarquía: por eso las
        # subclases no lo redefinen, sino que usan preparar() y despues_de_montar().
        self.preparar()
        tabla = self.tabla
        for clave, encabezado, ancho in self.COLUMNAS:
            tabla.add_column(encabezado, key=clave, width=ancho)
        self.refrescar()
        tabla.focus()
        self.despues_de_montar()

    def preparar(self):
        """Cargar datos antes de pintar la tabla."""

    def despues_de_montar(self):
        """Acciones iniciales (p. ej. pedir una carpeta)."""

    @property
    def tabla(self) -> DataTable:
        return self.query_one("#tabla", DataTable)

    def estado(self, texto, error=False):
        self.query_one("#estado", Static).update(Text(texto, style="#ff5555" if error else "#00ffff"))

    def titulo(self, texto):
        self.query_one("#titulo", Static).update(texto)

    # ---------------------------------------------------------
    def filas(self):
        """[(clave_fila, [celdas])] ya filtradas. La subclase lo implementa."""
        return []

    def refrescar(self, conservar=True):
        tabla = self.tabla
        clave_actual = self.fila_actual() if conservar else None
        tabla.clear()
        texto = self.query_one("#filtro", Input).value.strip().lower().split()
        for clave, celdas in self.filas():
            plano = " ".join(str(c) for c in celdas).lower()
            if all(t in plano for t in texto):
                tabla.add_row(*celdas, key=str(clave))
        if clave_actual is not None:
            try:
                tabla.move_cursor(row=tabla.get_row_index(str(clave_actual)))
            except Exception:
                pass
        self.al_refrescar()

    def al_refrescar(self):
        pass

    def fila_actual(self):
        tabla = self.tabla
        if not tabla.row_count or tabla.cursor_row is None:
            return None
        try:
            return tabla.coordinate_to_cell_key((tabla.cursor_row, 0)).row_key.value
        except Exception:
            return None

    # ---------------------------------------------------------
    def on_input_changed(self, evento: Input.Changed):
        if evento.input.id == "filtro":
            self.refrescar(conservar=False)

    def on_input_submitted(self, evento: Input.Submitted):
        if evento.input.id == "filtro":
            self.action_a_tabla()

    ACCION_ENTER = None      # nombre de la acción que dispara Enter sobre una fila

    def on_data_table_row_selected(self, evento: DataTable.RowSelected):
        # La tabla consume Enter (RowSelected) antes que las teclas de la pantalla.
        if self.ACCION_ENTER:
            getattr(self, f"action_{self.ACCION_ENTER}")()

    def on_worker_state_changed(self, evento):
        # Los errores de tareas en segundo plano de esta pantalla se reportan
        # en Eliza (aviso + eliza_error.log) en vez de cerrarla.
        self.app.on_worker_state_changed(evento)

    def action_a_filtro(self):
        self.query_one("#filtro", Input).focus()

    def action_a_tabla(self):
        self.tabla.focus()

    def action_cerrar(self):
        self.dismiss(None)
