"""
network_tools.py
-----------------
Herramientas de red para Eliza: información de interfaces y ping en una
ventana aparte.
"""

import os
import re
import socket

import psutil

# IP o nombre de host: letras, dígitos, punto, guion, guion bajo (y ':' para IPv6).
# Evita que algo como "/ping 1.1.1.1 & del ..." se ejecute en la consola.
_HOST_VALIDO = re.compile(r'^[A-Za-z0-9._:-]+$')


def ip_principal():
    """IP principal del equipo, o el nombre del equipo si no se puede resolver."""
    nombre = socket.gethostname()
    try:
        return socket.gethostbyname(nombre)
    except OSError:
        return nombre


def interfaces_ipv4():
    """Lista 'interfaz: ip' de las interfaces IPv4 (sin loopback)."""
    info = []
    for interfaz, direcciones in psutil.net_if_addrs().items():
        for d in direcciones:
            if d.family == socket.AF_INET and not d.address.startswith("127."):
                info.append(f"{interfaz}: {d.address}")
    return info


def lanzar_ping(destino):
    """
    Abre una ventana de consola nueva con un ping continuo (-t) al destino.
    No bloquea la consola principal de Eliza. Devuelve (ok, mensaje).
    """
    destino = (destino or '').strip()
    if not destino:
        return False, "Debes indicar una IP o host."
    if not _HOST_VALIDO.match(destino):
        return False, f"'{destino}' no parece una IP o nombre de host válido."
    try:
        os.system(f'start "Ping a {destino}" cmd /c ping {destino} -t')
    except Exception as e:
        return False, f"Error al lanzar ping hacia {destino}: {e}"
    return True, f"Ping lanzado en ventana nueva -> {destino}"
