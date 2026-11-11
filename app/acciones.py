"""
acciones.py
------------
Ejecutar una entrada de la base (lo que pasa al escribir su nombre y Enter):
- VNC  -> archivo .vnc temporal con host/puerto/contraseña y se abre con el
          visor asociado.
- DIR    -> abre la carpeta en el Explorador de Windows.
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


def destino_vnc(entrada, puerto_defecto=5900):
    """(host, puerto) para VNC. Acepta 'host:puerto' en IP o en 'vnc host:puerto'
    (el VNC propio de VMware usa un puerto distinto por VM, ej. 127.0.0.1:5901)."""
    texto = (entrada.get('ip') or '').strip()
    accion = (entrada.get('accion') or '').strip()
    desde_accion = accion[4:].strip() if accion.lower().startswith('vnc ') else ''
    if not texto or (':' not in texto and desde_accion.split(':')[0] == texto and ':' in desde_accion):
        texto = desde_accion or texto
    host, _, puerto = texto.partition(':')
    try:
        puerto = int(puerto) if puerto else int(puerto_defecto)
    except ValueError:
        puerto = int(puerto_defecto)
    return host.strip(), puerto


def ip_de_entrada(entrada):
    """Solo el host (sin puerto): para ping, /ip, búsquedas."""
    return destino_vnc(entrada)[0]


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
            ip, puerto = destino_vnc(entrada, config.get('vnc_puerto', 5900))
            if not ip:
                return False, f"'{nombre}' no tiene IP registrada."
            lanzar_vnc(ip, config.get('vnc_password', ''), puerto)
            return True, f"VNC → {nombre} ({ip}{'' if puerto == 5900 else f':{puerto}'})"
        ruta = acd_tools.resolver_ruta_action(entrada.get('accion', ''), carpeta_datos)
        if not ruta:
            return False, f"'{nombre}' no tiene acción registrada."
        if entrada.get('categoria') == 'dir' and not os.path.isdir(ruta):
            return False, f"'{nombre}': la carpeta no existe o no hay acceso ({ruta}). ¿Unidad de red desconectada?"
        os.startfile(ruta)
        return True, f"Abriendo {nombre}"
    except OSError as e:
        return False, f"No se pudo abrir '{nombre}': {e}"
