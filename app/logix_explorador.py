"""
logix_explorador.py
---------------------
Lee del PLC la lista de programas y de tags (vía pylogix) para el asistente
de tags de /logix, SIN bloquear la ventana: cada consulta corre en un hilo
propio con su propia conexión (pylogix no comparte instancias entre hilos)
y deja el resultado en una cola que la GUI revisa con after().

Los resultados se guardan en memoria por IP durante la sesión de /logix,
así que solo la primera consulta a cada PLC tarda.

Nombres que devuelve pylogix:
  - GetTagList(allTags=False): tags del controlador + entradas 'Program:X'
    (que son los programas, no tags) y llena plc.ProgramNames.
  - GetProgramTagList('Program:X'): tags con nombre 'Program:X.Tag'.
"""

import queue
import re
import threading

try:
    from pylogix import PLC
except ImportError:  # sin pylogix el asistente funciona como texto libre
    PLC = None

PREFIJO = "Program:"
TIMEOUT_SEGUNDOS = 5


def orden_natural(nombre):
    """Motor2 antes que Motor10 (los números se comparan como números)."""
    return [(0, int(p), '') if p.isdigit() else (1, 0, p) for p in re.split(r'(\d+)', nombre.lower())]


def _nombres_controlador(respuesta):
    tags = respuesta.Value or []
    return sorted({t.TagName for t in tags if not t.TagName.startswith(PREFIJO)}, key=orden_natural)


def _nombres_programa(respuesta, programa):
    prefijo = f"{PREFIJO}{programa}."
    nombres = set()
    for t in respuesta.Value or []:
        nombre = t.TagName[len(prefijo):] if t.TagName.startswith(prefijo) else t.TagName
        nombres.add(nombre)
    return sorted(nombres, key=orden_natural)


class ExploradorPLC:
    """
    Uso desde la GUI:
        exp.pedir_controlador(ip)          -> lanza la consulta (si no está en caché)
        exp.pedir_programa(ip, programa)
        exp.resultados()                    -> lista de eventos nuevos (llamar con after())
    Eventos: ('controlador', ip, {'tags': [...], 'programas': [...]})
             ('programa', ip, programa, [tags])
             ('error', ip, mensaje)
    """

    def __init__(self, fabrica_plc=None):
        self._fabrica = fabrica_plc or PLC
        self._cola = queue.Queue()
        self._cache_controlador = {}   # ip -> {'tags': [...], 'programas': [...]}
        self._cache_programa = {}      # (ip, programa) -> [tags]
        self._en_curso = set()
        self._lock = threading.Lock()

    @property
    def disponible(self):
        return self._fabrica is not None

    def olvidar(self, ip):
        """Borra la caché de esa IP (botón 'Leer del PLC' para volver a consultar)."""
        self._cache_controlador.pop(ip, None)
        for clave in [c for c in self._cache_programa if c[0] == ip]:
            self._cache_programa.pop(clave, None)

    def controlador_en_cache(self, ip):
        return self._cache_controlador.get(ip)

    def programa_en_cache(self, ip, programa):
        return self._cache_programa.get((ip, programa))

    def _lanzar(self, clave, objetivo, *args):
        with self._lock:
            if clave in self._en_curso:
                return False
            self._en_curso.add(clave)

        def correr():
            try:
                objetivo(*args)
            except Exception as e:
                self._cola.put(('error', args[0], f"{type(e).__name__}: {e}"))
            finally:
                with self._lock:
                    self._en_curso.discard(clave)
        threading.Thread(target=correr, daemon=True).start()
        return True

    def _nuevo_plc(self, ip):
        plc = self._fabrica(ip)
        try:
            plc.SocketTimeout = TIMEOUT_SEGUNDOS
        except Exception:
            pass
        return plc

    # -- controlador ------------------------------------------------
    def pedir_controlador(self, ip):
        if not self.disponible or not ip:
            return False
        if ip in self._cache_controlador:
            self._cola.put(('controlador', ip, self._cache_controlador[ip]))
            return False
        return self._lanzar(('c', ip), self._leer_controlador, ip)

    def _leer_controlador(self, ip):
        plc = self._nuevo_plc(ip)
        try:
            r = plc.GetTagList(allTags=False)
            if r.Status != 'Success':
                self._cola.put(('error', ip, f"El PLC respondió: {r.Status}"))
                return
            programas = sorted({p[len(PREFIJO):] if p.startswith(PREFIJO) else p
                                for p in (plc.ProgramNames or [])}, key=orden_natural)
            datos = {'tags': _nombres_controlador(r), 'programas': programas}
            self._cache_controlador[ip] = datos
            self._cola.put(('controlador', ip, datos))
        finally:
            try:
                plc.Close()
            except Exception:
                pass

    # -- programa ---------------------------------------------------
    def pedir_programa(self, ip, programa):
        if not self.disponible or not ip or not programa:
            return False
        clave = (ip, programa)
        if clave in self._cache_programa:
            self._cola.put(('programa', ip, programa, self._cache_programa[clave]))
            return False
        return self._lanzar(('p', ip, programa), self._leer_programa, ip, programa)

    def _leer_programa(self, ip, programa):
        plc = self._nuevo_plc(ip)
        try:
            r = plc.GetProgramTagList(f"{PREFIJO}{programa}")
            if r.Status != 'Success':
                self._cola.put(('error', ip, f"Programa '{programa}': {r.Status}"))
                return
            nombres = _nombres_programa(r, programa)
            self._cache_programa[(ip, programa)] = nombres
            self._cola.put(('programa', ip, programa, nombres))
        finally:
            try:
                plc.Close()
            except Exception:
                pass

    def resultados(self):
        eventos = []
        try:
            while True:
                eventos.append(self._cola.get_nowait())
        except queue.Empty:
            pass
        return eventos
