"""Request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelVerifyRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=512)


class ModelVerifyOut(BaseModel):
    ok: bool
    latency_ms: int
    message: str


class FeedbackItemIn(BaseModel):
    kind: Literal["false_positive", "false_negative", "location", "classification"]
    reason: str = Field(min_length=1, max_length=2000)
    finding_id: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=300)
    defect_type: str | None = Field(default=None, max_length=64)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_target(self) -> "FeedbackItemIn":
        if self.kind == "false_negative":
            if not self.path or self.finding_id:
                raise ValueError("漏报反馈需要选择文件，且不能指定 finding_id")
        elif not self.finding_id:
            raise ValueError("该反馈类型需要指定报告条目")
        if self.end_line is not None and (
            self.start_line is None or self.end_line < self.start_line
        ):
            raise ValueError("结束行不能小于起始行")
        return self


class FeedbackRequest(BaseModel):
    scan_id: str = Field(min_length=1, max_length=64)
    items: list[FeedbackItemIn] = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=512)


class DefectTypeOut(BaseModel):
    code: str
    label: str


class LanguageOut(BaseModel):
    code: str
    name: str
    description: str
    skill_id: str
    skill_version: str
    extensions: list[str]
    defect_types: list[DefectTypeOut]


class FrameworkOut(BaseModel):
    path: str
    available: bool
    detector_path: str = ""
    error: str = ""


class CatalogOut(BaseModel):
    languages: list[LanguageOut]
    framework: FrameworkOut


class ScanFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    size_bytes: int
    line_count: int
    sha256: str


class ScanEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event: str
    level: str
    message: str
    created_at: datetime


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    finding_key: str
    defect_type: str
    title: str
    description: str
    severity: str
    path: str
    start_line: int
    end_line: int
    evidence: list
    verification: dict
    properties: dict


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    language: str
    skill_id: str
    skill_version: str
    defect_types: list[str]
    source_kind: str
    source_name: str
    status: str
    status_detail: str
    total_files: int
    completed_files: int
    finding_count: int
    model_calls: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_seconds: float
    model_name: str
    base_url: str
    parent_scan_id: str = ""
    repo_url: str = ""
    error_code: str
    error_message: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ScanDetailOut(ScanOut):
    files: list[ScanFileOut] = Field(default_factory=list)
    findings: list[FindingOut] = Field(default_factory=list)
    events: list[ScanEventOut] = Field(default_factory=list)
    coverage: dict | None = None
    errors: list = Field(default_factory=list)
    feedback_items: list = Field(default_factory=list)
    feedback_summary: dict | None = None
    has_report: bool = False
    retry_file_count: int = 0


class FeedbackReportOut(ScanOut):
    number: int


class ScanPage(BaseModel):
    items: list[ScanOut]
    total: int
    page: int
    page_size: int


class StatsOut(BaseModel):
    total_scans: int
    running_scans: int
    completed_scans: int = 0
    total_findings: int
    high_findings: int
    languages: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    recent: list[ScanOut]
    daily: list[dict]
    token_daily: list[dict] = Field(default_factory=list)
    severity: dict
