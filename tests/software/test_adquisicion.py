"""Pruebas de software de la adquisición: parser, fusión y respaldos offline."""

from __future__ import annotations

import argparse
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from senamhi_var_metereologicas_lima import scraper
from senamhi_var_metereologicas_lima.scraper import (
    CSV_COLUMNS,
    _response_error,
    parse_ema_table,
)

META = {"lon": -77.0, "lat": -12.0, "alt": 100.0, "dist": "LIMA"}


class ParseEmaTableTests(unittest.TestCase):
    def test_resolves_variables_by_header_when_columns_are_reordered(self) -> None:
        html = """
        <table id="dataTable">
          <tr>
            <th>Fecha</th><th>Hora</th><th>Humedad relativa (%)</th>
            <th>Vel. Viento (m/s)</th><th>Temperatura (°C)</th>
            <th>Precipitación (mm)</th><th>Dir. Viento (°)</th>
          </tr>
          <tr>
            <td>2025-01-02</td><td>03:00</td><td>81</td>
            <td>1.8</td><td>19.5</td><td>0.2</td><td>270</td>
          </tr>
        </table>
        """

        rows = parse_ema_table(html, "PRUEBA", META)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["FECHA"], 20250102)
        self.assertEqual(rows[0]["HORA"], 30000)
        self.assertEqual(rows[0]["TEMP"], 19.5)
        self.assertEqual(rows[0]["HR"], 81.0)
        self.assertEqual(rows[0]["PP"], 0.2)
        self.assertEqual(rows[0]["DIR_VIENTO"], 270.0)
        self.assertEqual(rows[0]["VEL_VIENTO"], 1.8)
        self.assertEqual(list(rows[0]), CSV_COLUMNS)

    def test_uses_documented_positional_fallback_for_legacy_header(self) -> None:
        html = """
        <table id="dataTable">
          <tr><th>A</th><th>B</th><th>C</th><th>D</th><th>E</th></tr>
          <tr><td>2025/01/02</td><td>04:00</td><td>20</td><td>S/D</td><td>75</td></tr>
        </table>
        """

        row = parse_ema_table(html, "PRUEBA", META)[0]

        self.assertEqual(row["TEMP"], 20.0)
        self.assertEqual(row["HR"], 75.0)
        self.assertIsNone(row["PP"])
        self.assertIsNone(row["DIR_VIENTO"])
        self.assertIsNone(row["VEL_VIENTO"])

    def test_uses_full_ema_positional_fallback_for_wind(self) -> None:
        html = """
        <table id="dataTable">
          <tr>
            <th>A</th><th>B</th><th>C</th><th>D</th><th>E</th><th>F</th><th>G</th>
          </tr>
          <tr>
            <td>2025/01/02</td><td>04:00</td><td>20</td><td>0</td>
            <td>75</td><td>245</td><td>2.3</td>
          </tr>
        </table>
        """

        row = parse_ema_table(html, "PRUEBA", META)[0]

        self.assertEqual(row["DIR_VIENTO"], 245.0)
        self.assertEqual(row["VEL_VIENTO"], 2.3)

    def test_skips_invalid_calendar_date(self) -> None:
        html = """
        <table id="dataTable">
          <tr><th>Fecha</th><th>Hora</th><th>Temperatura</th><th>PP</th><th>HR</th></tr>
          <tr><td>2025-02-31</td><td>01:00</td><td>20</td><td>0</td><td>80</td></tr>
        </table>
        """

        with self.assertRaisesRegex(scraper.ScrapingError, "filas horarias válidas"):
            parse_ema_table(html, "PRUEBA", META)

    def test_rejects_non_hourly_time(self) -> None:
        html = """
        <table id="dataTable">
          <tr><th>Fecha</th><th>Hora</th><th>Temperatura</th></tr>
          <tr><td>2025-01-01</td><td>01:30</td><td>20</td></tr>
        </table>
        """

        with self.assertRaisesRegex(scraper.ScrapingError, "filas horarias válidas"):
            parse_ema_table(html, "PRUEBA", META)

    def test_normalizes_nonfinite_and_numeric_sentinels(self) -> None:
        for value in ["NaN", "inf", "-inf", "-999", "9999", "S/D", "N/D"]:
            with self.subTest(value=value):
                self.assertIsNone(scraper._safe_float(value))

    def test_preserves_available_variable_when_precipitation_header_is_absent(
        self,
    ) -> None:
        html = """
        <table id="dataTable">
          <tr>
            <th>Fecha</th><th>Hora</th><th>Temperatura</th>
            <th>Humedad relativa</th><th>Dirección del viento</th>
            <th>Velocidad del viento</th>
          </tr>
          <tr>
            <td>2025-01-02</td><td>01:00</td><td>20</td><td>82</td><td>230</td><td>1.4</td>
          </tr>
        </table>
        """

        row = parse_ema_table(html, "PRUEBA", META)[0]

        self.assertEqual(row["TEMP"], 20.0)
        self.assertEqual(row["HR"], 82.0)
        self.assertIsNone(row["PP"])
        self.assertEqual(row["DIR_VIENTO"], 230.0)
        self.assertEqual(row["VEL_VIENTO"], 1.4)

    def test_recognizes_senamhi_year_month_day_header(self) -> None:
        html = """
        <table id="dataTable">
          <tr>
            <td>AÑO / MES / DÍA</td><td>HORA</td><td>TEMPERATURA (°C)</td>
            <td>HUMEDAD (%)</td><td>DIRECCION DEL VIENTO (°)</td>
            <td>VELOCIDAD DEL VIENTO (m/s)</td>
          </tr>
          <tr>
            <td>2025/01/01</td><td>00:00</td><td>21.7</td>
            <td>79.47</td><td>227.8</td><td>1.2</td>
          </tr>
        </table>
        """

        row = parse_ema_table(html, "CARABAYLLO", META)[0]

        self.assertEqual(row["TEMP"], 21.7)
        self.assertEqual(row["HR"], 79.47)
        self.assertIsNone(row["PP"])
        self.assertEqual(row["DIR_VIENTO"], 227.8)
        self.assertEqual(row["VEL_VIENTO"], 1.2)

    def test_does_not_assign_ambiguous_wind_header(self) -> None:
        html = """
        <table id="dataTable">
          <tr>
            <th>Fecha</th><th>Hora</th><th>Temperatura</th><th>Viento</th>
          </tr>
          <tr><td>2025-01-02</td><td>01:00</td><td>20</td><td>230</td></tr>
        </table>
        """

        row = parse_ema_table(html, "PRUEBA", META)[0]

        self.assertIsNone(row["DIR_VIENTO"])
        self.assertIsNone(row["VEL_VIENTO"])

    def test_captcha_response_is_not_treated_as_empty_month(self) -> None:
        html = '<div class="alert alert-danger">El CAPTCHA es inválido.</div>'

        self.assertEqual(_response_error(html), "SENAMHI rechazó el CAPTCHA")


class MergeObservationsTests(unittest.TestCase):
    @staticmethod
    def _row(hour: int, **values: float | None) -> dict:
        row = {
            "ESTACION": "CAMPO_DE_MARTE",
            "FECHA": 20250101,
            "HORA": hour,
            "LONGITUD": 0.0,
            "LATITUD": 0.0,
            "ALTITUD": 0.0,
            "TEMP": None,
            "HR": None,
            "PP": None,
            "DIR_VIENTO": None,
            "VEL_VIENTO": None,
            "RED": "EMA",
            "DISTRITO": "PRUEBA",
        }
        row.update(values)
        return row

    def test_merges_each_variable_without_replacing_new_values(self) -> None:
        fresh = [self._row(0, TEMP=20.0, HR=None, PP=0.0)]
        historical = [self._row(0, TEMP=19.0, HR=80.0, PP=1.0)]

        rows = scraper.merge_observations(fresh, [historical])

        self.assertEqual(rows[0]["TEMP"], 20.0)
        self.assertEqual(rows[0]["HR"], 80.0)
        self.assertEqual(rows[0]["PP"], 0.0)
        self.assertEqual(rows[0]["LONGITUD"], -77.04314)

    def test_preserves_old_key_missing_from_new_capture(self) -> None:
        historical = [self._row(10000, TEMP=18.0)]

        rows = scraper.merge_observations([], [historical])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["TEMP"], 18.0)

    def test_collapses_fresh_duplicates_per_variable(self) -> None:
        fresh = [
            self._row(0, TEMP=None, HR=80.0),
            self._row(0, TEMP=20.0, HR=81.0),
        ]

        rows = scraper.merge_observations(fresh, [])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["TEMP"], 20.0)
        self.assertEqual(rows[0]["HR"], 80.0)

    def test_invalid_fresh_value_does_not_displace_history(self) -> None:
        fresh = [self._row(0, TEMP=float("nan"))]
        historical = [self._row(0, TEMP=20.0)]

        rows = scraper.merge_observations(fresh, [historical])

        self.assertEqual(rows[0]["TEMP"], 20.0)

    def test_validates_yyyymm(self) -> None:
        self.assertEqual(scraper.parse_yyyymm("202606"), 202606)
        with self.assertRaises(argparse.ArgumentTypeError):
            scraper.parse_yyyymm("202613")

    def test_historical_loader_preserves_rows_outside_requested_period(self) -> None:
        rows = [
            {**self._row(0, TEMP=20.0), "FECHA": value}
            for value in [20241231, 20250101, 20260701]
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "historical.csv"
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=scraper.CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            loaded = scraper._read_historical_csvs([path])

        self.assertEqual(
            [row["FECHA"] for row in loaded[0]],
            [20241231, 20250101, 20260701],
        )

    def test_merge_existing_flag_is_enabled_by_default_and_can_be_disabled(self) -> None:
        parser = scraper.build_parser()

        self.assertTrue(parser.parse_args([]).fusionar_existente)
        self.assertFalse(parser.parse_args(["--no-fusionar-existente"]).fusionar_existente)

    def test_ceres_ema_uses_current_station_code(self) -> None:
        self.assertEqual(scraper.LIMA_EMA["CERES"]["codigo"], "112278")

    def test_backs_up_existing_csv_inside_timestamped_history(self) -> None:
        expected_history = Path(scraper.__file__).resolve().parents[2] / "history"
        self.assertEqual(scraper.HISTORY_DIR, expected_history)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "meteo.csv"
            output.write_text("contenido anterior", encoding="utf-8")

            history = root / "history"
            with patch.object(scraper, "HISTORY_DIR", history):
                backup = scraper.backup_existing_csv(output)

            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_text(encoding="utf-8"), "contenido anterior")
            self.assertEqual(backup.name, "meteo.csv")
            self.assertEqual(backup.parent.parent, history)
            self.assertRegex(backup.parent.name, r"^\d{8}_\d{6}$")


if __name__ == "__main__":
    unittest.main()
