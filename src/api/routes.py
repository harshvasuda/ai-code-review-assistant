from __future__ import annotations

from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.services.reviewer import analyze_code_or_diff

router = APIRouter()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class ReviewStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------
class ReviewRequest(BaseModel):
    """Payload for a code-review or PR-diff review request."""

    repository: str = Field(
        ...,
        examples=["your-org/your-repo"],
        description="GitHub repository in 'owner/repo' format.",
    )
    pull_request_id: Optional[int] = Field(
        None,
        description="Pull-request number (optional; omit for raw snippet reviews).",
    )
    diff: Optional[str] = Field(
        None,
        description="Raw git diff to review (mutually exclusive with 'code').",
    )
    code: Optional[str] = Field(
        None,
        description="Raw code snippet to review (mutually exclusive with 'diff').",
    )
    language: Optional[str] = Field(
        None,
        examples=["python", "typescript"],
        description="Programming language of the provided snippet.",
    )


class ReviewComment(BaseModel):
    line: Optional[int] = Field(None, description="Line number the comment refers to.")
    severity: str = Field(..., examples=["info", "warning", "error"])
    category: str = Field("general", description="Finding category (bug, security, quality, readability).")
    message: str


class ReviewResponse(BaseModel):
    review_id: str
    status: ReviewStatus
    repository: str
    pull_request_id: Optional[int]
    score: int = Field(..., description="Quality score from 1 (worst) to 10 (best).")
    comments: list[ReviewComment]
    summary: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/review", response_model=ReviewResponse, tags=["Review"])
async def create_review(payload: ReviewRequest) -> ReviewResponse:
    """
    Submit code or a git diff for AI-powered review.

    At least one of `diff` or `code` must be provided.
    The response includes structured findings (bugs, security issues, quality
    suggestions) plus an overall quality score (1–10) and a plain-English summary.
    """
    content = payload.diff or payload.code
    if not content:
        raise HTTPException(
            status_code=422,
            detail="At least one of 'diff' or 'code' must be provided.",
        )

    language = payload.language or "python"

    try:
        result = await analyze_code_or_diff(content, language=language)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Review engine error: {exc}") from exc

    comments = [
        ReviewComment(
            line=finding.line,
            severity=finding.severity.value,
            category=finding.category,
            message=finding.message,
        )
        for finding in result.findings
    ]

    return ReviewResponse(
        review_id=result.review_id,
        status=ReviewStatus.completed,
        repository=payload.repository,
        pull_request_id=payload.pull_request_id,
        score=result.score,
        comments=comments,
        summary=result.summary,
    )
