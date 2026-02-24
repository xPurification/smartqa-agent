"""Selenium-based test execution engine with self-healing and screenshot capture."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

from webdriver_manager.chrome import ChromeDriverManager

from smartqa.config import Settings
from smartqa.logging_config import get_logger
from smartqa.models import (
    ActionType,
    BrowserMode,
    ExecutionReport,
    SelectorHealRecord,
    SelectorType,
    StepResult,
    TestCase,
    TestResult,
    TestStatus,
    TestStep,
)
from smartqa.self_healer import SelfHealer, selector_type_to_by

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

logger = get_logger(__name__)


class TestExecutor:
    """Drives Selenium through generated test cases, captures results, and self-heals."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._healer = SelfHealer(settings)
        self._driver: WebDriver | None = None
        self._screenshot_dir = settings.ensure_screenshot_dir()

    def execute(self, test_cases: list[TestCase], url: str) -> ExecutionReport:
        """Run all *test_cases* against *url* and return a full execution report."""
        logger.info("Starting test execution — %d test cases against %s", len(test_cases), url)
        started_at = datetime.now(UTC)

        self._driver = self._create_driver()
        results: list[TestResult] = []
        all_heal_records: list[SelectorHealRecord] = []

        try:
            for tc in test_cases:
                result = self._execute_test_case(tc, url)
                results.append(result)
                all_heal_records.extend(
                    sr.records for sr in [
                        step_r for step_r in result.step_results if step_r.healed
                    ]
                )
        finally:
            self._quit_driver()

        completed_at = datetime.now(UTC)
        total_duration = (completed_at - started_at).total_seconds() * 1000

        passed = sum(1 for r in results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in results if r.status == TestStatus.FAILED)
        errors = sum(1 for r in results if r.status == TestStatus.ERROR)
        skipped = sum(1 for r in results if r.status == TestStatus.SKIPPED)
        healed = sum(
            1 for r in results
            if any(sr.healed for sr in r.step_results)
        )

        heal_records_flat: list[SelectorHealRecord] = []
        for r in results:
            for sr in r.step_results:
                if sr.healed:
                    heal_records_flat.append(
                        SelectorHealRecord(
                            original_selector=sr.step.selector,
                            original_selector_type=sr.step.selector_type,
                            healed_selector=sr.healed_selector,
                            healed_selector_type=SelectorType.CSS,
                            strategy_used="self_healer",
                            confidence=0.8,
                        )
                    )

        report = ExecutionReport(
            url=url,
            test_results=results,
            total_tests=len(results),
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            healed=healed,
            total_duration_ms=total_duration,
            heal_records=heal_records_flat,
            started_at=started_at,
            completed_at=completed_at,
        )

        logger.info(
            "Execution complete — %d passed, %d failed, %d errors, %d healed (%.1f s)",
            passed,
            failed,
            errors,
            healed,
            total_duration / 1000,
        )
        return report

    # ------------------------------------------------------------------
    # Driver lifecycle
    # ------------------------------------------------------------------

    def _create_driver(self) -> WebDriver:
        options = ChromeOptions()
        if self._settings.browser == BrowserMode.HEADLESS:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")

        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.implicitly_wait(2)
        driver.set_page_load_timeout(self._settings.timeout_seconds)
        return driver

    def _quit_driver(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except WebDriverException:
                pass
            self._driver = None

    # ------------------------------------------------------------------
    # Test case execution
    # ------------------------------------------------------------------

    def _execute_test_case(self, tc: TestCase, url: str) -> TestResult:
        logger.info("Running test: %s", tc.name)
        assert self._driver is not None

        started_at = datetime.now(UTC)
        step_results: list[StepResult] = []
        overall_status = TestStatus.PASSED
        overall_error = ""
        screenshot_path = ""

        for step in tc.steps:
            step_result = self._execute_step(step)
            step_results.append(step_result)

            if step_result.status in (TestStatus.FAILED, TestStatus.ERROR):
                overall_status = step_result.status
                overall_error = step_result.error_message
                screenshot_path = self._capture_screenshot(tc.name)
                step_result = step_result.model_copy(
                    update={"screenshot_path": screenshot_path}
                )
                step_results[-1] = step_result
                break

        completed_at = datetime.now(UTC)
        duration_ms = (completed_at - started_at).total_seconds() * 1000

        status_icon = {
            TestStatus.PASSED: "[green]PASS[/green]",
            TestStatus.FAILED: "[red]FAIL[/red]",
            TestStatus.ERROR: "[red]ERROR[/red]",
        }.get(overall_status, overall_status.value)
        logger.info("  Result: %s  (%.0f ms)", status_icon, duration_ms)

        return TestResult(
            test_case=tc,
            status=overall_status,
            step_results=step_results,
            duration_ms=duration_ms,
            error_message=overall_error,
            screenshot_path=screenshot_path,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _execute_step(self, step: TestStep) -> StepResult:
        assert self._driver is not None
        start = time.perf_counter()

        try:
            self._perform_action(step)
            duration = (time.perf_counter() - start) * 1000
            return StepResult(step=step, status=TestStatus.PASSED, duration_ms=duration)
        except (NoSuchElementException, StaleElementReferenceException) as exc:
            heal_result = self._healer.heal(
                self._driver,
                step.selector,
                step.selector_type,
            )
            if heal_result.success:
                healed_step = step.model_copy(
                    update={
                        "selector": heal_result.healed_selector,
                        "selector_type": heal_result.healed_selector_type,
                    }
                )
                try:
                    self._perform_action(healed_step)
                    duration = (time.perf_counter() - start) * 1000
                    return StepResult(
                        step=step,
                        status=TestStatus.PASSED,
                        duration_ms=duration,
                        healed=True,
                        healed_selector=heal_result.healed_selector,
                    )
                except WebDriverException as inner_exc:
                    duration = (time.perf_counter() - start) * 1000
                    return StepResult(
                        step=step,
                        status=TestStatus.FAILED,
                        duration_ms=duration,
                        error_message=str(inner_exc)[:500],
                    )

            duration = (time.perf_counter() - start) * 1000
            return StepResult(
                step=step,
                status=TestStatus.FAILED,
                duration_ms=duration,
                error_message=f"Selector failed and self-healing unsuccessful: {exc}"[:500],
            )
        except (TimeoutException, WebDriverException) as exc:
            duration = (time.perf_counter() - start) * 1000
            return StepResult(
                step=step,
                status=TestStatus.ERROR,
                duration_ms=duration,
                error_message=str(exc)[:500],
            )

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _perform_action(self, step: TestStep) -> None:
        assert self._driver is not None
        action_map = {
            ActionType.NAVIGATE: self._action_navigate,
            ActionType.CLICK: self._action_click,
            ActionType.TYPE: self._action_type,
            ActionType.CLEAR: self._action_clear,
            ActionType.SELECT: self._action_select,
            ActionType.HOVER: self._action_hover,
            ActionType.SUBMIT: self._action_submit,
            ActionType.WAIT: self._action_wait,
            ActionType.SCROLL: self._action_scroll,
            ActionType.ASSERT_TEXT: self._action_assert_text,
            ActionType.ASSERT_VISIBLE: self._action_assert_visible,
            ActionType.ASSERT_NOT_VISIBLE: self._action_assert_not_visible,
            ActionType.ASSERT_URL: self._action_assert_url,
            ActionType.ASSERT_TITLE: self._action_assert_title,
            ActionType.ASSERT_ELEMENT_EXISTS: self._action_assert_element_exists,
            ActionType.SCREENSHOT: self._action_screenshot,
        }
        handler = action_map.get(step.action)
        if handler is None:
            raise ValueError(f"Unknown action type: {step.action}")
        handler(step)

    def _find_element(self, step: TestStep) -> WebElement:
        assert self._driver is not None
        by = selector_type_to_by(step.selector_type)
        return WebDriverWait(self._driver, step.timeout_seconds).until(
            EC.presence_of_element_located((by, step.selector))
        )

    def _action_navigate(self, step: TestStep) -> None:
        assert self._driver is not None
        url = step.value or step.selector
        logger.debug("  Navigating to %s", url)
        self._driver.get(url)
        WebDriverWait(self._driver, step.timeout_seconds).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )

    def _action_click(self, step: TestStep) -> None:
        el = self._find_element(step)
        logger.debug("  Clicking '%s'", step.selector)
        el.click()

    def _action_type(self, step: TestStep) -> None:
        el = self._find_element(step)
        logger.debug("  Typing '%s' into '%s'", step.value[:30], step.selector)
        el.clear()
        el.send_keys(step.value)

    def _action_clear(self, step: TestStep) -> None:
        el = self._find_element(step)
        el.clear()

    def _action_select(self, step: TestStep) -> None:
        el = self._find_element(step)
        select = Select(el)
        try:
            select.select_by_visible_text(step.value)
        except WebDriverException:
            select.select_by_value(step.value)

    def _action_hover(self, step: TestStep) -> None:
        assert self._driver is not None
        el = self._find_element(step)
        ActionChains(self._driver).move_to_element(el).perform()

    def _action_submit(self, step: TestStep) -> None:
        el = self._find_element(step)
        el.submit()

    def _action_wait(self, step: TestStep) -> None:
        duration = float(step.value) if step.value else 1.0
        time.sleep(duration)

    def _action_scroll(self, step: TestStep) -> None:
        assert self._driver is not None
        if step.selector:
            el = self._find_element(step)
            self._driver.execute_script("arguments[0].scrollIntoView(true);", el)
        else:
            self._driver.execute_script("window.scrollBy(0, 500);")

    def _action_assert_text(self, step: TestStep) -> None:
        el = self._find_element(step)
        actual = el.text
        if step.value and step.value not in actual:
            raise AssertionError(
                f"Expected text '{step.value}' not found in element. Got: '{actual[:200]}'"
            )

    def _action_assert_visible(self, step: TestStep) -> None:
        assert self._driver is not None
        by = selector_type_to_by(step.selector_type)
        el = WebDriverWait(self._driver, step.timeout_seconds).until(
            EC.visibility_of_element_located((by, step.selector))
        )
        if not el.is_displayed():
            raise AssertionError(f"Element '{step.selector}' is not visible")

    def _action_assert_not_visible(self, step: TestStep) -> None:
        assert self._driver is not None
        by = selector_type_to_by(step.selector_type)
        try:
            el = self._driver.find_element(by, step.selector)
            if el.is_displayed():
                raise AssertionError(f"Element '{step.selector}' is visible but expected hidden")
        except NoSuchElementException:
            pass

    def _action_assert_url(self, step: TestStep) -> None:
        assert self._driver is not None
        current = self._driver.current_url
        if step.value and step.value not in current:
            raise AssertionError(
                f"Expected URL to contain '{step.value}', got '{current}'"
            )

    def _action_assert_title(self, step: TestStep) -> None:
        assert self._driver is not None
        title = self._driver.title
        if step.value and step.value not in title:
            raise AssertionError(
                f"Expected title to contain '{step.value}', got '{title}'"
            )

    def _action_assert_element_exists(self, step: TestStep) -> None:
        self._find_element(step)

    def _action_screenshot(self, step: TestStep) -> None:
        self._capture_screenshot(step.value or "manual")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _capture_screenshot(self, label: str) -> str:
        if self._driver is None:
            return ""
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:60]
        filename = f"{safe_label}_{uuid.uuid4().hex[:8]}.png"
        path = self._screenshot_dir / filename
        try:
            self._driver.save_screenshot(str(path))
            logger.info("  Screenshot saved: %s", path)
            return str(path)
        except WebDriverException as exc:
            logger.warning("  Failed to capture screenshot: %s", exc)
            return ""
