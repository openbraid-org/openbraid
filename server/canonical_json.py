"""Canonical JSON serialization for byte-equivalent round-trip.

Phase E E5. An orgdef .opencatalog stored in Postgres JSONB loses
incidental formatting (whitespace, key order may shift, etc). To make
the openbraid claim "byte-equivalent round-trip" meaningful, we
serialize both upload and export via the same canonical-JSON form:

  - keys sorted lexicographically
  - compact separators (no spaces after `,` or `:`)
  - `ensure_ascii=False` (UTF-8 multibyte chars on the wire)
  - UTF-8 byte encoding

Two artifacts that serialize to the same canonical bytes are
substantively equivalent for OAGP-family export purposes. The SHA-256
of the canonical bytes is the integrity hash we publish in the
`X-Content-SHA256` header on the export endpoint and verify in
round-trip tests.
"""

from __future__ import annotations

import hashlib
import json


def canonicalize(content) -> bytes:
    """Return the canonical UTF-8 bytes for `content`.

    Stable under any JSONB round-trip: two artifacts that differ only
    in key order or whitespace serialize identically.
    """
    return json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(content) -> str:
    """Return the lowercase hex SHA-256 of `canonicalize(content)`."""
    return hashlib.sha256(canonicalize(content)).hexdigest()
