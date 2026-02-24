"""Converts high-level Claude test plans into fully executable TestCase objects."""

from __future__ import annotations

from smartqa.logging_config import get_logger
from smartqa.models import (
    ActionType,
    SelectorType,
    TestCase,
    TestPlan,
    TestStep,
)

logger = get_logger(__name__)

_ACTION_DURATION_ESTIMATES: dict[ActionType, float] = {
    ActionType.NAVIGATE: 3.0,
    ActionType.CLICK: 1.0,
    ActionType.TYPE: 1.5,
    ActionType.CLEAR: 0.5,
    ActionType.SELECT: 1.0,
    ActionType.HOVER: 0.5,
    ActionType.SUBMIT: 2.0,
    ActionType.WAIT: 2.0,
    ActionType.SCROLL: 1.0,
    ActionType.ASSERT_TEXT: 0.5,
    ActionType.ASSERT_VISIBLE: 0.5,
    ActionType.ASSERT_NOT_VISIBLE: 0.5,
    ActionType.ASSERT_URL: 0.5,
    ActionType.ASSERT_TITLE: 0.5,
    ActionType.ASSERT_ELEMENT_EXISTS: 0.5,
    ActionType.SCREENSHOT: 1.0,
}


class TestGenerator:
    """Enriches and validates test cases produced by the planner.

    The planner (Claude) returns high-level test scenarios.  This generator
    ensures every test case has:
    * a navigation step to the target URL (if missing)
    * at least one assertion
    * realistic duration estimates
    * properly resolved selectors
    """

    def generate(self, test_plan: TestPlan, url: str) -> list[TestCase]:
        """Return a list of fully executable TestCase objects."""
        logger.info("Generating executable tests from plan (%d raw cases)", len(test_plan.test_cases))

        enriched: list[TestCase] = []
        for tc in test_plan.test_cases:
            processed = self._enrich_test_case(tc, url)
            if processed is not None:
                enriched.append(processed)

        logger.info("Generated %d executable test cases", len(enriched))
        return enriched

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enrich_test_case(self, tc: TestCase, url: str) -> TestCase | None:
        """Add navigation step, compute duration, validate assertions."""
        steps = list(tc.steps)

        if not steps:
            logger.warning("Skipping test case '%s' — no steps defined", tc.name)
            return None

        if not self._has_navigate_step(steps):
            nav_step = TestStep(
                action=ActionType.NAVIGATE,
                value=url,
                description=f"Navigate to {url}",
            )
            steps.insert(0, nav_step)

        if not self._has_assertion(steps):
            steps.append(
                TestStep(
                    action=ActionType.ASSERT_VISIBLE,
                    selector="body",
                    selector_type=SelectorType.TAG_NAME,
                    expected_result="Page body is visible",
                    description="Verify page loaded",
                )
            )

        steps = self._resolve_selectors(steps)
        estimated_duration = self._estimate_duration(steps)

        return TestCase(
            name=tc.name,
            description=tc.description,
            category=tc.category,
            steps=steps,
            priority_score=tc.priority_score,
            risk_level=tc.risk_level,
            tags=tc.tags if tc.tags else self._infer_tags(tc),
            estimated_duration_seconds=estimated_duration,
            preconditions=tc.preconditions,
        )

    @staticmethod
    def _has_navigate_step(steps: list[TestStep]) -> bool:
        return any(s.action == ActionType.NAVIGATE for s in steps)

    @staticmethod
    def _has_assertion(steps: list[TestStep]) -> bool:
        assertion_actions = {
            ActionType.ASSERT_TEXT,
            ActionType.ASSERT_VISIBLE,
            ActionType.ASSERT_NOT_VISIBLE,
            ActionType.ASSERT_URL,
            ActionType.ASSERT_TITLE,
            ActionType.ASSERT_ELEMENT_EXISTS,
        }
        return any(s.action in assertion_actions for s in steps)

    @staticmethod
    def _resolve_selectors(steps: list[TestStep]) -> list[TestStep]:
        """Normalize selectors: if an ID is embedded in a CSS selector, extract it."""
        resolved: list[TestStep] = []
        for step in steps:
            selector = step.selector
            selector_type = step.selector_type

            if selector.startswith("#") and " " not in selector and selector_type == SelectorType.CSS:
                selector_type = SelectorType.ID
                selector = selector.lstrip("#")

            resolved.append(
                TestStep(
                    action=step.action,
                    selector=selector,
                    selector_type=selector_type,
                    value=step.value,
                    expected_result=step.expected_result,
                    timeout_seconds=step.timeout_seconds,
                    description=step.description,
                )
            )
        return resolved

    @staticmethod
    def _estimate_duration(steps: list[TestStep]) -> float:
        return sum(
            _ACTION_DURATION_ESTIMATES.get(s.action, 1.0) for s in steps
        )

    @staticmethod
    def _infer_tags(tc: TestCase) -> list[str]:
        tags: list[str] = [tc.category.value]
        name_lower = tc.name.lower()
        if "login" in name_lower or "auth" in name_lower:
            tags.append("authentication")
        if "form" in name_lower or "submit" in name_lower:
            tags.append("forms")
        if "nav" in name_lower:
            tags.append("navigation")
        if "search" in name_lower:
            tags.append("search")
        return tags
