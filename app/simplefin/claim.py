"""One-time claim: turn a SimpleFIN setup token into the Access URL.

    python -m app.simplefin.claim [--stdin] [--out PATH] [SETUP_TOKEN]

The setup token is base64 of a claim URL; POSTing it once returns the Access URL. Only
the Access URL goes to stdout (pipe it into your secrets manager); everything else goes
to stderr. A 403 means the token was already claimed: treat it as compromised, revoke the
app in Bridge, and create a new setup token. No logging is configured here on purpose."""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import sys
from urllib.parse import urlsplit

import httpx

EXIT_BAD_INPUT = 1
EXIT_ALREADY_CLAIMED = 2


def decode_setup_token(token: str) -> str:
    """base64 setup token → https claim URL; ValueError on anything else."""
    raw = (token or "").strip()
    if not raw:
        raise ValueError("empty setup token")
    try:
        url = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=False).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as e:
        raise ValueError("setup token is not valid base64") from e
    url = url.strip()
    if urlsplit(url).scheme != "https":
        raise ValueError("claim URL must be https")
    return url


def claim(claim_url: str, *, transport=None, timeout: float = 30.0) -> str:
    """POST the claim; returns the Access URL. Raises PermissionError on 403, RuntimeError
    on any other failure (status only, never the body)."""
    with httpx.Client(timeout=timeout, transport=transport, follow_redirects=False) as c:
        try:
            r = c.post(claim_url, content=b"")
        except httpx.HTTPError as e:
            raise RuntimeError(f"claim request failed: {type(e).__name__}") from None
    if r.status_code == 403:
        raise PermissionError("token already claimed")
    if r.status_code >= 400:
        raise RuntimeError(f"claim returned HTTP {r.status_code}")
    access_url = r.text.strip()
    if urlsplit(access_url).scheme != "https" or "@" not in urlsplit(access_url).netloc:
        raise RuntimeError("claim response is not an https access URL")
    return access_url


def write_out(path: str, access_url: str) -> None:
    """Create `path` with mode 600, refusing to overwrite."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(access_url + "\n")


def main(argv=None, *, transport=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.simplefin.claim", description=__doc__.split("\n\n")[0])
    ap.add_argument("token", nargs="?", help="the setup token (or use --stdin)")
    ap.add_argument("--stdin", action="store_true", help="read the setup token from stdin")
    ap.add_argument("--out", metavar="PATH", help="also write the access URL to PATH (mode 600, no overwrite)")
    args = ap.parse_args(argv)
    err = sys.stderr

    token = sys.stdin.read() if args.stdin else (args.token or "")
    if not token.strip():
        print("error: give the setup token as an argument or via --stdin", file=err)
        return EXIT_BAD_INPUT
    try:
        claim_url = decode_setup_token(token)
    except ValueError as e:
        print(f"error: {e}", file=err)
        return EXIT_BAD_INPUT
    try:
        access_url = claim(claim_url, transport=transport)
    except PermissionError:
        print("error: token already claimed (403). Treat it as compromised: revoke the app in "
              "SimpleFIN Bridge and create a new setup token.", file=err)
        return EXIT_ALREADY_CLAIMED
    except RuntimeError as e:
        print(f"error: {e}", file=err)
        return EXIT_BAD_INPUT
    if args.out:
        try:
            write_out(args.out, access_url)
        except FileExistsError:
            print(f"error: {args.out} already exists; not overwriting", file=err)
            return EXIT_BAD_INPUT
        print(f"wrote {args.out} (mode 600)", file=err)
    print("Claimed. Store the access URL as SIMPLEFIN_ACCESS_URL (e.g. `doppler secrets set` "
          "or your .env); it is a read-only credential for every linked bank.", file=err)
    print(access_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
