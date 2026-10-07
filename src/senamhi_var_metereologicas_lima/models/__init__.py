"""Interfaz pública de los modelos de estaciones SENAMHI.

Reexporta el modelo Pydantic y sus enums para que consumidores como
``station_service`` importen desde ``models`` sin depender de la ubicación
interna de ``station.py``. :data:`__all__` limita esa API pública explícita.
"""

from .station import Station, StationCategory, StationStatus, StationType

__all__ = [
    # Modelo y vocabularios validados que constituyen la API del paquete.
    "Station",
    "StationCategory",
    "StationStatus",
    "StationType",
]
