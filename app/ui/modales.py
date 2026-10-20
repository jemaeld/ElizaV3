"""
modales.py -- ventanas emergentes de Eliza V3 (todas manejables con teclado).

    Menu             lista de opciones (↑/↓ + Enter, o la letra resaltada)
    PedirCarpeta     ruta con autocompletado de carpetas (→ acepta la sugerencia)
    PedirTexto       una línea de texto (opcionalmente oculta)
    Contrasena       contraseña de acceso (verificar o definir)
    Reporte          texto largo de solo lectura (ayuda, reporte de migración)
    Confirmar        Sí / No
"""

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Input, Label, OptionList, RichLog, Static
from textual.widgets.option_list import Option


class _Base(ModalScreen):
    """Marco común: borde dorado, título y pie con teclas."""
    BINDINGS = [Binding("escape", "cancelar", "Cancelar", show=False)]

    def __init__(self, titulo, pie=""):
        super().__init__()
        self.titulo = titulo
        self.pie = pie

    def marco(self, *hijos):
        caja = Vertical(*hijos, classes="modal")
        caja.border_title = self.titulo
        if self.pie:
            caja.border_subtitle = self.pie
        return caja

    def action_cancelar(self):
        self.dismiss(None)

    def on_worker_state_changed(self, evento):
        # Los errores de tareas en segundo plano de esta pantalla se reportan
        # en Eliza (aviso + eliza_error.log) en vez de cerrarla.
        self.app.on_worker_state_changed(evento)


# ---------------------------------------------------------
class Menu(_Base):
    """opciones: [(clave, texto)]. Devuelve la clave elegida o None (Esc)."""

    def __init__(self, titulo, mensaje, opciones, cancelable=True):
        super().__init__(titulo, "↑/↓ · Enter elige" + (" · Esc cancela" if cancelable else ""))
        self.mensaje = mensaje
        self.opciones = opciones
        self.cancelable = cancelable

    def compose(self) -> ComposeResult:
        yield self.marco(
            Static(self.mensaje, classes="mensaje"),
            OptionList(*[Option(texto, id=clave) for clave, texto in self.opciones], id="opciones"),
        )

    def on_mount(self):
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, evento: OptionList.OptionSelected):
        self.dismiss(evento.option.id)

    def action_cancelar(self):
        if self.cancelable:
            self.dismiss(None)


# ---------------------------------------------------------
class SugeridorCarpetas(Suggester):
    """Sugiere la primera subcarpeta que coincide con lo escrito (como Tab en una consola)."""

    def __init__(self):
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, valor):
        if not valor:
            return None
        base, parcial = os.path.split(valor)
        if not base:
            return None
        try:
            candidatos = sorted(n for n in os.listdir(base)
                                if n.lower().startswith(parcial.lower()) and os.path.isdir(os.path.join(base, n)))
        except OSError:
            return None
        if not candidatos or candidatos[0] == parcial:
            return None
        return os.path.join(base, candidatos[0]) + os.sep


class PedirCarpeta(_Base):
    """Devuelve una ruta de carpeta existente o None."""

    def __init__(self, titulo, mensaje, valor=""):
        super().__init__(titulo, "→ acepta sugerencia · Enter confirma · Esc cancela")
        self.mensaje = mensaje
        self.valor = valor

    def compose(self) -> ComposeResult:
        yield self.marco(
            Static(self.mensaje, classes="mensaje"),
            Input(value=self.valor, placeholder=r"S:\carpeta\ELIZA   o   \\servidor\carpeta",
                  suggester=SugeridorCarpetas(), id="ruta"),
            Label("", id="error", classes="error"),
        )

    def on_input_submitted(self, evento: Input.Submitted):
        ruta = evento.value.strip().strip('"')
        if not ruta:
            return
        if not os.path.isdir(ruta):
            self.query_one("#error", Label).update(f"No existe o no está disponible: {ruta}")
            return
        self.dismiss(os.path.normpath(ruta))


class PedirTexto(_Base):
    def __init__(self, titulo, mensaje, valor="", oculto=False, placeholder=""):
        super().__init__(titulo, "Enter confirma · Esc cancela")
        self.mensaje, self.valor, self.oculto, self.placeholder = mensaje, valor, oculto, placeholder

    def compose(self) -> ComposeResult:
        yield self.marco(Static(self.mensaje, classes="mensaje"),
                         Input(value=self.valor, password=self.oculto, placeholder=self.placeholder))

    def on_input_submitted(self, evento: Input.Submitted):
        self.dismiss(evento.value)


# ---------------------------------------------------------
class Contrasena(_Base):
    """
    modo 'verificar': un campo, 'validar(valor)->bool', 3 intentos.
    modo 'definir'  : dos campos que deben coincidir.
    Devuelve True (acceso concedido) o False.
    """

    def __init__(self, modo, validar, intentos=3):
        super().__init__("ELIZA :: acceso", "Enter confirma · Esc sale")
        self.modo, self.validar, self.intentos = modo, validar, intentos

    def compose(self) -> ComposeResult:
        campos = [Static("Define la contraseña de acceso." if self.modo == 'definir' else "Contraseña",
                         classes="mensaje"),
                  Input(password=True, id="c1", placeholder="contraseña")]
        if self.modo == 'definir':
            campos.append(Input(password=True, id="c2", placeholder="confírmala"))
        campos.append(Label("", id="error", classes="error"))
        yield self.marco(*campos)

    def on_input_submitted(self, evento: Input.Submitted):
        error = self.query_one("#error", Label)
        if self.modo == 'definir':
            if evento.input.id == "c1":
                self.query_one("#c2", Input).focus()
                return
            c1, c2 = self.query_one("#c1", Input).value, self.query_one("#c2", Input).value
            if not c1.strip() or c1 != c2:
                error.update("No coinciden o quedó vacía.")
                return
            self.dismiss(self.validar(c1))
            return
        if self.validar(evento.value):
            self.dismiss(True)
            return
        self.intentos -= 1
        if self.intentos <= 0:
            self.dismiss(False)
            return
        evento.input.value = ""
        error.update(f"Contraseña incorrecta ({self.intentos} intento(s) más).")

    def action_cancelar(self):
        self.dismiss(False)


# ---------------------------------------------------------
class Reporte(_Base):
    def __init__(self, titulo, texto):
        super().__init__(titulo, "Esc / Enter cierra · ↑/↓ desplaza")
        self.texto = texto

    BINDINGS = [Binding("escape", "cancelar", show=False), Binding("enter", "cancelar", show=False)]

    def compose(self) -> ComposeResult:
        log = RichLog(markup=True, wrap=True, id="reporte")
        caja = self.marco(log)
        caja.add_class("ancho")
        yield caja

    def on_mount(self):
        log = self.query_one(RichLog)
        log.write(self.texto)
        log.focus()


class Confirmar(Menu):
    def __init__(self, titulo, mensaje, si="Sí", no="No"):
        super().__init__(titulo, mensaje, [("si", si), ("no", no)])

    def on_option_list_option_selected(self, evento):
        # Textual también llamaría al manejador de Menu (clase base): se evita,
        # porque un segundo dismiss() cerraría la pantalla de abajo.
        evento.prevent_default()
        self.dismiss(evento.option.id == "si")

    def action_cancelar(self):
        self.dismiss(False)
