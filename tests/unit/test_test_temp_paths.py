from __future__ import annotations

import pytest


@pytest.mark.parametrize("payload", [b"not-a-gif" * 40])
def test_tmp_path_supports_long_parameter_ids(tmp_path, request, payload):
    assert len(request.node.name) > 255
    assert len(tmp_path.name) <= 64 + 1 + 8
    assert tmp_path.is_dir()

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    target = uploads / "img_0123456789abcdef0123456789abcdef.gif"
    target.write_bytes(payload)
    assert target.read_bytes() == payload
