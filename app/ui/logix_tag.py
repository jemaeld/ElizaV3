"""
logix_tag.py -- asistente para agregar/editar un tag del Monitor de Variables.

    IP          [10.140.126.30]          (al confirmar la IP se leen programas y tags del PLC)
    Scope       [Principal (Controlador) ▼]   o Subprograma
    Programa    [Estacion30]             (solo subprograma)
    Tag         [Timer_Soldadura.DN]
    Polling ms  [100]
    Comentario  [...]
    Ruta final: Program:Estacion30.Timer_Soldadura.DN
    ┌ coincidencias ──────────┐  lista filtrada mientras escribes
    └─────────────────────────┘

Teclado: Enter / ↓ / Tab avanzan; en Programa o Tag, ↓ entra a la lista de
coincidencias (Enter elige, Esc regresa al campo); → acepta la sugerencia en
gris; Ctrl+S guarda; Esc cancela. Pegar una ruta completa (Program:X.Y) en
Tag la reparte sola. Sin conexión al PLC todo se escribe a mano.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.suggester import Suggester
from textual.widgets import Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

import logix_tools
from ui.modales import _Base

CONTROLADOR, PROGRAMA = 'controlador', 'programa'


class SugeridorLista(Suggester):
    def __init__(self, proveedor):
        super().__init__(use_cache=False, case_sensitive=True)
        self.proveedor = proveedor

    async def get_suggestion(self, valor):
        if not valor:
            return None
        raiz = valor.lower()
        for nombre in self.proveedor():
            if nombre.lower().startswith(raiz) and len(nombre) > len(valor):
                return valor + nombre[len(valor):]
        return None


class ListaCoincidencias(OptionList):
    BINDINGS = [Binding("escape", "screen.volver_al_campo", show=False)]


class AsistenteTag(_Base):
    BINDINGS = [
        Binding("escape", "cancelar", show=False),
        Binding("ctrl+s", "guardar", show=False, priority=True),
    ]

    def __init__(self, explorador, ip="", tag="", polling_ms=100, comentario="", editar=False):
        super().__init__("LOGIX :: " + ("editar tag" if editar else "agregar tag"),
                         "Enter siguiente · ↓ lista · → sugerencia · Ctrl+S guardar · Esc cancela")
        self.explorador = explorador
        programa, nombre = logix_tools.separar_ruta(tag)
        self.inicial = {'ip': ip, 'scope': PROGRAMA if programa else CONTROLADOR, 'programa': programa or '',
                        'tag': nombre, 'polling': str(polling_ms or 100), 'comentario': comentario}
        self.tags_controlador, self.programas, self.tags_programa = [], [], []
        self.ip_consultada = None
        self.campo_lista = None   # 'programa' o 'tag': a qué campo alimenta la lista

    def compose(self) -> ComposeResult:
        i = self.inicial
        caja = self.marco(
            Grid(Label("IP", classes="etiqueta"), Input(i['ip'], id="ip", placeholder="10.140.x.x"),
                 Label("Scope", classes="etiqueta"),
                 Select([("Principal (Controlador)", CONTROLADOR), ("Subprograma", PROGRAMA)],
                        value=i['scope'], allow_blank=False, id="scope"),
                 Label("Programa", classes="etiqueta"),
                 Input(i['programa'], id="programa", suggester=SugeridorLista(lambda: self.programas),
                       select_on_focus=False),
                 Label("Tag", classes="etiqueta"),
                 Input(i['tag'], id="tag", placeholder="Motor1.Run  ·  Datos[3].Valor",
                       suggester=SugeridorLista(self._base_tags), select_on_focus=False),
                 Label("Polling ms", classes="etiqueta"), Input(i['polling'], id="polling"),
                 Label("Comentario", classes="etiqueta"), Input(i['comentario'], id="comentario"),
                 classes="rejilla"),
            Static("", id="ruta", classes="ruta"),
            ListaCoincidencias(id="lista"),
            Static("", id="estado", classes="mensaje"),
        )
        caja.add_class("formulario")
        yield caja

    def on_mount(self):
        self._aplicar_scope()
        self._actualizar_ruta()
        (self.query_one("#tag") if self.inicial['ip'] else self.query_one("#ip")).focus()
        self._consultar_plc()
        self.set_interval(0.15, self._revisar_plc)

    # ---------------------------------------------------------
    def _orden(self):
        return ["#ip", "#scope"] + (["#programa"] if self._es_programa() else []) + ["#tag", "#polling", "#comentario"]

    def _es_programa(self):
        return self.query_one("#scope", Select).value == PROGRAMA

    def _base_tags(self):
        return self.tags_programa if self._es_programa() else self.tags_controlador

    def _estado(self, texto, error=False):
        self.query_one("#estado", Static).update(f"[#ff5555]{texto}[/]" if error else f"[#888888]{texto}[/]")

    def _aplicar_scope(self):
        self.query_one("#programa", Input).disabled = not self._es_programa()
        if self._es_programa():
            self._pedir_programa()
        self._llenar_lista('tag')

    def _actualizar_ruta(self):
        programa = self.query_one("#programa", Input).value if self._es_programa() else None
        tag = self.query_one("#tag", Input).value
        if self._es_programa() and not (programa or '').strip():
            texto = "[#ff5555](falta el programa)[/]"
        else:
            ruta = logix_tools.armar_ruta(programa, tag)
            texto = f"[bold #00ffff]{ruta}[/]" if ruta else "[#ff5555](falta el tag)[/]"
        self.query_one("#ruta", Static).update(f"[#00ff00]Ruta final:[/] {texto}")

    def _llenar_lista(self, campo):
        self.campo_lista = campo
        lista = self.query_one("#lista", OptionList)
        if campo == 'programa':
            base, texto = self.programas, self.query_one("#programa", Input).value
        else:
            base, texto = self._base_tags(), self.query_one("#tag", Input).value.split('.')[0].split('[')[0]
        lista.clear_options()
        for nombre in logix_tools.filtrar_nombres(base, texto, limite=300):
            lista.add_option(Option(nombre))

    # ---------------------------------------------------------
    # Eventos
    def on_select_changed(self, evento: Select.Changed):
        self._aplicar_scope()
        self._actualizar_ruta()

    def on_input_changed(self, evento: Input.Changed):
        campo = evento.input.id
        if campo == "tag":
            programa, nombre = logix_tools.separar_ruta(evento.value)
            if programa:  # se pegó una ruta completa: se reparte en los campos
                self.query_one("#scope", Select).value = PROGRAMA
                self.query_one("#programa", Input).value = programa
                evento.input.value = nombre
                return
            self._llenar_lista('tag')
        elif campo == "programa":
            self._llenar_lista('programa')
        if campo in ("tag", "programa"):
            self._actualizar_ruta()

    def on_descendant_focus(self, evento):
        widget = evento.widget
        if getattr(widget, "id", None) in ("tag", "programa"):
            self._llenar_lista(widget.id)
        if getattr(widget, "id", None) != "ip":
            self._consultar_plc()
        if getattr(widget, "id", None) == "tag" and self._es_programa():
            self._pedir_programa()

    def on_input_submitted(self, evento: Input.Submitted):
        self._mover(evento.input, 1, guardar_al_final=True)

    def on_key(self, evento):
        enfocado = self.focused
        if evento.key in ("down", "up") and isinstance(enfocado, (Input, Select)):
            if isinstance(enfocado, Select) and enfocado.expanded:
                return
            lista = self.query_one("#lista", OptionList)
            if evento.key == "down" and enfocado.id in ("tag", "programa") and lista.option_count:
                self.campo_lista = enfocado.id
                lista.highlighted = 0
                lista.focus()
            else:
                self._mover(enfocado, 1 if evento.key == "down" else -1)
            evento.stop()
            evento.prevent_default()

    def on_option_list_option_selected(self, evento: OptionList.OptionSelected):
        evento.prevent_default()
        destino = self.query_one(f"#{self.campo_lista or 'tag'}", Input)
        destino.value = str(evento.option.prompt)
        destino.cursor_position = len(destino.value)
        destino.focus()

    def action_volver_al_campo(self):
        self.query_one(f"#{self.campo_lista or 'tag'}", Input).focus()

    def _mover(self, widget, paso, guardar_al_final=False):
        orden = self._orden()
        ids = [f"#{w}" if not w.startswith('#') else w for w in orden]
        actual = f"#{widget.id}"
        if actual not in ids:
            return
        i = ids.index(actual) + paso
        if i >= len(ids):
            if guardar_al_final:
                self.action_guardar()
            return
        self.query_one(ids[max(0, i)]).focus()

    # ---------------------------------------------------------
    # PLC
    def _consultar_plc(self, forzar=False):
        ip = self.query_one("#ip", Input).value.strip()
        if not ip:
            self._estado("Escribe la IP para leer programas y tags del PLC (opcional).")
            return
        if not self.explorador.disponible:
            self._estado("pylogix no está disponible: escribe el tag a mano.")
            return
        if ip == self.ip_consultada and not forzar:
            return
        self.ip_consultada = ip
        datos = self.explorador.controlador_en_cache(ip)
        if datos is not None:
            self._cargar_controlador(datos)
            return
        self.explorador.pedir_controlador(ip)
        self._estado(f"Leyendo programas y tags de {ip}… (puedes seguir escribiendo)")

    def _pedir_programa(self):
        ip = self.query_one("#ip", Input).value.strip()
        programa = logix_tools._sin_prefijo_programa(self.query_one("#programa", Input).value)
        if not (ip and programa and self.explorador.disponible):
            self.tags_programa = []
            return
        en_cache = self.explorador.programa_en_cache(ip, programa)
        if en_cache is not None:
            self.tags_programa = en_cache
        elif self.explorador.pedir_programa(ip, programa):
            self._estado(f"Leyendo tags del programa '{programa}'…")

    def _cargar_controlador(self, datos):
        self.tags_controlador, self.programas = datos['tags'], datos['programas']
        self._estado(f"{len(self.tags_controlador)} tag(s) del controlador · {len(self.programas)} programa(s). "
                     "Escribe para filtrar, ↓ para elegir de la lista.")
        if self.campo_lista:
            self._llenar_lista(self.campo_lista)

    def _revisar_plc(self):
        ip = self.query_one("#ip", Input).value.strip()
        for evento in self.explorador.resultados():
            tipo, ip_evento = evento[0], evento[1]
            if ip_evento != ip:
                continue
            if tipo == 'controlador':
                self._cargar_controlador(evento[2])
            elif tipo == 'programa':
                programa = logix_tools._sin_prefijo_programa(self.query_one("#programa", Input).value)
                if evento[2] == programa:
                    self.tags_programa = evento[3]
                    self._estado(f"Programa '{programa}': {len(evento[3])} tag(s).")
                    if self.campo_lista == 'tag':
                        self._llenar_lista('tag')
            elif tipo == 'error':
                self._estado(f"No se pudo leer del PLC ({evento[2]}). Escribe el tag a mano.", error=True)

    # ---------------------------------------------------------
    def action_guardar(self):
        ip = self.query_one("#ip", Input).value.strip()
        programa = self.query_one("#programa", Input).value.strip() if self._es_programa() else None
        tag = self.query_one("#tag", Input).value.strip()
        try:
            polling = int(self.query_one("#polling", Input).value.strip() or 100)
        except ValueError:
            self._estado("El polling debe ser un número de milisegundos.", error=True)
            return
        if not ip:
            self._estado("Falta la IP.", error=True)
            return
        if self._es_programa() and not programa:
            self._estado("Elegiste Subprograma: falta el nombre del programa.", error=True)
            return
        if not tag:
            self._estado("Falta el tag.", error=True)
            return
        self.dismiss({'ip': ip, 'tag': logix_tools.armar_ruta(programa, tag),
                      'polling_ms': max(polling, logix_tools.POLLING_MIN_MS),
                      'comentario': self.query_one("#comentario", Input).value.strip()})
