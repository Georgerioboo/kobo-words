"""Línea de comandos.

    python -m kobo_words exportar        Lee el Kobo, busca definiciones y genera los .txt
    python -m kobo_words notion          Sube a Notion las palabras que aún no estén
    python -m kobo_words todo            exportar + notion
    python -m kobo_words limpiar-kobo    Borra del Kobo las palabras ya exportadas
"""

import argparse
import logging
import sys

from .config import Config
from .diccionario import Diccionario
from .exportar import Entrada, Vocabulario, escribir_txt, nombre_idioma
from .kobo import borrar_palabras, leer_palabras

log = logging.getLogger("kobo_words")


def _vocab(cfg: Config) -> Vocabulario:
    return Vocabulario(cfg.carpeta_salida / "palabras.json")


def _necesita_kobo(cfg: Config) -> str:
    if not cfg.db_path:
        sys.exit("❌ No encuentro el Kobo. Conéctalo por USB o define KOBO_DB_PATH en el .env")
    return cfg.db_path


def cmd_exportar(cfg: Config, args) -> None:
    db = _necesita_kobo(cfg)
    log.info("📚 Leyendo %s", db)
    palabras = leer_palabras(db)
    if not palabras:
        log.info("No hay palabras guardadas en el Kobo.")
        return

    vocab = _vocab(cfg)
    dicc = Diccionario(cfg.carpeta_salida / "cache_definiciones.json")
    nuevas = 0
    try:
        for i, p in enumerate(palabras, 1):
            previa = vocab.entradas.get(f"{p.idioma}:{p.palabra}")
            definicion = None
            if not (previa and previa.definicion):
                definicion = dicc.buscar(p.palabra, p.idioma)
            nuevas += vocab.añadir(Entrada(
                palabra=p.palabra,
                idioma=p.idioma,
                definicion=definicion.texto if definicion else None,
                fuente=definicion.fuente if definicion else None,
                libro=p.libro,
                fecha=p.fecha,
                texto_kobo=p.texto_original,
            ))
            marca = "✅" if (definicion or (previa and previa.definicion)) else "❔"
            log.info("%s [%d/%d] %s (%s)", marca, i, len(palabras), p.palabra,
                     nombre_idioma(p.idioma))

        # Reintenta las palabras antiguas del histórico que se quedaron sin definición
        en_kobo = {f"{p.idioma}:{p.palabra}" for p in palabras}
        for e in vocab.sin_definicion():
            if e.clave not in en_kobo and (d := dicc.buscar(e.palabra, e.idioma)):
                e.definicion, e.fuente = d.texto, d.fuente
                log.info("✅ (reintento) %s", e.palabra)
    finally:  # aunque se interrumpa con Ctrl+C, no perdemos lo hecho
        dicc.guardar_cache()
        vocab.guardar()

    archivos = escribir_txt(vocab, cfg.carpeta_salida)
    log.info("\n%d palabras leídas del Kobo (%d nuevas). Total en el histórico: %d "
             "(%d con definición).", len(palabras), nuevas, len(vocab.entradas),
             len(vocab.con_definicion()))
    for a in archivos:
        log.info("📄 %s", a)


def cmd_notion(cfg: Config, args) -> None:
    from .notion import ClienteNotion, ErrorNotion, sincronizar

    if not (cfg.notion_token and cfg.notion_database_id):
        sys.exit("❌ Falta NOTION_TOKEN o NOTION_DATABASE_ID en el .env")
    vocab = _vocab(cfg)
    if not vocab.entradas:
        sys.exit("❌ No hay palabras exportadas. Ejecuta primero: python -m kobo_words exportar")

    log.info("🔄 Sincronizando con Notion...")
    try:
        creadas, omitidas = sincronizar(
            ClienteNotion(cfg.notion_token), cfg.notion_database_id,
            list(vocab.entradas.values()), cfg, args.incluir_sin_definicion,
        )
    except ErrorNotion as e:
        sys.exit(f"❌ Notion: {e}")
    finally:
        vocab.guardar()  # guarda los page_id de lo que sí se haya creado
    log.info("✅ %d palabras nuevas en Notion (%d ya estaban o sin definición).",
             creadas, omitidas)


def cmd_todo(cfg: Config, args) -> None:
    cmd_exportar(cfg, args)
    cmd_notion(cfg, args)


def cmd_limpiar_kobo(cfg: Config, args) -> None:
    db = _necesita_kobo(cfg)
    vocab = _vocab(cfg)
    textos_exportados = {e.texto_kobo for e in vocab.entradas.values() if e.texto_kobo}
    en_kobo = {p.texto_original for p in leer_palabras(db)}
    a_borrar = sorted(en_kobo & textos_exportados)
    if not a_borrar:
        log.info("Nada que borrar: no hay palabras del Kobo que ya estén exportadas.")
        return
    log.info("Se borrarán del Kobo %d palabras ya exportadas "
             "(las que no se hayan exportado se mantienen).", len(a_borrar))
    if not args.si and input("¿Continuar? (s/N): ").strip().lower() != "s":
        log.info("Cancelado.")
        return
    borradas, backup = borrar_palabras(db, a_borrar, cfg.carpeta_salida / "backups")
    log.info("🗑️  %d palabras borradas. Copia de seguridad en %s", borradas, backup)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="kobo_words",
        description="Exporta las palabras guardadas en tu Kobo con su definición y las sube a Notion.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="más detalle en el log")
    sub = parser.add_subparsers(dest="comando", required=True)

    for nombre, ayuda in [("exportar", "lee el Kobo, busca definiciones y genera los .txt"),
                          ("todo", "exportar + notion")]:
        p = sub.add_parser(nombre, help=ayuda)
        if nombre == "todo":
            p.add_argument("--incluir-sin-definicion", action="store_true")
    p = sub.add_parser("notion", help="sube a Notion las palabras que aún no estén")
    p.add_argument("--incluir-sin-definicion", action="store_true",
                   help="sube también las palabras sin definición")
    p = sub.add_parser("limpiar-kobo", help="borra del Kobo las palabras ya exportadas")
    p.add_argument("--si", action="store_true", help="no pedir confirmación")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    cfg = Config.desde_entorno()
    {"exportar": cmd_exportar, "notion": cmd_notion, "todo": cmd_todo,
     "limpiar-kobo": cmd_limpiar_kobo}[args.comando](cfg, args)


if __name__ == "__main__":
    main()
