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


CAMPOS_NOTION = ("PALABRA", "DEFINICION", "IDIOMA", "LIBRO", "FECHA")
POR_DEFECTO = {"DEFINICION": "Definición"}


def _opcional(nombre: str) -> str | None:
    valor = os.getenv(nombre, "").strip()
    return valor or None


@dataclass
class BaseNotion:
    """Una base de datos de Notion y los nombres de sus columnas.

    prop_palabra = None → se usa la columna de título de la base de datos, sea cual sea su nombre.
    """

    database_id: str
    prop_definicion: str
    prop_palabra: str | None = None
    prop_idioma: str | None = None
    prop_libro: str | None = None
    prop_fecha: str | None = None


def _base_desde_entorno(database_id: str, idioma: str | None) -> BaseNotion:
    """Lee NOTION_PROP_<CAMPO>_<IDIOMA> y, si no existe, NOTION_PROP_<CAMPO>."""
    props = {}
    for campo in CAMPOS_NOTION:
        especifica = _opcional(f"NOTION_PROP_{campo}_{idioma.upper()}") if idioma else None
        valor = especifica or _opcional(f"NOTION_PROP_{campo}") or POR_DEFECTO.get(campo)
        props[campo] = None if valor == "-" else valor  # "-" = esta base no tiene esa columna
    return BaseNotion(
        database_id=database_id,
        prop_palabra=props["PALABRA"],
        prop_definicion=props["DEFINICION"],
        prop_idioma=props["IDIOMA"],
        prop_libro=props["LIBRO"],
        prop_fecha=props["FECHA"],
    )


def bases_notion_desde_entorno() -> dict[str, BaseNotion]:
    """{código de idioma: base}. La clave "*" es la base para el resto de idiomas.

    NOTION_DATABASE_ID_ES=...  → palabras en español
    NOTION_DATABASE_ID_EN=...  → palabras en inglés
    NOTION_DATABASE_ID=...     → cualquier otro idioma (o todos, si solo tienes una base)
    """
    bases: dict[str, BaseNotion] = {}
    prefijo = "NOTION_DATABASE_ID_"
    for nombre, valor in os.environ.items():
        if nombre.startswith(prefijo) and valor.strip():
            idioma = nombre[len(prefijo):].lower()
            bases[idioma] = _base_desde_entorno(valor.strip(), idioma)
    if general := _opcional("NOTION_DATABASE_ID"):
        bases["*"] = _base_desde_entorno(general, None)
    return bases


@dataclass
class Config:
    db_path: str | None
    carpeta_salida: Path
    notion_token: str | None
    notion_bases: dict[str, BaseNotion]

    @classmethod
    def desde_entorno(cls) -> "Config":
        return cls(
            db_path=_opcional("KOBO_DB_PATH") or detectar_kobo(),
            carpeta_salida=Path(os.getenv("OUTPUT_FOLDER", "salida")).expanduser(),
            notion_token=_opcional("NOTION_TOKEN"),
            notion_bases=bases_notion_desde_entorno(),
        )

    def base_para(self, idioma: str) -> BaseNotion | None:
        return self.notion_bases.get(idioma) or self.notion_bases.get("*")
