"""
Arkhashom Back to School — single-bot cloud runner for GitHub Actions.
One bot, one history, one run cycle.
"""
import os
import re
import time
from datetime import datetime

from scraper_backtoschool import AmazonScraper
from ai_caption import CaptionGenerator
from telegram_poster import TelegramPoster
from posted_history import PostedHistory

DATA_DIR = "data"

# ─── Config from environment ─────────────────────────────────────────────────
BOT_TOKEN         = os.environ["BOT_TOKEN"]
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "@arkhashomoffers")
AFFILIATE_TAG     = os.environ.get("AFFILIATE_TAG", "arkhashom-21")
BANNER_PATH       = os.environ.get("BANNER_PATH", "arkhashom_banner_backtoschool.png")
MAX_POSTS         = int(os.environ.get("MAX_POSTS_PER_RUN", "3"))
MIN_DISCOUNT      = int(os.environ.get("MIN_DISCOUNT", "15"))

CATEGORIES = [
    "deals", "bts_hub", "backpacks", "trolley_bags", "pencil_cases",
    "pens", "pencils", "notebooks", "office_supplies", "files_folders",
    "markers_highlighters", "colouring", "rulers_geometry",
    "erasers_sharpeners", "glue_scissors", "staplers_punch",
    "sticky_notes", "printing_paper", "calculators", "whiteboards",
    "art_supplies", "lunch_boxes", "water_bottles", "school_uniform",
    "school_shoes", "study_desks", "desk_chairs", "desk_lamps",
    "dorm_essentials", "books", "laptops", "tablets", "headphones",
    "printers", "storage_drives", "accessories", "laptop_bags",
    "kids_clothing", "kids_shoes", "biscuits", "juice",
    "chips_snacks", "breakfast",
]


def main():
    print(f"{'='*60}")
    print(f"  ARKHASHOM BACK TO SCHOOL BOT")
    print(f"  {datetime.now().isoformat(timespec='seconds')}")
    print(f"  Channel: {TELEGRAM_CHAT_ID}  |  Tag: {AFFILIATE_TAG}")
    print(f"  Max posts: {MAX_POSTS}  |  Min discount: {MIN_DISCOUNT}%")
    print(f"{'='*60}\n")

    os.makedirs(DATA_DIR, exist_ok=True)
    history_file = os.path.join(DATA_DIR, "posted_history.json")
    screenshot   = os.path.join(DATA_DIR, "screenshot.png")
    buttons_file = os.path.join(DATA_DIR, "buttons_store.json")

    # Build components
    scraper = AmazonScraper(
        headless=True,
        affiliate_tag=AFFILIATE_TAG,
        banner_path=BANNER_PATH,
        banner_text="Arkhashom Back to School",
        force_arabic=True,
    )
    captioner = CaptionGenerator(GEMINI_API_KEY)
    poster = TelegramPoster(BOT_TOKEN, TELEGRAM_CHAT_ID)
    poster.buttons_store.file_path = buttons_file
    poster.buttons_store.config = poster.buttons_store._load()
    history = PostedHistory(history_file)

    # Test connection
    ok, info = poster.test_connection()
    if not ok:
        print(f"❌ Telegram failed: {info}")
        scraper.close()
        return
    print(f"✅ @{info.get('username', '')} connected → {TELEGRAM_CHAT_ID}")

    # Discover
    print(f"🔄 Discovering across {len(CATEGORIES)} categories...")
    urls = scraper.discover_product_urls(CATEGORIES, max_per_category=20)
    fresh = history.filter_unposted(urls)
    print(f"   {len(fresh)} fresh candidates")

    posted = 0
    opens = 0
    max_opens = 20
    best_fallback = None

    for url in fresh:
        if posted >= MAX_POSTS or opens >= max_opens:
            break

        opens += 1
        disc = (scraper.deal_discount_for_url(url)
                if hasattr(scraper, "deal_discount_for_url") else 0)

        if best_fallback is None or disc > best_fallback[0]:
            best_fallback = (disc, url)

        info = scraper.get_product_info(url)
        if not info.get("title") or not info.get("current_price"):
            continue

        # Calculate discount
        d = str(info.get("discount_pct") or "")
        m = re.search(r"\d+", d)
        pct = int(m.group(0)) if m else 0
        if pct == 0:
            cur = re.sub(r"[^\d]", "", str(info.get("current_price") or ""))
            lst = re.sub(r"[^\d]", "", str(info.get("list_price") or ""))
            if cur and lst and int(lst) > int(cur) > 0:
                pct = round((1 - int(cur) / int(lst)) * 100)

        if pct < MIN_DISCOUNT:
            continue

        print(f"   ✅ {info['title'][:55]} [{pct}% off]")

        if not scraper.capture_product_screenshot(url, screenshot):
            if not info.get("image_url") or not scraper.download_image(
                    info["image_url"], screenshot):
                continue

        if not os.path.exists(screenshot) or os.path.getsize(screenshot) == 0:
            continue

        # Re-check history before posting
        if history.has_posted(url):
            print(f"   ⏭️ Already posted — skip")
            continue

        caption = captioner.generate(info)
        affiliate_url = info.get("affiliate_url") or info.get("url")
        ok_post, res = poster.post_product(screenshot, caption, affiliate_url)
        if ok_post:
            print(f"   ✅ Posted (id {res})")
            history.mark_posted(url, info["title"])
            posted += 1
            time.sleep(3)

    # Force-post best fallback if nothing cleared threshold
    if posted == 0 and best_fallback:
        disc, url = best_fallback
        if not history.has_posted(url):
            print(f"⚡ Force-posting best available ({disc}% off)")
            info = scraper.get_product_info(url)
            if info.get("title") and info.get("current_price"):
                if scraper.capture_product_screenshot(url, screenshot):
                    caption = captioner.generate(info)
                    ok_post, res = poster.post_product(screenshot, caption,
                                                       info.get("affiliate_url") or url)
                    if ok_post:
                        history.mark_posted(url, info.get("title", ""))
                        posted += 1

    scraper.close()
    print(f"\n{'='*60}")
    print(f"  DONE — Posted {posted} items")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
