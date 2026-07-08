"""
Phoenix Bot — Cloud Version
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

# ── Selenium ──────────────────────────────────────────────────────────────────
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
except ImportError:
    print("❌  Missing selenium. Run: pip install selenium webdriver-manager")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


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
    matches = re.findall(r'(\d+)\s*/\s*(\d+)', slot_text)
    for current, maximum in matches:
        if int(current) >= int(maximum):
            return True
    return False


def slot_matches(card_text, slot_day, slot_time):
    card     = normalize(card_text)
    day_ok   = (not slot_day)  or (normalize(slot_day) in card)
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


def advance_next_date(cfg):
    """Move next_registration_date forward by 7 days."""
    current = cfg.get("next_registration_date", "")
    if current:
        try:
            dt = datetime.strptime(current, "%Y-%m-%d")
            cfg["next_registration_date"] = (dt + timedelta(days=7)).strftime("%Y-%m-%d")
            log(f"📅  Next registration date advanced to: {cfg['next_registration_date']}")
        except ValueError:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG & STATUS
# ══════════════════════════════════════════════════════════════════════════════

def load_config(config_file):
    try:
        with open(config_file) as f:
            return json.load(f)
    except Exception as e:
        print(f"❌  Cannot load {config_file}: {e}")
        sys.exit(1)


def save_config(cfg, config_file):
    with open(config_file, "w") as f:
        json.dump(cfg, f, indent=2)
    log(f"✅  Config saved: {config_file}")


def save_status(user_id, status, message, next_run=""):
    status_file = f"status/{user_id}_status.json"
    data = {
        "user_id":     user_id,
        "status":      status,
        "last_run":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_result": status,
        "next_run":    next_run,
        "message":     message,
    }
    os.makedirs("status", exist_ok=True)
    with open(status_file, "w") as f:
        json.dump(data, f, indent=2)
    log(f"📊  Status saved: {status} — {message}")


# ══════════════════════════════════════════════════════════════════════════════
#  BROWSER
# ══════════════════════════════════════════════════════════════════════════════

def create_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--password-store=basic")
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    options.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)
    return driver


# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN
# ══════════════════════════════════════════════════════════════════════════════

def login(driver, cfg):
    password = os.environ.get("CRICJOIN_PASSWORD") or cfg.get("cricjoin_password", "")
    if not password:
        log("❌  No password found. Set USER1_PASSWORD in GitHub Secrets.")
        sys.exit(1)

    log(f"🔐  Logging in as {cfg['cricjoin_email']}...")
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
        log("❌  Login failed! Check credentials.")
        driver.quit()
        sys.exit(1)

    log("✅  Logged in successfully!")


# ══════════════════════════════════════════════════════════════════════════════
#  WAIT FOR REGISTER BUTTON
# ══════════════════════════════════════════════════════════════════════════════

def wait_for_register_button(driver, cfg):
    interval = 1
    category = normalize(cfg.get("category", ""))
    attempt  = 0
    max_attempts = 300  # 5 minutes max

    log(f"\n🔄  Watching for Register button (max {max_attempts} attempts)...")

    while attempt < max_attempts:
        attempt += 1
        driver.get(cfg["forms_url"])
        time.sleep(2)

        try:
            register_btns = driver.find_elements(By.XPATH,
                "//*[self::button or self::a]"
                "[normalize-space(translate(text(),"
                "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))='register']"
            )

            matched_btn = None
            for btn in register_btns:
                try:
                    card = btn.find_element(By.XPATH,
                        "./ancestor::div[contains(@class,'card') or "
                        "contains(@class,'slot') or contains(@class,'form') or "
                        "contains(@class,'item')][1]")
                    card_text = card.text
                except NoSuchElementException:
                    card_text = btn.text

                if category and category not in normalize(card_text):
                    continue
                if is_slot_full(card_text):
                    continue

                # Check slot choices in order
                for choice in cfg["slot_choices"]:
                    if slot_matches(card_text, choice.get("slot_day",""), choice.get("slot_time","")):
                        matched_btn = btn
                        log(f"🟢  Attempt {attempt}: Register button found!")
                        log(f"    Slot: {card_text[:80].strip()}")
                        break

                if matched_btn:
                    break

            if matched_btn:
                driver.execute_script("arguments[0].scrollIntoView(true);", matched_btn)
                time.sleep(0.3)
                try:
                    matched_btn.click()
                except ElementClickInterceptedException:
                    driver.execute_script("arguments[0].click();", matched_btn)
                log("✅  Register button clicked!")
                return True
            else:
                if attempt % 10 == 0:
                    log(f"   Attempt {attempt}: Still waiting...")
                time.sleep(interval)

        except Exception as e:
            log(f"   Attempt {attempt}: Error — {e}")
            time.sleep(interval)

    log("❌  Timed out waiting for Register button.")
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  ANSWER POLL
# ══════════════════════════════════════════════════════════════════════════════

def answer_poll(driver, cfg):
    poll_answer = cfg.get("poll_answer", "Excellent")
    wait = WebDriverWait(driver, 10)

    log(f"📋  Answering poll: '{poll_answer}'")
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
        time.sleep(0.3)
        try:
            option.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", option)

        log(f"✅  Selected '{poll_answer}'")
        time.sleep(0.5)

        next_btn = driver.find_element(By.XPATH,
            "//button[normalize-space(translate(text(),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))='next']"
        )
        next_btn.click()
        log("✅  Clicked Next")
        time.sleep(1)

    except (NoSuchElementException, TimeoutException) as e:
        log(f"⚠️   Poll error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  SELECT SLOT & REGISTER
# ══════════════════════════════════════════════════════════════════════════════

def select_slot_and_register(driver, cfg):
    log("🎯  Selecting slot...")
    time.sleep(1)

    try:
        slot_containers = driver.find_elements(By.XPATH, "//div[.//input[@type='checkbox']]")
        if not slot_containers:
            slot_containers = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")

        matched = None
        for choice in cfg["slot_choices"]:
            for container in slot_containers:
                if is_slot_full(container.text):
                    continue
                if slot_matches(container.text, choice.get("slot_day",""), choice.get("slot_time","")):
                    matched = container
                    log(f"✅  Matched: {container.text[:80].strip()}")
                    break
            if matched:
                break

        if not matched and slot_containers:
            matched = slot_containers[0]
            log("ℹ️   No exact match — using first available slot")

        if not matched:
            log("❌  No slot checkboxes found")
            return False

        try:
            checkbox = matched.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
        except NoSuchElementException:
            checkbox = matched

        driver.execute_script("arguments[0].scrollIntoView(true);", checkbox)
        time.sleep(0.3)
        if not checkbox.is_selected():
            try:
                checkbox.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", checkbox)

        log("✅  Slot checkbox ticked")
        time.sleep(0.5)

        register_btn = driver.find_element(By.XPATH,
            "//button[normalize-space(translate(text(),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))='register']"
        )
        register_btn.click()
        log("✅  Final Register clicked!")
        time.sleep(2)
        return True

    except Exception as e:
        log(f"❌  Slot selection error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 55)
    print("       🔥  Phoenix Bot — Cloud Runner  🔥")
    print("=" * 55)

    if len(sys.argv) < 2:
        print("Usage: python bot/phoenix_bot.py configs/user1.json")
        sys.exit(1)

    config_file = sys.argv[1]
    cfg         = load_config(config_file)
    user_id     = cfg.get("user_id", "user1")

    if not cfg.get("active", True):
        log("⏸   User is inactive. Skipping.")
        save_status(user_id, "idle", "User is inactive")
        sys.exit(0)

    log(f"👤  User    : {cfg['name']}")
    log(f"📧  Email   : {cfg['cricjoin_email']}")
    log(f"🏏  Category: {cfg['category']}")
    log(f"📅  Reg day : {cfg.get('registration_day','?')} at {cfg.get('registration_time','?')}")

    save_status(user_id, "running", "Bot started")

    driver = create_driver()

    try:
        login(driver, cfg)
        success = wait_for_register_button(driver, cfg)

        if success:
            answer_poll(driver, cfg)
            registered = select_slot_and_register(driver, cfg)

            if registered:
                # Advance next registration date by 7 days
                advance_next_date(cfg)
                save_config(cfg, config_file)
                next_run = cfg.get("next_registration_date", "")
                save_status(user_id, "success", "Slot registered successfully! 🏏", next_run)
                log("\n🏏  SUCCESS! Registered for the slot!")
            else:
                save_status(user_id, "failed", "Could not select slot — all may be full")
                log("\n❌  Failed to register — all slots may be full")
        else:
            save_status(user_id, "failed", "Timed out waiting for registration to open")

    except Exception as e:
        log(f"❌  Unexpected error: {e}")
        save_status(user_id, "failed", f"Error: {str(e)}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
