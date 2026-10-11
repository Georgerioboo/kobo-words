"""Almacén de vocabulario (palabras.json) y generación de los .txt."""

import json
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

NOMBRES_IDIOMA = {"en": "Inglés", "es": "Español", "fr": "Francés", "de": "Alemán",
                  "it": "Italiano", "pt": "Portugués", "nl": "Neerlandés"}


def nombre_idioma(codigo: str) -> str:
    return NOMBRES_IDIOMA.get(codigo, codigo.upper())


def _slug(texto: str) -> str:
    """'Inglés' → 'ingles' (nombres de fichero sin tildes)."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.lower().replace(" ", "_")


@dataclass
class Entrada:
    palabra: str
    idioma: str
    definicion: str | None = None
    fuente: str | None = None
    libro: str | None = None
    fecha: str | None = None
    texto_kobo: str | None = None
    notion_page_id: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def clave(self) -> str:
        return f"{self.idioma}:{self.palabra}"


class Vocabulario:
    """Histórico acumulado de todas las palabras exportadas, aunque se borren del Kobo."""

    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.entradas: dict[str, Entrada] = {}
        if ruta.is_file():
            for d in json.loads(ruta.read_text(encoding="utf-8")):
                e = Entrada(**d)
                self.entradas[e.clave] = e

    def añadir(self, e: Entrada) -> bool:
        """Añade o completa una entrada. Devuelve True si era nueva."""
        previa = self.entradas.get(e.clave)
        if previa is None:
            self.entradas[e.clave] = e
            return True
        if not previa.definicion and e.definicion:
            previa.definicion, previa.fuente = e.definicion, e.fuente
        previa.libro = previa.libro or e.libro
        previa.fecha = previa.fecha or e.fecha
        previa.texto_kobo = e.texto_kobo or previa.texto_kobo
        return False

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        datos = [asdict(e) for e in sorted(self.entradas.values(), key=lambda e: e.clave)]
        self.ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")

    def con_definicion(self) -> list[Entrada]:
        return [e for e in self.entradas.values() if e.definicion]

    def sin_definicion(self) -> list[Entrada]:
        return [e for e in self.entradas.values() if not e.definicion]


def escribir_txt(vocab: Vocabulario, carpeta: Path) -> list[Path]:
    """Un .txt por idioma con definiciones y otro con las palabras sin definición."""
    carpeta.mkdir(parents=True, exist_ok=True)
    creados: list[Path] = []

    por_idioma: dict[str, list[Entrada]] = {}
    for e in vocab.con_definicion():
        por_idioma.setdefault(e.idioma, []).append(e)

    for idioma, entradas in sorted(por_idioma.items()):
        nombre = nombre_idioma(idioma)
        ruta = carpeta / f"palabras_{_slug(nombre)}_definiciones.txt"
        with ruta.open("w", encoding="utf-8") as f:
            f.write(f"=== {len(entradas)} palabras en {nombre} con definición ===\n\n")
            for e in sorted(entradas, key=lambda e: e.palabra):
                f.write(f"• {e.palabra}\n  {e.definicion}\n")
                if e.libro:
                    f.write(f"  📖 {e.libro}\n")
                f.write("\n")
        creados.append(ruta)

    sin_def = vocab.sin_definicion()
    ruta = carpeta / "palabras_sin_definicion.txt"
    if sin_def:
        with ruta.open("w", encoding="utf-8") as f:
            f.write(f"=== {len(sin_def)} palabras sin definición ===\n\n")
            for e in sorted(sin_def, key=lambda e: (e.idioma, e.palabra)):
                f.write(f"• {e.palabra} ({nombre_idioma(e.idioma)})\n")
        creados.append(ruta)
    elif ruta.exists():
        ruta.unlink()
    return creados
