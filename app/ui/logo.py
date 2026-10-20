"""
logo.py -- el nombre ELIZA en letras de bloque doradas, con una chispa dorada
(emblema original) después del nombre. Solo usa caracteres de bloque, que
se ven bien en cualquier consola de Windows.
"""

from rich.text import Text

LETRAS = {
    'E': ["██████", "██    ", "████  ", "██    ", "██████"],
    'L': ["██    ", "██    ", "██    ", "██    ", "██████"],
    'I': ["██████", "  ██  ", "  ██  ", "  ██  ", "██████"],
    'Z': ["██████", "    ██", "  ██  ", "██    ", "██████"],
    'A': [" ████ ", "██  ██", "██████", "██  ██", "██  ██"],
}
CHISPA = ["  ▄  ", " ▐█▌ ", "▀███▀", " ▐█▌ ", "  ▀  "]

# Degradado dorado de arriba hacia abajo
DORADOS = ["#fff1a8", "#ffe066", "#ffd700", "#f0b400", "#c99400"]
CHISPA_COLOR = "#fff6c2"


def logo():
    texto = Text()
    for fila in range(5):
        linea = "  ".join(LETRAS[letra][fila] for letra in "ELIZA")
        texto.append(linea, style=f"bold {DORADOS[fila]}")
        texto.append("  ")
        texto.append(CHISPA[fila], style=f"bold {CHISPA_COLOR}")
        if fila < 4:
            texto.append("\n")
    return texto
