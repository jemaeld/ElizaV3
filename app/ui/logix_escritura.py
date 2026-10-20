"""
logix_escritura.py -- ventana "Escribir" del Monitor de Variables.

    TAG / IP / POLL       datos de la fila
    VALOR ACTUAL          en vivo, grande
    Escribir [ 1 ]  Veces [ 10 ]  [ ] Continuo
    [        IDLE  ·  Enter para iniciar        ]   indicador de 3 estados
    [■■■■■■■■░░░░░░░░░░] 4/10 · errores 0 · última Success
    bitácora: 14:02:11.120  #4  Success …

El indicador es un botón:  IDLE → inicia · WORKING n/N → detiene · DONE → vuelve a IDLE.
Esc cierra la ventana y la escritura SIGUE en segundo plano (se ve en la
columna ESCRITURA del monitor).
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal
from textual.widgets import Button, Checkbox, Input, Label, ProgressBar, RichLog, Static

import logix_tools
from ui.modales import _Base

TEXTOS = {
    logix_tools.IDLE: "IDLE  ·  Enter para iniciar",
    logix_tools.WORKING: "WORKING {p}  ·  Enter para detener",
    logix_tools.DONE: "DONE {p}  ·  Enter para reiniciar",
}
CLASES = {logix_tools.IDLE: "idle", logix_tools.WORKING: "working", logix_tools.DONE: "done"}


class VentanaEscritura(_Base):
    BINDINGS = [Binding("escape", "cancelar", show=False)]

    def __init__(self, monitor, id_fila):
        super().__init__("LOGIX :: escribir", "Tab entre campos · Enter inicia/detiene · Esc cierra (sigue en 2º plano)")
        self.monitor = monitor
        self.id_fila = id_fila
        self._historial = (None, 0)

    def compose(self) -> ComposeResult:
        fila = self.monitor.fila(self.id_fila) or {}
        t = fila.get('trabajo', {})
        caja = self.marco(
            Grid(Label("TAG", classes="etiqueta"), Static("", id="tag"),
                 Label("IP / POLL", classes="etiqueta"), Static("", id="conexion"),
                 classes="rejilla"),
            Static("", id="valor", classes="valor-grande"),
            Horizontal(Label("Escribir", classes="etiqueta"),
                       Input(t.get('valor_texto', ''), id="escribir", placeholder="valor"),
                       Label("Veces", classes="etiqueta"),
                       Input(str(t.get('total') or 1), id="veces", restrict=r"\d*"),
                       Checkbox("Continuo", t.get('total') == 0 and bool(t.get('valor_texto')), id="continuo"),
                       classes="parametros"),
            Button("", id="indicador", classes="indicador"),
            ProgressBar(total=100, show_eta=False, show_percentage=False, id="barra"),
            Static("", id="progreso"),
            Label("", id="error", classes="error"),
            Label("Bitácora de escrituras", classes="etiqueta"),
            RichLog(id="historial", markup=False, max_lines=200),
        )
        caja.add_class("escritura")
        yield caja

    def on_mount(self):
        self.query_one("#escribir", Input).focus()
        self._refrescar()
        self.set_interval(0.15, self._refrescar)

    def on_input_submitted(self, evento: Input.Submitted):
        self._clic()

    def on_button_pressed(self, evento: Button.Pressed):
        self._clic()

    def on_checkbox_changed(self, evento: Checkbox.Changed):
        self.query_one("#veces", Input).disabled = evento.value

    def _clic(self):
        fila = self.monitor.fila(self.id_fila)
        if fila is None:
            return
        estado = fila['trabajo']['estado']
        error = self.query_one("#error", Label)
        error.update("")
        if estado == logix_tools.WORKING:
            self.monitor.detener_escritura(self.id_fila)
        elif estado == logix_tools.DONE:
            self.monitor.reiniciar_escritura(self.id_fila)
        else:
            continuo = self.query_one("#continuo", Checkbox).value
            veces = self.query_one("#veces", Input).value.strip()
            if not continuo and (not veces or int(veces) < 1):
                error.update("Las veces deben ser 1 o más.")
                return
            try:
                self.monitor.iniciar_escritura(self.id_fila, self.query_one("#escribir", Input).value,
                                               0 if continuo else int(veces))
            except (ValueError, RuntimeError) as e:
                error.update(str(e))
                return
        self._refrescar()

    def _refrescar(self):
        fila = self.monitor.fila(self.id_fila)
        if fila is None:
            self.dismiss(None)
            return
        t = fila['trabajo']
        estado = t['estado']
        self.query_one("#tag", Static).update(Text(fila['tag'] or "(sin tag)", style="bold #00ffff"))
        self.query_one("#conexion", Static).update(Text(
            f"{fila['ip']}  ·  {fila['polling_ms']} ms  ·  {fila['conexion']}  {fila['estado_texto']}", style="#00ffff"))
        self.query_one("#valor", Static).update(Text(f"VALOR ACTUAL   {fila['valor'] or '—'}", style="bold #00ffff"))

        boton = self.query_one("#indicador", Button)
        boton.label = TEXTOS[estado].format(p=t['progreso'])
        for clase in CLASES.values():
            boton.set_class(clase == CLASES[estado], clase)
        trabajando = estado == logix_tools.WORKING
        self.query_one("#escribir", Input).disabled = trabajando
        self.query_one("#continuo", Checkbox).disabled = trabajando
        self.query_one("#veces", Input).disabled = trabajando or self.query_one("#continuo", Checkbox).value

        barra = self.query_one("#barra", ProgressBar)
        barra.update(total=100, progress=(100 * t['hechas'] / t['total']) if t['total'] else (100 if t['hechas'] else 0))
        detalle = f"{t['progreso']}  ·  errores: {t['errores']}"
        if t['ultimo_status']:
            detalle += f"  ·  última: {t['ultimo_status']}"
        if t['mensaje']:
            detalle += f"  ·  {t['mensaje']}"
        self.query_one("#progreso", Static).update(Text(detalle, style="#ff5555" if t['errores'] else "#00ffff"))

        clave = (t['corrida'], len(t['historial']))
        if clave != self._historial:
            log = self.query_one("#historial", RichLog)
            if clave[0] != self._historial[0]:
                log.clear()
                nuevos = t['historial']
            else:
                nuevos = t['historial'][self._historial[1]:]
            for hora, numero, status in nuevos:
                log.write(Text(f"{hora}  #{numero:<5} {status}", style="#00ffff" if status == 'Success' else "#ff5555"))
            self._historial = clave
