"""Split a document body into paragraphs with stable refs.

Primary: the document's own `[Pn]` markers (PDF line wrapping inside a paragraph is
undone by collapsing whitespace). Fallback when no markers exist: blank-line
blocks numbered P1..Pn in order. Text before the first marker that is not the
title is kept as P0. Whitespace collapsing is the only normalisation applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ragnarok.models import DamageFlag, DamageKind, Paragraph

_MARK_LINE = re.compile(r"(?m)^[ \t]*\[P(\d+)\][ \t]*")
_MARK_ANY = re.compile(r"\[P(\d+)\][ \t]*")
_WS = re.compile(r"\s+")  # does not match zero-width characters, which injection scanning needs
_TERMINAL = tuple('.!?"\'”’)]…:;*')


def normalise_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


@dataclass
class SplitResult:
    paragraphs: list[Paragraph]
    damage: list[DamageFlag] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used_markers: bool = True


def split_paragraphs(body: str, title: str | None = None) -> SplitResult:
    marks = list(_MARK_LINE.finditer(body)) or list(_MARK_ANY.finditer(body))
    title_norm = normalise_ws(title or "").casefold()
    if not marks:
        return _split_blank_lines(body, title_norm)

    out: list[Paragraph] = []
    damage: list[DamageFlag] = []
    warnings: list[str] = []
    preamble = normalise_ws(body[: marks[0].start()])
    if preamble and preamble.casefold() != title_norm:
        out.append(Paragraph(ref="P0", ordinal=0, text=preamble))
        warnings.append("text before the first [Pn] marker kept as P0")

    numbers = [int(m.group(1)) for m in marks]
    used: set[int] = set()
    next_free = max(numbers) + 1
    for idx, m in enumerate(marks):
        n = int(m.group(1))
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(body)
        text = normalise_ws(body[m.end():end])
        ref_n = n
        if n in used:
            ref_n = next_free
            next_free += 1
            damage.append(DamageFlag(
                kind=DamageKind.MALFORMED,
                detail=f"marker [P{n}] appears more than once; later occurrence stored as P{ref_n}",
                paragraph_ref=f"P{ref_n}",
            ))
        used.add(ref_n)
        if not text:
            damage.append(DamageFlag(kind=DamageKind.MALFORMED, detail=f"[P{n}] has no text", paragraph_ref=f"P{ref_n}"))
        out.append(Paragraph(ref=f"P{ref_n}", ordinal=len(out), text=text))

    distinct = sorted(set(numbers))
    expected = list(range(distinct[0], distinct[-1] + 1)) if distinct else []
    missing = sorted(set(expected) - set(distinct))
    if missing:
        damage.append(DamageFlag(kind=DamageKind.MALFORMED, detail=f"paragraph markers missing: {', '.join(f'P{n}' for n in missing)}"))
    if distinct and distinct[0] > 1:
        damage.append(DamageFlag(kind=DamageKind.MALFORMED, detail=f"paragraph numbering starts at P{distinct[0]}"))
    if numbers != sorted(numbers):
        damage.append(DamageFlag(kind=DamageKind.MALFORMED, detail="paragraph markers are out of order"))
    return SplitResult(paragraphs=out, damage=damage, warnings=warnings, used_markers=True)


def _split_blank_lines(body: str, title_norm: str) -> SplitResult:
    blocks = [normalise_ws(b) for b in re.split(r"\n[ \t]*\n", body)]
    blocks = [b for b in blocks if b]
    if blocks and blocks[0].casefold() == title_norm:
        blocks = blocks[1:]
    paras = [Paragraph(ref=f"P{i + 1}", ordinal=i, text=b) for i, b in enumerate(blocks)]
    warnings = ["no [Pn] markers; paragraphs split on blank lines and numbered in order"] if paras else []
    return SplitResult(paragraphs=paras, warnings=warnings, used_markers=False)


def looks_cut_off(text: str, min_words: int = 4) -> bool:
    """True when a paragraph of real prose stops without closing punctuation."""
    t = text.rstrip()
    if not t or len(t.split()) < min_words:
        return False
    return not t.endswith(_TERMINAL)
