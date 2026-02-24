"""SmartQA Agent — the main orchestrator that ties all components together."""

from __future__ import annotations

from typing import TYPE_CHECKING

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

from smartqa.config import Settings, get_settings
from smartqa.executor import TestExecutor
from smartqa.logging_config import get_logger
from smartqa.models import (
    ExecutionReport,
    Issue,
    PageAnalysis,
    QAReport,
    RiskLevel,
    Severity,
    TestCase,
    TestPlan,
    TestStatus,
)
from smartqa.planner import TestPlanner
from smartqa.prioritizer import TestPrioritizer
from smartqa.test_generator import TestGenerator
from smartqa.web_analyzer import WebAnalyzer

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

logger = get_logger(__name__)


class SmartQAAgent:
    """Orchestrates the full QA pipeline: analyze -> plan -> generate -> prioritize -> execute -> report.

    All collaborating components are injected via the constructor so they can be
    swapped for testing or customization.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        planner: TestPlanner | None = None,
        generator: TestGenerator | None = None,
        prioritizer: TestPrioritizer | None = None,
        executor: TestExecutor | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._planner = planner or TestPlanner(self._settings)
        self._generator = generator or TestGenerator()
        self._prioritizer = prioritizer or TestPrioritizer()
        self._executor = executor or TestExecutor(self._settings)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, url: str) -> TestPlan:
        """Analyze *url*, generate a test plan, and return it with prioritized cases."""
        logger.info("SmartQA Agent — analyzing %s", url)

        page_analysis = self._analyze_page(url)
        test_plan = self._planner.create_test_plan(page_analysis)
        test_cases = self._generator.generate(test_plan, url)
        test_cases = self._prioritizer.prioritize(test_cases, page_analysis)

        test_plan = test_plan.model_copy(
            update={
                "test_cases": test_cases,
                "total_tests": len(test_cases),
                "page_analysis": page_analysis,
            }
        )

        logger.info("Analysis complete — %d prioritized test cases", len(test_cases))
        return test_plan

    def run(self, url: str) -> QAReport:
        """Full pipeline: analyze -> execute -> report."""
        logger.info("SmartQA Agent — full run against %s", url)

        test_plan = self.analyze(url)
        execution_report = self._executor.execute(test_plan.test_cases, url)
        qa_report = self._build_report(url, test_plan, execution_report)

        logger.info(
            "Run complete — %d/%d passed, risk score: %.0f",
            qa_report.tests_passed,
            qa_report.tests_generated,
            qa_report.risk_score,
        )
        return qa_report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _analyze_page(self, url: str) -> PageAnalysis:
        """Create a temporary driver, analyze the page, and shut it down."""
        driver = self._create_analysis_driver()
        try:
            analyzer = WebAnalyzer(driver, self._settings)
            return analyzer.analyze(url)
        finally:
            try:
                driver.quit()
            except Exception:
                pass

    def _create_analysis_driver(self) -> WebDriver:
        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")

        service = ChromeService(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=options)

    @staticmethod
    def _build_report(
        url: str,
        test_plan: TestPlan,
        execution_report: ExecutionReport,
    ) -> QAReport:
        """Assemble the final QA report from execution results."""
        issues: list[Issue] = []
        for result in execution_report.test_results:
            if result.status in (TestStatus.FAILED, TestStatus.ERROR):
                severity = _infer_severity(result.test_case)
                steps_str = "\n".join(
                    f"{i+1}. {s.description or s.action.value}"
                    for i, s in enumerate(result.test_case.steps)
                )
                issues.append(
                    Issue(
                        severity=severity,
                        description=f"Test '{result.test_case.name}' {result.status.value}: {result.error_message}",
                        steps_to_reproduce=steps_str,
                        screenshot_path=result.screenshot_path,
                        test_case_name=result.test_case.name,
                        error_message=result.error_message,
                    )
                )

        risk_score = _compute_risk_score(execution_report)

        return QAReport(
            application_url=url,
            tests_generated=execution_report.total_tests,
            tests_passed=execution_report.passed,
            tests_failed=execution_report.failed,
            self_healed_failures=execution_report.healed,
            risk_score=risk_score,
            issues=issues,
            test_plan=test_plan,
            execution_report=execution_report,
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _infer_severity(tc: TestCase) -> Severity:
    if tc.risk_level == RiskLevel.CRITICAL:
        return Severity.CRITICAL
    if tc.risk_level == RiskLevel.HIGH:
        return Severity.HIGH
    if tc.risk_level == RiskLevel.MEDIUM:
        return Severity.MEDIUM
    return Severity.LOW


def _compute_risk_score(report: ExecutionReport) -> float:
    """Produce a 0-100 risk score based on pass/fail ratio and healed count."""
    if report.total_tests == 0:
        return 0.0

    fail_ratio = (report.failed + report.errors) / report.total_tests
    heal_penalty = report.healed * 2

    raw = fail_ratio * 80 + min(heal_penalty, 20)
    return min(round(raw, 1), 100.0)
