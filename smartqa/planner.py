"""Claude API integration for autonomous test plan generation."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import anthropic

from smartqa.logging_config import get_logger
from smartqa.models import (
    ActionType,
    PageAnalysis,
    RiskLevel,
    SelectorType,
    TestCase,
    TestCategory,
    TestPlan,
    TestStep,
)

if TYPE_CHECKING:
    from smartqa.config import Settings

logger = get_logger(__name__)

SYSTEM_PROMPT = """\
You are an expert QA engineer. Given a structured analysis of a web page, generate \
a comprehensive test plan in JSON format.

You MUST return a JSON object (no markdown fences) with this exact schema:

{
  "test_cases": [
    {
      "name": "string — short unique name",
      "description": "string — what the test validates",
      "category": "functional | edge_case | negative",
      "risk_level": "low | medium | high | critical",
      "tags": ["string"],
      "steps": [
        {
          "action": "<action_type>",
          "selector": "CSS or XPath selector",
          "selector_type": "css | xpath | id | name",
          "value": "text to type or expected value (if applicable)",
          "expected_result": "what should happen",
          "description": "human-readable step description"
        }
      ]
    }
  ],
  "coverage_summary": "string — brief summary of what the plan covers"
}

Valid action types: navigate, click, type, clear, select, hover, submit, wait, \
scroll, assert_text, assert_visible, assert_not_visible, assert_url, assert_title, \
assert_element_exists, screenshot.

Rules:
1. Generate functional tests for every form, button, and navigation link.
2. Generate edge-case tests (empty inputs, very long strings, special characters).
3. Generate negative tests (invalid emails, SQL injection strings, XSS payloads).
4. Use real selectors derived from the page analysis — prefer IDs, then names, \
   then CSS selectors.
5. Each test must have at least one assertion step.
6. Be concrete — no placeholder selectors.
"""


class TestPlanner:
    """Uses Claude to generate a structured test plan from page analysis data."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = anthropic.Anthropic(api_key=settings.claude_api_key)
        self._model = settings.claude_model

    def create_test_plan(self, page_analysis: PageAnalysis) -> TestPlan:
        """Send *page_analysis* to Claude and return a parsed TestPlan."""
        logger.info("Requesting test plan from Claude (%s)", self._model)
        analysis_json = page_analysis.model_dump_json(indent=2)

        raw_json = self._call_claude(analysis_json)
        test_plan = self._parse_response(raw_json, page_analysis)

        logger.info(
            "Test plan received — %d test cases generated", len(test_plan.test_cases)
        )
        return test_plan

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_claude(self, analysis_json: str) -> dict[str, Any]:
        """Call Claude API and return parsed JSON dict, retrying on failure."""
        user_message = (
            "Here is the page analysis. Generate a complete test plan.\n\n"
            f"{analysis_json}"
        )

        for attempt in range(1, self._settings.max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}],
                )
                text = response.content[0].text
                return self._extract_json(text)
            except anthropic.APIError as exc:
                logger.warning(
                    "Claude API error (attempt %d/%d): %s",
                    attempt,
                    self._settings.max_retries,
                    exc,
                )
                if attempt == self._settings.max_retries:
                    raise
            except (json.JSONDecodeError, KeyError, IndexError) as exc:
                logger.warning(
                    "Failed to parse Claude response (attempt %d/%d): %s",
                    attempt,
                    self._settings.max_retries,
                    exc,
                )
                if attempt == self._settings.max_retries:
                    raise ValueError(
                        f"Could not parse Claude response after {self._settings.max_retries} attempts"
                    ) from exc
        raise RuntimeError("Unreachable")

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Extract a JSON object from Claude's text, handling optional code fences."""
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        text = text.strip()
        return json.loads(text)

    @staticmethod
    def _parse_response(
        data: dict[str, Any], page_analysis: PageAnalysis
    ) -> TestPlan:
        """Convert raw Claude JSON into a validated TestPlan."""
        test_cases: list[TestCase] = []
        for tc_data in data.get("test_cases", []):
            steps = [
                TestStep(
                    action=ActionType(s.get("action", "click")),
                    selector=s.get("selector", ""),
                    selector_type=SelectorType(s.get("selector_type", "css")),
                    value=s.get("value", ""),
                    expected_result=s.get("expected_result", ""),
                    description=s.get("description", ""),
                )
                for s in tc_data.get("steps", [])
            ]
            test_cases.append(
                TestCase(
                    name=tc_data.get("name", "Unnamed Test"),
                    description=tc_data.get("description", ""),
                    category=TestCategory(tc_data.get("category", "functional")),
                    steps=steps,
                    risk_level=RiskLevel(tc_data.get("risk_level", "medium")),
                    tags=tc_data.get("tags", []),
                )
            )

        return TestPlan(
            url=page_analysis.url,
            test_cases=test_cases,
            coverage_summary=data.get("coverage_summary", ""),
            page_analysis=page_analysis,
        )
