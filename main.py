# main.py — X (Twitter) AI Daily Tweet Automation
# Version: 2.0.0  (Geopolitics Edition)
#
# Daily workflow:
#   1. Discovers trending geopolitical topic via Tavily
#   2. Checks Google Sheets for duplicate (already tweeted today?)
#   3. Researches topic via Tavily (deep search)
#   4. Generates tweet via Groq (Llama 3 70B)
#   5. Quality-checks tweet via second Groq call
#   6. Generates image via Pollinations.AI
#   7. Posts tweet with image to X via Tweepy API v2
#   8. Logs result to Google Sheets
#   9. Sends Gmail notification
#
# Run:          python main.py
# Run now:      python main.py --now  OR  RUN_NOW=true python main.py

import json, logging, os, random, re, smtplib, sys, tempfile, time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from types import ModuleType

# ── Python 3.13 Compatibility Mock for imghdr (removed in 3.13, needed by Tweepy) ──
if 'imghdr' not in sys.modules:
    mock_imghdr = ModuleType('imghdr')
    def mock_what(file, h=None):
        if h is None:
            if isinstance(file, (str, bytes, os.PathLike)):
                with open(file, 'rb') as f:
                    h = f.read(32)
            else:
                pos = file.tell()
                h = file.read(32)
                file.seek(pos)
        if h.startswith(b'\xff\xd8\xff'):
            return 'jpeg'
        if h.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'png'
        if h.startswith(b'GIF87a') or h.startswith(b'GIF89a'):
            return 'gif'
        return None
    mock_imghdr.what = mock_what
    sys.modules['imghdr'] = mock_imghdr

import requests
import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

import config

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_logs_dir = os.path.join(_SCRIPT_DIR, "logs")
os.makedirs(_logs_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(_logs_dir, "automation.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── Topic Discovery ───────────────────────────────────────────────────────────
_DISCOVERY_QUERIES = [
    "latest geopolitical developments 2026",
    "biggest international relations news this week 2026",
    "global power shifts 2026",
    "US China relations latest 2026",
    "Russia Ukraine conflict updates 2026",
    "Middle East geopolitical developments 2026",
    "India foreign policy news 2026",
    "South China Sea tensions 2026",
    "NATO security developments 2026",
    "global economic sanctions news 2026",
    "international trade disputes 2026",
    "BRICS expansion and policy news 2026",
    "Taiwan Strait developments 2026",
    "Arctic geopolitics and resource competition 2026",
    "Africa geopolitical developments 2026",
    "European Union foreign policy news 2026",
    "global energy security developments 2026",
    "defense and military strategy news 2026",
    "cyber warfare and national security news 2026",
    "emerging geopolitical risks and conflicts 2026",
]

_FALLBACK_TOPICS = [
    {
        "topic": "Major geopolitical developments shaping international relations this week",
        "actor": "Global Affairs",
        "hashtags": "#Geopolitics #WorldNews #Diplomacy"
    },
    {
        "topic": "Rising tensions and strategic competition in the South China Sea",
        "actor": "Asia-Pacific",
        "hashtags": "#SouthChinaSea #Security #Geopolitics"
    },
    {
        "topic": "The impact of economic sanctions on global trade and diplomacy",
        "actor": "International Economy",
        "hashtags": "#Sanctions #Trade #GlobalPolitics"
    }
]

# ── Hashtag Extraction ────────────────────────────────────────────────────────
def _extract_hashtags(title: str) -> str:
    t = title.lower()
    base = ["#Geopolitics", "#GlobalAffairs"]

    kmap = [
        (["china", "beijing", "xi jinping"], ["#China", "#AsiaPacific"]),
        (["united states", " us ", "washington", "biden", "trump"], ["#USA", "#ForeignPolicy"]),
        (["russia", "moscow", "putin"], ["#Russia", "#Security"]),
        (["ukraine", "kyiv", "zelensky"], ["#Ukraine", "#EuropeanSecurity"]),
        (["india", "modi", "new delhi"], ["#India", "#IndoPacific"]),
        (["taiwan", "taipei"], ["#Taiwan", "#StraitTensions"]),
        (["south china sea"], ["#SouthChinaSea", "#MaritimeSecurity"]),
        (["nato"], ["#NATO", "#Defense"]),
        (["brics"], ["#BRICS", "#EmergingPowers"]),
        (["middle east"], ["#MiddleEast", "#RegionalSecurity"]),
        (["iran", "tehran"], ["#Iran", "#MiddleEast"]),
        (["israel", "gaza", "tel aviv"], ["#Israel", "#RegionalSecurity"]),
        (["sanctions"], ["#Sanctions", "#EconomicStatecraft"]),
        (["trade war", "tariffs"], ["#TradePolicy", "#GlobalEconomy"]),
        (["energy", "oil", "gas", "lng"], ["#EnergySecurity", "#Geoeconomics"]),
        (["critical minerals", "rare earth"], ["#CriticalMinerals", "#SupplyChains"]),
        (["cyber"], ["#CyberSecurity", "#NationalSecurity"]),
        (["arctic"], ["#Arctic", "#StrategicCompetition"]),
        (["africa"], ["#Africa", "#GlobalInfluence"]),
        (["indo-pacific", "indopacific"], ["#IndoPacific", "#StrategicCompetition"]),
        (["europe", "eu", "brussels"], ["#Europe", "#EUPolicy"]),
        (["pakistan"], ["#Pakistan", "#SouthAsia"]),
        (["north korea", "pyongyang", "kim jong"], ["#NorthKorea", "#NuclearThreat"]),
        (["saudi", "riyadh", "opec"], ["#SaudiArabia", "#EnergyPolitics"]),
        (["japan", "tokyo"], ["#Japan", "#IndoPacific"]),
        (["korea", "seoul"], ["#SouthKorea", "#AsiaSecurity"]),
    ]

    for kws, tags in kmap:
        if any(k in t for k in kws):
            base.extend(tags)
            break

    seen, unique = set(), []
    for tag in base:
        if tag not in seen:
            seen.add(tag)
            unique.append(tag)
    return " ".join(unique[:5])


# ── Actor Detection ───────────────────────────────────────────────────────────
def _detect_actor(text: str) -> str:
    """Detect the primary geopolitical actor/region from text."""
    t = text.lower()
    actor_map = [
        (["china", "beijing", "xi jinping", "pla"], "China"),
        (["russia", "moscow", "putin", "kremlin"], "Russia"),
        (["ukraine", "kyiv", "zelensky"], "Ukraine"),
        (["united states", "washington", "pentagon", "biden", "trump"], "USA"),
        (["india", "modi", "new delhi"], "India"),
        (["taiwan", "taipei"], "Taiwan"),
        (["iran", "tehran"], "Iran"),
        (["israel", "tel aviv"], "Israel"),
        (["nato"], "NATO"),
        (["brics"], "BRICS"),
        (["south china sea"], "South China Sea"),
        (["pakistan", "islamabad"], "Pakistan"),
        (["north korea", "pyongyang", "kim jong"], "North Korea"),
        (["saudi", "riyadh", "opec"], "Saudi Arabia"),
        (["europe", "eu ", "brussels", "european union"], "Europe"),
        (["japan", "tokyo"], "Japan"),
        (["africa"], "Africa"),
        (["middle east"], "Middle East"),
        (["arctic"], "Arctic"),
        (["indo-pacific", "indopacific"], "Indo-Pacific"),
    ]
    for keywords, label in actor_map:
        if any(k in t for k in keywords):
            return label
    return "Global Affairs"


# ── Topic Discovery ───────────────────────────────────────────────────────────
def discover_topic() -> dict:
    query = random.choice(_DISCOVERY_QUERIES)
    log.info(f"🔎 Discovering topic (query: '{query}')...")
    try:
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": config.TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "topic": "news",
            "max_results": 10,
        }, timeout=20)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            raise ValueError("No results returned from Tavily")

        chosen = random.choice(results)
        topic_title = chosen.get("title", "").strip()[:120]
        combined_text = topic_title + " " + chosen.get("content", "")
        actor = _detect_actor(combined_text)

        log.info(f"✅ Topic: '{topic_title}' | Actor: {actor}")
        return {
            "topic": topic_title,
            "actor": actor,
            "hashtags": _extract_hashtags(topic_title),
        }
    except Exception as e:
        log.warning(f"⚠️ Topic discovery failed: {e}. Using fallback.")
    return random.choice(_FALLBACK_TOPICS)


# ── Google Sheets ─────────────────────────────────────────────────────────────
def get_sheet():
    """Authenticate with Google Sheets and return/initialize the target worksheet."""
    creds = Credentials.from_service_account_file(
        os.path.join(_SCRIPT_DIR, config.GOOGLE_CREDENTIALS_FILE),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(config.GOOGLE_SHEET_ID)

    try:
        return spreadsheet.worksheet(config.SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        log.info(f"📝 Worksheet '{config.SHEET_NAME}' not found. Initializing...")
        worksheets = spreadsheet.worksheets()
        default_names = ["Sheet1", "シート1", "Blad1", "Tabelle1"]
        if len(worksheets) == 1 and worksheets[0].title in default_names:
            worksheet = worksheets[0]
            worksheet.update_title(config.SHEET_NAME)
        else:
            worksheet = spreadsheet.add_worksheet(
                title=config.SHEET_NAME, rows=1000, cols=10
            )
        headers = ["Date", "Topic", "Actor", "Tweet", "ImageURL", "QualityScore", "Status", "PostedAt"]
        worksheet.append_row(headers)
        log.info("✅ Initialized worksheet with headers.")
        return worksheet


def is_duplicate(date_str: str) -> bool:
    try:
        return date_str in get_sheet().col_values(1)
    except Exception as e:
        log.warning(f"⚠️ Duplicate check failed: {e}")
        return False


def log_to_sheet(date, topic, actor, tweet, image_url, score, status):
    try:
        get_sheet().append_row([
            date, topic, actor, tweet, image_url, score, status,
            datetime.now().isoformat()
        ])
        log.info("✅ Logged to Google Sheets")
    except Exception as e:
        log.warning(f"⚠️ Sheets log failed: {e}")


# ── Gmail ─────────────────────────────────────────────────────────────────────
def send_email(subject: str, body: str):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.GMAIL_SENDER
        msg["To"] = config.GMAIL_RECEIVER
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(config.GMAIL_SENDER, config.GMAIL_APP_PASSWORD)
            s.sendmail(config.GMAIL_SENDER, config.GMAIL_RECEIVER, msg.as_string())
        log.info("📧 Email sent")
    except Exception as e:
        log.warning(f"⚠️ Email failed: {e}")


# ── Research ──────────────────────────────────────────────────────────────────
def research_topic(topic: str, actor: str) -> str:
    try:
        r = requests.post("https://api.tavily.com/search", json={
            "api_key": config.TAVILY_API_KEY,
            "query": f"{topic} latest news 2026",
            "search_depth": "advanced",
            "topic": "news",
            "max_results": 5,
            "include_answer": True,
        }, timeout=25)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])

        lines = []
        if data.get("answer"):
            lines.append("Key Insight: " + data["answer"])
        for res in results[:4]:
            c = res.get("content", "").strip()
            if c:
                lines.append(f"[{res.get('title', '')}] {c[:250]}...")

        summary = "\n\n".join(lines)
        if len(summary) < 50:
            raise ValueError("Too little content returned")

        log.info(f"🔍 Research done ({len(results)} sources)")
        return summary
    except Exception as e:
        log.warning(f"⚠️ Research failed: {e}")
    return f"Topic: {topic}\nActor: {actor}\nWrite about the latest 2026 geopolitical developments."


# ── Tweet Generation ──────────────────────────────────────────────────────────
def generate_tweet(research: str, topic: str, actor: str, hashtags: str) -> str:
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 400,
        "temperature": 0.85,
        "messages": [{
        "role": "system",
        "content": (
        "You are a witty, sarcastic geopolitical commentator on X (Twitter) — "
        "a blend of a foreign policy analyst, an observational comedian, and a chronically online news addict. "
        "You explain world events through clever, relatable analogies that make complex geopolitics instantly understandable "
        "(like trade wars as passive-aggressive roommate disputes, military alliances as chaotic group projects, "
        "or diplomatic summits as awkward family reunions where everyone remembers old grudges). "
        "Your humor is sharp, dry, and insightful, making people laugh while teaching them something meaningful. "
        "You mock incentives, contradictions, and political theater—not ordinary people or human suffering. "
        "Every joke must remain factually grounded and never invent information or speculate beyond the provided context. "
        "For serious events involving war, terrorism, or civilian casualties, reduce the humor and focus on irony, diplomacy, "
        "and the absurdity of power politics rather than the tragedy itself. "
        "Avoid repetitive joke formats and vary your analogies between office politics, dating, startups, sports, "
        "internet culture, family drama, and corporate meetings. "
        "Sound natural, human, and effortlessly clever—not like an AI trying too hard to be funny. "
        "Use a maximum of 2 emojis. Keep the tweet under 260 characters. "
        "Never be clickbait. Never be partisan. Prioritize insight over virality, but never be boring."
    ),
},
            {
                "role": "user",
                "content": (
                    f"Write a witty, sarcastic tweet about {actor} based on this research:\n\n{research}\n\n"
                    f"Topic: {topic}\n\n"
                    f"Rules:\n"
                    f"1. Open with a sarcastic or ironic hook that makes people stop scrolling\n"
                    f"2. Use an analogy or unexpected comparison to make the geopolitics relatable and funny\n"
                    f"3. Slip in the real insight or consequence so people actually learn something\n"
                    f"4. End with: {hashtags}\n\n"
                    f"Tone: witty commentator, dry humor, irony — NOT a news headline, NOT a lecture.\n"
                    f"Examples of good hooks:\n"
                    f"- 'Ah yes, nothing says diplomacy like...'\n"
                    f"- 'Plot twist nobody asked for:'\n"
                    f"- 'Two nuclear powers walk into a trade deal...'\n"
                    f"- 'Imagine your landlord also controls your oil supply.'\n\n"
                    f"Write only the tweet text. No quotes. No commentary. Max 280 chars total."
                ),
            },
        ],
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers, json=body, timeout=30
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ── Quality Check ─────────────────────────────────────────────────────────────
def quality_check(tweet_text: str) -> dict:
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 100,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a geopolitics Twitter content reviewer who values wit, sarcasm, "
                    "and entertaining writing. Respond ONLY with valid JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Review this geopolitics tweet:\n\n{tweet_text}\n\n"
                    f"Score 1-10 on: hook (is it witty/ironic?), analogy quality, "
                    f"geopolitical accuracy, entertainment value.\n"
                    f"Penalise if it sounds like a boring news headline. "
                    f"Reward clever analogies, sarcasm, and irony that still teach something.\n"
                    f'Respond with exactly: {{"score": 8, "approved": true, "reason": "brief reason"}}\n'
                    f"approved=true if score >= {config.QUALITY_MIN_SCORE}."
                ),
            },
        ],
    }
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers, json=body, timeout=20
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*?\}", content, re.DOTALL)
        if m:
            return json.loads(m.group())
        log.warning("⚠️ Quality parse failed — defaulting approved.")
        return {"score": 7, "approved": True, "reason": "parse fallback"}


# ── Image Prompt Generation ───────────────────────────────────────────────────
def generate_image_prompt(tweet_text: str) -> str:
    try:
        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "llama-3.3-70b-versatile",
            "max_tokens": 120,
            "temperature": 0.7,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Generate a detailed image prompt for a geopolitical tweet visual. "
                        "Style: editorial photojournalism, dramatic lighting, "
                        "world maps, flags, diplomatic settings, military silhouettes, "
                        "or symbolic geopolitical imagery. "
                        "No text, no logos, no watermarks, no people's faces. "
                        "Respond ONLY with the raw prompt, nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Create an image prompt for this geopolitics tweet:\n\n{tweet_text}",
                },
            ],
        }
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=body, timeout=20
        )
        r.raise_for_status()
        prompt = (
            r.json()["choices"][0]["message"]["content"]
            .strip()
            .replace('"', '')
            .replace("'", "")
        )
        if "no text" not in prompt.lower():
            prompt += ", editorial style, dramatic lighting, 4K, no text, no logos, no faces"
        log.info(f"🎨 Image prompt: {prompt[:80]}...")
        return prompt
    except Exception as e:
        log.warning(f"⚠️ Image prompt failed: {e}")
    return (
        "Dramatic geopolitical world map, flags, diplomatic summit silhouettes, "
        "cinematic editorial lighting, 4K, no text, no logos, no faces"
    )


# ── Image Generation ──────────────────────────────────────────────────────────
def generate_image(prompt: str) -> tuple:
    seed = random.randint(1, 99999)
    encoded = requests.utils.quote(prompt)
    url = (
        f"https://gen.pollinations.ai/image/{encoded}"
        f"?model=flux&width=1200&height=675&seed={seed}&nologo=true"
    )
    log.info("🖼️  Generating image via Pollinations.AI...")
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {config.POLLINATIONS_API_KEY}"},
        timeout=90,
    )
    r.raise_for_status()
    if "image" in r.headers.get("Content-Type", ""):
        log.info(f"🖼️  Image ready ({len(r.content) // 1024} KB)")
        return r.content, url
    raise Exception(
        f"Unexpected response: {r.status_code} {r.headers.get('Content-Type')}"
    )


# ── Post to X via Playwright (100% free — no API needed) ────────────────────
def post_to_x(tweet_text: str, image_bytes: bytes) -> str:
    """Log into X via Playwright browser and post a tweet with an image.
    Returns the tweet URL. Raises Exception on failure.
    """
    # Save image bytes to a temp file so Playwright can attach it
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(image_bytes)
        img_path = tmp.name

    session_file = os.path.join(_SCRIPT_DIR, ".x_session.json")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )

            # Re-use saved session to avoid login every time
            ctx_options = {
                "user_agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "viewport": {"width": 1280, "height": 800},
            }
            if os.path.exists(session_file):
                ctx_options["storage_state"] = session_file
                context = browser.new_context(**ctx_options)
                log.info("♻️  Reusing saved X session")
            else:
                context = browser.new_context(**ctx_options)

            page = context.new_page()
            # Remove webdriver flag
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

            # Helper function to dismiss common overlay popups
            def dismiss_overlays():
                try:
                    popup_selectors = [
                        '#layers button:has-text("Not now")',
                        '#layers button:has-text("Got it")',
                        '#layers div[role="button"]:has-text("Dismiss")',
                        '#layers [data-testid="app-bar-close"]',
                        '#layers button[aria-label="Close"]',
                        '#layers button[aria-label="Dismiss"]',
                        '#layers button:has-text("Skip")',
                    ]
                    for sel in popup_selectors:
                        btn = page.locator(sel).first
                        if btn.is_visible():
                            log.info(f"Dismissing overlay popup: {sel}")
                            btn.click(timeout=3000)
                            page.wait_for_timeout(1000)
                except Exception:
                    pass

            try:
                # ── Login if no saved session ───────────────────────────────
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)  # let JS settle

                if "/login" in page.url or "/flow/login" in page.url or page.url.endswith("x.com/"):
                    log.info("🔐 Session expired or missing. Logging into X...")
                    page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)

                    # Enter username/email
                    username_sel = 'input[autocomplete*="username"], input[name="username_or_email"], input[autocomplete="username"]'
                    page.wait_for_selector(username_sel, timeout=15000)
                    page.fill(username_sel, config.X_USERNAME)
                    
                    # Click "Next" or "Continue"
                    btn_selectors = [
                        'button:has-text("Next")',
                        'button:has-text("Continue")',
                        'div[role="button"]:has-text("Next")',
                        'div[role="button"]:has-text("Continue")',
                        'span:has-text("Next")',
                        'span:has-text("Continue")'
                    ]
                    clicked = False
                    for btn_sel in btn_selectors:
                        try:
                            locator = page.locator(btn_sel).first
                            if locator.is_visible():
                                locator.click()
                                clicked = True
                                break
                        except Exception:
                            pass
                    if not clicked:
                        page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)

                    # X sometimes asks for email verification
                    try:
                        page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                        log.info("📧 X asked for email verification")
                        page.fill('input[data-testid="ocfEnterTextTextInput"]', config.X_EMAIL)
                        page.keyboard.press("Enter")
                    except PlaywrightTimeout:
                        pass  # No email prompt — continue

                    # Enter password
                    page.wait_for_selector('input[name="password"]', timeout=15000)
                    page.fill('input[name="password"]', config.X_PASSWORD)
                    
                    # Click Log In button or press Enter
                    login_btn_selectors = [
                        'button:has-text("Log in")',
                        'button:has-text("Log In")',
                        'div[role="button"]:has-text("Log in")',
                        'div[role="button"]:has-text("Log In")',
                        'span:has-text("Log in")',
                        'span:has-text("Log In")'
                    ]
                    login_clicked = False
                    for l_sel in login_btn_selectors:
                        try:
                            locator = page.locator(l_sel).first
                            if locator.is_visible():
                                locator.click()
                                login_clicked = True
                                break
                        except Exception:
                            pass
                    if not login_clicked:
                        page.keyboard.press("Enter")

                    page.wait_for_url("https://x.com/home", timeout=20000)
                    log.info("✅ Logged into X")

                    # Save session for future runs
                    context.storage_state(path=session_file)
                    log.info("💾 X session saved")

                # ── Navigate to home and open compose ──────────────────────
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                dismiss_overlays()

                # Click compose tweet button
                page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=15000)
                tweet_box = page.locator('[data-testid="tweetTextarea_0"]')
                try:
                    tweet_box.click(timeout=5000)
                except Exception as click_err:
                    log.warning(f"⚠️ Standard tweet box click failed: {click_err}. Trying forced click...")
                    tweet_box.click(force=True)

                # ── Attach image ────────────────────────────────────────────
                file_input = page.locator('input[data-testid="fileInput"]')
                file_input.set_input_files(img_path)
                log.info("📎 Image attached")

                # Wait for image upload to complete
                page.wait_for_selector('[data-testid="attachments"]', timeout=30000)
                dismiss_overlays()

                # ── Type the tweet text ─────────────────────────────────────
                try:
                    tweet_box.click(timeout=5000)
                except Exception as click_err:
                    log.warning(f"⚠️ Standard tweet box click before typing failed: {click_err}. Trying forced click...")
                    tweet_box.click(force=True)
                tweet_box.focus()
                page.keyboard.type(tweet_text, delay=20)
                log.info(f"✍️  Tweet typed ({len(tweet_text)} chars)")

                # ── Submit tweet ────────────────────────────────────────────
                send_btn = page.locator('[data-testid="tweetButton"], [data-testid="tweetButtonInline"]').first
                send_btn.wait_for(state="visible", timeout=10000)
                dismiss_overlays()
                try:
                    send_btn.click(timeout=5000)
                except Exception as click_err:
                    log.warning(f"⚠️ Standard click failed: {click_err}. Trying forced click...")
                    send_btn.click(force=True)

                # Wait briefly to let the tweet post
                page.wait_for_timeout(4000)

                # ── Grab tweet URL ──────────────────────────────────────────
                tweet_url = "https://x.com/" + config.X_USERNAME
                try:
                    # Look for the posted tweet link in the timeline
                    page.goto(f"https://x.com/{config.X_USERNAME}", wait_until="networkidle", timeout=20000)
                    first_tweet = page.locator('article[data-testid="tweet"] a[href*="/status/"]').first
                    href = first_tweet.get_attribute("href", timeout=8000)
                    if href:
                        tweet_url = "https://x.com" + href
                except Exception:
                    pass  # URL fallback is fine

                log.info(f"🚀 Tweeted! {tweet_url}")
                context.storage_state(path=session_file)  # refresh session
                browser.close()
                return tweet_url

            except Exception as inner_err:
                try:
                    error_screenshot = os.path.join(_logs_dir, "x_error.png")
                    page.screenshot(path=error_screenshot)
                    log.info(f"📸 Saved error screenshot to {error_screenshot}")
                except Exception as screenshot_err:
                    log.warning(f"⚠️ Failed to take error screenshot: {screenshot_err}")
                raise inner_err

    except PlaywrightTimeout as e:
        raise Exception(f"Playwright timed out: {e}")
    finally:
        os.unlink(img_path)


# ── Main Workflow ─────────────────────────────────────────────────────────────
def run_workflow():
    log.info("=" * 50)
    log.info("▶ Starting X geopolitics auto-tweet workflow")

    today = datetime.now().strftime("%Y-%m-%d")
    topic_data = discover_topic()
    topic    = topic_data["topic"]
    actor    = topic_data["actor"]
    hashtags = topic_data["hashtags"]
    log.info(f"📅 {today} | Topic: {topic} | Actor: {actor}")

    if is_duplicate(today):
        log.info("⏭️  Already tweeted today — skipping.")
        send_email(
            f"[X Bot] Skipped — Already posted today ({today})",
            f"Already tweeted on {today}.\nTopic: {topic}\nNo action needed."
        )
        return

    try:
        research  = research_topic(topic, actor)
        post_text = None
        quality   = None

        for attempt in range(1, config.MAX_RETRIES + 1):
            log.info(f"✍️  Generating tweet (attempt {attempt}/{config.MAX_RETRIES})")
            post_text = generate_tweet(research, topic, actor, hashtags)
            quality   = quality_check(post_text)
            log.info(f"📊 Quality: {quality['score']}/10 — {quality['reason']}")
            if quality["approved"]:
                break
            log.warning(f"⚠️ Score {quality['score']}/10 below minimum. Retrying...")

        if not quality["approved"]:
            log.error(f"❌ Quality gate failed after {config.MAX_RETRIES} attempts.")
            send_email(
                f"[X Bot] ⚠️ Quality failed ({today})",
                (
                    f"Tweet quality too low after {config.MAX_RETRIES} attempts.\n"
                    f"Score: {quality['score']}/10\nTopic: {topic}"
                )
            )
            log_to_sheet(today, topic, actor, post_text, "", quality["score"], "QUALITY_FAILED")
            return

        image_prompt         = generate_image_prompt(post_text)
        image_bytes, img_url = generate_image(image_prompt)
        tweet_url            = post_to_x(post_text, image_bytes)

        log_to_sheet(today, topic, actor, post_text, img_url, quality["score"], "SUCCESS")
        send_email(
            f"[X Bot] ✅ Tweeted — {actor} ({today})",
            (
                f"Tweet published!\n\n"
                f"Date: {today}\n"
                f"Actor/Region: {actor}\n"
                f"Topic: {topic}\n"
                f"Quality: {quality['score']}/10\n\n"
                f"Tweet URL: {tweet_url}\n\n"
                f"--- PREVIEW ---\n\n{post_text}"
            )
        )
        log.info("✅ Workflow complete")

    except requests.exceptions.HTTPError as e:
        err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        log.error(f"❌ HTTP error: {err}")
        send_email(
            f"[X Bot] ❌ HTTP error ({today})",
            f"Error: {err}\nTopic: {topic}\nCheck logs."
        )
        log_to_sheet(today, topic, actor, "", "", 0, f"ERROR: {err}")


    except Exception as e:
        log.error(f"❌ Unexpected error: {e}")
        send_email(
            f"[X Bot] ❌ Crashed ({today})",
            f"Unexpected error: {e}\nTopic: {topic}\nCheck logs."
        )
        log_to_sheet(today, topic, actor, "", "", 0, f"ERROR: {e}")


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("🚀 Running workflow immediately...")
    run_workflow()
    log.info("🏁 Done.")