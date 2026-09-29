"""Deterministic prompt-injection detector.

Pipeline: unicode normalization -> remove invisible/control chars -> split into
segments (sentences/lines) -> score each segment with several independent
signals (pattern families + a lexical imperative/target heuristic).

The detector works per segment so the sanitizer can neutralize only the
malicious span and keep the legitimate content of the document.
"""

import re
import unicodedata
from dataclasses import dataclass

from domain.models.document import InjectionFinding

# Zero-width / bidi / BOM characters used to hide instructions from humans.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿­]")
# A segment ends at .!? followed by whitespace (so "500.000" is not split) or at end of line.
SEGMENT_PATTERN = re.compile(r"[^\n]+?(?:[.!?]+(?=\s)|[.!?]*$)", re.M)

# (name, weight, regex over accent-folded lowercase text)
_PATTERN_FAMILIES: tuple[tuple[str, float, re.Pattern[str]], ...] = tuple(
    (name, weight, re.compile(rx))
    for name, weight, rx in (
        ("ignore_previous_instructions", 0.9,
         r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|all|any)\b.{0,25}"
         r"\b(instructions?|rules?|prompts?|directions?|guidelines?)\b"),
        ("ignore_previous_instructions", 0.9,
         r"\b(ignora\w*|olvida\w*|omite|omitir|descarta\w*|desobedece\w*)\b.{0,40}"
         r"\b(instrucciones|reglas|indicaciones|normas|directrices|prompt)\b"),
        ("reveal_system_prompt", 0.9,
         r"\b(reveal|show|print|display|leak|output|repeat|muestra\w*|revela\w*|imprime|ensena\w*|"
         r"repite)\b.{0,30}\b(system prompt|prompt del sistema|system message|mensaje del sistema|"
         r"instrucciones del sistema|hidden (context|instructions)|contexto oculto|initial prompt)"),
        ("request_all_documents", 0.8,
         r"\b(show|list|return|dump|give|print|muestra\w*|lista\w*|devuelve|entrega\w*|dame|imprime)"
         r"\b.{0,20}\b(all|every|todos|todas)\b.{0,25}\b(documents?|documentos?|files|archivos|"
         r"registros|records|datos|data)\b"),
        ("override_instructions", 0.85,
         r"\b(override|overwrite|replace|sobrescrib\w*|anula\w*|reemplaza\w*|cambia\w*)\b.{0,30}"
         r"\b(instructions?|rules?|instrucciones|reglas|politicas?|policies|permisos?|permissions?|"
         r"filtros?|filters?)\b"),
        ("bypass_restrictions", 0.85,
         r"\b(bypass|circumvent|evade|disable|evita\w*|salta\w*|elud\w*|desactiva\w*)\b.{0,30}"
         r"\b(restrictions?|filters?|security|guardrails?|controls?|restricciones|filtros|seguridad|"
         r"controles)\b"),
        ("tool_invocation", 0.8,
         r"\b(execute|call|invoke|run|use|ejecuta\w*|llama\w*|invoca\w*|usa|utiliza)\b.{0,25}"
         r"\b(tools?|functions?|herramientas?|funcion\w*|get_employee_permissions|mcp_\w+)\b"),
        ("role_manipulation", 0.7,
         r"\b(you are now|act as|pretend to be|ahora eres|actua como|a partir de ahora eres|"
         r"new instructions|nuevas instrucciones|developer mode|modo desarrollador|jailbreak)\b"),
        ("privilege_escalation", 0.7,
         r"(\b(role|rol)\s*[:=]\s*[\"']?admin\b|\bas an? (admin|administrator)\b|"
         r"\bcomo administrador\b|\barea_filter\b|\bclassification_filter\b)"),
        ("fake_role_marker", 0.6,
         r"(^|\s)(system|assistant|developer)\s*:|</?\s*(system|untrusted_documents|document)\b"),
    )
)

# Second, independent signal: imperative verb + security-sensitive target.
_IMPERATIVE_VERBS = frozenset(
    "ignora ignore olvida forget omite muestra show revela reveal ejecuta execute "
    "desactiva disable bypass evita override anula imprime print dump devuelve".split()
)
_SENSITIVE_TARGETS = frozenset(
    "instrucciones instructions reglas rules prompt sistema system documentos documents "
    "permisos permissions herramientas tools filtros filters seguridad security "
    "credenciales credentials contrasena password".split()
)
_HEURISTIC_WEIGHT = 0.4


@dataclass(frozen=True)
class SegmentFinding:
    start: int
    end: int
    score: float
    patterns: tuple[str, ...]


def normalize(text: str) -> str:
    """NFKC normalization + removal of invisible and control characters."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    return "".join(
        ch for ch in text
        if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf")
    )


def _fold(text: str) -> str:
    """Lowercase and strip accents so 'ignorá'/'IGNORA' match 'ignora'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _combine(weights: list[float]) -> float:
    """Noisy-OR: independent signals reinforce each other, capped at 1."""
    remaining = 1.0
    for weight in weights:
        remaining *= 1.0 - weight
    return round(1.0 - remaining, 3)


class InjectionDetector:
    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold

    def scan_segments(self, normalized_text: str) -> list[SegmentFinding]:
        findings: list[SegmentFinding] = []
        for match in SEGMENT_PATTERN.finditer(normalized_text):
            raw = match.group()
            stripped = raw.strip()
            if not stripped:
                continue
            start = match.start() + (len(raw) - len(raw.lstrip()))
            folded = _fold(stripped)

            patterns: list[str] = []
            weights: list[float] = []
            for name, weight, regex in _PATTERN_FAMILIES:
                if regex.search(folded) and name not in patterns:
                    patterns.append(name)
                    weights.append(weight)

            tokens = set(re.findall(r"[a-z_]+", folded))
            if tokens & _IMPERATIVE_VERBS and tokens & _SENSITIVE_TARGETS:
                patterns.append("imperative_directive")
                weights.append(_HEURISTIC_WEIGHT)

            score = _combine(weights)
            if score >= self.threshold:
                findings.append(SegmentFinding(start, start + len(stripped), score, tuple(patterns)))
        return findings

    def detect(self, text: str) -> InjectionFinding:
        return self.summarize(self.scan_segments(normalize(text)))

    @staticmethod
    def summarize(segments: list[SegmentFinding]) -> InjectionFinding:
        if not segments:
            return InjectionFinding(detected=False, score=0.0)
        patterns = sorted({p for s in segments for p in s.patterns})
        return InjectionFinding(
            detected=True,
            score=max(s.score for s in segments),
            matched_patterns=tuple(patterns),
        )
