"""Format sniffing (magic bytes) and tolerant text decoding.

Decoding order for text files: BOM -> mid-file BOM (header and body in different
encodings) -> strict UTF-8 -> BOM-less UTF-16 LE/BE (NUL-byte pattern) ->
detected encoding (strict cp1252 for mostly-ASCII text, else the
charset-normalizer guess) -> cp1252 with replacement characters. The encoding used
is always recorded; replacement characters mean the text is flagged bad_encoding
by the caller.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from charset_normalizer import from_bytes

# Longest BOMs first so UTF-32 LE is not mistaken for UTF-16 LE.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)
_UTF16_BOMS: tuple[tuple[bytes, str], ...] = ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))


def sniff_format(data: bytes) -> str:
    """Return 'empty', 'pdf', 'docx', 'zip' (non-DOCX archive) or 'text'."""
    if not data:
        return "empty"
    head = data[:1024].lstrip(b"\xef\xbb\xbf\r\n\t ")
    if head.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                return "docx" if "word/document.xml" in zf.namelist() else "zip"
        except zipfile.BadZipFile:
            return "zip"
    return "text"


@dataclass
class Decoded:
    text: str
    encoding: str
    replacements: int = 0  # U+FFFD characters introduced or present
    truncated: bool = False  # a multi-byte sequence was cut off at the end
    warnings: list[str] = field(default_factory=list)


def _unit_size(encoding: str) -> int:
    return 4 if "32" in encoding else 2 if "16" in encoding else 1


def _decode_unicode(data: bytes, encoding: str) -> Decoded:
    """Decode a BOM-less byte run in a known Unicode encoding."""
    warnings: list[str] = []
    truncated = False
    unit = _unit_size(encoding)
    extra = len(data) % unit
    if extra:
        data = data[: len(data) - extra]
        truncated = True
        warnings.append(f"{encoding} data has {extra} trailing byte(s) that do not form a character (cut off)")
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as exc:
        text = data.decode(encoding, errors="replace")
        warnings.append(f"{encoding} decode errors replaced ({exc.reason})")
    return Decoded(text=text, encoding=encoding, replacements=text.count("�"), truncated=truncated, warnings=warnings)


def _looks_utf16(data: bytes) -> str | None:
    """Detect BOM-less UTF-16 from the NUL-byte pattern of mostly-ASCII text."""
    if len(data) < 4:
        return None
    sample = data[:4096]
    even = sample[0::2]
    odd = sample[1::2]
    zeros_even = even.count(0) / max(len(even), 1)
    zeros_odd = odd.count(0) / max(len(odd), 1)
    if zeros_odd > 0.4 and zeros_even < 0.05:
        return "utf-16-le"
    if zeros_even > 0.4 and zeros_odd < 0.05:
        return "utf-16-be"
    return None


def _find_mid_bom(data: bytes) -> tuple[int, int, str] | None:
    """A UTF-16 BOM after offset 0 whose tail really looks like UTF-16 text.

    0xFF/0xFE never occur in valid UTF-8, so this is a strong signal that a file
    switches encoding (e.g. an ASCII header followed by a UTF-16 body).
    """
    best: tuple[int, int, str] | None = None
    for bom, enc in _UTF16_BOMS:
        i = data.find(bom, 1)
        if i > 0 and _looks_utf16(data[i + len(bom):]) == enc and (best is None or i < best[0]):
            best = (i, len(bom), enc)
    return best


def _decode_plain(data: bytes) -> Decoded:
    """Decode bytes that have no BOM."""
    enc16 = _looks_utf16(data)
    try:
        text = data.decode("utf-8")
        # NUL bytes are legal UTF-8, so BOM-less UTF-16 ASCII text "decodes";
        # with a UTF-16 NUL pattern that is not a real UTF-8 success.
        if not (enc16 and "\x00" in text):
            return Decoded(text=text, encoding="utf-8")
    except UnicodeDecodeError:
        pass
    if enc16:
        d = _decode_unicode(data, enc16)
        d.warnings.insert(0, f"no BOM; {enc16} detected from NUL-byte pattern")
        return d
    best = from_bytes(data).best()
    guess = best.encoding if best is not None else None
    # charset-normalizer is unreliable on short, mostly-ASCII text (it can pick
    # e.g. mac_latin2 for a few accented letters and silently change them).
    # Mostly-ASCII text that is valid cp1252 is read as cp1252, the common
    # Western single-byte encoding; the guess is recorded for transparency.
    ascii_ratio = sum(1 for b in data if b < 0x80) / len(data)
    if ascii_ratio >= 0.9:
        try:
            text = data.decode("cp1252")
            note = f"not UTF-8; mostly-ASCII text read as cp1252 (charset-normalizer suggested {guess})"
            return Decoded(text=text, encoding="cp1252", warnings=[note])
        except UnicodeDecodeError:
            pass
    if best is not None and best.encoding:
        try:
            text = data.decode(best.encoding)
            return Decoded(text=text, encoding=best.encoding, warnings=[f"encoding guessed by charset-normalizer: {best.encoding}"])
        except (UnicodeDecodeError, LookupError):
            pass
    text = data.decode("cp1252", errors="replace")
    return Decoded(
        text=text,
        encoding="cp1252",
        replacements=text.count("�"),
        warnings=["fell back to cp1252 with replacement characters"],
    )


def decode_bytes(data: bytes) -> Decoded:
    if not data:
        return Decoded(text="", encoding="empty")
    for bom, enc in _BOMS:
        if data.startswith(bom):
            d = _decode_unicode(data[len(bom):], enc)
            d.encoding = f"{enc} (BOM)"
            return d
    mid = _find_mid_bom(data)
    if mid is not None:
        pos, bom_len, enc = mid
        head = _decode_plain(data[:pos])
        tail = _decode_unicode(data[pos + bom_len:], enc)
        return Decoded(
            text=head.text + tail.text,
            encoding=f"{head.encoding}+{enc}",
            replacements=head.replacements + tail.replacements,
            truncated=tail.truncated,
            warnings=[f"mixed encodings: bytes 0..{pos} as {head.encoding}, then {enc} after a BOM at byte {pos}"]
            + head.warnings
            + tail.warnings,
        )
    d = _decode_plain(data)
    d.replacements = max(d.replacements, d.text.count("�"))
    return d


def normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
