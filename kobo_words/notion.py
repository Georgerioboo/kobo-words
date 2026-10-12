"""Envío del vocabulario a una base de datos de Notion (API 2025-09-03, data sources)."""

import logging
import time

import requests

from .exportar import Entrada, nombre_idioma

log = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
LIMITE_TEXTO = 2000  # máximo de caracteres por bloque rich_text


class ErrorNotion(RuntimeError):
    pass


class ClienteNotion:
    def __init__(self, token: str, pausa: float = 0.35):
        self.pausa = pausa  # Notion permite ~3 peticiones/segundo
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })

    def _peticion(self, metodo: str, ruta: str, **kwargs) -> dict:
        for intento in range(5):
            r = self.s.request(metodo, f"{API}{ruta}", timeout=30, **kwargs)
            time.sleep(self.pausa)
            if r.status_code == 429 or r.status_code >= 500:
                espera = float(r.headers.get("Retry-After", 2 ** intento))
                log.warning("Notion ocupado (%s), reintentando en %.0fs", r.status_code, espera)
                time.sleep(espera)
                continue
            if not r.ok:
                try:
                    msg = r.json().get("message", r.text)
                except ValueError:
                    msg = r.text
                raise ErrorNotion(f"{r.status_code}: {msg}")
            return r.json()
        raise ErrorNotion("Notion no responde tras varios reintentos.")

    def data_source_de(self, database_id: str) -> str:
        """Una base de datos de Notion contiene uno o varios 'data sources'; usamos el primero."""
        db = self._peticion("GET", f"/databases/{database_id}")
        fuentes = db.get("data_sources") or []
        if not fuentes:
            raise ErrorNotion("La base de datos no tiene data sources. ¿Es el ID correcto?")
        if len(fuentes) > 1:
            log.info("La base de datos tiene %d fuentes; se usa '%s'.",
                     len(fuentes), fuentes[0].get("name"))
        return fuentes[0]["id"]

    def esquema(self, data_source_id: str) -> dict[str, str]:
        """Devuelve {nombre_propiedad: tipo}."""
        ds = self._peticion("GET", f"/data_sources/{data_source_id}")
        return {nombre: p["type"] for nombre, p in ds["properties"].items()}

    def titulos_existentes(self, data_source_id: str, prop_titulo: str) -> set[str]:
        """Todas las palabras que ya están en Notion (para no duplicarlas)."""
        titulos: set[str] = set()
        cursor = None
        while True:
            cuerpo = {"page_size": 100}
            if cursor:
                cuerpo["start_cursor"] = cursor
            datos = self._peticion("POST", f"/data_sources/{data_source_id}/query", json=cuerpo)
            for pagina in datos["results"]:
                partes = pagina["properties"].get(prop_titulo, {}).get("title", [])
                texto = "".join(p.get("plain_text", "") for p in partes).strip().lower()
                if texto:
                    titulos.add(texto)
            if not datos.get("has_more"):
                return titulos
            cursor = datos["next_cursor"]

    def crear_pagina(self, data_source_id: str, propiedades: dict) -> str:
        datos = self._peticion("POST", "/pages", json={
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": propiedades,
        })
        return datos["id"]


def _valor(tipo: str, texto: str) -> dict:
    """Construye el valor de una propiedad según su tipo en Notion."""
    texto = texto[:LIMITE_TEXTO]
    if tipo == "title":
        return {"title": [{"text": {"content": texto}}]}
    if tipo == "rich_text":
        return {"rich_text": [{"text": {"content": texto}}]}
    if tipo == "select":
        return {"select": {"name": texto[:100].replace(",", " ")}}
    if tipo == "multi_select":
        return {"multi_select": [{"name": texto[:100].replace(",", " ")}]}
    if tipo == "date":
        return {"date": {"start": texto}}
    raise ErrorNotion(f"Tipo de propiedad no soportado: {tipo}")


def _sincronizar_base(cliente: ClienteNotion, base, entradas: list[Entrada],
                     incluir_sin_definicion: bool) -> tuple[int, int]:
    """Sube un grupo de entradas a UNA base de datos. Devuelve (creadas, omitidas)."""
    ds_id = cliente.data_source_de(base.database_id)
    esquema = cliente.esquema(ds_id)

    # La columna de título es única en cada base: si no se configuró, se usa esa.
    prop_palabra = base.prop_palabra or next(n for n, t in esquema.items() if t == "title")

    # Comprobamos que las columnas configuradas existen y tienen un tipo válido.
    columnas = [
        (prop_palabra, {"title"}),
        (base.prop_definicion, {"rich_text"}),
        (base.prop_idioma, {"select", "multi_select", "rich_text"}),
        (base.prop_libro, {"select", "multi_select", "rich_text"}),
        (base.prop_fecha, {"date"}),
    ]
    for nombre, tipos in columnas:
        if nombre is None:
            continue
        if nombre not in esquema:
            raise ErrorNotion(
                f"La base de datos {base.database_id} no tiene la columna '{nombre}'. "
                f"Columnas disponibles: {', '.join(esquema)}"
            )
        if esquema[nombre] not in tipos:
            raise ErrorNotion(
                f"La columna '{nombre}' es de tipo '{esquema[nombre]}'; "
                f"se esperaba: {' o '.join(sorted(tipos))}."
            )

    existentes = cliente.titulos_existentes(ds_id, prop_palabra)
    creadas = omitidas = 0
    for e in entradas:
        if e.notion_page_id or e.palabra.lower() in existentes:
            omitidas += 1
            continue
        if not e.definicion and not incluir_sin_definicion:
            omitidas += 1
            continue

        props = {prop_palabra: _valor("title", e.palabra)}
        if e.definicion:
            props[base.prop_definicion] = _valor("rich_text", e.definicion)
        if base.prop_idioma:
            props[base.prop_idioma] = _valor(esquema[base.prop_idioma], nombre_idioma(e.idioma))
        if base.prop_libro and e.libro:
            props[base.prop_libro] = _valor(esquema[base.prop_libro], e.libro)
        if base.prop_fecha and e.fecha:
            props[base.prop_fecha] = _valor("date", e.fecha)

        e.notion_page_id = cliente.crear_pagina(ds_id, props)
        existentes.add(e.palabra.lower())
        creadas += 1
        log.info("  + %s", e.palabra)
    return creadas, omitidas


def sincronizar(cliente: ClienteNotion, entradas: list[Entrada], cfg,
                incluir_sin_definicion: bool = False) -> tuple[int, int]:
    """Reparte las entradas por idioma y sube cada grupo a su base de datos.

    Devuelve (creadas, omitidas) en total.
    """
    grupos: dict[str, list[Entrada]] = {}
    sin_base: dict[str, int] = {}
    for e in entradas:
        base = cfg.base_para(e.idioma)
        if base is None:
            sin_base[e.idioma] = sin_base.get(e.idioma, 0) + 1
            continue
        grupos.setdefault(base.database_id, []).append(e)

    for idioma, n in sorted(sin_base.items()):
        log.warning("⚠️  %d palabras en %s no se suben: no hay base de datos para ese idioma "
                    "(añade NOTION_DATABASE_ID_%s o NOTION_DATABASE_ID).",
                    n, nombre_idioma(idioma), idioma.upper())

    bases = {b.database_id: b for b in cfg.notion_bases.values()}
    creadas, omitidas = 0, sum(sin_base.values())
    for database_id, grupo in grupos.items():
        idiomas = ", ".join(sorted({nombre_idioma(e.idioma) for e in grupo}))
        log.info("📘 Base de datos de %s:", idiomas)
        c, o = _sincronizar_base(cliente, bases[database_id], grupo, incluir_sin_definicion)
        creadas += c
        omitidas += o
    return creadas, omitidas
