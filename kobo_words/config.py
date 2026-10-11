"""Configuración: se lee de variables de entorno o de un fichero .env."""

import glob
import os
import platform
import string
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv es opcional
    pass

RUTA_RELATIVA_DB = os.path.join(".kobo", "KoboReader.sqlite")


def detectar_kobo() -> str | None:
    """Busca el Kobo conectado por USB y devuelve la ruta a KoboReader.sqlite."""
    candidatos: list[str] = []
    sistema = platform.system()
    if sistema == "Windows":
        candidatos = [f"{letra}:\\{RUTA_RELATIVA_DB}" for letra in string.ascii_uppercase]
    elif sistema == "Darwin":
        candidatos = glob.glob(f"/Volumes/*/{RUTA_RELATIVA_DB}")
    else:
        candidatos = glob.glob(f"/media/*/*/{RUTA_RELATIVA_DB}") + glob.glob(
            f"/run/media/*/*/{RUTA_RELATIVA_DB}"
        )
    for ruta in candidatos:
        if os.path.isfile(ruta):
            return ruta
    return None


@dataclass
class Config:
    db_path: str | None
    carpeta_salida: Path
    notion_token: str | None
    notion_database_id: str | None
    prop_palabra: str
    prop_definicion: str
    prop_idioma: str | None
    prop_libro: str | None
    prop_fecha: str | None

    @classmethod
    def desde_entorno(cls) -> "Config":
        def opcional(nombre: str) -> str | None:
            valor = os.getenv(nombre, "").strip()
            return valor or None

        return cls(
            db_path=opcional("KOBO_DB_PATH") or detectar_kobo(),
            carpeta_salida=Path(os.getenv("OUTPUT_FOLDER", "salida")).expanduser(),
            notion_token=opcional("NOTION_TOKEN"),
            notion_database_id=opcional("NOTION_DATABASE_ID"),
            prop_palabra=os.getenv("NOTION_PROP_PALABRA", "Palabra"),
            prop_definicion=os.getenv("NOTION_PROP_DEFINICION", "Definición"),
            prop_idioma=opcional("NOTION_PROP_IDIOMA"),
            prop_libro=opcional("NOTION_PROP_LIBRO"),
            prop_fecha=opcional("NOTION_PROP_FECHA"),
        )
