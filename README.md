# Datos meteorológicos horarios — SENAMHI Lima

Datos de adquisición y extractor de temperatura, humedad relativa, precipitación
y viento para siete estaciones automáticas de Lima Metropolitana, enero de
2025–junio de 2026. Aportan la entrada meteorológica al **resultado R1.1 de la
tesis: dos datasets curados y georreferenciados de PM2.5 y meteorología**.

## Examinar los datos

- [CSV de adquisición](var_meteorologicas_lima_2025_2026.csv).
- [Fuente, estaciones, diccionario y procedimiento](docs/adquisicion.md).
- [Datos curados y verificación de R1.1](https://github.com/thought-eater/senamhi-pre-procesamiento).
- [Extractor de PM2.5 complementario](https://github.com/thought-eater/scraper-pm2.5-lima).

El archivo contiene los valores obtenidos del portal, sin imputaciones. Las
variables disponibles dependen de cada estación: un campo vacío no significa
precipitación cero ni ausencia física del fenómeno.

## Reproducir la adquisición

Requiere Python ≥ 3.14, [uv](https://docs.astral.sh/uv/), internet y un navegador
Chrome/Chromium que zendriver pueda iniciar mediante CDP. Desde la raíz:

```bash
uv sync --frozen
uv run --frozen senamhi-var-metereologicas-lima \
  --salida capturas/meteorologia.csv \
  --fusionar-desde var_meteorologicas_lima_2025_2026.csv
```

Se genera una nueva captura consolidada conservando el CSV publicado. Una nueva
consulta al portal puede diferir de la captura utilizada en la tesis.

## Pruebas de software

```bash
uv run --frozen python -m unittest discover -s tests/software -v
```

Las [pruebas offline](tests/README.md) usan HTML sintético y archivos temporales;
no inician el navegador. La verificación de R1.1 se encuentra en el repositorio
de preprocesamiento y utiliza los datasets reales.

## Créditos y licencia

Adaptación de [senamhi-scraper](https://github.com/danyneyra/senamhi-scraper), de
Dany Daniel Neyra. Se conservan su atribución y la [licencia MIT](LICENSE).
