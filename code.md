import time
import os
import re
import json
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# --- CONFIGURATION ---
BASE_OUTPUT_DIR = "SAT_Question_Corpus"
CHROME_DRIVER_PATH = r"C:\Selenium\chromedriver.exe"

# IMPORTANT:
# - This script is written to be platform-agnostic (no brand/site names).
# - Update these URLs and selectors to match the target practice platform you have access to.
LOGIN_URL = "https://example.com/login"
DASHBOARD_URL = "https://example.com/practice-tests"


class SATAcquisitionBot:
    """
    Automated data acquisition pipeline for SAT-style question repositories.

    Core responsibilities:
    - Navigate a practice-test dashboard, open exams, iterate over questions.
    - Extract question text, answer options, difficulty/skill metadata (if exposed).
    - Parse MathML / embedded math markup into LaTeX-like linear notation.
    - Capture stimulus visuals (images/tables/figures) as local screenshots.
    - Export a structured JSON dataset suitable for downstream AI training.
    """

    def __init__(self):
        self._setup_folders()
        self.driver = self._setup_driver()
        self.wait = WebDriverWait(self.driver, 10)

    def _setup_folders(self):
        os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)

    def _setup_driver(self):
        options = webdriver.ChromeOptions()
        options.add_experimental_option("detach", True)
        options.add_argument("--start-maximized")
        options.page_load_strategy = "eager"  # faster navigation
        service = Service(CHROME_DRIVER_PATH)
        return webdriver.Chrome(service=service, options=options)

    # ---------------------------
    # MATH / TEXT NORMALIZATION
    # ---------------------------
    @staticmethod
    def parse_mathml_soup(tag):
        """Converts MathML structures into a compact LaTeX-like linear string."""
        if not tag:
            return ""
        if isinstance(tag, str):
            return tag.strip()

        if tag.name in ["mi", "mn", "mo", "mtext", "ms"]:
            return tag.get_text(strip=True)

        if tag.name in ["mrow", "math", "mstyle", "semantics"]:
            return "".join(SATAcquisitionBot.parse_mathml_soup(child) for child in tag.children)

        if tag.name == "mfrac":
            children = [c for c in tag.children if (getattr(c, "name", None) or isinstance(c, str))]
            children = [c for c in children if str(c).strip()]
            if len(children) >= 2:
                num = SATAcquisitionBot.parse_mathml_soup(children[0]).strip()
                den = SATAcquisitionBot.parse_mathml_soup(children[1]).strip()
                return f"\\frac{{{num}}}{{{den}}}"

        if tag.name == "msup":
            children = [c for c in tag.children if (getattr(c, "name", None) or isinstance(c, str))]
            children = [c for c in children if str(c).strip()]
            if len(children) >= 2:
                base = SATAcquisitionBot.parse_mathml_soup(children[0]).strip()
                exp = SATAcquisitionBot.parse_mathml_soup(children[1]).strip()
                return f"{base}^{exp}"

        if tag.name == "msqrt":
            inner = "".join(SATAcquisitionBot.parse_mathml_soup(child) for child in tag.children).strip()
            return f"sqrt({inner})"

        if tag.name == "mfenced":
            open_char = tag.get("open", "(")
            close_char = tag.get("close", ")")
            inner = "".join(SATAcquisitionBot.parse_mathml_soup(child) for child in tag.children).strip()
            return f"{open_char}{inner}{close_char}"

        return "".join(SATAcquisitionBot.parse_mathml_soup(child) for child in tag.children)

    def _html_to_clean_text(self, html_content: str) -> str:
        """Removes non-content UI artifacts and converts math to linear notation."""
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, "html.parser")

        # Remove common non-question UI blocks (generic)
        for tag in soup.find_all(["svg", "table", "img", "figure", "style", "script"]):
            tag.decompose()

        for tag in soup.find_all(class_=["sr-only", "mjx-assistive-mathml", "MathJax_Preview"]):
            tag.decompose()

        # Remove invisible / transparent text (generic watermarking or UI artifacts)
        for tag in soup.find_all(attrs={"style": re.compile(r"color:\s*transparent", re.IGNORECASE)}):
            tag.decompose()

        # Convert <math> blocks
        for math in soup.find_all("math"):
            converted = self.parse_mathml_soup(math)
            math.replace_with(f" {converted} ")

        # Convert spans that store math in attributes (generic pattern)
        for span in soup.find_all("span", attrs={"data-mathml": True}):
            try:
                mathml_str = span["data-mathml"]
                if "<math" not in mathml_str:
                    mathml_str = f"<math>{mathml_str}</math>"
                math_soup = BeautifulSoup(mathml_str, "xml")
                converted = self.parse_mathml_soup(math_soup)
                span.replace_with(f" {converted} ")
            except Exception:
                pass

        text = soup.get_text(separator=" ", strip=True)
        return self._final_text_cleanup(text)

    @staticmethod
    def _final_text_cleanup(text: str) -> str:
        """Final pass: normalize whitespace and remove generic boilerplate strings."""
        if not text:
            return ""

        # Generic UI phrases often present in explanation modals (keep broad, non-site-specific)
        patterns = [
            r"Step-by-step\s*explanation",
            r"Step\s*by\s*step",
            r"Full\s*explanation",
            r"Explanation",
            r"Question\s*Info",
            r"Section",
            r"Score\s*Band",
        ]
        for pat in patterns:
            text = re.sub(pat, "", text, flags=re.IGNORECASE | re.MULTILINE)

        # Normalize math symbols
        text = text.replace("−", "-").replace("×", "*").replace("÷", "/")

        # Collapse whitespace
        return re.sub(r"\s+", " ", text).strip()

    # ---------------------------
    # PAGE INTERACTIONS
    # ---------------------------
    def _get_question_metadata(self):
        """
        Attempts to extract metadata (domain/skill/difficulty) if the UI exposes it.
        Implementation is intentionally generic; selectors may need adaptation.
        """
        meta = {"domain": "", "skill": "", "difficulty": ""}
        try:
            # Example pattern: open an "info" modal near an "Ask" or "Help" button
            help_buttons = self.driver.find_elements(By.XPATH, "//button[contains(., 'Ask') or contains(., 'Help')]")
            if help_buttons:
                info_btn = help_buttons[0].find_element(By.XPATH, "./preceding-sibling::button")
                self.driver.execute_script("arguments[0].click();", info_btn)

                modal = self.wait.until(
                    EC.visibility_of_element_located((By.XPATH, "//div[@role='dialog']"))
                )
                text = modal.text

                m_diff = re.search(r"Difficulty\s*\n\s*(.+?)(?:\n|$)", text)
                m_dom = re.search(r"Domain\s*\n\s*(.+?)(?:\n|$)", text)
                m_skill = re.search(r"Skill\s*\n\s*(.+?)(?:\n|$)", text)
                if m_diff:
                    meta["difficulty"] = m_diff.group(1).strip()
                if m_dom:
                    meta["domain"] = m_dom.group(1).strip()
                if m_skill:
                    meta["skill"] = m_skill.group(1).strip()

                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
        return meta

    def _open_explanation_modal(self) -> bool:
        """Opens the explanation modal if available."""
        try:
            candidates = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Explanation')]")
            if not candidates:
                # Fallback for icon-only buttons (generic)
                candidates = self.driver.find_elements(By.CSS_SELECTOR, "button svg")

            if candidates:
                target = candidates[-1]
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
                self.driver.execute_script("arguments[0].click();", target)
                self.wait.until(EC.visibility_of_element_located((By.XPATH, "//div[@role='dialog']")))
                return True
        except Exception:
            pass
        return False

    def _get_explanation_text(self) -> str:
        """Reads explanation modal content as clean text."""
        try:
            if not self._open_explanation_modal():
                return "Error: Explanation UI not found."

            modal = self.driver.find_element(By.XPATH, "//div[@role='dialog']")
            raw_html = modal.get_attribute("innerHTML")
            cleaned = self._html_to_clean_text(raw_html)

            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            return cleaned
        except Exception:
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            return "Error: Failed to extract explanation."

    def _exit_exam(self):
        """Returns from an exam view back to the dashboard (generic back arrow pattern)."""
        try:
            back = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//a[.//svg[contains(@class, 'lucide-arrow-left')]]"))
            )
            try:
                back.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", back)

            self.wait.until(EC.url_contains("practice-tests"))
            return True
        except Exception:
            # fallback: navigate directly
            self.driver.get(DASHBOARD_URL)
            return False

    # ---------------------------
    # SCRAPING: SINGLE EXAM
    # ---------------------------
    def scrape_single_exam(self, exam_name: str):
        safe_name = re.sub(r'[\\/*?:"<>|]', "", exam_name).strip() or "Exam"
        exam_dir = os.path.join(BASE_OUTPUT_DIR, safe_name)
        img_dir = os.path.join(exam_dir, "images")
        os.makedirs(img_dir, exist_ok=True)

        print(f"\n>>> START EXAM EXPORT: {safe_name}")

        q_index = 1
        dataset = []
        last_stem_text = ""

        while True:
            try:
                print(f"--- Question {q_index} ---")

                # Wait until question stem is present
                try:
                    stem = self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "question-stem")))
                except Exception:
                    print(">>> Question not found. Exam may be finished.")
                    self._exit_exam()
                    break

                # Duplicate guard (fast)
                stem_text = (stem.text or "").strip()
                if stem_text == last_stem_text and last_stem_text:
                    time.sleep(0.5)
                    continue
                last_stem_text = stem_text

                # Metadata
                meta = self._get_question_metadata()
                question_type = f"{meta.get('domain','')}: {meta.get('skill','')}".strip(": ").strip()

                # Capture visuals if present (generic stimulus selectors)
                image_paths = []
                try:
                    visuals = self.driver.find_elements(
                        By.CSS_SELECTOR,
                        "figure.image, .question-stimulus img, .question-stimulus svg, .question-stimulus table"
                    )
                    v_i = 1
                    for el in visuals:
                        if el.is_displayed() and el.size.get("width", 0) > 30:
                            filename = f"Q{q_index}_{v_i}.png"
                            path = os.path.join(img_dir, filename)
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                            el.screenshot(path)
                            image_paths.append(f"images/{filename}")
                            v_i += 1
                except Exception:
                    pass

                # Question text (stimulus + stem)
                question_text = ""
                try:
                    stimulus_elems = self.driver.find_elements(By.CLASS_NAME, "question-stimulus")
                    stimulus_html = stimulus_elems[0].get_attribute("innerHTML") if stimulus_elems else ""
                    stem_html = stem.get_attribute("innerHTML")

                    stimulus_text = self._html_to_clean_text(stimulus_html) if stimulus_html else ""
                    stem_clean = self._html_to_clean_text(stem_html) if stem_html else ""

                    question_text = stimulus_text if stem_clean and stem_clean in stimulus_text else f"{stimulus_text} {stem_clean}".strip()
                except Exception:
                    question_text = stem_text

                # Options (A-D)
                options = []
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, "div[role='button']")
                    labels = ["A", "B", "C", "D"]
                    c = 0
                    for btn in buttons:
                        if c > 3:
                            break
                        raw = self._html_to_clean_text(btn.get_attribute("innerHTML"))
                        if not raw:
                            continue
                        if any(x.lower() in raw.lower() for x in ["mark", "review"]):
                            continue
                        # Strip leading letter if the platform repeats it
                        if len(raw) > 1 and raw[0] in labels:
                            raw = raw[1:].strip()
                        options.append(f"{labels[c]}) {raw}")
                        c += 1
                except Exception:
                    pass

                # Explanation (modal)
                explanation = self._get_explanation_text()

                record = {
                    "id": f"Q{q_index}",
                    "question_type": question_type,
                    "difficulty": meta.get("difficulty", ""),
                    "question_text": question_text,
                    "options": options,
                    "solution_rationale": explanation,
                    "image_paths": image_paths
                }
                dataset.append(record)

                with open(os.path.join(exam_dir, "questions.json"), "w", encoding="utf-8") as f:
                    json.dump(dataset, f, ensure_ascii=False, indent=2)

                print(f">>> Question {q_index} saved.")

                # Next button
                try:
                    nxt = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'Next')]")
                    if nxt:
                        self.driver.execute_script("arguments[0].click();", nxt[0])
                        q_index += 1
                        # Wait for stem refresh (no fixed sleep)
                        try:
                            self.wait.until(EC.staleness_of(stem))
                        except Exception:
                            pass
                    else:
                        print(">>> Next button not found. End of exam.")
                        self._exit_exam()
                        break
                except Exception:
                    print(">>> Next navigation failed. Exiting exam.")
                    self._exit_exam()
                    break

            except Exception as e:
                print(f"General error: {e}")
                self._exit_exam()
                break

    # ---------------------------
    # SCRAPING: DASHBOARD LOOP
    # ---------------------------
    def run_dashboard_loop(self):
        self.driver.get(DASHBOARD_URL)
        print(">>> Dashboard loaded. Scanning exams...")

        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))

        try:
            rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr")
            total = len(rows)
            print(f">>> Found {total} exams on this page.")
        except Exception:
            print("!!! Dashboard table not found.")
            return

        for i in range(total):
            try:
                print(f"\n=== Exam {i+1}/{total} ===")

                current_rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr")
                if i >= len(current_rows):
                    break
                row = current_rows[i]

                # Exam name (generic: first columns)
                exam_name = f"Exam_{i+1}"
                try:
                    first = row.find_element(By.CSS_SELECTOR, "td:first-child").text.strip()
                    second = row.find_element(By.CSS_SELECTOR, "td:nth-child(2)").text.strip()
                    exam_name = f"{first}_{second}".strip("_")
                except Exception:
                    pass

                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                time.sleep(0.5)  # minimal UI scroll stabilization

                try:
                    row.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", row)

                self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "question-stem")))
                self.scrape_single_exam(exam_name)

                # Back on dashboard, ensure table present
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))

            except Exception as e:
                print(f"!!! Loop error: {e}")
                self.driver.get(DASHBOARD_URL)
                continue

    def start(self):
        self.driver.get(LOGIN_URL)
        print(">>> Please log in manually, then press ENTER here to continue...")
        input()
        self.run_dashboard_loop()


if __name__ == "__main__":
    bot = SATAcquisitionBot()
    bot.start()
