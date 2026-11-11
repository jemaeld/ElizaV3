"""
compat.py -- caracteres seguros para la consola clásica de Windows 10.

La consola clásica (conhost, la ventana negra de Windows 10) con fuentes
como Consolas no tiene los bloques finos que Textual usa en algunos bordes
(▔ ▁ ▊ ▎ ▏), en la barra de desplazamiento (▁▂▃…▇) ni los emoji del
explorador (📁 📄). Ahí se ven como '?'. Windows Terminal (el de Windows 11)
sí los tiene.

Si se detecta la consola clásica, se cambian por equivalentes que existen en
cualquier fuente: líneas de caja (─│╭╮), bloques completos (█▀▄▌▐) y ASCII.

Detección: Windows sin la variable WT_SESSION (Windows Terminal la define).
Se puede forzar en eliza_local.json:  "consola": "simple" | "completa".
"""

import os

# Caracteres que trae cualquier fuente de consola de Windows (Consolas, Lucida Console)
_SEGUROS = set(chr(c) for c in range(0x20, 0x7F)) | set(chr(c) for c in range(0x2500, 0x2580)) \
    | set("█▀▄▌▐░▒▓")


def es_consola_simple(local=None):
    preferencia = str((local or {}).get('consola', '')).lower()
    if preferencia in ('simple', 'completa'):
        return preferencia == 'simple'
    return os.name == 'nt' and not os.environ.get('WT_SESSION')


def _reemplazar_bordes():
    from textual import _border
    reemplazados = []
    for nombre, filas in list(_border.BORDER_CHARS.items()):
        if all(c in _SEGUROS for fila in filas for c in fila):
            continue
        # vkey/hkey/tall/outer/… -> 'round' (mismo tamaño: 1 celda por lado)
        _border.BORDER_CHARS[nombre] = _border.BORDER_CHARS['round']
        _border.BORDER_LOCATIONS[nombre] = _border.BORDER_LOCATIONS['round']
        reemplazados.append(nombre)
    for cache in ('get_box', '_get_box'):
        funcion = getattr(_border, cache, None)
        if hasattr(funcion, 'cache_clear'):
            funcion.cache_clear()
    return reemplazados


def aplicar(local=None):
    """Llamar ANTES de crear la App. Devuelve True si se activó el modo simple."""
    if not es_consola_simple(local):
        return False
    try:
        _reemplazar_bordes()
    except Exception:  # noqa: BLE001 - si cambia Textual, mejor verse feo que no arrancar
        pass
    try:
        from textual.scrollbar import ScrollBarRender
        # Sin bloques parciales: el pulgar de la barra se dibuja solo con color de fondo.
        ScrollBarRender.VERTICAL_BARS = [" "] * len(ScrollBarRender.VERTICAL_BARS)
        ScrollBarRender.HORIZONTAL_BARS = [" "] * len(ScrollBarRender.HORIZONTAL_BARS)
    except Exception:  # noqa: BLE001
        pass
    try:
        from textual.widgets import DirectoryTree
        DirectoryTree.ICON_NODE = "+ "
        DirectoryTree.ICON_NODE_EXPANDED = "- "
        DirectoryTree.ICON_FILE = "  "
    except Exception:  # noqa: BLE001
        pass
    return True
