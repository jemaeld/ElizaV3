"""
logix_monitor.py -- motor del Monitor de Variables (sin interfaz).

Cada fila es una conexión independiente (IP, polling, tag) con su propio
hilo. pylogix no debe compartir una instancia de PLC entre hilos: cada hilo
crea la suya. Cada ciclo: si hay una escritura en curso, ESCRIBE y luego LEE
(así el valor leído muestra el efecto).

La interfaz solo llama métodos y lee instantanea(); nunca toca un PLC.

Desconectar no bloquea: se marca la parada y se sube la "generación" de la
fila; un hilo viejo que todavía esté esperando la respuesta del PLC ya no
puede escribir en la fila al regresar.
"""

import itertools
import threading
from datetime import datetime

import logix_tools

try:
    from pylogix import PLC
except ImportError:
    PLC = None

OFF, CONECTANDO, ON, ERROR = 'OFF', 'CONECTANDO', 'ON', 'ERROR'
POLLING_MIN_MS = logix_tools.POLLING_MIN_MS
POLLING_DEFAULT_MS = logix_tools.POLLING_DEFAULT_MS


class Fila:
    def __init__(self, id_fila, ip, tag, polling_ms, comentario):
        self.id = id_fila
        self.ip = ip
        self.tag = tag
        self.polling_ms = max(int(polling_ms or POLLING_DEFAULT_MS), POLLING_MIN_MS)
        self.comentario = comentario
        self.trabajo = logix_tools.TrabajoEscritura()
        self.valor = ''
        self.conexion = OFF
        self.estado_texto = 'Desconectado'
        self.generacion = 0
        self.detener = None


class MonitorLogix:
    def __init__(self, fabrica_plc=None):
        self.fabrica = fabrica_plc or PLC
        self.lock = threading.Lock()
        self.filas = {}               # id -> Fila (en orden de alta)
        self._ids = itertools.count(1)

    @property
    def disponible(self):
        return self.fabrica is not None

    # ---------------------------------------------------------
    # Filas
    def agregar(self, ip, tag, polling_ms=POLLING_DEFAULT_MS, comentario=''):
        with self.lock:
            fila = Fila(next(self._ids), ip.strip(), tag.strip(), polling_ms, comentario.strip())
            self.filas[fila.id] = fila
            return fila.id

    def actualizar(self, id_fila, **campos):
        """Cambia ip/tag/polling_ms/comentario. Si cambia la IP de una fila conectada, reconecta."""
        with self.lock:
            fila = self.filas.get(id_fila)
            if fila is None:
                return
            ip_anterior = fila.ip
            for clave, valor in campos.items():
                if clave == 'polling_ms':
                    valor = max(int(valor), POLLING_MIN_MS)
                elif isinstance(valor, str):
                    valor = valor.strip()
                setattr(fila, clave, valor)
            reconectar = fila.ip != ip_anterior and fila.conexion != OFF
        if reconectar:
            self.conectar(id_fila)

    def quitar(self, id_fila):
        self.desconectar(id_fila)
        with self.lock:
            self.filas.pop(id_fila, None)

    def instantanea(self):
        """Copia del estado de todas las filas (para pintar la tabla)."""
        with self.lock:
            return [self._copia(f) for f in self.filas.values()]

    def fila(self, id_fila):
        with self.lock:
            f = self.filas.get(id_fila)
            return self._copia(f) if f else None

    @staticmethod
    def _copia(f):
        t = f.trabajo
        return {
            'id': f.id, 'ip': f.ip, 'tag': f.tag, 'polling_ms': f.polling_ms, 'comentario': f.comentario,
            'valor': f.valor, 'conexion': f.conexion, 'estado_texto': f.estado_texto,
            'trabajo': {'estado': t.estado, 'valor_texto': t.valor_texto, 'total': t.total, 'hechas': t.hechas,
                        'errores': t.errores, 'ultimo_status': t.ultimo_status, 'mensaje': t.mensaje,
                        'progreso': t.progreso_texto(), 'columna': t.texto_columna(), 'corrida': t.corrida,
                        'historial': list(t.historial)},
        }

    # ---------------------------------------------------------
    # Conexión
    def conectar(self, id_fila):
        if not self.disponible:
            raise RuntimeError("Falta la librería pylogix (pip install pylogix).")
        with self.lock:
            fila = self.filas.get(id_fila)
            if fila is None:
                return
            if not fila.ip:
                raise ValueError("La fila no tiene IP.")
            if fila.detener is not None:
                fila.detener.set()
            fila.generacion += 1
            fila.detener = threading.Event()
            fila.conexion, fila.estado_texto = CONECTANDO, 'Conectando...'
            args = (id_fila, fila.ip, fila.generacion, fila.detener)
        threading.Thread(target=self._bucle, args=args, daemon=True).start()

    def desconectar(self, id_fila, detener_escritura=True):
        with self.lock:
            fila = self.filas.get(id_fila)
            if fila is None:
                return
            if fila.detener is not None:
                fila.detener.set()
                fila.detener = None
            fila.generacion += 1
            fila.conexion, fila.estado_texto, fila.valor = OFF, 'Desconectado', ''
            if detener_escritura:
                fila.trabajo.detener("Detenido (desconectado)")

    def conectada(self, id_fila):
        with self.lock:
            fila = self.filas.get(id_fila)
            return fila is not None and fila.conexion != OFF

    def cerrar(self):
        for id_fila in list(self.filas):
            self.desconectar(id_fila)

    # ---------------------------------------------------------
    # Escritura
    def iniciar_escritura(self, id_fila, valor_texto, total):
        """Lanza ValueError con un mensaje para el usuario."""
        with self.lock:
            fila = self.filas.get(id_fila)
            if fila is None:
                raise ValueError("La fila ya no existe.")
            if not fila.tag:
                raise ValueError("La fila no tiene tag.")
            fila.trabajo.iniciar(valor_texto, total)
            conectada = fila.conexion != OFF
        if not conectada:
            self.conectar(id_fila)  # empieza a escribir en cuanto conecte

    def detener_escritura(self, id_fila):
        with self.lock:
            if id_fila in self.filas:
                self.filas[id_fila].trabajo.detener()

    def reiniciar_escritura(self, id_fila):
        with self.lock:
            if id_fila in self.filas:
                self.filas[id_fila].trabajo.reiniciar()

    def detener_todas(self):
        with self.lock:
            for fila in self.filas.values():
                fila.trabajo.detener()

    def hay_escrituras(self):
        with self.lock:
            return any(f.trabajo.estado == logix_tools.WORKING for f in self.filas.values())

    # ---------------------------------------------------------
    def _publicar(self, id_fila, generacion, **campos):
        """Escribe resultados en la fila solo si este hilo sigue siendo el vigente."""
        with self.lock:
            fila = self.filas.get(id_fila)
            if fila is None or fila.generacion != generacion:
                return False
            for clave, valor in campos.items():
                setattr(fila, clave, valor)
            return True

    def _bucle(self, id_fila, ip, generacion, detener):
        try:
            plc = self.fabrica(ip)
            try:
                plc.SocketTimeout = 5
            except Exception:
                pass
        except Exception as e:
            self._publicar(id_fila, generacion, conexion=ERROR, estado_texto=f'Error: {e}')
            return

        try:
            prueba = plc.GetPLCTime()
            if getattr(prueba, 'Status', None) == 'Success':
                self._publicar(id_fila, generacion, conexion=ON, estado_texto='Conectado')
            else:
                self._publicar(id_fila, generacion, conexion=ERROR, estado_texto=f'Sin respuesta: {prueba.Status}')
        except Exception as e:
            # No se corta: si el equipo no soporta GetPLCTime pero sí Read, el ciclo lo confirma.
            self._publicar(id_fila, generacion, conexion=ERROR, estado_texto=f'Sin respuesta: {e}')

        while not detener.is_set():
            with self.lock:
                fila = self.filas.get(id_fila)
                if fila is None or fila.generacion != generacion:
                    break
                tag, polling = fila.tag, fila.polling_ms
                trabajo = fila.trabajo
                escribir = trabajo.estado == logix_tools.WORKING
                corrida, valor = trabajo.corrida, trabajo.valor

            if tag:
                if escribir:
                    try:
                        status = plc.Write(tag, valor).Status
                    except Exception as e:
                        status = f'Error: {e}'
                    hora = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    with self.lock:
                        if self.filas.get(id_fila) is not None and self.filas[id_fila].generacion == generacion:
                            trabajo.registrar(corrida, status, hora)
                try:
                    r = plc.Read(tag)
                    if r.Status == 'Success':
                        self._publicar(id_fila, generacion, valor='' if r.Value is None else str(r.Value),
                                       conexion=ON, estado_texto='Conectado')
                    else:
                        self._publicar(id_fila, generacion, valor='', conexion=ERROR,
                                       estado_texto=f'Error de lectura: {r.Status}')
                except Exception as e:
                    self._publicar(id_fila, generacion, conexion=ERROR, estado_texto=f'Error de lectura: {e}')

            detener.wait(polling / 1000)

        try:
            plc.Close()
        except Exception:
            pass
