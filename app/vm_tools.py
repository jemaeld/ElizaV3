"""
vm_tools.py -- máquinas virtuales de VMware Workstation (categoría VM).

Una entrada VM en la base:
    nombre      NOIX
    accion      vm "C:\\VMs\\NOIX\\NOIX.vmx"
    ip          127.0.0.1:5901        (VNC propio de VMware; vacío = sin VNC)
    comentario  libre

Acciones (vmrun -T ws, siempre sin ventana):
    arrancar    vmrun start "<vmx>" nogui
    apagar      vmrun stop "<vmx>" soft    (apagado limpio: pide a la VM que se apague)
    forzar      vmrun stop "<vmx>" hard    (como desconectar la corriente)
    estado      vmrun list                  (rutas de las VMs encendidas)

vmrun.exe se busca en eliza_local.json ("vmrun"), luego en Program Files y
luego en el PATH. Las rutas de las VMs son de ESTA PC: en otra PC la entrada
aparece como "no disponible".
"""

import os
import re
import shutil
import subprocess

CANDIDATOS_VMRUN = (
    r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
    r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
)
CORRIENDO, APAGADA, NO_DISPONIBLE = "corriendo", "apagada", "no disponible"


class ErrorVM(Exception):
    pass


# ---------------------------------------------------------
def ruta_vmx(entrada):
    """De 'vm "C:\\...\\NOIX.vmx"' saca la ruta del .vmx."""
    texto = (entrada.get('accion') or '').strip()
    if texto.lower().startswith('vm '):
        texto = texto[3:].strip()
    return texto.strip('"').strip()


def accion_de(vmx):
    return f'vm "{os.path.normpath(vmx)}"'


def _clave(ruta):
    return os.path.normcase(os.path.normpath(ruta.strip().strip('"'))) if ruta else ''


def leer_vmx(ruta):
    """Lee el .vmx (formato clave = "valor"). Devuelve dict con claves en minúsculas."""
    datos = {}
    with open(ruta, encoding='utf-8', errors='replace') as f:
        for linea in f:
            m = re.match(r'\s*([^=#]+?)\s*=\s*"(.*)"\s*$', linea)
            if m:
                datos[m.group(1).strip().lower()] = m.group(2)
    return datos


def datos_de_vmx(ruta):
    """Para /add: {'categoria', 'nombre_sugerido', 'action', 'ip'} leídos del .vmx."""
    try:
        vmx = leer_vmx(ruta)
    except OSError as e:
        return None, f"No se pudo leer {os.path.basename(ruta)}: {e}"
    nombre = vmx.get('displayname') or os.path.splitext(os.path.basename(ruta))[0]
    vnc = ""
    if vmx.get('remotedisplay.vnc.enabled', '').upper() == 'TRUE':
        vnc = f"127.0.0.1:{vmx.get('remotedisplay.vnc.port', '5900')}"
    return {"categoria": "VM", "nombre_sugerido": nombre, "action": accion_de(ruta), "ip": vnc}, None


# ---------------------------------------------------------
def encontrar_vmrun(local=None):
    configurado = (local or {}).get('vmrun')
    for candidato in ([configurado] if configurado else []) + list(CANDIDATOS_VMRUN):
        if candidato and os.path.isfile(candidato):
            return candidato
    return shutil.which('vmrun')


def _vmrun(vmrun, *args, timeout=180):
    if not vmrun:
        raise ErrorVM("No se encontró vmrun.exe (VMware Workstation). Indica su ruta en eliza_local.json "
                      "como \"vmrun\".")
    sin_ventana = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        r = subprocess.run([vmrun, '-T', 'ws', *args], capture_output=True, text=True, timeout=timeout,
                           creationflags=sin_ventana, errors='replace')
    except subprocess.TimeoutExpired:
        raise ErrorVM(f"vmrun no respondió en {timeout} s.") from None
    except OSError as e:
        raise ErrorVM(f"No se pudo ejecutar vmrun: {e}") from None
    salida = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise ErrorVM(salida.replace('Error: ', '') or f"vmrun terminó con código {r.returncode}")
    return salida


def encendidas(vmrun):
    """Conjunto de rutas (normalizadas) de las VMs encendidas."""
    salida = _vmrun(vmrun, 'list', timeout=20)
    return {_clave(l) for l in salida.splitlines()[1:] if l.strip()}   # 1ª línea: "Total running VMs: N"


def estado(entrada, encendidas_ahora):
    vmx = ruta_vmx(entrada)
    if _clave(vmx) in encendidas_ahora:
        return CORRIENDO
    return APAGADA if vmx and os.path.isfile(vmx) else NO_DISPONIBLE


def arrancar(vmrun, entrada):
    vmx = ruta_vmx(entrada)
    if not os.path.isfile(vmx):
        raise ErrorVM(f"No existe {vmx} en esta PC.")
    _vmrun(vmrun, 'start', vmx, 'nogui', timeout=300)
    return f"{entrada['nombre']}: encendida."


def apagar(vmrun, entrada, forzado=False):
    vmx = ruta_vmx(entrada)
    try:
        _vmrun(vmrun, 'stop', vmx, 'hard' if forzado else 'soft', timeout=300)
    except ErrorVM as e:
        if forzado:
            raise
        raise ErrorVM(f"{e}. El apagado limpio necesita VMware Tools dentro de la VM; "
                      "si no responde, usa Forzar apagado.") from None
    return f"{entrada['nombre']}: apagada{' (forzado)' if forzado else ''}."
