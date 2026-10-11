"""Lectura (y borrado opcional) de las palabras guardadas en la base de datos del Kobo."""

import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PUNTUACION = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


@dataclass
class PalabraKobo:
    texto_original: str  # tal cual está en la tabla WordList (se usa para borrar)
    palabra: str  # limpia, en minúsculas
    idioma: str  # código ISO: "en", "es", ...
    libro: str | None
    fecha: str | None


def limpiar_palabra(texto: str) -> str:
    """Quita signos de puntuación al principio y al final (comillas, puntos, guiones...)."""
    return PUNTUACION.sub("", texto.strip()).lower()


def idioma_desde_sufijo(sufijo: str | None) -> str | None:
    """El Kobo guarda en DictSuffix el diccionario usado: '-es', '-en', '-de'... ('' = inglés)."""
    if sufijo is None:
        return None
    sufijo = sufijo.strip().lstrip("-").lower()
    if not sufijo:
        return "en"
    return sufijo.split("-")[0][:2] or None


def adivinar_idioma(palabra: str) -> str:
    """Último recurso si el Kobo no indica el diccionario."""
    if re.search(r"[ñáéíóúü¿¡]", palabra):
        return "es"
    return "en"


def _columnas(cur: sqlite3.Cursor, tabla: str) -> set[str]:
    return {fila[1] for fila in cur.execute(f"PRAGMA table_info({tabla})")}


def leer_palabras(db_path: str) -> list[PalabraKobo]:
    """Lee WordList trabajando sobre una COPIA de la base de datos.

    Así nunca bloqueamos ni corrompemos la base de datos del lector.
    """
    if not Path(db_path).is_file():
        raise FileNotFoundError(f"No se encuentra la base de datos del Kobo: {db_path}")

    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / "KoboReader.sqlite"
        shutil.copy2(db_path, copia)
        con = sqlite3.connect(f"file:{copia}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            cols = _columnas(cur, "WordList")
            if "Text" not in cols:
                raise RuntimeError("La tabla WordList no tiene la columna 'Text'.")

            sel_sufijo = "w.DictSuffix" if "DictSuffix" in cols else "NULL"
            sel_fecha = "w.DateCreated" if "DateCreated" in cols else "NULL"
            if "VolumeId" in cols:
                sel_libro = "c.Title"
                join = "LEFT JOIN content c ON c.ContentID = w.VolumeId AND c.ContentType = 6"
            else:
                sel_libro, join = "NULL", ""

            cur.execute(
                f"""SELECT w.Text, {sel_sufijo}, {sel_libro}, {sel_fecha}
                    FROM WordList w {join}
                    WHERE w.Text IS NOT NULL AND LENGTH(TRIM(w.Text)) > 0
                    ORDER BY {sel_fecha}"""
            )
            filas = cur.fetchall()
        finally:
            con.close()

    resultado: list[PalabraKobo] = []
    vistas: set[tuple[str, str]] = set()
    for texto, sufijo, libro, fecha in filas:
        palabra = limpiar_palabra(texto)
        if len(palabra) < 2:
            continue
        idioma = idioma_desde_sufijo(sufijo) or adivinar_idioma(palabra)
        clave = (idioma, palabra)
        if clave in vistas:
            continue
        vistas.add(clave)
        resultado.append(PalabraKobo(texto, palabra, idioma, libro, _normalizar_fecha(fecha)))
    return resultado


def _normalizar_fecha(valor: str | None) -> str | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return valor[:10]


def borrar_palabras(db_path: str, textos: list[str], carpeta_backup: Path) -> tuple[int, Path]:
    """Borra de WordList solo las palabras indicadas.

    Antes guarda una copia de seguridad de la base de datos en tu ordenador.
    Devuelve (filas borradas, ruta de la copia).
    """
    carpeta_backup.mkdir(parents=True, exist_ok=True)
    backup = carpeta_backup / f"KoboReader.backup-{datetime.now():%Y%m%d-%H%M%S}.sqlite"
    shutil.copy2(db_path, backup)
    if not textos:
        return 0, backup
    con = sqlite3.connect(db_path)
    try:
        con.executemany("DELETE FROM WordList WHERE Text = ?", [(t,) for t in textos])
        con.commit()
        return con.total_changes, backup
    finally:
        con.close()
