"""
logix_tools.py
-----------------
Lógica pura para el monitor/forzado de tags Allen-Bradley (Logix) vía
pylogix. Sin GUI ni threading -- eso vive en logix_window.py.

Incluye:
- convertir_valor(): texto del usuario -> tipo probable para el PLC.
- guardar_registro() / cargar_registro(): exportar/importar la lista de
  tags de la sesión a un archivo JSON.
"""

import json
from datetime import datetime

VERSION_REGISTRO = 1
POLLING_MIN_MS = 50
POLLING_DEFAULT_MS = 100


def convertir_valor(texto):
    """
    Intenta convertir el texto escrito por el usuario al tipo más probable
    que espera el PLC: bool, int, float, o texto tal cual si nada aplica.
    """
    texto = texto.strip()
    bajo = texto.lower()
    if bajo in ('true', 'false'):
        return bajo == 'true'
    try:
        return int(texto)
    except ValueError:
        pass
    try:
        return float(texto)
    except ValueError:
        pass
    return texto


# ---------------------------------------------------------
# Registro de tags (JSON)
#
# Formato:
# {
#   "version": 1,
#   "fecha": "2026-10-15T19:03:00",
#   "tags": [
#     {"ip": "192.168.1.10", "polling_ms": 100, "tag": "Motor1.Run", "comentario": "Arranque banda"},
#     ...
#   ]
# }
#
# Los valores de SOBRESCRIBIR (forzado) NO se guardan a propósito: cargar un
# registro nunca debe empezar a escribir sobre un PLC sin que el usuario lo
# confirme fila por fila.
# ---------------------------------------------------------

def _normalizar_fila(fila):
    """Limpia una fila leída/por escribir. Devuelve dict o None si no sirve."""
    if not isinstance(fila, dict):
        return None
    ip = str(fila.get('ip', '') or '').strip()
    tag = str(fila.get('tag', '') or '').strip()
    comentario = str(fila.get('comentario', '') or '').strip()
    try:
        polling = int(fila.get('polling_ms', POLLING_DEFAULT_MS))
    except (TypeError, ValueError):
        polling = POLLING_DEFAULT_MS
    polling = max(polling, POLLING_MIN_MS)
    if not ip and not tag and not comentario:
        return None  # fila vacía, no aporta nada
    return {'ip': ip, 'polling_ms': polling, 'tag': tag, 'comentario': comentario}


def guardar_registro(ruta, filas):
    """
    Escribe la lista de filas a 'ruta' en JSON. 'filas' es una lista de
    dicts con ip, polling_ms, tag, comentario. Devuelve cuántas se guardaron.
    """
    limpias = [f for f in (_normalizar_fila(f) for f in filas) if f is not None]
    datos = {
        'version': VERSION_REGISTRO,
        'fecha': datetime.now().isoformat(timespec='seconds'),
        'tags': limpias,
    }
    with open(ruta, 'w', encoding='utf-8') as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)
    return len(limpias)


def cargar_registro(ruta):
    """
    Lee un registro JSON y devuelve la lista de filas normalizadas.
    Acepta también una lista suelta de filas (sin el envoltorio con
    'version'/'tags'). Lanza ValueError si el archivo no tiene un formato
    reconocible.
    """
    with open(ruta, 'r', encoding='utf-8') as fh:
        datos = json.load(fh)

    if isinstance(datos, dict):
        crudas = datos.get('tags')
    elif isinstance(datos, list):
        crudas = datos
    else:
        crudas = None

    if not isinstance(crudas, list):
        raise ValueError("El archivo no contiene una lista de tags reconocible.")

    return [f for f in (_normalizar_fila(f) for f in crudas) if f is not None]


# ---------------------------------------------------------
# Rutas de tag (scope del controlador vs. programa)
#
#   Controlador:  Motor1.Run
#   Programa:     Program:Estacion30.Motor1.Run

PREFIJO_PROGRAMA = "Program:"


def _sin_prefijo_programa(programa):
    programa = (programa or '').strip()
    if programa.lower().startswith(PREFIJO_PROGRAMA.lower()):
        programa = programa[len(PREFIJO_PROGRAMA):]
    return programa.strip()


def separar_ruta(ruta):
    """
    'Program:Est30.Motor.Run' -> ('Est30', 'Motor.Run')
    'Motor.Run'               -> (None, 'Motor.Run')
    """
    ruta = (ruta or '').strip()
    if ruta.lower().startswith(PREFIJO_PROGRAMA.lower()):
        programa, punto, tag = ruta[len(PREFIJO_PROGRAMA):].partition('.')
        if punto and programa.strip():
            return programa.strip(), tag.strip()
    return None, ruta


def armar_ruta(programa, tag):
    """
    Arma la ruta completa. 'programa' vacío/None = scope del controlador.
    Si 'tag' ya es una ruta completa (Program:X.Y), se respeta tal cual.
    """
    tag = (tag or '').strip()
    if not tag:
        return ''
    if separar_ruta(tag)[0]:
        return tag
    programa = _sin_prefijo_programa(programa)
    return f"{PREFIJO_PROGRAMA}{programa}.{tag}" if programa else tag


def filtrar_nombres(nombres, texto, limite=500):
    """Nombres que contienen 'texto' (sin distinguir mayúsculas); los que empiezan igual van primero."""
    texto = (texto or '').strip().lower()
    if not texto:
        return list(nombres[:limite])
    empiezan = [n for n in nombres if n.lower().startswith(texto)]
    contienen = [n for n in nombres if texto in n.lower() and not n.lower().startswith(texto)]
    return (empiezan + contienen)[:limite]


# ---------------------------------------------------------
# Trabajo de escritura: escribir un valor 1..N veces (o continuo) al ritmo
# del polling de la fila. Lo ejecuta el hilo de la fila; la GUI solo lo
# consulta. Estados: IDLE -> WORKING -> DONE (-> IDLE al reiniciar).

IDLE, WORKING, DONE = 'IDLE', 'WORKING', 'DONE'


class TrabajoEscritura:
    def __init__(self):
        self.estado = IDLE
        self.valor_texto = ''
        self.valor = None
        self.total = 0           # 0 = continuo (hasta detener)
        self.hechas = 0
        self.errores = 0
        self.ultimo_status = ''
        self.mensaje = ''
        self.corrida = 0         # cambia en cada inicio: descarta resultados de una corrida anterior
        self.historial = []      # [(hora, numero, status)] de la corrida actual (últimos 200)

    def iniciar(self, valor_texto, total):
        """Lanza ValueError si los datos no sirven."""
        valor_texto = (valor_texto or '').strip()
        if not valor_texto:
            raise ValueError("Escribe el valor a escribir.")
        total = int(total)
        if total < 0:
            raise ValueError("El número de veces no puede ser negativo.")
        self.valor_texto = valor_texto
        self.valor = convertir_valor(valor_texto)
        self.total = total
        self.hechas = 0
        self.errores = 0
        self.ultimo_status = ''
        self.mensaje = ''
        self.historial = []
        self.corrida += 1
        self.estado = WORKING
        return self.corrida

    def detener(self, motivo="Detenido"):
        if self.estado == WORKING:
            self.estado = IDLE
            self.mensaje = f"{motivo} en {self.progreso_texto()}"

    def reiniciar(self):
        if self.estado == DONE:
            self.estado = IDLE
            self.mensaje = ''

    def registrar(self, corrida, status, hora=''):
        """Resultado de una escritura. Ignora resultados de corridas viejas o ya detenidas."""
        if corrida != self.corrida or self.estado != WORKING:
            return
        self.hechas += 1
        self.ultimo_status = status
        if status != 'Success':
            self.errores += 1
        self.historial.append((hora, self.hechas, status))
        del self.historial[:-200]
        if self.total and self.hechas >= self.total:
            self.estado = DONE
            self.mensaje = "Completado" + (f" con {self.errores} error(es)" if self.errores else "")

    def progreso_texto(self):
        return f"{self.hechas}/{self.total if self.total else '∞'}"

    def texto_columna(self):
        if self.estado == IDLE:
            return "IDLE" if not self.mensaje else f"IDLE {self.progreso_texto()}"
        texto = f"{self.estado} {self.progreso_texto()}"
        return texto + (f" ({self.errores} err)" if self.errores else "")
