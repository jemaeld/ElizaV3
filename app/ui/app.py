"""
app.py -- aplicación Textual de Eliza V3.

Pantalla principal (todo con teclado):

    ┌ logo dorado ✦ ───────────────────────── info (usuario, equipo, datos) ┐
    │ resultados: CAT | NOMBRE | IP | DETALLE      (se filtra mientras escribes)
    │ registro de mensajes
    │ ELIZA> _                                      línea de comandos
    └ pie con teclas

- Escribe parte de un nombre, IP o comentario: la tabla se filtra en vivo.
  ↑/↓ (o PgUp/PgDn) eligen; Enter ejecuta la entrada; Tab completa el nombre.
- Escribe "/" para ver y filtrar los comandos.

PARA AGREGAR UN COMANDO: método  cmd_xxx(self, arg)  y una línea en
COMANDOS (al final de la clase). Aparece solo en la lista y en la ayuda.
"""

import getpass
import importlib.util
import json
import os
import re
import traceback
from datetime import datetime

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Input, RichLog, Static

import acciones
import bitacora_tools
import db
import licencia
import migrar_v2
import network_tools
import rutas
from ui import alta, bitacora, modales
from ui.editor import PantallaEditor
from ui.scan_acd import PantallaScanACD
from ui.logo import logo

VERSION = "ELIZA v3"
COLOR_CATEGORIA = {'vnc': "#00ffff", 'apps': "#ffff66", 'acd': "#ff66ff"}
CATEGORIAS_CON_IP = ('vnc', 'acd')
CODIGO_REINICIAR = 10


def orden_natural(texto):
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in re.split(r'(\d+)', str(texto).lower())]


def version_instalada():
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION.json")
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        return f"{datos.get('commit', '')[:7]} ({(datos.get('fecha') or '')[:10]})"
    except (OSError, json.JSONDecodeError):
        return "dev"


class LineaComandos(Input):
    """El Input deja pasar ↑/↓/PgUp/PgDn/Tab a la app (mueven la tabla / completan)."""
    BINDINGS = [
        Binding("up", "app.mover(-1)", show=False, priority=True),
        Binding("down", "app.mover(1)", show=False, priority=True),
        Binding("pageup", "app.mover(-10)", show=False, priority=True),
        Binding("pagedown", "app.mover(10)", show=False, priority=True),
        Binding("tab", "app.completar", show=False, priority=True),
    ]


class ElizaApp(App):
    CSS_PATH = "tema.tcss"
    TITLE = VERSION
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("f1", "ayuda", "Ayuda"),
        Binding("f5", "recargar", "Recargar"),
        Binding("ctrl+l", "limpiar", "Limpiar registro"),
        Binding("escape", "borrar_linea", "Borrar línea", show=False),
        Binding("ctrl+q", "salir", "Salir", priority=True),
    ]

    def __init__(self):
        super().__init__()
        self.bd = None
        self.carpeta = None
        self.modo_datos = "-"
        self.config = {}
        self.entradas = []
        self.filas_visibles = []   # lo que muestra la tabla: ('entrada', dict) o ('comando', nombre)

    # ---------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Horizontal(id="cabecera"):
            yield Static(logo(), id="logo")
            yield Static("", id="info")
        tabla = DataTable(id="resultados", cursor_type="row", zebra_stripes=True)
        tabla.can_focus = False
        yield tabla
        yield RichLog(id="registro", markup=True, wrap=True, max_lines=500)
        with Horizontal(id="barra"):
            yield Static("ELIZA>", id="prompt")
            yield LineaComandos(placeholder="Escribe un nombre, IP o /comando…", id="linea")
        yield Footer()

    def on_mount(self):
        tabla = self.query_one("#resultados", DataTable)
        tabla.add_column("CAT", key="cat", width=6)
        tabla.add_column("NOMBRE", key="nombre", width=30)
        tabla.add_column("IP", key="ip", width=16)
        tabla.add_column("DETALLE", key="detalle")
        self.query_one("#linea").disabled = True
        self.arranque()

    # ---------------------------------------------------------
    # Mensajes
    def ok(self, texto):
        self.query_one("#registro", RichLog).write(Text.assemble(("[*] ", "bold #00ff00"), (texto, "#00ffff")))

    def aviso(self, texto):
        self.query_one("#registro", RichLog).write(Text.assemble(("[!] ", "bold #ff5555"), (texto, "#ffcc66")))

    def info(self, texto):
        self.query_one("#registro", RichLog).write(Text(texto, style="#00ffff"))

    def registrar_error(self, contexto):
        ruta = os.path.join(rutas.ruta_instalacion(), "eliza_error.log")
        try:
            with open(ruta, 'a', encoding='utf-8') as f:
                f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} | {contexto}\n{traceback.format_exc()}")
        except OSError:
            pass
        return ruta

    # ---------------------------------------------------------
    # Arranque: carpeta de datos -> base -> contraseña
    @work(exclusive=True, group="arranque")
    async def arranque(self, cambiar_carpeta=False):
        linea = self.query_one("#linea")
        linea.disabled = True

        if rutas.es_primer_arranque() or cambiar_carpeta:
            elegida = await self.elegir_carpeta(primera_vez=not cambiar_carpeta)
            if elegida is None:
                if cambiar_carpeta:
                    linea.disabled = False
                    linea.focus()
                    return
                self.exit(0)
                return

        carpeta, caida = rutas.resolver_carpeta()
        respaldo = False
        while caida:
            opcion = await self.push_screen_wait(modales.Menu(
                "Carpeta de datos remota no disponible",
                f"No se encuentra:\n{caida}\n\nSi estás en otra red (p. ej. después de /update), "
                "cambia a la red de planta y elige Reintentar.",
                [("r", "Reintentar"), ("l", "Usar datos LOCALES solo esta vez"), ("s", "Salir")],
                cancelable=False))
            if opcion == "s":
                self.exit(0)
                return
            if opcion == "l":
                carpeta, caida, respaldo = rutas.carpeta_local(), None, True
                os.makedirs(carpeta, exist_ok=True)
            elif rutas.remota_disponible(caida):
                carpeta, caida = caida, None

        if not db.existe(carpeta) and migrar_v2.es_carpeta_v2(carpeta):
            if not await self.ofrecer_migracion(carpeta):
                self.exit(0)
                return
        try:
            bd = db.BaseDatos(carpeta).inicializar()
        except db.ErrorDB as e:
            await self.push_screen_wait(modales.Reporte("Error de base de datos", str(e)))
            self.exit(0)
            return

        estado = licencia.estado(bd, respaldo_local=respaldo)
        if estado == 'bloqueado':
            await self.push_screen_wait(modales.Reporte(
                "ELIZA :: acceso",
                "Este equipo todavía no tiene acceso validado y la carpeta remota no está disponible.\n"
                "Conéctate a la red de planta y vuelve a abrir Eliza."))
            self.exit(0)
            return
        if estado == 'definir':
            if not await self.push_screen_wait(modales.Contrasena('definir', lambda v: licencia.definir(bd, v))):
                self.exit(0)
                return
        elif estado == 'verificar':
            if not await self.push_screen_wait(modales.Contrasena('verificar', lambda v: licencia.verificar(bd, v))):
                self.exit(0)
                return

        self.bd, self.carpeta = bd, carpeta
        self.modo_datos = "local (remota no disponible)" if respaldo else (
            "remota" if rutas.carpeta_remota() else "local")
        self.recargar(silencioso=True)
        if respaldo:
            self.aviso("Trabajando con datos LOCALES en esta sesión (la remota no estaba disponible).")
        self.ok(f"Base de datos: {self.bd.ruta}")
        linea.disabled = False
        linea.focus()

    async def elegir_carpeta(self, primera_vez):
        mensaje = ("Eliza guarda su base de datos (VNC/APPS/ACD, bitácora) en una carpeta.\n"
                   "Si tu equipo comparte una carpeta en red, elige la remota para usar la misma base.")
        while True:
            opcion = await self.push_screen_wait(modales.Menu(
                "BIENVENIDO A ELIZA v3 :: carpeta de datos" if primera_vez else "Carpeta de datos",
                mensaje, [("r", "Carpeta remota / compartida"), ("l", "Local en este equipo")],
                cancelable=not primera_vez))
            if opcion is None:
                return None
            if opcion == "l":
                return rutas.establecer_carpeta(None)
            ruta = await self.push_screen_wait(modales.PedirCarpeta(
                "Carpeta remota", "Escribe la ruta de la carpeta de datos compartida.",
                rutas.carpeta_remota() or ""))
            if ruta:
                return rutas.establecer_carpeta(ruta)

    async def ofrecer_migracion(self, carpeta):
        while True:
            opcion = await self.push_screen_wait(modales.Menu(
                "Datos de Eliza V2 encontrados",
                f"{carpeta}\n\nEsta carpeta tiene datos de Eliza V2 (JSON) y todavía no tiene eliza.db.\n"
                "La migración es de un solo uso: copia todo a eliza.db y NO modifica los archivos de V2.",
                [("simular", "Ver qué se va a migrar (simulación)"), ("migrar", "Migrar ahora"),
                 ("vacia", "Empezar con una base vacía"), ("salir", "Salir")], cancelable=False))
            if opcion == "salir":
                return False
            if opcion == "vacia":
                return True
            simular = opcion == "simular"
            try:
                reporte = await self.run_in_thread(migrar_v2.migrar, carpeta, None, simular)
                texto = reporte.texto()
            except (migrar_v2.ErrorMigracion, db.ErrorDB, OSError) as e:
                texto = f"[bold red]No se migró:[/] {e}"
            await self.push_screen_wait(modales.Reporte(
                "Simulación de migración" if simular else "Migración V2 → V3", texto))
            if not simular and db.existe(carpeta):
                return True

    async def run_in_thread(self, funcion, *args):
        """Corre algo lento (red, disco) sin congelar la pantalla."""
        import asyncio
        return await asyncio.get_running_loop().run_in_executor(None, funcion, *args)

    # ---------------------------------------------------------
    # Datos y tabla
    def recargar(self, silencioso=False):
        self.config = self.bd.config()
        self.entradas = sorted(self.bd.entradas(), key=lambda e: (e['categoria'], orden_natural(e['nombre'])))
        self.actualizar_info()
        self.filtrar(self.query_one("#linea", Input).value)
        if not silencioso:
            self.ok(f"Base recargada: {len(self.entradas)} entradas.")

    def actualizar_info(self):
        conteo = {}
        for e in self.entradas:
            conteo[e['categoria']] = conteo.get(e['categoria'], 0) + 1
        resumen = " · ".join(f"{c.upper()} {n}" for c, n in sorted(conteo.items())) or "sin entradas"
        filas = [("Usuario", getpass.getuser()), ("Equipo/IP", network_tools.ip_principal()),
                 ("Datos", self.modo_datos), ("Base", resumen), ("Versión", f"{VERSION} · {version_instalada()}")]
        texto = Text()
        for i, (etiqueta, valor) in enumerate(filas):
            texto.append(f"{etiqueta:<10}", style="bold #ff66ff")
            texto.append(str(valor), style="#00ffff")
            if i < len(filas) - 1:
                texto.append("\n")
        self.query_one("#info", Static).update(texto)

    def on_input_changed(self, evento: Input.Changed):
        if evento.input.id == "linea":
            self.filtrar(evento.value)

    def filtrar(self, texto):
        tabla = self.query_one("#resultados", DataTable)
        tabla.clear()
        self.filas_visibles = []
        texto = texto.strip()
        if texto.startswith('/'):
            palabra = texto.split(' ', 1)[0].lower()
            for nombre, (descripcion, _) in self.COMANDOS.items():
                if nombre.startswith(palabra) or (' ' in texto and nombre == palabra):
                    tabla.add_row(Text("CMD", style="bold #5f87ff"), Text(nombre, style="bold"), "", descripcion)
                    self.filas_visibles.append(('comando', nombre))
            return
        palabras = texto.lower().split()
        for e in self.entradas:
            pajar = f"{e['categoria']} {e['nombre']} {e['ip']} {e['comentario']} {e['info']}".lower()
            if all(p in pajar for p in palabras):
                color = COLOR_CATEGORIA.get(e['categoria'], "#ffffff")
                tabla.add_row(Text(e['categoria'].upper(), style=f"bold {color}"), e['nombre'], e['ip'],
                              e['comentario'] or e['info'])
                self.filas_visibles.append(('entrada', e))
        if texto and not self.filas_visibles:
            self.filas_visibles = []

    def action_mover(self, paso):
        tabla = self.query_one("#resultados", DataTable)
        if tabla.row_count:
            tabla.move_cursor(row=max(0, min(tabla.row_count - 1, tabla.cursor_row + paso)))

    def _seleccionada(self):
        tabla = self.query_one("#resultados", DataTable)
        if not self.filas_visibles or tabla.cursor_row is None or tabla.cursor_row >= len(self.filas_visibles):
            return None
        return self.filas_visibles[tabla.cursor_row]

    def action_completar(self):
        fila = self._seleccionada()
        linea = self.query_one("#linea", Input)
        if fila is None:
            return
        linea.value = (fila[1] + " ") if fila[0] == 'comando' else fila[1]['nombre']
        linea.cursor_position = len(linea.value)

    def action_borrar_linea(self):
        self.query_one("#linea", Input).value = ""

    def action_limpiar(self):
        self.query_one("#registro", RichLog).clear()

    def action_recargar(self):
        if self.bd:
            self.recargar()

    def action_ayuda(self):
        self.cmd_help("")

    def action_salir(self):
        self.exit(0)

    # ---------------------------------------------------------
    # Ejecutar
    def on_input_submitted(self, evento: Input.Submitted):
        if evento.input.id != "linea" or self.bd is None:
            return
        texto = evento.value.strip()
        try:
            self.ejecutar_linea(texto)
        except Exception as e:
            ruta = self.registrar_error(texto)
            self.aviso(f"Error inesperado: {e} (detalle en {ruta})")

    def ejecutar_linea(self, texto):
        if texto.lower() in ('exit', 'quit', 'salir'):
            self.exit(0)
            return
        if texto.startswith('/'):
            comando, _, arg = texto.partition(' ')
            comando = comando.lower()
            if comando not in self.COMANDOS:
                fila = self._seleccionada()  # "/re" + Enter ejecuta el comando resaltado
                if fila and fila[0] == 'comando':
                    comando = fila[1]
                else:
                    self.aviso(f"Comando no reconocido: {comando}. F1 para ayuda.")
                    return
            self.query_one("#linea", Input).value = ""
            self.COMANDOS[comando][1](self, arg.strip())
            return
        fila = self._seleccionada()
        if fila is None:
            if texto:
                self.aviso("Nada coincide. Escribe parte del nombre, IP o comentario, o /comando.")
            return
        if fila[0] == 'comando':
            self.query_one("#linea", Input).value = ""
            self.COMANDOS[fila[1]][1](self, "")
            return
        exito, mensaje = acciones.ejecutar(fila[1], self.carpeta, self.config)
        (self.ok if exito else self.aviso)(mensaje)
        if exito:
            self.query_one("#linea", Input).value = ""

    # ---------------------------------------------------------
    # Comandos
    def resolver_ip(self, argumento):
        buscado = argumento.strip().lower()
        coincidencias = [e for e in self.entradas
                         if e['categoria'] in CATEGORIAS_CON_IP and e['nombre'].lower() == buscado]
        if len(coincidencias) > 1:
            return None, f"Hay {len(coincidencias)} entradas llamadas '{argumento}'. Usa la IP directamente."
        if coincidencias:
            ip = acciones.ip_de_entrada(coincidencias[0])
            return (ip, None) if ip else (None, f"'{coincidencias[0]['nombre']}' no tiene IP registrada.")
        return argumento.strip(), None

    def cmd_ip(self, arg):
        self.info("── Interfaces de red ──")
        for detalle in network_tools.interfaces_ipv4():
            self.info(f"  {detalle}")

    def cmd_ping(self, arg):
        if not arg:
            fila = self._seleccionada()
            arg = fila[1]['nombre'] if fila and fila[0] == 'entrada' else ""
        if not arg:
            self.aviso("Uso: /ping <ip o nombre>  (o selecciona una entrada y escribe /ping)")
            return
        ip, error = self.resolver_ip(arg)
        if error:
            self.aviso(error)
            return
        exito, mensaje = network_tools.lanzar_ping(ip)
        (self.ok if exito else self.aviso)(mensaje)

    def cmd_reload(self, arg):
        self.recargar()

    def cmd_settings(self, arg):
        self.arranque(cambiar_carpeta=True)

    def cmd_help(self, arg):
        lineas = ["[bold #ffd700]COMANDOS[/]"]
        for nombre, (descripcion, _) in self.COMANDOS.items():
            lineas.append(f"  [bold #00ff00]{nombre:<10}[/] {descripcion}")
        teclas = [("Escribir", "filtra por nombre, IP o comentario (varias palabras: todas)"),
                  ("↑ ↓ PgUp PgDn", "eligen en la tabla"), ("Enter", "ejecuta la entrada o el comando"),
                  ("Tab", "completa el nombre"), ("/", "lista los comandos"), ("Esc", "borra la línea"),
                  ("F1 · F5", "ayuda · recargar"), ("Ctrl+L · Ctrl+Q", "limpia el registro · salir")]
        lineas += ["", "[bold #ffd700]TECLADO[/]"]
        lineas += [f"  [bold #00ff00]{tecla:<16}[/] {texto}" for tecla, texto in teclas]
        lineas += ["", f"[dim]Datos: {self.carpeta}[/]"]
        self.push_screen(modales.Reporte("Ayuda", "\n".join(lineas)))

    @work(exclusive=True, group="pantalla")
    async def cmd_edit(self, arg):
        if await self.push_screen_wait(PantallaEditor(self.bd, arg or None)):
            self.recargar()

    @work(exclusive=True, group="pantalla")
    async def cmd_add(self, arg):
        if await alta.alta(self, self.bd, arg or None):
            self.recargar()

    @work(exclusive=True, group="pantalla")
    async def cmd_scan_acd(self, arg):
        if await self.push_screen_wait(PantallaScanACD(self.bd, arg or None)):
            self.recargar()

    @work(exclusive=True, group="pantalla")
    async def cmd_bitacora(self, arg):
        if not arg:
            await bitacora.capturar(self, self.bd)
            return
        fecha, error = bitacora_tools.resolver_fecha_arg(arg)
        if error:
            self.aviso(error)
            return
        await self.push_screen_wait(bitacora.PantallaBitacora(self.bd, fecha))

    def cmd_clear(self, arg):
        self.action_limpiar()

    def cmd_salir(self, arg):
        self.exit(0)

    @work(exclusive=True, group="update")
    async def cmd_update(self, arg):
        instalador_ruta = os.path.join(rutas.ruta_instalacion(), "Eliza.py")
        if os.path.isdir(os.path.join(rutas.ruta_instalacion(), ".git")):
            self.aviso("Esta copia es el repositorio de desarrollo: actualiza con 'git pull'.")
            return
        try:
            spec = importlib.util.spec_from_file_location("eliza_instalador", instalador_ruta)
            instalador = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(instalador)
        except Exception as e:
            self.aviso(f"No se pudo cargar Eliza.py: {e}")
            return
        self.info("Consultando GitHub…")
        try:
            instalada, disponible, hay_nueva = await self.run_in_thread(instalador.hay_actualizacion, False)
        except instalador.ErrorActualizacion as e:
            self.aviso(str(e))
            return
        self.info(f"Instalada : {instalador.describir(instalada)}")
        self.info(f"Disponible: {instalador.describir(disponible)}")
        if not hay_nueva:
            self.ok("Ya tienes la última versión.")
            return
        if not await self.push_screen_wait(modales.Confirmar(
                "Actualización disponible", f"{instalador.describir(disponible)}\n\n¿Instalar y reiniciar Eliza?",
                si="Instalar y reiniciar", no="Ahora no")):
            return
        try:
            await self.run_in_thread(instalador.instalar, disponible, False)
        except (instalador.ErrorActualizacion, OSError) as e:
            self.aviso(f"No se actualizó: {e}")
            return
        self.exit(CODIGO_REINICIAR)

    COMANDOS = {
        '/bitacora': ("Sin fecha: nuevo registro. Con fecha (hoy, ayer, DD, MM/DD): visor del día", cmd_bitacora),
        '/edit':     ("Editor de la base (opcional: vnc, apps, acd)", cmd_edit),
        '/add':      ("Agregar VNC/APPS desde un archivo .vnc, .lnk o .exe", cmd_add),
        '/scan_acd': ("Buscar proyectos ACD/L5K en una carpeta y registrarlos", cmd_scan_acd),
        '/ip':       ("Interfaces de red de este equipo", cmd_ip),
        '/ping':     ("Ping a una IP o entrada VNC/ACD (ventana aparte)", cmd_ping),
        '/reload':   ("Vuelve a leer la base (si otro equipo la cambió)", cmd_reload),
        '/settings': ("Cambia la carpeta de datos (remota o local)", cmd_settings),
        '/update':   ("Busca y descarga la última versión desde GitHub", cmd_update),
        '/clear':    ("Limpia el registro de mensajes", cmd_clear),
        '/help':     ("Ayuda: comandos y teclado (F1)", cmd_help),
        '/salir':    ("Cierra Eliza (Ctrl+Q)", cmd_salir),
    }
