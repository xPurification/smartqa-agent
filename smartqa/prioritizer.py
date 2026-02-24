"""Risk-based test case prioritization engine."""

from __future__ import annotations

from smartqa.logging_config import get_logger
from smartqa.models import (
    ActionType,
    PageAnalysis,
    RiskLevel,
    TestCase,
    TestCategory,
)

logger = get_logger(__name__)

_WEIGHT_ELEMENT_IMPORTANCE = 0.30
_WEIGHT_PAGE_CRITICALITY = 0.25
_WEIGHT_FAILURE_PROBABILITY = 0.25
_WEIGHT_INTERACTION_FREQUENCY = 0.20

_CRITICAL_PAGE_KEYWORDS = frozenset({
    "login", "signin", "sign-in", "signup", "sign-up", "register",
    "checkout", "payment", "billing", "account", "password", "auth",
    "admin", "dashboard", "settings", "profile", "delete", "remove",
})

_HIGH_RISK_ACTIONS = frozenset({
    ActionType.SUBMIT,
    ActionType.TYPE,
    ActionType.SELECT,
    ActionType.CLICK,
})


class TestPrioritizer:
    """Scores and ranks test cases by risk and importance."""

    def prioritize(
        self,
        test_cases: list[TestCase],
        page_analysis: PageAnalysis,
    ) -> list[TestCase]:
        """Return *test_cases* sorted by computed priority score (descending)."""
        logger.info("Prioritizing %d test cases", len(test_cases))
        scored: list[TestCase] = []

        for tc in test_cases:
            score = self._compute_score(tc, page_analysis)
            risk = self._score_to_risk_level(score)
            scored.append(
                tc.model_copy(update={"priority_score": round(score, 1), "risk_level": risk})
            )

        scored.sort(key=lambda t: t.priority_score, reverse=True)

        for i, tc in enumerate(scored, 1):
            logger.debug(
                "  #%d  %.1f  %s  %s", i, tc.priority_score, tc.risk_level.value, tc.name
            )

        logger.info(
            "Prioritization complete — top score: %.1f, bottom score: %.1f",
            scored[0].priority_score if scored else 0,
            scored[-1].priority_score if scored else 0,
        )
        return scored

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_score(self, tc: TestCase, analysis: PageAnalysis) -> float:
        e = self._element_importance_score(tc)
        p = self._page_criticality_score(tc, analysis)
        f = self._failure_probability_score(tc)
        i = self._interaction_frequency_score(tc, analysis)

        return (
            e * _WEIGHT_ELEMENT_IMPORTANCE
            + p * _WEIGHT_PAGE_CRITICALITY
            + f * _WEIGHT_FAILURE_PROBABILITY
            + i * _WEIGHT_INTERACTION_FREQUENCY
        ) * 100

    @staticmethod
    def _element_importance_score(tc: TestCase) -> float:
        """Forms and submissions score highest; pure assertions score lowest."""
        action_scores: dict[ActionType, float] = {
            ActionType.SUBMIT: 1.0,
            ActionType.TYPE: 0.9,
            ActionType.SELECT: 0.85,
            ActionType.CLICK: 0.7,
            ActionType.NAVIGATE: 0.5,
            ActionType.HOVER: 0.3,
            ActionType.SCROLL: 0.2,
        }
        if not tc.steps:
            return 0.3

        max_score = max(
            action_scores.get(step.action, 0.2)
            for step in tc.steps
        )
        return max_score

    @staticmethod
    def _page_criticality_score(tc: TestCase, analysis: PageAnalysis) -> float:
        """Higher score when the test involves critical pages (login, payment, etc.)."""
        text_blob = (
            tc.name + " " + tc.description + " " + analysis.url + " " + analysis.title
        ).lower()

        matches = sum(1 for kw in _CRITICAL_PAGE_KEYWORDS if kw in text_blob)
        if matches >= 3:
            return 1.0
        if matches >= 2:
            return 0.85
        if matches >= 1:
            return 0.6
        return 0.3

    @staticmethod
    def _failure_probability_score(tc: TestCase) -> float:
        """Edge-case and negative tests have a higher probability of exposing failures."""
        category_scores = {
            TestCategory.NEGATIVE: 0.95,
            TestCategory.EDGE_CASE: 0.85,
            TestCategory.REGRESSION: 0.7,
            TestCategory.FUNCTIONAL: 0.5,
            TestCategory.SMOKE: 0.3,
        }
        base = category_scores.get(tc.category, 0.5)

        high_risk_step_count = sum(
            1 for s in tc.steps if s.action in _HIGH_RISK_ACTIONS
        )
        step_bonus = min(high_risk_step_count * 0.05, 0.15)

        return min(base + step_bonus, 1.0)

    @staticmethod
    def _interaction_frequency_score(tc: TestCase, analysis: PageAnalysis) -> float:
        """Approximate how frequently the tested elements are likely to be used."""
        if analysis.total_interactive_elements == 0:
            return 0.5

        matched = 0
        all_selectors = {s.selector.lower() for s in tc.steps if s.selector}

        for element in analysis.buttons + analysis.links + analysis.inputs:
            identifiers = {
                element.element_id.lower(),
                element.name.lower(),
                element.text.lower()[:50],
            }
            identifiers.update(c.lower() for c in element.classes)
            if all_selectors & identifiers:
                matched += 1

        if matched == 0:
            return 0.5
        ratio = matched / max(len(all_selectors), 1)
        return min(0.4 + ratio * 0.6, 1.0)

    @staticmethod
    def _score_to_risk_level(score: float) -> RiskLevel:
        if score >= 75:
            return RiskLevel.CRITICAL
        if score >= 55:
            return RiskLevel.HIGH
        if score >= 35:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
