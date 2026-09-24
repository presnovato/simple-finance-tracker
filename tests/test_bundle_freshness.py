import json

from finance_bot.services import bundle


def test_committed_bundle_meta_matches_current_sources():
    meta = bundle.read_build_meta()

    assert meta is not None, "tma/dist/build-meta.json отсутствует"
    assert meta["source_hash"] == bundle.source_hash(bundle.TMA_DIR)
    assert meta.get("built_at")


def test_bundle_files_cover_sources_and_configs():
    files = bundle.bundle_files(bundle.TMA_DIR)

    assert "src/main.tsx" in files
    assert "index.html" in files
    assert "vite.config.ts" in files
    assert "package-lock.json" in files
    assert files == sorted(files)


def test_source_hash_changes_when_a_source_byte_changes(tmp_path):
    tma = tmp_path / "tma"
    (tma / "src").mkdir(parents=True)
    (tma / "src" / "a.ts").write_text("export const a = 1\n", encoding="utf-8")
    (tma / "index.html").write_text("<html></html>\n", encoding="utf-8")

    first = bundle.source_hash(tma)
    (tma / "src" / "a.ts").write_text("export const a = 2\n", encoding="utf-8")

    assert bundle.source_hash(tma) != first


def test_source_hash_ignores_line_endings(tmp_path):
    tma = tmp_path / "tma"
    (tma / "src").mkdir(parents=True)
    (tma / "src" / "a.ts").write_bytes(b"line1\nline2\n")
    unix = bundle.source_hash(tma)

    (tma / "src" / "a.ts").write_bytes(b"line1\r\nline2\r\n")

    assert bundle.source_hash(tma) == unix


def test_is_bundle_fresh_detects_missing_and_stale_meta(tmp_path):
    tma = tmp_path / "tma"
    (tma / "src").mkdir(parents=True)
    (tma / "src" / "a.ts").write_text("export const a = 1\n", encoding="utf-8")
    (tma / "dist").mkdir()

    assert bundle.is_bundle_fresh(tma) is False

    meta_path = tma / "dist" / "build-meta.json"
    meta_path.write_text(
        json.dumps({"source_hash": "deadbeef", "built_at": "2026-01-01"}),
        encoding="utf-8",
    )
    assert bundle.is_bundle_fresh(tma) is False

    meta_path.write_text(
        json.dumps(
            {
                "source_hash": bundle.source_hash(tma),
                "built_at": "2026-01-01",
            }
        ),
        encoding="utf-8",
    )
    assert bundle.is_bundle_fresh(tma) is True
