import os, re, json, time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

OUTPUT_DIR = "SAT_Question_Corpus"
CHROMEDRIVER_PATH = r"C:\Selenium\chromedriver.exe"
LOGIN_URL = "https://example.com/login"
DASHBOARD_URL = "https://example.com/practice-tests"

class SATBot:
    def __init__(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        opts = webdriver.ChromeOptions()
        opts.add_argument("--start-maximized")
        opts.page_load_strategy = "eager"
        self.driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=opts)
        self.wait = WebDriverWait(self.driver, 10)

    # --- MathML -> linear text (minimal) ---
    @staticmethod
    def parse_math(tag):
        if not tag: return ""
        if isinstance(tag, str): return tag.strip()
        if tag.name in ["mi","mn","mo","mtext"]: return tag.get_text(strip=True)
        if tag.name in ["math","mrow","mstyle","semantics"]:
            return "".join(SATBot.parse_math(c) for c in tag.children)
        if tag.name == "mfrac":
            ch = [c for c in tag.children if str(c).strip()]
            if len(ch) >= 2:
                return f"\\frac{{{SATBot.parse_math(ch[0])}}}{{{SATBot.parse_math(ch[1])}}}"
        if tag.name == "msup":
            ch = [c for c in tag.children if str(c).strip()]
            if len(ch) >= 2:
                return f"{SATBot.parse_math(ch[0])}^{SATBot.parse_math(ch[1])}"
        return "".join(SATBot.parse_math(c) for c in tag.children)

    def html_to_text(self, html):
        if not html: return ""
        soup = BeautifulSoup(html, "html.parser")
        for t in soup.find_all(["svg","style","script"]): t.decompose()
        for m in soup.find_all("math"):
            m.replace_with(f" {self.parse_math(m)} ")
        text = soup.get_text(" ", strip=True)
        text = text.replace("−","-").replace("×","*").replace("÷","/")
        return re.sub(r"\s+"," ",text).strip()

    def get_explanation(self):
        try:
            btn = self.driver.find_elements(By.XPATH, "//*[contains(text(),'Explanation')]")
            if not btn: return ""
            self.driver.execute_script("arguments[0].click();", btn[-1])
            modal = self.wait.until(EC.visibility_of_element_located((By.XPATH, "//div[@role='dialog']")))
            txt = self.html_to_text(modal.get_attribute("innerHTML"))
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            return txt
        except:
            try: ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except: pass
            return ""

    def scrape_exam(self, exam_name):
        safe = re.sub(r'[\\/*?:"<>|]', "", exam_name).strip() or "Exam"
        exam_dir = os.path.join(OUTPUT_DIR, safe)
        os.makedirs(exam_dir, exist_ok=True)

        data, i = [], 1
        while True:
            try:
                stem = self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "question-stem")))
            except:
                break

            stimulus = self.driver.find_elements(By.CLASS_NAME, "question-stimulus")
            stimulus_html = stimulus[0].get_attribute("innerHTML") if stimulus else ""
            q_text = (self.html_to_text(stimulus_html) + " " + self.html_to_text(stem.get_attribute("innerHTML"))).strip()

            opts = []
            labels = ["A","B","C","D"]
            buttons = self.driver.find_elements(By.CSS_SELECTOR, "div[role='button']")
            c = 0
            for b in buttons:
                if c > 3: break
                t = self.html_to_text(b.get_attribute("innerHTML"))
                if not t: continue
                opts.append(f"{labels[c]}) {t}")
                c += 1

            exp = self.get_explanation()

            data.append({
                "id": f"Q{i}",
                "question_text": q_text,
                "options": opts,
                "solution_rationale": exp
            })

            with open(os.path.join(exam_dir, "questions.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            nxt = self.driver.find_elements(By.XPATH, "//a[contains(text(),'Next')]")
            if not nxt: break
            self.driver.execute_script("arguments[0].click();", nxt[0])
            i += 1
            try: self.wait.until(EC.staleness_of(stem))
            except: pass

    def run(self):
        self.driver.get(LOGIN_URL)
        print("Log in manually, then press ENTER here...")
        input()

        self.driver.get(DASHBOARD_URL)
        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))
        rows = self.driver.find_elements(By.CSS_SELECTOR, "tbody tr")

        for idx, row in enumerate(rows, start=1):
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", row)
            time.sleep(0.3)
            row.click()
            self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "question-stem")))
            self.scrape_exam(f"Exam_{idx}")
            self.driver.get(DASHBOARD_URL)
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))

if __name__ == "__main__":
    SATBot().run()
