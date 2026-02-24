"""Tests for the test executor and self-healer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException

from smartqa.config import Settings
from smartqa.executor import TestExecutor
from smartqa.models import (
    ActionType,
    BrowserMode,
    ExecutionReport,
    SelectorType,
    TestCase,
    TestCategory,
    TestStatus,
    TestStep,
)
from smartqa.self_healer import SelfHealer, selector_type_to_by


@pytest.fixture
def settings() -> Settings:
    return Settings(
        claude_api_key="test-key",
        browser=BrowserMode.HEADLESS,
        timeout_seconds=5,
        heal_attempts=3,
    )


@pytest.fixture
def mock_driver() -> MagicMock:
    driver = MagicMock()
    driver.title = "Test Page"
    driver.current_url = "https://example.com"
    driver.execute_script.return_value = "complete"
    driver.save_screenshot.return_value = True
    return driver


@pytest.fixture
def sample_test_case() -> TestCase:
    return TestCase(
        name="Click a button",
        description="Verify button click works",
        category=TestCategory.FUNCTIONAL,
        steps=[
            TestStep(
                action=ActionType.NAVIGATE,
                value="https://example.com",
                description="Go to page",
            ),
            TestStep(
                action=ActionType.CLICK,
                selector="#my-button",
                selector_type=SelectorType.CSS,
                description="Click button",
            ),
            TestStep(
                action=ActionType.ASSERT_TITLE,
                value="Test Page",
                description="Verify title",
            ),
        ],
    )


class TestTestExecutor:
    """Tests for the test executor engine."""

    def test_execute_returns_report(
        self, settings: Settings, mock_driver: MagicMock, sample_test_case: TestCase
    ) -> None:
        executor = TestExecutor(settings)

        with patch.object(executor, "_create_driver", return_value=mock_driver):
            mock_element = MagicMock()
            mock_element.text = "Test Page"
            mock_element.is_displayed.return_value = True
            mock_driver.find_element.return_value = mock_element

            from selenium.webdriver.support.wait import WebDriverWait

            with patch("smartqa.executor.WebDriverWait") as mock_wait:
                mock_wait.return_value.until.return_value = mock_element
                report = executor.execute([sample_test_case], "https://example.com")

        assert isinstance(report, ExecutionReport)
        assert report.total_tests == 1
        assert report.url == "https://example.com"

    def test_execute_captures_failure(
        self, settings: Settings, mock_driver: MagicMock
    ) -> None:
        failing_case = TestCase(
            name="Failing test",
            description="This test should fail",
            steps=[
                TestStep(
                    action=ActionType.NAVIGATE,
                    value="https://example.com",
                ),
                TestStep(
                    action=ActionType.CLICK,
                    selector="#nonexistent",
                    selector_type=SelectorType.CSS,
                ),
            ],
        )

        executor = TestExecutor(settings)

        with patch.object(executor, "_create_driver", return_value=mock_driver):
            with patch("smartqa.executor.WebDriverWait") as mock_wait:
                def wait_side_effect(locator):
                    if locator == (
                        "css selector", "#nonexistent"
                    ):
                        raise NoSuchElementException("not found")
                    mock_el = MagicMock()
                    mock_el.text = ""
                    mock_el.is_displayed.return_value = True
                    return mock_el

                mock_wait_instance = MagicMock()

                nav_element = MagicMock()
                call_count = [0]

                def until_effect(*args, **kwargs):
                    call_count[0] += 1
                    if call_count[0] == 1:
                        return "complete"
                    raise NoSuchElementException("not found")

                mock_wait_instance.until.side_effect = until_effect
                mock_wait.return_value = mock_wait_instance

                with patch.object(executor._healer, "heal") as mock_heal:
                    from smartqa.models import HealResult
                    mock_heal.return_value = HealResult(success=False, attempts=3)

                    report = executor.execute([failing_case], "https://example.com")

        assert report.failed >= 1 or report.errors >= 1

    def test_execute_multiple_cases(
        self, settings: Settings, mock_driver: MagicMock, sample_test_case: TestCase
    ) -> None:
        second_case = TestCase(
            name="Second test",
            description="Another test",
            steps=[
                TestStep(action=ActionType.NAVIGATE, value="https://example.com"),
                TestStep(action=ActionType.ASSERT_TITLE, value="Test Page"),
            ],
        )

        executor = TestExecutor(settings)

        with patch.object(executor, "_create_driver", return_value=mock_driver):
            mock_element = MagicMock()
            mock_element.text = "Test Page"
            mock_element.is_displayed.return_value = True

            with patch("smartqa.executor.WebDriverWait") as mock_wait:
                mock_wait.return_value.until.return_value = mock_element
                report = executor.execute(
                    [sample_test_case, second_case], "https://example.com"
                )

        assert report.total_tests == 2


class TestSelfHealer:
    """Tests for the self-healing mechanism."""

    def test_heal_by_id(self, settings: Settings, mock_driver: MagicMock) -> None:
        healer = SelfHealer(settings)

        mock_driver.find_element.side_effect = [MagicMock()]

        result = healer.heal(
            mock_driver,
            ".old-class",
            SelectorType.CSS,
            element_id="my-id",
        )

        assert result.success is True
        assert result.strategy_used == "alternative_selector"
        assert result.confidence >= 0.9

    def test_heal_by_text(self, settings: Settings, mock_driver: MagicMock) -> None:
        healer = SelfHealer(settings)

        mock_driver.find_element.side_effect = [
            NoSuchElementException("not found"),
            MagicMock(),
        ]

        result = healer.heal(
            mock_driver,
            ".missing-class",
            SelectorType.CSS,
            element_text="Click Me",
        )

        assert result.success is True
        assert result.strategy_used == "text_content_match"

    def test_heal_by_aria_label(self, settings: Settings, mock_driver: MagicMock) -> None:
        healer = SelfHealer(settings)

        mock_driver.find_element.side_effect = [
            NoSuchElementException("no"),
            MagicMock(),
        ]

        result = healer.heal(
            mock_driver,
            ".gone",
            SelectorType.CSS,
            aria_label="Submit Form",
        )

        assert result.success is True
        assert "attribute_match" in result.strategy_used

    def test_heal_failure(self, settings: Settings, mock_driver: MagicMock) -> None:
        healer = SelfHealer(settings)

        mock_driver.find_element.side_effect = NoSuchElementException("gone")
        mock_driver.find_elements.return_value = []

        result = healer.heal(
            mock_driver,
            ".totally-gone",
            SelectorType.CSS,
        )

        assert result.success is False

    def test_selector_type_to_by_mapping(self) -> None:
        from selenium.webdriver.common.by import By

        assert selector_type_to_by(SelectorType.CSS) == By.CSS_SELECTOR
        assert selector_type_to_by(SelectorType.XPATH) == By.XPATH
        assert selector_type_to_by(SelectorType.ID) == By.ID
        assert selector_type_to_by(SelectorType.NAME) == By.NAME


class TestSelfHealerEdgeCases:
    def test_heal_with_xpath_to_css_conversion(self, settings: Settings, mock_driver: MagicMock) -> None:
        healer = SelfHealer(settings)

        mock_driver.find_element.side_effect = [MagicMock()]

        result = healer.heal(
            mock_driver,
            "//*[@id='my-element']",
            SelectorType.XPATH,
        )

        assert result.success is True

    def test_heal_respects_max_attempts(self, settings: Settings, mock_driver: MagicMock) -> None:
        limited_settings = Settings(
            claude_api_key="test-key",
            heal_attempts=1,
        )
        healer = SelfHealer(limited_settings)

        mock_driver.find_element.side_effect = NoSuchElementException("nope")
        mock_driver.find_elements.return_value = []

        result = healer.heal(
            mock_driver,
            ".x",
            SelectorType.CSS,
            element_text="text",
            aria_label="label",
        )

        assert result.attempts <= 1
