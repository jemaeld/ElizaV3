"""
bitacora.py -- bitácora de turno en V3.

Se guarda en JSON EXACTAMENTE como V2 (ver bitacora_json.py):
<carpeta de datos>/bitacora/YYYY-MM-DD.json, un archivo por día, mismas
claves y formato. V2, V3 y otros programas usan los mismos archivos.

/bitacora              captura un registro nuevo (formulario)
/bitacora <fecha>      visor del día: hoy, ayer, DD, MM/DD, MM/DD/YYYY, YYYY-MM-DD

Teclas del visor:
    ← / →   día anterior / siguiente       n   nuevo registro (con la fecha que ves)
    Enter/e editar registro                Supr borrar (pide confirmar)
    y       copiar el día al portapapeles (formato Excel, igual que V2)
    x       exportar el día a .tsv         /   filtrar    Esc volver

El visor se recarga solo si el archivo del día cambia (otro equipo o programa).
Fecha y hora de un registro nuevo se llenan solas (hora redondeada a 5 min).
Línea y Falla son obligatorios; Tiempo vacío = 15.
"""

import os
import subprocess
from datetime import datetime, timedelta

from textual import work
from textual.binding import Binding

import bitacora_json
import bitacora_tools
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
        datos['fecha'] = datetime.strptime(datos['fecha'], "%Y-%m-%d").strftime("%Y-%m-%d")
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


async def capturar(app, carpeta, fecha=None):
    """Formulario de registro nuevo. Devuelve el registro guardado o None."""
    momento = bitacora_tools.redondear_hora_5min()
    datos = await app.push_screen_wait(Formulario(
        "BITÁCORA :: nuevo registro",
        campos_registro(fecha=fecha or momento.strftime("%Y-%m-%d"), hora=momento.strftime("%H:%M:%S")),
        validar=validar_registro))
    if not datos:
        return None
    datos['tiempo'] = datos['tiempo'] or TIEMPO_POR_DEFECTO
    try:
        ruta = await app.run_in_thread(bitacora_json.agregar, carpeta, datos)
    except (bitacora_json.ErrorBitacora, OSError) as e:
        app.aviso(f"NO se guardó el registro: {e}")
        return None
    app.ok(f"Bitácora: registro guardado en {os.path.relpath(ruta, carpeta)} "
           f"({datos['hora']}, línea {datos['linea']})")
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
        Binding("e", "editar", show=False),
        Binding("delete", "borrar", "Borrar", key_display="Supr"),
        Binding("y", "copiar", "Copiar Excel"),
        Binding("x", "exportar", "Exportar .tsv"),
    ]

    def __init__(self, carpeta, fecha):
        super().__init__()
        self.carpeta = carpeta
        self.fecha = fecha
        self.registros = []
        self._firma = None

    def preparar(self):
        self.cargar()

    def despues_de_montar(self):
        # Otros equipos/programas escriben los mismos archivos: si el del día
        # cambia en disco, se recarga solo.
        self.set_interval(2, self._vigilar)

    def _firma_archivo(self):
        try:
            st = os.stat(bitacora_json.ruta_dia(self.carpeta, self.fecha))
            return (st.st_mtime, st.st_size)
        except OSError:
            return None

    def cargar(self):
        self.registros = bitacora_json.cargar_dia(self.carpeta, self.fecha)
        self._firma = self._firma_archivo()

    def _vigilar(self):
        if self._firma_archivo() != self._firma:
            self.cargar()
            self.refrescar()

    def filas(self):
        for i, r in enumerate(self.registros):
            r = bitacora_json.normalizar(r)
            yield i, [bitacora_tools.calcular_turno(r['hora']), r['hora'], r['linea'], r['estacion'],
                      r['tiempo'], r['falla'], r['ajuste'], r['auditor'], r['prefijo'], r['comentarios']]

    def al_refrescar(self):
        self.titulo(f"BITÁCORA  ·  {fecha_legible(self.fecha)}  ·  {len(self.registros)} registro(s)  ·  "
                    f"bitacora/{self.fecha}.json")
        if not self.registros:
            fechas = bitacora_json.fechas_disponibles(self.carpeta, 8)
            self.estado("Sin registros este día." + (f" Días con registros: {', '.join(fechas)}" if fechas else ""))

    def _actual(self):
        clave = self.fila_actual()
        if clave is None:
            return None, None
        i = int(clave)
        return (i, self.registros[i]) if 0 <= i < len(self.registros) else (None, None)

    def action_dia(self, paso):
        self.fecha = (datetime.strptime(self.fecha, "%Y-%m-%d") + timedelta(days=paso)).strftime("%Y-%m-%d")
        self.cargar()
        self.estado("")
        self.refrescar(conservar=False)

    @work(exclusive=True, group="bitacora")
    async def action_nuevo(self):
        hoy = datetime.now().strftime("%Y-%m-%d")
        guardado = await capturar(self.app, self.carpeta, None if self.fecha == hoy else self.fecha)
        if guardado:
            self.fecha = guardado['fecha']
            self.cargar()
            self.refrescar(conservar=False)
            self.tabla.move_cursor(row=self.tabla.row_count - 1)
            self.estado("Registro guardado.")

    @work(exclusive=True, group="bitacora")
    async def action_editar(self):
        i, original = self._actual()
        if original is None:
            return
        datos = await self.app.push_screen_wait(Formulario(
            "BITÁCORA :: editar registro", campos_registro(bitacora_json.normalizar(original)),
            validar=validar_registro))
        if not datos:
            return
        try:
            await self.app.run_in_thread(bitacora_json.actualizar, self.carpeta, self.fecha, i, original, datos)
        except (bitacora_json.ErrorBitacora, OSError) as e:
            self.estado(str(e), error=True)
            self.cargar()
            self.refrescar()
            return
        self.cargar()
        self.refrescar()
        self.estado("Registro actualizado." if datos['fecha'] == self.fecha
                    else f"Registro movido a bitacora/{datos['fecha']}.json")

    @work(exclusive=True, group="bitacora")
    async def action_borrar(self):
        i, r = self._actual()
        if r is None:
            return
        if not await self.app.push_screen_wait(Confirmar(
                "Borrar registro", f"¿Borrar el registro de las {r.get('hora')} (línea {r.get('linea')}: {r.get('falla')})?",
                si="Borrar", no="Cancelar")):
            return
        try:
            await self.app.run_in_thread(bitacora_json.borrar, self.carpeta, self.fecha, i, r)
        except (bitacora_json.ErrorBitacora, OSError) as e:
            self.estado(str(e), error=True)
        else:
            self.estado("Registro borrado.")
        self.cargar()
        self.refrescar()

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
        defecto = os.path.join(self.carpeta, f"bitacora_{self.fecha}.tsv")
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
