"""
bitacora.py -- bitácora de turno en V3 (tabla 'bitacora' de eliza.db).

/bitacora              captura un registro nuevo (formulario)
/bitacora <fecha>      visor del día: hoy, ayer, DD, MM/DD, MM/DD/YYYY, YYYY-MM-DD

Teclas del visor:
    ← / →   día anterior / siguiente       n   nuevo registro (con la fecha que ves)
    Enter/e editar registro                Supr borrar (pide confirmar)
    y       copiar el día al portapapeles (formato Excel, igual que V2)
    x       exportar el día a .tsv         /   filtrar    Esc volver

Fecha y hora de un registro nuevo se llenan solas (hora redondeada a 5 min).
Línea y Falla son obligatorios; Tiempo vacío = 15.
"""

import getpass
import os
import socket
import subprocess
from datetime import datetime, timedelta

from textual import work
from textual.binding import Binding

import bitacora_tools
import db
from ui.formulario import Campo, Formulario
from ui.modales import Confirmar, PedirTexto
from ui.pantalla import PantallaTabla

TIEMPO_POR_DEFECTO = "15"
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def fecha_legible(fecha):
    """'2026-10-20' -> 'martes 20/10/2026' (sin depender del idioma de Windows)."""
    try:
        d = datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        return fecha
    return f"{DIAS[d.weekday()]} {d:%d/%m/%Y}"


def campos_registro(r=None, fecha=None, hora=None):
    r = r or {}
    return [Campo('fecha', "Fecha", r.get('fecha', fecha), obligatorio=True, ayuda="YYYY-MM-DD"),
            Campo('hora', "Hora", r.get('hora', hora), obligatorio=True, ayuda="HH:MM:SS"),
            Campo('linea', "Línea", r.get('linea', ''), obligatorio=True),
            Campo('estacion', "Estación", r.get('estacion', '')),
            Campo('prefijo', "Prefijo", r.get('prefijo', '')),
            Campo('auditor', "Auditor", r.get('auditor', '')),
            Campo('tiempo', "Tiempo (min)", r.get('tiempo', ''), ayuda=f"vacío = {TIEMPO_POR_DEFECTO}"),
            Campo('falla', "Falla", r.get('falla', ''), obligatorio=True),
            Campo('ajuste', "Ajuste", r.get('ajuste', '')),
            Campo('comentarios', "Comentarios", r.get('comentarios', ''))]


def validar_registro(datos):
    try:
        datetime.strptime(datos['fecha'], "%Y-%m-%d")
    except ValueError:
        return "Fecha inválida (usa YYYY-MM-DD)."
    try:
        datetime.strptime(datos['hora'], "%H:%M:%S")
    except ValueError:
        try:
            datos['hora'] = datetime.strptime(datos['hora'], "%H:%M").strftime("%H:%M:%S")
        except ValueError:
            return "Hora inválida (usa HH:MM o HH:MM:SS)."
    return None


async def capturar(app, bd, fecha=None):
    """Formulario de registro nuevo. Devuelve el registro guardado o None."""
    momento = bitacora_tools.redondear_hora_5min()
    datos = await app.push_screen_wait(Formulario(
        "BITÁCORA :: nuevo registro",
        campos_registro(fecha=fecha or momento.strftime("%Y-%m-%d"), hora=momento.strftime("%H:%M:%S")),
        validar=validar_registro))
    if not datos:
        return None
    datos['tiempo'] = datos['tiempo'] or TIEMPO_POR_DEFECTO
    datos['equipo'] = socket.gethostname()
    datos['usuario'] = getpass.getuser()
    try:
        bd.agregar_bitacora(datos)
    except db.ErrorDB as e:
        app.aviso(f"NO se guardó el registro: {e}")
        return None
    app.ok(f"Bitácora: registro guardado ({datos['fecha']} {datos['hora']}, línea {datos['linea']})")
    return datos


def copiar_portapapeles(texto):
    """clip.exe en UTF-16: así los acentos llegan bien a Excel."""
    proceso = subprocess.Popen(['clip'], stdin=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    proceso.communicate(input=texto.encode('utf-16'))
    return proceso.returncode == 0


class PantallaBitacora(PantallaTabla):
    COLUMNAS = [('turno', "T", 3), ('hora', "HORA", 9), ('linea', "LÍNEA", 7), ('estacion', "EST", 6),
                ('tiempo', "MIN", 5), ('falla', "FALLA", 30), ('ajuste', "AJUSTE", 30), ('auditor', "AUDITOR", 12),
                ('prefijo', "PREFIJO", 9), ('comentarios', "COMENTARIOS", None)]
    ACCION_ENTER = "editar"
    BINDINGS = PantallaTabla.BINDINGS + [
        Binding("left", "dia(-1)", "Día anterior", key_display="←"),
        Binding("right", "dia(1)", "Día siguiente", key_display="→"),
        Binding("n", "nuevo", "Nuevo"),
        Binding("enter", "editar", "Editar"),
        Binding("e", "editar", show=False),
        Binding("delete", "borrar", "Borrar", key_display="Supr"),
        Binding("y", "copiar", "Copiar Excel"),
        Binding("x", "exportar", "Exportar .tsv"),
    ]

    def __init__(self, bd, fecha):
        super().__init__()
        self.bd = bd
        self.fecha = fecha
        self.registros = []

    def preparar(self):
        self.cargar()

    def cargar(self):
        self.registros = self.bd.bitacora_dia(self.fecha)

    def filas(self):
        for r in self.registros:
            yield r['id'], [bitacora_tools.calcular_turno(r['hora']), r['hora'], r['linea'], r['estacion'],
                            r['tiempo'], r['falla'], r['ajuste'], r['auditor'], r['prefijo'], r['comentarios']]

    def al_refrescar(self):
        self.titulo(f"BITÁCORA  ·  {fecha_legible(self.fecha)}  ·  {len(self.registros)} registro(s)")
        if not self.registros:
            fechas = self.bd.bitacora_fechas(8)
            self.estado("Sin registros este día." + (f" Días con registros: {', '.join(fechas)}" if fechas else ""))

    def _actual(self):
        clave = self.fila_actual()
        return next((r for r in self.registros if str(r['id']) == str(clave)), None)

    def action_dia(self, paso):
        self.fecha = (datetime.strptime(self.fecha, "%Y-%m-%d") + timedelta(days=paso)).strftime("%Y-%m-%d")
        self.cargar()
        self.estado("")
        self.refrescar(conservar=False)

    @work(exclusive=True, group="bitacora")
    async def action_nuevo(self):
        hoy = datetime.now().strftime("%Y-%m-%d")
        guardado = await capturar(self.app, self.bd, None if self.fecha == hoy else self.fecha)
        if guardado:
            self.fecha = guardado['fecha']
            self.cargar()
            self.refrescar(conservar=False)
            self.estado("Registro guardado.")

    @work(exclusive=True, group="bitacora")
    async def action_editar(self):
        r = self._actual()
        if not r:
            return
        datos = await self.app.push_screen_wait(Formulario(
            "BITÁCORA :: editar registro", campos_registro(r), validar=validar_registro))
        if not datos:
            return
        try:
            self.bd.actualizar_bitacora(r['id'], datos)
        except db.ErrorDB as e:
            self.estado(str(e), error=True)
            return
        self.cargar()
        self.refrescar()
        self.estado("Registro actualizado.")

    @work(exclusive=True, group="bitacora")
    async def action_borrar(self):
        r = self._actual()
        if r and await self.app.push_screen_wait(Confirmar(
                "Borrar registro", f"¿Borrar el registro de las {r['hora']} (línea {r['linea']}: {r['falla']})?",
                si="Borrar", no="Cancelar")):
            self.bd.borrar_bitacora(r['id'])
            self.cargar()
            self.refrescar()
            self.estado("Registro borrado.")

    def action_copiar(self):
        if not self.registros:
            self.estado("No hay registros para copiar.", error=True)
            return
        try:
            ok = copiar_portapapeles(bitacora_tools.formatear_tsv(self.registros))
        except OSError as e:
            self.estado(f"No se pudo copiar: {e}", error=True)
            return
        self.estado(f"Copiado al portapapeles ({len(self.registros)} registro(s)). Pégalo en Excel."
                    if ok else "No se pudo copiar al portapapeles.", error=not ok)

    @work(exclusive=True, group="bitacora")
    async def action_exportar(self):
        if not self.registros:
            self.estado("No hay registros para exportar.", error=True)
            return
        defecto = os.path.join(self.bd.carpeta, f"bitacora_{self.fecha}.tsv")
        ruta = await self.app.push_screen_wait(PedirTexto("Exportar bitácora", "Ruta del archivo .tsv", defecto))
        if not ruta:
            return
        try:
            with open(ruta, 'w', encoding='utf-8-sig', newline='\r\n') as f:
                f.write(bitacora_tools.formatear_tsv(self.registros))
        except OSError as e:
            self.estado(f"No se pudo exportar: {e}", error=True)
            return
        self.estado(f"Exportado a {ruta}")
