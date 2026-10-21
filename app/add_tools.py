"""
add_tools.py
-------------
Lógica pura (sin GUI) para procesar archivos que se van a agregar como
entrada VNC o APPS: accesos directos (.lnk), ejecutables (.exe) o archivos
de conexión VNC (.vnc).

Resuelve accesos directos vía PowerShell y extrae la IP de archivos .vnc.
ACD queda fuera de este módulo a propósito: esas entradas se generan con
/scan_acd.
"""

import os
import re
import subprocess


EXTENSIONES_VNC = ('.vnc',)
EXTENSIONES_APPS = ('.lnk', '.exe')


def resolver_acceso_directo(ruta_lnk):
    """Usa PowerShell (WScript.Shell) para obtener el TargetPath real de un .lnk."""
    try:
        # Comillas simples: PowerShell no interpreta '$' ni '`' dentro de ellas
        # (con comillas dobles, una ruta con '$' se rompía). La comilla simple
        # se escapa duplicándola. La salida se fuerza a UTF-8 para que rutas
        # con acentos/ñ no lleguen alteradas.
        ruta_ps = ruta_lnk.replace("'", "''")
        comando = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            f"(New-Object -ComObject WScript.Shell).CreateShortcut('{ruta_ps}').TargetPath"
        )
        resultado = subprocess.run(
            ['powershell', '-NoProfile', '-Command', comando],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        destino = resultado.stdout.decode('utf-8', errors='replace').strip()
        return destino or None
    except Exception as e:
        print(f"[!] No se pudo resolver el acceso directo: {e}")
        return None


def extraer_ip_de_vnc(ruta_vnc):
    """Lee un archivo .vnc (formato ini) y extrae el valor de 'host='."""
    try:
        with open(ruta_vnc, 'r', errors='ignore') as f:
            contenido = f.read()
        match = re.search(r'^\s*host\s*=\s*(.+)$', contenido, re.IGNORECASE | re.MULTILINE)
        return match.group(1).strip() if match else None
    except Exception:
        return None


def analizar_archivo(ruta_original):
    """
    Analiza el archivo soltado/elegido y regresa (datos, None) con lo que se
    pudo detectar automáticamente:
        {'categoria', 'nombre_sugerido', 'action', 'ip'}
    o (None, mensaje_error) si la extensión no es soportada o algo falló.
    """
    ext = os.path.splitext(ruta_original)[1].lower()
    nombre_sin_ext = os.path.splitext(os.path.basename(ruta_original))[0]

    if ext in EXTENSIONES_VNC:
        ip = extraer_ip_de_vnc(ruta_original)
        return {
            "categoria": "VNC",
            "nombre_sugerido": nombre_sin_ext,
            "action": f"vnc {ip}" if ip else "",
            "ip": ip or "",
        }, None

    if ext == '.lnk':
        destino = resolver_acceso_directo(ruta_original)
        if not destino:
            return None, f"No se pudo resolver el acceso directo: {os.path.basename(ruta_original)}"
        return {
            "categoria": "APPS",
            "nombre_sugerido": nombre_sin_ext,
            "action": f'open "{destino}"',
            "ip": "",
        }, None

    if ext == '.exe':
        return {
            "categoria": "APPS",
            "nombre_sugerido": nombre_sin_ext,
            "action": f'open "{ruta_original}"',
            "ip": "",
        }, None

    return None, f"Extensión no soportada: '{ext or '(sin extensión)'}'. Usa .vnc, .lnk o .exe."
