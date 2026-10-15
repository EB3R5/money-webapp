"""A test client over django.test.Client that speaks the call shape the suite was written
in against httpx (`client.post(path, json=...)`, `data=`, `files=`, `content=`, `headers=`,
`params=`, `follow_redirects=`; responses with `.status_code`, `.headers`, `.text`,
`.content`, `.json()`, `.cookies`, `.url`), so a ported test body changes only by losing
its `await`s. Redirects are not followed unless asked, as with httpx."""

from __future__ import annotations

import json as _json
from urllib.parse import urlencode

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.client import MULTIPART_CONTENT


class Response:
    def __init__(self, raw):
        self._raw = raw
        self.status_code = raw.status_code
        self.headers = _Headers(raw)
        self.content = b"".join(raw.streaming_content) if raw.streaming else raw.content
        self.url = raw.get("Location", "")

    @property
    def text(self) -> str:
        return self.content.decode(self._raw.charset or "utf-8", errors="replace")

    def json(self):
        return _json.loads(self.content)

    @property
    def cookies(self) -> dict:
        return {k: v.value for k, v in self._raw.cookies.items()}


class _Headers:
    """Case-insensitive read access over the response headers."""

    def __init__(self, raw):
        self._raw = raw

    def __getitem__(self, key):
        v = self._raw.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __contains__(self, key):
        return self._raw.has_header(key)

    def get(self, key, default=None):
        return self._raw.get(key, default)

    def get_list(self, key):
        """httpx's multi-value read; a Django response holds one value per header."""
        v = self._raw.get(key)
        return [v] if v is not None else []

    def items(self):
        return self._raw.items()


class WebClient:
    def __init__(self, *, enforce_csrf_checks: bool = False, follow_redirects: bool = False, **kw):
        self._c = Client(enforce_csrf_checks=enforce_csrf_checks, raise_request_exception=False, **kw)
        self._follow = follow_redirects

    @property
    def django(self) -> Client:
        return self._c

    def _call(self, method, path, *, params=None, headers=None, follow_redirects=None, **kw):
        if params:
            path = f"{path}{'&' if '?' in path else '?'}{urlencode(params, doseq=True)}"
        follow = self._follow if follow_redirects is None else follow_redirects
        raw = getattr(self._c, method)(path, headers=headers or {}, follow=follow, **kw)
        return Response(raw)

    def get(self, path, **kw):
        return self._call("get", path, **kw)

    def post(self, path, *, json=None, data=None, files=None, content=None, headers=None, **kw):
        headers = dict(headers or {})
        if json is not None:
            body, ctype = _json.dumps(json), "application/json"
        elif files is not None:
            # Django's client encodes the multipart body itself from a dict; a field named
            # more than once (several files under "files") becomes a list of uploads.
            form: dict = dict(data or {})
            pairs = files.items() if isinstance(files, dict) else files
            for field, spec in pairs:
                if isinstance(spec, tuple):
                    name, payload, *ct = spec
                    upload = SimpleUploadedFile(name, payload, content_type=ct[0] if ct else "application/octet-stream")
                else:
                    upload = SimpleUploadedFile(field, spec)
                if field in form:
                    form[field] = [*(form[field] if isinstance(form[field], list) else [form[field]]), upload]
                else:
                    form[field] = upload
            body, ctype = form, MULTIPART_CONTENT
        elif data is not None:
            body, ctype = urlencode(data, doseq=True), "application/x-www-form-urlencoded"
        elif content is not None:
            body = content
            ctype = headers.pop("content-type", None) or headers.pop("Content-Type", None) or "application/octet-stream"
        else:
            body, ctype = b"", "application/x-www-form-urlencoded"
        ctype = headers.pop("content-type", None) or headers.pop("Content-Type", None) or ctype
        return self._call("post", path, data=body, content_type=ctype, headers=headers, **kw)

    def put(self, path, **kw):
        return self._call("put", path, **kw)

    def delete(self, path, **kw):
        return self._call("delete", path, **kw)
