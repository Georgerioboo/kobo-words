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


def test_notion_sincronizar(tmp_path):
    from kobo_words.config import Config
    from kobo_words.notion import sincronizar

    class ClienteFalso:
        creadas = []
        def data_source_de(self, _): return "ds1"
        def esquema(self, _): return {"Palabra": "title", "Definición": "rich_text",
                                      "Idioma": "select", "Libro": "rich_text", "Fecha": "date"}
        def titulos_existentes(self, *_): return {"ya_esta"}
        def crear_pagina(self, ds, props):
            self.creadas.append(props); return f"page{len(self.creadas)}"

    cfg = Config(None, tmp_path, "t", "db", "Palabra", "Definición", "Idioma", "Libro", "Fecha")
    entradas = [Entrada("ubiquitous", "en", "Found everywhere.", libro="Dune", fecha="2026-10-01"),
                Entrada("ya_esta", "en", "x"), Entrada("sin_def", "en")]
    c = ClienteFalso()
    assert sincronizar(c, "db", entradas, cfg) == (1, 2)
    assert c.creadas[0]["Idioma"] == {"select": {"name": "Inglés"}}
    assert entradas[0].notion_page_id == "page1"
