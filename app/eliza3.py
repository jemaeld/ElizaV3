"""
eliza3.py -- punto de entrada de Eliza V3 (lo ejecuta Eliza.bat).

Código de salida 10 = se instaló una actualización: Eliza.bat revisa
dependencias y vuelve a arrancar.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.app import ElizaApp  # noqa: E402


def main():
    app = ElizaApp()
    app.run()
    return app.return_code or 0


if __name__ == "__main__":
    sys.exit(main())
