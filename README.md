# kobo-words 📚

Exporta las palabras que buscas en el diccionario de tu **Kobo**, obtiene su definición
y las guarda en ficheros `.txt` y en una base de datos de **Notion** para repasarlas.

```
Kobo (WordList) ──► definiciones (APIs gratuitas) ──► .txt + palabras.json ──► Notion
```

## Qué hace

- **Lee el Kobo de forma segura**: trabaja sobre una copia de `KoboReader.sqlite`, nunca sobre el original.
- **Detecta el Kobo solo** (Windows, macOS y Linux) o usa la ruta que le indiques.
- **Idioma correcto**: usa el diccionario con el que buscaste la palabra en el Kobo (columna `DictSuffix`),
  no una suposición.
- **Guarda el libro** en el que encontraste cada palabra y la fecha.
- **Definiciones gratuitas, sin claves**:
  - Inglés: [Free Dictionary API](https://dictionaryapi.dev) → Wiktionary
  - Español: [Wikcionario](https://es.wiktionary.org) → Wiktionary en inglés
  - Otros idiomas: Wiktionary en inglés
- **Caché**: una palabra ya buscada no se vuelve a pedir a internet.
- **Histórico acumulado** (`palabras.json`): aunque borres las palabras del Kobo, no se pierden.
  Las que se quedaron sin definición se reintentan en cada ejecución.
- **Notion sin duplicados**: solo sube las palabras que aún no están.
- **Borrado seguro del Kobo**: borra solo lo ya exportado y antes hace una copia de seguridad.

## Instalación

```bash
git clone https://github.com/TU_USUARIO/kobo-words.git
cd kobo-words
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Edita `.env` con tu carpeta de salida y, si vas a usar Notion, tu token.
Requiere Python 3.10 o superior.

## Uso

Conecta el Kobo por USB y:

```bash
python -m kobo_words exportar        # lee el Kobo, busca definiciones y genera los .txt
python -m kobo_words notion          # sube a Notion las palabras nuevas
python -m kobo_words todo            # las dos cosas seguidas
python -m kobo_words limpiar-kobo    # borra del Kobo lo ya exportado (pide confirmación)
```

Opciones útiles: `-v` para ver más detalle, `notion --incluir-sin-definicion`
para subir también las palabras sin definición, `limpiar-kobo --si` para no pedir confirmación.

### Ficheros que se generan (en `OUTPUT_FOLDER`)

| Fichero | Contenido |
|---|---|
| `palabras_ingles_definiciones.txt`, `palabras_espanol_definiciones.txt`… | Palabras con definición, una lista por idioma |
| `palabras_sin_definicion.txt` | Las que no se encontraron |
| `palabras.json` | Histórico completo (lo usa el paso de Notion) |
| `cache_definiciones.json` | Caché de definiciones |
| `backups/` | Copias de la base de datos del Kobo antes de borrar |

## Configurar Notion

1. Crea una integración en <https://www.notion.so/my-integrations> y copia el token en `NOTION_TOKEN`.
2. Crea una base de datos con estas columnas (los nombres se pueden cambiar en `.env`):

   | Columna | Tipo | ¿Obligatoria? |
   |---|---|---|
   | Palabra | Título | Sí |
   | Definición | Texto | Sí |
   | Idioma | Selección (o texto) | No |
   | Libro | Texto (o selección) | No |
   | Fecha | Fecha | No |

   Si no quieres alguna opcional, deja su variable vacía en `.env`.
3. En la base de datos: **⋯ → Conexiones → añade tu integración**. Sin este paso la API devuelve 404.
4. Copia el ID de la base de datos (los 32 caracteres de la URL, antes de `?v=`) en `NOTION_DATABASE_ID`.

El script usa la versión `2025-09-03` de la API de Notion (bases de datos con *data sources*).
Antes de subir nada comprueba que las columnas existen y tienen el tipo correcto.

## Pruebas

```bash
pip install pytest
pytest
```

Las pruebas usan una base de datos de Kobo falsa y no necesitan internet.

## Estructura

```
kobo_words/
├── __main__.py     # línea de comandos
├── config.py       # lectura del .env y detección del Kobo
├── kobo.py         # lectura/borrado de WordList
├── diccionario.py  # fuentes de definiciones + caché
├── exportar.py     # histórico (palabras.json) y .txt
└── notion.py       # cliente de Notion y sincronización
```
