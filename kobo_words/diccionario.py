"""Búsqueda de definiciones con varias fuentes gratuitas y una caché local.

Fuentes (en orden):
  - Inglés:  Free Dictionary API (dictionaryapi.dev) → Wiktionary en inglés
  - Español: Wiktionary en español (es.wiktionary.org) → Wiktionary en inglés
  - Otros:   Wiktionary en inglés (definiciones en inglés)
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)

USER_AGENT = "kobo-words/1.0 (https://github.com/; script personal de vocabulario)"
TIMEOUT = 8
MAX_DEFINICIONES = 3


@dataclass
class Definicion:
    texto: str
    fuente: str


# --------------------------------------------------------------------------- utilidades


def _sesion() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _quitar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _limpiar_wikitexto(texto: str) -> str:
    texto = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>", "", texto, flags=re.S)
    texto = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", texto)  # [[a|b]] → b
    for _ in range(3):  # plantillas anidadas {{...}}
        texto = re.sub(r"\{\{[^{}]*\}\}", "", texto)
    texto = re.sub(r"'{2,}", "", texto)  # negritas/cursivas
    texto = _quitar_html(texto)
    return texto.strip(" :;,.") + ("." if texto.strip() else "")


def _unir(defs: list[str]) -> str | None:
    defs = [d for d in dict.fromkeys(d.strip() for d in defs) if d]
    if not defs:
        return None
    if len(defs) == 1:
        return defs[0]
    return " | ".join(f"{i}. {d}" for i, d in enumerate(defs[:MAX_DEFINICIONES], 1))


# --------------------------------------------------------------------------- fuentes


def free_dictionary(s: requests.Session, palabra: str) -> Definicion | None:
    r = s.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{palabra}", timeout=TIMEOUT)
    if r.status_code != 200:
        return None
    defs: list[str] = []
    for entrada in r.json():
        for sig in entrada.get("meanings", []):
            categoria = sig.get("partOfSpeech", "")
            for d in sig.get("definitions", [])[:1]:
                defs.append(f"({categoria}) {d['definition']}" if categoria else d["definition"])
    texto = _unir(defs)
    return Definicion(texto, "dictionaryapi.dev") if texto else None


def wiktionary_es(s: requests.Session, palabra: str) -> Definicion | None:
    """Lee el wikitexto de es.wiktionary y extrae las acepciones de la sección española."""
    r = s.get(
        "https://es.wiktionary.org/w/api.php",
        params={
            "action": "parse",
            "page": palabra,
            "prop": "wikitext",
            "format": "json",
            "formatversion": 2,
            "redirects": 1,
        },
        timeout=TIMEOUT,
    )
    if r.status_code != 200 or "error" in r.json():
        return None
    wikitexto = r.json()["parse"]["wikitext"]
    seccion = re.split(r"^==\s*\{\{lengua\|es\}\}\s*==", wikitexto, flags=re.M)
    if len(seccion) < 2:
        return None
    seccion_es = re.split(r"^==\s*\{\{lengua\|", seccion[1], flags=re.M)[0]
    defs = [
        _limpiar_wikitexto(m.group(1))
        for m in re.finditer(r"^;\s*\d+[^:\n]*:\s*(.+)$", seccion_es, flags=re.M)
    ]
    texto = _unir(defs)
    return Definicion(texto, "es.wiktionary.org") if texto else None


def wiktionary_en(s: requests.Session, palabra: str, idioma: str) -> Definicion | None:
    """API REST de en.wiktionary: sirve para casi cualquier idioma (definiciones en inglés)."""
    r = s.get(
        f"https://en.wiktionary.org/api/rest_v1/page/definition/{palabra}",
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        return None
    defs: list[str] = []
    for bloque in r.json().get(idioma, []):
        categoria = bloque.get("partOfSpeech", "")
        for d in bloque.get("definitions", [])[:1]:
            limpio = _quitar_html(d.get("definition", ""))
            if limpio:
                defs.append(f"({categoria}) {limpio}" if categoria else limpio)
    texto = _unir(defs)
    return Definicion(texto, "en.wiktionary.org") if texto else None


# --------------------------------------------------------------------------- buscador


class Diccionario:
    """Busca definiciones y las recuerda en un JSON para no repetir peticiones."""

    def __init__(self, ruta_cache: Path, pausa: float = 0.3):
        self.ruta_cache = ruta_cache
        self.pausa = pausa
        self.sesion = _sesion()
        self.cache: dict[str, dict] = {}
        if ruta_cache.is_file():
            self.cache = json.loads(ruta_cache.read_text(encoding="utf-8"))

    def guardar_cache(self) -> None:
        self.ruta_cache.parent.mkdir(parents=True, exist_ok=True)
        self.ruta_cache.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _fuentes(self, idioma: str):
        if idioma == "en":
            return [lambda p: free_dictionary(self.sesion, p),
                    lambda p: wiktionary_en(self.sesion, p, "en")]
        if idioma == "es":
            return [lambda p: wiktionary_es(self.sesion, p),
                    lambda p: wiktionary_en(self.sesion, p, "es")]
        return [lambda p: wiktionary_en(self.sesion, p, idioma)]

    def buscar(self, palabra: str, idioma: str) -> Definicion | None:
        clave = f"{idioma}:{palabra}"
        if clave in self.cache:
            c = self.cache[clave]
            return Definicion(c["texto"], c["fuente"])

        for fuente in self._fuentes(idioma):
            try:
                resultado = fuente(palabra)
            except (requests.RequestException, ValueError, KeyError) as e:
                log.debug("Error buscando %r: %s", palabra, e)
                resultado = None
            time.sleep(self.pausa)  # ser amables con APIs gratuitas
            if resultado:
                self.cache[clave] = {"texto": resultado.texto, "fuente": resultado.fuente}
                return resultado
        return None
