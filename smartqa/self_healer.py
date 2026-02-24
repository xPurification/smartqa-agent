"""Self-healing selector engine — retries failing selectors with fallback strategies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    NoSuchElementException,
    WebDriverException,
)

from smartqa.logging_config import get_logger
from smartqa.models import HealResult, SelectorHealRecord, SelectorType

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from smartqa.config import Settings

logger = get_logger(__name__)

_SELECTOR_TYPE_TO_BY: dict[SelectorType, str] = {
    SelectorType.CSS: By.CSS_SELECTOR,
    SelectorType.XPATH: By.XPATH,
    SelectorType.ID: By.ID,
    SelectorType.NAME: By.NAME,
    SelectorType.CLASS_NAME: By.CLASS_NAME,
    SelectorType.TAG_NAME: By.TAG_NAME,
    SelectorType.LINK_TEXT: By.LINK_TEXT,
    SelectorType.PARTIAL_LINK_TEXT: By.PARTIAL_LINK_TEXT,
}


def selector_type_to_by(st: SelectorType) -> str:
    return _SELECTOR_TYPE_TO_BY[st]


class _HealContext:
    """Bundles all contextual hints passed to healing strategies."""

    __slots__ = (
        "original_selector",
        "selector_type",
        "element_text",
        "element_name",
        "element_id",
        "aria_label",
        "placeholder",
    )

    def __init__(
        self,
        original_selector: str,
        selector_type: SelectorType,
        element_text: str,
        element_name: str,
        element_id: str,
        aria_label: str,
        placeholder: str,
    ) -> None:
        self.original_selector = original_selector
        self.selector_type = selector_type
        self.element_text = element_text
        self.element_name = element_name
        self.element_id = element_id
        self.aria_label = aria_label
        self.placeholder = placeholder


class _StrategyResult:
    """Outcome of a single healing strategy attempt."""

    __slots__ = ("selector", "selector_type", "strategy_name", "confidence")

    def __init__(
        self,
        selector: str,
        selector_type: SelectorType,
        strategy_name: str,
        confidence: float,
    ) -> None:
        self.selector = selector
        self.selector_type = selector_type
        self.strategy_name = strategy_name
        self.confidence = confidence


class SelfHealer:
    """Attempts to locate an element via a chain of fallback strategies when the
    primary selector fails.

    Strategies (tried in order):
    1. Alternative selector types derived from the original (CSS <-> XPath, ID, name).
    2. Text-content matching via XPath ``contains(text(), ...)``.
    3. Attribute matching (aria-label, placeholder, title, data-testid).
    4. Partial class-name matching.
    """

    def __init__(self, settings: Settings) -> None:
        self._max_attempts = settings.heal_attempts

    def heal(
        self,
        driver: WebDriver,
        original_selector: str,
        selector_type: SelectorType,
        *,
        element_text: str = "",
        element_name: str = "",
        element_id: str = "",
        aria_label: str = "",
        placeholder: str = "",
    ) -> HealResult:
        """Try to find the element using fallback strategies.

        Returns a ``HealResult`` with ``success=True`` and the working selector
        if any strategy succeeds.
        """
        logger.info(
            "Self-healing triggered for selector '%s' (type=%s)",
            original_selector,
            selector_type.value,
        )

        context = _HealContext(
            original_selector=original_selector,
            selector_type=selector_type,
            element_text=element_text,
            element_name=element_name,
            element_id=element_id,
            aria_label=aria_label,
            placeholder=placeholder,
        )

        strategies: list[
            Callable[[WebDriver, _HealContext], _StrategyResult | None]
        ] = [
            self._try_alternative_selectors,
            self._try_text_match,
            self._try_attribute_match,
            self._try_partial_class_match,
        ]

        records: list[SelectorHealRecord] = []
        attempts = 0

        for strategy in strategies:
            if attempts >= self._max_attempts:
                break
            result = strategy(driver, context)
            attempts += 1
            if result is not None:
                record = SelectorHealRecord(
                    original_selector=original_selector,
                    original_selector_type=selector_type,
                    healed_selector=result.selector,
                    healed_selector_type=result.selector_type,
                    strategy_used=result.strategy_name,
                    confidence=result.confidence,
                )
                records.append(record)
                logger.info(
                    "Healed selector '%s' -> '%s' via %s (confidence=%.2f)",
                    original_selector,
                    result.selector,
                    result.strategy_name,
                    result.confidence,
                )
                return HealResult(
                    success=True,
                    healed_selector=result.selector,
                    healed_selector_type=result.selector_type,
                    strategy_used=result.strategy_name,
                    confidence=result.confidence,
                    attempts=attempts,
                    records=records,
                )

        logger.warning(
            "Self-healing failed for selector '%s' after %d attempts",
            original_selector,
            attempts,
        )
        return HealResult(success=False, attempts=attempts, records=records)

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _try_alternative_selectors(
        self, driver: WebDriver, ctx: _HealContext
    ) -> _StrategyResult | None:
        """Try ID, name, or a converted CSS/XPath selector."""
        candidates: list[tuple[str, SelectorType, float]] = []

        if ctx.element_id and ctx.selector_type != SelectorType.ID:
            candidates.append((ctx.element_id, SelectorType.ID, 0.95))

        if ctx.element_name and ctx.selector_type != SelectorType.NAME:
            candidates.append((ctx.element_name, SelectorType.NAME, 0.85))

        if ctx.selector_type == SelectorType.CSS:
            xpath = self._css_to_simple_xpath(ctx.original_selector)
            if xpath:
                candidates.append((xpath, SelectorType.XPATH, 0.6))
        elif ctx.selector_type == SelectorType.XPATH:
            css = self._xpath_to_simple_css(ctx.original_selector)
            if css:
                candidates.append((css, SelectorType.CSS, 0.6))

        for selector, stype, confidence in candidates:
            if self._can_find(driver, selector, stype):
                return _StrategyResult(
                    selector=selector,
                    selector_type=stype,
                    strategy_name="alternative_selector",
                    confidence=confidence,
                )
        return None

    def _try_text_match(
        self, driver: WebDriver, ctx: _HealContext
    ) -> _StrategyResult | None:
        """Locate an element by its visible text content."""
        if not ctx.element_text:
            return None

        safe_text = ctx.element_text.replace("'", "\\'")
        xpath = f"//*[contains(normalize-space(text()), '{safe_text}')]"
        if self._can_find(driver, xpath, SelectorType.XPATH):
            return _StrategyResult(
                selector=xpath,
                selector_type=SelectorType.XPATH,
                strategy_name="text_content_match",
                confidence=0.7,
            )
        return None

    def _try_attribute_match(
        self, driver: WebDriver, ctx: _HealContext
    ) -> _StrategyResult | None:
        """Search by aria-label, placeholder, title, or data-testid."""
        attr_candidates: list[tuple[str, str, float]] = []

        if ctx.aria_label:
            attr_candidates.append(("aria-label", ctx.aria_label, 0.8))
        if ctx.placeholder:
            attr_candidates.append(("placeholder", ctx.placeholder, 0.75))

        for attr_name, attr_value, confidence in attr_candidates:
            safe_val = attr_value.replace("'", "\\'")
            xpath = f"//*[@{attr_name}='{safe_val}']"
            if self._can_find(driver, xpath, SelectorType.XPATH):
                return _StrategyResult(
                    selector=xpath,
                    selector_type=SelectorType.XPATH,
                    strategy_name=f"attribute_match_{attr_name}",
                    confidence=confidence,
                )
        return None

    def _try_partial_class_match(
        self, driver: WebDriver, ctx: _HealContext
    ) -> _StrategyResult | None:
        """Extract class tokens from the original selector and match partially."""
        classes = self._extract_classes_from_selector(ctx.original_selector)
        if not classes:
            return None

        for cls in classes:
            safe = cls.replace("'", "\\'")
            xpath = f"//*[contains(@class, '{safe}')]"
            try:
                elements = driver.find_elements(By.XPATH, xpath)
                if len(elements) == 1:
                    return _StrategyResult(
                        selector=xpath,
                        selector_type=SelectorType.XPATH,
                        strategy_name="partial_class_match",
                        confidence=0.55,
                    )
            except WebDriverException:
                continue
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _can_find(driver: WebDriver, selector: str, stype: SelectorType) -> bool:
        by = selector_type_to_by(stype)
        try:
            driver.find_element(by, selector)
            return True
        except (NoSuchElementException, WebDriverException):
            return False

    @staticmethod
    def _css_to_simple_xpath(css: str) -> str | None:
        """Convert trivial CSS selectors to XPath (tag, #id, .class only)."""
        css = css.strip()
        if css.startswith("#"):
            return f"//*[@id='{css[1:]}']"
        if css.startswith("."):
            class_name = css[1:].split(".")[0]
            return f"//*[contains(@class, '{class_name}')]"
        if css.isalpha():
            return f"//{css}"
        return None

    @staticmethod
    def _xpath_to_simple_css(xpath: str) -> str | None:
        """Convert trivial XPath expressions back to CSS."""
        if xpath.startswith("//*[@id='") and xpath.endswith("']"):
            id_val = xpath[len("//*[@id='"):-len("']")]
            return f"#{id_val}"
        return None

    @staticmethod
    def _extract_classes_from_selector(selector: str) -> list[str]:
        """Pull class names out of a CSS selector like '.foo.bar'."""
        if "." not in selector:
            return []
        parts = selector.split(".")
        return [p.strip() for p in parts if p.strip() and not p.startswith("#")]
