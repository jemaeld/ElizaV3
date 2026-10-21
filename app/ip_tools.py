"""
ip_tools.py -- /ip: ver y cambiar la IP de un adaptador de red.

    /ip                                 lista de adaptadores (en la tabla del lanzador)
    /ip LAN 10.140.16.250               IP fija, máscara 255.255.255.0, sin gateway
    /ip LAN 10.140.16.250 255.255.0.0   (o /16) con esa máscara
    /ip LAN L31E125                     misma subred del PLC, terminación .250
    /ip LAN L31E125 .249                misma subred del PLC, terminación .249
    /ip LAN dhcp                        regresa a automático

El adaptador se reconoce por su nombre real (puede tener espacios, ej.
"Ethernet 2"): se toma el nombre más largo que coincida al inicio.

Cambiar la IP en Windows pide permisos de administrador. Primero se intenta
con netsh normal (funciona si el usuario está en "Network Configuration
Operators" o Eliza corre como admin); si Windows lo niega, se repite el
mismo netsh con "Ejecutar como administrador" (UAC), solo para ese cambio.
"""

import os
import re
import socket
import subprocess
import time

MASCARA_DEFECTO = "255.255.255.0"
TERMINACION_DEFECTO = 250
_IP = re.compile(r'^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$')


# ---------------------------------------------------------
# Validación
def es_ip(texto):
    m = _IP.match((texto or '').strip())
    return bool(m) and all(0 <= int(g) <= 255 for g in m.groups())


def mascara_desde_prefijo(n):
    bits = (0xFFFFFFFF << (32 - n)) & 0xFFFFFFFF if n else 0
    return ".".join(str((bits >> s) & 255) for s in (24, 16, 8, 0))


def prefijo_de_mascara(mascara):
    try:
        bits = "".join(f"{int(o):08b}" for o in mascara.split('.'))
    except ValueError:
        return None
    if len(bits) != 32 or '01' in bits:
        return None
    return bits.count('1')


def leer_mascara(texto):
    """'255.255.0.0' o '/16' o '16' -> '255.255.0.0'; None si no es válida."""
    texto = (texto or '').strip()
    if re.fullmatch(r'/?\d{1,2}', texto):
        n = int(texto.lstrip('/'))
        return mascara_desde_prefijo(n) if 1 <= n <= 32 else None
    if es_ip(texto) and prefijo_de_mascara(texto) is not None:
        return texto
    return None


# ---------------------------------------------------------
# Adaptadores
def adaptadores():
    """[{nombre, ip, mascara, activo}] de los adaptadores con IPv4 o activos (sin loopback)."""
    import psutil
    estados = psutil.net_if_stats()
    lista = []
    for nombre, direcciones in psutil.net_if_addrs().items():
        ipv4 = [d for d in direcciones if d.family == socket.AF_INET]
        if nombre.lower().startswith('loopback') or any(d.address.startswith('127.') for d in ipv4):
            continue
        d = ipv4[0] if ipv4 else None
        activo = bool(estados.get(nombre) and estados[nombre].isup)
        lista.append({'nombre': nombre, 'ip': d.address if d else '', 'mascara': (d.netmask if d else '') or '',
                      'activo': activo})
    lista.sort(key=lambda a: (not a['activo'], a['nombre'].lower()))
    return lista


def describir_adaptador(a):
    if not a['ip']:
        return "sin IP" + ("" if a['activo'] else " · desconectado")
    n = prefijo_de_mascara(a['mascara']) if a['mascara'] else None
    texto = a['ip'] + (f"/{n}" if n is not None else "")
    if a['ip'].startswith('169.254.'):
        texto += " · sin DHCP (APIPA)"
    return texto + ("" if a['activo'] else " · desconectado")


def separar_adaptador(resto, lista):
    """('Ethernet 2 10.0.0.1', adaptadores) -> (adaptador, '10.0.0.1'); (None, resto) si no coincide."""
    bajo = resto.lower()
    for a in sorted(lista, key=lambda a: -len(a['nombre'])):
        n = a['nombre'].lower()
        if bajo == n or bajo.startswith(n + ' '):
            return a, resto[len(n):].strip()
    return None, resto


# ---------------------------------------------------------
# Interpretar lo que se escribió después de /ip
def interpretar(texto, lista_adaptadores, equipos):
    """
    Devuelve un dict con 'etapa':
        'adaptador' -> todavía se elige el adaptador ('filtro' = lo escrito)
        'destino'   -> adaptador elegido; se elige IP / PLC / dhcp ('filtro')
        'plan'      -> listo para aplicar: 'adaptador', 'modo' ('estatica'|'dhcp'),
                       'ip', 'mascara', 'equipo' (si vino de un PLC), 'resumen'
        'error'     -> 'mensaje' (adaptador elegido pero algo no es válido)
    'equipos' son las entradas ACD de la base: {nombre, ip, comentario}.
    """
    texto = (texto or '').strip()
    adaptador, resto = separar_adaptador(texto, lista_adaptadores)
    if adaptador is None:
        return {'etapa': 'adaptador', 'filtro': texto}
    if not resto:
        return {'etapa': 'destino', 'adaptador': adaptador, 'filtro': ''}
    partes = resto.split()
    base = {'adaptador': adaptador}

    if len(partes) == 1 and partes[0].lower() == 'dhcp':
        return {**base, 'etapa': 'plan', 'modo': 'dhcp', 'ip': '', 'mascara': '', 'equipo': None,
                'resumen': f"{adaptador['nombre']}: {describir_adaptador(adaptador)}  →  automático (DHCP)"}

    if es_ip(partes[0]):
        ip, extra = partes[0], partes[1:]
        equipo = None
    else:
        # ¿un PLC de la base? (nombre exacto; puede ir seguido de .N y/o máscara)
        equipo = next((e for e in equipos if e['nombre'].lower() == partes[0].lower()), None)
        if equipo is None:
            return {'etapa': 'destino', 'adaptador': adaptador, 'filtro': resto}
        extra = partes[1:]
        ip_plc = (equipo.get('ip') or '').strip()
        if not es_ip(ip_plc):
            return {**base, 'etapa': 'error',
                    'mensaje': f"{equipo['nombre']} tiene la IP incompleta ('{ip_plc}'). Corrígela en /edit acd."}
        terminacion = TERMINACION_DEFECTO
        if extra and re.fullmatch(r'\.\d{1,3}', extra[0]):
            terminacion = int(extra[0][1:])
            extra = extra[1:]
        if not 1 <= terminacion <= 254:
            return {**base, 'etapa': 'error', 'mensaje': f"La terminación .{terminacion} no es válida (1 a 254)."}
        ip = ".".join(ip_plc.split('.')[:3] + [str(terminacion)])
        if ip == ip_plc:
            return {**base, 'etapa': 'error',
                    'mensaje': f"{ip} es la IP del PLC {equipo['nombre']}. Usa otra terminación (ej. .249)."}

    mascara = MASCARA_DEFECTO
    if extra:
        mascara = leer_mascara(extra[0])
        if mascara is None or len(extra) > 1:
            return {**base, 'etapa': 'error',
                    'mensaje': f"No entiendo '{' '.join(extra)}'. Máscara: 255.255.0.0 o /16."}
    n = prefijo_de_mascara(mascara)
    destino = f"{ip}/{n}"
    if equipo:
        destino += f"  (subred de {equipo['nombre']} {equipo['ip']})"
    return {**base, 'etapa': 'plan', 'modo': 'estatica', 'ip': ip, 'mascara': mascara, 'equipo': equipo,
            'resumen': f"{adaptador['nombre']}: {describir_adaptador(adaptador)}  →  {destino}  · sin gateway"}


# ---------------------------------------------------------
# Aplicar
def argumentos_netsh(plan):
    nombre = plan['adaptador']['nombre']
    if plan['modo'] == 'dhcp':
        return ['interface', 'ipv4', 'set', 'address', f'name={nombre}', 'source=dhcp']
    return ['interface', 'ipv4', 'set', 'address', f'name={nombre}', 'source=static',
            f'address={plan["ip"]}', f'mask={plan["mascara"]}', 'gateway=none']


def _linea_comandos(args):
    """Argumentos -> una línea para Windows (comillas donde hay espacios)."""
    return subprocess.list2cmdline(args)


def _netsh_normal(args):
    sin_ventana = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    r = subprocess.run(['netsh'] + args, capture_output=True, text=True, timeout=30, creationflags=sin_ventana,
                       encoding='mbcs' if os.name == 'nt' else None, errors='replace')
    return r.returncode, (r.stdout + r.stderr).strip()


def _netsh_admin(args):
    """netsh con UAC. Devuelve (código, mensaje). Código None = el usuario canceló el UAC."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR),
                    ('lpParameters', wintypes.LPCWSTR), ('lpDirectory', wintypes.LPCWSTR),
                    ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p),
                    ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY), ('dwHotKey', wintypes.DWORD),
                    ('hIconOrMonitor', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]

    SEE_MASK_NOCLOSEPROCESS, SW_HIDE, ERROR_CANCELLED = 0x40, 0, 1223
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "netsh"
    info.lpParameters = _linea_comandos(args)
    info.nShow = SW_HIDE
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.GetLastError()
        if error == ERROR_CANCELLED:
            return None, "Cancelaste el permiso de administrador: no se cambió nada."
        return 1, f"No se pudo pedir permiso de administrador (error {error})."
    kernel32.WaitForSingleObject(info.hProcess, 60000)
    codigo = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(codigo))
    kernel32.CloseHandle(info.hProcess)
    return codigo.value, ""


def _esperar_ip(nombre, ip, segundos=8):
    """Espera a que el adaptador muestre la IP nueva (Windows tarda un poco)."""
    limite = time.time() + segundos
    while time.time() < limite:
        a = next((x for x in adaptadores() if x['nombre'] == nombre), None)
        if a and a['ip'] == ip:
            return True
        time.sleep(0.5)
    return False


def aplicar(plan, ejecutar_normal=None, ejecutar_admin=None):
    """
    Aplica el plan. Devuelve (ok, mensaje, uso_admin).
    ejecutar_normal / ejecutar_admin se pueden reemplazar en pruebas.
    """
    ejecutar_normal = ejecutar_normal or _netsh_normal
    ejecutar_admin = ejecutar_admin or _netsh_admin
    args = argumentos_netsh(plan)
    nombre = plan['adaptador']['nombre']
    try:
        codigo, salida = ejecutar_normal(args)
    except (OSError, subprocess.SubprocessError) as e:
        codigo, salida = 1, str(e)
    uso_admin = False
    if codigo != 0:
        uso_admin = True
        try:
            codigo, salida_admin = ejecutar_admin(args)
        except (OSError, AttributeError) as e:  # AttributeError: no es Windows
            return False, f"No se pudo cambiar la IP: {salida or e}", True
        if codigo is None:
            return False, salida_admin, True
        if codigo != 0:
            return False, f"netsh no pudo cambiar la IP de {nombre} (código {codigo}). {salida_admin or salida}", True
    if plan['modo'] == 'dhcp':
        return True, f"{nombre}: ahora en automático (DHCP). La IP puede tardar unos segundos en llegar.", uso_admin
    if _esperar_ip(nombre, plan['ip']):
        return True, f"{nombre}: IP cambiada a {plan['ip']} / {plan['mascara']}.", uso_admin
    return True, (f"{nombre}: netsh aceptó el cambio a {plan['ip']}, pero el adaptador todavía no la muestra "
                  "(¿cable desconectado?). Revisa con /ip."), uso_admin
