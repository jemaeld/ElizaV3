# Eliza V3

Lanzador de herramientas industriales **manejado con teclado**, con
apariencia de consola: VNC, aplicaciones, proyectos ACD, bitácora de turno,
red y monitor de variables Allen-Bradley.

Es la sucesora de [Eliza V2](https://github.com/jemaeld/Eliza), que sigue
operando: las dos pueden convivir en el mismo equipo y apuntar a la misma
carpeta de datos.

> El nombre viene de Zelda **Eliza**beth.

## Instalar

1. Requisito: **Python 3.10+** (python.org, con "Add python.exe to PATH").
2. Copia **`Eliza.bat`** y **`Eliza.py`** a una carpeta **distinta a la de
   V2** (ej. `C:\Eliza3`).
3. Ejecuta `Eliza.bat`. La primera vez descarga la última versión, crea
   `.venv`, instala dependencias y arranca. Eliza pregunta la **carpeta de
   datos**: remota/compartida (la de red) o local.
4. Si esa carpeta tiene datos de **Eliza V2** y todavía no tiene `eliza.db`,
   Eliza ofrece **migrarlos** (una sola vez): VNC, APPS, ACD y configuración.
   La bitácora no se migra (V3 usa los mismos JSON). Los archivos de V2 no se
   tocan.
5. Pide la **contraseña de acceso** (la misma que en V2).

Recomendado: **Windows Terminal** (en Windows 11 viene por defecto). La
consola clásica también funciona.

## Uso

Todo con teclado, desde la línea `ELIZA>`:

| Tecla | Qué hace |
|---|---|
| escribir | filtra la base por nombre, IP o comentario (varias palabras: todas) |
| ↑ ↓ PgUp PgDn | eligen en la tabla |
| Enter | ejecuta la entrada o el comando elegido |
| Tab | completa el nombre |
| `/` | lista los comandos |
| Esc | borra la línea |
| F1 · F5 · Ctrl+L · Ctrl+Q | ayuda · recargar · limpiar registro · salir |

| Comando | Qué hace |
|---|---|
| `/bitacora` | captura un registro (formulario; fecha y hora automáticas) |
| `/bitacora hoy` · `ayer` · `DD` · `MM/DD` · `YYYY-MM-DD` | visor del día: ←/→ cambia de día, n nuevo, Enter editar, Supr borrar, y copiar a Excel, x exportar .tsv |
| `/edit [vnc\|apps\|acd]` | editor de la base: Enter editar, n nueva, Supr borrar, c categoría, o orden, r reescanear ACD |
| `/add` | agregar VNC/APPS eligiendo un .vnc/.lnk/.exe en un explorador de consola |
| `/scan_acd [carpeta]` | buscar ACD/L5K y registrarlos (Enter), a abrir, u ubicación |
| `/logix [ip\|nombre]` | **Monitor de variables** Allen-Bradley (ver abajo) |
| `/ip` · `/ping` | red |
| `/settings` · `/reload` · `/update` | carpeta de datos · recargar · actualizar |
| `/clear` · `/help` · `/salir` | |

En todas las pantallas: `/` filtra, Esc vuelve.

### Monitor de variables (`/logix`)

Tabla `CONEX | IP | POLL | TAG | VALOR | ESCRITURA | COMENTARIO`, que se
actualiza en vivo. Cada fila es una conexión propia.

| Tecla | Qué hace |
|---|---|
| `a` | agregar tag: asistente con IP, Scope **Principal / Subprograma**, Programa y Tag. Lee del PLC los programas y tags (en segundo plano) y los ofrece mientras escribes: ↓ entra a la lista, → acepta la sugerencia. Pegar `Program:X.Y` lo reparte solo |
| Enter / `e` | editar el tag de la fila con el mismo asistente |
| Espacio | conectar / desconectar (`● ON` · `○ OFF` · `× ERR`) |
| `w` | **escribir** 1..N veces (o continuo) al ritmo del polling, con indicador **IDLE → WORKING n/N → DONE**, progreso y bitácora de cada escritura. Esc cierra la ventana y la escritura sigue |
| `s` | detener todas las escrituras |
| `g` · `l` | guardar / cargar conjuntos de tags en la base (o importar un `.json` de V2) |
| Supr | quitar la fila |

El detalle de la fila seleccionada (error exacto, escritura) va en la línea
de estado de abajo. Cada ciclo escribe y luego lee, así el valor muestra el
efecto de la escritura.

## Datos

La base (VNC, APPS, ACD, configuración, conjuntos de tags) vive en un solo
archivo **`eliza.db`** (SQLite) dentro de la carpeta de datos, junto a
`_acd_store\` (los proyectos ACD siguen siendo archivos, igual que en V2).

La **bitácora** NO va en la base: se queda en `bitacora\YYYY-MM-DD.json`,
un archivo por día, con el **formato exacto de V2** (mismas claves, mismo
orden, mismo formato). V2, V3 y otros programas usan esos archivos a la vez;
el visor de V3 se recarga solo si el archivo del día cambia. Pensado para carpeta de red: transacciones cortas,
reintentos si otro equipo está escribiendo, y sin modo WAL (no es seguro
sobre red).

Migración manual (si se necesita fuera del primer arranque):

```
.venv\Scripts\python.exe app\migrar_v2.py "S:\...\carpeta de datos V2" --simular
.venv\Scripts\python.exe app\migrar_v2.py "S:\...\carpeta de datos V2"
```

## Actualizar

`/update` dentro de Eliza (o `python Eliza.py actualizar`). El repositorio
es público: no requiere token.

## Estado

- [x] **Fase 1**: núcleo, base SQLite, migrador V2→V3, instalador,
      lanzador, primer arranque, contraseña, `/ip` `/ping` `/settings`
      `/reload` `/update`.
- [x] **Fase 2**: editor de la base, alta (VNC/APPS), `/scan_acd`, bitácora.
- [x] **Fase 3**: `/logix` (monitor de variables + escritura 1..N + asistente
      de tags).

## Código

| Archivo | Rol |
|---|---|
| `Eliza.bat` / `Eliza.py` | instalador, lanzador y actualizador |
| `app/eliza3.py` | punto de entrada |
| `app/ui/app.py` | aplicación Textual: lanzador, comandos, arranque |
| `app/ui/modales.py` | ventanas emergentes (menús, contraseña, carpetas) |
| `app/ui/formulario.py` · `app/ui/pantalla.py` | formulario genérico y base de pantallas con tabla |
| `app/ui/editor.py` · `app/ui/alta.py` · `app/ui/explorador.py` | editor de la base, /add y explorador de archivos |
| `app/ui/scan_acd.py` · `app/ui/bitacora.py` | /scan_acd y bitácora |
| `app/ui/logix.py` · `app/ui/logix_tag.py` · `app/ui/logix_escritura.py` | monitor de variables, asistente de tags y ventana de escritura |
| `app/logix_monitor.py` | motor del monitor: un hilo por fila, lectura y escritura 1..N (sin interfaz) |
| `app/ui/tema.tcss` · `app/ui/logo.py` | estilo de consola y logo dorado |
| `app/db.py` | base SQLite (entradas, bitácora, config, registros logix) |
| `app/migrar_v2.py` | migración de un solo uso desde V2 |
| `app/rutas.py` · `app/licencia.py` | carpeta de datos y contraseña de acceso |
| `app/acciones.py` | ejecutar entradas (VNC, apps, ACD) |
| `app/acd_tools.py` · `app/add_tools.py` · `app/bitacora_tools.py` · `app/logix_tools.py` · `app/logix_explorador.py` · `app/network_tools.py` | lógica heredada de V2 |

**Agregar un comando:** en `app/ui/app.py`, método `cmd_xxx(self, arg)` y
una línea en `COMANDOS`.
