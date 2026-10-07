"""Modelo Pydantic de las estaciones almacenadas en ``data/estaciones.json``.

Los nombres públicos en Python son descriptivos, mientras :class:`Field` usa
aliases breves (``nom``, ``cate``, ``lat``, etc.) para aceptar directamente el
esquema del JSON y los parámetros conceptuales del portal. Pydantic valida
coordenadas, enums y textos al cargar la base de estaciones.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class StationCategory(str, Enum):
    """Códigos de categoría aceptados por la base local y el portal."""

    EAA = "EAA"  # Estación Automática Agrícola
    PE = "PE"  # Pluviométrica Especial
    CP = "CP"  # Climatológica Principal
    HLM = "HLM"  # Hidrológica con Limnígrafo
    MAP = "MAP"  # Meteorológica Aeroportuaria
    EHA = "EHA"  # Estación Hidrológica Automática
    EHMA = "EHMA"  # Estación Hidrometeorológica Automática
    CO = "CO"  # Climatológica Ordinaria
    EMA = "EMA"  # Estación Meteorológica Automática
    PLU = "PLU"  # Pluviométrica
    EAMA = "EAMA"  # Estación Agrometeorológica Automática
    HLG = "HLG"  # Hidrológica con Limniógrafo


class StationType(str, Enum):
    """Código general meteorológico o hidrológico de una estación."""

    METEOROLOGICAL = "M"  # Meteorológica
    HYDROLOGICAL = "H"  # Hidrológica


class StationStatus(str, Enum):
    """Estados de publicación aceptados por el portal de estaciones."""

    REAL_TIME = "REAL"  # Tiempo real
    DEFERRED = "DIFERIDO"  # Diferido
    AUTOMATIC = "AUTOMATICA"  # Automática


class Station(BaseModel):
    """Representa y valida una estación meteorológica o hidrológica.

    Los aliases de :class:`pydantic.Field` enlazan el JSON externo con nombres
    Python: ``nom`` a ``name``, ``cate`` a ``category``, ``lat`` a
    ``latitude``, ``lon`` a ``longitude``, ``ico`` a ``station_type``, ``cod``
    a ``code``, ``cod_old`` a ``legacy_code`` y ``estado`` a ``status``.
    ``validate_by_name=True`` permite además construir el modelo con los
    nombres Python, no solo con aliases.

    ``use_enum_values=True`` hace que Pydantic almacene los valores de los enums
    como cadenas (por ejemplo, ``"EMA"``) después de validar. Esto simplifica
    ``urlencode`` y serialización, pero significa que el acceso en tiempo de
    ejecución no debe asumir atributos como ``.value``.

    Attributes:
        name: Nombre de la estación
        category: Categoría de la estación (EMA, CO, etc.)
        latitude: Latitud en grados decimales
        longitude: Longitud en grados decimales
        station_type: Tipo M (Meteorológica) o H (Hidrológica)
        code: Código único de la estación
        legacy_code: Código anterior (opcional)
        status: Estado operativo de la estación
    """

    name: str = Field(..., alias="nom", description="Nombre de la estación")
    category: StationCategory = Field(
        ..., alias="cate", description="Categoría de la estación"
    )
    latitude: float = Field(
        ..., alias="lat", ge=-90, le=90, description="Latitud en grados decimales"
    )
    longitude: float = Field(
        ..., alias="lon", ge=-180, le=180, description="Longitud en grados decimales"
    )
    station_type: StationType = Field(..., alias="ico", description="Tipo de estación")
    code: str = Field(
        ..., alias="cod", min_length=1, description="Código único de la estación"
    )
    legacy_code: str | None = Field(
        "", alias="cod_old", description="Código anterior de la estación"
    )
    status: StationStatus = Field(..., alias="estado", description="Estado operativo")

    class Config:
        validate_by_name = True
        use_enum_values = True

    @field_validator("code")
    def validate_code(cls, v):
        """Normaliza el código y rechaza valores vacíos.

        Returns:
            Código sin espacios exteriores y en mayúsculas.

        Raises:
            ValueError: Si el valor está vacío o solo contiene espacios.
        """
        if not v or not v.strip():
            raise ValueError("El código de estación no puede estar vacío")
        return v.strip().upper()

    @field_validator("name")
    def validate_name(cls, v):
        """Normaliza el nombre y rechaza valores vacíos.

        Returns:
            Nombre sin espacios exteriores y convertido con ``str.title``.

        Raises:
            ValueError: Si el valor está vacío o solo contiene espacios.
        """
        if not v or not v.strip():
            raise ValueError("El nombre de la estación no puede estar vacío")
        return v.strip().title()

    def __str__(self) -> str:
        """Devuelve una etiqueta legible sin asumir una instancia de Enum.

        ``category`` es una cadena en modelos validados debido a
        ``use_enum_values=True``; usar directamente su valor evita el
        ``AttributeError`` que produciría acceder a ``category.value``.
        """
        return f"{self.name} ({self.code}) - {self.category}"
