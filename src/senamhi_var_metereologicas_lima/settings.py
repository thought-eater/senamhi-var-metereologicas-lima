"""Configuración operativa del scraper meteorológico de SENAMHI.

Las constantes controlan el endpoint observado, la espera de respuestas CDP,
la lectura de la base local, los mensajes de consola y las pausas entre meses.
La base de estaciones se resuelve como recurso del paquete. Este módulo no lee
variables de entorno ni abre archivos por sí mismo.
"""

from importlib.resources import files

# URL de ficha de estación y fragmento identificador del endpoint mensual.
BASE_URL = "https://www.senamhi.gob.pe/mapas/mapa-estaciones-2/map_red_graf.php"
DATA_ENDPOINT = "__dt_est_tp_0s3n"

# Límite para que _capture reciba por CDP una respuesta mensual terminada.
TIMEOUT_SECONDS = 30

# Codificación de lectura del JSON; el CSV principal abre UTF-8 literalmente.
CSV_ENCODING = "utf-8"

# Recurso que station_service carga durante su importación.
STATIONS_FILE = files("senamhi_var_metereologicas_lima").joinpath(
    "data", "estaciones.json"
)

# Mensajes de estado
SUCCESS = "✅"
ERROR = "❌"
PROCESSING = "🔄"
WARNING = "⚠️"

# Pausas de cortesía para moderar consultas consecutivas al portal.
JITTER_MIN = 0.3  # Mínimo de la pausa aleatoria entre meses, en segundos.
JITTER_MAX = 0.9  # Máximo de la pausa aleatoria entre meses, en segundos.
YEAR_BOUNDARY_SLEEP = 1.5  # Pausa adicional al cambiar de año, en segundos.

# Recuperación de fallos mensuales transitorios, incluidos timeouts de red.
MAX_RETRIES = 2  # Reintentos posteriores al intento inicial.
RETRY_SLEEP = 5.0  # Pausa fija entre intentos, en segundos.
