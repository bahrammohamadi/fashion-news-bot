# ============================================================
# Telegram Fashion News Bot — @irfashionnews
# Version:    13.0 — Full Rewrite, Schema-Correct
# Runtime:    Python 3.12 / Appwrite Cloud Functions
# Timeout:    120 seconds
#
# DB SCHEMA (Appwrite: fashion_db → history):
#   $id            string (auto/manual)
#   link           string  1000  required
#   title          string  500
#   published_at   datetime
#   feed_url       string  500
#   source_type    string  20
#   title_hash     string  64
#   content_hash   string  64
#   category       string  50
#   trend_score    integer
#   post_hour      integer
#   domain_hash    string  64
#   $createdAt     datetime (auto)
#   $updatedAt     datetime (auto)
#
# DEDUP STRATEGY:
#   title_hash = SHA-256 of sorted normalized title tokens
#   content_hash = SHA-256 of normalized title (no description)
#   domain_hash = SHA-256 of feed domain
#   Duplicate check: title_hash only (title is canonical identity)
#   Document ID = title_hash[:36] → Appwrite 409 on conflict
#   Save BEFORE post → race-condition proof
#
# ARCHITECTURE:
#   Phase 1: Fetch all feeds in parallel with retry
#   Phase 2: Load all title_hashes from DB once (in-memory)
#   Phase 3: Filter + dedup (in-memory, instant)
#   Phase 4: Save-then-post for ALL qualifying items
# ============================================================

import os
import re
import asyncio
import hashlib
import random
import requests
import feedparser

from datetime import datetime, timedelta, timezone
from time import monotonic, sleep
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from telegram import Bot, InputMediaPhoto, LinkPreviewOptions
from telegram.error import TelegramError


# ═══════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═══════════════════════════════════════════════════════════

BRAND_FEEDS: list[dict] = [
    {"url": "https://lafemmeroje.com/feed/",
     "brand": "La Femme Roje | لا فم روژ",
     "tag": "#LaFemmeRoje #لافم_روژ",
     "category": "women"},
    {"url": "https://salian.ir/feed/",
     "brand": "Salian | سالیان",
     "tag": "#Salian #سالیان",
     "category": "women"},
    {"url": "https://celebon.com/feed/",
     "brand": "Celebon | سلبون",
     "tag": "#Celebon #سلبون",
     "category": "unisex"},
    {"url": "https://siawood.com/feed/",
     "brand": "Siawood | سیاوود",
     "tag": "#Siawood #سیاوود",
     "category": "men"},
    {"url": "https://naghmehkiumarsi.com/feed/",
     "brand": "Naghmeh Kiumarsi | نغمه کیومرثی",
     "tag": "#NaghmehKiumarsi #نغمه_کیومرثی",
     "category": "designer"},
    {"url": "https://pooshmode.com/feed/",
     "brand": "Poosh | پوش",
     "tag": "#Poosh #پوش_مد",
     "category": "women"},
    {"url": "https://kimiamode.com/feed/",
     "brand": "Kimia | کیمیا",
     "tag": "#Kimia #کیمیا_مد",
     "category": "women"},
    {"url": "https://mihanomomosa.com/feed/",
     "brand": "Mihano Momosa | میهانو موموسا",
     "tag": "#MihanoMomosa #میهانو_موموسا",
     "category": "designer"},
    {"url": "https://taghcheh.com/feed/",
     "brand": "Taghcheh | طاقچه",
     "tag": "#Taghcheh #طاقچه",
     "category": "marketplace"},
    {"url": "https://parmimanto.com/feed/",
     "brand": "Parmi Manto | پارمی مانتو",
     "tag": "#ParmiManto #پارمی_مانتو",
     "category": "women"},
    {"url": "https://banoosara.com/feed/",
     "brand": "Banoo Sara | بانو سارا",
     "tag": "#BanooSara #بانو_سارا",
     "category": "women"},
    {"url": "https://roshanakmode.com/feed/",
     "brand": "Roshanak | رشنک",
     "tag": "#Roshanak #رشنک",
     "category": "women"},
    {"url": "https://bodyspinner.com/feed/",
     "brand": "Bodyspinner | بادی اسپینر",
     "tag": "#Bodyspinner #بادی_اسپینر",
     "category": "activewear"},
    {"url": "https://garoudi.com/feed/",
     "brand": "Garoudi | گارودی",
     "tag": "#Garoudi #گارودی",
     "category": "leather"},
    {"url": "https://hacoupian.com/feed/",
     "brand": "Hacoupian | هاکوپیان",
     "tag": "#Hacoupian #هاکوپیان",
     "category": "men"},
    {"url": "https://holidayfashion.ir/feed/",
     "brand": "Holiday | هالیدی",
     "tag": "#Holiday #هالیدی",
     "category": "unisex"},
    {"url": "https://lcman.ir/feed/",
     "brand": "LC Man | ال سی من",
     "tag": "#LCMan #ال_سی_من",
     "category": "men"},
    {"url": "https://narbon.ir/feed/",
     "brand": "Narbon | ناربن",
     "tag": "#Narbon #ناربن",
     "category": "women"},
    {"url": "https://narian.ir/feed/",
     "brand": "Narian | ناریان",
     "tag": "#Narian #ناریان",
     "category": "women"},
    {"url": "https://patanjameh.com/feed/",
     "brand": "Patan Jameh | پاتان جامه",
     "tag": "#PatanJameh #پاتان_جامه",
     "category": "traditional"},
    {"url": "https://medopia.ir/feed/",
     "brand": "Medopia | مدوپیا",
     "tag": "#Medopia #مدوپیا",
     "category": "aggregator"},
    {"url": "https://www.digistyle.com/mag/feed/",
     "brand": "Digistyle | دیجی‌استایل",
     "tag": "#Digistyle #دیجی_استایل",
     "category": "aggregator"},
    {"url": "https://www.chibepoosham.com/feed/",
     "brand": "Chi Be Poosham | چی بپوشم",
     "tag": "#ChibePooosham #چی_بپوشم",
     "category": "aggregator"},
]

POSITIVE_KEYWORDS = [
    'مد', 'فشن', 'استایل', 'زیبایی', 'لباس', 'پوشاک',
    'طراحی لباس', 'ترند', 'کلکسیون', 'برند', 'سیزن',
    'آرایش', 'مانتو', 'پیراهن', 'کت', 'شلوار', 'کیف',
    'کفش', 'اکسسوری', 'جواهر', 'طلا', 'عطر', 'نگین',
    'پالتو', 'ست لباس', 'مزون', 'خیاطی', 'بافت', 'تونیک',
    'بلوز', 'دامن', 'شنل', 'کاپشن', 'جوراب', 'روسری',
    'پارچه', 'طرح', 'دوخت', 'برند ایرانی', 'محصول جدید',
    'fashion', 'style', 'beauty', 'clothing', 'trend',
    'outfit', 'couture', 'collection', 'lookbook', 'brand',
    'wardrobe', 'luxury', 'designer', 'new arrival', 'product',
    'coat', 'dress', 'blouse', 'skirt', 'jacket', 'accessory',
]

NEGATIVE_KEYWORDS = [
    'فیلم', 'سینما', 'سریال', 'بازیگر', 'کارگردان', 'اسکار',
    'صبحانه', 'رژیم غذایی', 'طرز تهیه', 'دستور پخت', 'آشپزی',
    'اپل', 'گوگل', 'آیفون', 'سامسونگ', 'تکنولوژی', 'گیم',
    'فوتبال', 'والیبال', 'ورزش', 'تیم ملی', 'لیگ',
    'بورس', 'ارز', 'دلار', 'سکه', 'بیت کوین', 'اقتصاد',
    'انتخابات', 'سیاسی', 'مجلس', 'دولت', 'وزیر',
    'زلزله', 'سیل', 'آتش سوزی', 'تصادف', 'حادثه', 'کشته',
]

FIXED_HASHTAGS = (
    "#مد #استایل #ترند #برند_ایرانی #فشن_ایرانی "
    "#fashion #IranianFashion #style"
)

# ── Limits ──
MAX_DESC_CHARS     = 350
MAX_IMAGES         = 5
CAPTION_MAX        = 1020
PUBLISH_BATCH_SIZE = 5

# ── Timeouts ──
GLOBAL_DEADLINE_SEC = 110
FEED_FETCH_TIMEOUT  = 8
FEEDS_TOTAL_TIMEOUT = 25
PAGE_TIMEOUT        = 6
DB_TIMEOUT          = 5

# ── Retry ──
FEED_MAX_RETRIES = 2
FEED_RETRY_BASE  = 0.5

# ── Weekly window ──
HOURS_THRESHOLD = 168

# ── Delays ──
ALBUM_CAPTION_DELAY = 2.5
STICKER_DELAY       = 1.5
INTER_POST_DELAY    = 3.0

# ── Image ──
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
IMAGE_BLOCKLIST  = [
    'doubleclick', 'googletagmanager', 'googlesyndication',
    'facebook.com/tr', 'analytics', 'pixel', 'beacon',
    'tracking', 'counter', 'stat.', 'stats.',
]

FASHION_STICKERS = [
    "CAACAgIAAxkBAAIBmGRx1yRFMVhVqVXLv_dAAXJMOdFNAAIUAAOVgnkAAVGGBbBjxbg4LwQ",
    "CAACAgIAAxkBAAIBmWRx1yRqy9JkN2DmV_Z2sRsKdaTjAAIVAAOVgnkAAc8R3q5p5-AELAQ",
    "CAACAgIAAxkBAAIBmmRx1yS2T2gfLqJQX9oK6LZqp1HIAAIWAAO0yXAAAV0MzCRF3ZRILAQ",
    "CAACAgIAAxkBAAIBm2Rx1ySiJV4dVeTuCTc-RfFDnfQpAAIXAAO0yXAAAA3Vm7IiJdisLAQ",
    "CAACAgIAAxkBAAIBnGRx1yT_jVlWt5xPJ7BO9aQ4JvFaAAIYAAO0yXAAAA0k9GZDQpLcLAQ",
]


# ═══════════════════════════════════════════════════════════
# SECTION 2 — MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

async def main(event=None, context=None):
    _t0 = monotonic()

    def _remaining() -> float:
        return GLOBAL_DEADLINE_SEC - (monotonic() - _t0)

    print("[INFO] ══════════════════════════════════════")
    print("[INFO] Fashion Bot v13.0 started")
    print(f"[INFO] {datetime.now(timezone.utc).isoformat()}")
    print(f"[INFO] {len(BRAND_FEEDS)} feeds | "
          f"window={HOURS_THRESHOLD}h | batch={PUBLISH_BATCH_SIZE}")
    print("[INFO] ══════════════════════════════════════")

    config = _load_config()
    if not config:
        return {"status": "error", "reason": "missing_env_vars"}

    bot = Bot(token=config["token"])
    db  = _AppwriteDB(
        endpoint      = config["endpoint"],
        project       = config["project"],
        key           = config["key"],
        database_id   = config["database_id"],
        collection_id = config["collection_id"],
    )

    now            = datetime.now(timezone.utc)
    time_threshold = now - timedelta(hours=HOURS_THRESHOLD)
    loop           = asyncio.get_event_loop()

    stats = {
        "feeds_ok": 0, "feeds_fail": 0, "feeds_retry": 0,
        "entries_total": 0,
        "skip_time": 0, "skip_filter": 0, "skip_dupe": 0,
        "posted": 0, "errors": 0,
        "db_timeout": False,
    }

    # ════════════════════════════════════════════════
    # PHASE 1: Fetch all brand feeds in parallel
    # ════════════════════════════════════════════════
    fetch_budget = min(FEEDS_TOTAL_TIMEOUT, _remaining() - 60)
    if fetch_budget < 5:
        print("[WARN] Not enough time for feeds")
        return _build_response(stats)

    print(f"\n[PHASE 1] Fetching feeds (budget={fetch_budget:.1f}s)")

    try:
        all_items = await asyncio.wait_for(
            _fetch_all_parallel(loop, stats),
            timeout=fetch_budget,
        )
    except asyncio.TimeoutError:
        print("[WARN] Feed fetch timed out — partial results")
        all_items = []

    stats["entries_total"] = len(all_items)
    print(f"[PHASE 1] Done: {len(all_items)} entries from "
          f"{stats['feeds_ok']}/{len(BRAND_FEEDS)} feeds "
          f"[{_remaining():.1f}s left]")

    if not all_items:
        return _build_response(stats)

    # Sort newest first
    all_items.sort(
        key=lambda x: x["pub_date"] or datetime.min.replace(
            tzinfo=timezone.utc),
        reverse=True,
    )

    # ════════════════════════════════════════════════
    # PHASE 2: Load existing title_hashes from DB
    # ════════════════════════════════════════════════
    known_hashes: set[str] = set()
    known_links:  set[str] = set()

    db_budget = min(DB_TIMEOUT, _remaining() - 50)
    if db_budget > 2:
        print(f"\n[PHASE 2] Loading DB state (budget={db_budget:.1f}s)")
        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(None, db.load_recent, 500),
                timeout=db_budget,
            )
            for rec in raw:
                if rec.get("title_hash"):
                    known_hashes.add(rec["title_hash"])
                if rec.get("link"):
                    known_links.add(rec["link"])
            print(f"[PHASE 2] Done: {len(raw)} records → "
                  f"{len(known_hashes)} hashes, {len(known_links)} links "
                  f"[{_remaining():.1f}s left]")
        except asyncio.TimeoutError:
            stats["db_timeout"] = True
            print("[WARN] DB load timed out — relying on save-based 409")
        except Exception as e:
            stats["db_timeout"] = True
            print(f"[ERROR] DB load: {e}")
    else:
        print("[WARN] No budget for DB load")

    local_posted: set[str] = set()

    # ════════════════════════════════════════════════
    # PHASE 3: Filter + Dedup + Post ALL qualifying
    # ════════════════════════════════════════════════
    print(f"\n[PHASE 3] Processing {len(all_items)} entries")

    for item in all_items:
        if _remaining() < 20:
            print(f"[INFO] Time budget low ({_remaining():.1f}s) — stop")
            break
        if stats["posted"] >= PUBLISH_BATCH_SIZE:
            print(f"[INFO] Batch limit ({PUBLISH_BATCH_SIZE}) reached")
            break

        title      = item["title"]
        link       = item["link"]
        desc       = item["desc"]
        pub_date   = item["pub_date"]
        brand_name = item["brand"]
        brand_tag  = item["tag"]
        feed_url   = item["feed_url"]
        category   = item["category"]
        entry      = item["entry"]

        # ── Time filter ──
        if pub_date and pub_date < time_threshold:
            stats["skip_time"] += 1
            continue

        # ── Fashion filter ──
        if not _is_fashion(title, desc, feed_url, brand_name):
            stats["skip_filter"] += 1
            brand_short = brand_name.split("|")[0].strip()
            print(f"  [SKIP:filter] [{brand_short}] {title[:50]}")
            continue

        # ── Compute hashes ──
        title_hash   = _make_title_hash(title)
        content_hash = _make_content_hash(title)
        domain_hash  = _make_domain_hash(feed_url)

        # ── Dedup: in-process ──
        if title_hash in local_posted:
            stats["skip_dupe"] += 1
            continue

        # ── Dedup: from DB load ──
        if title_hash in known_hashes:
            stats["skip_dupe"] += 1
            brand_short = brand_name.split("|")[0].strip()
            print(f"  [SKIP:dupe:hash] [{brand_short}] {title[:50]}")
            continue

        # ── Dedup: link ──
        if link in known_links:
            stats["skip_dupe"] += 1
            brand_short = brand_name.split("|")[0].strip()
            print(f"  [SKIP:dupe:link] [{brand_short}] {title[:50]}")
            continue

        brand_short = brand_name.split("|")[0].strip()
        print(f"\n  [CANDIDATE] [{brand_short}] {title[:55]}")

        # ── Trend score ──
        trend_score = _calc_trend_score(title, desc, brand_name)

        # ── Post hour ──
        post_hour = now.hour

        # ── Source type ──
        source_type = "brand"
        if category in ("aggregator",):
            source_type = "aggregator"

        # ── SAVE TO DB BEFORE POSTING (atomic dedup) ──
        save_budget = min(DB_TIMEOUT, _remaining() - 15)
        if save_budget < 1:
            print("[WARN] No time for DB save — stopping")
            break

        pub_iso = pub_date.isoformat() if pub_date else now.isoformat()

        try:
            saved = await asyncio.wait_for(
                loop.run_in_executor(
                    None, db.save,
                    link, title, title_hash, content_hash,
                    feed_url, pub_iso, source_type, category,
                    trend_score, post_hour, domain_hash,
                ),
                timeout=save_budget,
            )
        except asyncio.TimeoutError:
            print("  [WARN] DB save timed out — skipping")
            stats["errors"] += 1
            continue

        if not saved:
            print(f"  [INFO] DB rejected (409/error) — skip")
            stats["skip_dupe"] += 1
            continue

        # Mark in local sets
        local_posted.add(title_hash)
        known_hashes.add(title_hash)
        known_links.add(link)

        # ── Collect images ──
        image_urls: list[str] = []
        img_budget = min(PAGE_TIMEOUT, _remaining() - 12)
        if img_budget > 2:
            try:
                image_urls = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, _collect_images, entry, link
                    ),
                    timeout=img_budget,
                )
            except asyncio.TimeoutError:
                print("  [WARN] Image collection timed out")
                image_urls = []

        # ── Build caption ──
        caption = _build_caption(
            title=title, desc=desc, link=link,
            brand_name=brand_name, brand_tag=brand_tag,
        )

        # ── Post to Telegram ──
        tg_budget = min(15, _remaining() - 5)
        if tg_budget < 5:
            print("[WARN] No time for Telegram — stopping")
            break

        try:
            success = await asyncio.wait_for(
                _post_to_telegram(
                    bot, config["chat_id"], image_urls, caption
                ),
                timeout=tg_budget,
            )
        except asyncio.TimeoutError:
            print("  [WARN] Telegram post timed out")
            success = False

        if success:
            stats["posted"] += 1
            print(f"  [SUCCESS] Posted #{stats['posted']}: "
                  f"[{brand_short}] {title[:50]}")

            if (_remaining() > 10
                    and stats["posted"] < PUBLISH_BATCH_SIZE):
                await asyncio.sleep(INTER_POST_DELAY)
        else:
            stats["errors"] += 1

    # ════════════════════════════════════════════════
    # Summary
    # ════════════════════════════════════════════════
    elapsed = monotonic() - _t0
    print(f"\n[INFO] ─────────── SUMMARY ({elapsed:.1f}s) ───────────")
    print(f"[INFO] Feeds        : {stats['feeds_ok']} ok / "
          f"{stats['feeds_fail']} fail / {stats['feeds_retry']} retries")
    print(f"[INFO] Entries      : {stats['entries_total']}")
    print(f"[INFO] Skip/time    : {stats['skip_time']}")
    print(f"[INFO] Skip/filter  : {stats['skip_filter']}")
    print(f"[INFO] Skip/dupe    : {stats['skip_dupe']}")
    print(f"[INFO] Posted       : {stats['posted']}")
    print(f"[INFO] Errors       : {stats['errors']}")
    if stats["db_timeout"]:
        print("[WARN] DB timeout occurred")
    print("[INFO] ──────────────────────────────────────")

    return _build_response(stats)


def _build_response(stats: dict) -> dict:
    return {
        "status":  "success",
        "posted":  stats.get("posted", 0),
        "feeds":   stats.get("feeds_ok", 0),
        "checked": stats.get("entries_total", 0),
        "dupes":   stats.get("skip_dupe", 0),
        "errors":  stats.get("errors", 0),
    }


# ═══════════════════════════════════════════════════════════
# SECTION 3 — PARALLEL FEED FETCHER
# ═══════════════════════════════════════════════════════════

async def _fetch_all_parallel(
    loop: asyncio.AbstractEventLoop, stats: dict,
) -> list[dict]:
    tasks = [
        loop.run_in_executor(
            None, _fetch_brand_retry, info, stats
        )
        for info in BRAND_FEEDS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items: list[dict] = []
    for i, result in enumerate(results):
        brand = BRAND_FEEDS[i]["brand"]
        if isinstance(result, Exception):
            print(f"  [ERROR] {brand.split('|')[0].strip()}: {result}")
            stats["feeds_fail"] += 1
        elif result is None:
            stats["feeds_fail"] += 1
        elif result:
            all_items.extend(result)
            stats["feeds_ok"] += 1
        else:
            stats["feeds_ok"] += 1
    return all_items


def _fetch_brand_retry(
    feed_info: dict, stats: dict,
) -> list[dict] | None:
    url        = feed_info["url"]
    brand_name = feed_info["brand"]
    brand_tag  = feed_info["tag"]
    category   = feed_info.get("category", "unknown")
    last_error = None

    for attempt in range(FEED_MAX_RETRIES):
        try:
            resp = requests.get(
                url, timeout=FEED_FETCH_TIMEOUT,
                headers={
                    "User-Agent":
                        "Mozilla/5.0 (compatible; FashionBot/13.0)",
                    "Accept":
                        "application/rss+xml, application/xml, */*",
                },
            )
            if resp.status_code == 404:
                brand_short = brand_name.split("|")[0].strip()
                print(f"  [WARN] {brand_short}: 404")
                return []

            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                if attempt < FEED_MAX_RETRIES - 1:
                    stats["feeds_retry"] += 1
                    sleep(FEED_RETRY_BASE * (2 ** attempt))
                    continue
                return None

            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                brand_short = brand_name.split("|")[0].strip()
                print(f"  [WARN] {brand_short}: Malformed")
                return []

            items = []
            for entry in feed.entries:
                title = _clean(entry.get("title", ""))
                link  = _clean(entry.get("link", ""))
                if not title or not link:
                    continue

                raw_html = (
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                )
                desc     = _truncate(
                    _strip_html(raw_html), MAX_DESC_CHARS
                )
                pub_date = _parse_date(entry)

                items.append({
                    "title":    title,
                    "link":     link,
                    "desc":     desc,
                    "pub_date": pub_date,
                    "brand":    brand_name,
                    "tag":      brand_tag,
                    "feed_url": url,
                    "category": category,
                    "entry":    entry,
                })

            brand_short = brand_name.split("|")[0].strip()
            suffix = f" (retry {attempt})" if attempt > 0 else ""
            print(f"  [FEED] {brand_short}: "
                  f"{len(items)} entries{suffix}")
            return items

        except requests.exceptions.ConnectionError as e:
            last_error = f"Conn: {str(e)[:60]}"
        except requests.exceptions.Timeout:
            last_error = "Timeout"
        except Exception as e:
            last_error = str(e)[:80]
            return None

        if attempt < FEED_MAX_RETRIES - 1:
            stats["feeds_retry"] += 1
            sleep(FEED_RETRY_BASE * (2 ** attempt))

    brand_short = brand_name.split("|")[0].strip()
    print(f"  [ERROR] {brand_short}: Failed: {last_error}")
    return None


# ═══════════════════════════════════════════════════════════
# SECTION 4 — APPWRITE DATABASE CLIENT
# ═══════════════════════════════════════════════════════════

class _AppwriteDB:
    """
    Maps EXACTLY to Appwrite schema:
      fashion_db → history collection

    Columns used:
      link, title, published_at, feed_url, source_type,
      title_hash, content_hash, category, trend_score,
      post_hour, domain_hash
    """

    def __init__(self, endpoint, project, key,
                 database_id, collection_id):
        self._url = (
            f"{endpoint}/databases/{database_id}"
            f"/collections/{collection_id}/documents"
        )
        self._headers = {
            "Content-Type":       "application/json",
            "X-Appwrite-Project": project,
            "X-Appwrite-Key":     key,
        }

    def load_recent(self, limit: int = 500) -> list[dict]:
        """Load recent records for in-memory dedup."""
        try:
            resp = requests.get(
                self._url,
                headers=self._headers,
                params={
                    "limit": str(limit),
                    "orderType": "DESC",
                },
                timeout=DB_TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"[WARN] DB load: HTTP {resp.status_code}")
                return []
            docs = resp.json().get("documents", [])
            return [
                {
                    "link":       d.get("link", ""),
                    "title":      d.get("title", ""),
                    "title_hash": d.get("title_hash", ""),
                }
                for d in docs
            ]
        except requests.exceptions.Timeout:
            raise
        except Exception as e:
            print(f"[ERROR] DB load: {e}")
            return []

    def save(
        self,
        link: str,
        title: str,
        title_hash: str,
        content_hash: str,
        feed_url: str,
        published_at: str,
        source_type: str,
        category: str,
        trend_score: int,
        post_hour: int,
        domain_hash: str,
    ) -> bool:
        """
        Save document with title_hash[:36] as ID.
        409 = already exists (atomic dedup).
        ALL fields match exact Appwrite column names.
        """
        doc_id = title_hash[:36]
        try:
            resp = requests.post(
                self._url,
                headers=self._headers,
                json={
                    "documentId": doc_id,
                    "data": {
                        "link":         link[:1000],
                        "title":        title[:500],
                        "title_hash":   title_hash[:64],
                        "content_hash": content_hash[:64],
                        "feed_url":     feed_url[:500],
                        "published_at": published_at,
                        "source_type":  source_type[:20],
                        "category":     category[:50],
                        "trend_score":  trend_score,
                        "post_hour":    post_hour,
                        "domain_hash":  domain_hash[:64],
                    },
                },
                timeout=DB_TIMEOUT,
            )
            if resp.status_code in (200, 201):
                print("  [DB] Saved.")
                return True
            if resp.status_code == 409:
                print("  [DB] 409 — already exists")
                return False
            print(f"  [WARN] DB save: HTTP {resp.status_code}: "
                  f"{resp.text[:150]}")
            return False
        except Exception as e:
            print(f"  [WARN] DB save: {e}")
            return False


# ═══════════════════════════════════════════════════════════
# SECTION 5 — CONFIG LOADER
# ═══════════════════════════════════════════════════════════

def _load_config() -> dict | None:
    cfg = {
        "token":         os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id":       os.environ.get("TELEGRAM_CHANNEL_ID"),
        "endpoint":      os.environ.get(
            "APPWRITE_ENDPOINT", "https://cloud.appwrite.io/v1"
        ),
        "project":       os.environ.get("APPWRITE_PROJECT_ID"),
        "key":           os.environ.get("APPWRITE_API_KEY"),
        "database_id":   os.environ.get("APPWRITE_DATABASE_ID"),
        "collection_id": os.environ.get(
            "APPWRITE_COLLECTION_ID", "history"
        ),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        print(f"[ERROR] Missing env vars: {missing}")
        return None
    return cfg


# ═══════════════════════════════════════════════════════════
# SECTION 6 — TEXT + HASH UTILITIES
# ═══════════════════════════════════════════════════════════

def _clean(text: str) -> str:
    return (text or "").strip()


def _strip_html(html: str) -> str:
    """Safe HTML stripping with fallback."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "iframe"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())
    except Exception:
        # Fallback: regex strip
        return re.sub(r"<[^>]+>", " ", html).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.8:
        cut = cut[:last_space]
    return cut + "…"


def _normalize_title(title: str) -> str:
    """Normalize for hashing: lowercase, no ZWNJ, no punctuation,
    Persian char normalization, sorted tokens."""
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r"[\u200c\u200d\u200e\u200f\ufeff]", "", t)
    t = t.replace("ي", "ی").replace("ك", "ک")
    t = t.replace("ة", "ه").replace("ؤ", "و")
    t = t.replace("إ", "ا").replace("أ", "ا")
    t = re.sub(r"[^\w\s\u0600-\u06FF]", " ", t)
    tokens = sorted(t.split())
    return " ".join(tokens)


def _make_title_hash(title: str) -> str:
    """
    SHA-256 of sorted normalized title tokens.
    This is the PRIMARY dedup key.
    No description included — it varies across fetches.
    """
    canonical = _normalize_title(title)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _make_content_hash(title: str) -> str:
    """
    SHA-256 of normalized title (unsorted, preserving order).
    Secondary hash for analytics — NOT used for dedup.
    """
    t = title.lower().strip()
    t = re.sub(r"[\u200c\u200d\u200e\u200f\ufeff]", "", t)
    t = t.replace("ي", "ی").replace("ك", "ک")
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _make_domain_hash(feed_url: str) -> str:
    """SHA-256 of feed domain for grouping/analytics."""
    try:
        domain = urlparse(feed_url).netloc.lower()
    except Exception:
        domain = feed_url
    return hashlib.sha256(domain.encode("utf-8")).hexdigest()


def _parse_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


# ═══════════════════════════════════════════════════════════
# SECTION 7 — TREND SCORE CALCULATOR
# ═══════════════════════════════════════════════════════════

def _calc_trend_score(
    title: str, desc: str, brand_name: str,
) -> int:
    """
    Simple trend score based on keyword density.
    Higher = more fashion-relevant.
    Stored in DB for analytics/sorting.
    """
    combined = (title + " " + desc).lower()
    score = 0

    for kw in POSITIVE_KEYWORDS:
        if kw in combined:
            score += 1

    # Brand mention in own content = baseline relevance
    brand_parts = [
        p.strip().lower()
        for p in brand_name.replace("|", " ").split()
        if len(p.strip()) >= 4
    ]
    for part in brand_parts:
        if part in combined:
            score += 2

    # Title keywords worth more
    title_lower = title.lower()
    high_value = ['کلکسیون', 'collection', 'new arrival',
                  'محصول جدید', 'ترند', 'trend', 'lookbook']
    for kw in high_value:
        if kw in title_lower:
            score += 3

    return min(score, 100)  # cap at 100


# ═══════════════════════════════════════════════════════════
# SECTION 8 — FASHION RELEVANCE FILTER
# ═══════════════════════════════════════════════════════════

def _is_fashion(
    title: str, desc: str, feed_url: str, brand_name: str,
) -> bool:
    combined = (title + " " + desc).lower()

    # Hard reject
    for kw in NEGATIVE_KEYWORDS:
        if kw in combined:
            return False

    # Positive keyword
    for kw in POSITIVE_KEYWORDS:
        if kw in combined:
            return True

    # Brand name leniency
    brand_parts = [
        p.strip().lower()
        for p in brand_name.replace("|", " ").split()
        if len(p.strip()) >= 4
    ]
    for part in brand_parts:
        if part in combined:
            return True

    # Domain signal
    try:
        domain = urlparse(feed_url).netloc.replace(
            "www.", ""
        ).lower()
        if domain and domain.split(".")[0] in combined:
            return True
    except Exception:
        pass

    return False


# ═══════════════════════════════════════════════════════════
# SECTION 9 — IMAGE COLLECTION
# ═══════════════════════════════════════════════════════════

def _collect_images(entry, article_url: str) -> list[str]:
    """Blocking — called via run_in_executor."""
    images: list[str] = []
    seen:   set[str]  = set()

    def _add(url: str) -> None:
        url = (url or "").strip()
        if not url or not url.startswith("http") or url in seen:
            return
        lower = url.lower()
        if any(b in lower for b in IMAGE_BLOCKLIST):
            return
        base = lower.split("?")[0]
        has_ext = any(base.endswith(e) for e in IMAGE_EXTENSIONS)
        has_kw = any(
            w in lower for w in
            ["image", "photo", "img", "picture", "media",
             "cdn", "upload", "product", "wp-content"]
        )
        if not has_ext and not has_kw:
            return
        seen.add(url)
        images.append(url)

    # 1. Enclosures
    enclosures = entry.get("enclosures", [])
    if (not enclosures and hasattr(entry, "enclosure")
            and entry.enclosure):
        enclosures = [entry.enclosure]
    for enc in enclosures:
        if isinstance(enc, dict):
            mime = enc.get("type", "")
            href = enc.get("href") or enc.get("url", "")
        else:
            mime = getattr(enc, "type", "")
            href = (getattr(enc, "href", "")
                    or getattr(enc, "url", ""))
        if mime.startswith("image/") and href:
            _add(href)

    # 2. media:content
    for m in entry.get("media_content", []):
        u = (m.get("url", "") if isinstance(m, dict)
             else getattr(m, "url", ""))
        med = (m.get("medium", "") if isinstance(m, dict)
               else getattr(m, "medium", ""))
        if (med == "image"
                or any(u.lower().endswith(e)
                       for e in IMAGE_EXTENSIONS)):
            _add(u)

    # 3. media:thumbnail
    for t in entry.get("media_thumbnail", []):
        u = (t.get("url", "") if isinstance(t, dict)
             else getattr(t, "url", ""))
        _add(u)

    # 4. <img> in description
    if len(images) < MAX_IMAGES:
        raw = (
            entry.get("summary")
            or entry.get("description")
            or (entry.get("content") or [{}])[0].get("value", "")
        )
        if raw:
            try:
                soup = BeautifulSoup(raw, "lxml")
                for img in soup.find_all("img"):
                    for attr in ("src", "data-src",
                                 "data-lazy-src", "data-original"):
                        s = img.get(attr, "")
                        if s and s.startswith("http"):
                            _add(s)
                            break
                    if len(images) >= MAX_IMAGES:
                        break
            except Exception:
                pass

    # 5. og:image fallback
    if not images:
        og = _fetch_og_image(article_url)
        if og:
            _add(og)

    result = images[:MAX_IMAGES]
    print(f"  [INFO] Images: {len(result)}")
    return result


def _fetch_og_image(url: str) -> str | None:
    try:
        resp = requests.get(
            url, timeout=PAGE_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        for prop in ("og:image", "twitter:image"):
            tag = (
                soup.find("meta", property=prop)
                or soup.find("meta", attrs={"name": prop})
            )
            if tag:
                c = tag.get("content", "").strip()
                if c.startswith("http"):
                    return c
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# SECTION 10 — CAPTION BUILDER
# ═══════════════════════════════════════════════════════════

def _build_caption(
    title: str, desc: str, link: str,
    brand_name: str, brand_tag: str,
) -> str:
    safe_brand = _escape_html(brand_name.strip())
    safe_title = _escape_html(title.strip())
    safe_desc  = _escape_html(desc.strip())
    hashtag_line = f"{brand_tag} {FIXED_HASHTAGS}"

    parts = [
        f"🏷️ {safe_brand}",
        f"💠 <b>{safe_title}</b>",
        "─────────────",
        safe_desc,
        f'🔗 <a href="{link}">ادامه مطلب</a> | '
        f'🆔 @irfashionnews',
        hashtag_line,
    ]

    caption = "\n\n".join(parts)

    if len(caption) > CAPTION_MAX:
        overflow  = len(caption) - CAPTION_MAX
        safe_desc = safe_desc[
            :max(0, len(safe_desc) - overflow - 5)
        ] + "…"
        parts[3] = safe_desc
        caption  = "\n\n".join(parts)

    return caption


# ═══════════════════════════════════════════════════════════
# SECTION 11 — TELEGRAM POSTING
# ═══════════════════════════════════════════════════════════

async def _post_to_telegram(
    bot: Bot, chat_id: str,
    image_urls: list[str], caption: str,
) -> bool:
    anchor_msg_id: int | None = None

    # ── Images (no caption) ──
    if len(image_urls) >= 2:
        try:
            media = [
                InputMediaPhoto(media=url)
                for url in image_urls[:MAX_IMAGES]
            ]
            sent = await bot.send_media_group(
                chat_id=chat_id, media=media,
                disable_notification=True,
            )
            anchor_msg_id = sent[-1].message_id
            print(f"  [INFO] ① Album: {len(sent)} imgs "
                  f"anchor={anchor_msg_id}")
        except TelegramError as e:
            print(f"  [WARN] ① Album failed: {e}")
            if image_urls:
                try:
                    s = await bot.send_photo(
                        chat_id=chat_id, photo=image_urls[0],
                        disable_notification=True,
                    )
                    anchor_msg_id = s.message_id
                except TelegramError as e2:
                    print(f"  [WARN] ① Fallback photo: {e2}")

    elif len(image_urls) == 1:
        try:
            s = await bot.send_photo(
                chat_id=chat_id, photo=image_urls[0],
                disable_notification=True,
            )
            anchor_msg_id = s.message_id
            print(f"  [INFO] ① Photo anchor={anchor_msg_id}")
        except TelegramError as e:
            print(f"  [WARN] ① Photo failed: {e}")

    else:
        print("  [INFO] ① No images — standalone caption")

    # ── Delay ──
    if anchor_msg_id is not None:
        await asyncio.sleep(ALBUM_CAPTION_DELAY)

    # ── Caption (reply to anchor) ──
    try:
        kwargs = {
            "chat_id":              chat_id,
            "text":                 caption,
            "parse_mode":           "HTML",
            "link_preview_options": LinkPreviewOptions(
                is_disabled=True
            ),
            "disable_notification": True,
        }
        if anchor_msg_id is not None:
            kwargs["reply_to_message_id"] = anchor_msg_id

        await bot.send_message(**kwargs)
        label = (f"reply_to={anchor_msg_id}"
                 if anchor_msg_id else "standalone")
        print(f"  [INFO] ③ Caption sent ({label})")
    except TelegramError as e:
        print(f"  [ERROR] ③ Caption failed: {e}")
        return False

    # ── Sticker (non-fatal) ──
    if FASHION_STICKERS:
        await asyncio.sleep(STICKER_DELAY)
        try:
            await bot.send_sticker(
                chat_id=chat_id,
                sticker=random.choice(FASHION_STICKERS),
                disable_notification=True,
            )
            print("  [INFO] ⑤ Sticker sent")
        except TelegramError as e:
            print(f"  [WARN] ⑤ Sticker (non-fatal): {e}")

    return True


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(main())
