#!/usr/bin/env python3
"""Generate ignored local-only SAMPLE-001 compose credentials."""

from __future__ import annotations

import base64
import secrets
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / ".env.local"


def token(bytes_: int = 32) -> str:
    return base64.b64encode(secrets.token_bytes(bytes_)).decode("ascii")


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


def main() -> None:
    private_key, public_key = ed25519_pair()
    values = {
        "POSTGRES_PASSWORD": token(),
        "BFF_DB_PASSWORD": token(),
        "API_DB_PASSWORD": token(),
        "SCANNER_DB_PASSWORD": token(),
        "PROMOTION_DB_PASSWORD": token(),
        "DELETION_DB_PASSWORD": token(),
        "SESSION_ENCRYPTION_KEY": token(),
        "ASSERTION_PRIVATE_KEY": private_key,
        "ASSERTION_PUBLIC_KEY": public_key,
        "OIDC_CLIENT_SECRET": token(),
    }
    lines = [
        "# Generated local/demo credentials. Do not commit this file.",
        *[f"{name}={value}" for name, value in values.items()],
        "",
    ]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
