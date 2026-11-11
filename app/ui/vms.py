"""
vms.py -- /vm [nombre]: máquinas virtuales de VMware Workstation.

    ESTADO | NOMBRE | VNC | COMENTARIO | VMX

Teclas:
    Enter   apagada -> arrancar · corriendo -> conectar VNC
    a       arrancar (sin ventana de VMware)
    s       apagado limpio (pide confirmar)
    f       forzar apagado (pide confirmar)
    v       conectar VNC (VNC propio de VMware, 127.0.0.1:puerto)
    r       refrescar estado          /  filtrar          Esc volver

El estado se lee con 'vmrun list' cada 10 s y después de cada acción.
Arrancar NO conecta el VNC solo: hay VMs que se usan por SSH.
"""

import os

from rich.text import Text
from textual import work
from textual.binding import Binding

import acciones
import rutas
import vm_tools
from ui.modales import Confirmar
from ui.pantalla import PantallaTabla

ESTILOS = {vm_tools.CORRIENDO: ("● corriendo", "bold #00ff00"), vm_tools.APAGADA: ("○ apagada", "#888888"),
           vm_tools.NO_DISPONIBLE: ("× no en esta PC", "#ff5555")}


def texto_estado(estado, ocupada=None):
    if ocupada:
        return Text(f"… {ocupada}", style="bold #ffcc00")
    texto, estilo = ESTILOS.get(estado, ("? desconocido", "#ffcc00"))
    return Text(texto, style=estilo)


class PantallaVMs(PantallaTabla):
    COLUMNAS = [('estado', "ESTADO", 16), ('nombre', "NOMBRE", 24), ('vnc', "VNC", 18),
                ('comentario', "COMENTARIO", 34), ('vmx', "VMX", None)]
    ACCION_ENTER = "principal"
    BINDINGS = PantallaTabla.BINDINGS + [
        Binding("a", "arrancar", "Arrancar"),
        Binding("s", "apagar", "Apagar"),
        Binding("f", "forzar", "Forzar apagado"),
        Binding("v", "vnc", "VNC"),
        Binding("r", "refrescar_estado", "Refrescar"),
    ]

    def __init__(self, bd, nombre_inicial=""):
        super().__init__()
        self.bd = bd
        self.nombre_inicial = nombre_inicial
        self.vmrun = vm_tools.encontrar_vmrun(rutas.leer_local())
        self.vms = []
        self.encendidas = set()
        self.ocupadas = {}          # id -> "arrancando" / "apagando"
        self.error_estado = ""

    # ---------------------------------------------------------
    def preparar(self):
        self.vms = sorted(self.bd.entradas('vm'), key=lambda e: e['nombre'].lower())

    def despues_de_montar(self):
        if self.nombre_inicial:
            for e in self.vms:
                if e['nombre'].lower() == self.nombre_inicial.lower():
                    self.refrescar()
                    self.tabla.move_cursor(row=self.tabla.get_row_index(str(e['id'])))
        if not self.vms:
            self.estado("No hay VMs. Agrégalas con /add eligiendo su archivo .vmx.")
        elif not self.vmrun:
            self.estado("No se encontró vmrun.exe (VMware Workstation). Indica su ruta en eliza_local.json "
                        "como \"vmrun\".", error=True)
        self.leer_estado()
        self.set_interval(10, self.leer_estado)

    def filas(self):
        for e in self.vms:
            estado = vm_tools.estado(e, self.encendidas)
            yield e['id'], [texto_estado(estado, self.ocupadas.get(e['id'])), e['nombre'], e['ip'] or "—",
                            e['comentario'] or "", vm_tools.ruta_vmx(e)]

    def al_refrescar(self):
        corriendo = sum(1 for e in self.vms if vm_tools.estado(e, self.encendidas) == vm_tools.CORRIENDO)
        self.titulo(f"MÁQUINAS VIRTUALES  ·  {len(self.vms)} VM(s)  ·  {corriendo} corriendo")

    def _actual(self):
        clave = self.fila_actual()
        return next((e for e in self.vms if str(e['id']) == clave), None) if clave is not None else None

    # ---------------------------------------------------------
    @work(thread=True, exclusive=True, group="vm_estado", exit_on_error=False)
    def leer_estado(self):
        if not self.vmrun or not self.vms:
            return
        try:
            encendidas, error = vm_tools.encendidas(self.vmrun), ""
        except vm_tools.ErrorVM as e:
            encendidas, error = self.encendidas, str(e)
        self.app.call_from_thread(self._estado_leido, encendidas, error)

    def _estado_leido(self, encendidas, error):
        cambio = encendidas != self.encendidas
        self.encendidas = encendidas
        if error and error != self.error_estado:
            self.estado(f"No se pudo leer el estado: {error}", error=True)
        self.error_estado = error
        if cambio or not self.tabla.row_count:
            self.refrescar()

    # ---------------------------------------------------------
    def action_principal(self):
        e = self._actual()
        if not e:
            return
        if vm_tools.estado(e, self.encendidas) == vm_tools.CORRIENDO:
            self.action_vnc()
        else:
            self.action_arrancar()

    def action_vnc(self):
        e = self._actual()
        if not e:
            return
        if not e['ip']:
            self.estado(f"{e['nombre']} no tiene VNC configurado (edítala en /edit vm: 127.0.0.1:puerto).",
                        error=True)
            return
        if vm_tools.estado(e, self.encendidas) != vm_tools.CORRIENDO:
            self.estado(f"{e['nombre']} está apagada: arráncala primero (a).", error=True)
            return
        ok, mensaje = acciones.ejecutar({'categoria': 'vnc', 'nombre': e['nombre'], 'ip': e['ip']},
                                        self.app.carpeta, self.app.config)
        self.estado(mensaje, error=not ok)
        if ok:
            self.app.registrar_apertura(e)

    def action_arrancar(self):
        e = self._actual()
        if not e:
            return
        estado = vm_tools.estado(e, self.encendidas)
        if estado == vm_tools.CORRIENDO:
            self.estado(f"{e['nombre']} ya está corriendo.")
        elif estado == vm_tools.NO_DISPONIBLE:
            self.estado(f"No existe {vm_tools.ruta_vmx(e)} en esta PC.", error=True)
        else:
            self._ejecutar(e, "arrancando", vm_tools.arrancar)

    @work(exclusive=True, group="vm_confirmar", exit_on_error=False)
    async def action_apagar(self):
        await self._apagar(forzado=False)

    @work(exclusive=True, group="vm_confirmar", exit_on_error=False)
    async def action_forzar(self):
        await self._apagar(forzado=True)

    async def _apagar(self, forzado):
        e = self._actual()
        if not e:
            return
        if vm_tools.estado(e, self.encendidas) != vm_tools.CORRIENDO:
            self.estado(f"{e['nombre']} no está corriendo.")
            return
        if forzado:
            pregunta = (f"¿FORZAR el apagado de {e['nombre']}?\n\nEs como desconectarle la corriente: "
                        "se pierde lo que no esté guardado dentro de la VM.")
        else:
            pregunta = f"¿Apagar {e['nombre']}?\n\nSe le pide a la VM que se apague limpio (como Inicio → Apagar)."
        if not await self.app.push_screen_wait(Confirmar("Forzar apagado" if forzado else "Apagar VM", pregunta,
                                                         si="Forzar" if forzado else "Apagar", no="Cancelar")):
            return
        self._ejecutar(e, "apagando", lambda vmrun, entrada: vm_tools.apagar(vmrun, entrada, forzado))

    def _ejecutar(self, e, que, funcion):
        if e['id'] in self.ocupadas:
            self.estado(f"{e['nombre']} ya está {self.ocupadas[e['id']]}…")
            return
        self.ocupadas[e['id']] = que
        self.refrescar()
        self.estado(f"{e['nombre']}: {que}…")
        self._en_segundo_plano(e, funcion)

    @work(thread=True, exit_on_error=False)
    def _en_segundo_plano(self, e, funcion):
        try:
            ok, mensaje = True, funcion(self.vmrun, e)
        except vm_tools.ErrorVM as error:
            ok, mensaje = False, f"{e['nombre']}: {error}"
        self.app.call_from_thread(self._terminado, e, ok, mensaje)

    def _terminado(self, e, ok, mensaje):
        self.ocupadas.pop(e['id'], None)
        self.estado(mensaje, error=not ok)
        (self.app.ok if ok else self.app.aviso)(mensaje)
        self.leer_estado()
        self.refrescar()

    def action_refrescar_estado(self):
        self.leer_estado()
        self.estado("Estado actualizado.")

    def action_cerrar(self):
        self.dismiss(None)


def es_vmx(ruta):
    return os.path.splitext(ruta)[1].lower() == '.vmx'
