"""Text extraction per sniffed format. Extractors never raise: failures become
damage flags and an empty text, so every file still yields a Document."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version

from ragnarok.ingest.decoding import decode_bytes, normalise_newlines
from ragnarok.models import DamageFlag, DamageKind, DocFormat, ParserInfo

logging.getLogger("pypdf").setLevel(logging.ERROR)


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return ""


@dataclass
class Extracted:
    text: str
    format: DocFormat | None
    parser: ParserInfo
    damage: list[DamageFlag] = field(default_factory=list)
    # Text outside the body that must still be scanned for injection,
    # e.g. PDF info dictionary, DOCX core properties, headers/footers, comments.
    side_text: dict[str, str] = field(default_factory=dict)
    # Body text a human reader would not see (DOCX hidden runs).
    hidden_runs: list[str] = field(default_factory=list)


def _extract_txt(data: bytes) -> Extracted:
    d = decode_bytes(data)
    info = ParserInfo(parser="text", encoding=d.encoding, warnings=list(d.warnings))
    damage: list[DamageFlag] = []
    if d.replacements:
        damage.append(DamageFlag(kind=DamageKind.BAD_ENCODING, detail=f"{d.replacements} replacement character(s) needed ({d.encoding})"))
    if d.truncated:
        damage.append(DamageFlag(kind=DamageKind.TRUNCATED, detail="file ends inside a multi-byte character (cut off)"))
    return Extracted(text=normalise_newlines(d.text), format=DocFormat.TXT, parser=info, damage=damage)


def _extract_pdf(data: bytes) -> Extracted:
    import pypdf

    info = ParserInfo(parser="pypdf", version=_pkg_version("pypdf"))
    damage: list[DamageFlag] = []
    side: dict[str, str] = {}
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        pages: list[str] = []
        for i, page in enumerate(reader.pages):
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:  # noqa: BLE001 - a bad page must not stop the file
                pages.append("")
                damage.append(DamageFlag(kind=DamageKind.UNPARSEABLE, detail=f"page {i + 1} could not be read: {type(exc).__name__}"))
            try:
                for j, annot in enumerate(page.get("/Annots") or []):
                    obj = annot.get_object()
                    contents = obj.get("/Contents")
                    if contents:
                        side[f"pdf.page{i + 1}.annotation{j + 1}"] = str(contents)
            except Exception:  # noqa: BLE001
                info.warnings.append(f"page {i + 1} annotations unreadable")
        try:
            for k, v in (reader.metadata or {}).items():
                if v:
                    side[f"pdf.info.{str(k).lstrip('/')}"] = str(v)
        except Exception:  # noqa: BLE001
            info.warnings.append("PDF info dictionary unreadable")
        text = "\n".join(pages)
    except Exception as exc:  # noqa: BLE001
        return Extracted(
            text="", format=DocFormat.PDF, parser=info,
            damage=[DamageFlag(kind=DamageKind.UNPARSEABLE, detail=f"PDF could not be opened: {type(exc).__name__}: {str(exc)[:120]}")],
        )
    if not text.strip():
        damage.append(DamageFlag(kind=DamageKind.EMPTY, detail="PDF has no extractable text layer (OCR is not supported)"))
    return Extracted(text=normalise_newlines(text), format=DocFormat.PDF, parser=info, damage=damage, side_text=side)


def _extract_docx(data: bytes) -> Extracted:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph as DocxParagraph

    info = ParserInfo(parser="python-docx", version=_pkg_version("python-docx"))
    side: dict[str, str] = {}
    hidden: list[str] = []
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        return Extracted(
            text="", format=DocFormat.DOCX, parser=info,
            damage=[DamageFlag(kind=DamageKind.UNPARSEABLE, detail=f"DOCX could not be opened: {type(exc).__name__}: {str(exc)[:120]}")],
        )

    def para_text(p: DocxParagraph) -> str:
        for run in p.runs:
            if run.font.hidden and run.text.strip():
                hidden.append(run.text)
        return p.text

    lines: list[str] = []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append(para_text(DocxParagraph(el, d)))
        elif tag == "tbl":
            for row in Table(el, d).rows:
                lines.append(" | ".join(cell.text.strip() for cell in row.cells))
            lines.append("")
    cp = d.core_properties
    for name in ("title", "subject", "author", "keywords", "comments", "category", "last_modified_by", "identifier", "content_status"):
        v = getattr(cp, name, None)
        if v:
            side[f"docx.core.{name}"] = str(v)
    for si, section in enumerate(d.sections):
        for part_name in ("header", "footer"):
            try:
                part = getattr(section, part_name)
                t = "\n".join(p.text for p in part.paragraphs if p.text.strip())
                if t:
                    side[f"docx.section{si + 1}.{part_name}"] = t
            except Exception:  # noqa: BLE001
                info.warnings.append(f"section {si + 1} {part_name} unreadable")
    try:
        for ci, c in enumerate(getattr(d, "comments", None) or []):
            t = getattr(c, "text", "")
            if t:
                side[f"docx.comment{ci + 1}"] = t
    except Exception:  # noqa: BLE001
        info.warnings.append("comments part unreadable")
    text = "\n".join(lines)
    damage: list[DamageFlag] = []
    if not text.strip():
        damage.append(DamageFlag(kind=DamageKind.EMPTY, detail="DOCX body has no text"))
    return Extracted(text=normalise_newlines(text), format=DocFormat.DOCX, parser=info, damage=damage, side_text=side, hidden_runs=hidden)


def extract(data: bytes, sniffed: str) -> Extracted:
    """Dispatch on the sniffed format (magic bytes), never on the extension alone."""
    if sniffed == "empty":
        return Extracted(
            text="", format=None, parser=ParserInfo(parser="none"),
            damage=[DamageFlag(kind=DamageKind.EMPTY, detail="file is empty (0 bytes)")],
        )
    if sniffed == "pdf":
        return _extract_pdf(data)
    if sniffed == "docx":
        return _extract_docx(data)
    if sniffed == "zip":
        return Extracted(
            text="", format=None, parser=ParserInfo(parser="none"),
            damage=[DamageFlag(kind=DamageKind.UNPARSEABLE, detail="ZIP archive that is not a readable DOCX")],
        )
    ex = _extract_txt(data)
    # Mostly control characters => a binary file, not text.
    sample = ex.text[:4000]
    if sample:
        ctrl = sum(1 for ch in sample if ord(ch) < 32 and ch not in "\n\t")
        if ctrl / len(sample) > 0.1:
            ex.damage.append(DamageFlag(kind=DamageKind.UNPARSEABLE, detail="content looks binary, not text"))
    return ex
