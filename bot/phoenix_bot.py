"""
Phoenix Bot â€” Cloud Version
============================
Runs on GitHub Actions (headless Chrome).
Reads user config, logs into CricJoin, grabs the slot,
updates status and advances the next registration date by 7 days.

Usage:
    python bot/phoenix_bot.py configs/user1.json
"""

import json
import os
import sys
import re
import time
from datetime import datetime, timedelta

print("ðŸ”¥  Phoenix Bot starting...", flush=True)

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        NoSuchElementException, TimeoutException, ElementClickInterceptedException
    )
    from webdriver_manager.chrome import ChromeDriverManager
    print("âœ…  Selenium imported successfully", flush=True)
except ImportError as e:
    print(f"âŒ  Missing selenium: {e}", flush=True)
    sys.exit(1)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  HELPERS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize(text):
    return text.strip().lower()


def time_to_24h(time_str):
    time_str = time_str.strip()
    for fmt in ("%H:%M", "%I:%M %p", "%I %p", "%I:%M%p"):
        try:
            return datetime.strptime(time_str, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return time_str


def is_slot_full(slot_text):
    """Returns True if slot is full (e.g. 36/36, 27/27)"""
    matches = re.findall(r'(\d+)\s*/\s*(\d+)', slot_text)
    for current, maximum in matches:
        if int(current) >= int(maximum):
            return True
    return False


def is_waitlist(text):
    """Returns True if button/slot is a waitlist option"""
    return 'waitlist' in normalize(text)


def _time_to_minutes(text):
    """First clock time found in text -> minutes since midnight, else None."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*([ap])\.?m", text.lower())
    if m:
        hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3)
        if ap == "p" and hh != 12:
            hh += 12
        if ap == "a" and hh == 12:
            hh = 0
        return hh * 60 + mm
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def slot_matches(card_text, slot_day, slot_time):
    card   = normalize(card_text)
    day_ok = (not slot_day) or (normalize(slot_day) in card)
    if not slot_time:
        return day_ok
    target = _time_to_minutes(slot_time)
    # the slot's START time is the first time shown on the card
    start  = _time_to_minutes(card_text)
    if target is not None and start is not None:
        return day_ok and (start == target)
    # fallback: plain text match
    return day_ok and (normalize(slot_time) in card)


def find_button(driver, keywords, exclude_keywords=None):
    """
    Find a button containing any of the keywords (case insensitive).
    Exclude buttons containing exclude_keywords.
    """
    exclude_keywords = exclude_keywords or []
    all_buttons = driver.find_elements(By.TAG_NAME, "button")
    all_buttons += driver.find_elements(By.CSS_SELECTOR, "input[type='submit']")
    all_buttons += driver.find_elements(By.TAG_NAME, "a")

    for btn in all_buttons:
        btn_text = normalize(btn.text or btn.get_attribute('value') or '')
        # Skip excluded keywords
        if any(ex in btn_text for ex in exclude_keywords):
            continue
        # Match keywords
        if any(kw in btn_text for kw in keywords):
            return btn
    return None


def advance_next_date(cfg):
    current = cfg.get("next_registration_date", "")
    if current:
        try:
            dt = datetime.strptime(current, "%Y-%m-%d")
            cfg["next_registration_date"] = (dt + timedelta(days=7)).strftime("%Y-%m-%d")
            log(f"ðŸ“…  Next registration date advanced to: {cfg['next_registration_date']}")
        except ValueError:
            pass


def update_cron_schedule(cfg, config_file):
    """
    Update the GitHub Actions workflow cron schedule based on
    registration_day and registration_time in config.
    Fires 5 minutes before registration opens.
    """
    try:
        reg_day  = cfg.get("registration_day", "Thursday")
        reg_time = cfg.get("registration_time", "19:00")

        # Convert day name to cron weekday number (0=Sunday, 1=Monday...6=Saturday)
        day_map = {
            "Sunday": 0, "Monday": 1, "Tuesday": 2, "Wednesday": 3,
            "Thursday": 4, "Friday": 5, "Saturday": 6
        }
        day_num = day_map.get(reg_day, 4)

        # Parse registration time
        hh, mm = map(int, reg_time.split(":"))

        # Convert IST to UTC (IST = UTC + 5:30)
        total_mins = hh * 60 + mm - 330  # subtract 5h30m
        if total_mins < 0:
            total_mins += 1440
            day_num = (day_num - 1) % 7

        # Fire 5 minutes before
        total_mins -= 5
        if total_mins < 0:
            total_mins += 1440
            day_num = (day_num - 1) % 7

        cron_hour = total_mins // 60
        cron_min  = total_mins % 60

        new_cron = f"{cron_min} {cron_hour} * * {day_num}"
        log(f"ðŸ“…  New cron schedule: '{new_cron}' ({reg_day} at {reg_time} IST, fires 5 mins early)")

        # Read and update the workflow file
        workflow_file = f".github/workflows/{cfg.get('user_id', 'user1')}.yml"
        if os.path.exists(workflow_file):
            with open(workflow_file, "r") as f:
                workflow = f.read()

            # Replace the cron line
            import re as re2
            workflow = re2.sub(
                r"- cron: '[^']*'",
                f"- cron: '{new_cron}'",
                workflow
            )

            with open(workflow_file, "w") as f:
                f.write(workflow)

            log(f"âœ…  Workflow cron updated to: {new_cron}")
        else:
            log(f"âš ï¸   Workflow file not found: {workflow_file}")

    except Exception as e:
        log(f"âš ï¸   Could not update cron: {e}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  CONFIG & STATUS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def load_config(config_file):
    try:
        with open(config_file) as f:
            return json.load(f)
    except Exception as e:
        print(f"âŒ  Cannot load {config_file}: {e}", flush=True)
        sys.exit(1)


DEFAULT_SITE = {
    "login_url": "https://cricjoin.com/login",
    "home_url":  "https://cricjoin.com/home",
    "slots_url": "https://cricjoin.com/slots",
    "register_button_keywords": ["register"],
    "register_exclude_keywords": ["cancel", "back", "waitlist", "coming soon"],
    "poll_next_keywords": ["next", "continue", "proceed"],
    "join_button_keywords": ["join"],
    "join_exclude_keywords": ["waitlist"],
    "finalize_button_keywords": ["register"],
    "confirm_keywords": ["approved"],
}

SITE_CONFIG_FILE = "configs/cricjoin_site.json"


def load_site_config():
    """Shared CricJoin settings (URLs + button keywords), editable from the
    Phoenix admin panel. Any missing/invalid field falls back to its default."""
    site = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_SITE.items()}
    try:
        with open(SITE_CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for key, default in DEFAULT_SITE.items():
            val = data.get(key)
            if isinstance(default, list):
                if isinstance(val, list) and all(isinstance(x, str) for x in val):
                    site[key] = [x.strip().lower() for x in val if x.strip()]
            elif isinstance(val, str) and val.strip():
                site[key] = val.strip()
        print(f"[site] Loaded shared CricJoin config: {SITE_CONFIG_FILE}", flush=True)
    except FileNotFoundError:
        print(f"[site] {SITE_CONFIG_FILE} not found - using built-in defaults", flush=True)
    except Exception as e:
        print(f"[site] Could not read {SITE_CONFIG_FILE} ({e}) - using built-in defaults", flush=True)
    return site


def apply_site_config(cfg):
    """Attach shared site settings to the user's cfg. The shared file wins over
    the old per-user login_url / forms_url fields."""
    site = load_site_config()
    cfg["site"]      = site
    cfg["login_url"] = site["login_url"]
    cfg["forms_url"] = site["home_url"]
    cfg["slots_url"] = site["slots_url"]
    return cfg


def save_config(cfg, config_file):
    # never write the shared site settings back into a user's own config file
    out = {k: v for k, v in cfg.items() if k not in ("site", "slots_url")}
    with open(config_file, "w") as f:
        json.dump(out, f, indent=2)
    log(f"Config saved: {config_file}")


def save_status(user_id, status, message, next_run="", slot_info=""):
    status_file = f"status/{user_id}_status.json"
    data = {
        "user_id":     user_id,
        "status":      status,
        "last_run":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_result": status,
        "next_run":    next_run,
        "message":     message,
        "slot_info":   slot_info,
    }
    os.makedirs("status", exist_ok=True)
    with open(status_file, "w") as f:
        json.dump(data, f, indent=2)
    log(f"ðŸ“Š  Status saved: {status} â€” {message}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  BROWSER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def create_driver():
    log("ðŸŒ  Setting up Chrome...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--password-store=basic")
    options.add_argument("--remote-debugging-port=9222")
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    options.add_experimental_option("prefs", prefs)

    log("ðŸ”§  Installing ChromeDriver...")
    service = Service(ChromeDriverManager().install())
    log("ðŸš€  Launching Chrome...")
    driver  = webdriver.Chrome(service=service, options=options)
    log("âœ…  Chrome launched successfully!")
    return driver


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  LOGIN
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def login(driver, cfg):
    password = os.environ.get("CRICJOIN_PASSWORD") or cfg.get("cricjoin_password", "")
    if not password:
        log("âŒ  No password found. Set USER1_PASSWORD in GitHub Secrets.")
        sys.exit(1)

    log(f"ðŸ”  Logging in as {cfg['cricjoin_email']}...")
    driver.get(cfg["login_url"])

    wait = WebDriverWait(driver, 15)
    email_field = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input[type='email'], input[name='email']")
    ))
    email_field.clear()
    email_field.send_keys(cfg["cricjoin_email"])

    pwd_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
    pwd_field.clear()
    pwd_field.send_keys(password)

    login_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
    login_btn.click()

    time.sleep(3)
    if "login" in driver.current_url:
        log("âŒ  Login failed! Check credentials.")
        driver.quit()
        sys.exit(1)

    log("âœ…  Logged in successfully!")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  WAIT FOR REGISTER BUTTON
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def wait_for_register_button(driver, cfg):
    interval     = float(cfg.get("check_interval_seconds", 0.5))
    category     = normalize(cfg.get("category", ""))
    reg_kw       = cfg["site"]["register_button_keywords"]
    reg_ex       = cfg["site"]["register_exclude_keywords"]
    attempt      = 0
    max_attempts = 600  # 10 minutes max

    log(f"\nðŸ”„  Watching for Register button every {interval}s (max {max_attempts} attempts)...")

    while attempt < max_attempts:
        attempt += 1
        driver.get(cfg["forms_url"])
        time.sleep(1.5)

        try:
            if attempt == 1:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                log(f"   Page preview: {body_text[:300]}")

            # Find ALL buttons on page
            all_buttons = driver.find_elements(By.TAG_NAME, "button")
            all_buttons += driver.find_elements(By.CSS_SELECTOR, "input[type='submit']")
            all_buttons += driver.find_elements(By.TAG_NAME, "a")

            register_btns = []
            for btn in all_buttons:
                btn_text = normalize(btn.text or btn.get_attribute('value') or '')
                # keywords come from the shared CricJoin site config
                if any(k in btn_text for k in reg_kw) and not any(x in btn_text for x in reg_ex):
                    register_btns.append(btn)

            if attempt == 1:
                log(f"   Found {len(register_btns)} Register button(s)")

            matched_btn = None
            for btn in register_btns:
                try:
                    parent = btn.find_element(By.XPATH, "./ancestor::*[self::div or self::li or self::tr][1]")
                    card_text = parent.text
                except NoSuchElementException:
                    card_text = btn.text

                if is_slot_full(card_text):
                    log(f"   Slot full, skipping")
                    continue

                if category and category not in normalize(card_text):
                    page_text = driver.find_element(By.TAG_NAME, "body").text
                    if category not in normalize(page_text):
                        continue

                matched_btn = btn
                log(f"ðŸŸ¢  Attempt {attempt}: Register button found!")
                log(f"    Context: {card_text[:80].strip()}")
                break

            if matched_btn:
                driver.execute_script("arguments[0].scrollIntoView(true);", matched_btn)
                time.sleep(0.3)
                try:
                    matched_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", matched_btn)
                log("âœ…  Register button clicked!")
                return True
            else:
                if attempt % 10 == 0:
                    log(f"   Attempt {attempt}: Waiting for slot to open...")
                time.sleep(interval)

        except Exception as e:
            log(f"   Attempt {attempt}: Error â€” {e}")
            time.sleep(interval)

    log("âŒ  Timed out waiting for Register button.")
    return False


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  ANSWER POLL
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def answer_poll(driver, cfg):
    poll_answer = cfg.get("poll_answer", "Excellent")
    # the question may or may not appear - don't burn 10s when it doesn't
    wait        = WebDriverWait(driver, float(cfg.get("poll_wait_seconds", 3)))

    log(f"ðŸ“‹  Answering poll: '{poll_answer}'")
    try:
        wait.until(EC.presence_of_element_located((By.XPATH,
            f"//*[contains(translate(text(),"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
            f"'{poll_answer.lower()}')]"
        )))

        option = driver.find_element(By.XPATH,
            f"//*[contains(translate(text(),"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
            f"'{poll_answer.lower()}')]"
            f"[self::label or self::span or self::div or self::input]"
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", option)
        time.sleep(0.2)
        try:
            option.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", option)

        log(f"âœ…  Selected '{poll_answer}'")
        time.sleep(0.5)

        # Find Next/Continue/Proceed button (case insensitive)
        next_btn = find_button(
            driver,
            keywords=cfg["site"]["poll_next_keywords"],
            exclude_keywords=['cancel', 'back']
        )

        if next_btn:
            log(f"âœ…  Found next button: '{next_btn.text.strip()}'")
            driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
            time.sleep(0.2)
            try:
                next_btn.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", next_btn)
            log("âœ…  Clicked Next")
            time.sleep(1)
        else:
            log("âš ï¸   Could not find Next button")

    except (NoSuchElementException, TimeoutException) as e:
        log(f"âš ï¸   Poll error: {e}")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  SELECT SLOT & REGISTER
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def find_slot_cards(driver, site):
    """Return [(card_element, checkbox_element)] - one per slot on the select-slot
    page. A card is the largest ancestor of a Join checkbox that holds only that
    one checkbox (so it contains the title, date/time and 'N / M members')."""
    boxes = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], [role='checkbox']")
    cards, seen = [], set()
    for box in boxes:
        card, node = None, box
        for _ in range(8):
            try:
                node = node.find_element(By.XPATH, "..")
            except Exception:
                break
            n = len(node.find_elements(By.CSS_SELECTOR, "input[type='checkbox'], [role='checkbox']"))
            if n == 1:
                card = node
            elif n > 1:
                break
        if card is None or card.id in seen:
            continue
        txt = (card.text or "")
        if "join" not in txt.lower():
            continue
        seen.add(card.id)
        cards.append((card, box))
    return cards


def _click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    try:
        el.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", el)


def _is_checked(el):
    try:
        if el.tag_name == "input":
            return el.is_selected()
        return (el.get_attribute("aria-checked") or "").lower() == "true"
    except Exception:
        return False


def _final_register_button(driver, site):
    """The dark 'Register' button under the slot list (not Cancel)."""
    kws = site.get("finalize_button_keywords") or ["register"]
    cands = driver.find_elements(By.TAG_NAME, "button") + \
            driver.find_elements(By.CSS_SELECTOR, "input[type='submit']")
    found = None
    for b in cands:
        t = normalize(b.text or b.get_attribute("value") or "")
        if any(k in t for k in kws) and not any(x in t for x in ("cancel", "back", "waitlist")):
            found = b          # last matching button on the page = the form's submit
    return found


def _slot_key(card_text):
    """('oct 11', '5:00 pm') taken from the slot card, used to verify afterwards."""
    t = " ".join(card_text.split())
    d = re.search(r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}),\s*\d{4}\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)", t, re.I)
    if not d:
        return None
    return (f"{d.group(1)} {int(d.group(2))}".lower(), re.sub(r"\s+", " ", d.group(3)).lower().lstrip("0"))


def _registration_confirmed(driver, site, key):
    """True only if the page shows an Approved registration (and the chosen date/time)."""
    body = normalize(driver.find_element(By.TAG_NAME, "body").text)
    ok_words = site.get("confirm_keywords") or ["approved"]
    if not any(w in body for w in ok_words):
        return False
    if key:
        day, tm = key
        compact = body.replace("  ", " ")
        if day not in compact:
            return False
        if tm.replace(":00", "") not in compact and tm not in compact:
            return False
    return True


def select_slot_and_register(driver, cfg):
    """Flow (after the Register button on /home was clicked):
       select-slot page -> pick slot by priority -> tick Join -> click Register
       -> verify 'Approved'.  Returns (ok, slot_text_or_reason)."""
    site = cfg["site"]

    # 1) wait for the select-slot page. Register on /home may first open a slot
    #    page that has another Register button - click through up to 2 times.
    cards, hops = [], 0
    for attempt in range(1, int(cfg.get("slots_page_attempts", 40)) + 1):
        cards = find_slot_cards(driver, site)
        if cards:
            break
        if attempt in (3, 8):
            answer_poll(driver, cfg)          # question may appear here too
            continue
        if hops < 2 and attempt % 3 == 0:
            btn = find_button(driver, site["register_button_keywords"], site["register_exclude_keywords"])
            if btn:
                _click(driver, btn)
                hops += 1
                log("   Clicked another Register button to reach the slot selection page")
        time.sleep(1)
    if not cards:
        log("Select-slot page never showed any Join checkboxes")
        return False, "Select-slot page did not load"
    log(f"   Found {len(cards)} slot(s) on the selection page")
    for card, box in cards:
        log("     - " + " ".join(card.text.split())[:110])

    # already ticked? (e.g. user registered by hand) - nothing to do but verify
    for card, box in cards:
        if _is_checked(box):
            txt = " ".join(card.text.split())
            log("A slot is already selected: " + txt[:80])
            return False, "A slot was already selected (not changed): " + txt[:70]

    def usable(card_text):
        if is_waitlist(card_text):
            log("   Skipping waitlist slot: " + " ".join(card_text.split())[:60])
            return False
        if is_slot_full(card_text):
            log("   Skipping full slot: " + " ".join(card_text.split())[:60])
            return False
        return True

    # 2) choose by priority
    matched = None
    for idx, choice in enumerate(cfg["slot_choices"]):
        day, tm = choice.get("slot_day", ""), choice.get("slot_time", "")
        log(f"   Trying choice {idx + 1}: {day} at {tm}")
        for card, box in cards:
            if usable(card.text) and slot_matches(card.text, day, tm):
                matched = (card, box)
                log("Matched slot: " + " ".join(card.text.split())[:100])
                break
        if matched:
            break
    if not matched:
        log("   No preferred slot available - trying first available slot")
        for card, box in cards:
            if usable(card.text):
                matched = (card, box)
                log("   Fallback slot: " + " ".join(card.text.split())[:80])
                break
    if not matched:
        log("No available slots found")
        return False, "No available slot (all full / waitlist)"

    card, box = matched
    slot_text = " ".join(card.text.split())
    key = _slot_key(slot_text)

    # 3) tick Join
    _click(driver, box)
    time.sleep(0.5)
    if not _is_checked(box):
        driver.execute_script("arguments[0].click();", box)   # retry via JS
        time.sleep(0.5)
    if not _is_checked(box):
        log("Could not tick the Join checkbox")
        return False, "Join checkbox could not be ticked: " + slot_text[:60]
    log("Ticked Join")

    # 4) final Register button
    reg = _final_register_button(driver, site)
    if not reg:
        log("Final Register button not found")
        return False, "Final Register button not found"
    _click(driver, reg)
    log("Clicked final Register")

    # 5) verify: Approved (+ chosen date/time) on this page or on /home
    for _ in range(10):
        time.sleep(1.5)
        try:
            if _registration_confirmed(driver, site, key):
                log("Verified: registration shows as Approved")
                return True, slot_text
        except Exception:
            pass
    try:
        driver.get(cfg["forms_url"])
        time.sleep(2)
        if _registration_confirmed(driver, site, key):
            log("Verified on home page: registration shows as Approved")
            return True, slot_text
    except Exception as e:
        log(f"   Verification error: {e}")
    log("Register clicked but 'Approved' was NOT found - treating as failed")
    return False, "Register clicked but not confirmed: " + slot_text[:60]


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  MAIN
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def main():
    print("=" * 55, flush=True)
    print("       ðŸ”¥  Phoenix Bot â€” Cloud Runner  ðŸ”¥", flush=True)
    print("=" * 55, flush=True)

    if len(sys.argv) < 2:
        print("Usage: python bot/phoenix_bot.py configs/user1.json", flush=True)
        sys.exit(1)

    config_file = sys.argv[1]
    cfg         = load_config(config_file)
    apply_site_config(cfg)
    user_id     = cfg.get("user_id", "user1")

    if not cfg.get("active", True):
        log("â¸   User is inactive. Skipping.")
        save_status(user_id, "idle", "User is inactive")
        sys.exit(0)

    log(f"ðŸ‘¤  User      : {cfg['name']}")
    log(f"ðŸ“§  Email     : {cfg['cricjoin_email']}")
    log(f"ðŸ  Category  : {cfg['category']}")
    log(f"ðŸ“…  Reg day   : {cfg.get('registration_day','?')} at {cfg.get('registration_time','?')}")
    log(f"â±ï¸   Interval  : {cfg.get('check_interval_seconds', 0.5)}s")
    log(f"ðŸŽ¯  Slot choices:")
    for i, choice in enumerate(cfg["slot_choices"]):
        log(f"    {i+1}. {choice.get('slot_day','?')} at {choice.get('slot_time','?')}")

    save_status(user_id, "running", "Bot started")

    # Update cron schedule based on config
    update_cron_schedule(cfg, config_file)

    driver = create_driver()

    try:
        login(driver, cfg)
        success = wait_for_register_button(driver, cfg)

        if success:
            answer_poll(driver, cfg)
            registered, slot_info = select_slot_and_register(driver, cfg)

            if registered:
                advance_next_date(cfg)
                save_config(cfg, config_file)
                next_run  = cfg.get("next_registration_date", "")
                slot_msg  = f"Registered! ðŸ Slot: {slot_info[:80]}" if slot_info else "Registered successfully! ðŸ"
                save_status(user_id, "success", slot_msg, next_run, slot_info)
                log(f"\nðŸ  SUCCESS! {slot_msg}")
            else:
                save_status(user_id, "failed", (slot_info or "Could not select slot")[:120])
                log("\nâŒ  Failed to register â€” all slots may be full")
        else:
            save_status(user_id, "failed", "Timed out waiting for registration to open")

    except Exception as e:
        log(f"âŒ  Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        save_status(user_id, "failed", f"Error: {str(e)}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
