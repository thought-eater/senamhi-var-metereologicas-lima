"""Descarga TEMP, HR, PP y viento de seis estaciones EMA de Lima Metropolitana.

El script automatiza Chromium con zendriver y usa asyncio para esperar sin
bloquear las operaciones de navegador y los eventos de red. Tras abrir cada
estación, habilita Chrome DevTools Protocol (CDP), activa la pestaña de tabla y
selecciona, de forma secuencial, los meses 202501 a 202606. En vez de leer el
DOM ya renderizado, intercepta la respuesta del endpoint de datos, obtiene su
body HTML mediante CDP y analiza ``table#dataTable`` con BeautifulSoup.

El resultado se escribe en ``var_meteorologicas_lima_2025_2026.csv`` con las
columnas ``ESTACION, FECHA, HORA, LONGITUD, LATITUD, ALTITUD, TEMP, HR, PP,
DIR_VIENTO, VEL_VIENTO, RED, DISTRITO``. ``FECHA`` usa ``YYYYMMDD`` y ``HORA``
usa ``HH*10000``. La zona horaria no queda registrada en el CSV.
Los metadatos geográficos se toman de :data:`LIMA_EMA`; su procedencia y fecha
de actualización tampoco se incorporan al archivo.

El flujo depende de selectores, posiciones de columnas y nombres de eventos
del portal, por lo que cambios en su HTML o JavaScript pueden producir meses
vacíos, timeouts o errores de selección. Los fallos mensuales se reintentan y
se omiten al agotarse; fallos de preparación de una estación se propagan hasta
``main``, que siempre intenta detener el navegador.

Uso recomendado::

    uv run senamhi-var-metereologicas-lima

El wrapper heredado ``scraper_var_meterologicas.py`` ofrece el mismo flujo.
"""

import argparse
import asyncio
import csv
import math
import random
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import zendriver as zd
from bs4 import BeautifulSoup
from zendriver import cdp

from . import settings
from .exceptions import ScrapingError, SelectNotFoundError
from .html_utils import extract_select_options
from .station_service import create_station_url, find_station_by_code

# ── Período objetivo ────────────────────────────────────────────────────────
START_YYYYMM = 202501
END_YYYYMM = 202606

# ── Estaciones EMA de Lima Metropolitana ────────────────────────────────────
# Metadatos configurados para el CSV; el código no registra su procedencia.
LIMA_EMA = {
    "CERES": {
        "codigo": "112278",
        "lon": -76.92711,
        "lat": -12.02867,
        "alt": None,
        "dist": "ATE",
    },
    "CAMPO_DE_MARTE": {
        "codigo": "112181",
        "lon": -77.04314,
        "lat": -12.07056,
        "alt": 117.0,
        "dist": "JESUS_MARIA",
    },
    "CARABAYLLO": {
        "codigo": "111286",
        "lon": -77.03364,
        "lat": -11.90219,
        "alt": 179.0,
        "dist": "CARABAYLLO",
    },
    "SANTA_ANITA": {
        "codigo": "112208",
        "lon": -76.97144,
        "lat": -12.04302,
        "alt": 253.0,
        "dist": "SANTA_ANITA",
    },
    "SAN_BORJA": {
        "codigo": "112193",
        "lon": -77.00769,
        "lat": -12.10859,
        "alt": 128.0,
        "dist": "SAN_BORJA",
    },
    "SAN_JUAN_DE_LURIGANCHO": {
        "codigo": "112267",
        "lon": -76.99925,
        "lat": -11.98164,
        "alt": 240.0,
        "dist": "SAN_JUAN_DE_LURIGANCHO",
    },
    "SAN_MARTIN_DE_PORRES": {
        "codigo": "112265",
        "lon": -77.08447,
        "lat": -12.00889,
        "alt": 56.0,
        "dist": "SAN_MARTIN_DE_PORRES",
    },
}

OUTPUT_FILE = "var_meteorologicas_lima_2025_2026.csv"
HISTORY_DIR = Path(__file__).resolve().parents[2] / "history"
CSV_COLUMNS = [
    "ESTACION",
    "FECHA",
    "HORA",
    "LONGITUD",
    "LATITUD",
    "ALTITUD",
    "TEMP",
    "HR",
    "PP",
    "DIR_VIENTO",
    "VEL_VIENTO",
    "RED",
    "DISTRITO",
]
KEY_COLUMNS = ["ESTACION", "FECHA", "HORA"]
MEASUREMENT_COLUMNS = ["TEMP", "HR", "PP", "DIR_VIENTO", "VEL_VIENTO"]
NUMERIC_SENTINELS = {-999.0, -9999.0, 9999.0, 99999.0}


# ── Parseo de tabla HTML ─────────────────────────────────────────────────────


def _safe_float(s: str):
    """Convierte una celda numérica del portal sin interrumpir el mes.

    Args:
        s: Texto de una celda; se eliminan espacios en los extremos.

    Returns:
        El valor ``float`` o ``None`` cuando el texto está vacío, es exactamente
        ``S/D`` o no puede convertirse. Esta tolerancia representa ausencias y
        valores inesperados como campos vacíos en el CSV, en lugar de descartar
        toda la fila.
    """
    s = s.strip()
    if s.upper() in {"", "NULL", "NAN", "NA", "N/A", "N/D", "S/D", "-"}:
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    if not math.isfinite(value) or value in NUMERIC_SENTINELS:
        return None
    return value


def _normalize_header(text: str) -> str:
    """Normaliza un encabezado HTML para compararlo sin tildes ni mayúsculas.

    SENAMHI puede incluir unidades o variar capitalización. La normalización no
    modifica datos: solo permite reconocer, por ejemplo, ``Precipitación (mm)``
    mediante la raíz ``precipit``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(without_accents.lower().split())


def _response_error(html: str) -> str | None:
    """Describe respuestas de error que no deben confundirse con meses vacíos."""
    normalized = _normalize_header(html)
    if "captcha" in normalized and (
        "invalido" in normalized or "invalid" in normalized
    ):
        return "SENAMHI rechazó el CAPTCHA"
    return None


def parse_ema_table(html: str, nombre: str, meta: dict) -> list[dict]:
    """Convierte ``table#dataTable`` de una respuesta EMA en registros CSV.

    Primero identifica columnas por el texto del encabezado. Esto evita asignar,
    por ejemplo, dirección del viento a ``HR`` si una estación publica sensores
    adicionales o cambia el orden. Si el encabezado no contiene nombres
    reconocibles, usa como fallback el contrato históricamente observado:
    fecha=0, hora=1, temperatura=2, precipitación=3, humedad=4, dirección del
    viento=5 y velocidad del viento=6. Las posiciones de viento solo se aplican
    cuando la tabla tiene las siete columnas EMA; así se preservan respuestas
    antiguas de cinco columnas. El fallback queda documentado como una ruta más
    frágil.

    Args:
        html: Body HTML capturado de la respuesta mensual.
        nombre: Nombre configurado que se replica como ``ESTACION``.
        meta: Mapeo con ``lon``, ``lat``, ``alt`` y ``dist``; esos valores se
            copian a cada fila sin validarlos ni registrar su procedencia.

    Returns:
        Registros con el esquema de :data:`CSV_COLUMNS`. ``FECHA`` se codifica
        como ``YYYYMMDD``, ``HORA`` como ``HH*10000`` y ``RED`` como ``EMA``.
        Devuelve una colección vacía si falta la tabla. Omite encabezado, filas
        que no contienen todas las columnas requeridas y filas cuya fecha u hora
        no sean parseables. Las variables no numéricas se conservan como
        ``None``.

    Notes:
        La hora se toma literalmente de la tabla y la zona horaria queda sin
        registrar. BeautifulSoup usa el parser HTML incluido en Python.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="dataTable")
    if not table:
        raise ScrapingError("La respuesta no contiene table#dataTable")

    table_rows = table.find_all("tr")
    if not table_rows:
        raise ScrapingError("La tabla EMA no contiene filas")

    header_cells = [
        _normalize_header(cell.get_text(" ", strip=True))
        for cell in table_rows[0].find_all(["td", "th"])
    ]

    def find_column(*fragments: str) -> int | None:
        for index, header in enumerate(header_cells):
            if any(fragment in header for fragment in fragments):
                return index
        return None

    column_indexes: dict[str, int | None] = {
        "fecha": find_column("fecha", "ano / mes / dia", "ano/mes/dia"),
        "hora": find_column("hora"),
        "temp": find_column("temperatura", "temp"),
        "pp": find_column("precipit", "pp"),
        "hr": find_column("humedad", "hr"),
        "dir_viento": find_column(
            "direccion del viento",
            "direccion viento",
            "dir. viento",
            "dir viento",
        ),
        "vel_viento": find_column(
            "velocidad del viento",
            "velocidad viento",
            "vel. viento",
            "vel viento",
        ),
    }
    recognized_measurements = sum(
        column_indexes[name] is not None
        for name in ("temp", "pp", "hr", "dir_viento", "vel_viento")
    )
    if (
        column_indexes["fecha"] is None
        or column_indexes["hora"] is None
        or recognized_measurements == 0
    ):
        has_full_ema_schema = len(header_cells) >= 7
        column_indexes = {
            "fecha": 0,
            "hora": 1,
            "temp": 2,
            "pp": 3,
            "hr": 4,
            "dir_viento": 5 if has_full_ema_schema else None,
            "vel_viento": 6 if has_full_ema_schema else None,
        }

    present_indexes = [index for index in column_indexes.values() if index is not None]

    def measurement(cells: list[str], name: str) -> float | None:
        """Convierte una variable si su encabezado existe en esta estación."""
        index = column_indexes[name]
        return None if index is None else _safe_float(cells[index])

    rows = []
    for tr in table_rows[1:]:  # la primera fila ya se interpretó como encabezado
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) <= max(present_indexes):
            continue
        try:
            parts = cells[column_indexes["fecha"]].replace("/", "-").split("-")
            yyyy, mm, dd = int(parts[0]), int(parts[1]), int(parts[2])
            hour_text = cells[column_indexes["hora"]].strip()
            hour_match = re.fullmatch(r"(\d{1,2}):00(?::00)?", hour_text)
            if hour_match is None:
                raise ValueError("La hora no corresponde a una observación horaria")
            hh = int(hour_match.group(1))
            # date valida el calendario; el portal entrega horas enteras.
            calendar_date = date(yyyy, mm, dd)
            if not 0 <= hh <= 23:
                raise ValueError("Hora fuera de rango")

            rows.append(
                {
                    "ESTACION": nombre,
                    "FECHA": calendar_date.year * 10000
                    + calendar_date.month * 100
                    + calendar_date.day,
                    "HORA": hh * 10000,
                    "LONGITUD": meta["lon"],
                    "LATITUD": meta["lat"],
                    "ALTITUD": meta["alt"],
                    "TEMP": measurement(cells, "temp"),
                    "HR": measurement(cells, "hr"),
                    "PP": measurement(cells, "pp"),
                    "DIR_VIENTO": measurement(cells, "dir_viento"),
                    "VEL_VIENTO": measurement(cells, "vel_viento"),
                    "RED": "EMA",
                    "DISTRITO": meta["dist"],
                }
            )
        except (ValueError, IndexError):
            continue

    if not rows and len(table_rows) > 1:
        raise ScrapingError("La tabla EMA no contiene filas horarias válidas")
    return rows


# ── Automatización de navegador ──────────────────────────────────────────────


async def _setup_page(browser, url: str):
    """Prepara una página y su canal de respuestas mensuales completadas.

    ``asyncio`` permite suspender esta corrutina mientras Chromium navega o
    emite eventos, sin bloquear el loop. CDP ``Network.enable`` habilita dos
    eventos complementarios: ``ResponseReceived`` identifica respuestas cuyo
    URL contiene :data:`settings.DATA_ENDPOINT`, y ``LoadingFinished`` indica
    que el body de esa solicitud ya puede pedirse. Un ``set`` mantiene los
    request ids pendientes y evita confundir finalizaciones de otros recursos;
    una ``asyncio.Queue`` entrega, en orden de finalización, los ids listos al
    consumidor.

    Al hacer clic en ``a#tabla-tab``, el portal genera un POST inicial para el
    mes preseleccionado. Se consume una entrada de la cola, si llega dentro de
    15 segundos, para que la primera captura explícita no reciba ese body viejo.

    Args:
        browser: Instancia zendriver activa con método asíncrono ``get``.
        url: URL completa de la estación.

    Returns:
        Tupla ``(page, queue)``. Los handlers permanecen asociados a ``page`` y
        seguirán alimentando la cola durante las consultas de la estación.

    Raises:
        SelectNotFoundError: Si no aparece ``select#CBOFiltro`` después de
            activar la pestaña.
        Exception: Propaga fallos de navegación, CDP o espera de selectores.

    Side Effects:
        Navega a la URL, habilita captura de red, registra handlers, ejecuta
        JavaScript en la página y puede esperar hasta 15 segundos al descartar
        la respuesta inicial. Los selectores son contratos frágiles del portal.
    """
    page = await browser.get(url)
    await page.send(cdp.network.enable())

    queue: asyncio.Queue = asyncio.Queue()
    pending: set = set()

    async def on_response(evt: cdp.network.ResponseReceived):
        """Registra una respuesta candidata hasta recibir su finalización.

        Añade el request id al ``pending`` compartido solo si el URL contiene
        el fragmento configurado. No valida método HTTP ni consume el body.
        """
        if settings.DATA_ENDPOINT in str(evt.response.url):
            pending.add(evt.request_id)

    async def on_finished(evt: cdp.network.LoadingFinished):
        """Publica un request pendiente cuyo body ya está disponible.

        Retira el id del conjunto y lo coloca en la cola compartida. Las cargas
        ajenas al endpoint se ignoran; una carga abortada que no emita este
        evento no llega a la cola y será tratada como timeout por el consumidor.
        """
        if evt.request_id in pending:
            pending.discard(evt.request_id)
            await queue.put(evt.request_id)

    page.add_handler(cdp.network.ResponseReceived, on_response)
    page.add_handler(cdp.network.LoadingFinished, on_finished)

    await page.wait_for(selector="a#tabla-tab")
    await page.send(
        cdp.runtime.evaluate(expression="document.querySelector('a#tabla-tab').click()")
    )

    if not await page.wait_for(selector="select#CBOFiltro"):
        raise SelectNotFoundError("select#CBOFiltro no encontrado")

    try:
        await asyncio.wait_for(queue.get(), timeout=15)
    except TimeoutError:
        pass

    return page, queue


async def _capture(page, queue: asyncio.Queue, action) -> str:
    """Ejecuta un cambio de filtro y devuelve el body de su respuesta.

    Antes de la acción vacía ids atrasados para asociar la próxima respuesta al
    cambio actual. Después espera como máximo :data:`settings.TIMEOUT_SECONDS`
    y usa CDP ``Network.getResponseBody``; no espera una actualización del DOM.

    Args:
        page: Página zendriver con captura de red ya configurada.
        queue: Cola alimentada por los handlers de :func:`_setup_page`.
        action: Corrutina sin argumentos que cambia el ``select`` y dispara la
            petición del portal.

    Returns:
        Body de la respuesta como texto HTML.

    Raises:
        asyncio.TimeoutError: Si no finaliza una respuesta coincidente dentro
            del timeout.
        Exception: Propaga fallos de la acción o de ``get_response_body``.

    Notes:
        El filtro se basa en una subcadena del URL y no verifica aquí el método
        HTTP; el contrato observado del portal produce un POST por cambio.
    """
    while not queue.empty():
        queue.get_nowait()
    await action()
    req_id = await asyncio.wait_for(queue.get(), timeout=settings.TIMEOUT_SECONDS)
    body, _ = await page.send(cdp.network.get_response_body(req_id))
    return body


# ── Scraping por estación ────────────────────────────────────────────────────


async def scrape_station(
    browser,
    nombre: str,
    meta: dict,
    start_yyyymm: int = START_YYYYMM,
    end_yyyymm: int = END_YYYYMM,
) -> list[dict]:
    """Descarga secuencialmente los meses objetivo de una estación.

    Resuelve el código contra la base cargada por :mod:`src.station_service`,
    filtra las opciones numéricas ``YYYYMM`` dentro del rango inclusivo y
    dispara el evento JavaScript ``change`` para cada mes. Procesar meses en
    serie permite asociar una respuesta CDP con una única selección y aplicar
    pausas de cortesía; asyncio se usa para la E/S, no para paralelizar
    estaciones ni meses.

    Args:
        browser: Instancia zendriver compartida por todas las estaciones.
        nombre: Etiqueta de salida y de progreso.
        meta: Configuración con código SENAMHI y metadatos de salida.
        start_yyyymm: Primer mes incluido, codificado como ``YYYYMM``.
        end_yyyymm: Último mes incluido, codificado como ``YYYYMM``.

    Returns:
        Todos los registros parseados de los meses exitosos. Devuelve una
        colección vacía si el código no existe, no hay opciones en rango o
        todos los meses fallan.

    Side Effects:
        Navega, ejecuta JavaScript, imprime progreso y espera entre meses. Al
        cambiar de año añade :data:`settings.YEAR_BOUNDARY_SLEEP`; entre meses
        usa jitter uniforme. Cada mes realiza ``MAX_RETRIES + 1`` intentos y
        espera ``RETRY_SLEEP`` antes de reintentar. Los fallos definitivos se
        informan y se omiten para permitir que continúe la estación.

    Raises:
        Exception: Los fallos ocurridos antes del bucle mensual, como preparar
            la página o extraer el ``select``, no se capturan localmente.
    """
    station = find_station_by_code(meta["codigo"])
    if not station:
        print(
            f"{settings.ERROR} {nombre} ({meta['codigo']}) no encontrada en estaciones.json"
        )
        return []

    url = create_station_url(station)
    print(f"\n{settings.PROCESSING} {nombre} ({meta['codigo']})")

    page, queue = await _setup_page(browser, url)

    select_elem = await page.wait_for(selector="select#CBOFiltro")
    select_html = await select_elem.get_html()
    all_opts = extract_select_options(select_html)

    target_opts = sorted(
        [
            o
            for o in all_opts
            if o["value"].strip().isdigit()
            and start_yyyymm <= int(o["value"]) <= end_yyyymm
        ],
        key=lambda o: o["value"],
    )
    print(f"  {len(target_opts)} meses en rango {start_yyyymm}–{end_yyyymm}")

    all_rows = []
    prev_year = None

    for i, opt in enumerate(target_opts, 1):
        val = opt["value"]
        current_year = val[:4]

        if prev_year and current_year != prev_year:
            await asyncio.sleep(settings.YEAR_BOUNDARY_SLEEP)
        prev_year = current_year

        for attempt in range(settings.MAX_RETRIES + 1):
            try:

                async def action(v=val, current_page=page):
                    """Selecciona el mes y emite el ``change`` que genera el POST.

                    Captura el mes y la página del intento actual como argumentos
                    predeterminados. Ejecuta JavaScript y eleva
                    :class:`SelectNotFoundError` si la opción desapareció.
                    """
                    if not await current_page.query_selector(f"option[value='{v}']"):
                        raise SelectNotFoundError(f"Opción {v} no encontrada")
                    # Cambia el select y dispara el evento change que genera el POST
                    await current_page.send(
                        cdp.runtime.evaluate(
                            expression=(
                                f"(function(){{"
                                f"  var s=document.querySelector('#CBOFiltro');"
                                f"  s.value='{v}';"
                                f"  s.dispatchEvent(new Event('change',{{bubbles:true}}));"
                                f"}})()"
                            )
                        )
                    )

                html = await _capture(page, queue, action)
                response_error = _response_error(html)
                if response_error:
                    raise ScrapingError(response_error)
                rows = parse_ema_table(html, nombre, meta)
                all_rows.extend(rows)
                print(f"  {settings.SUCCESS} {val}: {len(rows)} filas")
                break

            except Exception as exc:  # noqa: BLE001 - el mes completo es reintentable
                if attempt < settings.MAX_RETRIES:
                    print(f"  {settings.WARNING} {val} intento {attempt + 1}: {exc}")
                    await asyncio.sleep(settings.RETRY_SLEEP)
                    # Un CAPTCHA inválido o una respuesta desincronizada suele
                    # persistir en la página actual. Abrir nuevamente la ficha
                    # obtiene una sesión y handlers de red limpios.
                    page, queue = await _setup_page(browser, url)
                else:
                    print(
                        f"  {settings.ERROR} {val} fallido tras {attempt + 1} intentos: {exc}"
                    )

        if i < len(target_opts):
            await asyncio.sleep(
                random.uniform(settings.JITTER_MIN, settings.JITTER_MAX)
            )

    return all_rows


# ── Main ─────────────────────────────────────────────────────────────────────


def _read_historical_csvs(paths: list[Path]) -> list[list[dict]]:
    """Carga snapshots brutos compatibles sin recortar su cobertura temporal."""
    snapshots = []
    seen_paths = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot histórico no encontrado: {path}")

        with path.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames != CSV_COLUMNS:
                raise ValueError(
                    f"Esquema incompatible en {path}: se esperaba {CSV_COLUMNS}"
                )
            rows = []
            seen_keys = set()
            for raw in reader:
                row = {
                    **raw,
                    "FECHA": int(raw["FECHA"]),
                    "HORA": int(raw["HORA"]),
                }
                for column in [
                    "LONGITUD",
                    "LATITUD",
                    "ALTITUD",
                    *MEASUREMENT_COLUMNS,
                ]:
                    row[column] = _safe_float(raw[column])
                key = tuple(row[column] for column in KEY_COLUMNS)
                if key in seen_keys:
                    raise ValueError(f"{path} contiene la clave duplicada {key}")
                seen_keys.add(key)
                rows.append(row)
            snapshots.append(rows)
    return snapshots


def merge_observations(
    fresh_rows: list[dict], historical_snapshots: list[list[dict]]
) -> list[dict]:
    """Fusiona por clave y variable, dando prioridad a observaciones nuevas."""
    merged = {}

    for row in fresh_rows:
        row = row.copy()
        for variable in MEASUREMENT_COLUMNS:
            row[variable] = _safe_float(str(row[variable])) if row[variable] is not None else None
        key = tuple(row[column] for column in KEY_COLUMNS)
        if key in merged:
            current = merged[key]
            for variable in MEASUREMENT_COLUMNS:
                incoming_value = row[variable]
                if current[variable] is None and incoming_value is not None:
                    current[variable] = incoming_value
            continue
        merged[key] = row.copy()

    for snapshot in historical_snapshots:
        for row in snapshot:
            row = row.copy()
            for variable in MEASUREMENT_COLUMNS:
                row[variable] = (
                    _safe_float(str(row[variable])) if row[variable] is not None else None
                )
            key = tuple(row[column] for column in KEY_COLUMNS)
            if key not in merged:
                merged[key] = row.copy()
                continue

            current = merged[key]
            for variable in MEASUREMENT_COLUMNS:
                historical_value = row[variable]
                if current[variable] is None and historical_value is not None:
                    current[variable] = historical_value

    for row in merged.values():
        meta = LIMA_EMA.get(row["ESTACION"])
        if meta is None:
            continue
        row.update(
            {
                "LONGITUD": meta["lon"],
                "LATITUD": meta["lat"],
                "ALTITUD": meta["alt"],
                "RED": "EMA",
                "DISTRITO": meta["dist"],
            }
        )

    return sorted(
        merged.values(), key=lambda row: tuple(row[column] for column in KEY_COLUMNS)
    )


def backup_existing_csv(path: Path) -> Path | None:
    """Copia el CSV que será reemplazado dentro del historial local fechado."""
    if not path.exists():
        return None

    run_id = datetime.now(UTC).astimezone().strftime("%Y%m%d_%H%M%S")
    backup_dir = HISTORY_DIR / run_id
    backup_path = backup_dir / path.name
    suffix = 1
    while backup_path.exists():
        backup_dir = HISTORY_DIR / f"{run_id}_{suffix}"
        backup_path = backup_dir / path.name
        suffix += 1

    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    return backup_path


def _write_csv(rows: list[dict], out: Path) -> None:
    """Escribe filas mediante reemplazo atómico."""
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(out)


async def main(args: argparse.Namespace):
    """Orquesta Chromium, consolida filas y escribe el CSV final.

    Las estaciones se procesan secuencialmente con una sola instancia de
    Chromium. El bloque ``finally`` intenta detenerla incluso si una estación
    falla. Con datos nuevos o históricos, fusiona por celda, ordena por
    estación/fecha/hora, escribe el esquema fijo y muestra conteos de nulos.

    Side Effects:
        Inicia y detiene Chromium, accede a internet, imprime estado y crea o
        sobrescribe :data:`OUTPUT_FILE`. ``csv.DictWriter`` usa el dialecto
        predeterminado de Python: cabecera, separador coma y codificación UTF-8
        indicada al abrir el archivo. Los errores de navegador o escritura se
        propagan después de ejecutar la limpieza aplicable.
    """
    print(
        f"{settings.SUCCESS} Scraper meteorológico Lima EMA — {args.inicio}→{args.fin}"
    )

    output_file = Path(args.salida)
    historical_paths = list(args.fusionar_desde)
    if args.fusionar_existente and output_file.exists():
        historical_paths.insert(0, output_file)
    historical_snapshots = _read_historical_csvs(historical_paths)

    all_rows: list[dict] = []
    browser = await zd.start()

    try:
        for nombre, meta in LIMA_EMA.items():
            rows = await scrape_station(
                browser, nombre, meta, args.inicio, args.fin
            )
            all_rows.extend(rows)
            print(f"{settings.SUCCESS} {nombre}: {len(rows)} filas")
    finally:
        await asyncio.sleep(1)
        await browser.stop()

    if not all_rows and output_file.exists():
        print(f"{settings.WARNING} Sin datos nuevos; se conserva el CSV existente.")
        return

    if not all_rows and not historical_snapshots:
        print(f"{settings.ERROR} Sin datos nuevos ni históricos. No se generó CSV.")
        return

    all_rows = merge_observations(all_rows, historical_snapshots)
    backup_path = backup_existing_csv(output_file)
    _write_csv(all_rows, output_file)

    print(f"\n{settings.SUCCESS} Guardado: {output_file.resolve()}")
    if backup_path is not None:
        print(f"{settings.SUCCESS} Respaldo: {backup_path.resolve()}")
    print(f"Total: {len(all_rows):,} filas | {len(LIMA_EMA)} estaciones")

    by_station: dict[str, list] = defaultdict(list)
    for r in all_rows:
        by_station[r["ESTACION"]].append(r)

    fechas = [r["FECHA"] for r in all_rows]
    print(f"Fechas: {min(fechas)} – {max(fechas)}")
    print()
    print(
        f"{'ESTACION':<30} {'FILAS':>7} {'TEMP_NULL':>10} {'HR_NULL':>8} "
        f"{'PP_NULL':>8} {'DIR_NULL':>9} {'VEL_NULL':>9}"
    )
    print("-" * 86)
    for name in sorted(by_station):
        rs = by_station[name]
        t_null = sum(1 for r in rs if r["TEMP"] is None)
        h_null = sum(1 for r in rs if r["HR"] is None)
        p_null = sum(1 for r in rs if r["PP"] is None)
        d_null = sum(1 for r in rs if r["DIR_VIENTO"] is None)
        v_null = sum(1 for r in rs if r["VEL_VIENTO"] is None)
        print(
            f"{name:<30} {len(rs):>7} {t_null:>10} {h_null:>8} "
            f"{p_null:>8} {d_null:>9} {v_null:>9}"
        )


def parse_yyyymm(value: str) -> int:
    """Valida un mes CLI con formato YYYYMM."""
    try:
        parsed = int(value)
        date(parsed // 100, parsed % 100, 1)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"Mes inválido: {value!r} (usa YYYYMM)")
    if len(value) != 6:
        raise argparse.ArgumentTypeError(f"Mes inválido: {value!r} (usa YYYYMM)")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Construye la interfaz de extracción y fusión."""
    parser = argparse.ArgumentParser(
        description="Descarga variables meteorológicas EMA de Lima."
    )
    parser.add_argument("--inicio", type=parse_yyyymm, default=START_YYYYMM)
    parser.add_argument("--fin", type=parse_yyyymm, default=END_YYYYMM)
    parser.add_argument("--salida", type=Path, default=Path(OUTPUT_FILE))
    parser.add_argument(
        "--fusionar-existente",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Usa el CSV de salida existente como respaldo (default: activado)",
    )
    parser.add_argument(
        "--fusionar-desde",
        action="append",
        default=[],
        type=Path,
        metavar="CSV",
        help="Snapshot bruto adicional usado como respaldo; se puede repetir",
    )
    return parser


def cli() -> None:
    """Ejecuta el punto de entrada asíncrono desde una consola síncrona."""
    parser = build_parser()
    args = parser.parse_args()
    if args.inicio > args.fin:
        parser.error("--inicio debe ser anterior o igual a --fin")
    try:
        asyncio.run(main(args))
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    cli()
