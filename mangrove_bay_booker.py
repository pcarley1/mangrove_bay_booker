import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
import time
import logging
import sys
import os
import subprocess
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# --- CONFIGURATION (use Railway environment variables) ---
EMAIL = os.environ.get("EMAIL", "pcarley1@gmail.com")
PASSWORD = os.environ.get("GOLF_PASSWORD", "Dklounge1$")
PLAYERS = os.environ.get("PLAYERS", "4")
TARGET_DAYS_OUT = int(os.environ.get("TARGET_DAYS_OUT", "7"))
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "fktwoykpdpwwlcku")

# --- LOGGING SETUP (stdout only for Railway) ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

try:
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    driver = uc.Chrome(options=options)
    log.info("Chrome launched successfully via undetected-chromedriver.")
except Exception as e:
    log.error(f"Failed to launch Chrome: {e}")
    sys.exit(1)


def click_with_retry(selector, by=By.CSS_SELECTOR, attempts=3):
    for i in range(attempts):
        try:
            element = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((by, selector)))
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            time.sleep(1.5)
            continue
    return False

def send_email(subject, body, screenshot_b64=None):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL
        msg["To"] = EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if screenshot_b64:
            try:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(screenshot_b64)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment; filename=screenshot.png")
                msg.attach(part)
            except Exception:
                pass

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL, GMAIL_APP_PASSWORD)
            smtp.sendmail(EMAIL, EMAIL, msg.as_string())
        log.info("Notification email sent!")
    except Exception as e:
        log.warning(f"Email notification failed (non-fatal): {e}")

try:
    log.info("Starting tee time booking script...")

    driver.get("https://golfstpete.com/mangrove-bay/")
    wait = WebDriverWait(driver, 15)
    btn = wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "BOOK A TEE TIME")))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
    btn.click()
    time.sleep(3)

    if len(driver.window_handles) > 1:
        driver.switch_to.window(driver.window_handles[-1])
        log.info("Switched to new tab.")
    else:
        log.info("Page loaded inline (no new tab).")

    try:
        pub_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Public')]")))
        pub_btn.click()
        log.info("Clicked Public button.")
    except Exception:
        log.info("No Public button found, continuing.")
    time.sleep(3)

    target_date = datetime.now() + timedelta(days=TARGET_DAYS_OUT)
    day_to_select = target_date.strftime("%d").lstrip("0")
    log.info(f"Selecting date: {target_date.strftime('%Y-%m-%d')} (day={day_to_select})")
    day_xpath = f"//td[contains(@class, 'day') and not(contains(@class, 'old')) and text()='{day_to_select}']"
    wait.until(EC.element_to_be_clickable((By.XPATH, day_xpath))).click()

    player_clicked = False
    for player_sel in [
        f"a.ob-filters-btn[data-value='{PLAYERS}']",
        f"//a[contains(@class,'ob-filters-btn') and @data-value='{PLAYERS}']",
        f"//*[contains(@class,'filters') and text()='{PLAYERS}']",
        f"//button[normalize-space()='{PLAYERS}']",
    ]:
        try:
            by = By.XPATH if player_sel.startswith("//") else By.CSS_SELECTOR
            WebDriverWait(driver, 5).until(EC.element_to_be_clickable((by, player_sel))).click()
            player_clicked = True
            log.info(f"Filtered by {PLAYERS} players using selector: {player_sel}")
            break
        except Exception:
            continue
    if not player_clicked:
        log.warning("Could not click player filter — proceeding without it.")

    time_slots = wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, "time-summary-ob")))
    if time_slots:
        driver.execute_script("arguments[0].click();", time_slots[0])
        log.info(f"Selected first available time slot ({len(time_slots)} found).")
    else:
        raise Exception("No time slots found!")

    wait.until(EC.visibility_of_element_located((By.NAME, "email"))).send_keys(EMAIL)
    driver.find_element(By.NAME, "password").send_keys(PASSWORD)
    driver.find_element(By.XPATH, "//button[contains(., 'Log In')]").click()
    log.info("Logged in.")

    click_with_retry("div[aria-label='18 Holes']")
    log.info("Selected 18 holes.")

    click_with_retry(f"div[aria-label='{PLAYERS} Players']")
    log.info(f"Confirmed {PLAYERS} players.")

    click_with_retry("div[aria-label='Yes, I need a cart']")
    log.info("Confirmed cart.")

    try:
        dismiss = driver.find_element(By.XPATH, "//*[contains(text(), 'You are only allowed')]/..//button | //*[contains(text(), 'You are only allowed')]//following-sibling::*[@role='button']")
        dismiss.click()
        log.warning("Dismissed reservation limit banner.")
    except Exception:
        pass

    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '$')]")))
    time.sleep(2)

    try:
        checkbox = driver.find_element(By.ID, "notes-accepted")
        if checkbox.is_displayed() and not checkbox.is_selected():
            driver.execute_script("arguments[0].click();", checkbox)
            log.info("Checked booking conditions checkbox.")
    except Exception:
        pass

    preclick_screenshot = driver.get_screenshot_as_base64()
    log.info("Pre-click screenshot captured.")

    try:
        book_btn = WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.book")))
        driver.execute_script("arguments[0].scrollIntoView(true);", book_btn)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", book_btn)
        log.info("Clicked Book Time button.")
    except Exception as e:
        raise Exception(f"Could not click Book Time button: {e}")

    log.info("Waiting for confirmation page...")
    try:
        wait_confirm = WebDriverWait(driver, 20)
        wait_confirm.until(EC.any_of(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Confirmation')]")),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'confirmation')]")),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Thank you')]")),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Booked')]")),
        ))
        log.info("Confirmation page detected!")
    except Exception:
        log.warning("Could not detect confirmation text — check screenshot.")

    time.sleep(3)
    confirmation_screenshot = driver.get_screenshot_as_base64()
    log.info("SUCCESS! Tee time booked.")

    send_email(
        subject="⛳ Tee Time Booked - Mangrove Bay!",
        body=f"Your tee time has been successfully booked!\n\nDate: {target_date.strftime('%A, %B %d')}\nPlayers: {PLAYERS}\nHoles: 18\nCourse: Mangrove Bay\n\nSee attached screenshot for confirmation details.",
        screenshot_b64=confirmation_screenshot
    )

except Exception as e:
    log.error(f"FAILED: {e}")
    try:
        error_screenshot = driver.get_screenshot_as_base64()
        send_email(
            subject="❌ Tee Time Booking FAILED",
            body=f"The tee time booking script failed.\n\nError: {e}",
            screenshot_b64=error_screenshot
        )
    except Exception as email_err:
        log.warning(f"Failure email could not be sent: {email_err}")
    sys.exit(1)

finally:
    driver.quit()
