"""Carga, busca y convierte en URL la base local de estaciones SENAMHI.

La colección :data:`stations` se materializa al importar el módulo desde el
JSON indicado por :data:`settings.STATIONS_FILE`. Este diseño evita releer el
archivo por cada estación, pero implica que los cambios en el JSON solo se ven
en un proceso nuevo y que un archivo ausente o inválido impide la importación.
"""

import json
from importlib.resources.abc import Traversable
from urllib.parse import urlencode

from . import settings
from .models import Station


def load_stations(path: Traversable) -> list[Station]:
    """Lee y valida una colección JSON de estaciones.

    Args:
        path: Ruta a un JSON cuyo nivel superior debe ser una colección de
            objetos con los aliases SENAMHI aceptados por :class:`Station`.

    Returns:
        Modelos Pydantic validados, en el mismo orden del archivo.

    Raises:
        OSError: Si el archivo no puede abrirse.
        json.JSONDecodeError: Si el contenido no es JSON válido.
        pydantic.ValidationError: Si algún objeto incumple el modelo; no se
            devuelve una carga parcial.

    Side Effects:
        Lee el archivo usando :data:`settings.CSV_ENCODING`. Aunque el nombre
        de la constante menciona CSV, en este flujo configura la lectura JSON;
        la escritura del CSV especifica UTF-8 directamente en el scraper.
    """
    with path.open("r", encoding=settings.CSV_ENCODING) as file:
        data_json = json.load(file)
    return [Station(**item) for item in data_json]


# Caché de proceso: el recurso se resuelve dentro del paquete instalado.
stations = load_stations(settings.STATIONS_FILE)


def find_station_by_code(code: str) -> Station | None:
    """Busca por el código interno que el JSON denomina ``cod``.

    Args:
        code: Código a normalizar mediante espacios, mayúsculas y minúsculas.

    Returns:
        La primera estación cuyo ``Station.code`` coincide, o ``None``. Una
        cadena vacía simplemente no encuentra coincidencias.
    """
    code = code.strip().upper()
    for est in stations:
        if est.code == code:
            return est
    return None


def create_station_url(station: Station) -> str:
    """Construye la URL de la ficha usando los nombres esperados por SENAMHI.

    Args:
        station: Modelo validado. Sus atributos Python se traducen a los
            parámetros ``cod``, ``estado``, ``tipo_esta``, ``cate`` y
            ``cod_old`` del portal.

    Returns:
        URL con query string escapado por :func:`urllib.parse.urlencode`.
        Debido a ``use_enum_values`` en :class:`Station`, categoría, tipo y
        estado ya son cadenas aptas para serialización.
    """
    url_base = settings.BASE_URL
    params = {
        "cod": station.code,
        "estado": station.status,
        "tipo_esta": station.station_type,
        "cate": station.category,
        "cod_old": station.legacy_code,
    }
    return f"{url_base}?{urlencode(params)}"
