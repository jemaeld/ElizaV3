"""
acciones.py
------------
Ejecutar una entrada de la base (lo que pasa al escribir su nombre y Enter):
- VNC  -> archivo .vnc temporal con host/puerto/contraseña y se abre con el
          visor asociado.
- Resto (APPS, ACD, ...) -> os.startfile de la ruta del 'accion'. Las rutas
          relativas (_acd_store/...) se resuelven contra la carpeta de datos.

Devuelve (ok, mensaje); nunca imprime ni lanza por errores esperables.
"""

import glob
import os
import tempfile
import time

import acd_tools

PREFIJO_VNC = "eliza_vnc_"


def _limpiar_vnc_temporales():
    limite = time.time() - 60
    for ruta in glob.glob(os.path.join(tempfile.gettempdir(), PREFIJO_VNC + "*.vnc")):
        try:
            if os.path.getmtime(ruta) < limite:
                os.remove(ruta)
        except OSError:
            pass


def ip_de_entrada(entrada):
    ip = (entrada.get('ip') or '').strip()
    if not ip:
        accion = (entrada.get('accion') or '').strip()
        if accion.lower().startswith('vnc '):
            ip = accion[4:].strip()
    return ip


def lanzar_vnc(ip, password, puerto=5900):
    _limpiar_vnc_temporales()
    contenido = f"[connection]\nhost={ip}\nport={puerto}\npassword={password or ''}\n"
    with tempfile.NamedTemporaryFile(mode='w', prefix=PREFIJO_VNC, suffix='.vnc', delete=False,
                                     encoding='utf-8') as f:
        f.write(contenido)
    os.startfile(f.name)


def ejecutar(entrada, carpeta_datos, config):
    nombre = entrada.get('nombre', '')
    try:
        if entrada.get('categoria') == 'vnc':
            ip = ip_de_entrada(entrada)
            if not ip:
                return False, f"'{nombre}' no tiene IP registrada."
            lanzar_vnc(ip, config.get('vnc_password', ''), config.get('vnc_puerto', 5900))
            return True, f"VNC → {nombre} ({ip})"
        ruta = acd_tools.resolver_ruta_action(entrada.get('accion', ''), carpeta_datos)
        if not ruta:
            return False, f"'{nombre}' no tiene acción registrada."
        os.startfile(ruta)
        return True, f"Abriendo {nombre}"
    except OSError as e:
        return False, f"No se pudo abrir '{nombre}': {e}"
