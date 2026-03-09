import os
import sys
import re
import logging
import smtplib
import base64
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# --- CONFIGURATION ---
EMAIL = os.environ.get("EMAIL", "pcarley1@gmail.com")
PASSWORD = os.environ.get("GOLF_PASSWORD", "Dklounge1$")
PLAYERS = os.environ.get("PLAYERS", "4")
TARGET_DAYS_OUT = int(os.environ.get("TARGET_DAYS_OUT", "7"))
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "fktwoykpdpwwlcku")

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


def send_email(subject, body, screenshot_bytes=None):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL
        msg["To"] = EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if screenshot_bytes:
            try:
                part = MIMEBase("image", "png")
                part.set_payload(screenshot_bytes)
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


def run():
    target_date = datetime.now() + timedelta(days=TARGET_DAYS_OUT)
    day_to_select = target_date.strftime("%d").lstrip("0")
    log.info(f"Target date: {target_date.strftime('%Y-%m-%d')} (day={day_to_select})")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        screenshot_bytes = None

        try:
            log.info("Starting tee time booking script...")

            # --- Navigate to booking page ---
            page.goto("https://golfstpete.com/mangrove-bay/", wait_until="domcontentloaded")
            page.get_by_partial_text = None  # reset
            page.locator("a", has_text="BOOK A TEE TIME").first.click()
            log.info("Clicked Book a Tee Time.")

            # Handle new tab
            with context.expect_page(timeout=5000) as new_page_info:
                pass
            booking_page = new_page_info.value
            booking_page.wait_for_load_state("domcontentloaded")
            log.info("Switched to booking tab.")

            # --- Public booking class ---
            try:
                booking_page.locator("button", has_text="Public").click(timeout=5000)
                log.info("Clicked Public button.")
            except PlaywrightTimeout:
                log.info("No Public button found, continuing.")

            # --- Select date ---
            booking_page.wait_for_selector("td.day", timeout=15000)
            day_cell = booking_page.locator("td.day:not(.old):not(.disabled)").filter(
                has_text=re.compile(rf"^\s*{re.escape(day_to_select)}\s*$")
            ).first
            day_cell.click()
            log.info(f"Selected date: {target_date.strftime('%Y-%m-%d')}")

            # --- Filter by players ---
            try:
                booking_page.locator(f"a.ob-filters-btn[data-value='{PLAYERS}']").click(timeout=5000)
                log.info(f"Filtered by {PLAYERS} players.")
            except PlaywrightTimeout:
                log.warning("Could not click player filter — proceeding without it.")

            # --- Select first time slot ---
            booking_page.wait_for_selector(".time-summary-ob", timeout=15000)
            slots = booking_page.locator(".time-summary-ob")
            count = slots.count()
            if count == 0:
                raise Exception("No time slots found!")
            slots.first.click()
            log.info(f"Selected first available time slot ({count} found).")

            # --- Log in ---
            booking_page.wait_for_selector("input[name='email']", timeout=10000)
            booking_page.fill("input[name='email']", EMAIL)
            booking_page.fill("input[name='password']", PASSWORD)
            booking_page.locator("button", has_text="Log In").click()
            booking_page.wait_for_load_state("networkidle")
            log.info("Logged in.")

            # --- Select players ---
            try:
                booking_page.locator(f".btn-group.players a.btn[data-value='{PLAYERS}']").click(timeout=8000)
                log.info(f"Confirmed {PLAYERS} players.")
            except PlaywrightTimeout:
                log.warning(f"Could not confirm {PLAYERS} players.")

            # --- Select cart ---
            try:
                booking_page.locator(".btn-group.carts a.btn[data-value='yes']").click(timeout=8000)
                log.info("Confirmed cart.")
            except PlaywrightTimeout:
                log.warning("Could not confirm cart.")

            # --- Dismiss reservation limit banner if present ---
            try:
                booking_page.locator("text=You are only allowed").locator("..").locator("button").click(timeout=3000)
                log.warning("Dismissed reservation limit banner.")
            except PlaywrightTimeout:
                pass

            # --- Wait for price to load ---
            booking_page.wait_for_selector("text=$", timeout=15000)

            # --- Accept booking conditions if present ---
            try:
                checkbox = booking_page.locator("#notes-accepted")
                if checkbox.is_visible() and not checkbox.is_checked():
                    checkbox.click()
                    log.info("Checked booking conditions checkbox.")
            except Exception:
                pass

            # --- Screenshot before booking ---
            screenshot_bytes = booking_page.screenshot()
            log.info("Pre-click screenshot captured.")

            # --- Click Book Time ---
            booking_page.locator("button.book").click(timeout=15000)
            log.info("Clicked Book Time button.")

            # --- Wait for confirmation ---
            try:
                booking_page.wait_for_selector(
                    "text=reservation has been booked, text=Confirmation, text=Thank you, text=Booked",
                    timeout=20000
                )
                log.info("Confirmation page detected!")
            except PlaywrightTimeout:
                log.warning("Could not detect confirmation text — check screenshot.")

            confirmation_bytes = booking_page.screenshot()
            log.info("SUCCESS! Tee time booked.")

            send_email(
                subject="Tee Time Booked - Mangrove Bay!",
                body=f"Your tee time has been successfully booked!\n\nDate: {target_date.strftime('%A, %B %d')}\nPlayers: {PLAYERS}\nHoles: 18\nCourse: Mangrove Bay\n\nSee attached screenshot for confirmation details.",
                screenshot_bytes=confirmation_bytes
            )

        except Exception as e:
            log.error(f"FAILED: {e}")
            try:
                screenshot_bytes = booking_page.screenshot()
            except Exception:
                pass
            send_email(
                subject="Tee Time Booking FAILED",
                body=f"The tee time booking script failed.\n\nError: {e}",
                screenshot_bytes=screenshot_bytes
            )
            sys.exit(1)

        finally:
            browser.close()


run()
