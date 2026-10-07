"""Jerarquía de errores de dominio del scraper de SENAMHI.

Separar estos fallos permite distinguir cambios o ausencias en la interfaz del
portal de errores genéricos de red, CDP, validación o escritura.
"""


class ScrapingError(Exception):
    """Clase base para fallos reconocibles del flujo de scraping.

    No agrega estado ni comportamiento a :class:`Exception`; sirve como punto
    único de captura para errores de dominio presentes o futuros.
    """



class SelectNotFoundError(ScrapingError):
    """Indica que falta un ``select`` u opción requeridos por el scraper.

    Normalmente señala que la página no terminó de cargar o que SENAMHI cambió
    ``select#CBOFiltro`` o sus opciones. El mensaje debe conservar el selector
    o valor problemático para facilitar el diagnóstico.
    """
