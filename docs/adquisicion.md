# Adquisición meteorológica

## Fuente y estaciones

El extractor consulta las tablas mensuales del
[mapa de estaciones de SENAMHI](https://www.senamhi.gob.pe/mapas/mapa-estaciones-2/map_red_graf.php).
El periodo predeterminado comprende enero de 2025 a junio de 2026, inclusive.
Se configuran siete estaciones EMA: Campo de Marte, Carabayllo, Ceres, Santa
Anita, San Borja, San Juan de Lurigancho y San Martín de Porres.

Los códigos y metadatos geográficos utilizados están en `LIMA_EMA`, dentro del
[extractor](../src/senamhi_var_metereologicas_lima/scraper.py). El recurso
[`estaciones.json`](../src/senamhi_var_metereologicas_lima/data/estaciones.json)
permite resolver sus fichas en el portal.

## Diccionario del CSV

Separador coma, UTF-8 y campos vacíos para ausencias. La clave es
`(ESTACION, FECHA, HORA)`.

| Campo | Tipo / unidad | Significado |
|---|---|---|
| `ESTACION` | Texto | Nombre normalizado de estación |
| `FECHA` | Entero `YYYYMMDD` | Fecha reportada |
| `HORA` | Entero `HH*10000` | Hora; `230000` representa 23:00 |
| `LONGITUD`, `LATITUD` | Grados decimales | Coordenadas configuradas |
| `ALTITUD` | Metros | Altitud configurada |
| `TEMP` | °C | Temperatura del aire |
| `HR` | % | Humedad relativa |
| `PP` | mm | Precipitación asociada a la hora |
| `DIR_VIENTO` | Grados | Dirección meteorológica de procedencia |
| `VEL_VIENTO` | m/s | Velocidad del viento |
| `RED` | Texto | Red EMA |
| `DISTRITO` | Texto | Distrito configurado |

Las mediciones pueden estar vacías. `S/D` no se convierte en cero. El CSV no
almacena zona horaria; el preprocesamiento asume hora local de Lima. Las unidades
se interpretan según la fuente; el intervalo institucional de acumulación de
`PP` y los metadatos completos de instrumentos no están documentados en la
captura. Tampoco se registra la vigencia de las coordenadas.

## Reproducción y opciones

La instalación y el ejemplo básico están en el [README](../README.md).
El navegador debe poder iniciarse y establecer una conexión CDP; la instalación
de las dependencias Python no garantiza la disponibilidad de Chromium.

| Opción | Valor predeterminado / función |
|---|---|
| `--inicio`, `--fin` | `202501`, `202606`; formato `YYYYMM` |
| `--salida` | `var_meteorologicas_lima_2025_2026.csv` |
| `--no-fusionar-existente` | Desactiva el respaldo desde el CSV de salida |
| `--fusionar-desde CSV` | Añade una captura bruta de respaldo; repetible |

zendriver inicia el navegador y captura mediante CDP la respuesta de cada tabla
mensual. BeautifulSoup resuelve variables por encabezado; para respuestas
antiguas no reconocidas usa el orden posicional previsto por el parser.
Estaciones y meses se recorren secuencialmente, con pausas y reintentos.

La fusión se realiza por estación y hora, para cada variable: un valor nuevo no
nulo prevalece y el histórico completa ausencias. También se conservan filas
históricas fuera del intervalo solicitado. Solo se fusionan capturas brutas.
Antes del reemplazo se crea automáticamente un respaldo en
`history/<fecha_hora>/`; si falla el respaldo se conserva el CSV anterior.

## Alcance

La disponibilidad depende de la estación y la variable. En la captura utilizada,
`PP` carece de observaciones en Carabayllo, Ceres y Santa Anita, y `HR` en Ceres.
Una respuesta vacía puede deberse a fallos del portal; no prueba por sí sola
ausencia de medición. No se archivan todas las respuestas HTML originales.

La precipitación externa `PP_IFS` se incorpora posteriormente en el
[preprocesamiento](https://github.com/thought-eater/senamhi-pre-procesamiento)
y no pertenece a este CSV de adquisición.
