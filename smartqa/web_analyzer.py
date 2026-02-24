"""Selenium-based web page analyzer that extracts interactive elements."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
)

from smartqa.logging_config import get_logger
from smartqa.models import ElementInfo, FormInfo, PageAnalysis

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement
    from smartqa.config import Settings

logger = get_logger(__name__)


class WebAnalyzer:
    """Inspects a web page and extracts structured information about its interactive elements."""

    def __init__(self, driver: WebDriver, settings: Settings) -> None:
        self._driver = driver
        self._settings = settings
        self._timeout = settings.timeout_seconds

    def analyze(self, url: str) -> PageAnalysis:
        """Navigate to *url* and return a full page analysis."""
        logger.info("Analyzing page: %s", url)
        start = time.perf_counter()

        self._driver.get(url)
        self._wait_for_page_load()

        title = self._driver.title or ""
        meta_description = self._extract_meta_description()
        forms = self._extract_forms()
        buttons = self._extract_elements("button", By.TAG_NAME)
        buttons += self._extract_elements("input[type='submit']", By.CSS_SELECTOR)
        buttons += self._extract_elements("input[type='button']", By.CSS_SELECTOR)
        links = self._extract_elements("a", By.TAG_NAME)
        inputs = self._extract_elements(
            "input:not([type='submit']):not([type='button']):not([type='hidden'])",
            By.CSS_SELECTOR,
        )
        inputs += self._extract_elements("textarea", By.TAG_NAME)
        inputs += self._extract_elements("select", By.TAG_NAME)
        nav_elements = self._extract_elements("nav a", By.CSS_SELECTOR)
        images = self._extract_elements("img", By.TAG_NAME)
        headings = self._extract_headings()

        load_time_ms = (time.perf_counter() - start) * 1000
        total_interactive = len(forms) + len(buttons) + len(links) + len(inputs)

        analysis = PageAnalysis(
            url=url,
            title=title,
            meta_description=meta_description,
            forms=forms,
            buttons=buttons,
            links=links,
            inputs=inputs,
            navigation_elements=nav_elements,
            images=images,
            headings=headings,
            total_interactive_elements=total_interactive,
            page_load_time_ms=load_time_ms,
        )
        logger.info(
            "Analysis complete — %d interactive elements found in %.0f ms",
            total_interactive,
            load_time_ms,
        )
        return analysis

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _wait_for_page_load(self) -> None:
        try:
            WebDriverWait(self._driver, self._timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            logger.warning("Page load timed out after %d s", self._timeout)

    def _extract_meta_description(self) -> str:
        try:
            el = self._driver.find_element(
                By.CSS_SELECTOR, "meta[name='description']"
            )
            return el.get_attribute("content") or ""
        except WebDriverException:
            return ""

    def _element_to_info(self, el: WebElement) -> ElementInfo | None:
        try:
            return ElementInfo(
                tag=el.tag_name,
                element_id=el.get_attribute("id") or "",
                classes=(el.get_attribute("class") or "").split(),
                name=el.get_attribute("name") or "",
                element_type=el.get_attribute("type") or "",
                text=(el.text or "").strip()[:200],
                href=el.get_attribute("href") or "",
                placeholder=el.get_attribute("placeholder") or "",
                aria_label=el.get_attribute("aria-label") or "",
                value=el.get_attribute("value") or "",
                is_visible=el.is_displayed(),
            )
        except StaleElementReferenceException:
            return None

    def _extract_elements(self, selector: str, by: str) -> list[ElementInfo]:
        try:
            raw = self._driver.find_elements(by, selector)
        except WebDriverException:
            return []

        results: list[ElementInfo] = []
        for el in raw:
            info = self._element_to_info(el)
            if info is not None:
                results.append(info)
        return results

    def _extract_forms(self) -> list[FormInfo]:
        forms: list[FormInfo] = []
        try:
            form_elements = self._driver.find_elements(By.TAG_NAME, "form")
        except WebDriverException:
            return forms

        for form_el in form_elements:
            try:
                form_inputs: list[ElementInfo] = []
                for inp in form_el.find_elements(By.CSS_SELECTOR, "input, textarea, select"):
                    info = self._element_to_info(inp)
                    if info is not None:
                        form_inputs.append(info)

                form_buttons: list[ElementInfo] = []
                for btn in form_el.find_elements(
                    By.CSS_SELECTOR, "button, input[type='submit'], input[type='button']"
                ):
                    info = self._element_to_info(btn)
                    if info is not None:
                        form_buttons.append(info)

                forms.append(
                    FormInfo(
                        form_id=form_el.get_attribute("id") or "",
                        action=form_el.get_attribute("action") or "",
                        method=form_el.get_attribute("method") or "",
                        inputs=form_inputs,
                        buttons=form_buttons,
                    )
                )
            except StaleElementReferenceException:
                continue
        return forms

    def _extract_headings(self) -> list[ElementInfo]:
        headings: list[ElementInfo] = []
        for level in range(1, 7):
            headings.extend(
                self._extract_elements(f"h{level}", By.TAG_NAME)
            )
        return headings
