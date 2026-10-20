"""
logo.py -- el nombre ELIZA en letras de bloque doradas, terminado con un
pequeño punto final dorado (un triángulo ▲ a la altura de la base de las
letras). Solo usa caracteres que se ven bien en cualquier consola de Windows.
"""

from rich.text import Text

LETRAS = {
    'E': ["██████", "██    ", "████  ", "██    ", "██████"],
    'L': ["██    ", "██    ", "██    ", "██    ", "██████"],
    'I': ["██████", "  ██  ", "  ██  ", "  ██  ", "██████"],
    'Z': ["██████", "    ██", "  ██  ", "██    ", "██████"],
    'A': [" ████ ", "██  ██", "██████", "██  ██", "██  ██"],
}
PUNTO = ["", "", "", "", "▲"]   # punto final, solo en la última fila

# Degradado dorado de arriba hacia abajo
DORADOS = ["#fff1a8", "#ffe066", "#ffd700", "#f0b400", "#c99400"]
PUNTO_COLOR = "#ffd700"


def logo():
    texto = Text()
    for fila in range(5):
        linea = "  ".join(LETRAS[letra][fila] for letra in "ELIZA")
        texto.append(linea, style=f"bold {DORADOS[fila]}")
        texto.append(" ")
        texto.append(PUNTO[fila] or " ", style=f"bold {PUNTO_COLOR}")
        if fila < 4:
            texto.append("\n")
    return texto
