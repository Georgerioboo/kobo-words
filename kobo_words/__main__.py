"""Línea de comandos.

    python -m kobo_words exportar        Lee el Kobo, busca definiciones y genera los .txt
    python -m kobo_words notion          Sube a Notion las palabras que aún no estén
    python -m kobo_words todo            exportar + notion
    python -m kobo_words limpiar-kobo    Borra del Kobo las palabras ya exportadas
"""

import argparse
import logging
import sys

from .config import Config, aviso_env, ruta_env
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

    if aviso := aviso_env():
        sys.exit(f"❌ {aviso}")
    if not cfg.notion_token:
        sys.exit("❌ Falta NOTION_TOKEN en el .env")
    if not cfg.notion_bases:
        sys.exit("❌ Falta el ID de la base de datos de Notion en el .env "
                 "(NOTION_DATABASE_ID_ES, NOTION_DATABASE_ID_EN o NOTION_DATABASE_ID)")
    vocab = _vocab(cfg)
    if not vocab.entradas:
        sys.exit("❌ No hay palabras exportadas. Ejecuta primero: python -m kobo_words exportar")

    log.info("🔄 Sincronizando con Notion...")
    try:
        creadas, omitidas = sincronizar(
            ClienteNotion(cfg.notion_token), list(vocab.entradas.values()), cfg, args.incluir_sin_definicion,
        )
    except ErrorNotion as e:
        sys.exit(f"❌ Notion: {e}")
    finally:
        vocab.guardar()  # guarda los page_id de lo que sí se haya creado
    log.info("✅ %d palabras nuevas en Notion (%d ya estaban o sin definición).",
             creadas, omitidas)


def cmd_comprobar(cfg: Config, args) -> None:
    """Revisa la configuración paso a paso sin modificar nada."""
    from .exportar import nombre_idioma
    from .notion import ClienteNotion, ErrorNotion

    ok = True
    log.info("1) Fichero .env")
    if env := ruta_env():
        log.info("   ✅ %s", env)
    else:
        log.info("   ❌ %s", aviso_env())
        ok = False

    log.info("2) Kobo")
    log.info("   %s %s", "✅" if cfg.db_path else "❌",
             cfg.db_path or "no encontrado (¿está conectado y montado como unidad?)")

    log.info("3) Token de Notion")
    if cfg.notion_token:
        t = cfg.notion_token
        log.info("   ✅ %s…%s (%d caracteres)", t[:4], t[-4:], len(t))
    else:
        log.info("   ❌ falta NOTION_TOKEN")
        ok = False

    log.info("4) Bases de datos de Notion")
    if not cfg.notion_bases:
        log.info("   ❌ no hay ninguna: añade NOTION_DATABASE_ID_ES / NOTION_DATABASE_ID_EN")
        ok = False
    cliente = ClienteNotion(cfg.notion_token) if cfg.notion_token else None
    for idioma, base in sorted(cfg.notion_bases.items()):
        nombre = "resto de idiomas" if idioma == "*" else nombre_idioma(idioma)
        log.info("   • %s → %s", nombre, base.database_id)
        if len(base.database_id) != 32:
            log.info("     ❌ no parece un ID de Notion (deben ser 32 caracteres 0-9 y a-f)")
            ok = False
            continue
        if not cliente:
            continue
        try:
            ds = cliente.data_source_de(base.database_id)
            esquema = cliente.esquema(ds)
        except ErrorNotion as e:
            log.info("     ❌ %s", str(e).replace("\n", "\n     "))
            ok = False
            continue
        titulo = next((n for n, t in esquema.items() if t == "title"), None)
        log.info("     ✅ '%s' encontrada. Columnas: %s", cliente.titulo(ds),
                 ", ".join(f"{n} ({t})" for n, t in esquema.items()))
        palabra = base.prop_palabra or titulo
        log.info("     %s La palabra irá a '%s'", "✅" if palabra in esquema else "❌", palabra)
        if esquema.get(base.prop_definicion) == "rich_text":
            log.info("     ✅ La definición irá a '%s'", base.prop_definicion)
        else:
            log.info("     ❌ La definición debería ir a '%s', pero %s", base.prop_definicion,
                     "esa columna no existe" if base.prop_definicion not in esquema
                     else f"es de tipo {esquema[base.prop_definicion]}, no Texto")
            ok = False

    log.info("\n%s", "✅ Todo listo." if ok else "❌ Corrige lo marcado y vuelve a ejecutar 'comprobar'.")


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
    sub.add_parser("comprobar", help="revisa el .env, el Kobo y las bases de Notion")
    p = sub.add_parser("limpiar-kobo", help="borra del Kobo las palabras ya exportadas")
    p.add_argument("--si", action="store_true", help="no pedir confirmación")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    cfg = Config.desde_entorno()
    {"exportar": cmd_exportar, "notion": cmd_notion, "todo": cmd_todo,
     "limpiar-kobo": cmd_limpiar_kobo, "comprobar": cmd_comprobar}[args.comando](cfg, args)


if __name__ == "__main__":
    main()
