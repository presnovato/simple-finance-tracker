"""Свежесть собранного TMA-бандла относительно исходников.

Хеш считается по тем же правилам, что и Vite-плагин в ``tma/vite.config.ts``:
sha256 по отсортированным путям относительно ``tma/`` с LF-нормализацией.
Алгоритмы должны совпадать — меняй их только вместе.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

TMA_DIR = Path(__file__).resolve().parents[2] / "tma"
EXTRA_FILES = (
    "index.html",
    "package-lock.json",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
)


def bundle_files(tma_dir: Path) -> list[str]:
    rels: list[str] = []
    src = tma_dir / "src"
    if src.is_dir():
        for path in src.rglob("*"):
            if path.is_file():
                rels.append(path.relative_to(tma_dir).as_posix())
    for extra in EXTRA_FILES:
        if (tma_dir / extra).is_file():
            rels.append(extra)
    return sorted(rels)


def source_hash(tma_dir: Path) -> str:
    digest = hashlib.sha256()
    for rel in bundle_files(tma_dir):
        # Читаем байты и декодируем вручную: read_text() на Windows сам
        # нормализует переводы строк, из-за чего результат разошёлся бы с JS.
        content = (
            (tma_dir / rel)
            .read_bytes()
            .decode("utf-8")
            .replace("\r\n", "\n")
        )
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def read_build_meta(tma_dir: Path = TMA_DIR) -> dict | None:
    meta_path = tma_dir / "dist" / "build-meta.json"
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def is_bundle_fresh(tma_dir: Path = TMA_DIR) -> bool:
    meta = read_build_meta(tma_dir)
    if not meta or not meta.get("source_hash"):
        return False
    return meta["source_hash"] == source_hash(tma_dir)


def log_bundle_freshness(tma_dir: Path = TMA_DIR) -> bool:
    fresh = is_bundle_fresh(tma_dir)
    if not fresh:
        logger.warning("tma/dist устарел относительно tma/src")
    else:
        logger.info("tma/dist соответствует tma/src")
    return fresh
