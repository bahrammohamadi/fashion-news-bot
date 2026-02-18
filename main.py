import os
import asyncio
import feedparser
import requests
import hashlib
import json
from datetime import datetime, timedelta, timezone
from telegram import Bot, LinkPreviewOptions
from telegram.error import TelegramError
from bs4 import BeautifulSoup


# ─────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────

RSS_FEEDS = [
    # ✅ Dedicated fashion/style sources (highest priority)
    "https://medopia.ir/feed/",
    "https://www.digistyle.com/mag/feed/",
    "https://www.chibepoosham.com/feed/",
    "https://www.tarahanelebas.com/feed/",
    "https://www.persianpood.com/feed/",
    "https://www.zibamoon.com/feed/",
    "https://www.elsana.com/feed/",
    "https://www.beytoote.com/rss/fashion",
    "https://www.namnak.com/rss/fashion",
    "https://www.roozaneh.net/rss/fashion",
    "https://www.bartarinha.ir/rss/fashion",
    # ✅ General news - fashion category only
    "https://www.zoomit.ir/feed/category/fashion-beauty/",
    "https://fararu.com/rss/category/مد-زیبایی",
    "https://www.digikala.com/mag/feed/?category=مد-و-زیبایی",
]

# Keywords that MUST appear for the post to be published
POSITIVE_KEYWORDS = [
    'مد', 'فشن', 'استایل', 'زیبایی', 'لباس', 'پوشاک',
    'طراحی لباس', 'ترند', 'کلکسیون', 'برند', 'سیزن',
    'fashion', 'style', 'beauty', 'clothing', 'trend',
    'outfit', 'couture', 'runway', 'lookbook', 'textile',
    'آرایش', 'مانتو', 'پیراهن', 'کت', 'شلوار', 'کیف',
    'کفش', 'اکسسوری', 'جواهر', 'طلا', 'عطر', 'نگین',
]

# Keywords that immediately REJECT the post
NEGATIVE_KEYWORDS = [
    'فیلم', 'سینما', 'سریال', 'بازی', 'گیم', 'تریلر',
    'نقد فیلم', 'بازیگر', 'کارگردان', 'اسکار',
    'صبحانه', 'رژیم غذایی', 'طرز تهیه', 'دستور پخت',
    'اپل', 'گوگل', 'پیکسل', 'آیفون', 'سامسونگ',
    'فوتبال', 'والیبال', 'ورزش', 'تیم ملی', 'لیگ',
    'بورس', 'ارز', 'دلار', 'سکه', 'بیت کوین',
    'انتخابات', 'سیاسی', 'مجلس', 'دولت', 'وزیر',
    'زلزله', 'سیل', 'آتش سوزی', 'تصادف', 'حادثه',
]

MAX_DESCRIPTION_LENGTH = 350
FEED_TIMEOUT = 10       # seconds for RSS fetch
PAGE_TIMEOUT = 8        # seconds for og:image page fetch
DB_TIMEOUT = 6          # seconds for Appwrite API calls
HOURS_THRESHOLD = 48    # how old can a post be (hours)


# ─────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────

async def main(event=None, context=None):
    print("[INFO] ═══════════════════════════════════")
    print("[INFO] Fashion News Bot started")
    print(f"[INFO] Time: {datetime.now(timezone.utc).isoformat()}")
    print("[INFO] ═══════════════════════════════════")

    # Load environment variables
    config = load_config()
    if not config:
        return {"status": "error", "reason": "missing_env_vars"}

    bot = Bot(token=config['token'])
    appwrite = AppwriteClient(
        endpoint=config['endpoint'],
        project=config['project'],
        key=config['key'],
        database_id=config['database_id'],
        collection_id=config['collection_id'],
    )

    now = datetime.now(timezone.utc)
    time_threshold = now - timedelta(hours=HOURS_THRESHOLD)
    posted = False
    total_checked = 0
    total_skipped_time = 0
    total_skipped_filter = 0
    total_skipped_duplicate = 0

    for feed_url in RSS_FEEDS:
        if posted:
            break

        print(f"\n[FEED] Checking: {feed_url}")
        entries = fetch_feed_entries(feed_url)

        if not entries:
            continue

        for entry in entries:
            if posted:
                break

            total_checked += 1

            # ── 1. Parse basic fields ──────────────────────────
            title = clean_text(entry.get('title', ''))
            link = clean_text(entry.get('link', ''))

            if not title or not link:
                continue

            # ── 2. Time filter ─────────────────────────────────
            pub_date = parse_entry_date(entry)
            if pub_date and pub_date < time_threshold:
                total_skipped_time += 1
                continue

            # ── 3. Clean description ───────────────────────────
            raw = entry.get('summary') or entry.get('description') or ''
            description = strip_html(raw)
            description = truncate(description, MAX_DESCRIPTION_LENGTH)

            # ── 4. Fashion relevance filter ────────────────────
            if not is_fashion_related(title, description):
                total_skipped_filter += 1
                print(f"[SKIP:filter] {title[:70]}")
                continue

            # ── 5. Duplicate check ─────────────────────────────
            content_hash = make_hash(title, description)

            if appwrite.is_duplicate(link, content_hash):
                total_skipped_duplicate += 1
                print(f"[SKIP:duplicate] {title[:70]}")
                continue

            # ── 6. Get image ───────────────────────────────────
            image_url = get_image_from_rss(entry) or get_og_image(link)

            # ── 7. Build message ───────────────────────────────
            message = build_message(title, description, link)

            # ── 8. Send to Telegram ────────────────────────────
            success = await send_to_telegram(
                bot=bot,
                chat_id=config['chat_id'],
                text=message,
                image_url=image_url
            )

            if success:
                posted = True
                print(f"[SUCCESS] Post sent: {title[:70]}")

                # ── 9. Save to database ────────────────────────
                appwrite.save_record(
                    link=link,
                    title=title,
                    content_hash=content_hash,
                    created_at=now.isoformat()
                )

    # ── Summary ────────────────────────────────────────────────
    print("\n[INFO] ═══════════════ SUMMARY ════════════════")
    print(f"[INFO] Total checked  : {total_checked}")
    print(f"[INFO] Skipped (time) : {total_skipped_time}")
    print(f"[INFO] Skipped (filter): {total_skipped_filter}")
    print(f"[INFO] Skipped (dupe) : {total_skipped_duplicate}")
    print(f"[INFO] Post sent      : {posted}")
    print("[INFO] ════════════════════════════════════════")

    return {"status": "success", "posted": posted}


# ─────────────────────────────────────────────
#  CONFIGURATION LOADER
# ─────────────────────────────────────────────

def load_config():
    """Load and validate all required environment variables."""
    required = {
        'token':         os.environ.get('TELEGRAM_BOT_TOKEN'),
        'chat_id':       os.environ.get('TELEGRAM_CHANNEL_ID'),
        'endpoint':      os.environ.get('APPWRITE_ENDPOINT', 'https://cloud.appwrite.io/v1'),
        'project':       os.environ.get('APPWRITE_PROJECT_ID'),
        'key':           os.environ.get('APPWRITE_API_KEY'),
        'database_id':   os.environ.get('APPWRITE_DATABASE_ID'),
        'collection_id': os.environ.get('APPWRITE_COLLECTION_ID', 'history'),
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[ERROR] Missing environment variables: {missing}")
        return None

    return required


# ─────────────────────────────────────────────
#  APPWRITE CLIENT
# ─────────────────────────────────────────────

class AppwriteClient:
    """Handles all Appwrite database operations."""

    def __init__(self, endpoint, project, key, database_id, collection_id):
        self.base_url = f"{endpoint}/databases/{database_id}/collections/{collection_id}/documents"
        self.headers = {
            'Content-Type': 'application/json',
            'X-Appwrite-Project': project,
            'X-Appwrite-Key': key,
        }

    def is_duplicate(self, link: str, content_hash: str) -> bool:
        """
        Check if post already exists by link OR content hash.
        Uses correct Appwrite v1 query format.
        """
        # ── Check by link ──────────────────────────────────────
        if self._query_exists('link', link):
            return True

        # ── Check by content hash ──────────────────────────────
        if self._query_exists('content_hash', content_hash):
            return True

        return False

    def _query_exists(self, field: str, value: str) -> bool:
        """Run an Appwrite equal() query and return True if any document found."""
        try:
            # ✅ Correct Appwrite REST query format
            params = {
                'queries[]': f'equal("{field}", ["{value}"])',
                'limit': 1,
            }
            res = requests.get(
                self.base_url,
                headers=self.headers,
                params=params,
                timeout=DB_TIMEOUT
            )

            if res.status_code == 200:
                return res.json().get('total', 0) > 0

            print(f"[WARN] Appwrite query returned {res.status_code}: {res.text[:100]}")
            return False

        except requests.RequestException as e:
            print(f"[WARN] Appwrite query error: {e}")
            return False  # On network error, don't block posting

    def save_record(self, link: str, title: str, content_hash: str, created_at: str) -> bool:
        """
        Save a new document to Appwrite.
        ✅ Uses correct Appwrite REST API structure.
        """
        try:
            # Generate a unique document ID
            doc_id = hashlib.md5(link.encode()).hexdigest()[:20]

            # ✅ Correct Appwrite document creation payload
            payload = {
                'documentId': doc_id,
                'data': {
                    'link': link[:500],
                    'title': title[:300],
                    'content_hash': content_hash,
                    'created_at': created_at,
                }
            }

            res = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=DB_TIMEOUT
            )

            if res.status_code in (200, 201):
                print("[DB] Record saved successfully")
                return True
            else:
                print(f"[WARN] DB save failed ({res.status_code}): {res.text[:150]}")
                return False

        except requests.RequestException as e:
            print(f"[WARN] DB save error: {e}")
            return False


# ─────────────────────────────────────────────
#  RSS FEED FETCHER
# ─────────────────────────────────────────────

def fetch_feed_entries(url: str) -> list:
    """
    Fetch and parse RSS feed entries.
    Returns empty list on any error.
    """
    try:
        # feedparser can hang on slow feeds - use requests with timeout first
        response = requests.get(
            url,
            timeout=FEED_TIMEOUT,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; FashionBot/1.0)',
                'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            }
        )

        if response.status_code != 200:
            print(f"[WARN] Feed returned {response.status_code}: {url}")
            return []

        feed = feedparser.parse(response.content)

        if feed.bozo and not feed.entries:
            print(f"[WARN] Malformed feed: {url}")
            return []

        entries = feed.entries
        print(f"[INFO] Found {len(entries)} entries in feed")
        return entries

    except requests.RequestException as e:
        print(f"[ERROR] Feed fetch failed ({url}): {e}")
        return []
    except Exception as e:
        print(f"[ERROR] Feed parse error ({url}): {e}")
        return []


# ─────────────────────────────────────────────
#  TEXT UTILITIES
# ─────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Strip whitespace and normalize."""
    return (text or '').strip()


def strip_html(html: str) -> str:
    """Remove HTML tags and return clean text."""
    if not html:
        return ''
    soup = BeautifulSoup(html, 'lxml')
    # Remove script and style elements
    for tag in soup(['script', 'style', 'iframe']):
        tag.decompose()
    return ' '.join(soup.get_text(separator=' ').split())


def truncate(text: str, max_length: int) -> str:
    """Truncate text at word boundary."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(' ')
    if last_space > max_length * 0.8:
        truncated = truncated[:last_space]
    return truncated + '...'


def make_hash(title: str, description: str) -> str:
    """Create SHA256 hash for duplicate detection."""
    content = f"{title.lower().strip()} {description[:150].lower().strip()}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def parse_entry_date(entry) -> datetime | None:
    """Safely parse RSS entry date to UTC datetime."""
    for field in ('published_parsed', 'updated_parsed'):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None  # No date = don't skip (be inclusive)


# ─────────────────────────────────────────────
#  FASHION RELEVANCE FILTER
# ─────────────────────────────────────────────

def is_fashion_related(title: str, description: str) -> bool:
    """
    Two-stage filter:
    1. Reject if any negative keyword found
    2. Accept only if at least one positive keyword found
    """
    combined = (title + ' ' + description).lower()

    # Stage 1: Hard rejection
    for kw in NEGATIVE_KEYWORDS:
        if kw in combined:
            return False

    # Stage 2: Must have fashion content
    for kw in POSITIVE_KEYWORDS:
        if kw in combined:
            return True

    return False


# ─────────────────────────────────────────────
#  IMAGE EXTRACTION
# ─────────────────────────────────────────────

def get_image_from_rss(entry) -> str | None:
    """
    Extract image URL from RSS entry.
    Handles multiple RSS image formats.
    """
    # ── Method 1: <enclosure> tag ──────────────────────────────
    enclosures = entry.get('enclosures', [])
    # feedparser sometimes puts single enclosure as entry.enclosure
    if not enclosures and hasattr(entry, 'enclosure'):
        enclosures = [entry.enclosure]

    for enc in enclosures:
        if isinstance(enc, dict):
            mime = enc.get('type', '')
            url = enc.get('href') or enc.get('url', '')
        else:
            mime = getattr(enc, 'type', '')
            url = getattr(enc, 'href', '') or getattr(enc, 'url', '')

        if mime.startswith('image/') and url:
            return url

    # ── Method 2: <media:content> tag ─────────────────────────
    media_content = entry.get('media_content', [])
    for media in media_content:
        if isinstance(media, dict):
            url = media.get('url', '')
            medium = media.get('medium', '')
        else:
            url = getattr(media, 'url', '')
            medium = getattr(media, 'medium', '')

        if url and (medium == 'image' or url.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))):
            return url

    # ── Method 3: <media:thumbnail> tag ───────────────────────
    media_thumbnail = entry.get('media_thumbnail', [])
    for thumb in media_thumbnail:
        url = thumb.get('url', '') if isinstance(thumb, dict) else getattr(thumb, 'url', '')
        if url:
            return url

    # ── Method 4: Image in description HTML ───────────────────
    raw = entry.get('summary') or entry.get('description') or entry.get('content', [{}])[0].get('value', '')
    if raw:
        soup = BeautifulSoup(raw, 'lxml')
        img = soup.find('img')
        if img and img.get('src'):
            src = img['src']
            if src.startswith('http'):
                return src

    return None


def get_og_image(url: str) -> str | None:
    """Fetch article page and extract og:image meta tag."""
    try:
        response = requests.get(
            url,
            timeout=PAGE_TIMEOUT,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            allow_redirects=True,
        )

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'lxml')

        # Try og:image first, then twitter:image
        for prop in ('og:image', 'twitter:image'):
            tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            if tag and tag.get('content'):
                img_url = tag['content'].strip()
                if img_url.startswith('http'):
                    return img_url

    except requests.RequestException:
        pass
    except Exception:
        pass

    return None


# ─────────────────────────────────────────────
#  MESSAGE BUILDER
# ─────────────────────────────────────────────

def build_message(title: str, description: str, link: str) -> str:
    """
    Build clean Persian fashion post.
    No HTML tags used since parse_mode is set to HTML
    but we want plain text with emoji formatting.
    """
    parts = [f"💠 <b>{title}</b>"]

    if description:
        parts.append(f"\n{description}")

    parts.append("\n")
    parts.append("👗 #مد  ✨ #استایل  🌟 #ترند")
    parts.append("#فشن_ایرانی  #زیبایی")
    parts.append(f"\n🔗 <a href='{link}'>ادامه مطلب</a>")
    parts.append("🆔 @irfashionnews")

    return '\n'.join(parts)


# ─────────────────────────────────────────────
#  TELEGRAM SENDER
# ─────────────────────────────────────────────

async def send_to_telegram(
    bot: Bot,
    chat_id: str,
    text: str,
    image_url: str | None
) -> bool:
    """
    Send post to Telegram channel.
    Falls back from photo → text if image fails.
    """
    # ── Try sending with photo ─────────────────────────────────
    if image_url:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=text,
                parse_mode='HTML',
                disable_notification=True,
            )
            return True
        except TelegramError as e:
            print(f"[WARN] Photo send failed ({e}), trying text-only...")

    # ── Fallback: text only ────────────────────────────────────
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode='HTML',
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            disable_notification=True,
        )
        return True

    except TelegramError as e:
        print(f"[ERROR] Message send failed: {e}")
        return False


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(main())