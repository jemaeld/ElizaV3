"""
formulario.py -- formulario genérico en ventana emergente, 100% teclado.

    Campo(clave, etiqueta, valor="", obligatorio=False, opciones=None, ayuda="")

- Enter pasa al siguiente campo; en el último, guarda.  Ctrl+S guarda desde
  cualquier campo.  Esc cancela.  ↑/↓ (y Tab) también se mueven entre campos.
- 'opciones' convierte el campo en una lista (Select): Enter o Espacio la
  abre, ↑/↓ eligen, Enter confirma.
- 'validar(datos) -> str | None' permite rechazar con un mensaje sin cerrar.
- Devuelve dict {clave: valor} o None si se canceló.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.widgets import Input, Label, Select, Static

from ui.modales import _Base


class Campo:
    def __init__(self, clave, etiqueta, valor="", obligatorio=False, opciones=None, ayuda="", oculto=False):
        self.clave, self.etiqueta, self.valor = clave, etiqueta, valor
        self.obligatorio, self.opciones, self.ayuda, self.oculto = obligatorio, opciones, ayuda, oculto


class Formulario(_Base):
    BINDINGS = [
        Binding("escape", "cancelar", show=False),
        Binding("ctrl+s", "guardar", show=False, priority=True),
        Binding("down", "mover(1)", show=False, priority=True),
        Binding("up", "mover(-1)", show=False, priority=True),
    ]

    def __init__(self, titulo, campos, validar=None, mensaje="", texto_guardar="guardar"):
        super().__init__(titulo, f"Enter siguiente · Ctrl+S {texto_guardar} · Esc cancela")
        self.campos = campos
        self.validar = validar
        self.mensaje = mensaje

    def compose(self) -> ComposeResult:
        hijos = []
        if self.mensaje:
            hijos.append(Static(self.mensaje, classes="mensaje"))
        rejilla = []
        for c in self.campos:
            etiqueta = c.etiqueta + (" *" if c.obligatorio else "")
            rejilla.append(Label(etiqueta, classes="etiqueta"))
            if c.opciones:
                rejilla.append(Select([(texto, valor) for valor, texto in c.opciones], value=c.valor or c.opciones[0][0],
                                      allow_blank=False, id=f"f_{c.clave}"))
            else:
                rejilla.append(Input(value=str(c.valor or ""), placeholder=c.ayuda, password=c.oculto,
                                     id=f"f_{c.clave}"))
        hijos.append(Grid(*rejilla, classes="rejilla"))
        hijos.append(Label("", id="error", classes="error"))
        caja = self.marco(*hijos)
        caja.add_class("formulario")
        yield caja

    def on_mount(self):
        self._widgets()[0].focus()

    def _widgets(self):
        return [self.query_one(f"#f_{c.clave}") for c in self.campos]

    def check_action(self, action, parameters):
        # Con una lista desplegable abierta, ↑/↓ eligen opción en vez de cambiar de campo.
        if action == "mover" and any(isinstance(w, Select) and w.expanded for w in self.query(Select)):
            return False
        return True

    def action_mover(self, paso):
        widgets = self._widgets()
        actual = self.focused
        if actual in widgets:
            widgets[max(0, min(len(widgets) - 1, widgets.index(actual) + paso))].focus()

    def on_input_submitted(self, evento: Input.Submitted):
        widgets = self._widgets()
        i = widgets.index(evento.input)
        if i < len(widgets) - 1:
            widgets[i + 1].focus()
        else:
            self.action_guardar()

    def datos(self):
        resultado = {}
        for c in self.campos:
            w = self.query_one(f"#f_{c.clave}")
            resultado[c.clave] = (w.value if isinstance(w, Select) else w.value.strip())
        return resultado

    def action_guardar(self):
        datos = self.datos()
        faltan = [c.etiqueta for c in self.campos if c.obligatorio and not str(datos[c.clave]).strip()]
        error = f"Falta: {', '.join(faltan)}" if faltan else (self.validar(datos) if self.validar else None)
        if error:
            self.query_one("#error", Label).update(error)
            return
        self.dismiss(datos)
