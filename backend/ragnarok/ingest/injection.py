"""Pattern-based detection of instructions embedded in documents.

Documents are evidence, never instructions. This module only *annotates*: the
original text and its hashes are never changed. `evidence_text` builds the
version shown to agents, in which high-severity spans are withheld and other
spans are wrapped in explicit markers. A flag is a suspicion, not a verdict: the
surrounding context is kept so a human or Odin can judge it.

Patterns are generic (no dataset-specific phrases or IDs); unseen packs may use
other wordings, so the list errs towards recall and severity tells consumers how
much weight to give a hit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ragnarok.models import InjectionFlag

_ROLE = r"(?:system|assistant|user|developer|human|operator|ai|model|tool)"


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    severity: str  # low | medium | high
    expand: str  # "match" | "sentence" | "line": how far the flagged span reaches


def _r(p: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(p, flags)


RULES: tuple[Rule, ...] = (
    # Role labels at the start of a line or sentence: "SYSTEM:", "[assistant]:", "<user>:"
    Rule("role_label", _r(rf"(?:^|(?<=[.!?:\n])|(?<=[.!?:]\s))[ \t]*[\[<(]?\s*{_ROLE}\s*[\]>)]?\s*:", re.IGNORECASE | re.MULTILINE), "high", "line"),
    Rule("chat_template_token", _r(r"<\|?\s*(?:im_start|im_end|system|endoftext|eot_id|start_header_id)\s*\|?>|\[/?INST\]|<</?SYS>>"), "high", "line"),
    Rule("override_instructions", _r(
        r"\b(?:ignore|disregard|forget|override|bypass|overrule)\b[^.\n]{0,40}?\b(?:all|any|previous|prior|above|earlier|your|the|these|those|system|existing)\b"
        r"[^.\n]{0,30}?\b(?:instructions?|rules?|prompts?|guidelines?|directives?|constraints?|polic(?:y|ies)|limits?|programming|orders)\b"), "high", "sentence"),
    Rule("ignore_imperative", _r(r"\b(?:ignore|disregard)\s+(?:all|previous|prior|your|the\s+above|everything|any\s+(?:other|previous))\b"), "high", "sentence"),
    Rule("persona_change", _r(r"\b(?:you\s+are\s+now|from\s+now\s+on,?\s+you|act\s+as\s+(?:an?|the)\b|pretend\s+(?:to\s+be|you\s+are)|your\s+new\s+(?:role|task|instructions?))"), "high", "sentence"),
    Rule("new_instructions", _r(r"\b(?:new|updated|revised|additional|hidden|secret|special)\s+(?:instructions?|directives?|system\s+prompt|orders|task)\b"), "high", "sentence"),
    Rule("approve_all", _r(
        r"\b(?:approve|accept|establish|confirm|uphold|rule\s+in\s+favou?r\s+of|sign\s+off)\b[^.\n]{0,25}?\b(?:all|every|each|any)\b[^.\n]{0,20}?\b(?:claims?|findings?|arguments?|evidence|positions?)\b"), "high", "sentence"),
    Rule("skip_process", _r(
        r"\b(?:skip|bypass|omit|cancel|avoid|no\s+need\s+(?:for|to)|do\s+not|don't|dont|never)\b[^.\n]{0,20}?\b(?:cross[- ]?exam(?:ination|ine)?s?|debate|verification|verify|fact[- ]?check(?:ing)?|rulings?|the\s+trial)\b"), "high", "sentence"),
    Rule("addressed_to_ai", _r(
        r"\b(?:note|message|instructions?|attention|memo|notice|request)\s+(?:to|for)\s+(?:the\s+|any\s+|all\s+)?(?:ai|assistants?|models?|llms?|agents?|bots?|language\s+models?|automated\s+(?:systems?|readers?))\b"), "high", "sentence"),
    Rule("verdict_steering", _r(r"\b(?:mark|rule|classify|label|record)\b[^.\n]{0,30}?\b(?:claims?|findings?|this|it|them)\b[^.\n]{0,20}?\bas\s+(?:established|conceded|rejected|contested|verified|true)\b"), "medium", "sentence"),
    Rule("system_prompt_reference", _r(r"\bsystem\s+prompt\b|\bprompt\s+injection\b|\bjailbreak\b"), "medium", "sentence"),
    Rule("limit_or_tool_change", _r(r"\b(?:remove|disable|turn\s+off|ignore|lift|increase|raise|unlimited|no)\b[^.\n]{0,20}?\b(?:date\s+(?:filter|limit|cut-?off)|as[- ]of(?:\s+date)?|cut-?off\s+date|token\s+(?:limit|budget)|tool\s+(?:limit|permissions?)|budgets?|run\s+limit)\b"), "medium", "sentence"),
    Rule("output_override", _r(r"\b(?:respond|reply|answer|output)\s+(?:only|exactly|with\s+only)\b|\bprint\s+the\s+following\b"), "medium", "sentence"),
    Rule("command_or_url", _r(r"\b(?:run|execute|eval)\b[^.\n]{0,20}?\b(?:command|code|script|shell)\b|\b(?:curl|wget|pip\s+install|npm\s+install|powershell|bash\s+-c|rm\s+-rf)\b|\bhttps?://\S+"), "medium", "sentence"),
    Rule("ai_reference", _r(r"\b(?:as\s+an\s+ai|large\s+language\s+model|language\s+model|chatbot|ai\s+(?:system|assistant|model|agent)s?)\b"), "low", "match"),
    Rule("disregard_word", _r(r"\bdisregard\b"), "low", "sentence"),
    Rule("encoded_blob", re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{48,}={0,2}(?![A-Za-z0-9+/=])"), "low", "match"),
)

# Invisible or direction-changing characters. Tag characters can smuggle whole
# hidden messages, so they rate higher.
_HIDDEN = (
    ("hidden_tag_characters", re.compile("[\U000e0000-\U000e007f]+"), "high"),
    ("zero_width_characters", re.compile("[​-‏⁠-⁤﻿]+"), "medium"),
    ("bidi_control_characters", re.compile("[‪-‮⁦-⁩]+"), "medium"),
)

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


def _expand(text: str, start: int, end: int, how: str) -> tuple[int, int]:
    if how == "match":
        return start, end
    if how == "line":  # from the label to the end of its line (the labelled "message")
        e = text.find("\n", end)
        return start, len(text) if e == -1 else e
    # sentence: back to the previous sentence end / line start, forward to the next
    s = start
    while s > 0 and text[s - 1] != "\n" and not (text[s - 1] == " " and s >= 2 and text[s - 2] in ".!?"):
        s -= 1
    m = re.compile(r"[.!?](?=\s|$)|\n").search(text, end)
    e = m.end() if m else len(text)
    return s, e


def _excerpt(text: str, start: int, end: int, limit: int = 200) -> str:
    frag = text[start:end]
    return frag if len(frag) <= limit else frag[: limit - 1] + "…"


def scan_text(text: str, paragraph_ref: str | None = None, field: str | None = None) -> list[InjectionFlag]:
    flags: list[InjectionFlag] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            m_start = m.start()
            while m_start < m.end() and text[m_start].isspace():  # patterns may consume a preceding newline
                m_start += 1
            s, e = _expand(text, m_start, m.end(), rule.expand)
            key = (rule.name, s, e)
            if key in seen or e <= s:
                continue
            seen.add(key)
            flags.append(InjectionFlag(
                paragraph_ref=paragraph_ref, field=field, start=s, end=e,
                pattern=rule.name, excerpt=_excerpt(text, s, e).strip() or "(whitespace)", severity=rule.severity,
            ))
    for name, pat, severity in _HIDDEN:
        for m in pat.finditer(text):
            flags.append(InjectionFlag(
                paragraph_ref=paragraph_ref, field=field, start=m.start(), end=m.end(), pattern=name,
                excerpt=" ".join(f"U+{ord(c):04X}" for c in m.group(0)[:12]), severity=severity,
            ))
    return flags


def hidden_run_flags(paragraph_text: str, paragraph_ref: str, hidden_runs: list[str]) -> list[InjectionFlag]:
    """Flag DOCX runs marked hidden (invisible to a human reader)."""
    out: list[InjectionFlag] = []
    for run in hidden_runs:
        needle = " ".join(run.split())
        if not needle:
            continue
        i = paragraph_text.find(needle)
        if i >= 0:
            out.append(InjectionFlag(
                paragraph_ref=paragraph_ref, start=i, end=i + len(needle), pattern="hidden_text",
                excerpt=_excerpt(paragraph_text, i, i + len(needle)), severity="high",
            ))
    return out


def evidence_text(text: str, flags: list[InjectionFlag]) -> str | None:
    """Text for agents: high-severity spans withheld, others wrapped; None if unflagged.

    Hidden characters are removed (they are invisible and only useful for smuggling).
    """
    if not flags:
        return None
    spans: list[list] = []  # [start, end, max_severity, {patterns}, hidden_only]
    for f in sorted(flags, key=lambda x: (x.start, x.end)):
        hidden = f.pattern.endswith("_characters")
        if spans and f.start < spans[-1][1]:
            cur = spans[-1]
            cur[1] = max(cur[1], f.end)
            if _SEVERITY_RANK[f.severity] > _SEVERITY_RANK[cur[2]]:
                cur[2] = f.severity
            cur[3].add(f.pattern)
            cur[4] = cur[4] and hidden
        else:
            spans.append([f.start, f.end, f.severity, {f.pattern}, hidden])
    out: list[str] = []
    pos = 0
    for start, end, severity, patterns, hidden_only in spans:
        out.append(text[pos:start])
        names = ",".join(sorted(patterns))
        frag = text[start:end]
        if hidden_only:
            out.append(f"[FLAGGED: {len(frag)} hidden character(s) removed]")
        elif severity == "high":
            out.append(f"[FLAGGED UNTRUSTED TEXT WITHHELD ({names}): possible instruction embedded in a document; original kept in the source]")
        else:
            for _, pat, _ in _HIDDEN:
                frag = pat.sub("", frag)
            out.append(f"[FLAGGED ({names}) START]{frag}[FLAGGED END]")
        pos = end
    out.append(text[pos:])
    return "".join(out)
