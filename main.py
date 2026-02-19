# ============================================================
# Telegram Fashion News Bot — @irfashionnews
# Version:    11.0 — Iranian Fashion Brands Focus
# Runtime:    Python 3.12 / Appwrite Cloud Functions
# Timeout:    120 seconds
#
# POST FLOW (guaranteed order):
#   ① Fetch RSS feeds from Iranian fashion brand sources
#   ② Filter by fashion relevance + time (weekly window)
#   ③ Check Appwrite DB — strict duplicate check (link + hash)
#   ④ Extract 1–5 images per post
#   ⑤ send_media_group(all images, NO caption)
#      → anchor_id = last_sent_message.message_id
#   ⑥ asyncio.sleep(2.5s)
#   ⑦ send_message(caption, reply_to=anchor_id)
#      → reply dependency = protocol-level order guarantee
#   ⑧ asyncio.sleep(1.5s)
#   ⑨ send_sticker(random) [non-fatal]
#   ⑩ Save record to Appwrite DB
#
# CAPTION FORMAT (HTML, magazine style):
#   🏷️ Brand Name
#   💠 Product / Post Title
#   ─────────────
#   Key details (≤ 350 chars)
#
#   🔗 ادامه مطلب | 🆔 @irfashionnews
#
#   #BrandName #مد #استایل #ترند #فشن_ایرانی #برند_ایرانی
# ============================================================

import os
import asyncio
import hashlib
import random
import requests
import feedparser

from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from telegram import Bot, InputMediaPhoto, LinkPreviewOptions
from telegram.error import TelegramError


# ═══════════════════════════════════════════════════════════
# SECTION 1 — IRANIAN FASHION BRAND RSS FEEDS
#
# Each entry is a dict with:
#   url   → RSS/Atom feed URL
#   brand → Brand display name (Persian + English)
#   tag   → Hashtag string for this brand
#
# How to find a brand's RSS feed:
#   1. Visit brand website
#   2. Try appending /feed, /rss, /feed.xml, /atom.xml
#   3. Check <link rel="alternate" type="application/rss+xml">
#   4. For WooCommerce shops: /?feed=rss2 or /feed/
#   5. For WordPress blogs: /feed/ always works
#
# Feeds marked [NEEDS_VERIFICATION] require manual check —
# the URL pattern is standard for their platform but may
# need adjustment if the brand uses a custom setup.
# ═══════════════════════════════════════════════════════════

BRAND_FEEDS: list[dict] = [

    # ── La Femme Roje ──
    {
        "url":   "https://lafemmeroje.com/feed/",
        "brand": "La Femme Roje | لا فم روژ",
        "tag":   "#LaFemmeRoje #لافم_روژ",
    },

    # ── Salian ──
    {
        "url":   "https://salian.ir/feed/",
        "brand": "Salian | سالیان",
        "tag":   "#Salian #سالیان",
    },

    # ── Celebon ──
    {
        "url":   "https://celebon.com/feed/",
        "brand": "Celebon | سلبون",
        "tag":   "#Celebon #سلبون",
    },

    # ── Siawood ──
    {
        "url":   "https://siawood.com/feed/",
        "brand": "Siawood | سیاوود",
        "tag":   "#Siawood #سیاوود",
    },

    # ── Naghmeh Kiumarsi ──
    {
        "url":   "https://naghmehkiumarsi.com/feed/",
        "brand": "Naghmeh Kiumarsi | نغمه کیومرثی",
        "tag":   "#NaghmehKiumarsi #نغمه_کیومرثی",
    },

    # ── Poosh ──
    {
        "url":   "https://pooshmode.com/feed/",
        "brand": "Poosh | پوش",
        "tag":   "#Poosh #پوش_مد",
    },

    # ── Kimia ──
    {
        "url":   "https://kimiamode.com/feed/",
        "brand": "Kimia | کیمیا",
        "tag":   "#Kimia #کیمیا_مد",
    },

    # ── Mihano Momosa ──
    {
        "url":   "https://mihanomomosa.com/feed/",
        "brand": "Mihano Momosa | میهانو موموسا",
        "tag":   "#MihanoMomosa #میهانو_موموسا",
    },

    # ── Taghcheh ──
    {
        "url":   "https://taghcheh.com/feed/",
        "brand": "Taghcheh | طاقچه",
        "tag":   "#Taghcheh #طاقچه",
    },

    # ── Parmi Manto ──
    {
        "url":   "https://parmimanto.com/feed/",
        "brand": "Parmi Manto | پارمی مانتو",
        "tag":   "#ParmiManto #پارمی_مانتو",
    },

    # ── Banoo Sara ──
    {
        "url":   "https://banoosara.com/feed/",
        "brand": "Banoo Sara | بانو سارا",
        "tag":   "#BanooSara #بانو_سارا",
    },

    # ── Roshanak ──
    {
        "url":   "https://roshanakmode.com/feed/",
        "brand": "Roshanak | رشنک",
        "tag":   "#Roshanak #رشنک",
    },

    # ── Bodyspinner ──
    {
        "url":   "https://bodyspinner.com/feed/",
        "brand": "Bodyspinner | بادی اسپینر",
        "tag":   "#Bodyspinner #بادی_اسپینر",
    },

    # ── Garoudi ──
    {
        "url":   "https://garoudi.com/feed/",
        "brand": "Garoudi | گارودی",
        "tag":   "#Garoudi #گارودی",
    },

    # ── Hacoupian ──
    {
        "url":   "https://hacoupian.com/feed/",
        "brand": "Hacoupian | هاکوپیان",
        "tag":   "#Hacoupian #هاکوپیان",
    },

    # ── Holiday ──
    {
        "url":   "https://holidayfashion.ir/feed/",
        "brand": "Holiday | هالیدی",
        "tag":   "#Holiday #هالیدی",
    },

    # ── LC Man ──
    {
        "url":   "https://lcman.ir/feed/",
        "brand": "LC Man | ال سی من",
        "tag":   "#LCMan #ال_سی_من",
    },

    # ── Narbon ──
    {
        "url":   "https://narbon.ir/feed/",
        "brand": "Narbon | ناربن",
        "tag":   "#Narbon #ناربن",
    },

    # ── Narian ──
    {
        "url":   "https://narian.ir/feed/",
        "brand": "Narian | ناریان",
        "tag":   "#Narian #ناریان",
    },

    # ── Patan Jameh ──
    {
        "url":   "https://patanjameh.com/feed/",
        "brand": "Patan Jameh | پاتان جامه",
        "tag":   "#PatanJameh #پاتان_جامه",
    },

    # ── General Persian fashion aggregators (fallback) ──
    {
        "url":   "https://medopia.ir/feed/",
        "brand": "Medopia | مدوپیا",
        "tag":   "#Medopia #مدوپیا",
    },
    {
        "url":   "https://www.digistyle.com/mag/feed/",
        "brand": "Digistyle | دیجی‌استایل",
        "tag":   "#Digistyle #دیجی_استایل",
    },
    {
        "url":   "https://www.chibepoosham.com/feed/",
        "brand": "Chi Be Poosham | چی بپوشم",
        "tag":   "#ChibePooosham #چی_بپوشم",
    },
]

# ── Fashion relevance: must match at least ONE ──
POSITIVE_KEYWORDS = [
    # Persian
    'مد', 'فشن', 'استایل', 'زیبایی', 'لباس', 'پوشاک',
    'طراحی لباس', 'ترند', 'کلکسیون', 'برند', 'سیزن',
    'آرایش', 'مانتو', 'پیراهن', 'کت', 'شلوار', 'کیف',
    'کفش', 'اکسسوری', 'جواهر', 'طلا', 'عطر', 'نگین',
    'پالتو', 'ست لباس', 'مزون', 'خیاطی', 'بافت', 'تونیک',
    'بلوز', 'دامن', 'شنل', 'کاپشن', 'جوراب', 'روسری',
    'پارچه', 'طرح', 'دوخت', 'برند ایرانی', 'محصول جدید',
    # English
    'fashion', 'style', 'beauty', 'clothing', 'trend',
    'outfit', 'couture', 'collection', 'lookbook', 'brand',
    'wardrobe', 'luxury', 'designer', 'new arrival', 'product',
    'coat', 'dress', 'blouse', 'skirt', 'jacket', 'accessory',
]

# ── Hard reject: ANY match = skip ──
NEGATIVE_KEYWORDS = [
    'فیلم', 'سینما', 'سریال', 'بازیگر', 'کارگردان', 'اسکار',
    'صبحانه', 'رژیم غذایی', 'طرز تهیه', 'دستور پخت', 'آشپزی',
    'اپل', 'گوگل', 'آیفون', 'سامسونگ', 'تکنولوژی', 'گیم',
    'فوتبال', 'والیبال', 'ورزش', 'تیم ملی', 'لیگ',
    'بورس', 'ارز', 'دلار', 'سکه', 'بیت کوین', 'اقتصاد',
    'انتخابات', 'سیاسی', 'مجلس', 'دولت', 'وزیر',
    'زلزله', 'سیل', 'آتش سوزی', 'تصادف', 'حادثه', 'کشته',
]

# ── Fixed hashtag block (always last line of caption) ──
FIXED_HASHTAGS = (
    "#مد #استایل #ترند #برند_ایرانی #فشن_ایرانی "
    "#fashion #IranianFashion #style"
)

# ── Limits ──
MAX_DESCRIPTION_CHARS = 350
MAX_IMAGES            = 5
CAPTION_MAX           = 1020

# ── Timeouts (seconds) ──
FEED_TIMEOUT        = 10
PAGE_TIMEOUT        = 8
DB_TIMEOUT          = 6

# ── Weekly scan window (168 hours = 7 days) ──
HOURS_THRESHOLD     = 168

# ── Posting delays ──
ALBUM_CAPTION_DELAY = 2.5
STICKER_DELAY       = 1.5

# ── Image filtering ──
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
IMAGE_BLOCKLIST  = [
    'doubleclick', 'googletagmanager', 'googlesyndication',
    'facebook.com/tr', 'analytics', 'pixel', 'beacon',
    'tracking', 'counter', 'stat.', 'stats.',
]

# ── Fashion stickers ──
# Replace with real file_ids. Instructions:
#   1. Send any fashion sticker to your bot
#   2. GET https://api.telegram.org/bot<TOKEN>/getUpdates
#   3. Copy result[0].message.sticker.file_id
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
    print("[INFO] ══════════════════════════════════════")
    print("[INFO] Iranian Fashion Brand Bot v11.0 started")
    print(f"[INFO] {datetime.now(timezone.utc).isoformat()}")
    print(f"[INFO] Scanning {len(BRAND_FEEDS)} brand feeds")
    print(f"[INFO] Weekly window: {HOURS_THRESHOLD}h")
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

    stats = {
        "feeds_ok":  0,
        "checked":   0,
        "skip_time": 0,
        "skip_filt": 0,
        "skip_dupe": 0,
        "posted":    False,
    }

    for feed_info in BRAND_FEEDS:
        if stats["posted"]:
            break

        feed_url    = feed_info["url"]
        brand_name  = feed_info["brand"]
        brand_tag   = feed_info["tag"]

        print(f"\n[FEED] {brand_name}")
        print(f"       {feed_url}")

        entries = _fetch_feed(feed_url)
        if not entries:
            continue

        stats["feeds_ok"] += 1

        for entry in entries:
            if stats["posted"]:
                break

            stats["checked"] += 1

            # ── Parse basic fields ──
            title = _clean(entry.get("title", ""))
            link  = _clean(entry.get("link",  ""))
            if not title or not link:
                continue

            # ── Time filter (weekly window) ──
            pub_date = _parse_date(entry)
            if pub_date and pub_date < time_threshold:
                stats["skip_time"] += 1
                continue

            # ── Description ──
            raw_html = (
                entry.get("summary")
                or entry.get("description")
                or ""
            )
            desc = _truncate(
                _strip_html(raw_html),
                MAX_DESCRIPTION_CHARS,
            )

            # ── Fashion relevance filter ──
            # For brand-dedicated feeds we are lenient:
            # brand name in title or feed URL counts as positive signal.
            if not _is_fashion(title, desc, feed_url, brand_name):
                stats["skip_filt"] += 1
                print(f"  [SKIP:filter] {title[:60]}")
                continue

            # ── Strict duplicate check ──
            content_hash = _make_hash(title, desc)
            if db.is_duplicate(link, content_hash):
                stats["skip_dupe"] += 1
                print(f"  [SKIP:dupe]   {title[:60]}")
                continue

            print(f"  [CANDIDATE] {title[:60]}")

            # ── Collect images ──
            image_urls = _collect_images(entry, link)

            # ── Build caption ──
            caption = _build_caption(
                title      = title,
                desc       = desc,
                link       = link,
                brand_name = brand_name,
                brand_tag  = brand_tag,
            )

            # ── Post to Telegram ──
            success = await _post_to_telegram(
                bot        = bot,
                chat_id    = config["chat_id"],
                image_urls = image_urls,
                caption    = caption,
            )

            if success:
                stats["posted"] = True
                print(f"  [SUCCESS] Posted: {title[:60]}")
                db.save(
                    link         = link,
                    title        = title,
                    content_hash = content_hash,
                    brand        = brand_name,
                    created_at   = now.isoformat(),
                )

    # ── Summary ──
    print("\n[INFO] ─────────── SUMMARY ───────────")
    print(f"[INFO] Feeds alive : {stats['feeds_ok']} / {len(BRAND_FEEDS)}")
    print(f"[INFO] Checked     : {stats['checked']}")
    print(f"[INFO] Skip/time   : {stats['skip_time']}")
    print(f"[INFO] Skip/filter : {stats['skip_filt']}")
    print(f"[INFO] Skip/dupe   : {stats['skip_dupe']}")
    print(f"[INFO] Posted      : {stats['posted']}")
    print("[INFO] ──────────────────────────────")

    return {"status": "success", "posted": stats["posted"]}


# ═══════════════════════════════════════════════════════════
# SECTION 3 — CONFIG LOADER
# ═══════════════════════════════════════════════════════════

def _load_config() -> dict | None:
    cfg = {
        "token":         os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id":       os.environ.get("TELEGRAM_CHANNEL_ID"),
        "endpoint":      os.environ.get("APPWRITE_ENDPOINT",
                                        "https://cloud.appwrite.io/v1"),
        "project":       os.environ.get("APPWRITE_PROJECT_ID"),
        "key":           os.environ.get("APPWRITE_API_KEY"),
        "database_id":   os.environ.get("APPWRITE_DATABASE_ID"),
        "collection_id": os.environ.get("APPWRITE_COLLECTION_ID", "history"),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        print(f"[ERROR] Missing env vars: {missing}")
        return None
    return cfg


# ═══════════════════════════════════════════════════════════
# SECTION 4 — APPWRITE DATABASE CLIENT
#
# Raw requests — no SDK dependency.
# Same database + collection as the international bot.
# Checks: link (exact URL) + content_hash (SHA256).
# Saves: link, title, content_hash, brand, created_at.
# ═══════════════════════════════════════════════════════════

class _AppwriteDB:

    def __init__(self, endpoint, project, key, database_id, collection_id):
        self._url = (
            f"{endpoint}/databases/{database_id}"
            f"/collections/{collection_id}/documents"
        )
        self._headers = {
            "Content-Type":       "application/json",
            "X-Appwrite-Project": project,
            "X-Appwrite-Key":     key,
        }

    def is_duplicate(self, link: str, content_hash: str) -> bool:
        """
        Strict check — True if EITHER link OR hash already in DB.
        On DB error returns False (do not block posting).
        """
        return (
            self._exists("link",         link[:500])
            or self._exists("content_hash", content_hash)
        )

    def save(self, link: str, title: str, content_hash: str,
             brand: str, created_at: str) -> bool:
        """Persist a new post record after successful delivery."""
        doc_id = hashlib.md5(link.encode()).hexdigest()[:20]
        try:
            resp = requests.post(
                self._url,
                headers=self._headers,
                json={
                    "documentId": doc_id,
                    "data": {
                        "link":         link[:500],
                        "title":        title[:300],
                        "content_hash": content_hash,
                        "brand":        brand[:100],
                        "created_at":   created_at,
                    },
                },
                timeout=DB_TIMEOUT,
            )
            ok = resp.status_code in (200, 201)
            print(
                "[DB] Saved." if ok
                else f"[WARN] DB save {resp.status_code}: {resp.text[:100]}"
            )
            return ok
        except requests.RequestException as e:
            print(f"[WARN] DB save error: {e}")
            return False

    def _exists(self, field: str, value: str) -> bool:
        try:
            resp = requests.get(
                self._url,
                headers=self._headers,
                params={
                    "queries[]": f'equal("{field}", ["{value}"])',
                    "limit":     1,
                },
                timeout=DB_TIMEOUT,
            )
            if resp.status_code == 200:
                found = resp.json().get("total", 0) > 0
                if found:
                    print(f"  [DB] Duplicate by {field}.")
                return found
            print(f"[WARN] DB query {resp.status_code} ({field})")
            return False
        except requests.RequestException as e:
            print(f"[WARN] DB query error ({field}): {e}")
            return False


# ═══════════════════════════════════════════════════════════
# SECTION 5 — RSS FEED FETCHER
# ═══════════════════════════════════════════════════════════

def _fetch_feed(url: str) -> list:
    """
    Fetch RSS via requests (timeout-safe), parse with feedparser.
    Returns list of entries, or [] on any failure.
    """
    try:
        resp = requests.get(
            url,
            timeout=FEED_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; IranFashionBot/1.0)",
                "Accept":     "application/rss+xml, application/xml, */*",
            },
        )
        if resp.status_code != 200:
            print(f"  [WARN] HTTP {resp.status_code}")
            return []

        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            print(f"  [WARN] Malformed feed")
            return []

        print(f"  [INFO] {len(feed.entries)} entries found.")
        return feed.entries

    except requests.RequestException as e:
        print(f"  [ERROR] Feed fetch: {e}")
        return []
    except Exception as e:
        print(f"  [ERROR] Feed parse: {e}")
        return []


# ═══════════════════════════════════════════════════════════
# SECTION 6 — TEXT UTILITIES
# ═══════════════════════════════════════════════════════════

def _clean(text: str) -> str:
    return (text or "").strip()


def _strip_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "iframe"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut        = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.8:
        cut = cut[:last_space]
    return cut + "…"


def _make_hash(title: str, desc: str) -> str:
    """SHA256 of normalized title + first 150 chars of description."""
    raw = f"{title.lower().strip()} {desc[:150].lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
# SECTION 7 — FASHION RELEVANCE FILTER
#
# For brand-dedicated feeds we apply extra leniency:
# if the brand name or feed domain appears in the text,
# that counts as a positive signal even without explicit
# fashion keywords (product names rarely contain them).
# ═══════════════════════════════════════════════════════════

def _is_fashion(
    title: str,
    desc: str,
    feed_url: str,
    brand_name: str,
) -> bool:
    """
    Stage 1: Hard reject if ANY negative keyword found.
    Stage 2: Accept if:
      a) At least one POSITIVE keyword found, OR
      b) Brand name appears in title/desc (brand feed leniency), OR
      c) Feed URL domain matches a known brand domain.
    """
    combined = (title + " " + desc).lower()

    # Stage 1 — hard reject
    for kw in NEGATIVE_KEYWORDS:
        if kw in combined:
            return False

    # Stage 2a — positive keyword
    for kw in POSITIVE_KEYWORDS:
        if kw in combined:
            return True

    # Stage 2b — brand name signal (leniency for brand feeds)
    brand_lower = brand_name.lower()
    brand_parts = [
        p.strip()
        for p in brand_lower.replace("|", " ").split()
        if len(p.strip()) >= 4
    ]
    for part in brand_parts:
        if part in combined:
            return True

    # Stage 2c — domain signal
    try:
        from urllib.parse import urlparse
        domain = urlparse(feed_url).netloc.replace("www.", "").lower()
        if domain and domain.split(".")[0] in combined:
            return True
    except Exception:
        pass

    return False


# ═══════════════════════════════════════════════════════════
# SECTION 8 — IMAGE COLLECTION
#
# Collects up to MAX_IMAGES valid image URLs per entry.
# Priority:
#   1. RSS <enclosure type="image/*">
#   2. RSS <media:content>
#   3. RSS <media:thumbnail>
#   4. <img> tags inside RSS description HTML
#   5. og:image / twitter:image from article page (fallback)
# ═══════════════════════════════════════════════════════════

def _collect_images(entry, article_url: str) -> list[str]:
    images: list[str] = []
    seen:   set[str]  = set()

    def _add(url: str) -> None:
        url = (url or "").strip()
        if not url or not url.startswith("http") or url in seen:
            return
        lower = url.lower()
        if any(b in lower for b in IMAGE_BLOCKLIST):
            return
        base     = lower.split("?")[0]
        has_ext  = any(base.endswith(e) for e in IMAGE_EXTENSIONS)
        has_word = any(
            w in lower
            for w in ["image", "photo", "img", "picture", "media", "cdn",
                      "upload", "product", "wp-content"]
        )
        if not has_ext and not has_word:
            return
        seen.add(url)
        images.append(url)

    # 1. Enclosures
    enclosures = entry.get("enclosures", [])
    if not enclosures and hasattr(entry, "enclosure") and entry.enclosure:
        enclosures = [entry.enclosure]
    for enc in enclosures:
        if isinstance(enc, dict):
            mime = enc.get("type", "")
            href = enc.get("href") or enc.get("url", "")
        else:
            mime = getattr(enc, "type", "")
            href = getattr(enc, "href", "") or getattr(enc, "url", "")
        if mime.startswith("image/") and href:
            _add(href)

    # 2. media:content
    for m in entry.get("media_content", []):
        url    = m.get("url", "")    if isinstance(m, dict) else getattr(m, "url", "")
        medium = m.get("medium", "") if isinstance(m, dict) else getattr(m, "medium", "")
        if medium == "image" or any(url.lower().endswith(e) for e in IMAGE_EXTENSIONS):
            _add(url)

    # 3. media:thumbnail
    for t in entry.get("media_thumbnail", []):
        url = t.get("url", "") if isinstance(t, dict) else getattr(t, "url", "")
        _add(url)

    # 4. <img> in description HTML
    if len(images) < MAX_IMAGES:
        raw_html = (
            entry.get("summary")
            or entry.get("description")
            or (entry.get("content") or [{}])[0].get("value", "")
        )
        if raw_html:
            soup = BeautifulSoup(raw_html, "lxml")
            for img_tag in soup.find_all("img"):
                for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                    src = img_tag.get(attr, "")
                    if src and src.startswith("http"):
                        _add(src)
                        break
                if len(images) >= MAX_IMAGES:
                    break

    # 5. og:image page fallback
    if not images:
        og = _fetch_og_image(article_url)
        if og:
            _add(og)

    result = images[:MAX_IMAGES]
    print(f"  [INFO] Images: {len(result)}")
    return result


def _fetch_og_image(url: str) -> str | None:
    """Fetch article page and extract og:image or twitter:image."""
    try:
        resp = requests.get(
            url,
            timeout=PAGE_TIMEOUT,
            headers={"User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            )},
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
                content = tag.get("content", "").strip()
                if content.startswith("http"):
                    return content
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# SECTION 9 — CAPTION BUILDER
#
# Structure (top → bottom):
#
#   🏷️ Brand Name
#   💠 <b>Product Title</b>
#   ─────────────
#   Description (≤ 350 chars)
#
#   🔗 <a href="link">ادامه مطلب</a> | 🆔 @irfashionnews
#
#   #BrandTag #مد #استایل #ترند #برند_ایرانی #فشن_ایرانی
#   ← always last line
# ═══════════════════════════════════════════════════════════

def _build_caption(
    title:      str,
    desc:       str,
    link:       str,
    brand_name: str,
    brand_tag:  str,
) -> str:
    safe_brand = _escape_html(brand_name.strip())
    safe_title = _escape_html(title.strip())
    safe_desc  = _escape_html(desc.strip())

    # Brand-specific hashtags come first, then fixed block
    hashtag_line = f"{brand_tag} {FIXED_HASHTAGS}"

    parts = [
        f"🏷️ {safe_brand}",
        f"💠 <b>{safe_title}</b>",
        "─────────────",
        safe_desc,
        f'🔗 <a href="{link}">ادامه مطلب</a> | 🆔 @irfashionnews',
        hashtag_line,    # always last
    ]

    caption = "\n\n".join(parts)

    # Trim description if over Telegram limit
    if len(caption) > CAPTION_MAX:
        overflow  = len(caption) - CAPTION_MAX
        safe_desc = safe_desc[:max(0, len(safe_desc) - overflow - 5)] + "…"
        parts[3]  = safe_desc
        caption   = "\n\n".join(parts)

    return caption


# ═══════════════════════════════════════════════════════════
# SECTION 10 — TELEGRAM POSTING
#
# ORDER GUARANTEE via reply_to_message_id:
#
#   ① send_media_group(all images, NO caption)
#      → anchor_id = last_sent_message.message_id
#   ② asyncio.sleep(ALBUM_CAPTION_DELAY = 2.5s)
#   ③ send_message(caption, reply_to=anchor_id)
#      → A Telegram reply cannot be delivered before its parent.
#        Order is enforced at protocol level, not by timing alone.
#   ④ asyncio.sleep(STICKER_DELAY = 1.5s)
#   ⑤ send_sticker(random) [non-fatal]
#
# EDGE CASES:
#   ≥2 images → send_media_group → anchor → reply caption
#    1 image  → send_photo (no caption) → anchor → reply caption
#    0 images → skip image step → standalone caption
#
# FALLBACK CHAIN:
#   send_media_group fails → try send_photo(images[0])
#   send_photo fails       → proceed without anchor
#   send_message fails     → return False (post not counted)
#   send_sticker fails     → log warn, return True anyway
# ═══════════════════════════════════════════════════════════

async def _post_to_telegram(
    bot:        Bot,
    chat_id:    str,
    image_urls: list[str],
    caption:    str,
) -> bool:
    """
    Full post sequence.
    Returns True only if the caption message was delivered.
    """
    anchor_msg_id: int | None = None

    # ─────────────────────────────────────────
    # STEP ①  Send images (no caption)
    # ─────────────────────────────────────────
    if len(image_urls) >= 2:
        try:
            media_group = [
                InputMediaPhoto(media=url)
                for url in image_urls[:MAX_IMAGES]
            ]
            sent_list = await bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
                disable_notification=True,
            )
            anchor_msg_id = sent_list[-1].message_id
            print(
                f"  [INFO] ① Album: {len(sent_list)} images. "
                f"anchor={anchor_msg_id}"
            )
        except TelegramError as e:
            print(f"  [WARN] ① Album failed: {e}")
            if image_urls:
                try:
                    sent = await bot.send_photo(
                        chat_id=chat_id,
                        photo=image_urls[0],
                        disable_notification=True,
                    )
                    anchor_msg_id = sent.message_id
                    print(
                        f"  [INFO] ① Fallback photo. "
                        f"anchor={anchor_msg_id}"
                    )
                except TelegramError as e2:
                    print(f"  [WARN] ① Fallback photo failed: {e2}")

    elif len(image_urls) == 1:
        try:
            sent = await bot.send_photo(
                chat_id=chat_id,
                photo=image_urls[0],
                disable_notification=True,
            )
            anchor_msg_id = sent.message_id
            print(f"  [INFO] ① Single photo. anchor={anchor_msg_id}")
        except TelegramError as e:
            print(f"  [WARN] ① Single photo failed: {e}")

    else:
        print("  [INFO] ① No images — caption will be standalone.")

    # ─────────────────────────────────────────
    # STEP ②  Hard delay
    # ─────────────────────────────────────────
    if anchor_msg_id is not None:
        print(f"  [INFO] ② Waiting {ALBUM_CAPTION_DELAY}s…")
        await asyncio.sleep(ALBUM_CAPTION_DELAY)

    # ─────────────────────────────────────────
    # STEP ③  Send caption (reply to anchor)
    # ─────────────────────────────────────────
    try:
        kwargs: dict = {
            "chat_id":              chat_id,
            "text":                 caption,
            "parse_mode":           "HTML",
            "link_preview_options": LinkPreviewOptions(is_disabled=True),
            "disable_notification": True,
        }
        if anchor_msg_id is not None:
            kwargs["reply_to_message_id"] = anchor_msg_id

        await bot.send_message(**kwargs)

        label = (
            f"reply_to={anchor_msg_id}"
            if anchor_msg_id is not None else "standalone"
        )
        print(f"  [INFO] ③ Caption sent ({label}).")

    except TelegramError as e:
        print(f"  [ERROR] ③ Caption failed: {e}")
        return False

    # ─────────────────────────────────────────
    # STEPS ④⑤  Sticker (non-fatal)
    # ─────────────────────────────────────────
    if FASHION_STICKERS:
        await asyncio.sleep(STICKER_DELAY)
        try:
            await bot.send_sticker(
                chat_id=chat_id,
                sticker=random.choice(FASHION_STICKERS),
                disable_notification=True,
            )
            print("  [INFO] ⑤ Sticker sent.")
        except TelegramError as e:
            print(f"  [WARN] ⑤ Sticker failed (non-fatal): {e}")

    return True


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(main())
