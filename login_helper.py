# login_helper.py — Interactive X Login Helper
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

_SCRIPT_DIR = Path(__file__).parent.resolve()
session_file = _SCRIPT_DIR / ".x_session.json"

def run():
    print("=" * 60)
    print("🔑 X (Twitter) Interactive Login Helper")
    print("=" * 60)
    print("This script will open a headful Chromium browser window so you can")
    print("log in to X, handle any phone verification or verification codes manually.")
    print("Once you successfully reach the home page, the session will be saved")
    print("and the browser will close automatically.")
    print("=" * 60)

    try:
        with sync_playwright() as p:
            print("🚀 Launching browser in headful mode...")
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()
            
            # Navigate to login page
            print("🌐 Navigating to X Login...")
            page.goto("https://x.com/login")
            
            print("\n👉 Please log in to X in the browser window.")
            print("👉 Complete any email, phone, or SMS verification requested.")
            print("👉 Waiting for you to reach the home page...")
            
            # Poll until URL contains '/home'
            logged_in = False
            for _ in range(300): # Wait up to 5 minutes (300 * 1s)
                try:
                    current_url = page.url
                    if "/home" in current_url:
                        logged_in = True
                        print("\n🎉 Detected successful login (reached home page)!")
                        # Wait a few seconds to let cookies load
                        time.sleep(3)
                        context.storage_state(path=str(session_file))
                        print(f"💾 Session successfully saved to: {session_file}")
                        break
                except Exception:
                    break
                time.sleep(1)
                
            if not logged_in:
                print("\n❌ Timeout or browser closed before login completed.")
            
            browser.close()
            print("👋 Browser closed.")
            
    except Exception as e:
        print(f"\n❌ Error running login helper: {e}")

if __name__ == "__main__":
    run()
