"""P1.3 — supply-chain hardening: tar extraction must reject path traversal."""

import io
import tarfile

import pytest

from indaga.reference.manager import _safe_extract


def _make_tar(path, members):
    with tarfile.open(path, "w") as tf:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_safe_extract_blocks_traversal(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    evil = tmp_path / "evil.tar"
    _make_tar(evil, [("../escape.txt", b"pwned")])
    with tarfile.open(evil) as tf:
        with pytest.raises(Exception):  # noqa: B017 — data-filter or manual guard, either rejects
            _safe_extract(tf, dest)
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_allows_benign(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    good = tmp_path / "good.tar"
    _make_tar(good, [("sub/file.txt", b"ok")])
    with tarfile.open(good) as tf:
        _safe_extract(tf, dest)
    assert (dest / "sub" / "file.txt").read_bytes() == b"ok"
