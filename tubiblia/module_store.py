# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


MAX_MODULE_FILE_BYTES = 100 * 1024 * 1024
_MODULE_FILE_STEM = re.compile(r"^[A-Za-z0-9._+'-]{1,128}$")


class ModuleError(Exception):
    """An installed or imported Bible module cannot be used."""


class ModuleFormatError(ModuleError):
    """A SQLite file does not have the required MyBible Bible schema."""


@dataclass(frozen=True)
class Book:
    number: int
    short_name: str
    long_name: str


@dataclass(frozen=True)
class Verse:
    book_number: int
    chapter: int
    verse: int
    text: str


@dataclass(frozen=True)
class SearchResult(Verse):
    book_name: str


@dataclass(frozen=True)
class ModuleMetadata:
    path: Path
    sha256: str
    name: str
    language: str
    book_count: int
    verse_count: int


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect_readonly(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (OSError, sqlite3.Error) as exc:
        raise ModuleFormatError(f"No se pudo abrir el módulo: {exc}") from exc
    connection.row_factory = sqlite3.Row
    return connection


def inspect_module(path: Path) -> ModuleMetadata:
    path = Path(path).expanduser()
    if not path.is_file():
        raise ModuleFormatError(f"El archivo del módulo no existe: {path}")

    connection = _connect_readonly(path)
    try:
        integrity = connection.execute("PRAGMA quick_check(1)").fetchone()
        if integrity is None or integrity[0] != "ok":
            detail = "sin resultado" if integrity is None else str(integrity[0])
            raise ModuleFormatError(f"La base de datos no supera quick_check: {detail}")

        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required_tables = {"info", "books", "verses"}
        missing_tables = required_tables - tables
        if missing_tables:
            raise ModuleFormatError(
                "Faltan tablas requeridas de MyBible: "
                + ", ".join(sorted(missing_tables))
            )

        required_columns = {
            "info": {"name", "value"},
            "books": {"book_number", "short_name", "long_name"},
            "verses": {"book_number", "chapter", "verse", "text"},
        }
        for table, required in required_columns.items():
            columns = {
                str(row["name"])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            missing_columns = required - columns
            if missing_columns:
                raise ModuleFormatError(
                    f"La tabla {table} no contiene: "
                    + ", ".join(sorted(missing_columns))
                )

        info = {
            str(row["name"]): str(row["value"] or "")
            for row in connection.execute("SELECT name, value FROM info")
        }
        book_count = int(connection.execute("SELECT COUNT(*) FROM books").fetchone()[0])
        verse_count = int(connection.execute("SELECT COUNT(*) FROM verses").fetchone()[0])
        if book_count == 0 or verse_count == 0:
            raise ModuleFormatError("El módulo no contiene libros y versículos.")

        missing_book_refs = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM verses AS v
                LEFT JOIN books AS b ON b.book_number = v.book_number
                WHERE b.book_number IS NULL
                """
            ).fetchone()[0]
        )
        if missing_book_refs:
            raise ModuleFormatError(
                f"Hay {missing_book_refs} versículos sin un libro correspondiente."
            )
    except sqlite3.Error as exc:
        raise ModuleFormatError(f"No se pudo validar el módulo: {exc}") from exc
    finally:
        connection.close()

    return ModuleMetadata(
        path=path.resolve(),
        sha256=_file_sha256(path),
        name=info.get("description") or info.get("name") or path.stem,
        language=info.get("language", ""),
        book_count=book_count,
        verse_count=verse_count,
    )


class BibleModule:
    def __init__(self, path: Path):
        self.metadata = inspect_module(path)

    def books(self) -> tuple[Book, ...]:
        connection = _connect_readonly(self.metadata.path)
        try:
            rows = connection.execute(
                """
                SELECT book_number, short_name, long_name
                FROM books
                WHERE EXISTS (
                    SELECT 1
                    FROM verses
                    WHERE verses.book_number = books.book_number
                )
                ORDER BY book_number
                """
            )
            return tuple(
                Book(
                    number=int(row["book_number"]),
                    short_name=str(row["short_name"] or ""),
                    long_name=str(row["long_name"] or row["short_name"] or ""),
                )
                for row in rows
            )
        except sqlite3.Error as exc:
            raise ModuleError(f"No se pudieron leer los libros: {exc}") from exc
        finally:
            connection.close()

    def chapters(self, book_number: int) -> tuple[int, ...]:
        connection = _connect_readonly(self.metadata.path)
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT chapter
                FROM verses
                WHERE book_number = ?
                ORDER BY chapter
                """,
                (book_number,),
            )
            return tuple(int(row["chapter"]) for row in rows)
        except sqlite3.Error as exc:
            raise ModuleError(f"No se pudieron leer los capítulos: {exc}") from exc
        finally:
            connection.close()

    def chapter_references(self) -> tuple[tuple[int, int], ...]:
        connection = _connect_readonly(self.metadata.path)
        try:
            rows = connection.execute(
                """
                SELECT DISTINCT book_number, chapter
                FROM verses
                ORDER BY book_number, chapter
                """
            )
            return tuple(
                (int(row["book_number"]), int(row["chapter"])) for row in rows
            )
        except sqlite3.Error as exc:
            raise ModuleError(f"No se pudieron leer las referencias: {exc}") from exc
        finally:
            connection.close()

    def verses(self, book_number: int, chapter: int) -> tuple[Verse, ...]:
        connection = _connect_readonly(self.metadata.path)
        try:
            rows = connection.execute(
                """
                SELECT book_number, chapter, verse, text
                FROM verses
                WHERE book_number = ? AND chapter = ?
                ORDER BY verse
                """,
                (book_number, chapter),
            )
            return tuple(
                Verse(
                    book_number=int(row["book_number"]),
                    chapter=int(row["chapter"]),
                    verse=int(row["verse"]),
                    text=str(row["text"] or ""),
                )
                for row in rows
            )
        except sqlite3.Error as exc:
            raise ModuleError(f"No se pudieron leer los versículos: {exc}") from exc
        finally:
            connection.close()

    def search(self, query: str, limit: int = 200) -> tuple[SearchResult, ...]:
        needle = query.strip().casefold()
        if not needle:
            return ()
        if limit < 1:
            raise ValueError("El límite de resultados debe ser positivo.")

        connection = _connect_readonly(self.metadata.path)
        try:
            rows = connection.execute(
                """
                SELECT v.book_number, b.long_name, b.short_name,
                       v.chapter, v.verse, v.text
                FROM verses AS v
                JOIN books AS b ON b.book_number = v.book_number
                ORDER BY v.book_number, v.chapter, v.verse
                """
            )
            results: list[SearchResult] = []
            for row in rows:
                text = str(row["text"] or "")
                if needle in text.casefold():
                    results.append(
                        SearchResult(
                            book_number=int(row["book_number"]),
                            chapter=int(row["chapter"]),
                            verse=int(row["verse"]),
                            text=text,
                            book_name=str(row["long_name"] or row["short_name"] or ""),
                        )
                    )
                    if len(results) >= limit:
                        break
            return tuple(results)
        except sqlite3.Error as exc:
            raise ModuleError(f"No se pudo buscar en el módulo: {exc}") from exc
        finally:
            connection.close()


class ModuleStore:
    def __init__(self, data_directory: Path):
        self.data_directory = Path(data_directory).expanduser()
        self.modules_directory = self.data_directory / "modules"
        self.modules_directory.mkdir(parents=True, exist_ok=True)

    def scan_modules(self) -> tuple[tuple[ModuleMetadata, ...], tuple[str, ...]]:
        modules: list[ModuleMetadata] = []
        errors: list[str] = []
        paths = sorted(
            (
                path
                for path in self.modules_directory.iterdir()
                if path.is_file() and path.suffix.casefold() == ".sqlite3"
            ),
            key=lambda path: path.name.casefold(),
        )
        for path in paths:
            try:
                modules.append(inspect_module(path))
            except ModuleError as exc:
                errors.append(f"{path.name}: {exc}")
        return tuple(modules), tuple(errors)

    def import_module(self, source: Path) -> ModuleMetadata:
        source = Path(source).expanduser()
        metadata = inspect_module(source)
        destination = self.modules_directory / f"{metadata.sha256}.SQLite3"
        if destination.exists():
            existing = inspect_module(destination)
            if existing.sha256 != metadata.sha256:
                raise ModuleError(
                    "El destino de importación ya existe con contenido distinto."
                )
            return existing
        if source.resolve() == destination.resolve():
            return metadata

        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            shutil.copyfile(source, temporary)
            copied_metadata = inspect_module(temporary)
            if copied_metadata.sha256 != metadata.sha256:
                raise ModuleError("El módulo cambió mientras se estaba copiando.")
            os.replace(temporary, destination)
        except (OSError, ModuleError):
            temporary.unlink(missing_ok=True)
            raise

        return inspect_module(destination)

    def import_module_archive(
        self, archive: bytes, expected_file_stem: str
    ) -> ModuleMetadata:
        if len(archive) > MAX_MODULE_FILE_BYTES:
            raise ModuleFormatError("El archivo descargado supera el límite permitido.")
        if (
            not _MODULE_FILE_STEM.fullmatch(expected_file_stem)
            or expected_file_stem in {".", ".."}
        ):
            raise ModuleFormatError("El registro contiene un nombre de módulo no válido.")

        temporary_path: Path | None = None
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                entries = zipped.infolist()
                if len(entries) > 128:
                    raise ModuleFormatError("El ZIP contiene demasiados archivos.")
                expected_name = f"{expected_file_stem}.SQLite3".casefold()
                matches = [
                    entry
                    for entry in entries
                    if not entry.is_dir()
                    and PurePosixPath(entry.filename).name.casefold() == expected_name
                ]
                if not matches:
                    matches = [
                        entry
                        for entry in entries
                        if not entry.is_dir()
                        and PurePosixPath(entry.filename).name.casefold()
                        == ".sqlite3"
                    ]
                if len(matches) != 1:
                    raise ModuleFormatError(
                        "El ZIP no contiene exactamente el módulo SQLite anunciado."
                    )
                entry = matches[0]
                member_path = PurePosixPath(entry.filename)
                if (
                    member_path.is_absolute()
                    or "\\" in entry.filename
                    or ".." in member_path.parts
                    or entry.flag_bits & 1
                ):
                    raise ModuleFormatError("La ruta del archivo dentro del ZIP no es segura.")
                if entry.file_size < 1 or entry.file_size > MAX_MODULE_FILE_BYTES:
                    raise ModuleFormatError("El módulo SQLite supera el límite permitido.")
                if (
                    entry.file_size > 1024 * 1024
                    and entry.compress_size
                    and entry.file_size / entry.compress_size > 500
                ):
                    raise ModuleFormatError("El módulo ZIP tiene una compresión sospechosa.")

                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=".module-download-",
                    suffix=".SQLite3",
                    dir=self.modules_directory,
                    delete=False,
                ) as target:
                    temporary_path = Path(target.name)
                    written = 0
                    with zipped.open(entry) as source:
                        while chunk := source.read(1024 * 1024):
                            written += len(chunk)
                            if written > MAX_MODULE_FILE_BYTES:
                                raise ModuleFormatError(
                                    "El módulo extraído supera el límite permitido."
                                )
                            target.write(chunk)
                    if written != entry.file_size:
                        raise ModuleFormatError(
                            "El módulo descargado está incompleto o dañado."
                        )
            return self.import_module(temporary_path)
        except ModuleError:
            raise
        except (
            OSError,
            EOFError,
            RuntimeError,
            zipfile.BadZipFile,
            zlib.error,
        ) as exc:
            raise ModuleFormatError(f"No se pudo validar el ZIP del módulo: {exc}") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
