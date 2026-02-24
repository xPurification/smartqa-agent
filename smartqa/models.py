"""Pydantic models and enums for the SmartQA Agent system."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    HEALED = "healed"


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    CLEAR = "clear"
    SELECT = "select"
    HOVER = "hover"
    SUBMIT = "submit"
    WAIT = "wait"
    SCROLL = "scroll"
    ASSERT_TEXT = "assert_text"
    ASSERT_VISIBLE = "assert_visible"
    ASSERT_NOT_VISIBLE = "assert_not_visible"
    ASSERT_URL = "assert_url"
    ASSERT_TITLE = "assert_title"
    ASSERT_ELEMENT_EXISTS = "assert_element_exists"
    SCREENSHOT = "screenshot"


class SelectorType(str, Enum):
    CSS = "css"
    XPATH = "xpath"
    ID = "id"
    NAME = "name"
    CLASS_NAME = "class_name"
    TAG_NAME = "tag_name"
    LINK_TEXT = "link_text"
    PARTIAL_LINK_TEXT = "partial_link_text"


class BrowserMode(str, Enum):
    HEADLESS = "headless"
    HEADED = "headed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TestCategory(str, Enum):
    FUNCTIONAL = "functional"
    EDGE_CASE = "edge_case"
    NEGATIVE = "negative"
    SMOKE = "smoke"
    REGRESSION = "regression"


# --- Page Analysis Models ---


class ElementInfo(BaseModel):
    """Represents a single interactive element discovered on a page."""

    tag: str
    element_id: str = ""
    classes: list[str] = Field(default_factory=list)
    name: str = ""
    element_type: str = ""
    text: str = ""
    href: str = ""
    placeholder: str = ""
    aria_label: str = ""
    value: str = ""
    is_visible: bool = True
    attributes: dict[str, str] = Field(default_factory=dict)


class FormInfo(BaseModel):
    """Represents a form and its child inputs."""

    form_id: str = ""
    action: str = ""
    method: str = ""
    inputs: list[ElementInfo] = Field(default_factory=list)
    buttons: list[ElementInfo] = Field(default_factory=list)


class PageAnalysis(BaseModel):
    """Complete analysis of a web page's interactive elements."""

    url: str
    title: str = ""
    meta_description: str = ""
    forms: list[FormInfo] = Field(default_factory=list)
    buttons: list[ElementInfo] = Field(default_factory=list)
    links: list[ElementInfo] = Field(default_factory=list)
    inputs: list[ElementInfo] = Field(default_factory=list)
    navigation_elements: list[ElementInfo] = Field(default_factory=list)
    images: list[ElementInfo] = Field(default_factory=list)
    headings: list[ElementInfo] = Field(default_factory=list)
    total_interactive_elements: int = 0
    page_load_time_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


# --- Test Planning Models ---


class TestStep(BaseModel):
    """A single action within a test case."""

    action: ActionType
    selector: str = ""
    selector_type: SelectorType = SelectorType.CSS
    value: str = ""
    expected_result: str = ""
    timeout_seconds: float = 10.0
    description: str = ""


class TestCase(BaseModel):
    """A complete test scenario with ordered steps."""

    name: str
    description: str
    category: TestCategory = TestCategory.FUNCTIONAL
    steps: list[TestStep] = Field(default_factory=list)
    priority_score: float = Field(default=50.0, ge=0.0, le=100.0)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    tags: list[str] = Field(default_factory=list)
    estimated_duration_seconds: float = 30.0
    preconditions: list[str] = Field(default_factory=list)


class TestPlan(BaseModel):
    """A collection of test cases generated for a target URL."""

    url: str
    test_cases: list[TestCase] = Field(default_factory=list)
    total_tests: int = 0
    coverage_summary: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    page_analysis: PageAnalysis | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.total_tests == 0:
            self.total_tests = len(self.test_cases)


# --- Test Execution Models ---


class StepResult(BaseModel):
    """Result of executing a single test step."""

    step: TestStep
    status: TestStatus
    duration_ms: float = 0.0
    error_message: str = ""
    screenshot_path: str = ""
    healed: bool = False
    healed_selector: str = ""


class TestResult(BaseModel):
    """Result of executing a single test case."""

    test_case: TestCase
    status: TestStatus
    step_results: list[StepResult] = Field(default_factory=list)
    duration_ms: float = 0.0
    error_message: str = ""
    screenshot_path: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class SelectorHealRecord(BaseModel):
    """Records a self-healing selector adaptation."""

    original_selector: str
    original_selector_type: SelectorType
    healed_selector: str
    healed_selector_type: SelectorType
    strategy_used: str
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HealResult(BaseModel):
    """Outcome of a self-healing attempt."""

    success: bool
    healed_selector: str = ""
    healed_selector_type: SelectorType = SelectorType.CSS
    strategy_used: str = ""
    confidence: float = 0.0
    attempts: int = 0
    records: list[SelectorHealRecord] = Field(default_factory=list)


class ExecutionReport(BaseModel):
    """Full report from a test execution run."""

    url: str
    test_results: list[TestResult] = Field(default_factory=list)
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    healed: int = 0
    total_duration_ms: float = 0.0
    heal_records: list[SelectorHealRecord] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


# --- QA Report Models ---


class Issue(BaseModel):
    """A discovered issue during test execution."""

    severity: Severity
    description: str
    steps_to_reproduce: str = ""
    screenshot_path: str = ""
    test_case_name: str = ""
    error_message: str = ""


class QAReport(BaseModel):
    """Final structured QA report matching the specification."""

    application_url: str
    tests_generated: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    self_healed_failures: int = 0
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    issues: list[Issue] = Field(default_factory=list)
    test_plan: TestPlan | None = None
    execution_report: ExecutionReport | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# --- API Models ---


class AnalyzeRequest(BaseModel):
    url: str


class RunTestsRequest(BaseModel):
    url: str


class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = ""
