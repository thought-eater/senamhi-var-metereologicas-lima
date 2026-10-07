# Pruebas de software

Desde la raíz del repositorio, con las dependencias instaladas:

```bash
uv run --frozen python -m unittest discover -s tests/software -v
```

`software/test_adquisicion.py` comprueba encabezados y fechas, variables ausentes,
fusión de capturas y respaldos temporales. Incluye pruebas unitarias y de
integración con archivos. Usa HTML sintético, no inicia Chromium ni consulta
SENAMHI y no modifica el CSV publicado.

La evidencia sobre los datasets reales se encuentra en la
[validación de R1.1](https://github.com/thought-eater/senamhi-pre-procesamiento/tree/HEAD/validacion/r1_1).
