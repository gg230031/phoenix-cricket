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
    "finalize_button_keywords": [],
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
    """Return [(card_element, action_element)] - one per slot on the page.
    action_element is the slot's Join checkbox or Join button."""
    join_kw = site["join_button_keywords"]
    join_ex = site["join_exclude_keywords"]
    cap_re  = re.compile(r"\d+\s*/\s*\d+")

    actions = list(driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']"))
    for el in driver.find_elements(By.XPATH, "//button | //a | //label | //span"):
        try:
            t = normalize(el.text or "")
        except Exception:
            continue
        if t and len(t) <= 25 and any(k in t for k in join_kw) and not any(x in t for x in join_ex):
            actions.append(el)

    cards, seen = [], set()
    for act in actions:
        node, card = act, None
        for _ in range(8):
            try:
                node = node.find_element(By.XPATH, "..")
            except Exception:
                break
            txt = node.text or ""
            if cap_re.search(txt) or "member" in txt.lower():
                card = node
                break
        if card is None or card.id in seen:
            continue
        seen.add(card.id)
        cards.append((card, act))
    return cards


def _click(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    try:
        el.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", el)


def select_slot_and_register(driver, cfg):
    site = cfg["site"]
    log("Opening slots page: " + cfg["slots_url"])

    # 1) navigate to /slots ourselves and wait for the slot cards to appear
    cards = []
    for attempt in range(1, int(cfg.get("slots_page_attempts", 20)) + 1):
        driver.get(cfg["slots_url"])
        time.sleep(1.5)
        cards = find_slot_cards(driver, site)
        if cards:
            break
        log(f"   Slots page attempt {attempt}: no slot cards yet")
        time.sleep(float(cfg.get("check_interval_seconds", 0.5)))
    if not cards:
        log("No slots found on the slots page")
        return False, ""
    log(f"   Found {len(cards)} slot card(s)")

    def usable(card_text):
        if is_waitlist(card_text):
            log(f"   Skipping waitlist slot: {card_text[:60]!r}")
            return False
        if is_slot_full(card_text):
            log(f"   Skipping full slot: {card_text[:60]!r}")
            return False
        return True

    # 2) pick the slot by priority (Choice 1, then Choice 2, ...)
    matched = None
    for idx, choice in enumerate(cfg["slot_choices"]):
        day, tm = choice.get("slot_day", ""), choice.get("slot_time", "")
        log(f"   Trying choice {idx + 1}: {day} at {tm}")
        for card, act in cards:
            if usable(card.text) and slot_matches(card.text, day, tm):
                matched = (card, act)
                log("Matched slot: " + " ".join(card.text.split())[:100])
                break
        if matched:
            break

    if not matched:
        log("   No preferred slot available - trying first available slot")
        for card, act in cards:
            if usable(card.text):
                matched = (card, act)
                log("   Fallback slot: " + " ".join(card.text.split())[:80])
                break
    if not matched:
        log("No available slots found")
        return False, ""

    card, action = matched
    slot_text = " ".join(card.text.split())

    # 3) click Join (this is the final action)
    try:
        already = action.tag_name == "input" and action.is_selected()
    except Exception:
        already = False
    if already:
        log("Slot is already registered - nothing to click")
        return True, slot_text
    _click(driver, action)
    log("Clicked Join")
    time.sleep(1.5)

    # optional extra confirm button (empty by default - Join is the last step)
    if site["finalize_button_keywords"]:
        fin = find_button(driver, site["finalize_button_keywords"], ["cancel", "back"])
        if fin:
            _click(driver, fin)
            log("Clicked confirm button: " + repr(fin.text.strip()))
            time.sleep(1.5)

    # 4) verify - re-read the slots page and look for this slot as registered
    key = slot_text[:40]
    try:
        for c2, a2 in find_slot_cards(driver, site):
            t2 = " ".join(c2.text.split())
            if t2[:40] == key:
                sel = a2.tag_name == "input" and a2.is_selected()
                if sel or "registered" in t2.lower():
                    log("Verified: slot now shows as registered")
                    return True, slot_text
                break
    except Exception as e:
        log(f"   Verification skipped: {e}")
    log("Join clicked but could not verify the registration")
    return True, "(unverified) " + slot_text



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
                save_status(user_id, "failed", "Could not select slot â€” all may be full")
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
