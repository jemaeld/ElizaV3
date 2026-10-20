"""
bitacora_tools.py
-------------------
Lógica pura (sin GUI/consola) para la Bitácora de Control: redondeo de hora,
cálculo de turno, formato TSV (para pegar en Excel) e interpretación de
fechas escritas por el usuario.

En V3 los registros viven en la base (tabla bitacora, ver db.py); aquí
solo queda la lógica pura. La hora se guarda redondeada a 5 minutos.
"""

import re
from datetime import datetime, time, timedelta


def redondear_hora_5min(momento=None):
    """Redondea un datetime (por defecto, ahora) a los 5 minutos más cercanos."""
    momento = momento or datetime.now()
    resto = momento.minute % 5
    minutos_base = (momento.minute // 5) * 5
    minutos_a_sumar = minutos_base + (5 if resto >= 3 else 0)
    return momento.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minutos_a_sumar)


def calcular_turno(hora_str):
    """
    Determina el turno según la hora (idéntico a V1):
    A: 07:00 - 15:30 | B: 15:30 - 23:30 | C: 23:30 - 07:00
    """
    try:
        h = datetime.strptime(hora_str, "%H:%M:%S").time()
        t_0700 = time(7, 0, 0)
        t_1530 = time(15, 30, 0)
        t_2330 = time(23, 30, 0)
        if t_0700 <= h < t_1530:
            return "A"
        elif t_1530 <= h < t_2330:
            return "B"
        else:
            return "C"
    except ValueError:
        return "?"


def formatear_tsv(registros):
    """
    Arma el bloque de texto separado por tabs, listo para pegar en Excel.
    Mismo formato/orden de columnas que usaba V1:
    JDRG | TURNO | FECHA | HORA | LINEA | EST | TIEMPO | FALLA | AJUSTE | (vacío) | (vacío) | AUDITOR | PREFIJO | COMENTARIOS
    """
    lineas = []
    for r in registros:
        hora_str = r.get('hora', '00:00:00')
        turno = calcular_turno(hora_str)
        falla = r.get('falla', '').replace('\n', ' ').replace('\t', ' ')
        ajuste = r.get('ajuste', '').replace('\n', ' ').replace('\t', ' ')
        comentarios = r.get('comentarios', '').replace('\n', ' ').replace('\t', ' ')

        linea = (
            f"JDRG\t"
            f"{turno}\t"
            f"{r.get('fecha', '')}\t"
            f"{hora_str}\t"
            f"{r.get('linea', '')}\t"
            f"{r.get('estacion', '')}\t"
            f"{r.get('tiempo', '')}\t"
            f"{falla}\t"
            f"{ajuste}\t"
            f"\t"
            f"\t"
            f"{r.get('auditor', '')}\t"
            f"{r.get('prefijo', '')}\t"
            f"{comentarios}"
        )
        lineas.append(linea)
    return "\n".join(lineas)


def resolver_fecha_arg(argumento):
    """
    Convierte el argumento de /bitacora en una fecha 'YYYY-MM-DD', completando
    mes y/o año actuales cuando no se especifican. Formatos aceptados:
      - 'hoy' / 'show'          -> fecha de hoy
      - 'ayer'                  -> fecha de ayer
      - 'YYYY-MM-DD'            -> tal cual (ej. 2026-07-25)
      - 'MM/DD'                 -> año actual (ej. 07/25 -> 25 de julio de este año)
      - 'MM/DD/YYYY'            -> fecha completa (ej. 07/25/2026)
      - 'DD'                    -> mes y año actuales (ej. 25 -> día 25 de este mes)

    Devuelve (fecha_str, None) si se pudo resolver, o (None, mensaje_error) si no.
    """
    argumento = argumento.strip()
    ahora = datetime.now()

    if argumento.lower() in ('hoy', 'show'):
        return ahora.strftime('%Y-%m-%d'), None

    if argumento.lower() == 'ayer':
        return (ahora - timedelta(days=1)).strftime('%Y-%m-%d'), None

    # YYYY-MM-DD completo
    if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', argumento):
        try:
            fecha = datetime.strptime(argumento, '%Y-%m-%d')
            return fecha.strftime('%Y-%m-%d'), None
        except ValueError:
            return None, f"Fecha inválida: '{argumento}'."

    # MM/DD o MM/DD/YYYY
    if '/' in argumento:
        partes = argumento.split('/')
        try:
            if len(partes) == 2:
                mes, dia = int(partes[0]), int(partes[1])
                anio = ahora.year
            elif len(partes) == 3:
                mes, dia, anio = int(partes[0]), int(partes[1]), int(partes[2])
                if anio < 100:
                    anio += 2000
            else:
                return None, f"Formato de fecha no reconocido: '{argumento}'. Usa MM/DD o MM/DD/YYYY."
            fecha = datetime(anio, mes, dia)
            return fecha.strftime('%Y-%m-%d'), None
        except ValueError:
            return None, f"Fecha inválida: '{argumento}'."

    # Solo el día (número) -> mes y año actuales
    if argumento.isdigit():
        try:
            fecha = datetime(ahora.year, ahora.month, int(argumento))
            return fecha.strftime('%Y-%m-%d'), None
        except ValueError:
            return None, f"Día inválido para el mes actual: '{argumento}'."

    return None, f"No se reconoce el formato de fecha: '{argumento}'. Usa YYYY-MM-DD, MM/DD, o solo el día."
