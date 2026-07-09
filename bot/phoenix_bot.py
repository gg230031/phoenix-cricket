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


def slot_matches(card_text, slot_day, slot_time):
    card     = normalize(card_text)
    day_ok   = (not slot_day) or (normalize(slot_day) in card)
    if slot_time:
        target_24 = time_to_24h(slot_time)
        time_ok   = (target_24 in card) or (normalize(slot_time) in card)
        try:
            alt = datetime.strptime(target_24, "%H:%M").strftime("%I:%M %p").lstrip("0").lower()
            time_ok = time_ok or (alt in card)
        except Exception:
            pass
    else:
        time_ok = True
    return day_ok and time_ok


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


def save_config(cfg, config_file):
    with open(config_file, "w") as f:
        json.dump(cfg, f, indent=2)
    log(f"âœ…  Config saved: {config_file}")


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
                # Must contain 'register' but NOT 'cancel', 'back', 'waitlist'
                if 'register' in btn_text and not any(
                    x in btn_text for x in ['cancel', 'back', 'waitlist']
                ):
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
    wait        = WebDriverWait(driver, 10)

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
            keywords=['next', 'continue', 'proceed'],
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

def select_slot_and_register(driver, cfg):
    log("ðŸŽ¯  Selecting slot...")
    time.sleep(1)
    registered_slot_info = ""

    try:
        # Find all slot containers
        slot_containers = driver.find_elements(By.XPATH, "//div[.//input[@type='checkbox']]")
        if not slot_containers:
            slot_containers = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")

        log(f"   Found {len(slot_containers)} slot container(s)")

        matched      = None
        matched_text = ""

        # Go through slot choices in order
        for choice_idx, choice in enumerate(cfg["slot_choices"]):
            slot_day  = choice.get("slot_day", "")
            slot_time = choice.get("slot_time", "")
            log(f"   Trying choice {choice_idx + 1}: {slot_day} at {slot_time}")

            for container in slot_containers:
                container_text = container.text

                # Skip waitlist slots
                if is_waitlist(container_text):
                    log(f"   Skipping waitlist slot: {container_text[:60]}")
                    continue

                # Skip full slots
                if is_slot_full(container_text):
                    log(f"   Skipping full slot: {container_text[:60]}")
                    continue

                # Match day + time
                if slot_matches(container_text, slot_day, slot_time):
                    matched      = container
                    matched_text = container_text
                    log(f"âœ…  Matched slot: {container_text[:100].strip()}")
                    break

            if matched:
                break

        # Fallback â€” first available non-waitlist slot
        if not matched:
            log("   No exact match â€” trying first available non-waitlist slot")
            for container in slot_containers:
                if not is_waitlist(container.text) and not is_slot_full(container.text):
                    matched      = container
                    matched_text = container.text
                    log(f"   Fallback slot: {container.text[:80]}")
                    break

        if not matched:
            log("âŒ  No available slots found")
            return False, ""

        # Find and click the Join checkbox (not Join Waitlist)
        join_checkbox = None
        try:
            # Look for checkbox inside the container
            checkboxes = matched.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            for cb in checkboxes:
                parent_text = normalize(cb.find_element(By.XPATH, "..").text)
                if 'waitlist' not in parent_text:
                    join_checkbox = cb
                    break
            if not join_checkbox and checkboxes:
                join_checkbox = checkboxes[0]
        except NoSuchElementException:
            join_checkbox = matched

        if join_checkbox:
            driver.execute_script("arguments[0].scrollIntoView(true);", join_checkbox)
            time.sleep(0.2)
            if not join_checkbox.is_selected():
                try:
                    join_checkbox.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", join_checkbox)
            log("âœ…  Join checkbox ticked")
        
        time.sleep(0.5)

        # Click Register button (not Cancel, not Back)
        register_btn = find_button(
            driver,
            keywords=['register'],
            exclude_keywords=['cancel', 'back', 'waitlist']
        )

        if register_btn:
            log(f"âœ…  Found Register button: '{register_btn.text.strip()}'")
            driver.execute_script("arguments[0].scrollIntoView(true);", register_btn)
            time.sleep(0.2)
            try:
                register_btn.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", register_btn)
            log("âœ…  Final Register clicked!")
            time.sleep(2)
            return True, matched_text
        else:
            log("âŒ  Could not find Register button")
            return False, ""

    except Exception as e:
        log(f"âŒ  Slot selection error: {e}")
        import traceback
        traceback.print_exc()
        return False, ""


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
