#!/usr/bin/env python3
"""Generate ignored local-only SAMPLE-001 compose credentials."""

from __future__ import annotations

import base64
import argparse
import secrets
import subprocess
import tempfile
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / ".env.local"
PASSWORD_NAMES = (
    "POSTGRES_PASSWORD",
    "BFF_DB_PASSWORD",
    "API_DB_PASSWORD",
    "SCANNER_DB_PASSWORD",
    "PROMOTION_DB_PASSWORD",
    "DELETION_DB_PASSWORD",
)


def token(bytes_: int = 32) -> str:
    return base64.b64encode(secrets.token_bytes(bytes_)).decode("ascii")


def url_token(bytes_: int = 32) -> str:
    return secrets.token_urlsafe(bytes_)


def parse_existing(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name] = value
    return values


def add_encoded_passwords(values: dict[str, str]) -> dict[str, str]:
    updated = dict(values)
    for name in PASSWORD_NAMES:
        updated[f"{name}_URLENCODED"] = urllib.parse.quote(updated[name], safe="")
    return updated


def ed25519_pair() -> tuple[str, str]:
    source = r'''
package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"fmt"
)

func main() {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		panic(err)
	}
	fmt.Println(base64.StdEncoding.EncodeToString(private))
	fmt.Println(base64.StdEncoding.EncodeToString(public))
}
'''
    with tempfile.TemporaryDirectory(prefix="sample001-env-") as directory:
        main = Path(directory) / "main.go"
        main.write_text(source, encoding="utf-8")
        result = subprocess.run(
            ["go", "run", str(main)],
            check=True,
            capture_output=True,
            text=True,
        )
    private_key, public_key = result.stdout.strip().splitlines()
    return private_key, public_key


def build_values(preserve_existing: bool) -> dict[str, str]:
    existing = parse_existing(OUTPUT) if preserve_existing else {}
    private_key, public_key = (
        (existing["ASSERTION_PRIVATE_KEY"], existing["ASSERTION_PUBLIC_KEY"])
        if "ASSERTION_PRIVATE_KEY" in existing and "ASSERTION_PUBLIC_KEY" in existing
        else ed25519_pair()
    )
    values = {
        "POSTGRES_PASSWORD": existing.get("POSTGRES_PASSWORD", url_token()),
        "BFF_DB_PASSWORD": existing.get("BFF_DB_PASSWORD", url_token()),
        "API_DB_PASSWORD": existing.get("API_DB_PASSWORD", url_token()),
        "SCANNER_DB_PASSWORD": existing.get("SCANNER_DB_PASSWORD", url_token()),
        "PROMOTION_DB_PASSWORD": existing.get("PROMOTION_DB_PASSWORD", url_token()),
        "DELETION_DB_PASSWORD": existing.get("DELETION_DB_PASSWORD", url_token()),
        "SESSION_ENCRYPTION_KEY": existing.get("SESSION_ENCRYPTION_KEY", token()),
        "ASSERTION_PRIVATE_KEY": private_key,
        "ASSERTION_PUBLIC_KEY": public_key,
        "OIDC_CLIENT_SECRET": existing.get("OIDC_CLIENT_SECRET", token()),
    }
    return add_encoded_passwords(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ignored local-only SAMPLE-001 compose credentials.")
    parser.add_argument("--preserve-existing", action="store_true", help="Keep existing credential values and refresh derived fields.")
    args = parser.parse_args()
    values = build_values(args.preserve_existing)
    lines = [
        "# Generated local/demo credentials. Do not commit this file.",
        *[f"{name}={value}" for name, value in values.items()],
        "",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
