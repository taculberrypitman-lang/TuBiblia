# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser

from tubiblia.module_store import MAX_MODULE_FILE_BYTES

REGISTRY_URL = "https://mybible.zone/repository/registry/registry.zip"
REGISTRY_MAX_BYTES = 16 * 1024 * 1024
ALLOWED_HOSTS = frozenset({"mybible.zone", "mybible.infoo.pro"})
_MODULE_STEM = re.compile(r"^[A-Za-z0-9._+'-]{1,128}$")


class CatalogError(Exception):
    """The MyBible module catalog or a downloaded archive cannot be used."""


@dataclass(frozen=True)
class CatalogModule:
    abbreviation: str
    file_stem: str
    language: str
    description: str
    information: str
    updated: str
    size: str
    book_count: int
    download_url: str


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def _plain_text(value: object) -> str:
    parser = _PlainTextParser()
    parser.feed(str(value or ""))
    parser.close()
    return " ".join(parser.parts)


def _validate_download_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CatalogError("El catálogo contiene una URL de descarga no válida.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise CatalogError("El catálogo contiene una URL de descarga no permitida.")
    return parsed


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urllib.parse.urljoin(req.full_url, newurl)
        _validate_download_url(destination)
        return super().redirect_request(req, fp, code, msg, headers, destination)


def _read_https(url: str, limit: int) -> bytes:
    _validate_download_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TuBiblia/0.1 (+local Bible module reader)"},
    )
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            _validate_download_url(response.geturl())
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > limit:
                raise CatalogError("El archivo supera el límite de descarga permitido.")
            chunks: list[bytes] = []
            total = 0
            while chunk := response.read(min(64 * 1024, limit + 1 - total)):
                total += len(chunk)
                if total > limit:
                    raise CatalogError("El archivo supera el límite de descarga permitido.")
                chunks.append(chunk)
            return b"".join(chunks)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise CatalogError(f"No se pudo descargar {url}: {exc}") from exc


def _host_templates(registry: dict[str, object]) -> dict[str, str]:
    hosts = registry.get("hosts")
    if not isinstance(hosts, list):
        raise CatalogError("El catálogo no contiene la lista de servidores.")

    templates: dict[str, str] = {}
    for host in hosts:
        if not isinstance(host, dict):
            continue
        alias = host.get("alias")
        template = host.get("path")
        if not isinstance(alias, str) or not isinstance(template, str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", alias):
            continue
        if template.count("%s") != 1:
            continue
        try:
            parsed = urllib.parse.urlsplit(template.replace("%s", "module"))
            port = parsed.port
        except ValueError:
            continue
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.query
            or parsed.fragment
        ):
            continue
        templates[alias] = template
    if not templates:
        raise CatalogError("El catálogo no ofrece un servidor HTTPS compatible.")
    return templates


def _module_url(entry: dict[str, object], templates: dict[str, str]) -> str | None:
    urls = entry.get("url")
    file_stem = entry.get("fil")
    if not isinstance(urls, list) or not isinstance(file_stem, str):
        return None
    if not _MODULE_STEM.fullmatch(file_stem) or file_stem in {".", ".."}:
        return None

    for value in urls:
        if not isinstance(value, str):
            continue
        match = re.fullmatch(r"\{([A-Za-z0-9_-]{1,32})\}(.+)", value)
        if match is None:
            continue
        alias, encoded_stem = match.groups()
        template = templates.get(alias)
        if template is None:
            continue
        try:
            decoded_stem = urllib.parse.unquote(encoded_stem, errors="strict")
        except (UnicodeDecodeError, ValueError):
            continue
        if decoded_stem != file_stem or "/" in decoded_stem or "\\" in decoded_stem:
            continue
        url = template.replace("%s", urllib.parse.quote(file_stem, safe=""))
        _validate_download_url(url)
        return url
    return None


def parse_registry(archive: bytes) -> tuple[CatalogModule, ...]:
    if len(archive) > REGISTRY_MAX_BYTES:
        raise CatalogError("El catálogo supera el límite de tamaño permitido.")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            files = [
                member
                for member in zipped.infolist()
                if not member.is_dir() and member.filename == "registry.json"
            ]
            if len(files) != 1 or files[0].file_size > REGISTRY_MAX_BYTES:
                raise CatalogError("El ZIP no contiene un registry.json válido.")
            registry_bytes = zipped.read(files[0])
        registry = json.loads(registry_bytes.decode("utf-8-sig"))
    except (zipfile.BadZipFile, OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"No se pudo leer el registro de módulos: {exc}") from exc

    if not isinstance(registry, dict):
        raise CatalogError("El registro de módulos tiene un formato inesperado.")
    templates = _host_templates(registry)
    entries = registry.get("downloads")
    if not isinstance(entries, list):
        raise CatalogError("El catálogo no contiene módulos descargables.")

    modules: list[CatalogModule] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            book_count = int(entry.get("bkq", "0"))
        except (TypeError, ValueError):
            continue
        if book_count <= 0:
            continue
        abbreviation = entry.get("abr")
        file_stem = entry.get("fil")
        description = entry.get("des")
        language = entry.get("lng", "")
        if not all(isinstance(value, str) and value for value in (abbreviation, file_stem, description)):
            continue
        url = _module_url(entry, templates)
        if url is None:
            continue
        modules.append(
            CatalogModule(
                abbreviation=abbreviation,
                file_stem=file_stem,
                language=language if isinstance(language, str) else "",
                description=_plain_text(description),
                information=_plain_text(entry.get("inf", "")),
                updated=str(entry.get("upd", "")),
                size=str(entry.get("siz", "")),
                book_count=book_count,
                download_url=url,
            )
        )
    if not modules:
        raise CatalogError("El registro no contiene módulos bíblicos compatibles.")
    return tuple(sorted(modules, key=lambda item: (item.language.casefold(), item.description.casefold(), item.abbreviation.casefold())))


def fetch_catalog() -> tuple[CatalogModule, ...]:
    return parse_registry(_read_https(REGISTRY_URL, REGISTRY_MAX_BYTES))


def download_module_archive(module: CatalogModule) -> bytes:
    return _read_https(module.download_url, MAX_MODULE_FILE_BYTES)
