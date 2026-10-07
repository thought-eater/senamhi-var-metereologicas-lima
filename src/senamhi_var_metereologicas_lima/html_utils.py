"""Utilidades de análisis para controles ``select`` del HTML de SENAMHI.

El módulo usa BeautifulSoup con el parser estándar de Python. No ejecuta
JavaScript: recibe HTML ya obtenido por zendriver y devuelve atributos
normalizados para que el scraper elija los meses disponibles.
"""

from bs4 import BeautifulSoup

# Constante para el parser HTML
HTML_PARSER = "html.parser"


def extract_select_options(
    html_content: str,
    select_id: str | None = None,
    select_name: str | None = None,
) -> list[dict]:
    """Extrae atributos relevantes de las opciones de un ``select``.

    La búsqueda da prioridad a ``select_id`` cuando ambos criterios se
    proporcionan; si solo existe ``select_name`` se usa el atributo ``name`` y,
    sin criterios, se toma el primer ``select`` del fragmento. Esta dependencia
    de ids y nombres es sensible a cambios en el HTML del portal.

    Args:
        html_content: Documento o fragmento HTML que contiene el control.
        select_id: Id exacto del ``select`` buscado.
        select_name: Atributo ``name`` exacto, usado si no se proporciona id.

    Returns:
        Opciones en orden de documento. Cada registro contiene ``value``
        (cadena vacía si falta), texto sin espacios exteriores y los booleanos
        ``selected`` y ``disabled`` según la presencia de esos atributos.

    Raises:
        ValueError: Si ningún ``select`` satisface el criterio efectivo.
    """

    soup = BeautifulSoup(html_content, HTML_PARSER)

    # Buscar el select específico
    select_element = None

    if select_id:
        select_element = soup.find("select", id=select_id)
    elif select_name:
        select_element = soup.find("select", attrs={"name": select_name})
    else:
        # Si no se especifica ID ni name, tomar el primer select
        select_element = soup.find("select")

    if not select_element:
        if select_id:
            criteria = f"ID '{select_id}'"
        elif select_name:
            criteria = f"name '{select_name}'"
        else:
            criteria = "algún select"
        raise ValueError(f"No se encontró ningún select con {criteria}")

    # Extraer todas las opciones
    options = select_element.find_all("option")

    result = []

    for option in options:
        option_data = {
            "value": option.get("value", ""),
            "text": option.get_text(strip=True),
            "selected": option.has_attr("selected"),
            "disabled": option.has_attr("disabled"),
        }

        result.append(option_data)

    return result
