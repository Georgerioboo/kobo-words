"""Pruebas sin red ni Kobo real: se crea una base de datos falsa con la misma estructura."""

import sqlite3
from pathlib import Path

from kobo_words import diccionario
from kobo_words.exportar import Entrada, Vocabulario, escribir_txt
from kobo_words.kobo import borrar_palabras, idioma_desde_sufijo, leer_palabras, limpiar_palabra


def crear_kobo_falso(ruta: Path) -> None:
    con = sqlite3.connect(ruta)
    con.executescript("""
        CREATE TABLE WordList (Text TEXT PRIMARY KEY, VolumeId TEXT, DictSuffix TEXT, DateCreated TEXT);
        CREATE TABLE content (ContentID TEXT, ContentType INTEGER, Title TEXT);
        INSERT INTO content VALUES ('libro1', 6, 'Dune'), ('libro2', 6, 'Niebla');
        INSERT INTO WordList VALUES
            ('Ubiquitous,', 'libro1', '', '2026-10-01T20:00:00Z'),
            ('“ubiquitous”', 'libro1', '', '2026-10-02T20:00:00Z'),
            ('desasosiego.', 'libro2', '-es', '2026-10-03T20:00:00Z'),
            ('a', 'libro1', '', '2026-10-04T20:00:00Z');
    """)
    con.commit()
    con.close()


def test_limpieza_e_idioma():
    assert limpiar_palabra(" “Hello!” ") == "hello"
    assert idioma_desde_sufijo("") == "en"
    assert idioma_desde_sufijo("-es") == "es"
    assert idioma_desde_sufijo(None) is None


def test_leer_y_borrar(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    crear_kobo_falso(db)
    palabras = leer_palabras(str(db))
    assert [(p.palabra, p.idioma, p.libro) for p in palabras] == [
        ("ubiquitous", "en", "Dune"),
        ("desasosiego", "es", "Niebla"),
    ]
    borradas, backup = borrar_palabras(str(db), ["desasosiego."], tmp_path / "bk")
    assert borradas == 1 and backup.exists()
    assert len(leer_palabras(str(db))) == 1


def test_wikitexto():
    texto = "[[edificio|Edificio]] [[destinado]] a {{l|es|x}}''vivienda''<ref>x</ref>."
    assert diccionario._limpiar_wikitexto(texto) == "Edificio destinado a vivienda."


def test_vocabulario_y_txt(tmp_path):
    v = Vocabulario(tmp_path / "palabras.json")
    assert v.añadir(Entrada("ubiquitous", "en", "Found everywhere.", libro="Dune"))
    assert v.añadir(Entrada("desasosiego", "es"))
    assert not v.añadir(Entrada("desasosiego", "es", "Falta de sosiego."))  # completa la previa
    v.guardar()
    v2 = Vocabulario(tmp_path / "palabras.json")
    assert v2.entradas["es:desasosiego"].definicion == "Falta de sosiego."
    nombres = {p.name for p in escribir_txt(v2, tmp_path)}
    assert nombres == {"palabras_ingles_definiciones.txt", "palabras_espanol_definiciones.txt"}


class RespuestaFalsa:
    def __init__(self, datos, status=200):
        self.datos, self.status_code = datos, status

    def json(self):
        return self.datos


class SesionFalsa:
    def __init__(self, datos):
        self.datos = datos

    def get(self, *a, **k):
        return RespuestaFalsa(self.datos)


def test_wiktionary_es():
    wikitexto = """== {{lengua|es}} ==
==== {{sustantivo femenino|es}} ====
;1 {{csem|construcción}}: [[edificio|Edificio]] [[destinado]] a [[vivienda]].
;2: [[familia|Familia]].
== {{lengua|pt}} ==
;1: Casa en portugués.
"""
    s = SesionFalsa({"parse": {"wikitext": wikitexto}})
    d = diccionario.wiktionary_es(s, "casa")
    assert d.texto == "1. Edificio destinado a vivienda. | 2. Familia."


def test_free_dictionary():
    s = SesionFalsa([{"meanings": [
        {"partOfSpeech": "adjective", "definitions": [{"definition": "Found everywhere."}]}]}])
    assert diccionario.free_dictionary(s, "ubiquitous").texto == "(adjective) Found everywhere."


class ClienteNotionFalso:
    """Simula dos bases: la inglesa con columnas en inglés, la española en español."""

    ESQUEMAS = {
        "ds_en": {"Word": "title", "Definition": "rich_text", "Book": "rich_text"},
        "ds_es": {"Palabra": "title", "Definición": "rich_text", "Libro": "select",
                  "Fecha": "date"},
    }

    def __init__(self):
        self.creadas: list[tuple[str, dict]] = []

    def data_source_de(self, database_id): return "ds_" + database_id[-2:]
    def esquema(self, ds): return self.ESQUEMAS[ds]
    def titulos_existentes(self, *_): return {"ya_esta"}

    def crear_pagina(self, ds, props):
        self.creadas.append((ds, props))
        return f"page{len(self.creadas)}"


def test_notion_una_base_por_idioma(tmp_path, monkeypatch):
    from kobo_words.config import Config, bases_notion_desde_entorno
    from kobo_words.notion import sincronizar

    for var, valor in {
        "NOTION_DATABASE_ID_EN": "base_en", "NOTION_DATABASE_ID_ES": "base_es",
        "NOTION_PROP_DEFINICION": "Definición", "NOTION_PROP_LIBRO": "Libro",
        "NOTION_PROP_FECHA": "Fecha",
        # La base inglesa tiene las columnas en inglés y no tiene fecha:
        "NOTION_PROP_DEFINICION_EN": "Definition", "NOTION_PROP_LIBRO_EN": "Book",
        "NOTION_PROP_FECHA_EN": "-",
    }.items():
        monkeypatch.setenv(var, valor)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    cfg = Config(None, tmp_path, "token", bases_notion_desde_entorno())

    entradas = [
        Entrada("ubiquitous", "en", "Found everywhere.", libro="Dune", fecha="2026-10-01"),
        Entrada("desasosiego", "es", "Falta de sosiego.", libro="Niebla", fecha="2026-10-03"),
        Entrada("ya_esta", "en", "x"),
        Entrada("sin_def", "es"),
        Entrada("bonjour", "fr", "Salut."),  # no hay base para francés
    ]
    c = ClienteNotionFalso()
    assert sincronizar(c, entradas, cfg) == (2, 3)
    assert c.creadas[0] == ("ds_en", {
        "Word": {"title": [{"text": {"content": "ubiquitous"}}]},
        "Definition": {"rich_text": [{"text": {"content": "Found everywhere."}}]},
        "Book": {"rich_text": [{"text": {"content": "Dune"}}]},
    })
    ds, props = c.creadas[1]
    assert ds == "ds_es" and props["Libro"] == {"select": {"name": "Niebla"}}
    assert props["Fecha"] == {"date": {"start": "2026-10-03"}}


def test_normalizar_id():
    from kobo_words.config import normalizar_id

    db = "0123456789abcdef0123456789abcdef"
    vista = "fedcba9876543210fedcba9876543210"
    assert normalizar_id(db) == db
    assert normalizar_id(f" '{db.upper()}' ") == db
    assert normalizar_id("01234567-89ab-cdef-0123-456789abcdef") == db
    assert normalizar_id(f"https://www.notion.so/jorge/Mis-palabras-{db}?v={vista}&pvs=4") == db
    assert normalizar_id(f"https://www.notion.so/{db}?v={vista}") == db
