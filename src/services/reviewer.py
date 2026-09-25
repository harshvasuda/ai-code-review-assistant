"""
reviewer.py — Core code-review engine.

Architecture
------------
analyze_code_or_diff()
  └─ _run_rule_based_checks()   ← pattern-matching rules (always active)
  └─ _call_llm()                ← LLM hook (active when LLM_API_KEY is set)
       ├─ _call_openai()
       ├─ _call_watsonx()
       └─ _call_anthropic()

The rule-based engine runs unconditionally and returns structured
ReviewFinding objects.  The LLM hook is a clean integration point: when
no API key is configured it returns an empty list so the service still
works out-of-the-box during local development.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"


@dataclass
class ReviewFinding:
    severity: Severity
    message: str
    line: Optional[int] = None
    category: str = "general"


@dataclass
class ReviewResult:
    review_id: str
    findings: list[ReviewFinding]
    summary: str
    score: int                        # 1 (worst) – 10 (best)
    language: str


# ---------------------------------------------------------------------------
# Rule catalogue
# ---------------------------------------------------------------------------

# Each rule is (category, severity, pattern, message_template).
# `pattern` is compiled against every non-empty line of the input.
# Use (?i) inline flags for case-insensitive matching.
_LINE_RULES: list[tuple[str, Severity, re.Pattern[str], str]] = [
    # ── Security ───────────────────────────────────────────────────────────
    (
        "security",
        Severity.error,
        re.compile(r'(?i)(password|secret|token|api_?key)\s*=\s*["\'][^"\']{4,}["\']'),
        "Possible hardcoded secret detected. Use environment variables instead.",
    ),
    (
        "security",
        Severity.error,
        re.compile(r'(?i)SELECT\s.+\s+FROM\s.+\s+WHERE\s.+["\']?\s*\+'),
        "Possible SQL injection: string concatenation inside a query. Use parameterised queries.",
    ),
    (
        "security",
        Severity.warning,
        re.compile(r'(?i)eval\s*\('),
        "Use of eval() is a security risk; prefer safer alternatives.",
    ),
    (
        "security",
        Severity.warning,
        re.compile(r'(?i)subprocess\.(call|run|Popen)\s*\(.+shell\s*=\s*True'),
        "shell=True in subprocess is a command-injection risk. Pass a list of args instead.",
    ),
    (
        "security",
        Severity.warning,
        re.compile(r'(?i)pickle\.(loads?|dumps?)\s*\('),
        "pickle deserialisation of untrusted data can execute arbitrary code.",
    ),
    # ── Bugs / edge-cases ─────────────────────────────────────────────────
    (
        "bug",
        Severity.error,
        re.compile(r'except\s*:'),
        "Bare except clause catches all exceptions including SystemExit/KeyboardInterrupt. Specify exception types.",
    ),
    (
        "bug",
        Severity.warning,
        re.compile(r'==\s*None|None\s*=='),
        "Use 'is None' / 'is not None' for None comparisons (PEP 8 E711).",
    ),
    (
        "bug",
        Severity.warning,
        re.compile(r'==\s*True|True\s*==|==\s*False|False\s*=='),
        "Use 'if x:' / 'if not x:' instead of comparing to True/False (PEP 8 E712).",
    ),
    (
        "bug",
        Severity.warning,
        re.compile(r'def\s+\w+\s*\(.*=\s*\['),
        "Mutable default argument (list). Use None as default and initialise inside the function.",
    ),
    (
        "bug",
        Severity.warning,
        re.compile(r'def\s+\w+\s*\(.*=\s*\{'),
        "Mutable default argument (dict). Use None as default and initialise inside the function.",
    ),
    # ── Code quality ──────────────────────────────────────────────────────
    (
        "quality",
        Severity.info,
        re.compile(r'print\s*\('),
        "print() found. Consider using a proper logging library (e.g. logging.getLogger).",
    ),
    (
        "quality",
        Severity.info,
        re.compile(r'#\s*TODO|#\s*FIXME|#\s*HACK|#\s*XXX'),
        "Unresolved TODO/FIXME/HACK comment. Track this in your issue tracker before merging.",
    ),
    (
        "quality",
        Severity.info,
        re.compile(r'(?i)^\s*(pass)\s*$'),
        "Empty block (pass). Verify this is intentional; consider raising NotImplementedError.",
    ),
    # ── Readability ───────────────────────────────────────────────────────
    (
        "readability",
        Severity.info,
        re.compile(r'^\s{0,}(.{121,})$'),
        "Line exceeds 120 characters. Consider breaking it up for readability.",
    ),
]

# Whole-file (multi-line) rules: (category, severity, pattern, message).
_FILE_RULES: list[tuple[str, Severity, re.Pattern[str], str]] = [
    (
        "quality",
        Severity.warning,
        re.compile(r'^def |^class ', re.MULTILINE),
        # This rule is checked specially — see _run_rule_based_checks
        "__MISSING_DOCSTRINGS__",
    ),
]


# ---------------------------------------------------------------------------
# Rule-based engine
# ---------------------------------------------------------------------------

def _run_rule_based_checks(text: str) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    lines = text.splitlines()

    # Strip diff prefixes (+/-) so rules work on both raw code and diffs.
    clean_lines = [
        ln[1:] if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
        else ln
        for ln in lines
    ]

    # Per-line rules
    for lineno, line in enumerate(clean_lines, start=1):
        for category, severity, pattern, message in _LINE_RULES:
            if pattern.search(line):
                findings.append(
                    ReviewFinding(
                        severity=severity,
                        message=message,
                        line=lineno,
                        category=category,
                    )
                )

    # Whole-file: missing docstrings heuristic
    joined = "\n".join(clean_lines)
    def_matches = list(re.finditer(r'^(def |class )\s*(\w+)', joined, re.MULTILINE))
    for m in def_matches:
        # Find the line number of this definition
        def_line = joined[: m.start()].count("\n") + 1
        # Check if the line after the def signature contains a docstring
        after_def = joined[m.end() :]
        body_start = re.search(r':\s*\n\s*', after_def)
        if body_start:
            rest = after_def[body_start.end() :]
            if not rest.lstrip().startswith(('"""', "'''")):
                findings.append(
                    ReviewFinding(
                        severity=Severity.info,
                        message=f"'{m.group(2)}' appears to lack a docstring.",
                        line=def_line,
                        category="readability",
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Score calculator
# ---------------------------------------------------------------------------

_SEVERITY_PENALTY = {
    Severity.error: 3,
    Severity.warning: 1,
    Severity.info: 0,
}


def _calculate_score(findings: list[ReviewFinding]) -> int:
    penalty = sum(_SEVERITY_PENALTY[f.severity] for f in findings)
    score = max(1, 10 - penalty)
    return score


# ---------------------------------------------------------------------------
# LLM integration hooks
# ---------------------------------------------------------------------------

async def _call_openai(text: str, language: str) -> list[ReviewFinding]:
    """
    Hook for OpenAI (GPT-4o, GPT-4-turbo, …).

    To activate: set LLM_PROVIDER=openai and LLM_API_KEY in .env.
    Install:  pip install openai
    """
    # from openai import AsyncOpenAI
    # client = AsyncOpenAI(api_key=os.environ["LLM_API_KEY"])
    # response = await client.chat.completions.create(
    #     model=os.getenv("LLM_MODEL", "gpt-4o"),
    #     messages=[
    #         {"role": "system", "content": _SYSTEM_PROMPT},
    #         {"role": "user", "content": f"Language: {language}\n\n{text}"},
    #     ],
    #     response_format={"type": "json_object"},
    # )
    # return _parse_llm_response(response.choices[0].message.content)
    return []


async def _call_watsonx(text: str, language: str) -> list[ReviewFinding]:
    """
    Hook for IBM watsonx.ai.

    To activate: set LLM_PROVIDER=watsonx, LLM_API_KEY, and WATSONX_PROJECT_ID in .env.
    Install:  pip install ibm-watsonx-ai
    """
    # from ibm_watsonx_ai import Credentials
    # from ibm_watsonx_ai.foundation_models import ModelInference
    # credentials = Credentials(url=os.getenv("WATSONX_URL"), api_key=os.environ["LLM_API_KEY"])
    # model = ModelInference(
    #     model_id=os.getenv("LLM_MODEL", "ibm/granite-34b-code-instruct"),
    #     credentials=credentials,
    #     project_id=os.environ["WATSONX_PROJECT_ID"],
    # )
    # result = model.generate_text(prompt=f"{_SYSTEM_PROMPT}\n\nLanguage: {language}\n\n{text}")
    # return _parse_llm_response(result)
    return []


async def _call_anthropic(text: str, language: str) -> list[ReviewFinding]:
    """
    Hook for Anthropic Claude.

    To activate: set LLM_PROVIDER=anthropic and LLM_API_KEY in .env.
    Install:  pip install anthropic
    """
    # import anthropic
    # client = anthropic.AsyncAnthropic(api_key=os.environ["LLM_API_KEY"])
    # message = await client.messages.create(
    #     model=os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022"),
    #     max_tokens=1024,
    #     system=_SYSTEM_PROMPT,
    #     messages=[{"role": "user", "content": f"Language: {language}\n\n{text}"},],
    # )
    # return _parse_llm_response(message.content[0].text)
    return []


# System prompt shared by all LLM providers.
_SYSTEM_PROMPT = """
You are an expert code reviewer. Analyse the provided code or git diff and return a
JSON object with the following schema:
{
  "findings": [
    {"severity": "error|warning|info", "line": <int|null>, "category": "<string>", "message": "<string>"}
  ]
}
Focus on: bugs, edge cases, security vulnerabilities, code quality, and readability.
Return ONLY the JSON object, no markdown fences.
""".strip()


def _parse_llm_response(raw: str) -> list[ReviewFinding]:
    """Parse the JSON response returned by an LLM into ReviewFinding objects."""
    import json

    try:
        data = json.loads(raw)
        return [
            ReviewFinding(
                severity=Severity(item.get("severity", "info")),
                message=item.get("message", ""),
                line=item.get("line"),
                category=item.get("category", "general"),
            )
            for item in data.get("findings", [])
        ]
    except (json.JSONDecodeError, KeyError, ValueError):
        return []


async def _call_llm(text: str, language: str) -> list[ReviewFinding]:
    """Dispatch to the configured LLM provider, or return [] when unconfigured."""
    api_key = os.getenv("LLM_API_KEY", "")
    provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if not api_key or api_key in {"your_llm_api_key_here", ""}:
        return []

    if provider == "openai":
        return await _call_openai(text, language)
    if provider == "watsonx":
        return await _call_watsonx(text, language)
    if provider == "anthropic":
        return await _call_anthropic(text, language)

    return []


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _build_summary(findings: list[ReviewFinding], score: int, language: str) -> str:
    errors = sum(1 for f in findings if f.severity == Severity.error)
    warnings = sum(1 for f in findings if f.severity == Severity.warning)
    infos = sum(1 for f in findings if f.severity == Severity.info)

    parts = [f"Code review complete for {language} code. Overall score: {score}/10."]

    if errors:
        parts.append(f"{errors} error(s) found that should be fixed before merging.")
    if warnings:
        parts.append(f"{warnings} warning(s) flagged for attention.")
    if infos:
        parts.append(f"{infos} informational suggestion(s) provided.")
    if not findings:
        parts.append("No issues detected. Looks good to merge!")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyze_code_or_diff(
    code_or_diff: str,
    language: str = "python",
) -> ReviewResult:
    """
    Analyse a code snippet or git diff and return a structured ReviewResult.

    Parameters
    ----------
    code_or_diff:
        Raw source code or the output of ``git diff``.
    language:
        Programming language hint (e.g. "python", "typescript").
        Used as context for the LLM hook.

    Returns
    -------
    ReviewResult
        Contains a unique review_id, list of findings, a human-readable
        summary, and a quality score from 1 (worst) to 10 (best).
    """
    rule_findings = _run_rule_based_checks(code_or_diff)
    llm_findings = await _call_llm(code_or_diff, language)

    all_findings = rule_findings + llm_findings
    score = _calculate_score(all_findings)
    summary = _build_summary(all_findings, score, language)

    return ReviewResult(
        review_id=f"review-{uuid.uuid4().hex[:8]}",
        findings=all_findings,
        summary=summary,
        score=score,
        language=language,
    )
