# Copyright © 2026 CunaWare.Lab
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path


ASSET_DIRECTORY = Path(__file__).parent / "assets"


def asset_path(name: str) -> Path:
    return ASSET_DIRECTORY / name
