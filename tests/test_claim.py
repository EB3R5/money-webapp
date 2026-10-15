"""The claim CLI (app/simplefin/claim.py): stdout is exactly the access URL, 403 is exit 2
with the compromise guidance, bad input is exit 1, --out is created 600 and never
overwritten."""

import base64
import io
import os

import httpx
import pytest

from app.simplefin import claim as cl

CLAIM_URL = "https://bridge.test/simplefin/claim/DEMO"
TOKEN = base64.b64encode(CLAIM_URL.encode()).decode()
ACCESS = "https://user:pass@bridge.test/simplefin"


def _transport(status=200, text=ACCESS, seen=None):
    def handler(request: httpx.Request):
        if seen is not None:
            seen.update(method=request.method, url=str(request.url), body=request.content)
        return httpx.Response(status, text=text)
    return httpx.MockTransport(handler)


def test_decode_setup_token():
    assert cl.decode_setup_token(TOKEN) == CLAIM_URL
    assert cl.decode_setup_token(TOKEN.rstrip("=")) == CLAIM_URL           # padding restored
    with pytest.raises(ValueError):
        cl.decode_setup_token("!!not base64!!")
    with pytest.raises(ValueError):
        cl.decode_setup_token(base64.b64encode(b"http://bridge.test/claim").decode())
    with pytest.raises(ValueError):
        cl.decode_setup_token("")


def test_stdout_is_exactly_the_access_url(capsys):
    seen = {}
    rc = cl.main([TOKEN], transport=_transport(seen=seen))
    out, err = capsys.readouterr()
    assert rc == 0 and out == ACCESS + "\n"
    assert seen == {"method": "POST", "url": CLAIM_URL, "body": b""}
    assert "SIMPLEFIN_ACCESS_URL" in err and ACCESS not in err


def test_stdin_mode(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN + "\n"))
    assert cl.main(["--stdin"], transport=_transport()) == 0
    assert capsys.readouterr().out == ACCESS + "\n"


def test_403_is_exit_2_with_compromise_guidance(capsys):
    rc = cl.main([TOKEN], transport=_transport(403, "nope"))
    out, err = capsys.readouterr()
    assert rc == 2 and out == ""
    assert "already claimed" in err and "compromised" in err and "new setup token" in err


def test_bad_input_is_exit_1(capsys):
    assert cl.main(["!!bad!!"], transport=_transport()) == 1
    assert cl.main([base64.b64encode(b"http://insecure/claim").decode()], transport=_transport()) == 1
    assert cl.main([], transport=_transport()) == 1
    assert cl.main([TOKEN], transport=_transport(500, "boom")) == 1
    assert cl.main([TOKEN], transport=_transport(200, "not a url")) == 1
    assert capsys.readouterr().out == ""                             # nothing ever hits stdout


def test_out_file_mode_600_and_no_overwrite(tmp_path, capsys):
    path = tmp_path / "access.txt"
    assert cl.main([TOKEN, "--out", str(path)], transport=_transport()) == 0
    assert path.read_text() == ACCESS + "\n"
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert cl.main([TOKEN, "--out", str(path)], transport=_transport()) == 1
    assert path.read_text() == ACCESS + "\n"
    assert "already exists" in capsys.readouterr().err
