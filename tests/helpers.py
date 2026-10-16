# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

import sqlite3
from pathlib import Path


def create_test_module(path: Path) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE info (name TEXT, value TEXT);
            CREATE TABLE books (
                book_color TEXT,
                book_number NUMERIC,
                short_name TEXT,
                long_name TEXT
            );
            CREATE TABLE verses (
                book_number NUMERIC,
                chapter NUMERIC,
                verse NUMERIC,
                text TEXT
            );
            CREATE UNIQUE INDEX verses_index
                ON verses (book_number, chapter, verse);
            INSERT INTO info VALUES ('description', 'Módulo de prueba');
            INSERT INTO info VALUES ('language', 'es');
            INSERT INTO books VALUES ('', 1, 'Uno', 'Libro de prueba');
            INSERT INTO books VALUES ('', 2, 'Dos', 'Segundo libro');
            INSERT INTO verses VALUES (1, 1, 1, 'Una frase de muestra.');
            INSERT INTO verses VALUES (1, 1, 2, 'Café para probar búsqueda.');
            INSERT INTO verses VALUES (1, 2, 1, 'Otra frase de muestra.');
            INSERT INTO verses VALUES (2, 1, 1, 'Contenido de prueba.');
            """
        )
        connection.commit()
    finally:
        connection.close()
    return path
