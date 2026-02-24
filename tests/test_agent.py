"""Tests for the SmartQA Agent orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from smartqa.agent import SmartQAAgent, _compute_risk_score, _infer_severity
from smartqa.config import Settings
from smartqa.models import (
    ActionType,
    BrowserMode,
    ElementInfo,
    ExecutionReport,
    FormInfo,
    PageAnalysis,
    QAReport,
    RiskLevel,
    SelectorType,
    Severity,
    StepResult,
    TestCase,
    TestCategory,
    TestPlan,
    TestResult,
    TestStatus,
    TestStep,
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        claude_api_key="test-key",
        browser=BrowserMode.HEADLESS,
        timeout_seconds=10,
    )


@pytest.fixture
def sample_page_analysis() -> PageAnalysis:
    return PageAnalysis(
        url="https://example.com",
        title="Example",
        forms=[
            FormInfo(
                form_id="login-form",
                action="/login",
                method="POST",
                inputs=[
                    ElementInfo(tag="input", element_id="username", name="username", element_type="text"),
                    ElementInfo(tag="input", element_id="password", name="password", element_type="password"),
                ],
                buttons=[
                    ElementInfo(tag="button", element_id="submit-btn", text="Log In"),
                ],
            )
        ],
        buttons=[ElementInfo(tag="button", element_id="submit-btn", text="Log In")],
        links=[ElementInfo(tag="a", href="/about", text="About")],
        inputs=[
            ElementInfo(tag="input", element_id="username", name="username", element_type="text"),
            ElementInfo(tag="input", element_id="password", name="password", element_type="password"),
        ],
        total_interactive_elements=5,
    )


@pytest.fixture
def sample_test_cases() -> list[TestCase]:
    return [
        TestCase(
            name="Login with valid credentials",
            description="Verify login form accepts valid input",
            category=TestCategory.FUNCTIONAL,
            risk_level=RiskLevel.HIGH,
            steps=[
                TestStep(action=ActionType.NAVIGATE, value="https://example.com"),
                TestStep(action=ActionType.TYPE, selector="#username", selector_type=SelectorType.CSS, value="admin"),
                TestStep(action=ActionType.TYPE, selector="#password", selector_type=SelectorType.CSS, value="pass123"),
                TestStep(action=ActionType.CLICK, selector="#submit-btn", selector_type=SelectorType.CSS),
                TestStep(action=ActionType.ASSERT_URL, value="/dashboard"),
            ],
        ),
        TestCase(
            name="Login with empty fields",
            description="Verify form rejects empty submission",
            category=TestCategory.NEGATIVE,
            risk_level=RiskLevel.MEDIUM,
            steps=[
                TestStep(action=ActionType.NAVIGATE, value="https://example.com"),
                TestStep(action=ActionType.CLICK, selector="#submit-btn", selector_type=SelectorType.CSS),
                TestStep(action=ActionType.ASSERT_VISIBLE, selector=".error-message", selector_type=SelectorType.CSS),
            ],
        ),
    ]


@pytest.fixture
def sample_test_plan(sample_test_cases: list[TestCase], sample_page_analysis: PageAnalysis) -> TestPlan:
    return TestPlan(
        url="https://example.com",
        test_cases=sample_test_cases,
        coverage_summary="Login form functional and negative tests",
        page_analysis=sample_page_analysis,
    )


class TestSmartQAAgentAnalyze:
    """Tests for the analyze pipeline."""

    def test_analyze_returns_test_plan(
        self,
        settings: Settings,
        sample_page_analysis: PageAnalysis,
        sample_test_plan: TestPlan,
    ) -> None:
        mock_planner = MagicMock()
        mock_planner.create_test_plan.return_value = sample_test_plan

        mock_generator = MagicMock()
        mock_generator.generate.return_value = sample_test_plan.test_cases

        mock_prioritizer = MagicMock()
        mock_prioritizer.prioritize.return_value = sample_test_plan.test_cases

        agent = SmartQAAgent(
            settings=settings,
            planner=mock_planner,
            generator=mock_generator,
            prioritizer=mock_prioritizer,
        )

        with patch.object(agent, "_analyze_page", return_value=sample_page_analysis):
            plan = agent.analyze("https://example.com")

        assert isinstance(plan, TestPlan)
        assert plan.url == "https://example.com"
        assert len(plan.test_cases) == 2
        mock_planner.create_test_plan.assert_called_once_with(sample_page_analysis)

    def test_analyze_calls_components_in_order(
        self,
        settings: Settings,
        sample_page_analysis: PageAnalysis,
        sample_test_plan: TestPlan,
        sample_test_cases: list[TestCase],
    ) -> None:
        call_order: list[str] = []

        mock_planner = MagicMock()
        mock_planner.create_test_plan.side_effect = lambda _: (
            call_order.append("planner"), sample_test_plan
        )[1]

        mock_generator = MagicMock()
        mock_generator.generate.side_effect = lambda plan, url: (
            call_order.append("generator"), sample_test_cases
        )[1]

        mock_prioritizer = MagicMock()
        mock_prioritizer.prioritize.side_effect = lambda cases, analysis: (
            call_order.append("prioritizer"), cases
        )[1]

        agent = SmartQAAgent(
            settings=settings,
            planner=mock_planner,
            generator=mock_generator,
            prioritizer=mock_prioritizer,
        )

        with patch.object(agent, "_analyze_page", return_value=sample_page_analysis):
            agent.analyze("https://example.com")

        assert call_order == ["planner", "generator", "prioritizer"]


class TestSmartQAAgentRun:
    """Tests for the full run pipeline."""

    def test_run_returns_qa_report(
        self,
        settings: Settings,
        sample_page_analysis: PageAnalysis,
        sample_test_plan: TestPlan,
        sample_test_cases: list[TestCase],
    ) -> None:
        mock_planner = MagicMock()
        mock_planner.create_test_plan.return_value = sample_test_plan

        mock_generator = MagicMock()
        mock_generator.generate.return_value = sample_test_cases

        mock_prioritizer = MagicMock()
        mock_prioritizer.prioritize.return_value = sample_test_cases

        execution_report = ExecutionReport(
            url="https://example.com",
            test_results=[
                TestResult(
                    test_case=sample_test_cases[0],
                    status=TestStatus.PASSED,
                    step_results=[
                        StepResult(step=s, status=TestStatus.PASSED)
                        for s in sample_test_cases[0].steps
                    ],
                ),
                TestResult(
                    test_case=sample_test_cases[1],
                    status=TestStatus.FAILED,
                    error_message="Element not found",
                    step_results=[
                        StepResult(step=sample_test_cases[1].steps[0], status=TestStatus.PASSED),
                        StepResult(
                            step=sample_test_cases[1].steps[1],
                            status=TestStatus.FAILED,
                            error_message="Element not found",
                        ),
                    ],
                ),
            ],
            total_tests=2,
            passed=1,
            failed=1,
        )

        mock_executor = MagicMock()
        mock_executor.execute.return_value = execution_report

        agent = SmartQAAgent(
            settings=settings,
            planner=mock_planner,
            generator=mock_generator,
            prioritizer=mock_prioritizer,
            executor=mock_executor,
        )

        with patch.object(agent, "_analyze_page", return_value=sample_page_analysis):
            report = agent.run("https://example.com")

        assert isinstance(report, QAReport)
        assert report.tests_generated == 2
        assert report.tests_passed == 1
        assert report.tests_failed == 1
        assert len(report.issues) == 1
        assert report.issues[0].severity == Severity.MEDIUM


class TestHelpers:
    def test_infer_severity_critical(self) -> None:
        tc = TestCase(name="test", description="", risk_level=RiskLevel.CRITICAL, steps=[])
        assert _infer_severity(tc) == Severity.CRITICAL

    def test_infer_severity_low(self) -> None:
        tc = TestCase(name="test", description="", risk_level=RiskLevel.LOW, steps=[])
        assert _infer_severity(tc) == Severity.LOW

    def test_compute_risk_score_all_passed(self) -> None:
        report = ExecutionReport(url="http://x", total_tests=10, passed=10, failed=0, errors=0)
        assert _compute_risk_score(report) == 0.0

    def test_compute_risk_score_all_failed(self) -> None:
        report = ExecutionReport(url="http://x", total_tests=10, passed=0, failed=10, errors=0)
        score = _compute_risk_score(report)
        assert score == 80.0

    def test_compute_risk_score_empty(self) -> None:
        report = ExecutionReport(url="http://x", total_tests=0)
        assert _compute_risk_score(report) == 0.0

    def test_compute_risk_score_with_healed(self) -> None:
        report = ExecutionReport(url="http://x", total_tests=10, passed=8, failed=2, healed=3)
        score = _compute_risk_score(report)
        assert score > 0
        assert score <= 100
