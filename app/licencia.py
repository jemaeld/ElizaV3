"""
licencia.py
------------
Contraseña de acceso ("licencia de usuario legítimo"), igual que en V2:

- Es el 'vnc_password' guardado en la base (tabla config): la misma que se
  escribe en los .vnc al conectar.
- Cada instalación guarda solo una HUELLA (sha256) en eliza_local.json; no
  se vuelve a pedir mientras la contraseña de la base no cambie.
- Si la base todavía no tiene contraseña (instalación inicial de todo el
  sistema), la primera que se escriba (confirmada) queda definida.
- En respaldo local (la remota no estaba disponible) una instalación ya
  validada entra sin pedir nada; una nueva necesita la remota.

Esta capa no tiene interfaz: la pantalla de acceso usa estas funciones.
"""

import hashlib

import rutas

CLAVE = 'vnc_password'
INTENTOS = 3


def huella(texto):
    return hashlib.sha256(("eliza:" + texto).encode('utf-8')).hexdigest()


def estado(bd, respaldo_local=False):
    """
    'ok'         -> puede entrar sin preguntar
    'definir'    -> nadie ha definido contraseña: pedirla dos veces
    'verificar'  -> pedir la contraseña
    'bloqueado'  -> equipo nuevo en respaldo local: no se puede validar
    """
    guardada = (bd.config_get(CLAVE) or '').strip()
    local = rutas.leer_local().get('licencia')
    if guardada and local == huella(guardada):
        return 'ok'
    if respaldo_local:
        return 'ok' if local else 'bloqueado'
    if not guardada and not local:
        return 'definir'
    return 'verificar'


def verificar(bd, valor):
    """True si 'valor' es la contraseña; en ese caso guarda la huella local."""
    valor = (valor or '').strip()
    if not valor:
        return False
    guardada = (bd.config_get(CLAVE) or '').strip()
    local = rutas.leer_local().get('licencia')
    if guardada and valor == guardada:
        rutas.guardar_local(licencia=huella(valor))
        return True
    if not guardada and local == huella(valor):
        bd.config_set(CLAVE, valor)  # se repone en la base que no la tenía
        return True
    return False


def definir(bd, valor):
    valor = (valor or '').strip()
    if not valor:
        return False
    bd.config_set(CLAVE, valor)
    rutas.guardar_local(licencia=huella(valor))
    return True
