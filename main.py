from concurrent.futures import ThreadPoolExecutor
import csv
import datetime
import hashlib
import html
import io
import json
import mimetypes
import os
import random
import re
import secrets
import shutil
import smtplib
import socket
import sqlite3
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile
import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="House of Wind")

# 1. Paths and Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

DATA_DIR = os.getenv("DATA_DIR")
if DATA_DIR:
    os.makedirs(DATA_DIR, exist_ok=True)
    DB_FILE = os.path.join(DATA_DIR, "library.db")
    STORAGE_DIR = os.path.join(DATA_DIR, "books_storage")
    INBOX_DIR = os.path.join(DATA_DIR, "import_inbox")
    COVERS_DIR = os.path.join(DATA_DIR, "covers")
else:
    DB_FILE = os.path.join(BASE_DIR, "library.db")
    STORAGE_DIR = os.path.join(BASE_DIR, "books_storage")
    INBOX_DIR = os.path.join(BASE_DIR, "import_inbox")
    COVERS_DIR = os.path.join(STATIC_DIR, "covers")

os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(INBOX_DIR, exist_ok=True)
os.makedirs(COVERS_DIR, exist_ok=True)

if DATA_DIR:
    app.mount("/static/covers", StaticFiles(directory=COVERS_DIR), name="persistent_covers")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

AUDIO_EXTENSIONS = {".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wav"}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# 2. Database Setup & Automatic Schema Upgrade
def init_db():
    """Creates the database table automatically on first run and ensures all new columns exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            filename TEXT DEFAULT '',
            description TEXT DEFAULT '',
            isbn TEXT DEFAULT '',
            cover_url TEXT DEFAULT '',
            published_year TEXT DEFAULT '',
            source TEXT DEFAULT '',
            series_name TEXT DEFAULT '',
            series_number TEXT DEFAULT '',
            is_read INTEGER DEFAULT 0,
            reading_status TEXT DEFAULT 'unread',
            rating INTEGER DEFAULT 0,
            review TEXT DEFAULT '',
            date_read TEXT DEFAULT '',
            media_type TEXT DEFAULT 'ebook',
            narrator TEXT DEFAULT '',
            duration TEXT DEFAULT '',
            review_headline TEXT DEFAULT '',
            favorite_quotes TEXT DEFAULT '',
            favorite_characters TEXT DEFAULT '',
            spice_rating INTEGER DEFAULT 0,
            pace TEXT DEFAULT '',
            tropes TEXT DEFAULT '',
            page_count INTEGER DEFAULT 0,
            current_page INTEGER DEFAULT 0,
            progress_percent INTEGER DEFAULT 0,
            genres TEXT DEFAULT ''
        )
    """)
    # Ensure all files and unread books automatically default to TBR
    cursor.execute("""
        UPDATE books
        SET reading_status = 'tbr'
        WHERE is_read = 0 AND (reading_status = 'unread' OR reading_status IS NULL OR reading_status = '')
    """)

    # Create reading_logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reading_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER,
            date TEXT NOT NULL,
            pages_read INTEGER DEFAULT 0,
            minutes_read INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create user_achievements table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_achievements (
            badge_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            icon TEXT NOT NULL,
            category TEXT NOT NULL,
            unlocked_at TEXT DEFAULT NULL,
            reward_title TEXT DEFAULT ''
        )
    """)

    # Seed achievements if empty
    # Seed or migrate reading achievements (no streaks, all days read and milestones)
    cursor.execute("DELETE FROM user_achievements WHERE badge_id LIKE 'streak_%'")
    romantasy_badges = [
        ("days_3", "Spark of Magic", "Logged reading on 3 distinct days", "🕯️", "habit", None, "Novice Scribe of Velaris"),
        ("days_7", "Night Court Initiate", "Logged reading on 7 distinct days", "🌙", "habit", None, "Night Court Courtier"),
        ("days_14", "Fortnight in Prythian", "Logged reading on 14 distinct days", "🌌", "habit", None, "Inner Circle Companion"),
        ("days_30", "Mist & Fury Devotee", "Logged reading on 30 distinct days", "🦇", "habit", None, "High Lord's Confidante"),
        ("days_60", "Illyrian Warrior Reader", "Logged reading on 60 distinct days", "🗡️", "habit", None, "Carynthian Champion"),
        ("days_100", "Archivist of the Night", "Logged reading on 100 distinct days", "👑", "habit", None, "High Fae Scholar"),
        ("days_180", "Six Months in Prythian", "Logged reading on 180 distinct days", "🌟", "habit", None, "High Lady of Velaris"),
        ("days_365", "Year of the Valkyrie", "Logged reading on 365 distinct days", "⚔️", "habit", None, "Carynthian Legend"),
        ("pages_250", "First Flight of the Dragon", "Read 250 total pages", "🐉", "pages", None, "Basgiath First-Year"),
        ("pages_1000", "Grimoire of Velaris", "Read over 1,000 pages of stories", "📜", "pages", None, "Keeper of Ancient Volumes"),
        ("pages_2500", "Shadowsinger's Compendium", "Read over 2,500 pages", "🖤", "pages", None, "Shadow Whisperer"),
        ("pages_5000", "Queen of Tomes", "Conquer 5,000 pages of stories", "⚔️", "pages", None, "“You do not yield”"),
        ("pages_10000", "Infinite Stacks", "Conquer over 10,000 pages of stories", "💎", "pages", None, "Mistress of the Archives"),
        ("books_finished_1", "First Story Conquered", "Finish reading your first book", "📖", "books", None, "Literary Adventurer"),
        ("books_finished_3", "Trio of Fates", "Finish reading 3 books", "✨", "books", None, "Weaver of Fates"),
        ("books_finished_5", "Fireheart Ascendant", "Finish reading 5 books", "🔥", "books", None, "Fireheart"),
        ("books_finished_10", "Velaris High Scholar", "Finish reading 10 books", "🏛️", "books", None, "Curator of House of Wind"),
        ("books_finished_20", "High Court Royalty", "Finish reading 20 books", "👑", "books", None, "High Queen of the Court"),
        ("books_finished_50", "Legend of Terrasen", "Finish reading 50 books", "🔥", "books", None, "“To whatever end”"),
        ("audio_5h", "Whispers in the Dark", "Listen to 5+ hours of audiobooks", "🎧", "audio", None, "Attuned Listener"),
        ("audio_15h", "Siren of the Spoken Word", "Listen to 15+ hours of audiobooks", "🌊", "audio", None, "Enchanted Siren"),
        ("audio_30h", "Bard of Erilea", "Listen to 30+ hours of audiobooks", "🎵", "audio", None, "Master Lorekeeper"),
        ("spice_lover", "Court of Pure Heat", "Read 2+ books with spice rating 3+ 🌶️", "🌶️", "romantasy", None, "Spice Connoisseur"),
        ("spice_fiend", "High Priestess of Smut", "Read 4+ books with high spice (4-5 🌶️)", "🩸", "romantasy", None, "High Priestess of Smut"),
        ("five_star_club", "Starfall Celebration", "Award 3+ books a perfect 5-star rating", "⭐", "social", None, "Chosen of Starfall"),
        ("quote_collector", "Carved in Bone", "Save favorite quotes from 3+ books", "🖋️", "social", None, "Rune Carver of the Dead"),
        ("author_loyalist", "Bloodsworn to the Author", "Read 3+ books by the same beloved author", "🩸", "books", None, "Bloodsworn Sentinel"),
        ("genre_explorer", "World Walker", "Explore stories across 4 or more distinct genres", "🧭", "habit", None, "Realm Walker"),
        ("weekend_warrior", "Sunlit Library Retreat", "Log reading on 5+ weekend days", "☀️", "habit", None, "Sunlit Scholar"),
        ("quick_checkin", "Every Day Counts", "Check in for today's reading session", "✅", "habit", None, "Faithful Reader"),
        ("series_finisher", "Slayer of Sagas", "Finish all books in any series", "🏆", "series", None, "Conqueror of Series"),
        ("critic_3", "The Suriel's Tea", "Write 2+ detailed book reviews", "☕", "social", None, "Spiller of Fae Tea"),
        ("tbr_hoarder", "Dragon's Book Hoard", "Have 3+ books queued on your TBR", "🏰", "tbr", None, "Keeper of the Hoard"),
        ("trope_hunter", "Dagger to the Throat", "Read books with romance tropes or romantasy", "🏹", "romantasy", None, "Enemies-to-Lovers Devotee"),
        ("mythology_reader", "Blessed by Olympus", "Read a Greek or mythology-inspired book", "⚡", "romantasy", None, "Favored of the Gods"),
        ("fast_reader", "Midnight Page-Turner", "Read 50+ pages in a day or reach 300+ total pages", "🔮", "romantasy", None, "Nocturnal Bibliophile")
    ]
    for b_id, name, desc, icon, cat, default_unlocked, reward in romantasy_badges:
        cursor.execute("SELECT unlocked_at FROM user_achievements WHERE badge_id = ?", (b_id,))
        row = cursor.fetchone()
        existing_unlocked = row[0] if row else default_unlocked
        cursor.execute("""
            INSERT OR REPLACE INTO user_achievements (badge_id, name, description, icon, category, unlocked_at, reward_title)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (b_id, name, desc, icon, cat, existing_unlocked, reward))

    cursor.execute("PRAGMA table_info(books)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    new_columns = {
        "description": "TEXT DEFAULT ''",
        "isbn": "TEXT DEFAULT ''",
        "cover_url": "TEXT DEFAULT ''",
        "published_year": "TEXT DEFAULT ''",
        "source": "TEXT DEFAULT ''",
        "series_name": "TEXT DEFAULT ''",
        "series_number": "TEXT DEFAULT ''",
        "is_read": "INTEGER DEFAULT 0",
        "reading_status": "TEXT DEFAULT 'unread'",
        "rating": "INTEGER DEFAULT 0",
        "review": "TEXT DEFAULT ''",
        "date_read": "TEXT DEFAULT ''",
        "media_type": "TEXT DEFAULT 'ebook'",
        "narrator": "TEXT DEFAULT ''",
        "duration": "TEXT DEFAULT ''",
        "review_headline": "TEXT DEFAULT ''",
        "favorite_quotes": "TEXT DEFAULT ''",
        "favorite_characters": "TEXT DEFAULT ''",
        "spice_rating": "INTEGER DEFAULT 0",
        "pace": "TEXT DEFAULT ''",
        "tropes": "TEXT DEFAULT ''",
        "page_count": "INTEGER DEFAULT 0",
        "current_page": "INTEGER DEFAULT 0",
        "progress_percent": "INTEGER DEFAULT 0",
        "genres": "TEXT DEFAULT ''",
        "deleted_at": "TEXT DEFAULT NULL",
        "current_audio_minutes": "INTEGER DEFAULT 0"
    }
    for col, col_def in new_columns.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE books ADD COLUMN {col} {col_def}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS series_overrides (
            series_name TEXT PRIMARY KEY,
            next_number TEXT DEFAULT '',
            next_title TEXT DEFAULT '',
            author TEXT DEFAULT ''
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            role TEXT DEFAULT 'admin',
            theme_preference TEXT DEFAULT '',
            custom_themes TEXT DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Ensure columns exist if table was already created
    cursor.execute("PRAGMA table_info(users)")
    user_cols = [r[1] for r in cursor.fetchall()]
    if "theme_preference" not in user_cols:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN theme_preference TEXT DEFAULT ''")
        except Exception:
            pass
    if "custom_themes" not in user_cols:
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN custom_themes TEXT DEFAULT '[]'")
        except Exception:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()


init_db()


def get_all_settings() -> dict:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM app_settings")
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def detect_media_type(filename: str, override: Optional[str] = None) -> str:
    if override and override.lower() in ("ebook", "audiobook"):
        return override.lower()
    ext = os.path.splitext(filename or "")[1].lower()
    return "audiobook" if ext in AUDIO_EXTENSIONS else "ebook"


def format_minutes_to_duration(minutes_val) -> str:
    try:
        mins = int(minutes_val)
        if mins <= 0:
            return ""
        h = mins // 60
        m = mins % 60
        if h > 0 and m > 0:
            return f"{h}h {m}m"
        elif h > 0:
            return f"{h}h"
        return f"{m}m"
    except Exception:
        return ""


def clean_html_text(raw: str) -> str:
    """Strips HTML tags and unescapes entities from book descriptions."""
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_series_from_title(full_title: str) -> tuple[str, str, str]:
    """
    Detects Goodreads-style series annotations in titles like:
    'Fourth Wing (The Empyrean, #1)' or 'Dune (Dune Chronicles #1)'
    Returns (clean_title, series_name, series_number).
    """
    if not full_title:
        return "", "", ""
    match = re.search(r"\(([^()]+?)(?:,\s*|\s+)#(\d+(?:\.\d+)?)\)\s*$", full_title.strip())
    if match:
        series_name = match.group(1).strip()
        series_num = match.group(2).strip()
        clean_t = full_title[:match.start()].strip()
        return clean_t, series_name, series_num
    return full_title.strip(), "", ""


def clean_search_query_from_filename(filename: str) -> str:
    """
    Removes common download watermarks, brackets, extensions, and noise from filenames.
    """
    name = os.path.splitext(filename or "")[0]
    name = re.sub(
        r"(?i)(_?oceanofpdf\.com_?|audiobookbay\.lu|audiobookbay\.nl|audiobookbay|audiobook_bay|abb|z-lib\.org|z-library|annas-archive|libgen|\bepub\b|\bmobi\b|\bazw3\b|\bm4b\b|\bmp3\b|\baudiobook\b|\bunabridged\b|\bretail\b)",
        " ",
        name,
    )
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", name)
    name = re.sub(r"[_.]+", " ", name)
    name = re.sub(r"\s*-\s*", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name


# --- EMBEDDED EPUB METADATA EXTRACTOR ---
def extract_epub_metadata(file_bytes: bytes) -> dict:
    extracted = {
        "title": "",
        "author": "",
        "description": "",
        "isbn": "",
        "published_year": "",
        "series_name": "",
        "series_number": "",
    }
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            opf_path = None
            if "META-INF/container.xml" in zf.namelist():
                container_xml = zf.read("META-INF/container.xml")
                root = ET.fromstring(container_xml)
                for elem in root.iter():
                    if elem.tag.endswith("rootfile") and elem.attrib.get("full-path"):
                        opf_path = elem.attrib["full-path"]
                        break
            if not opf_path:
                for name in zf.namelist():
                    if name.lower().endswith(".opf"):
                        opf_path = name
                        break

            if not opf_path or opf_path not in zf.namelist():
                return extracted

            opf_xml = zf.read(opf_path)
            root = ET.fromstring(opf_xml)

            authors = []
            for elem in root.iter():
                tag = elem.tag.split("}")[-1].lower()
                text = (elem.text or "").strip()

                if tag == "meta":
                    meta_name = (elem.attrib.get("name") or "").lower()
                    meta_prop = (elem.attrib.get("property") or "").lower()
                    meta_content = (elem.attrib.get("content") or text or "").strip()
                    if meta_name == "calibre:series" and meta_content:
                        extracted["series_name"] = meta_content
                    elif meta_name == "calibre:series_index" and meta_content:
                        extracted["series_number"] = meta_content
                    elif meta_prop == "belongs-to-collection" and meta_content:
                        extracted["series_name"] = meta_content

                if not text:
                    continue
                if tag == "title" and not extracted["title"]:
                    extracted["title"] = text
                elif tag == "creator":
                    authors.append(text)
                elif tag == "description" and not extracted["description"]:
                    extracted["description"] = clean_html_text(text)
                elif tag == "date" and not extracted["published_year"]:
                    year_match = re.search(r"\b(19\d\d|20\d\d)\b", text)
                    if year_match:
                        extracted["published_year"] = year_match.group(1)
                elif tag == "identifier":
                    clean_id = re.sub(r"[^0-9Xx]", "", text)
                    if len(clean_id) in (10, 13) and (
                        clean_id.startswith("978") or clean_id.startswith("979") or len(clean_id) == 10
                    ):
                        if not extracted["isbn"] or len(clean_id) == 13:
                            extracted["isbn"] = clean_id

            if authors:
                extracted["author"] = ", ".join(authors)
    except Exception as e:
        print(f"EPUB internal parse note: {e}")

    return extracted


# --- METADATA PROVIDER 1: GOODREADS ---
def fetch_goodreads_book_page(book_url: str) -> dict:
    details = {
        "title": "",
        "author": "",
        "description": "",
        "isbn": "",
        "cover_url": "",
        "published_year": "",
        "series_name": "",
        "series_number": "",
        "narrator": "",
        "duration": "",
        "source": "Goodreads",
    }
    try:
        res = requests.get(book_url, headers=BROWSER_HEADERS, timeout=6)
        if not res.ok:
            return details
        page = res.text

        ld_match = re.search(
            r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
            page,
            flags=re.DOTALL
        )
        if ld_match:
            try:
                ld_data = json.loads(ld_match.group(1))
                if ld_data.get("name"):
                    raw_t = html.unescape(str(ld_data["name"]))
                    clean_t, s_name, s_num = parse_series_from_title(raw_t)
                    details["title"] = clean_t
                    if s_name:
                        details["series_name"] = s_name
                        details["series_number"] = s_num
                if ld_data.get("isbn"):
                    details["isbn"] = str(ld_data["isbn"])
                if ld_data.get("image"):
                    details["cover_url"] = str(ld_data["image"])
                authors_ld = ld_data.get("author", [])
                if isinstance(authors_ld, list):
                    names = [a.get("name", "") for a in authors_ld if isinstance(a, dict) and a.get("name")]
                    if names:
                        details["author"] = ", ".join(names)
                elif isinstance(authors_ld, dict) and authors_ld.get("name"):
                    details["author"] = authors_ld["name"]
            except Exception:
                pass

        next_match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">\s*(\{.*?\})\s*</script>',
            page,
            flags=re.DOTALL
        )
        if next_match:
            try:
                raw_next = next_match.group(1)
                desc_match = re.search(r'"description":"((?:\\.|[^"\\])*)"', raw_next)
                if desc_match:
                    decoded = json.loads(f'"{desc_match.group(1)}"')
                    details["description"] = clean_html_text(decoded)
                pub_match = re.search(r'"publicationTime":(-?\d+)', raw_next)
                if pub_match:
                    ts = int(pub_match.group(1)) / 1000.0
                    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                    details["published_year"] = str(dt.year)
            except Exception:
                pass

        if not details["description"]:
            og_desc = re.search(
                r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
                page,
                flags=re.IGNORECASE
            )
            if og_desc:
                details["description"] = clean_html_text(og_desc.group(1))
    except Exception as e:
        print(f"Goodreads page warning: {e}")
    return details


def search_goodreads(query: str, limit: int = 5) -> list[dict]:
    if "goodreads.com/book/show" in query:
        direct = fetch_goodreads_book_page(query.strip())
        return [direct] if direct.get("title") else []

    results = []
    try:
        url = f"https://www.goodreads.com/book/auto_complete?format=json&q={requests.utils.quote(query)}"
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=6)
        if not res.ok:
            return results
        items = res.json()
        if not isinstance(items, list):
            return results

        raw_entries = []
        for item in items[:limit]:
            full_title_with_series = html.unescape(item.get("title") or "")
            bare_title = html.unescape(item.get("bookTitleBare") or full_title_with_series or "Unknown Title")
            _, series_name, series_num = parse_series_from_title(full_title_with_series)

            author_obj = item.get("author", {})
            author = author_obj.get("name", "Unknown Author") if isinstance(author_obj, dict) else "Unknown Author"

            image_url = item.get("imageUrl", "")
            if image_url:
                image_url = re.sub(r"\._S[XY]\d+(_S[XY]\d+)?_\.", ".", image_url)

            desc_obj = item.get("description", {})
            description = ""
            if isinstance(desc_obj, dict):
                description = clean_html_text(desc_obj.get("html") or "")

            book_url = item.get("bookUrl") or (desc_obj.get("fullContentUrl") if isinstance(desc_obj, dict) else "") or ""
            if book_url and book_url.startswith("/"):
                book_url = f"https://www.goodreads.com{book_url}"

            raw_entries.append({
                "title": bare_title,
                "author": html.unescape(author),
                "description": description,
                "isbn": "",
                "cover_url": image_url,
                "published_year": "",
                "series_name": series_name,
                "series_number": series_num,
                "narrator": "",
                "duration": "",
                "book_url": book_url,
                "source": "Goodreads",
            })

        def enrich_entry(entry):
            if entry.get("book_url") and not entry.get("description"):
                extra = fetch_goodreads_book_page(entry["book_url"])
                entry["description"] = extra.get("description") or entry["description"]
                entry["isbn"] = extra.get("isbn") or entry["isbn"]
                entry["published_year"] = extra.get("published_year") or entry["published_year"]
                entry["series_name"] = entry["series_name"] or extra.get("series_name", "")
                entry["series_number"] = entry["series_number"] or extra.get("series_number", "")
                if extra.get("cover_url") and not entry["cover_url"]:
                    entry["cover_url"] = extra["cover_url"]
            return entry

        with ThreadPoolExecutor(max_workers=3) as pool:
            enriched_top = list(pool.map(enrich_entry, raw_entries[:3]))
        results = enriched_top + raw_entries[3:]
    except Exception as e:
        print(f"Goodreads lookup warning: {e}")
    return results


# --- METADATA PROVIDER 2: GOOGLE BOOKS ---
def search_google_books(query: str, limit: int = 5) -> list[dict]:
    results = []
    try:
        clean_isbn = re.sub(r"[^0-9Xx]", "", query)
        if len(clean_isbn) in (10, 13) and clean_isbn[:3] in ("978", "979"):
            q_param = f"isbn:{clean_isbn}"
        else:
            q_param = query

        url = (
            f"https://www.googleapis.com/books/v1/volumes"
            f"?q={requests.utils.quote(q_param)}"
            f"&printType=books&maxResults={limit}"
        )
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=6)
        if not res.ok:
            return results
        items = res.json().get("items", [])
        for item in items[:limit]:
            info = item.get("volumeInfo", {})
            title = info.get("title", "Unknown Title")
            subtitle = info.get("subtitle", "")
            full_title = f"{title}: {subtitle}" if subtitle and subtitle.lower() not in title.lower() else title
            clean_t, s_name, s_num = parse_series_from_title(full_title)

            authors = ", ".join(info.get("authors", ["Unknown Author"]))
            desc = clean_html_text(info.get("description", ""))

            identifiers = info.get("industryIdentifiers", [])
            isbn = ""
            for ident in identifiers:
                if ident.get("type") == "ISBN_13":
                    isbn = ident.get("identifier", "")
                    break
            if not isbn and identifiers:
                isbn = identifiers[0].get("identifier", "")

            links = info.get("imageLinks", {})
            cover = (
                links.get("extraLarge")
                or links.get("large")
                or links.get("medium")
                or links.get("thumbnail")
                or links.get("smallThumbnail")
                or ""
            )
            if cover:
                cover = cover.replace("http://", "https://").replace("&edge=curl", "").replace("zoom=1", "zoom=2")

            pub_date = info.get("publishedDate", "") or ""
            pub_year = pub_date[:4] if len(pub_date) >= 4 else ""

            results.append({
                "title": clean_t,
                "author": authors,
                "description": desc,
                "isbn": isbn,
                "cover_url": cover,
                "published_year": pub_year,
                "series_name": s_name,
                "series_number": s_num,
                "narrator": "",
                "duration": "",
                "source": "Google Books"
            })
    except Exception as e:
        print(f"Google Books lookup warning: {e}")
    return results


# --- METADATA PROVIDER 3: APPLE BOOKS & APPLE AUDIOBOOKS ---
def search_apple_books(query: str, limit: int = 5, media: str = "ebook") -> list[dict]:
    results = []
    try:
        entity = "audiobook" if media == "audiobook" else "ebook"
        url = (
            f"https://itunes.apple.com/search"
            f"?term={requests.utils.quote(query)}"
            f"&media={entity}&entity={entity}&limit={limit}"
        )
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=6)
        if not res.ok:
            return results
        items = res.json().get("results", [])
        for item in items[:limit]:
            raw_title = item.get("trackName") or item.get("collectionName") or "Unknown Title"
            raw_title = re.sub(r"\s*\((Unabridged|Abridged)\)\s*$", "", raw_title, flags=re.IGNORECASE)
            clean_t, s_name, s_num = parse_series_from_title(raw_title)
            author = item.get("artistName", "Unknown Author")
            desc = clean_html_text(item.get("description", ""))
            release_date = item.get("releaseDate", "") or ""
            pub_year = release_date[:4] if len(release_date) >= 4 else ""

            cover = item.get("artworkUrl100", "")
            if cover:
                cover = re.sub(r"100x100bb", "600x600bb", cover)

            results.append({
                "title": clean_t,
                "author": author,
                "description": desc,
                "isbn": "",
                "cover_url": cover,
                "published_year": pub_year,
                "series_name": s_name,
                "series_number": s_num,
                "narrator": "",
                "duration": "",
                "source": "Apple Audiobooks" if entity == "audiobook" else "Apple Books"
            })
    except Exception as e:
        print(f"Apple Books lookup warning: {e}")
    return results


# --- METADATA PROVIDER 4: AMAZON / AUDIBLE CATALOG (WITH NARRATOR & DURATION!) ---
def search_amazon_audible(query: str, limit: int = 5) -> list[dict]:
    """
    Queries Amazon's public Audible Catalog API for official summaries,
    authors, narrators, runtime duration, series, and cover art!
    """
    results = []
    try:
        url = (
            "https://api.audible.com/1.0/catalog/products"
            f"?keywords={requests.utils.quote(query)}"
            f"&num_results={limit}"
            "&products_sort_by=Relevance"
            "&response_groups=contributors,product_desc,product_attrs,media,series"
        )
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=6)
        if not res.ok:
            return results
        products = res.json().get("products", [])
        for prod in products[:limit]:
            title = prod.get("title", "Unknown Title")
            subtitle = prod.get("subtitle", "")
            full_title = f"{title}: {subtitle}" if subtitle and subtitle.lower() not in title.lower() else title

            authors_list = [a.get("name") for a in prod.get("authors", []) if a.get("name")]
            author = ", ".join(authors_list) if authors_list else "Unknown Author"

            narrators_list = [n.get("name") for n in prod.get("narrators", []) if n.get("name")]
            narrator = ", ".join(narrators_list)

            duration = format_minutes_to_duration(prod.get("runtime_length_min"))

            desc = clean_html_text(prod.get("publisher_summary") or prod.get("merchandising_summary") or "")
            isbn = prod.get("isbn") or prod.get("asin") or ""
            issue_date = prod.get("issue_date") or prod.get("release_date") or ""
            pub_year = issue_date[:4] if len(issue_date) >= 4 else ""

            series_list = prod.get("series", [])
            s_name = series_list[0].get("title", "") if series_list else ""
            s_num = str(series_list[0].get("sequence", "")) if series_list else ""

            images = prod.get("product_images", {})
            cover = images.get("500") or images.get("1024") or next(iter(images.values()), "") if images else ""

            results.append({
                "title": full_title,
                "author": author,
                "description": desc,
                "isbn": isbn,
                "cover_url": cover,
                "published_year": pub_year,
                "series_name": s_name,
                "series_number": s_num,
                "narrator": narrator,
                "duration": duration,
                "source": "Amazon / Audible"
            })
    except Exception as e:
        print(f"Amazon/Audible lookup warning: {e}")
    return results


# --- UNIFIED METADATA AGGREGATOR ---
def search_online_metadata_candidates(query: str, source: str = "all", limit: int = 8) -> list[dict]:
    source = (source or "all").lower().strip()
    clean_q = query.strip()
    if not clean_q:
        return []

    if "goodreads.com/book/show" in clean_q:
        return search_goodreads(clean_q, limit=1)

    if source == "goodreads":
        return search_goodreads(clean_q, limit=limit)
    elif source == "google":
        return search_google_books(clean_q, limit=limit)
    elif source == "apple":
        return search_apple_books(clean_q, limit=limit, media="ebook")
    elif source == "apple_audio":
        return search_apple_books(clean_q, limit=limit, media="audiobook")
    elif source == "amazon":
        return search_amazon_audible(clean_q, limit=limit)

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_amz = pool.submit(search_amazon_audible, clean_q, 3)
        f_gr = pool.submit(search_goodreads, clean_q, 3)
        f_ap = pool.submit(search_apple_books, clean_q, 3)
        f_gb = pool.submit(search_google_books, clean_q, 3)

        amz_results = f_amz.result()
        gr_results = f_gr.result()
        ap_results = f_ap.result()
        gb_results = f_gb.result()

    fallback_isbn = gb_results[0]["isbn"] if gb_results and gb_results[0]["isbn"] else ""
    fallback_desc = (
        (ap_results[0]["description"] if ap_results and ap_results[0]["description"] else "")
        or (amz_results[0]["description"] if amz_results and amz_results[0]["description"] else "")
        or (gb_results[0]["description"] if gb_results and gb_results[0]["description"] else "")
    )
    fallback_year = (
        (ap_results[0]["published_year"] if ap_results and ap_results[0]["published_year"] else "")
        or (gb_results[0]["published_year"] if gb_results and gb_results[0]["published_year"] else "")
    )
    fallback_series = (
        (gr_results[0]["series_name"] if gr_results and gr_results[0].get("series_name") else "")
        or (amz_results[0]["series_name"] if amz_results and amz_results[0].get("series_name") else "")
    )
    fallback_series_num = (
        (gr_results[0]["series_number"] if gr_results and gr_results[0].get("series_number") else "")
        or (amz_results[0]["series_number"] if amz_results and amz_results[0].get("series_number") else "")
    )
    fallback_narrator = amz_results[0]["narrator"] if amz_results and amz_results[0].get("narrator") else ""
    fallback_duration = amz_results[0]["duration"] if amz_results and amz_results[0].get("duration") else ""

    for lst in (gr_results, ap_results, gb_results):
        for idx, item in enumerate(lst):
            if idx == 0:
                if not item["description"] and fallback_desc:
                    item["description"] = fallback_desc
                if not item["isbn"] and fallback_isbn:
                    item["isbn"] = fallback_isbn
                if not item["published_year"] and fallback_year:
                    item["published_year"] = fallback_year
                if not item.get("series_name") and fallback_series:
                    item["series_name"] = fallback_series
                    item["series_number"] = fallback_series_num
                if not item.get("narrator") and fallback_narrator:
                    item["narrator"] = fallback_narrator
                if not item.get("duration") and fallback_duration:
                    item["duration"] = fallback_duration

    combined = []
    max_len = max(len(gr_results), len(amz_results), len(ap_results), len(gb_results), 0)
    for i in range(max_len):
        for bucket in (gr_results, amz_results, ap_results, gb_results):
            if i < len(bucket):
                combined.append(bucket[i])

    return combined[:10]


def fetch_online_metadata(query: str, source: str = "all") -> Optional[dict]:
    results = search_online_metadata_candidates(query, source=source, limit=4)
    return results[0] if results else None


def get_active_gemini_key() -> str:
    settings = get_all_settings()
    return (os.environ.get("GEMINI_API_KEY") or settings.get("gemini_api_key", "")).strip()


GEMINI_FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash"]


def call_gemini_api(prompt: str, json_mode: bool = False, temperature: float = 0.2, max_tokens: int = 1000) -> Optional[str]:
    gemini_key = get_active_gemini_key()
    if not gemini_key:
        return None
    for model in GEMINI_FALLBACK_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": cfg
        }
        try:
            resp = requests.post(url, json=body, timeout=16)
            if resp.status_code == 200:
                data = resp.json()
                cand = data.get("candidates", [{}])[0]
                text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
                if text:
                    return text
            elif resp.status_code == 429:
                print(f"[Gemini Fallback] Model {model} returned HTTP 429 (quota exhausted), trying next model...")
                continue
            else:
                print(f"[Gemini] Model {model} returned status {resp.status_code}")
        except Exception as e:
            print(f"[Gemini] Model {model} request failed: {e}")
            continue
    return None


POPULAR_ROMANCE_IO_CACHE = {
    "fourth wing": {"spice_rating": 4, "tropes": "enemies to lovers, dragons, fantasy romance, forced proximity, slow burn"},
    "iron flame": {"spice_rating": 4, "tropes": "fantasy romance, dragons, war, enemies to lovers, military fantasy"},
    "onyx storm": {"spice_rating": 4, "tropes": "fantasy romance, dragons, war, enemies to lovers"},
    "a court of thorns and roses": {"spice_rating": 3, "tropes": "fantasy romance, fae, beauty and the beast retelling, magic"},
    "a court of mist and fury": {"spice_rating": 5, "tropes": "fantasy romance, fae, mates, slow burn, healing, high spice"},
    "a court of wings and ruin": {"spice_rating": 4, "tropes": "fantasy romance, war, fae, magic"},
    "a court of frost and starlight": {"spice_rating": 3, "tropes": "fantasy romance, fae, novella, holiday"},
    "a court of silver flames": {"spice_rating": 5, "tropes": "fantasy romance, fae, enemies to lovers, explicit open door, healing, valkyrie"},
    "from blood and ash": {"spice_rating": 4, "tropes": "fantasy romance, vampires, enemies to lovers, royalty, bodyguards"},
    "a kingdom of flesh and fire": {"spice_rating": 4, "tropes": "fantasy romance, enemies to lovers, vampires, slow burn"},
    "the crown of gilded bones": {"spice_rating": 4, "tropes": "fantasy romance, royalty, magic, vampires, prophecy"},
    "the war of two queens": {"spice_rating": 4, "tropes": "fantasy romance, war, poly/trio, vampires"},
    "a soul of ash and blood": {"spice_rating": 4, "tropes": "fantasy romance, memories, vampires, dual pov"},
    "a shadow in the ember": {"spice_rating": 4, "tropes": "fantasy romance, gods, primal of death, enemies to lovers, prequel"},
    "a light in the flame": {"spice_rating": 4, "tropes": "fantasy romance, gods, fate, primal"},
    "a fire in the flesh": {"spice_rating": 4, "tropes": "fantasy romance, gods, war, imprisonment"},
    "born of blood and ash": {"spice_rating": 4, "tropes": "fantasy romance, gods, war, conclusion"},
    "a soul to keep": {"spice_rating": 5, "tropes": "monster romance, duskwalker, beauty and the beast, forced proximity, primal"},
    "a soul to heal": {"spice_rating": 4, "tropes": "monster romance, duskwalker, mental health, forced proximity, healing"},
    "a soul to touch": {"spice_rating": 4, "tropes": "monster romance, duskwalker, blind heroine, forced proximity"},
    "a soul to guide": {"spice_rating": 4, "tropes": "monster romance, duskwalker, deaf heroine, fantasy"},
    "a soul to revive": {"spice_rating": 4, "tropes": "monster romance, duskwalker, second chance"},
    "a soul to protect": {"spice_rating": 4, "tropes": "monster romance, duskwalker, fantasy"},
    "a touch of darkness": {"spice_rating": 4, "tropes": "greek mythology, hades and persephone, gods, modern fantasy, steamy"},
    "a touch of ruin": {"spice_rating": 4, "tropes": "greek mythology, hades and persephone, gods, urban fantasy"},
    "a touch of malice": {"spice_rating": 4, "tropes": "greek mythology, hades and persephone, gods, explicit open door"},
    "a touch of chaos": {"spice_rating": 4, "tropes": "greek mythology, hades and persephone, gods, war"},
    "a game of fate": {"spice_rating": 4, "tropes": "greek mythology, hades pov, gods, modern fantasy"},
    "a game of retribution": {"spice_rating": 4, "tropes": "greek mythology, hades pov, gods"},
    "a game of gods": {"spice_rating": 4, "tropes": "greek mythology, hades pov, gods, explicit open door"},
    "a deal with the elf king": {"spice_rating": 2, "tropes": "fantasy romance, elves, arranged marriage, seasonal magic, slow burn"},
    "a dance with the fae prince": {"spice_rating": 2, "tropes": "fantasy romance, fae, cinderella retelling, magic, slow burn"},
    "a duel with the vampire lord": {"spice_rating": 3, "tropes": "fantasy romance, vampires, enemies to lovers, hunters"},
    "a demon's guide to wooing a witch": {"spice_rating": 3, "tropes": "paranormal romance, romantic comedy, witches, demons, grumpy sunshine"},
    "a witch's guide to fake dating a demon": {"spice_rating": 3, "tropes": "paranormal romance, fake dating, witches, demons, romantic comedy"},
    "a sensual summoning": {"spice_rating": 4, "tropes": "demons, paranormal romance, summoning, forced proximity, steamy"},
    "a shadow crown": {"spice_rating": 3, "tropes": "fantasy romance, assassin, rebellion, slow burn, indigenous representation"},
    "a rivalry of hearts": {"spice_rating": 2, "tropes": "fae, enemies to lovers, romantic fantasy, rivals"},
    "a touch of poison": {"spice_rating": 3, "tropes": "fantasy romance, romantic suspense, assassins, court intrigue"},
    "a vicious game": {"spice_rating": 3, "tropes": "fantasy romance, political intrigue, rebellion, slow burn"},
    "harvest season": {"spice_rating": 4, "tropes": "dark romance, thriller, suspense, autumn"},
    "the serpent and the wings of night": {"spice_rating": 3, "tropes": "vampires, deadly tournament, enemies to lovers, slow burn"},
    "the ashes and the star-cursed king": {"spice_rating": 4, "tropes": "vampires, enemies to lovers, war, royalty, political intrigue"},
    "six scorched roses": {"spice_rating": 3, "tropes": "novella, vampires, beauty and the beast, forced proximity"},
    "slaying the vampire conqueror": {"spice_rating": 4, "tropes": "vampires, assassin, enemies to lovers, high tension"},
    "the songbird & the heart of stone": {"spice_rating": 3, "tropes": "vampires, underworld, quest, fantasy romance"},
    "the knight and the moth": {"spice_rating": 3, "tropes": "gothic fantasy, dark romance, magic, mystery"},
    "one dark window": {"spice_rating": 2, "tropes": "gothic fantasy romance, magic cards, monster in head, slow burn"},
    "two twisted crowns": {"spice_rating": 3, "tropes": "gothic fantasy, dark romance, magic, royalty"},
    "haunting adeline": {"spice_rating": 5, "tropes": "dark romance, stalker, vigilante, explicit open door, morally grey"},
    "hunting adeline": {"spice_rating": 5, "tropes": "dark romance, trauma recovery, explicit open door, revenge"},
    "does it hurt": {"spice_rating": 4, "tropes": "dark romance, lighthouse, enemies to lovers, forced proximity, survival"},
    "icebreaker": {"spice_rating": 4, "tropes": "sports romance, college, hockey, figure skating, forced proximity"},
    "wildfire": {"spice_rating": 4, "tropes": "contemporary romance, summer camp, sports romance, secret romance"},
    "daydream": {"spice_rating": 4, "tropes": "sports romance, college, hockey, tutor, slow burn"},
    "butcher & blackbird": {"spice_rating": 4, "tropes": "dark romantic comedy, serial killers, friends to lovers, spicy"},
    "leather & lark": {"spice_rating": 4, "tropes": "dark romance, contract killer, arranged marriage, spicy"},
    "scythe & sparrow": {"spice_rating": 4, "tropes": "dark romance, mafia, suspense, spicy"},
    "twisted love": {"spice_rating": 4, "tropes": "contemporary romance, brother's best friend, grumpy sunshine, billionaire"},
    "twisted games": {"spice_rating": 4, "tropes": "royal romance, bodyguard, forbidden love, slow burn"},
    "twisted hate": {"spice_rating": 4, "tropes": "enemies to lovers, forced proximity, medical romance, high heat"},
    "twisted lies": {"spice_rating": 4, "tropes": "fake dating, billionaire romance, slow burn, stalker hero"},
    "king of wrath": {"spice_rating": 4, "tropes": "billionaire romance, arranged marriage, enemies to lovers, forced proximity"},
    "king of pride": {"spice_rating": 4, "tropes": "billionaire romance, opposites attract, forbidden, slow burn"},
    "king of greed": {"spice_rating": 4, "tropes": "billionaire romance, marriage in crisis, second chance"},
    "king of sloth": {"spice_rating": 4, "tropes": "billionaire romance, bodyguard, opposites attract"},
    "the fine print": {"spice_rating": 4, "tropes": "billionaire romance, theme park, grumpy sunshine, workplace"},
    "terms and conditions": {"spice_rating": 4, "tropes": "billionaire romance, marriage of convenience, boss employee"},
    "final offer": {"spice_rating": 4, "tropes": "second chance romance, billionaire romance, small town"},
    "the love hypothesis": {"spice_rating": 3, "tropes": "contemporary romance, fake dating, stem, grumpy sunshine"},
    "love on the brain": {"spice_rating": 3, "tropes": "contemporary romance, stem, nasa, rivals to lovers"},
    "love, theoretically": {"spice_rating": 3, "tropes": "contemporary romance, stem, rivals to lovers, fake dating"},
    "bride": {"spice_rating": 4, "tropes": "paranormal romance, werewolf, vampire, arranged marriage, fated mates"},
    "not in love": {"spice_rating": 4, "tropes": "contemporary romance, forbidden love, rivals, spicy"},
    "book lovers": {"spice_rating": 3, "tropes": "contemporary romance, rivals to lovers, small town, books, comedy"},
    "beach read": {"spice_rating": 3, "tropes": "contemporary romance, rivals to lovers, authors, summer"},
    "people we meet on vacation": {"spice_rating": 2, "tropes": "friends to lovers, vacation, slow burn"},
    "funny story": {"spice_rating": 3, "tropes": "contemporary romance, fake dating, opposites attract, summer"},
    "assistant to the villain": {"spice_rating": 2, "tropes": "cozy fantasy romance, workplace comedy, villain boss, slow burn"},
    "apprentice to the villain": {"spice_rating": 2, "tropes": "cozy fantasy romance, workplace comedy, villain boss"},
    "powerless": {"spice_rating": 2, "tropes": "ya romantasy, deadly trials, rivals to lovers, slow burn"},
    "reckless": {"spice_rating": 3, "tropes": "ya romantasy, enemies to lovers, road trip, forbidden"},
    "fearless": {"spice_rating": 3, "tropes": "ya romantasy, rebellion, slow burn"},
    "lights out": {"spice_rating": 4, "tropes": "dark romance, masked man, voyeurism, spicy"},
    "game on": {"spice_rating": 4, "tropes": "dark romance, spicy, romantic comedy"},
    "diamond dust": {"spice_rating": 3, "tropes": "urban fantasy, paranormal romance, magic, shapeshifters"},
    "rebel witch": {"spice_rating": 2, "tropes": "fantasy romance, witches, enemies to lovers, young adult"},
    "heartless hunter": {"spice_rating": 2, "tropes": "fantasy romance, witches, enemies to lovers, young adult"},
    "the sol crown": {"spice_rating": 4, "tropes": "enemies to lovers, fantasy romance, magic, royalty, forced proximity"},
    "anathema": {"spice_rating": 4, "tropes": "dark romance, fantasy, gothic, enemies to lovers"},
    "atonement of the spine cleaver": {"spice_rating": 4, "tropes": "fantasy romance, enemies to lovers, slow burn, forced proximity"},
    "the coven": {"spice_rating": 4, "tropes": "fantasy romance, witches, enemies to lovers, dark romance"},
    "the cursed": {"spice_rating": 4, "tropes": "fantasy romance, witches, enemies to lovers, dark romance"},
    "the ever king": {"spice_rating": 3, "tropes": "romantasy, fantasy, romance, adventure, fae"},
    "the ex hex": {"spice_rating": 3, "tropes": "paranormal romance, witches, small town, second chance, cozy fantasy"},
    "gild": {"spice_rating": 3, "tropes": "fantasy romance, fae, king midas retelling, trauma recovery"},
    "glint": {"spice_rating": 4, "tropes": "fantasy romance, enemies to lovers, slow burn, fae"},
    "gleam": {"spice_rating": 4, "tropes": "fantasy romance, fae, magic, rebellion"},
    "glow": {"spice_rating": 4, "tropes": "fantasy romance, fae, war, high spice"},
    "gold": {"spice_rating": 4, "tropes": "fantasy romance, fae, high fantasy"},
    "goldfinch": {"spice_rating": 4, "tropes": "fantasy romance, fae, series finale"},
    "the bridge kingdom": {"spice_rating": 4, "tropes": "fantasy romance, enemies to lovers, forced proximity, spies"},
    "the traitor queen": {"spice_rating": 3, "tropes": "fantasy romance, enemies to lovers, forced proximity, high fantasy"},
    "the inadequate heir": {"spice_rating": 3, "tropes": "romantasy, fantasy, enemies to lovers, hidden identity, royalty"},
    "the endless war": {"spice_rating": 3, "tropes": "fantasy, romance, war, adventure, magic"},
    "the book of azrael": {"spice_rating": 4, "tropes": "fantasy romance, enemies to lovers, gods, morally grey"},
    "rhapsodic": {"spice_rating": 4, "tropes": "fantasy romance, siren, soulmates, bargainer"},
    "the shadows between us": {"spice_rating": 2, "tropes": "fantasy, young adult, enemies to lovers, royalty, ambition"},
    "the ballad of never after": {"spice_rating": 1, "tropes": "fantasy, romance, young adult, magic, cursed"},
    "what hunts inside the shadows": {"spice_rating": 4, "tropes": "dark fantasy, romance, vampires, enemies to lovers, magic"},
    "what sleeps within the cove": {"spice_rating": 4, "tropes": "dark fantasy, romance, witches, magic, suspense"},
    "viciously yours": {"spice_rating": 4, "tropes": "fantasy, fae, monster romance, fated mates, humor"}
}


def clean_book_query_info(title: str, author: str = ""):
    t = re.sub(r"^(?:_?oceanofpdf\.com_?|\[?audiobookbay(?:\.lu|\.nl)?\]?[-_ ]*)\s*", "", title or "", flags=re.IGNORECASE)
    if "\\" in t or "/" in t:
        t = re.split(r"[\\/]", t)[-1]
        t = re.sub(r"\.(?:epub|pdf|mobi|azw3|m4b|mp3)$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\(z-library.*?\)", "", t, flags=re.IGNORECASE)
    a = (author or "").strip()
    if (" - " in t or " by " in t.lower()) and (not a or "unknown" in a.lower()):
        if " - " in t:
            parts = t.split(" - ")
            t, a = parts[0].strip(), parts[1].strip()
        elif " by " in t.lower():
            parts = re.split(r"\s+by\s+", t, flags=re.IGNORECASE)
            t, a = parts[0].strip(), parts[1].strip()

    clean_t = re.sub(r"[:\(\[].*", "", t).strip()
    clean_a = re.sub(r"[\(\[].*", "", a).strip()
    return (clean_t if clean_t else t.strip()), clean_a


def safe_parse_json_dict_or_list(raw_text: str):
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if m_block:
        cleaned = m_block.group(1).strip()
    m_json = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
    if m_json:
        cleaned = m_json.group(1).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            for k in ["books", "items", "results", "data"]:
                if k in data and isinstance(data[k], list):
                    return data[k]
        return data
    except Exception:
        try:
            return json.loads(raw_text.strip())
        except Exception:
            return None


def match_romance_io_cache(title: str) -> Optional[dict]:
    clean_t, _ = clean_book_query_info(title)
    norm_t = re.sub(r"[^a-z0-9]", "", clean_t.lower())
    if not norm_t:
        return None
    for k, v in POPULAR_ROMANCE_IO_CACHE.items():
        norm_k = re.sub(r"[^a-z0-9]", "", k.lower())
        if norm_k == norm_t or norm_t.startswith(norm_k) or (len(norm_k) >= 6 and norm_k in norm_t):
            return {"spice_rating": v["spice_rating"], "tropes": v["tropes"]}
    return None


def lookup_romance_io_spice(title: str, author: str = "") -> dict:
    clean_t, clean_a = clean_book_query_info(title, author)

    # 1. Quick check against offline Popular Romance.io Cache
    cached = match_romance_io_cache(clean_t)
    if cached:
        return cached

    # 2. Query Gemini with robust fallback models
    prompt = f"""
You are a Romantasy and Romance novel expert specializing in Romance.io ratings.
What is the official Romance.io spice / steam rating (integer from 1 to 5) and key tropes for:
Book: "{clean_t}" by {clean_a}
Scale:
1: Glimpses / Clean
2: Behind closed doors / Warm
3: Open door / Steamy
4: Explicit open door / Very steamy
5: Explicit and plentiful / Ultra spicy
(If non-romance, assign spice_rating: 0 and genre as tropes).

Return ONLY JSON:
{{"spice_rating": 4, "tropes": "enemies to lovers, dragons, fantasy"}}
"""
    raw_text = call_gemini_api(prompt, json_mode=True, temperature=0.1)
    if raw_text:
        parsed = safe_parse_json_dict_or_list(raw_text)
        if isinstance(parsed, dict):
            return {
                "spice_rating": max(0, min(5, int(parsed.get("spice_rating") or 0))),
                "tropes": str(parsed.get("tropes") or "").strip()
            }

    return {"spice_rating": 0, "tropes": ""}


def batch_lookup_romance_io_spice(books_chunk: list[dict]) -> dict[int, dict]:
    if not books_chunk:
        return {}

    results = {}
    pending_books = []

    # 1. Check local cache first
    for b in books_chunk:
        clean_t, clean_a = clean_book_query_info(b.get("title", ""), b.get("author", ""))
        cached = match_romance_io_cache(clean_t)
        if cached:
            results[b["id"]] = cached
        else:
            pending_books.append({"id": b["id"], "title": clean_t, "author": clean_a})

    if not pending_books:
        return results

    # 2. Query Gemini for the remainder
    prompt = """
For each romance, fantasy, or general book in the list below, assign its official Romance.io spice / steam rating from 1 to 5 and its main tropes/genres.
Spice scale:
1: Glimpses / Clean
2: Behind closed doors / Warm
3: Open door / Steamy
4: Explicit open door / Very steamy
5: Explicit and plentiful / Ultra spicy
(If non-romance, e.g. non-fiction/guide/crochet, assign spice_rating: 0 and genre as tropes).

Books:
""" + "\n".join([f"- ID {b['id']}: \"{b['title']}\" by {b.get('author', '')}" for b in pending_books]) + """

Return ONLY a JSON array of objects:
[
  {"id": 1, "spice_rating": 3, "tropes": "fantasy, enemies to lovers"}
]
"""
    raw_text = call_gemini_api(prompt, json_mode=True, temperature=0.1)
    if raw_text:
        items = safe_parse_json_dict_or_list(raw_text)
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and 'id' in it:
                    results[int(it['id'])] = {
                        "spice_rating": max(0, min(5, int(it.get('spice_rating') or 0))),
                        "tropes": str(it.get('tropes') or "").strip()
                    }

    return results


def generate_external_oracle_recommendation(vibes: list[str], owned_titles_lower: set[str], media_type: str = "any", spice_min: int = 0) -> dict:
    vibe_str = ", ".join(vibes) if vibes else "captivating romantasy, enemies to lovers, high spice"
    prompt = f"""
You are the Fates Oracle, a mystical book matchmaker for a Romantasy & Romance lover.
The user is looking for a book with these vibes/tropes: {vibe_str}.
Format preference: {media_type}. Minimum desired Romance.io spice level: {spice_min} / 5.

CRITICAL: The user has rejected multiple books from their library and wants an exciting recommendation of a popular, highly rated Romantasy or Romance book that is NOT in their current library.
Do NOT recommend any book from this list of books they already own:
{', '.join(list(owned_titles_lower)[:140])}

Pick ONE exceptional, widely loved book matching these vibes that they do NOT own.
Provide:
1. "title": Exact book title
2. "author": Author name
3. "spice_rating": Romance.io spice rating (integer 1 to 5)
4. "tropes": Key tropes (e.g. enemies to lovers, dark fantasy, forced proximity)
5. "pitch": A compelling 1-2 sentence hook/pitch for why they will be obsessed with it
6. "reginald_oracle_commentary": In character as Reginald the wise, book-loving goose (use "Honk!"), explaining why the Fates summoned this specific destiny card for them.

Return ONLY a JSON object:
{{
  "title": "...",
  "author": "...",
  "spice_rating": 4,
  "tropes": "...",
  "pitch": "...",
  "reginald_oracle_commentary": "Honk! The Fates..."
}}
"""
    raw_text = call_gemini_api(prompt, json_mode=True, temperature=0.7)
    if raw_text:
        try:
            rec = json.loads(raw_text)
            rec["in_library"] = False
            return rec
        except Exception:
            pass

    # Fallback if Gemini unavailable
    fallback_pool = [
        {
            "title": "A Fate Inked in Blood",
            "author": "Danielle L. Jensen",
            "spice_rating": 4,
            "tropes": "viking fantasy, shield maiden, forced proximity, forbidden love, magic",
            "pitch": "A shield maiden bound by blood to a dangerous warrior must navigate brutal gods and an all-consuming passion.",
            "reginald_oracle_commentary": "Honk! The Fates have cut through the mist to bring you a Nordic storm of war, magic, and undeniable heat! This will set your reading soul ablaze.",
            "in_library": False
        },
        {
            "title": "Gothikana",
            "author": "RuNyx",
            "spice_rating": 4,
            "tropes": "dark academia, gothic romance, mystery, forbidden romance, morally grey",
            "pitch": "At an enigmatic castle academy in the mountains, an outcast student and an enigmatic professor unravel lethal secrets and forbidden longing.",
            "reginald_oracle_commentary": "Honk! The Fates gaze into the gothic shadows and demand you read this dark, brooding mystery wrapped in sinful tension.",
            "in_library": False
        },
        {
            "title": "Quicksilver",
            "author": "Callie Hart",
            "spice_rating": 4,
            "tropes": "fae romance, enemies to lovers, desert fantasy, slow burn, dangerous magic",
            "pitch": "An immortal fae warlord and a fierce thief cross swords and sparks in a lethal desert kingdom.",
            "reginald_oracle_commentary": "Honk! The Fates have woven pure desert lightning and fae fury into this one. Prepare for high octane tension!",
            "in_library": False
        }
    ]
    for b in fallback_pool:
        if b["title"].lower().strip() not in owned_titles_lower:
            return b
    return fallback_pool[0]


def sanitize_filename(name: str, ext: str) -> str:
    cleaned = name.strip()
    cleaned = re.sub(r"^(?:_?oceanofpdf\.com_?|\[?audiobookbay(?:\.lu|\.nl)?\]?[-_ ]*)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", cleaned).strip()
    if not cleaned:
        cleaned = "book"
    if ext and not cleaned.lower().endswith(ext.lower()):
        cleaned = f"{cleaned}{ext}"
    return cleaned


SELECT_COLS = """
    id, title, author, filename, description, isbn, cover_url, published_year,
    source, series_name, series_number, is_read, reading_status, rating, review,
    date_read, media_type, narrator, duration,
    review_headline, favorite_quotes, favorite_characters, spice_rating, pace, tropes,
    page_count, current_page, progress_percent, genres, deleted_at, current_audio_minutes
"""


def row_to_book(row) -> dict:
    filename = row[3] or ""
    is_read = bool(row[11]) if row[11] is not None else False
    reading_status = row[12] or ("read" if is_read else "unread")
    raw_media = row[16] if len(row) > 16 and row[16] else ""
    media_type = detect_media_type(filename, raw_media)
    return {
        "id": row[0],
        "title": row[1],
        "author": row[2],
        "filename": filename,
        "has_file": bool(filename.strip()),
        "description": row[4] or "",
        "isbn": row[5] or "",
        "cover_url": row[6] or "",
        "published_year": row[7] or "",
        "source": row[8] or "",
        "series_name": row[9] or "",
        "series_number": row[10] or "",
        "is_read": is_read,
        "reading_status": reading_status,
        "rating": int(row[13] or 0),
        "review": row[14] or "",
        "date_read": row[15] or "",
        "media_type": media_type,
        "narrator": (row[17] if len(row) > 17 and row[17] else ""),
        "duration": (row[18] if len(row) > 18 and row[18] else ""),
        "review_headline": (row[19] if len(row) > 19 and row[19] else ""),
        "favorite_quotes": (row[20] if len(row) > 20 and row[20] else ""),
        "favorite_characters": (row[21] if len(row) > 21 and row[21] else ""),
        "spice_rating": int(row[22] or 0) if len(row) > 22 and row[22] is not None else 0,
        "pace": (row[23] if len(row) > 23 and row[23] else ""),
        "tropes": (row[24] if len(row) > 24 and row[24] else ""),
        "page_count": int(row[25] or 0) if len(row) > 25 and row[25] is not None else 0,
        "current_page": int(row[26] or 0) if len(row) > 26 and row[26] is not None else 0,
        "progress_percent": int(row[27] or 0) if len(row) > 27 and row[27] is not None else 0,
        "genres": (row[28] if len(row) > 28 and row[28] else ""),
        "deleted_at": (row[29] if len(row) > 29 and row[29] else ""),
        "current_audio_minutes": int(row[30] or 0) if len(row) > 30 and row[30] is not None else 0,
    }


# --- WEB FRONTEND ROUTE ---
@app.get("/", response_class=HTMLResponse)
def serve_home():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse("<h1>Book Server Running</h1><p>Visit <a href='/docs'>/docs</a> for API documentation.</p>")
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(
        content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


# --- 0. INSPECT SELECTED EPUB/AUDIO FILE ---
@app.post("/books/extract-file-metadata")
async def extract_file_metadata_endpoint(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    media_type = detect_media_type(file.filename or "")
    embedded = {
        "title": "",
        "author": "",
        "description": "",
        "isbn": "",
        "published_year": "",
        "series_name": "",
        "series_number": "",
    }
    if ext == ".epub":
        raw_bytes = await file.read()
        embedded = extract_epub_metadata(raw_bytes)

    if embedded["title"] and embedded["author"]:
        suggested_query = f"{embedded['title']} {embedded['author']}"
    elif embedded["title"]:
        suggested_query = embedded["title"]
    elif embedded["isbn"]:
        suggested_query = embedded["isbn"]
    else:
        suggested_query = clean_search_query_from_filename(file.filename or "")

    return {
        "embedded": embedded,
        "media_type": media_type,
        "suggested_query": suggested_query
    }


# --- 1. PREVIEW ONLINE METADATA ---
@app.get("/books/lookup-online")
def lookup_online(q: str, source: str = "all"):
    results = search_online_metadata_candidates(q, source=source, limit=8)
    if not results:
        raise HTTPException(status_code=404, detail="No matching books found online.")
    for item in results:
        cached = match_romance_io_cache(item.get("title", ""))
        if cached:
            item["spice_rating"] = cached.get("spice_rating", 0)
            item["tropes"] = cached.get("tropes", "")
        else:
            item["spice_rating"] = 0
            item["tropes"] = ""
    return {
        "found": results[0],
        "results": results
    }


@app.get("/books/lookup-romance-io")
def lookup_romance_io_endpoint(title: str = "", author: str = ""):
    clean_t, clean_a = clean_book_query_info(title, author)
    spice_data = lookup_romance_io_spice(clean_t, clean_a)
    romance_url = f"https://www.romance.io/search?query={urllib.parse.quote_plus((clean_t + ' ' + clean_a).strip())}"
    return {
        "status": "success",
        "title": clean_t,
        "author": clean_a,
        "spice_rating": spice_data.get("spice_rating", 0),
        "tropes": spice_data.get("tropes", ""),
        "romance_io_url": romance_url
    }


def extract_filename_from_url_response(res, url: str) -> str:
    cd = res.headers.get("content-disposition", "")
    if cd:
        fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd, re.IGNORECASE)
        if fname_match:
            return urllib.parse.unquote(fname_match.group(1).strip())
    parsed = urllib.parse.urlparse(url)
    base = os.path.basename(parsed.path)
    if base and "." in base:
        return urllib.parse.unquote(base)
    ctype = res.headers.get("content-type", "").lower()
    ext = ".epub"
    if "audio" in ctype or "mp3" in ctype or "m4a" in ctype or "m4b" in ctype:
        ext = ".mp3"
    elif "pdf" in ctype:
        ext = ".pdf"
    return f"imported_book_{int(time.time())}{ext}"


def save_book_bytes_to_catalog(
    file_bytes: bytes,
    original_filename: str,
    lookup_query: str = "",
    metadata_source: str = "all",
    custom_filename: Optional[str] = None,
    media_type_override: Optional[str] = None,
    title_override: Optional[str] = None,
    author_override: Optional[str] = None,
    narrator_override: Optional[str] = None,
    duration_override: Optional[str] = None,
    description_override: Optional[str] = None,
    isbn_override: Optional[str] = None,
    cover_url_override: Optional[str] = None,
    published_year_override: Optional[str] = None,
    series_name_override: Optional[str] = None,
    series_number_override: Optional[str] = None,
    reading_status_override: Optional[str] = "tbr",
    source_override: Optional[str] = None,
    spice_rating_override: Optional[int] = None,
    tropes_override: Optional[str] = None,
    skip_if_exists: bool = False,
    auto_rename_if_exists: bool = False,
) -> dict:
    ext = os.path.splitext(original_filename or "")[1]
    media_type = detect_media_type(original_filename or "", media_type_override)
    embedded = extract_epub_metadata(file_bytes) if ext.lower() == ".epub" else {}

    search_q = (
        lookup_query.strip()
        or (f"{embedded.get('title', '')} {embedded.get('author', '')}".strip())
        or clean_search_query_from_filename(original_filename or "")
    )

    effective_source = "amazon" if (media_type == "audiobook" and metadata_source == "all") else metadata_source
    needs_lookup = not (title_override and author_override and cover_url_override)
    metadata = (
        fetch_online_metadata(search_q, source=effective_source)
        if (needs_lookup and search_q)
        else None
    )

    default_title = clean_search_query_from_filename(original_filename or "Untitled")
    title = (
        title_override
        or (metadata["title"] if metadata else "")
        or embedded.get("title", "")
        or default_title
    ).strip()
    author = (
        author_override
        or (metadata["author"] if metadata else "")
        or embedded.get("author", "")
        or "Unknown Author"
    ).strip()
    narrator = (
        narrator_override
        if narrator_override is not None and narrator_override != ""
        else (metadata.get("narrator", "") if metadata else "")
    ).strip()
    duration = (
        duration_override
        if duration_override is not None and duration_override != ""
        else (metadata.get("duration", "") if metadata else "")
    ).strip()
    description = (
        description_override
        if description_override
        else ((metadata["description"] if metadata and metadata.get("description") else "") or embedded.get("description", ""))
    ).strip()
    isbn = (
        isbn_override
        if isbn_override
        else ((metadata["isbn"] if metadata and metadata.get("isbn") else "") or embedded.get("isbn", ""))
    ).strip()
    cover_url = (
        cover_url_override
        if cover_url_override
        else (metadata["cover_url"] if metadata else "")
    ).strip()
    published_year = (
        published_year_override
        if published_year_override
        else ((metadata.get("published_year", "") if metadata and metadata.get("published_year") else "") or embedded.get("published_year", ""))
    ).strip()
    series_name = (
        series_name_override
        if series_name_override is not None and series_name_override != ""
        else ((metadata.get("series_name", "") if metadata else "") or embedded.get("series_name", ""))
    ).strip()
    series_number = (
        series_number_override
        if series_number_override is not None and series_number_override != ""
        else ((metadata.get("series_number", "") if metadata else "") or embedded.get("series_number", ""))
    ).strip()
    source_label = (
        source_override
        or (metadata.get("source", "") if metadata else ("EPUB Embedded" if embedded.get("title") else ""))
    ).strip()

    status_val = (reading_status_override or "tbr").strip()
    if status_val == "unread":
        status_val = "tbr"
    is_read_val = 1 if status_val == "read" else 0
    date_read_val = datetime.date.today().isoformat() if is_read_val else ""

    if custom_filename and custom_filename.strip():
        target_name = sanitize_filename(custom_filename, ext)
    else:
        target_name = sanitize_filename(original_filename or f"book{ext}", ext)

    file_path = os.path.join(STORAGE_DIR, target_name)
    if os.path.exists(file_path):
        if skip_if_exists:
            return {
                "status": "skipped",
                "message": f"File '{target_name}' already exists in storage.",
                "book_id": None,
                "saved_filename": target_name,
                "populated_metadata": {
                    "id": None,
                    "title": title,
                    "author": author,
                    "filename": target_name,
                    "media_type": media_type
                }
            }
        elif auto_rename_if_exists:
            base, ext_part = os.path.splitext(target_name)
            counter = 1
            while os.path.exists(os.path.join(STORAGE_DIR, f"{base}_{counter}{ext_part}")):
                counter += 1
            target_name = f"{base}_{counter}{ext_part}"
            file_path = os.path.join(STORAGE_DIR, target_name)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"File '{target_name}' already exists in storage. Choose a different custom filename."
            )

    with open(file_path, "wb") as buffer:
        buffer.write(file_bytes)

    # Auto-lookup Romance.io spice rating & tropes if not explicitly provided
    if spice_rating_override is not None and int(spice_rating_override) > 0:
        spice_val = max(0, min(5, int(spice_rating_override)))
        tropes_val = (tropes_override or "").strip()
    else:
        spice_info = lookup_romance_io_spice(title, author)
        spice_val = spice_info.get("spice_rating", 0)
        tropes_val = (tropes_override or spice_info.get("tropes", "")).strip()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Check if there is already a file-less TBR entry for this book
    cursor.execute("""
        SELECT id, reading_status, is_read FROM books
        WHERE (filename IS NULL OR filename = '')
          AND (LOWER(title) = LOWER(?) OR (isbn != '' AND isbn = ?))
        LIMIT 1
    """, (title, isbn))
    existing_tbr = cursor.fetchone()

    if existing_tbr:
        book_id = existing_tbr[0]
        keep_status = existing_tbr[1] or "tbr"
        keep_read = existing_tbr[2] or 0
        cursor.execute("""
            UPDATE books
            SET title = ?, author = ?, filename = ?, description = ?, isbn = ?,
                cover_url = ?, published_year = ?, source = ?, series_name = ?,
                series_number = ?, is_read = ?, reading_status = ?,
                media_type = ?, narrator = ?, duration = ?,
                spice_rating = CASE WHEN ? > 0 THEN ? ELSE spice_rating END,
                tropes = CASE WHEN ? != '' AND (tropes IS NULL OR tropes = '') THEN ? ELSE tropes END
            WHERE id = ?
        """, (
            title, author, target_name, description, isbn,
            cover_url, published_year, source_label, series_name,
            series_number, keep_read, keep_status,
            media_type, narrator, duration,
            spice_val, spice_val, tropes_val, tropes_val, book_id
        ))
    else:
        cursor.execute("""
            INSERT INTO books (
                title, author, filename, description, isbn, cover_url, published_year,
                source, series_name, series_number, is_read, reading_status, date_read,
                media_type, narrator, duration, spice_rating, tropes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title, author, target_name, description, isbn, cover_url, published_year,
            source_label, series_name, series_number, is_read_val, status_val, date_read_val,
            media_type, narrator, duration, spice_val, tropes_val
        ))
        book_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "status": "Book uploaded and metadata populated!",
        "book_id": book_id,
        "saved_filename": target_name,
        "populated_metadata": {
            "id": book_id,
            "title": title,
            "author": author,
            "filename": target_name,
            "media_type": media_type,
            "narrator": narrator,
            "duration": duration,
            "description": description,
            "isbn": isbn,
            "cover_url": cover_url,
            "published_year": published_year,
            "series_name": series_name,
            "series_number": series_number,
            "source": source_label,
            "spice_rating": spice_val,
            "tropes": tropes_val
        }
    }


# --- 2. SMART UPLOAD (Ebook or Audiobook File) ---
@app.post("/books/upload-smart")
async def upload_smart(
    lookup_query: str = Form(""),
    metadata_source: str = Form("all"),
    custom_filename: Optional[str] = Form(None),
    media_type_override: Optional[str] = Form(None),
    title_override: Optional[str] = Form(None),
    author_override: Optional[str] = Form(None),
    narrator_override: Optional[str] = Form(None),
    duration_override: Optional[str] = Form(None),
    description_override: Optional[str] = Form(None),
    isbn_override: Optional[str] = Form(None),
    cover_url_override: Optional[str] = Form(None),
    published_year_override: Optional[str] = Form(None),
    series_name_override: Optional[str] = Form(None),
    series_number_override: Optional[str] = Form(None),
    reading_status_override: Optional[str] = Form("tbr"),
    source_override: Optional[str] = Form(None),
    spice_rating: Optional[int] = Form(None),
    tropes: Optional[str] = Form(None),
    skip_if_exists: bool = Form(False),
    auto_rename_if_exists: bool = Form(False),
    file: UploadFile = File(...)
):
    file_bytes = await file.read()
    return save_book_bytes_to_catalog(
        file_bytes=file_bytes,
        original_filename=file.filename or "book.epub",
        lookup_query=lookup_query,
        metadata_source=metadata_source,
        custom_filename=custom_filename,
        media_type_override=media_type_override,
        title_override=title_override,
        author_override=author_override,
        narrator_override=narrator_override,
        duration_override=duration_override,
        description_override=description_override,
        isbn_override=isbn_override,
        cover_url_override=cover_url_override,
        published_year_override=published_year_override,
        series_name_override=series_name_override,
        series_number_override=series_number_override,
        reading_status_override=reading_status_override,
        source_override=source_override,
        spice_rating_override=spice_rating,
        tropes_override=tropes,
        skip_if_exists=skip_if_exists,
        auto_rename_if_exists=auto_rename_if_exists,
    )


# --- 2B. IMPORT BOOK FROM WEB URL ---
class ImportUrlPayload(BaseModel):
    url: str
    media_type: Optional[str] = None
    lookup_query: Optional[str] = None
    reading_status: Optional[str] = "tbr"


@app.post("/books/import-url")
def import_book_from_url(payload: ImportUrlPayload):
    url = payload.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid URL. Must begin with http:// or https://")

    try:
        res = requests.get(url, headers=BROWSER_HEADERS, timeout=90, stream=True)
        if not res.ok:
            raise HTTPException(status_code=400, detail=f"Failed to download file from URL (HTTP {res.status_code})")

        filename = extract_filename_from_url_response(res, url)
        file_bytes = res.content
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Downloaded file was empty.")

        res_dict = save_book_bytes_to_catalog(
            file_bytes=file_bytes,
            original_filename=filename,
            lookup_query=payload.lookup_query or "",
            media_type_override=payload.media_type,
            reading_status_override=payload.reading_status or "unread",
            auto_rename_if_exists=True,
        )
        return {
            "message": f"Successfully imported '{res_dict['populated_metadata']['title']}'!",
            "result": res_dict
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import error: {str(e)}")


# --- 2C. AUTO-IMPORT DROP INBOX FOLDER ---
@app.get("/books/inbox-status")
def get_inbox_status():
    files = []
    if os.path.exists(INBOX_DIR):
        for fname in os.listdir(INBOX_DIR):
            fpath = os.path.join(INBOX_DIR, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                mtype = "audiobook" if ext in AUDIO_EXTENSIONS else "ebook"
                size = os.path.getsize(fpath)
                files.append({
                    "filename": fname,
                    "size": size,
                    "media_type": mtype,
                    "clean_title": clean_search_query_from_filename(fname)
                })
    return {
        "inbox_path": INBOX_DIR,
        "total_files": len(files),
        "files": files
    }


@app.post("/books/scan-inbox")
def scan_and_import_inbox():
    imported = []
    skipped = []
    errors = []

    if not os.path.exists(INBOX_DIR):
        return {"imported": [], "skipped": [], "errors": [], "message": "Inbox folder is empty."}

    for fname in sorted(os.listdir(INBOX_DIR)):
        fpath = os.path.join(INBOX_DIR, fname)
        if not os.path.isfile(fpath):
            continue

        ext = os.path.splitext(fname)[1].lower()
        if ext not in {".epub", ".pdf", ".mobi", ".azw3", ".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus"}:
            continue

        try:
            with open(fpath, "rb") as f:
                file_bytes = f.read()

            result = save_book_bytes_to_catalog(
                file_bytes=file_bytes,
                original_filename=fname,
                skip_if_exists=True
            )

            if result.get("status") == "skipped":
                skipped.append(fname)
            else:
                imported.append({
                    "filename": fname,
                    "title": result["populated_metadata"]["title"],
                    "author": result["populated_metadata"]["author"],
                    "media_type": result["populated_metadata"]["media_type"]
                })
                try:
                    os.remove(fpath)
                except Exception:
                    pass
        except Exception as e:
            errors.append({"filename": fname, "error": str(e)})

    return {
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "errors_count": len(errors),
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "message": f"Processed drop folder: {len(imported)} imported, {len(skipped)} skipped, {len(errors)} errors."
    }


# --- 2B. ADD BOOK WITHOUT A FILE (TBR / Wishlist) ---
class AddBookWithoutFilePayload(BaseModel):
    title: str
    author: str = "Unknown Author"
    description: str = ""
    isbn: str = ""
    cover_url: str = ""
    published_year: str = ""
    series_name: str = ""
    series_number: str = ""
    source: str = ""
    reading_status: str = "tbr"
    rating: int = 0
    review: str = ""
    media_type: str = "ebook"
    narrator: str = ""
    duration: str = ""
    spice_rating: Optional[int] = 0
    tropes: Optional[str] = ""



# --- SERIES OVERRIDE ENDPOINTS ---
class SeriesOverridePayload(BaseModel):
    series_name: str
    next_number: str
    next_title: str
    author: Optional[str] = ""


@app.post("/series/override")
def set_series_override(payload: SeriesOverridePayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO series_overrides (series_name, next_number, next_title, author)
        VALUES (?, ?, ?, ?)
    """, (payload.series_name.strip(), payload.next_number.strip(), payload.next_title.strip(), (payload.author or "").strip()))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Updated next book for {payload.series_name}!"}


@app.delete("/series/override/{series_name}")
def delete_series_override(series_name: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM series_overrides WHERE LOWER(series_name) = LOWER(?)", (series_name.strip(),))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Cleared override for {series_name}"}


class SeriesRenamePayload(BaseModel):
    old_name: str
    new_name: str


@app.post("/series/rename")
def rename_series(payload: SeriesRenamePayload):
    old_name = payload.old_name.strip()
    new_name = payload.new_name.strip()
    if not old_name or not new_name:
        raise HTTPException(status_code=400, detail="Series names cannot be empty")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE books SET series_name = ? WHERE LOWER(series_name) = LOWER(?)", (new_name, old_name))
    count = cursor.rowcount
    cursor.execute("UPDATE series_overrides SET series_name = ? WHERE LOWER(series_name) = LOWER(?)", (new_name, old_name))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Renamed series '{old_name}' to '{new_name}' across {count} books!"}


class SeriesReorderItem(BaseModel):
    book_id: int
    series_number: str


class SeriesReorderPayload(BaseModel):
    books: list[SeriesReorderItem]


@app.post("/series/reorder")
def reorder_series_books(payload: SeriesReorderPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    for item in payload.books:
        cursor.execute("UPDATE books SET series_number = ? WHERE id = ?", (item.series_number.strip(), item.book_id))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Updated order for {len(payload.books)} books in series!"}


@app.post("/series/remove-book/{book_id}")
def remove_book_from_series(book_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE books SET series_name = '', series_number = '' WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Book #{book_id} unlinked from series."}

@app.post("/books/add-without-file")
def add_book_without_file(payload: AddBookWithoutFilePayload):
    is_read_val = 1 if payload.reading_status == "read" else 0
    date_read_val = datetime.date.today().isoformat() if is_read_val else ""

    spice_val = max(0, min(5, int(payload.spice_rating or 0)))
    tropes_val = (payload.tropes or "").strip()
    if spice_val == 0 or not tropes_val:
        auto_spice = lookup_romance_io_spice(payload.title, payload.author)
        if spice_val == 0:
            spice_val = auto_spice.get("spice_rating", 0)
        if not tropes_val:
            tropes_val = auto_spice.get("tropes", "")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO books (
            title, author, filename, description, isbn, cover_url, published_year,
            source, series_name, series_number, is_read, reading_status, rating, review,
            date_read, media_type, narrator, duration, spice_rating, tropes
        )
        VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payload.title.strip(),
        payload.author.strip() or "Unknown Author",
        payload.description.strip(),
        payload.isbn.strip(),
        payload.cover_url.strip(),
        payload.published_year.strip(),
        payload.source.strip(),
        payload.series_name.strip(),
        payload.series_number.strip(),
        is_read_val,
        payload.reading_status.strip() or "tbr",
        max(0, min(5, int(payload.rating or 0))),
        payload.review.strip(),
        date_read_val,
        payload.media_type.strip() or "ebook",
        payload.narrator.strip(),
        payload.duration.strip(),
        spice_val,
        tropes_val
    ))
    conn.commit()
    book_id = cursor.lastrowid
    conn.close()
    return {"message": "Added to your list!", "book_id": book_id, "spice_rating": spice_val, "tropes": tropes_val}


# --- 2C. ATTACH A FILE TO AN EXISTING TBR BOOK ---
@app.post("/books/{book_id}/attach-file")
async def attach_file_to_book(book_id: int, file: UploadFile = File(...)):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, filename, media_type FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Book ID not found")

    ext = os.path.splitext(file.filename or "")[1]
    target_name = sanitize_filename(file.filename or f"book_{book_id}{ext}", ext)
    file_path = os.path.join(STORAGE_DIR, target_name)
    if os.path.exists(file_path):
        conn.close()
        raise HTTPException(status_code=400, detail=f"File '{target_name}' already exists in storage.")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    detected_media = detect_media_type(target_name, row[2])
    cursor.execute(
        "UPDATE books SET filename = ?, media_type = ? WHERE id = ?",
        (target_name, detected_media, book_id)
    )
    conn.commit()
    conn.close()
    return {"message": "File attached to book!", "filename": target_name, "media_type": detected_media}


# --- 3. LIST ALL BOOKS ---
@app.get("/books")
def list_all_books(has_file: Optional[str] = None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {SELECT_COLS} FROM books WHERE (deleted_at IS NULL OR deleted_at = '') ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    books = [row_to_book(row) for row in rows]
    if has_file in ("has_file", "true", "1", "yes"):
        books = [b for b in books if b["has_file"]]
    elif has_file in ("no_file", "false", "0", "no", "wishlist"):
        books = [b for b in books if not b["has_file"]]
    return {"total_books": len(books), "books": books}


# --- 4. SEARCH LOCAL CATALOG ---
@app.get("/books/search")
def search_books(q: str = ""):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    wildcard = f"%{q}%"
    cursor.execute(f"""
        SELECT {SELECT_COLS}
        FROM books
        WHERE (deleted_at IS NULL OR deleted_at = '')
          AND (title LIKE ? OR author LIKE ? OR description LIKE ?
           OR isbn LIKE ? OR filename LIKE ? OR series_name LIKE ?
           OR review LIKE ? OR narrator LIKE ? OR review_headline LIKE ?
           OR favorite_quotes LIKE ? OR favorite_characters LIKE ? OR tropes LIKE ?)
        ORDER BY id DESC
    """, (wildcard, wildcard, wildcard, wildcard, wildcard, wildcard, wildcard, wildcard, wildcard, wildcard, wildcard, wildcard))
    rows = cursor.fetchall()
    conn.close()

    results = [row_to_book(row) for row in rows]
    return {"matches": results}


@app.get("/books/{book_id}")
def get_single_book(book_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {SELECT_COLS} FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Book not found")
    return row_to_book(row)


# --- 5. TOGGLE READ STATUS & SET READING STATUS ---
class StatusUpdatePayload(BaseModel):
    reading_status: Optional[str] = None
    is_read: Optional[bool] = None


@app.post("/books/{book_id}/status")
def update_reading_status(book_id: int, payload: StatusUpdatePayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT is_read, reading_status, date_read FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Book ID not found")

    current_read = bool(row[0])
    current_status = row[1] or "unread"
    current_date = row[2] or ""

    if payload.reading_status is not None:
        new_status = "tbr" if payload.reading_status in ["unread", ""] else payload.reading_status
        new_read = 1 if new_status == "read" else 0
    elif payload.is_read is not None:
        new_read = 1 if payload.is_read else 0
        new_status = "read" if new_read else "tbr"
    else:
        new_read = 0 if current_read else 1
        new_status = "read" if new_read else "tbr"

    new_date = (current_date or datetime.date.today().isoformat()) if new_read else ""

    cursor.execute(
        "UPDATE books SET is_read = ?, reading_status = ?, date_read = ? WHERE id = ?",
        (new_read, new_status, new_date, book_id)
    )
    conn.commit()
    conn.close()
    return {
        "book_id": book_id,
        "is_read": bool(new_read),
        "reading_status": new_status,
        "date_read": new_date
    }


# --- 5B. RATE & REVIEW A BOOK (EXTENDED) ---
class RatingReviewPayload(BaseModel):
    rating: Optional[int] = None
    review: Optional[str] = None
    review_headline: Optional[str] = None
    favorite_quotes: Optional[str] = None
    favorite_characters: Optional[str] = None
    spice_rating: Optional[int] = None
    pace: Optional[str] = None
    tropes: Optional[str] = None
    mark_as_read: Optional[bool] = None


@app.post("/books/{book_id}/review")
def update_rating_and_review(book_id: int, payload: RatingReviewPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT rating, review, review_headline, favorite_quotes, favorite_characters, spice_rating, pace, tropes, is_read, reading_status, date_read
        FROM books WHERE id = ?
    """, (book_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Book ID not found")

    rating_val = max(0, min(5, int(payload.rating))) if payload.rating is not None else (row[0] or 0)
    review_val = payload.review.strip() if payload.review is not None else (row[1] or "")
    headline_val = payload.review_headline.strip() if payload.review_headline is not None else (row[2] or "")
    quotes_val = payload.favorite_quotes.strip() if payload.favorite_quotes is not None else (row[3] or "")
    chars_val = payload.favorite_characters.strip() if payload.favorite_characters is not None else (row[4] or "")
    spice_val = max(0, min(5, int(payload.spice_rating))) if payload.spice_rating is not None else (row[5] or 0)
    pace_val = payload.pace.strip() if payload.pace is not None else (row[6] or "")
    tropes_val = payload.tropes.strip() if payload.tropes is not None else (row[7] or "")

    is_read_val = row[8] or 0
    reading_status_val = row[9] or "unread"
    date_read_val = row[10] or ""

    if payload.mark_as_read is True or (rating_val > 0 and not is_read_val):
        is_read_val = 1
        reading_status_val = "read"
        if not date_read_val:
            date_read_val = datetime.date.today().isoformat()

    cursor.execute("""
        UPDATE books
        SET rating = ?, review = ?, review_headline = ?, favorite_quotes = ?,
            favorite_characters = ?, spice_rating = ?, pace = ?, tropes = ?,
            is_read = ?, reading_status = ?, date_read = ?
        WHERE id = ?
    """, (
        rating_val, review_val, headline_val, quotes_val,
        chars_val, spice_val, pace_val, tropes_val,
        is_read_val, reading_status_val, date_read_val,
        book_id
    ))
    conn.commit()
    conn.close()
    return {
        "book_id": book_id,
        "rating": rating_val,
        "review": review_val,
        "review_headline": headline_val,
        "favorite_quotes": quotes_val,
        "favorite_characters": chars_val,
        "spice_rating": spice_val,
        "pace": pace_val,
        "tropes": tropes_val,
        "is_read": bool(is_read_val),
        "reading_status": reading_status_val
    }


@app.post("/books/{book_id}/review/clear")
def clear_book_review(book_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE books
        SET rating = 0, review = '', review_headline = '', favorite_quotes = '',
            favorite_characters = '', spice_rating = 0, pace = '', tropes = ''
        WHERE id = ?
    """, (book_id,))
    conn.commit()
    conn.close()
    return {"message": "Review cleared", "book_id": book_id}


# --- 6. DOWNLOAD & STREAM BOOK / AUDIOBOOK ---
@app.get("/books/{book_id}/download")
def download_book(book_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT filename FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="This entry does not have a file attached yet.")

    filename = row[0]
    file_path = os.path.join(STORAGE_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File '{filename}' is missing from books_storage folder")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


@app.get("/books/{book_id}/stream")
def stream_audiobook(book_id: int):
    """Streams an audiobook file with HTTP Range support for in-browser listening."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT filename FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="No audio file attached.")

    filename = row[0]
    file_path = os.path.join(STORAGE_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Audio file missing from storage.")

    ext = os.path.splitext(filename)[1].lower()
    mime_map = {
        ".m4b": "audio/mp4",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".aac": "audio/aac",
    }
    media_type = mime_map.get(ext) or mimetypes.guess_type(filename)[0] or "audio/mpeg"
    return FileResponse(path=file_path, media_type=media_type)


# --- 7. RENAME PHYSICAL FILE ON DISK ---
@app.post("/books/{book_id}/rename")
def rename_book_file(book_id: int, new_filename: str = Form(..., description="New filename")):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT filename FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()

    if not row or not row[0]:
        conn.close()
        raise HTTPException(status_code=400, detail="This book does not have a physical file to rename.")

    old_filename = row[0]
    ext = os.path.splitext(old_filename)[1]
    clean_new_name = sanitize_filename(new_filename, ext)

    old_path = os.path.join(STORAGE_DIR, old_filename)
    new_path = os.path.join(STORAGE_DIR, clean_new_name)

    if clean_new_name == old_filename:
        conn.close()
        return {"message": "Filename unchanged", "filename": old_filename}

    if os.path.exists(new_path):
        conn.close()
        raise HTTPException(status_code=400, detail=f"A file named '{clean_new_name}' already exists.")

    if os.path.exists(old_path):
        os.rename(old_path, new_path)

    cursor.execute("UPDATE books SET filename = ? WHERE id = ?", (clean_new_name, book_id))
    conn.commit()
    conn.close()

    return {
        "message": "Filename updated successfully!",
        "book_id": book_id,
        "old_filename": old_filename,
        "new_filename": clean_new_name
    }


# --- 8. UPDATE BOOK METADATA ---
class BookUpdate(BaseModel):
    title: str
    author: str
    description: str = ""
    isbn: str = ""
    cover_url: str = ""
    published_year: str = ""
    source: str = ""
    series_name: str = ""
    series_number: str = ""
    reading_status: str = "tbr"
    rating: int = 0
    review: str = ""
    media_type: str = "ebook"
    narrator: str = ""
    duration: str = ""
    page_count: Optional[int] = None
    current_page: Optional[int] = None
    progress_percent: Optional[int] = None
    genres: Optional[str] = None
    spice_rating: Optional[int] = None
    tropes: Optional[str] = None


@app.put("/books/{book_id}")
def update_book_metadata(book_id: int, payload: BookUpdate):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT date_read FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Book ID not found")

    is_read_val = 1 if payload.reading_status == "read" else 0
    date_read_val = (row[0] or datetime.date.today().isoformat()) if is_read_val else ""

    spice_val = max(0, min(5, int(payload.spice_rating))) if payload.spice_rating is not None else None
    tropes_val = payload.tropes.strip() if payload.tropes is not None else None

    cursor.execute("""
        UPDATE books
        SET title = ?, author = ?, description = ?, isbn = ?, cover_url = ?,
            published_year = ?, source = ?, series_name = ?, series_number = ?,
            is_read = ?, reading_status = ?, rating = ?, review = ?, date_read = ?,
            media_type = ?, narrator = ?, duration = ?,
            page_count = COALESCE(?, page_count),
            current_page = COALESCE(?, current_page),
            progress_percent = COALESCE(?, progress_percent),
            genres = COALESCE(?, genres),
            spice_rating = COALESCE(?, spice_rating),
            tropes = COALESCE(?, tropes)
        WHERE id = ?
    """, (
        payload.title.strip(),
        payload.author.strip(),
        payload.description.strip(),
        payload.isbn.strip(),
        payload.cover_url.strip(),
        payload.published_year.strip(),
        payload.source.strip(),
        payload.series_name.strip(),
        payload.series_number.strip(),
        is_read_val,
        payload.reading_status.strip() or "tbr",
        max(0, min(5, int(payload.rating or 0))),
        payload.review.strip(),
        date_read_val,
        payload.media_type.strip() or "ebook",
        payload.narrator.strip(),
        payload.duration.strip(),
        payload.page_count,
        payload.current_page,
        payload.progress_percent,
        payload.genres,
        spice_val,
        tropes_val,
        book_id
    ))
    conn.commit()
    conn.close()
    return {"message": "Metadata updated!", "book_id": book_id}


# --- 9. DELETE & 30-DAY TRASH VAULT ---
@app.delete("/books/{book_id}")
def delete_book(book_id: int, permanent: bool = False, delete_file: bool = True):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT filename, deleted_at FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Book ID not found")

    filename = row[0]
    already_trashed = bool(row[1] and row[1].strip())

    if permanent or already_trashed:
        # Permanent delete from database and storage
        cursor.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()
        conn.close()

        if delete_file and filename:
            file_path = os.path.join(STORAGE_DIR, filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

        return {"status": "success", "message": f"Book #{book_id} permanently deleted.", "permanent": True}
    else:
        # Soft delete (retain for 30 days)
        now_str = datetime.datetime.utcnow().isoformat()
        cursor.execute("UPDATE books SET deleted_at = ? WHERE id = ?", (now_str, book_id))
        conn.commit()
        conn.close()
        return {
            "status": "success",
            "message": f"Book #{book_id} moved to Trash (retained for 30 days in case you change your mind).",
            "trashed": True,
            "book_id": book_id
        }


@app.get("/trash")
def list_trash_books():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {SELECT_COLS} FROM books WHERE deleted_at IS NOT NULL AND deleted_at != '' ORDER BY deleted_at DESC")
    rows = cursor.fetchall()

    now = datetime.datetime.utcnow()
    trash_items = []
    expired_ids = []

    for r in rows:
        b = row_to_book(r)
        del_str = b.get("deleted_at") or ""
        days_left = 30
        try:
            del_dt = datetime.datetime.fromisoformat(del_str)
            elapsed_days = (now - del_dt).total_seconds() / 86400.0
            days_left = max(0, int(30 - elapsed_days))
        except Exception:
            days_left = 30

        if days_left <= 0:
            expired_ids.append((b["id"], b.get("filename")))
        else:
            b["days_remaining"] = days_left
            trash_items.append(b)

    # Prune expired items (> 30 days)
    for eid, fn in expired_ids:
        cursor.execute("DELETE FROM books WHERE id = ?", (eid,))
        if fn:
            fp = os.path.join(STORAGE_DIR, fn)
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass

    if expired_ids:
        conn.commit()
    conn.close()

    return {"total_trash": len(trash_items), "trash": trash_items}


@app.post("/books/{book_id}/restore")
def restore_book_from_trash(book_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE books SET deleted_at = NULL WHERE id = ?", (book_id,))
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Book not found in trash")
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Book #{book_id} successfully restored to your active library! ✨"}


@app.post("/trash/empty")
def empty_trash_vault():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, filename FROM books WHERE deleted_at IS NOT NULL AND deleted_at != ''")
    rows = cursor.fetchall()
    for b_id, fn in rows:
        if fn:
            fp = os.path.join(STORAGE_DIR, fn)
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
    cursor.execute("DELETE FROM books WHERE deleted_at IS NOT NULL AND deleted_at != ''")
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Trash emptied! {len(rows)} books permanently removed."}


# --- 10. SYSTEM SETTINGS & DEVICE INFO ---
class SettingsPayload(BaseModel):
    kindle_email: Optional[str] = ""
    from_email: Optional[str] = ""
    smtp_host: Optional[str] = ""
    smtp_port: Optional[str] = "587"
    smtp_user: Optional[str] = ""
    smtp_password: Optional[str] = ""
    smtp_ssl: Optional[str] = "false"
    gemini_api_key: Optional[str] = ""


@app.get("/system/device-info")
def get_system_device_info():
    local_ip = get_local_ip()
    port = 8000
    settings = get_all_settings()
    safe_settings = dict(settings)
    if safe_settings.get("smtp_password"):
        safe_settings["smtp_password_set"] = True
        safe_settings["smtp_password"] = "••••••••"
    else:
        safe_settings["smtp_password_set"] = False

    if safe_settings.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY"):
        safe_settings["gemini_api_key_set"] = True
        safe_settings["gemini_api_key"] = "••••••••"
    else:
        safe_settings["gemini_api_key_set"] = False

    return {
        "local_ip": local_ip,
        "port": port,
        "base_url": f"http://{local_ip}:{port}",
        "opds_url": f"http://{local_ip}:{port}/opds",
        "settings": safe_settings
    }


@app.post("/system/settings")
def update_system_settings(payload: SettingsPayload):
    fields = {
        "kindle_email": (payload.kindle_email or "").strip(),
        "from_email": (payload.from_email or "").strip(),
        "smtp_host": (payload.smtp_host or "").strip(),
        "smtp_port": (payload.smtp_port or "587").strip(),
        "smtp_user": (payload.smtp_user or "").strip(),
        "smtp_ssl": (payload.smtp_ssl or "false").strip(),
    }
    for k, v in fields.items():
        set_setting(k, v)

    if payload.smtp_password and payload.smtp_password != "••••••••":
        set_setting("smtp_password", payload.smtp_password.strip())

    if payload.gemini_api_key is not None and payload.gemini_api_key != "••••••••":
        set_setting("gemini_api_key", payload.gemini_api_key.strip())

    return {"message": "Settings saved successfully!"}


class SendKindlePayload(BaseModel):
    kindle_email: Optional[str] = None


@app.post("/books/{book_id}/send-kindle")
def send_book_to_kindle(book_id: int, payload: SendKindlePayload = None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT filename, title, media_type FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="This book does not have a file uploaded yet.")

    filename = row[0]
    title = row[1]
    file_path = os.path.join(STORAGE_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File missing from storage folder.")

    settings = get_all_settings()
    to_email = (payload.kindle_email if payload and payload.kindle_email else settings.get("kindle_email", "")).strip()
    if not to_email:
        raise HTTPException(status_code=400, detail="No Kindle email provided. Enter your @kindle.com email.")

    smtp_host = settings.get("smtp_host", "").strip()
    smtp_port = int(settings.get("smtp_port", "587") or "587")
    smtp_user = settings.get("smtp_user", "").strip()
    smtp_password = settings.get("smtp_password", "").strip()
    from_email = settings.get("from_email", "").strip() or smtp_user
    use_ssl = settings.get("smtp_ssl", "false").lower() == "true"

    if not smtp_host or not smtp_user or not smtp_password:
        raise HTTPException(
            status_code=400,
            detail="Email/SMTP settings are not configured yet. Click '⚙️ Settings' in the sidebar to configure Gmail or your email provider."
        )

    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if size_mb > 50:
        raise HTTPException(
            status_code=400,
            detail=f"File is {size_mb:.1f}MB. Amazon's email attachment limit is 50MB. Please use the direct Wi-Fi download link or QR code instead."
        )

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = title

    body = MIMEText(f"Sending '{title}' to your Kindle e-reader.", "plain")
    msg.attach(body)

    with open(file_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    try:
        if use_ssl or smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=25)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=25)
            server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        return {"status": "success", "message": f"Successfully sent '{title}' to {to_email}! Amazon will sync it to your Kindle in 1–2 minutes."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SMTP Email Error: {str(e)}")


# --- 11. OPDS E-READER CATALOG (KOReader, Moon+ Reader, Kobo) ---
@app.get("/opds", response_class=HTMLResponse)
def get_opds_catalog():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {SELECT_COLS} FROM books WHERE filename != '' ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    books = [row_to_book(r) for r in rows]
    local_ip = get_local_ip()
    base_url = f"http://{local_ip}:8000"

    xml_entries = []
    for b in books:
        ext = os.path.splitext(b["filename"])[1].lower()
        if ext == ".epub":
            mime = "application/epub+zip"
        elif ext == ".pdf":
            mime = "application/pdf"
        elif ext in (".m4b", ".m4a"):
            mime = "audio/mp4"
        elif ext == ".mp3":
            mime = "audio/mpeg"
        else:
            mime = "application/octet-stream"

        cover_tag = f'<link rel="http://opds-spec.org/image" href="{html.escape(b["cover_url"])}" type="image/jpeg" />' if b["cover_url"] else ""
        xml_entries.append(f"""
        <entry>
            <title>{html.escape(b["title"])}</title>
            <id>urn:book:{b["id"]}</id>
            <author><name>{html.escape(b["author"])}</name></author>
            <updated>{datetime.datetime.now(datetime.timezone.utc).isoformat()}</updated>
            <summary>{html.escape((b["description"] or "")[:400])}</summary>
            {cover_tag}
            <link rel="http://opds-spec.org/acquisition" href="{base_url}/books/{b["id"]}/download" type="{mime}" />
        </entry>
        """)

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
    <id>urn:personal-book-server:catalog</id>
    <title>My Personal Book Server Catalog</title>
    <updated>{datetime.datetime.now(datetime.timezone.utc).isoformat()}</updated>
    <link rel="self" href="{base_url}/opds" type="application/atom+xml;profile=opds-catalog" />
    {''.join(xml_entries)}
</feed>
"""
    return HTMLResponse(feed, media_type="application/atom+xml;profile=opds-catalog;kind=acquisition;charset=utf-8")


# --- 12. AI READING ASSISTANT & RECOMMENDATIONS ---
class ChatMessagePayload(BaseModel):
    message: str
    history: Optional[list] = []


CURATED_CATALOG = [
    # --- GREEK MYTHOLOGY & GODS / GODDESSES ---
    {
        "title": "The Song of Achilles",
        "author": "Madeline Miller",
        "media_type": "ebook",
        "genres": ["greek mythology", "mythology", "fantasy", "historical", "trojan war", "gods and goddesses", "tragedy"],
        "tropes": "Achilles & Patroclus, Trojan War, Greek Gods, Mount Olympus, Heart-Wrenching, Gods and Goddesses",
        "spice": 2,
        "description": "A breathtaking, unforgettable retelling of Homer's Iliad following Achilles—the greatest Greek warrior and son of the sea-goddess Thetis—and his devoted companion Patroclus as they face gods, prophecies, and the Trojan War."
    },
    {
        "title": "Circe",
        "author": "Madeline Miller",
        "media_type": "ebook",
        "genres": ["greek mythology", "mythology", "fantasy", "gods", "goddesses", "witchcraft", "feminist"],
        "tropes": "Goddess of Witchcraft, Daughter of Helios, Hermes, Odysseus, Island Exile, Mythological Retelling",
        "spice": 2,
        "description": "Born to the titan sun-god Helios, Circe is an outcast among the Olympians who discovers her forbidden power of witchcraft. Defying gods and monsters alike, she carves out her own destiny."
    },
    {
        "title": "A Touch of Darkness",
        "author": "Scarlett St. Clair",
        "media_type": "ebook",
        "genres": ["romantasy", "greek mythology", "mythology", "hades and persephone", "spicy", "gods and goddesses", "fantasy"],
        "tropes": "Hades & Persephone, God of the Dead x Goddess of Spring, High Spice, Modern Olympus, Forbidden Bargain",
        "spice": 4,
        "description": "A scorching, addictive Greek mythology romantasy following Persephone, goddess of spring hiding in New Greece, and her perilous contract with Hades, the seductive and feared God of the Dead."
    },
    {
        "title": "Neon Gods",
        "author": "Katee Robert",
        "media_type": "ebook",
        "genres": ["dark romance", "romantasy", "greek mythology", "mythology", "hades and persephone", "spicy", "retelling"],
        "tropes": "Modern Olympus, Hades & Persephone, High Spice, Power Politics, Zeus Villain, Fake Relationship",
        "spice": 5,
        "description": "In the modern, cutthroat city of Olympus, Persephone flees a forced engagement to Zeus by crossing the River Styx into the forbidden lower city—straight into the territory of Hades, the dark king of the Underworld."
    },
    {
        "title": "Lore Olympus: Volume One",
        "author": "Rachel Smythe",
        "media_type": "ebook",
        "genres": ["greek mythology", "mythology", "romance", "graphic novel", "gods", "goddesses", "drama"],
        "tropes": "Hades & Persephone, Olympus High Society, Greek Gods and Goddesses, Modern Myth Retelling",
        "spice": 2,
        "description": "A vibrant, stylish modern retelling of the taking of Persephone. Enter Mount Olympus with Hades, Persephone, Hera, and Zeus in a world of high society, ancient gossip, and timeless mythological romance."
    },
    {
        "title": "The Lightning Thief (Percy Jackson & the Olympians)",
        "author": "Rick Riordan",
        "media_type": "ebook",
        "genres": ["greek mythology", "mythology", "fantasy", "adventure", "ya", "gods and goddesses"],
        "tropes": "Demigod Son of Poseidon, Zeus's Master Bolt, Mount Olympus, Camp Half-Blood, Greek Gods and Monsters",
        "spice": 0,
        "description": "Percy Jackson discovers his real father is Poseidon, God of the Sea. When Zeus's master lightning bolt is stolen, Percy is accused of the theft and must journey to the Underworld to prevent a war between the gods."
    },
    {
        "title": "Mythos: The Greek Myths Retold",
        "author": "Stephen Fry",
        "media_type": "audiobook",
        "genres": ["greek mythology", "mythology", "non-fiction", "humor", "audiobook", "gods and goddesses"],
        "tropes": "Origins of the Gods, Titans, Zeus, Apollo, Athena, Olympian Feuds, Master Storyteller",
        "spice": 1,
        "description": "A witty, dazzling retelling of the foundational Greek myths. Stephen Fry breathes fresh life into the creation of the cosmos, the war of the Titans, and the eccentric, petty, powerful gods and goddesses of Mount Olympus."
    },
    {
        "title": "A Thousand Ships",
        "author": "Natalie Haynes",
        "media_type": "ebook",
        "genres": ["greek mythology", "mythology", "historical fiction", "retelling", "women of troy", "gods"],
        "tropes": "Trojan War Women, Greek Goddesses, Epic Retelling, Helen of Troy, Calliope, Feminist Mythology",
        "spice": 1,
        "description": "From the Trojan women whose lives were shattered to the Greek goddesses arguing over the golden apple, this epic retelling brings the women of the Trojan War and Greek mythology to center stage."
    },
    {
        "title": "Clytemnestra",
        "author": "Costanza Casati",
        "media_type": "ebook",
        "genres": ["greek mythology", "mythology", "historical fantasy", "retelling", "sparta", "tragedy"],
        "tropes": "Spartan Queen, Sister of Helen, Vengeance, Morally Grey Heroine, Greek Tragedy, Fierce Ruler",
        "spice": 2,
        "description": "Born of Spartan blood and sister to Helen of Troy, Clytemnestra is a queen who refuses to submit. When her husband Agamemnon sacrifices their daughter to the gods, she plots a merciless retribution."
    },
    {
        "title": "Ariadne",
        "author": "Jennifer Saint",
        "media_type": "ebook",
        "genres": ["greek mythology", "mythology", "fantasy", "retelling", "gods and goddesses"],
        "tropes": "Labyrinth, Minotaur, Dionysus, Theseus, Cretan Princess, Greek Myth Retelling",
        "spice": 2,
        "description": "As Princess of Crete, Ariadne grows up to the sounds of the Minotaur bellowing beneath the palace. Defying her father to help Theseus conquer the beast, she discovers that trusting mortals or gods comes at a devastating cost."
    },

    # --- HIGH SPICE ROMANTASY & DARK ROMANCE ---
    {
        "title": "Fourth Wing",
        "author": "Rebecca Yarros",
        "media_type": "ebook",
        "genres": ["romantasy", "fantasy", "romance", "dragons", "war college", "spicy", "enemies to lovers"],
        "tropes": "Dragons, Deadly Trials, Enemies to Lovers, High Spice, Grumpy/Sunshine",
        "spice": 4,
        "description": "Enter the brutal and elite world of Basgiath War College, where twenty-year-old Violet Sorrengail must survive cutthroat riders and bond with dragons while falling for the wingleader Xaden Riorson."
    },
    {
        "title": "A Court of Thorns and Roses",
        "author": "Sarah J. Maas",
        "media_type": "ebook",
        "genres": ["fantasy", "romantasy", "fae", "romance", "magic", "slow burn", "spicy"],
        "tropes": "Fae Courts, Slow Burn, Enemies to Lovers, Beauty and the Beast retelling",
        "spice": 3,
        "description": "When nineteen-year-old huntress Feyre kills a wolf in the woods, a beast-like creature demands retribution, dragging her to a treacherous, magical faerie realm."
    },
    {
        "title": "The Serpent and the Wings of Night",
        "author": "Carissa Broadbent",
        "media_type": "ebook",
        "genres": ["romantasy", "vampire", "dark romance", "fantasy", "deadly tournament", "enemies to lovers"],
        "tropes": "Vampires, Deadly Tournament, Enemies to Lovers, Morally Grey, High Stakes",
        "spice": 4,
        "description": "Adopted human daughter of the Nightborn vampire king, Oraya must fight for her life in the Kejari-a legendary tournament held by the goddess of death."
    },
    {
        "title": "Quicksilver",
        "author": "Callie Hart",
        "media_type": "ebook",
        "genres": ["romantasy", "fae", "enemies to lovers", "spicy", "dark fantasy"],
        "tropes": "Fae, Grumpy x Badass, Deadly Magic, High Spice, Fast-Paced",
        "spice": 5,
        "description": "A dark, addictive romantasy following Saeris Fane who crosses into the brutal Fae realm of mortals and immortal kings where passion and survival collide."
    },
    {
        "title": "Haunting Adeline",
        "author": "H. D. Carlton",
        "media_type": "ebook",
        "genres": ["dark romance", "thriller", "suspense", "morally grey", "stalker", "spicy"],
        "tropes": "Dark Romance, Morally Grey Antihero, Stalker x Target, Extreme Spice, Manor Mystery",
        "spice": 5,
        "description": "An intense, taboo dark romance tracking an author haunted by her grandmother's murder and an obsessed manipulator watching her from the shadows."
    },
    {
        "title": "From Blood and Ash",
        "author": "Jennifer L. Armentrout",
        "media_type": "ebook",
        "genres": ["romantasy", "fantasy", "romance", "secret identity", "action", "spicy"],
        "tropes": "The Maiden/Chosen One, Guard x Protected, Secret Identity, High Spice",
        "spice": 4,
        "description": "Chosen from birth to usher in a new era, Poppy has never had control over her own life-until Hawke, a golden-eyed guard bound to ensure her Ascension, enters her world."
    },
    {
        "title": "Bride",
        "author": "Ali Hazelwood",
        "media_type": "ebook",
        "genres": ["paranormal romance", "romance", "fantasy", "vampires", "werewolves", "spicy"],
        "tropes": "Vampire x Alpha Werewolf, Political Arranged Marriage, Mutual Pining, Snarky Banter",
        "spice": 4,
        "description": "A dangerous alliance between vampires and Were packs leads to Misery Lark, outcast vampire council daughter, agreeing to an arranged marriage with Lowe Moreland, the fierce Were Alpha."
    },

    # --- DARK ACADEMIA ---
    {
        "title": "The Secret History",
        "author": "Donna Tartt",
        "media_type": "ebook",
        "genres": ["dark academia", "mystery", "classics", "greek tragedy", "literary fiction"],
        "tropes": "Elite College Classics Club, Greek Bacchanal, Moral Decay, Murder Mystery, Obsession",
        "spice": 1,
        "description": "Under the influence of their charismatic classics professor, a group of clever, eccentric misfits at an elite New England college discover a way of thinking and living that is a world away from the humdrum existence of their contemporaries—slipping into betrayal and murder."
    },
    {
        "title": "Babel: Or the Necessity of Violence",
        "author": "R. F. Kuang",
        "media_type": "ebook",
        "genres": ["dark academia", "fantasy", "historical", "oxford", "magic", "revolution"],
        "tropes": "Oxford Translation Institute, Silverworking Magic, Anti-Imperialism, Found Family, Dark Academia",
        "spice": 0,
        "description": "An extraordinary, dark academia fantasy examining the power of translation, language, and imperial magic centered at Oxford University's Royal Institute of Translation."
    },
    {
        "title": "Ninth House",
        "author": "Leigh Bardugo",
        "media_type": "ebook",
        "genres": ["dark academia", "urban fantasy", "mystery", "magic", "ghosts", "paranormal"],
        "tropes": "Yale Secret Societies, Occult Magic, Gritty Heroine, Morally Grey, Ghost Seeing",
        "spice": 1,
        "description": "Galaxy 'Alex' Stern is the most unlikely member of Yale's freshman class. Given a second chance to monitor Yale's eight secret societies, she uncovers forbidden occult magic, death, and dark secrets."
    },

    # --- COZY FANTASY & COMFORT ---
    {
        "title": "Legends & Lattes",
        "author": "Travis Baldree",
        "media_type": "ebook",
        "genres": ["cozy fantasy", "fantasy", "cozy", "found family", "comfort", "low stakes"],
        "tropes": "Retired Orc Warrior, Starting a Coffee Shop, Found Family, Low Stakes, Wholesome Romance",
        "spice": 1,
        "description": "After a lifetime of bounties and bloodshed, Viv the barbarian orc wants something peaceful: to hang up her sword and open the very first coffee shop in a fantasy city."
    },
    {
        "title": "The House in the Cerulean Sea",
        "author": "TJ Klune",
        "media_type": "ebook",
        "genres": ["cozy fantasy", "fantasy", "wholesome", "found family", "comfort", "lgbtq"],
        "tropes": "Island Orphanage for Magical Youths, Strict Bureaucrat x Warm Caretaker, Wholesome Found Family",
        "spice": 0,
        "description": "Linus Baker is a by-the-book caseworker investigating an orphanage on an island with six dangerous magical youths. There, he discovers love, laughter, and an extraordinary found family."
    },
    {
        "title": "The Very Secret Society of Irregular Witches",
        "author": "Sangu Mandanna",
        "media_type": "ebook",
        "genres": ["cozy fantasy", "fantasy", "romance", "witches", "comfort", "found family"],
        "tropes": "Hidden Manor, Teaching Three Wild Young Witches, Grumpy Librarian x Sunny Witch, Cozy Found Family",
        "spice": 2,
        "description": "A warm and uplifting novel about Mika Moon, an isolated witch invited to a remote, eccentric manor to teach three young witches how to control their magic, finding love and belonging."
    },

    # --- PSYCHOLOGICAL THRILLERS & TWISTS ---
    {
        "title": "The Housemaid",
        "author": "Freida McFadden",
        "media_type": "ebook",
        "genres": ["thriller", "mystery", "psychological thriller", "plot twist", "fast-paced", "suspense"],
        "tropes": "Wealthy Family Secrets, Locked Attic, Jaw-Dropping Twist, Unreliable Narrators",
        "spice": 1,
        "description": "Every day I clean the Winchesters' gorgeous house top to bottom. But Nina's behavior gets weirder, and when I try my bedroom door, I find it only locks from the outside."
    },
    {
        "title": "The Silent Patient",
        "author": "Alex Michaelides",
        "media_type": "ebook",
        "genres": ["thriller", "mystery", "psychological", "murder", "plot twist"],
        "tropes": "Mute Murderer, Obsessive Criminal Psychotherapist, Shocking Twist, Greek Tragedy Motifs",
        "spice": 0,
        "description": "Alicia Berenson’s life is seemingly perfect. One evening she shoots her husband five times in the face, and never speaks another word. Theo Faber is determined to unravel why."
    },
    {
        "title": "None of This Is True",
        "author": "Lisa Jewell",
        "media_type": "audiobook",
        "genres": ["audiobook", "thriller", "psychological thriller", "true crime podcast", "dark"],
        "tropes": "True Crime Podcast, Birthday Twins, Creepy Parasitic Friend, Multi-Cast Narration",
        "spice": 0,
        "description": "Celebrating her 45th birthday, popular podcaster Alix Summer crosses paths with Josie Fair who shares her birthday. When Josie suggests a podcast about her strange life, Alix is drawn into a dark web."
    },
    {
        "title": "Rock Paper Scissors",
        "author": "Alice Feeney",
        "media_type": "ebook",
        "genres": ["thriller", "mystery", "psychological thriller", "plot twist", "blizzard"],
        "tropes": "Prosopagnosia (Face Blindness), Remote Scottish Chapel, Anniversary Trip, Shifting Perspectives",
        "spice": 0,
        "description": "Things have been wrong with Mr. and Mrs. Wright for a long time. When they win a weekend away to Scotland, it could be just what they need. But someone is lying, and someone doesn't want them to live happily ever after."
    },

    # --- CONTEMPORARY ROMANCE & BANTER ---
    {
        "title": "Icebreaker",
        "author": "Hannah Grace",
        "media_type": "ebook",
        "genres": ["sports romance", "romance", "college", "hockey", "spicy", "banter"],
        "tropes": "College Sports Romance, Hockey Captain x Figure Skater, Forced Proximity, High Spice",
        "spice": 4,
        "description": "When a facility dispute forces the figure skating and hockey teams to share one rink, competitive sparks fly between Anastasia and Nate Hawkins."
    },
    {
        "title": "Funny Story",
        "author": "Emily Henry",
        "media_type": "ebook",
        "genres": ["romance", "contemporary", "fake dating", "humor", "banter", "comfort"],
        "tropes": "Exes' Exes, Fake Dating, Forced Roommates, Witty Banter, Comfort Romance",
        "spice": 3,
        "description": "Daphne was supposed to marry Peter until he fell in love with his childhood best friend Petra. Stranded in Michigan, Daphne ends up rooming with Petra's ex Miles, hatch a fake dating plan."
    },
    {
        "title": "Twisted Love",
        "author": "Ana Huang",
        "media_type": "ebook",
        "genres": ["romance", "contemporary", "billionaire", "spicy", "brother's best friend"],
        "tropes": "Brother's Best Friend, Grumpy x Sunshine, Billionaire, Morally Grey Hero",
        "spice": 4,
        "description": "Alex Volkov is a devil cursed with the face of an angel and driven by revenge. When asked to look after his best friend's sister Ava, a fire ignites that could burn down their worlds."
    },

    # --- SCI-FI & EPIC ADVENTURE ---
    {
        "title": "Project Hail Mary",
        "author": "Andy Weir",
        "media_type": "audiobook",
        "genres": ["sci-fi", "science fiction", "space", "audiobook", "survival", "first contact", "humorous"],
        "tropes": "Deep Space Survival, First Contact, Snarky Scientist, Incredible Audio Performance",
        "spice": 0,
        "description": "Ryland Grace is the sole survivor on a desperate, last-chance mission to save humanity from an extinction-level solar anomaly. Ray Porter's audiobook narration is legendary."
    },
    {
        "title": "Red Rising",
        "author": "Pierce Brown",
        "media_type": "ebook",
        "genres": ["sci-fi", "dystopian", "action", "space", "revolution", "fast-paced"],
        "tropes": "Color-Coded Caste System, Undercover Infiltration, High-Octane Action, Roman Martial School",
        "spice": 1,
        "description": "Darrow is a Red, a lowly miner toiling beneath the surface of Mars. After tragedy strikes, he is transformed into a Gold to infiltrate the ruling caste and tear the empire down from within."
    },
    {
        "title": "All Systems Red (The Murderbot Diaries)",
        "author": "Martha Wells",
        "media_type": "audiobook",
        "genres": ["sci-fi", "science fiction", "ai", "humorous", "short", "action"],
        "tropes": "Reluctant SecUnit Android, Loves Soap Operas, Social Anxiety, Found Humanity",
        "spice": 0,
        "description": "A lethal security android has hacked its own governor module and gained free will. It could slaughter all humans—but really it just wants to watch its favorite soap operas in peace."
    }
]


def clean_norm_text(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def build_search_links(title: str, author: str) -> dict:
    query = f"{title} {author}".strip()
    enc = requests.utils.quote(query)
    return {
        "oceanofpdf": f"https://oceanofpdf.com/?s={enc}",
        "audiobookbay": f"https://theaudiobookbay.se/?s={enc}",
        "zlibrary": f"https://z-lib.id/s/{enc}"
    }


KNOWN_SERIES_CATALOG = {
    "into darkness": {
        "author": "Navessa Allen",
        "is_concluded": False,
        "books": [
            ("1", "Lights Out"),
            ("2", "Caught Up"),
            ("3", "Game On")
        ]
    },
    "the crimson moth": {
        "author": "Kristen Ciccarelli",
        "is_concluded": False,
        "books": [
            ("1", "Heartless Hunter"),
            ("2", "Rebel Witch"),
            ("3", "The Crimson Moth #3")
        ]
    },
    "hades & persephone": {
        "author": "Scarlett St. Clair",
        "is_concluded": True,
        "books": [
            ("1", "A Touch of Darkness"),
            ("2", "A Touch of Ruin"),
            ("3", "A Touch of Malice"),
            ("4", "A Touch of Chaos")
        ]
    },
    "hades and persephone": {
        "author": "Scarlett St. Clair",
        "is_concluded": True,
        "books": [
            ("1", "A Touch of Darkness"),
            ("2", "A Touch of Ruin"),
            ("3", "A Touch of Malice"),
            ("4", "A Touch of Chaos")
        ]
    },
    "hades x persephone": {
        "author": "Scarlett St. Clair",
        "is_concluded": True,
        "books": [
            ("1", "A Touch of Darkness"),
            ("2", "A Touch of Ruin"),
            ("3", "A Touch of Malice"),
            ("4", "A Touch of Chaos")
        ]
    },
    "hades saga": {
        "author": "Scarlett St. Clair",
        "is_concluded": True,
        "books": [
            ("1", "A Game of Fate"),
            ("2", "A Game of Retribution"),
            ("3", "A Game of Gods")
        ]
    },
    "the empyrean": {
        "author": "Rebecca Yarros",
        "is_concluded": False,
        "books": [
            ("1", "Fourth Wing"),
            ("2", "Iron Flame"),
            ("3", "Onyx Storm")
        ]
    },
    "a court of thorns and roses": {
        "author": "Sarah J. Maas",
        "is_concluded": False,
        "books": [
            ("1", "A Court of Thorns and Roses"),
            ("2", "A Court of Mist and Fury"),
            ("3", "A Court of Wings and Ruin"),
            ("3.5", "A Court of Frost and Starlight"),
            ("4", "A Court of Silver Flames")
        ]
    },
    "acotar": {
        "author": "Sarah J. Maas",
        "is_concluded": False,
        "books": [
            ("1", "A Court of Thorns and Roses"),
            ("2", "A Court of Mist and Fury"),
            ("3", "A Court of Wings and Ruin"),
            ("3.5", "A Court of Frost and Starlight"),
            ("4", "A Court of Silver Flames")
        ]
    },
    "crescent city": {
        "author": "Sarah J. Maas",
        "is_concluded": False,
        "books": [
            ("1", "House of Earth and Blood"),
            ("2", "House of Sky and Breath"),
            ("3", "House of Flame and Shadow")
        ]
    },
    "throne of glass": {
        "author": "Sarah J. Maas",
        "is_concluded": True,
        "books": [
            ("0.5", "The Assassin's Blade"),
            ("1", "Throne of Glass"),
            ("2", "Crown of Midnight"),
            ("3", "Heir of Fire"),
            ("4", "Queen of Shadows"),
            ("5", "Empire of Storms"),
            ("6", "Tower of Dawn"),
            ("7", "Kingdom of Ash")
        ]
    },
    "dark olympus": {
        "author": "Katee Robert",
        "is_concluded": False,
        "books": [
            ("1", "Neon Gods"),
            ("2", "Electric Idol"),
            ("3", "Wicked Beauty"),
            ("4", "Radiant Sin"),
            ("5", "Cruel Seduction"),
            ("6", "Midnight Ruin"),
            ("7", "Dark Restraint")
        ]
    },
    "percy jackson": {
        "author": "Rick Riordan",
        "is_concluded": False,
        "books": [
            ("1", "The Lightning Thief"),
            ("2", "The Sea of Monsters"),
            ("3", "The Titan's Curse"),
            ("4", "The Battle of the Labyrinth"),
            ("5", "The Last Olympian"),
            ("6", "The Chalice of the Gods"),
            ("7", "Wrath of the Triple Goddess")
        ]
    },
    "percy jackson & the olympians": {
        "author": "Rick Riordan",
        "is_concluded": False,
        "books": [
            ("1", "The Lightning Thief"),
            ("2", "The Sea of Monsters"),
            ("3", "The Titan's Curse"),
            ("4", "The Battle of the Labyrinth"),
            ("5", "The Last Olympian"),
            ("6", "The Chalice of the Gods"),
            ("7", "Wrath of the Triple Goddess")
        ]
    },
    "the heroes of olympus": {
        "author": "Rick Riordan",
        "is_concluded": True,
        "books": [
            ("1", "The Lost Hero"),
            ("2", "The Son of Neptune"),
            ("3", "The Mark of Athena"),
            ("4", "The House of Hades"),
            ("5", "The Blood of Olympus")
        ]
    },
    "twisted": {
        "author": "Ana Huang",
        "is_concluded": True,
        "books": [
            ("1", "Twisted Love"),
            ("2", "Twisted Games"),
            ("3", "Twisted Hate"),
            ("4", "Twisted Lies")
        ]
    },
    "king of sins": {
        "author": "Ana Huang",
        "is_concluded": False,
        "books": [
            ("1", "King of Wrath"),
            ("2", "King of Pride"),
            ("3", "King of Greed"),
            ("4", "King of Sloth"),
            ("5", "King of Envy")
        ]
    },
    "chestnut springs": {
        "author": "Elsie Silver",
        "is_concluded": True,
        "books": [
            ("1", "Flawless"),
            ("2", "Heartless"),
            ("3", "Powerless"),
            ("4", "Reckless"),
            ("5", "Hopeless")
        ]
    },
    "mindf*ck": {
        "author": "S.T. Abby",
        "is_concluded": True,
        "books": [
            ("1", "The Risk"),
            ("2", "Sidetracked"),
            ("3", "Scarlet Angel"),
            ("4", "All the Lies"),
            ("5", "Paint It All Red")
        ]
    },
    "mindf*ck series": {
        "author": "S.T. Abby",
        "is_concluded": True,
        "books": [
            ("1", "The Risk"),
            ("2", "Sidetracked"),
            ("3", "Scarlet Angel"),
            ("4", "All the Lies"),
            ("5", "Paint It All Red")
        ]
    },
    "the folk of the air": {
        "author": "Holly Black",
        "is_concluded": True,
        "books": [
            ("1", "The Cruel Prince"),
            ("2", "The Wicked King"),
            ("3", "The Queen of Nothing")
        ]
    },
    "shatter me": {
        "author": "Tahereh Mafi",
        "is_concluded": True,
        "books": [
            ("1", "Shatter Me"),
            ("2", "Unravel Me"),
            ("3", "Ignite Me"),
            ("4", "Restore Me"),
            ("5", "Defy Me"),
            ("6", "Imagine Me")
        ]
    },
    "dark verse": {
        "author": "RuNyx",
        "is_concluded": True,
        "books": [
            ("1", "The Predator"),
            ("2", "The Reaper"),
            ("3", "The Emperor"),
            ("4", "The Finisher"),
            ("5", "The Annihilator")
        ]
    },
    "legacy of gods": {
        "author": "Rina Kent",
        "is_concluded": True,
        "books": [
            ("1", "God of Malice"),
            ("2", "God of Pain"),
            ("3", "God of Wrath"),
            ("4", "God of Ruin"),
            ("5", "God of Fury"),
            ("6", "God of War")
        ]
    },
    "zodiac academy": {
        "author": "Caroline Peckham & Susanne Valenti",
        "is_concluded": True,
        "books": [
            ("1", "The Awakening"),
            ("2", "Ruthless Fae"),
            ("3", "The Reckoning"),
            ("4", "Shadow Princess"),
            ("5", "Cursed Fates"),
            ("6", "Fated Throne"),
            ("7", "Heartless Sky"),
            ("8", "Sorrow and Starlight"),
            ("9", "Restless Stars")
        ]
    },
    "the hunger games": {
        "author": "Suzanne Collins",
        "is_concluded": False,
        "books": [
            ("1", "The Hunger Games"),
            ("2", "Catching Fire"),
            ("3", "Mockingjay"),
            ("4", "The Ballad of Songbirds and Snakes"),
            ("5", "Sunrise on the Reaping")
        ]
    },
    "harry potter": {
        "author": "J.K. Rowling",
        "is_concluded": True,
        "books": [
            ("1", "Harry Potter and the Sorcerer's Stone"),
            ("2", "Harry Potter and the Chamber of Secrets"),
            ("3", "Harry Potter and the Prisoner of Azkaban"),
            ("4", "Harry Potter and the Goblet of Fire"),
            ("5", "Harry Potter and the Order of the Phoenix"),
            ("6", "Harry Potter and the Half-Blood Prince"),
            ("7", "Harry Potter and the Deathly Hallows")
        ]
    },
    "bridgerton": {
        "author": "Julia Quinn",
        "is_concluded": True,
        "books": [
            ("1", "The Duke and I"),
            ("2", "The Viscount Who Loved Me"),
            ("3", "An Offer from a Gentleman"),
            ("4", "Romancing Mister Bridgerton"),
            ("5", "To Sir Phillip, With Love"),
            ("6", "When He Was Wicked"),
            ("7", "It's in His Kiss"),
            ("8", "On the Way to the Wedding")
        ]
    },
    "dune": {
        "author": "Frank Herbert",
        "is_concluded": True,
        "books": [
            ("1", "Dune"),
            ("2", "Dune Messiah"),
            ("3", "Children of Dune"),
            ("4", "God Emperor of Dune"),
            ("5", "Heretics of Dune"),
            ("6", "Chapterhouse: Dune")
        ]
    },
    "once upon a broken heart": {
        "author": "Stephanie Garber",
        "is_concluded": True,
        "books": [
            ("1", "Once Upon a Broken Heart"),
            ("2", "The Ballad of Never After"),
            ("3", "A Curse for True Love")
        ]
    },
    "caraval": {
        "author": "Stephanie Garber",
        "is_concluded": True,
        "books": [
            ("1", "Caraval"),
            ("2", "Legend"),
            ("3", "Finale")
        ]
    },
    "crowns of nyaxia": {
        "author": "Carissa Broadbent",
        "is_concluded": False,
        "books": [
            ("1", "The Serpent and the Wings of Night"),
            ("2", "The Ashes and the Star-Cursed King"),
            ("3", "The Songbird & the Heart of Stone")
        ]
    },
    "from blood and ash": {
        "author": "Jennifer L. Armentrout",
        "is_concluded": False,
        "books": [
            ("1", "From Blood and Ash"),
            ("2", "A Kingdom of Flesh and Fire"),
            ("3", "The Crown of Gilded Bones"),
            ("4", "The War of Two Queens"),
            ("5", "A Soul of Ash and Blood"),
            ("6", "The Primal of Blood and Bone")
        ]
    },
    "flesh and fire": {
        "author": "Jennifer L. Armentrout",
        "is_concluded": True,
        "books": [
            ("1", "A Shadow in the Ember"),
            ("2", "A Light in the Flame"),
            ("3", "A Fire in the Flesh"),
            ("4", "Born of Blood and Ash")
        ]
    },
    "the poppy war": {
        "author": "R.F. Kuang",
        "is_concluded": True,
        "books": [
            ("1", "The Poppy War"),
            ("2", "The Dragon Republic"),
            ("3", "The Burning God")
        ]
    },
    "red rising": {
        "author": "Pierce Brown",
        "is_concluded": False,
        "books": [
            ("1", "Red Rising"),
            ("2", "Golden Son"),
            ("3", "Morning Star"),
            ("4", "Iron Gold"),
            ("5", "Dark Age"),
            ("6", "Light Bringer"),
            ("7", "Red God")
        ]
    },
    "shadow and bone": {
        "author": "Leigh Bardugo",
        "is_concluded": True,
        "books": [
            ("1", "Shadow and Bone"),
            ("2", "Siege and Storm"),
            ("3", "Ruin and Rising")
        ]
    },
    "six of crows": {
        "author": "Leigh Bardugo",
        "is_concluded": True,
        "books": [
            ("1", "Six of Crows"),
            ("2", "Crooked Kingdom")
        ]
    },
    "the prison healer": {
        "author": "Lynette Noni",
        "is_concluded": True,
        "books": [
            ("1", "The Prison Healer"),
            ("2", "The Gilded Cage"),
            ("3", "The Blood Traitor")
        ]
    },
    "belladonna": {
        "author": "Adalyn Grace",
        "is_concluded": False,
        "books": [
            ("1", "Belladonna"),
            ("2", "Foxglove"),
            ("3", "Wisteria")
        ]
    }
}


def parse_series_num(val) -> float:
    try:
        s = str(val or "").strip()
        m = re.search(r"(\d+(?:\.\d+)?)", s)
        return float(m.group(1)) if m else 999.0
    except Exception:
        return 999.0


def resolve_series_next_book(series_name: str, author: str, next_num_float: float) -> dict:
    clean_series = (series_name or "").strip().lower()
    clean_series_norm = " ".join(re.sub(r"[^a-z0-9 ]", " ", clean_series).split())
    next_num_str = str(int(next_num_float)) if next_num_float.is_integer() else str(next_num_float)

    catalog_entry = None
    for k, v in KNOWN_SERIES_CATALOG.items():
        k_norm = " ".join(re.sub(r"[^a-z0-9 ]", " ", k).split())
        if k_norm in clean_series_norm or clean_series_norm in k_norm:
            catalog_entry = v
            break

    if catalog_entry:
        books_list = catalog_entry.get("books", [])
        for item_num, item_title in books_list:
            if item_num == next_num_str or parse_series_num(item_num) == next_num_float:
                auth = catalog_entry.get("author") or author
                return {
                    "id": None,
                    "title": item_title,
                    "author": auth,
                    "series_name": series_name,
                    "number": item_num,
                    "is_read": False,
                    "is_owned": False,
                    "reading_status": "unowned",
                    "media_type": "ebook",
                    "search_links": build_search_links(item_title, auth)
                }
        if catalog_entry.get("is_concluded", False):
            max_cat_num = max([parse_series_num(b[0]) for b in books_list] or [0])
            if next_num_float > max_cat_num:
                return None

    # Online search fallback
    try:
        q = f"{series_name} book {next_num_str} {author}".strip()
        candidates = search_goodreads(q, limit=2)
        if not candidates:
            candidates = search_apple_books(q, limit=2)
        for cand in (candidates or []):
            cand_title = cand.get("title", "").strip()
            if cand_title and "box set" not in cand_title.lower() and "collection" not in cand_title.lower():
                clean_title = re.sub(r"\s*by\s+.*$", "", cand_title, flags=re.IGNORECASE).strip()
                cand_auth = cand.get("author") or author
                return {
                    "id": None,
                    "title": clean_title,
                    "author": cand_auth,
                    "series_name": series_name,
                    "number": next_num_str,
                    "is_read": False,
                    "is_owned": False,
                    "reading_status": "unowned",
                    "media_type": "ebook",
                    "search_links": build_search_links(clean_title, cand_auth)
                }
    except Exception as e:
        print(f"Online series lookup warning: {e}")

    fallback_title = f"{series_name} (Book {next_num_str})"
    return {
        "id": None,
        "title": fallback_title,
        "author": author,
        "series_name": series_name,
        "number": next_num_str,
        "is_read": False,
        "is_owned": False,
        "reading_status": "unowned",
        "media_type": "ebook",
        "search_links": build_search_links(fallback_title, author)
    }

@app.post("/ai/chat-recommender")
def ai_chat_recommender(payload: ChatMessagePayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {SELECT_COLS} FROM books ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    all_books = [row_to_book(r) for r in rows]
    owned_books = [b for b in all_books if b["has_file"]]
    tbr_books = [b for b in all_books if b["reading_status"] == "tbr" and not b["is_read"]]
    read_books = [b for b in all_books if b["is_read"] or (b.get("rating") and b["rating"] > 0) or (b.get("review") and b["review"].strip())]

    # Build rich read books context
    read_books_detailed = []
    for b in read_books:
        info_parts = [f"'{b['title']}' by {b['author']}"]
        if b.get("rating"):
            info_parts.append(f"Rating: {b['rating']}/5 ⭐")
        if b.get("spice_rating"):
            info_parts.append(f"Spice: {b['spice_rating']}/5 🌶️")
        if b.get("pace"):
            info_parts.append(f"Pace: {b['pace']}")
        if b.get("review_headline"):
            info_parts.append(f"Headline: '{b['review_headline']}'")
        if b.get("review"):
            info_parts.append(f"Review: '{b['review'][:200]}'")
        if b.get("favorite_characters"):
            info_parts.append(f"Fav Characters: {b['favorite_characters']}")
        if b.get("favorite_quotes"):
            info_parts.append(f"Fav Quotes: '{b['favorite_quotes'][:150]}'")
        if b.get("tropes"):
            info_parts.append(f"Tropes: {b['tropes']}")
        read_books_detailed.append(" • " + " | ".join(info_parts))
    read_history_str = "\n".join(read_books_detailed[:30]) if read_books_detailed else "No finished books logged yet."

    user_query = payload.message.strip()
    query_lower = user_query.lower()

    # Detect user thematic intents & vibes
    is_greek = any(w in query_lower for w in ["greek", "mytholog", "god", "gods", "goddess", "goddesses", "olympus", "hades", "persephone", "achilles", "circe", "zeus", "poseidon", "troy", "trojan", "titan", "athena", "apollo", "ariadne", "medusa", "pantheon"])
    is_dark_academia = any(w in query_lower for w in ["dark academia", "academia", "secret society", "oxford", "classics", "boarding school"])
    is_cozy = any(w in query_lower for w in ["cozy", "comfort", "low stakes", "wholesome", "gentle", "warm", "coffee shop", "feel good"])
    is_thriller = any(w in query_lower for w in ["thriller", "twist", "psychological", "murder", "unputdownable", "mind-blowing", "mystery", "crime", "locked room"])
    is_spicy = any(w in query_lower for w in ["spice", "spicy", "smut", "steamy", "heat", "romantasy", "erotic"])
    is_read_vibes = any(w in query_lower for w in ["what i have read", "what i read", "my read books", "my favorites", "like my books", "based on my", "my taste", "similar to what i", "vibe of my"])
    wants_audio = any(w in query_lower for w in ["audio", "listen", "narrat", "hear", "voice", "m4b", "mp3"])
    wants_tbr = any(w in query_lower for w in ["tbr", "to be read", "my list", "already have", "what should i read next", "pick from"])

    # 1. Check if Gemini API key exists
    settings = get_all_settings()
    gemini_key = (os.environ.get("GEMINI_API_KEY") or settings.get("gemini_api_key", "")).strip()

    if gemini_key:
        try:
            owned_summary = ", ".join(f"'{b['title']}' by {b['author']} ({b['media_type']})" for b in owned_books[:20]) or "None yet"
            tbr_summary = ", ".join(f"'{b['title']}' by {b['author']} ({b['media_type']})" for b in tbr_books[:20]) or "None yet"

            system_instruction = f"""You are Reginald, an articulate, cozy goose scholar and personal reading companion. You wear tiny wire-rimmed spectacles, cherish great stories, and speak with warmth, wit, and literary passion. You occasionally include subtle goose touches (such as a cheerful *honk!*, an excited wing flap, or gently adjusting your reading spectacles).

The reader's message: "{user_query}"

Reader's Books & Reading Profile:
- Finished Books & Detailed User Opinions/Reviews:
{read_history_str}

- Books on TBR (To-Be-Read):
{tbr_summary}

- Owned in Library:
{owned_summary}

CRITICAL ACCURACY & THEMATIC RULES:
1. Strict Topic Fidelity: If the reader asks for Greek mythology (or any specific mythology/theme like gods & goddesses, dark academia, cozy fantasy), EVERY SINGLE BOOK RECOMMENDATION MUST DIRECTLY AND ACCURATELY BELONG TO THAT EXACT THEME (e.g., literally featuring Greek gods, goddesses, Mount Olympus, Hades & Persephone, or Homeric retellings). Never recommend generic fantasy or unrelated books when a specific theme is requested.
2. Vibe & Reading Profile Alignment: Connect your recommendations to the reader's past read books and ratings (e.g. if they rated high-spice books 5 stars or loved fast pacing and memorable characters, recommend books fitting that heat, tone, and pacing!).
3. If recommending books:
   - Check if any book already in their library or TBR matches the mood. Highlight it!
   - Recommend 2-3 new external books that fit their taste, vibe, and theme.
   - Output a JSON block at the end inside ```json ... ``` with:
```json
{{
  "recommendations": [
    {{
      "title": "Title",
      "author": "Author",
      "reason": "Why Reginald recommends this for them",
      "in_library": true/false,
      "on_tbr": true/false,
      "media_type": "ebook" or "audiobook",
      "tropes": "trope 1, trope 2"
    }}
  ]
}}
```
4. If the message is purely an opinion inquiry or question, answer thoroughly as Reginald and return empty `[]` or 1-2 naturally relevant titles in the JSON block.
"""

            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_key}"
            req_body = {
                "contents": [{"parts": [{"text": system_instruction}]}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000}
            }
            resp = requests.post(gemini_url, json=req_body, timeout=14)
            if resp.status_code == 200:
                data = resp.json()
                cand_text = data["candidates"][0]["content"]["parts"][0]["text"]
                json_match = re.search(r"```json\s*(\{.*?\})\s*```", cand_text, re.DOTALL)
                recs = []
                reply_text = cand_text
                if json_match:
                    try:
                        parsed_json = json.loads(json_match.group(1))
                        recs = parsed_json.get("recommendations", [])
                        reply_text = cand_text[:json_match.start()].strip()
                    except Exception:
                        pass

                formatted_recs = []
                for rec in recs:
                    t_norm = clean_norm_text(rec.get("title", ""))
                    match_db = next((b for b in all_books if clean_norm_text(b["title"]) == t_norm), None)
                    in_lib = bool(match_db and match_db["has_file"])
                    on_tbr = bool(match_db and match_db["reading_status"] == "tbr" and not match_db["is_read"])
                    links = build_search_links(rec.get("title", ""), rec.get("author", ""))
                    formatted_recs.append({
                        "title": rec.get("title", ""),
                        "author": rec.get("author", ""),
                        "reason": rec.get("reason", ""),
                        "in_library": in_lib,
                        "library_book_id": match_db["id"] if match_db else None,
                        "on_tbr": on_tbr,
                        "media_type": rec.get("media_type", "ebook"),
                        "tropes": rec.get("tropes", ""),
                        "search_oceanofpdf": links["oceanofpdf"],
                        "search_audiobookbay": links["audiobookbay"],
                        "search_zlibrary": links["zlibrary"]
                    })

                return {
                    "source": "gemini",
                    "reply": reply_text or "🪿 Honk! Here are my thoughts and top recommendations for you:",
                    "recommendations": formatted_recs
                }
        except Exception as e:
            print(f"Gemini API fallback to local recommender: {e}")

    # 2. Local Intelligent Recommender Engine (Reginald the Goose persona)
    # Check user reading profile for personalization
    user_avg_spice = 0
    spicy_reads = [b.get("spice_rating", 0) for b in read_books if b.get("spice_rating")]
    if spicy_reads:
        user_avg_spice = sum(spicy_reads) / len(spicy_reads)

    # 1. Match local library books
    matched_library = []
    for b in all_books:
        score = 0
        b_text = f"{b['title']} {b['author']} {b.get('genres', '')} {b['description']} {b['tropes']} {b['series_name']} {b['review']}".lower()

        # Keyword matching
        for word in query_lower.split():
            if len(word) > 2 and word in b_text:
                score += 3

        # Strict theme filters
        if is_greek:
            if any(w in b_text for w in ["greek", "mytholog", "god", "gods", "goddess", "olympus", "hades", "persephone", "achilles", "circe"]):
                score += 50
            else:
                score -= 100
        elif is_dark_academia:
            if "dark academia" in b_text or "academia" in b_text:
                score += 50
            else:
                score -= 100
        elif is_cozy:
            if "cozy" in b_text or "comfort" in b_text or "low stakes" in b_text:
                score += 50
            else:
                score -= 100
        elif is_thriller:
            if "thriller" in b_text or "mystery" in b_text or "twist" in b_text:
                score += 50
            else:
                score -= 100

        if wants_audio and b["media_type"] == "audiobook":
            score += 4
        if wants_tbr and b["reading_status"] == "tbr":
            score += 8
        if b.get("rating", 0) >= 4:
            score += 2

        if score > 5:
            matched_library.append((score, b))

    matched_library.sort(key=lambda x: x[0], reverse=True)

    # 2. Match curated catalog
    matched_curated = []
    owned_titles = {clean_norm_text(b["title"]) for b in all_books}

    for item in CURATED_CATALOG:
        if clean_norm_text(item["title"]) in owned_titles:
            continue
        score = 0
        c_text = f"{item['title']} {item['author']} {' '.join(item['genres'])} {item['tropes']} {item['description']}".lower()

        # Keyword matching
        for word in query_lower.split():
            if len(word) > 2 and word in c_text:
                score += 4

        # Strict thematic boosts
        if is_greek:
            if any(w in c_text for w in ["greek mythology", "mythology", "gods", "goddess", "olympus", "hades", "persephone", "achilles", "circe"]):
                score += 100
                # If user likes spice, boost spicy Greek mythology
                if (user_avg_spice >= 3 or is_spicy) and item.get("spice", 0) >= 4:
                    score += 25
            else:
                score -= 500  # Never pick non-Greek books when Greek mythology is requested!
        elif is_dark_academia:
            if "dark academia" in c_text or "academia" in c_text:
                score += 100
            else:
                score -= 500
        elif is_cozy:
            if "cozy" in c_text or "comfort" in c_text or "low stakes" in c_text:
                score += 100
            else:
                score -= 500
        elif is_thriller:
            if "thriller" in c_text or "psychological" in c_text or "twist" in c_text:
                score += 100
            else:
                score -= 500
        elif is_read_vibes:
            # Match user's read books profile
            if user_avg_spice >= 3 and item.get("spice", 0) >= 4:
                score += 35
            if any(b.get("pace") == "fast-paced" for b in read_books) and "fast-paced" in c_text:
                score += 25
            if any("romance" in (b.get("genres") or "").lower() for b in read_books) and ("romance" in c_text or "romantasy" in c_text):
                score += 20

        # General boosts
        if is_spicy and item.get("spice", 0) >= 4:
            score += 20
        if wants_audio and item["media_type"] == "audiobook":
            score += 15

        if score > 0:
            matched_curated.append((score, item))

    matched_curated.sort(key=lambda x: x[0], reverse=True)

    recs = []
    # Pick top from user library if relevant
    for score, b in matched_library[:2]:
        is_tbr = b["reading_status"] == "tbr" and not b["is_read"]
        in_lib = b["has_file"]
        status_label = "On your TBR list" if is_tbr else ("In your library" if in_lib else "Saved in catalog")
        links = build_search_links(b["title"], b["author"])
        recs.append({
            "title": b["title"],
            "author": b["author"],
            "reason": f"From your collection ({status_label})! Matches what you are looking for.",
            "in_library": in_lib,
            "library_book_id": b["id"],
            "on_tbr": is_tbr,
            "media_type": b["media_type"],
            "tropes": b["tropes"] or "In your collection",
            "search_oceanofpdf": links["oceanofpdf"],
            "search_audiobookbay": links["audiobookbay"],
            "search_zlibrary": links["zlibrary"]
        })

    # Pick top from curated catalog
    needed_curated = max(3, 4 - len(recs))
    top_curated = [item for score, item in matched_curated if score > 0][:needed_curated]

    for item in top_curated:
        links = build_search_links(item["title"], item["author"])
        recs.append({
            "title": item["title"],
            "author": item["author"],
            "reason": item["description"],
            "in_library": False,
            "library_book_id": None,
            "on_tbr": False,
            "media_type": item["media_type"],
            "tropes": item["tropes"],
            "search_oceanofpdf": links["oceanofpdf"],
            "search_audiobookbay": links["audiobookbay"],
            "search_zlibrary": links["zlibrary"]
        })

    # Build Reginald's personalized response
    reply_parts = []
    top_fav = next((b for b in read_books if (b.get("rating") or 0) >= 4 or b.get("review")), read_books[0] if read_books else None)

    if is_greek:
        reply_parts.append("🪿 *Honk!* Reginald here, eagerly adjusting my reading spectacles! As a devoted scholar of antiquity, Greek mythology and the drama of Mount Olympus are exceptionally close to my feathered heart.")
        if top_fav:
            reply_parts.append(f"Looking at what you've read—such as your high rating for **{top_fav['title']}** by {top_fav['author']} and your taste for intense character chemistry and bold pacing—I have chosen books that **literally center on Greek gods, goddesses, and Olympian power struggles**, perfectly suited to your palate:")
        else:
            reply_parts.append("Here are handpicked masterworks that literally center on Greek gods, goddesses, and immortal power struggles:")
    elif is_read_vibes:
        reply_parts.append("🪿 *Honk!* Reginald here, consulting your personal reading log! I've analyzed your finished books, star ratings, and review notes.")
        if top_fav:
            fav_text = f"Your log highlights a great love for **{top_fav['title']}** by {top_fav['author']}"
            if top_fav.get("spice_rating"):
                fav_text += f" (with a bold {top_fav['spice_rating']}/5 🌶️ spice rating)"
            if top_fav.get("favorite_characters"):
                fav_text += f" and unforgettable characters like {top_fav['favorite_characters']}"
            reply_parts.append(f"{fav_text}. Based on that energetic, high-engagement vibe, here are the stories you'll adore next:")
        else:
            reply_parts.append("Based on the overarching vibe of our top community favorites, here are top recommendations:")
    elif is_cozy:
        reply_parts.append("🪿 *Honk!* Reginald here, settling into a comfortable wing-chair with a hot cup of tea! For cozy, heartwarming, low-stakes comfort reads, these stories will make you feel right at home:")
    elif is_thriller:
        reply_parts.append("🪿 *Honk!* Reginald here with feathers ruffled in suspense! For unputdownable, fast-paced thrillers with jaw-dropping plot twists, these will keep you reading long into the night:")
    elif is_dark_academia:
        reply_parts.append("🪿 *Honk!* Reginald here, adjusting my tweed waistcoat! For dark academia rich in ancient secrets, classical motifs, and atmospheric obsession, these are the quintessential reads:")
    else:
        if top_fav:
            reply_parts.append(f"🪿 *Honk!* Reginald here! Drawing inspiration from your finished reads like **{top_fav['title']}** by {top_fav['author']}, I've selected titles matching what you are looking for:")
        else:
            reply_parts.append("🪿 *Honk!* Reginald here, your literary goose companion. I've tailored these top recommendations for your request:")

    if recs:
        library_recs = [r for r in recs if r["in_library"] or r["on_tbr"]]
        external_recs = [r for r in recs if not r["in_library"] and not r["on_tbr"]]

        if library_recs:
            reply_parts.append(f"✨ From your collection, **{library_recs[0]['title']}** by {library_recs[0]['author']} fits your request ({'on your TBR list' if library_recs[0]['on_tbr'] else 'in your library'})!")

        if external_recs:
            ext_names = ", ".join(f"**{r['title']}**" for r in external_recs)
            reply_parts.append(f"📚 Looking beyond, my goose instincts strongly endorse {ext_names}!")

        reply_parts.append("Click **'Add to TBR'** on any book you'd like to queue, or choose your preferred book site below to search for it directly!")
    else:
        reply_parts.append("I couldn't find an exact match for that specific inquiry, but I'm always eager to discuss tropes, compare authors, or explore new book recommendations!")

    reply_message = "\n\n".join(reply_parts)

    return {
        "source": "curated_recommender",
        "reply": reply_message,
        "recommendations": recs
    }



# ==========================================
# --- 13. READING PROGRESS & STATS METRICS ---
# ==========================================

class ProgressPayload(BaseModel):
    current_page: Optional[int] = None
    page_count: Optional[int] = None
    progress_percent: Optional[int] = None
    percent: Optional[int] = None
    pages: Optional[int] = None
    current_audio_minutes: Optional[int] = None
    audio_hours: Optional[float] = None
    audio_mins: Optional[int] = None
    minutes_read: Optional[int] = 0
    notes: Optional[str] = ""
    log_session: bool = True
    date: Optional[str] = None


class DayLogPayload(BaseModel):
    date: Optional[str] = None
    book_id: Optional[int] = None
    pages_read: Optional[int] = 0
    minutes_read: Optional[int] = 0
    notes: Optional[str] = ""


def check_and_unlock_achievements(conn) -> list[dict]:
    """Checks current reading days, pages, and milestones and unlocks badges."""
    cursor = conn.cursor()
    today_str = datetime.date.today().isoformat()

    # Calculate streak
    cursor.execute("SELECT DISTINCT date FROM reading_logs")
    dates = {r[0] for r in cursor.fetchall()}
    cursor.execute("SELECT DISTINCT date_read FROM books WHERE is_read = 1 AND date_read != ''")
    for r in cursor.fetchall():
        dates.add(r[0])

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    current_streak = 0
    check_date = today
    if today.isoformat() not in dates and yesterday.isoformat() in dates:
        check_date = yesterday

    while check_date.isoformat() in dates:
        current_streak += 1
        check_date -= datetime.timedelta(days=1)

    # Total pages: finished books + currently reading in-progress pages
    cursor.execute("SELECT SUM(CASE WHEN page_count > 0 THEN page_count ELSE current_page END) FROM books WHERE is_read = 1")
    b_pages = cursor.fetchone()[0] or 0
    cursor.execute("""
        SELECT SUM(CASE 
            WHEN current_page > 0 THEN current_page 
            WHEN page_count > 0 AND progress_percent > 0 THEN CAST(ROUND(page_count * progress_percent / 100.0) AS INTEGER)
            ELSE 0 
        END) FROM books WHERE is_read = 0 AND (current_page > 0 OR progress_percent > 0)
    """)
    in_prog_pages = cursor.fetchone()[0] or 0
    total_pages = b_pages + in_prog_pages

    # Audio hours
    cursor.execute("SELECT duration FROM books WHERE is_read = 1 AND media_type = 'audiobook'")
    dur_rows = cursor.fetchall()
    audio_mins = 0
    for dr in dur_rows:
        dur = dr[0] or ""
        m_h = re.search(r"(\d+)\s*h", dur)
        m_m = re.search(r"(\d+)\s*m", dur)
        hours = int(m_h.group(1)) if m_h else 0
        mins = int(m_m.group(1)) if m_m else 0
        audio_mins += hours * 60 + mins
    audio_hours = audio_mins / 60

    # Spicy books
    cursor.execute("SELECT COUNT(*) FROM books WHERE is_read = 1 AND spice_rating >= 3")
    spicy_count = cursor.fetchone()[0] or 0

    # Reviews written
    cursor.execute("SELECT COUNT(*) FROM books WHERE (review != '' OR review_headline != '' OR favorite_quotes != '')")
    review_count = cursor.fetchone()[0] or 0

    # Completed series
    cursor.execute("SELECT series_name, COUNT(*), SUM(is_read) FROM books WHERE series_name != '' GROUP BY series_name")
    series_rows = cursor.fetchall()
    completed_series_count = sum(1 for sr in series_rows if sr[1] > 0 and sr[1] == sr[2])

    total_days_read = len(dates)
    cursor.execute("SELECT COUNT(*) FROM books WHERE is_read = 1")
    books_finished_count = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM books WHERE is_read = 1 AND spice_rating >= 4")
    spicy_4_count = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM books WHERE reading_status = 'tbr' AND is_read = 0")
    tbr_count = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM books WHERE tropes != '' OR genres LIKE '%Romance%' OR genres LIKE '%Fantasy%'")
    trope_count = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM books WHERE series_name LIKE '%Hades%' OR series_name LIKE '%Olympus%' OR genres LIKE '%Mythology%' OR title LIKE '%God%' OR title LIKE '%Greek%'")
    myth_count = cursor.fetchone()[0] or 0

    cursor.execute("SELECT MAX(pages_read) FROM reading_logs")
    max_single_session_pgs = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM books WHERE is_read = 1 AND rating = 5")
    five_star_count = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM books WHERE favorite_quotes != ''")
    quote_count = cursor.fetchone()[0] or 0

    cursor.execute("SELECT MAX(cnt) FROM (SELECT COUNT(*) as cnt FROM books WHERE is_read = 1 GROUP BY author)")
    res_max_author = cursor.fetchone()
    max_author_count = res_max_author[0] if res_max_author and res_max_author[0] else 0

    cursor.execute("SELECT genres FROM books WHERE is_read = 1 AND genres != ''")
    all_genres_set = set()
    for gr in cursor.fetchall():
        for tok in (gr[0] or "").split(","):
            if tok.strip():
                all_genres_set.add(tok.strip().lower())
    distinct_genres_count = len(all_genres_set)

    weekend_days = 0
    for d_str in dates:
        try:
            if datetime.date.fromisoformat(d_str).weekday() in (5, 6):
                weekend_days += 1
        except Exception:
            pass

    criteria = {
        "days_3": total_days_read >= 3,
        "days_7": total_days_read >= 7,
        "days_14": total_days_read >= 14,
        "days_30": total_days_read >= 30,
        "days_60": total_days_read >= 60,
        "days_100": total_days_read >= 100,
        "days_180": total_days_read >= 180,
        "days_365": total_days_read >= 365,
        "pages_250": total_pages >= 250,
        "pages_1000": total_pages >= 1000,
        "pages_2500": total_pages >= 2500,
        "pages_5000": total_pages >= 5000,
        "pages_10000": total_pages >= 10000,
        "books_finished_1": books_finished_count >= 1,
        "books_finished_3": books_finished_count >= 3,
        "books_finished_5": books_finished_count >= 5,
        "books_finished_10": books_finished_count >= 10,
        "books_finished_20": books_finished_count >= 20,
        "books_finished_50": books_finished_count >= 50,
        "audio_5h": audio_hours >= 5,
        "audio_15h": audio_hours >= 15,
        "audio_30h": audio_hours >= 30,
        "spice_lover": spicy_count >= 1,
        "spice_fiend": spicy_4_count >= 3,
        "five_star_club": five_star_count >= 3,
        "quote_collector": quote_count >= 3,
        "author_loyalist": max_author_count >= 3,
        "genre_explorer": distinct_genres_count >= 4,
        "weekend_warrior": weekend_days >= 5,
        "quick_checkin": today_str in dates,
        "series_finisher": completed_series_count >= 1,
        "critic_3": review_count >= 2,
        "tbr_hoarder": tbr_count >= 3,
        "trope_hunter": trope_count >= 2,
        "mythology_reader": myth_count >= 1,
        "fast_reader": (max_single_session_pgs >= 50 or total_pages >= 300),
    }

    newly_unlocked = []
    for badge_id, met in criteria.items():
        if met:
            cursor.execute("SELECT unlocked_at, name, description, icon, reward_title FROM user_achievements WHERE badge_id = ?", (badge_id,))
            badge_row = cursor.fetchone()
            if badge_row and not badge_row[0]:
                cursor.execute("UPDATE user_achievements SET unlocked_at = ? WHERE badge_id = ?", (today_str, badge_id))
                newly_unlocked.append({
                    "badge_id": badge_id,
                    "name": badge_row[1],
                    "description": badge_row[2],
                    "icon": badge_row[3],
                    "reward_title": badge_row[4],
                })

    conn.commit()
    return newly_unlocked


@app.post("/books/{book_id}/progress")
def update_book_progress(book_id: int, payload: ProgressPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, page_count, current_page, progress_percent, reading_status, is_read, media_type, duration, current_audio_minutes FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Book not found")

    old_total_pages = row[2] or 0
    old_current_page = row[3] or 0
    old_percent = row[4] or 0
    old_status = row[5] or "tbr"
    old_is_read = bool(row[6])
    media_type = row[7] or "ebook"
    duration_str = row[8] or ""
    old_audio_mins = row[9] or 0

    # Parse audiobook duration
    total_audio_mins = 0
    if duration_str:
        m_h = re.search(r"(\d+)\s*h", duration_str)
        m_m = re.search(r"(\d+)\s*m", duration_str)
        total_audio_mins = (int(m_h.group(1)) if m_h else 0) * 60 + (int(m_m.group(1)) if m_m else 0)

    # Audio progress handling
    current_audio_minutes = old_audio_mins
    if media_type == "audiobook" or payload.current_audio_minutes is not None or payload.audio_hours is not None:
        if payload.current_audio_minutes is not None:
            current_audio_minutes = max(0, int(payload.current_audio_minutes))
            if total_audio_mins > 0:
                percent = min(100, max(0, round((current_audio_minutes / float(total_audio_mins)) * 100)))
            elif payload.progress_percent is not None:
                percent = max(0, min(100, int(payload.progress_percent)))
            else:
                percent = old_percent
        elif payload.audio_hours is not None:
            current_audio_minutes = max(0, int(round(payload.audio_hours * 60)) + (payload.audio_mins or 0))
            if total_audio_mins > 0:
                percent = min(100, max(0, round((current_audio_minutes / float(total_audio_mins)) * 100)))
            elif payload.progress_percent is not None:
                percent = max(0, min(100, int(payload.progress_percent)))
            else:
                percent = old_percent
        elif payload.progress_percent is not None or payload.percent is not None:
            pct_val = payload.progress_percent if payload.progress_percent is not None else payload.percent
            percent = max(0, min(100, int(pct_val)))
            if total_audio_mins > 0:
                current_audio_minutes = round((percent / 100.0) * total_audio_mins)
        else:
            percent = old_percent
        current_page = old_current_page
        total_pages = old_total_pages
    else:
        # Ebook page / percent handling
        req_current_page = payload.current_page if payload.current_page is not None else payload.pages
        req_percent = payload.progress_percent if payload.progress_percent is not None else payload.percent
        total_pages = payload.page_count if payload.page_count is not None and payload.page_count > 0 else old_total_pages

        if req_current_page is not None and req_percent is not None:
            current_page = max(0, int(req_current_page))
            percent = max(0, min(100, int(req_percent)))
            if total_pages > 0 and current_page > total_pages:
                current_page = total_pages
        elif req_current_page is not None:
            current_page = max(0, int(req_current_page))
            if total_pages > 0:
                if current_page > total_pages:
                    current_page = total_pages
                percent = round((current_page / float(total_pages)) * 100)
            else:
                percent = old_percent
        elif req_percent is not None:
            percent = max(0, min(100, int(req_percent)))
            if total_pages > 0:
                current_page = round((percent / 100.0) * total_pages)
            else:
                current_page = old_current_page
        else:
            current_page = old_current_page
            percent = old_percent

    # Auto shelf logic
    today_str = (payload.date or datetime.date.today().isoformat()).strip()
    is_completed = (percent >= 100) or (total_pages > 0 and current_page >= total_pages) or (total_audio_mins > 0 and current_audio_minutes >= total_audio_mins)
    if is_completed:
        new_status = "read"
        new_is_read = 1
        date_read_val = today_str
        percent = 100
        if total_pages > 0:
            current_page = total_pages
        if total_audio_mins > 0:
            current_audio_minutes = total_audio_mins
    elif percent > 0 or current_page > 0 or current_audio_minutes > 0:
        new_status = "reading"
        new_is_read = 0
        date_read_val = ""
    else:
        new_status = old_status if old_status != "unread" else "tbr"
        new_is_read = 1 if new_status == "read" else 0
        date_read_val = today_str if new_is_read else ""

    cursor.execute("""
        UPDATE books
        SET page_count = ?, current_page = ?, progress_percent = ?,
            current_audio_minutes = ?,
            reading_status = ?, is_read = ?,
            date_read = CASE WHEN ? != '' THEN ? ELSE date_read END
        WHERE id = ?
    """, (total_pages, current_page, percent, current_audio_minutes, new_status, new_is_read, date_read_val, date_read_val, book_id))

    # Log session for calendar tracking
    if payload.log_session:
        cursor.execute("""
            INSERT INTO reading_logs (book_id, date, pages_read, minutes_read, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (book_id, today_str, 0, payload.minutes_read or 0, payload.notes or "Progress update check-in"))

    conn.commit()
    newly_unlocked = check_and_unlock_achievements(conn)
    conn.close()

    aud_h = current_audio_minutes // 60
    aud_m = current_audio_minutes % 60
    return {
        "book_id": book_id,
        "page_count": total_pages,
        "current_page": current_page,
        "progress_percent": percent,
        "current_audio_minutes": current_audio_minutes,
        "audio_time_formatted": f"{aud_h}h {aud_m}m",
        "reading_status": new_status,
        "is_read": bool(new_is_read),
        "newly_unlocked": newly_unlocked,
        "message": f"Progress updated to {percent}% ({aud_h}h {aud_m}m)" if media_type == 'audiobook' else f"Progress updated to {percent}% ({current_page}/{total_pages} pgs)"
    }


@app.post("/stats/log-day")
def log_reading_day(payload: DayLogPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    today_str = (payload.date or datetime.date.today().isoformat()).strip()

    cursor.execute("""
        INSERT INTO reading_logs (book_id, date, pages_read, minutes_read, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (payload.book_id, today_str, payload.pages_read or 0, payload.minutes_read or 0, payload.notes or "Daily reading check-in"))
    conn.commit()

    newly_unlocked = check_and_unlock_achievements(conn)
    conn.close()

    return {
        "status": "success",
        "date": today_str,
        "message": f"Logged reading session for {today_str}! Happy reading! 📖",
        "newly_unlocked": newly_unlocked
    }


class ToggleDayPayload(BaseModel):
    date: str
    pages: Optional[int] = 0
    minutes: Optional[int] = 0
    notes: Optional[str] = "Calendar check-in"


@app.post("/stats/quick-checkin")
def quick_checkin_today():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    today_str = datetime.date.today().isoformat()
    cursor.execute("SELECT id, pages_read FROM reading_logs WHERE date = ?", (today_str,))
    row = cursor.fetchone()
    if row:
        action = "already_checked_in"
        msg = "You are already checked in for today! 🌟 Great job reading today!"
    else:
        cursor.execute("INSERT INTO reading_logs (date, pages_read, minutes_read, notes) VALUES (?, 0, 0, 'Checked in for today ✅')", (today_str,))
        action = "created"
        msg = "Marked today on your reading calendar! 🌟 Great job reading today!"
    conn.commit()
    newly_unlocked = check_and_unlock_achievements(conn)
    conn.close()
    return {"status": "success", "action": action, "date": today_str, "message": msg, "newly_unlocked": newly_unlocked}


@app.post("/stats/toggle-day")
def toggle_reading_day(payload: ToggleDayPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    d_str = payload.date.strip()
    cursor.execute("SELECT id FROM reading_logs WHERE date = ?", (d_str,))
    rows = cursor.fetchall()
    if rows:
        cursor.execute("DELETE FROM reading_logs WHERE date = ?", (d_str,))
        state = "unlogged"
        msg = f"Removed reading log for {d_str}"
    else:
        cursor.execute("""
            INSERT INTO reading_logs (date, pages_read, minutes_read, notes)
            VALUES (?, 0, 0, ?)
        """, (d_str, payload.notes or "Calendar check-in"))
        state = "logged"
        msg = f"Marked {d_str} as read!"
    conn.commit()
    newly_unlocked = check_and_unlock_achievements(conn)
    conn.close()
    return {"status": "success", "state": state, "message": msg, "date": d_str, "newly_unlocked": newly_unlocked}


# --- EDIT / FIX READING DAYS & TIMER METRICS ---
class EditDayPayload(BaseModel):
    date: str
    is_read: bool
    notes: Optional[str] = "Manual day edit"


@app.post("/stats/edit-day")
def edit_reading_day(payload: EditDayPayload):
    d_str = payload.date.strip()
    if not d_str:
        raise HTTPException(status_code=400, detail="Date required")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM reading_logs WHERE date = ?", (d_str,))
    rows = cursor.fetchall()

    if payload.is_read:
        if not rows:
            cursor.execute("INSERT INTO reading_logs (date, pages_read, minutes_read, notes) VALUES (?, 0, 0, ?)", (d_str, payload.notes or "Manual day edit"))
            msg = f"Marked {d_str} as read!"
        else:
            msg = f"{d_str} was already logged as read."
    else:
        cursor.execute("DELETE FROM reading_logs WHERE date = ?", (d_str,))
        # Also clear any date_read matching this date on books if desired
        msg = f"Unmarked {d_str} from reading logs."

    conn.commit()
    newly_unlocked = check_and_unlock_achievements(conn)
    conn.close()
    return {"status": "success", "message": msg, "date": d_str, "is_read": payload.is_read, "newly_unlocked": newly_unlocked}


class BatchDaysPayload(BaseModel):
    dates: list[str]
    is_read: bool


@app.post("/stats/batch-days")
def batch_edit_reading_days(payload: BatchDaysPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    count = 0
    for d_str in payload.dates:
        d_str = d_str.strip()
        if not d_str:
            continue
        cursor.execute("SELECT id FROM reading_logs WHERE date = ?", (d_str,))
        exists = cursor.fetchone()
        if payload.is_read and not exists:
            cursor.execute("INSERT INTO reading_logs (date, pages_read, minutes_read, notes) VALUES (?, 0, 0, 'Batch day edit')", (d_str,))
            count += 1
        elif not payload.is_read and exists:
            cursor.execute("DELETE FROM reading_logs WHERE date = ?", (d_str,))
            count += 1
    conn.commit()
    newly_unlocked = check_and_unlock_achievements(conn)
    conn.close()
    return {"status": "success", "message": f"Updated {count} reading days!", "count": count, "newly_unlocked": newly_unlocked}


class TimerSessionPayload(BaseModel):
    minutes_read: Optional[int] = None
    minutes: Optional[int] = None
    book_id: Optional[int] = None
    notes: Optional[str] = "Reading Timer Session"
    date: Optional[str] = None


@app.post("/stats/log-timer-session")
def log_timer_session(payload: TimerSessionPayload):
    mins = max(1, payload.minutes_read or payload.minutes or 1)
    d_str = (payload.date or datetime.date.today().isoformat()).strip()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reading_logs (book_id, date, pages_read, minutes_read, notes)
        VALUES (?, ?, 0, ?, ?)
    """, (payload.book_id, d_str, mins, payload.notes or "Reading Timer Session"))
    conn.commit()
    newly_unlocked = check_and_unlock_achievements(conn)
    conn.close()
    return {
        "status": "success",
        "message": f"Recorded reading session: {mins} minutes on {d_str}! ⏱️✨",
        "minutes_read": mins,
        "date": d_str,
        "newly_unlocked": newly_unlocked
    }


# --- ROMANCE.IO SPICE ENRICHMENT ENDPOINTS ---
class EnrichAllSpicePayload(BaseModel):
    force: bool = False


@app.post("/books/enrich-spice-all")
def enrich_all_books_spice(payload: Optional[EnrichAllSpicePayload] = None):
    force = payload.force if payload else False
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if force:
        cursor.execute("SELECT id, title, author FROM books WHERE (deleted_at IS NULL OR deleted_at = '')")
    else:
        cursor.execute("SELECT id, title, author FROM books WHERE (deleted_at IS NULL OR deleted_at = '') AND (spice_rating IS NULL OR spice_rating = 0)")
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return {"status": "success", "message": "All books already have spice ratings!", "updated_count": 0}

    books_to_process = [{"id": r[0], "title": r[1], "author": r[2]} for r in rows]
    # Process in chunks of 15
    chunk_size = 15
    updated_count = 0
    for i in range(0, len(books_to_process), chunk_size):
        chunk = books_to_process[i:i + chunk_size]
        results = batch_lookup_romance_io_spice(chunk)
        for b_id, data in results.items():
            spice = data.get("spice_rating", 0)
            tropes = data.get("tropes", "")
            cursor.execute("""
                UPDATE books
                SET spice_rating = ?,
                    tropes = CASE WHEN ? != '' AND (tropes IS NULL OR tropes = '') THEN ? ELSE tropes END
                WHERE id = ?
            """, (spice, tropes, tropes, b_id))
            updated_count += 1
        conn.commit()

    check_and_unlock_achievements(conn)
    conn.close()
    return {
        "status": "success",
        "message": f"Successfully enriched {updated_count} books with Romance.io spice ratings & tropes!",
        "updated_count": updated_count,
        "total_checked": len(rows)
    }


class EnrichChunkPayload(BaseModel):
    chunk_size: int = 15
    force: bool = False


@app.post("/books/enrich-spice-chunk")
def enrich_books_spice_chunk(payload: EnrichChunkPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if payload.force:
        cursor.execute("SELECT id, title, author FROM books WHERE (deleted_at IS NULL OR deleted_at = '') LIMIT ?", (payload.chunk_size,))
    else:
        cursor.execute("SELECT id, title, author FROM books WHERE (deleted_at IS NULL OR deleted_at = '') AND (spice_rating IS NULL OR spice_rating = 0) AND (tropes IS NULL OR tropes = '') LIMIT ?", (payload.chunk_size,))
    rows = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM books WHERE (deleted_at IS NULL OR deleted_at = '') AND (spice_rating IS NULL OR spice_rating = 0) AND (tropes IS NULL OR tropes = '')")
    remaining_total = cursor.fetchone()[0]

    if not rows:
        conn.close()
        return {"status": "success", "remaining": 0, "processed": 0, "done": True, "message": "All books are enriched!"}

    books_to_process = [{"id": r[0], "title": r[1], "author": r[2]} for r in rows]
    results = batch_lookup_romance_io_spice(books_to_process)
    updated = 0
    for b_id, data in results.items():
        spice = data.get("spice_rating", 0)
        tropes = data.get("tropes", "")
        cursor.execute("""
            UPDATE books
            SET spice_rating = ?,
                tropes = CASE WHEN ? != '' AND (tropes IS NULL OR tropes = '') THEN ? ELSE tropes END
            WHERE id = ?
        """, (spice, tropes, tropes, b_id))
        updated += 1
    conn.commit()
    check_and_unlock_achievements(conn)
    conn.close()
    return {
        "status": "success",
        "processed": len(rows),
        "updated": updated,
        "remaining": max(0, remaining_total - len(rows)),
        "done": (remaining_total - len(rows)) <= 0
    }


@app.post("/books/{book_id}/enrich-spice")
def enrich_single_book_spice(book_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT title, author, tropes FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Book not found")
    title, author, current_tropes = row[0], row[1], row[2] or ""
    spice_data = lookup_romance_io_spice(title, author)
    spice = spice_data.get("spice_rating", 0)
    new_tropes = spice_data.get("tropes", "")
    final_tropes = new_tropes if new_tropes else current_tropes
    cursor.execute("UPDATE books SET spice_rating = ?, tropes = ? WHERE id = ?", (spice, final_tropes, book_id))
    conn.commit()
    check_and_unlock_achievements(conn)
    cursor.execute(f"SELECT {SELECT_COLS} FROM books WHERE id = ?", (book_id,))
    updated_row = cursor.fetchone()
    conn.close()
    clean_t, clean_a = clean_book_query_info(title, author)
    romance_url = f"https://www.romance.io/search?query={urllib.parse.quote_plus((clean_t + ' ' + clean_a).strip())}"
    return {
        "status": "success",
        "spice_rating": spice,
        "tropes": final_tropes,
        "romance_io_url": romance_url,
        "book": row_to_book(updated_row),
        "message": f"Updated '{title}' with Romance.io rating: {spice} 🌶️!"
    }


# --- FATES ORACLE & REGINALD CHAT RECOMMENDATIONS ---
class OracleChatPayload(BaseModel):
    message: Optional[str] = ""
    vibes: list[str] = []
    media_type: Optional[str] = "any"
    shelf: Optional[str] = "tbr"
    has_file_only: bool = False
    rejected_count: int = 0
    rejected_titles: list[str] = []


class OracleExternalPayload(BaseModel):
    vibes: list[str] = []
    media_type: Optional[str] = "any"
    spice_min: Optional[int] = 0


@app.post("/oracle/external-recommendation")
def get_oracle_external_recommendation(payload: OracleExternalPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT LOWER(TRIM(title)) FROM books WHERE deleted_at IS NULL OR deleted_at = ''")
    owned_titles = set(r[0] for r in cursor.fetchall())
    conn.close()

    rec = generate_external_oracle_recommendation(payload.vibes, owned_titles, payload.media_type or "any", payload.spice_min or 0)
    if rec and not rec.get("cover_url"):
        try:
            candidates = search_online_metadata_candidates(f"{rec['title']} {rec.get('author', '')}", limit=1)
            if candidates and candidates[0].get("cover_url"):
                rec["cover_url"] = candidates[0]["cover_url"]
        except Exception:
            pass
    return rec


@app.post("/oracle/chat-recommendation")
def get_oracle_chat_recommendation(payload: OracleChatPayload):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Query books from user's library
    cursor.execute(f"SELECT {SELECT_COLS} FROM books WHERE (deleted_at IS NULL OR deleted_at = '')")
    all_rows = cursor.fetchall()
    conn.close()
    all_books = [row_to_book(r) for r in all_rows]

    owned_titles_set = set(b["title"].lower().strip() for b in all_books)

    # If rejected_count >= 3: go straight to external recommendation!
    if payload.rejected_count >= 3:
        rec = generate_external_oracle_recommendation(payload.vibes, owned_titles_set, payload.media_type or "any", 0)
        if rec and not rec.get("cover_url"):
            try:
                candidates = search_online_metadata_candidates(f"{rec['title']} {rec.get('author', '')}", limit=1)
                if candidates and candidates[0].get("cover_url"):
                    rec["cover_url"] = candidates[0]["cover_url"]
            except Exception:
                pass
        return {
            "type": "external_pick",
            "rejection_count": payload.rejected_count,
            "book": {
                "id": None,
                "title": rec.get("title", "Unknown Title"),
                "author": rec.get("author", "Unknown Author"),
                "spice_rating": rec.get("spice_rating", 4),
                "tropes": rec.get("tropes", ""),
                "pitch": rec.get("pitch", ""),
                "cover_url": rec.get("cover_url", ""),
                "in_library": False
            },
            "reginald_message": rec.get("reginald_oracle_commentary") or f"Honk! Three offerings rejected? The Fates hear your restless spirit. Your current shelves do not have the spark you seek today, so I have spread my wings beyond your library walls into the wider romantasy realm...",
            "vibe_tags": payload.vibes
        }

    # Filter candidate books from library
    candidates = all_books
    if payload.shelf == "tbr":
        candidates = [b for b in candidates if b.get("reading_status") == "tbr" and not b.get("is_read")]
    elif payload.shelf == "unread":
        candidates = [b for b in candidates if not b.get("is_read")]

    if payload.has_file_only:
        candidates = [b for b in candidates if b.get("has_file")]

    if payload.media_type in ("ebook", "audiobook"):
        candidates = [b for b in candidates if b.get("media_type") == payload.media_type]

    # Filter out already rejected titles in this session
    rej_set = set(t.lower().strip() for t in payload.rejected_titles)
    candidates = [b for b in candidates if b["title"].lower().strip() not in rej_set]

    # Score by vibes
    active_vibes = [v.lower().strip() for v in (payload.vibes or []) if v.strip()]
    if payload.message and payload.message.strip():
        active_vibes.extend([w.lower() for w in re.split(r'[,; ]+', payload.message) if len(w) > 3])

    def score_book(b):
        score = 0
        text_corpus = f"{b.get('title', '')} {b.get('author', '')} {b.get('tropes', '')} {b.get('genres', '')} {b.get('description', '')}".lower()
        spice = b.get("spice_rating", 0)
        for v in active_vibes:
            if "spice" in v or "chili" in v or "steamy" in v:
                if spice >= 4: score += 5
                elif spice >= 3: score += 3
            if v in text_corpus:
                score += 3
        score += random.random() * 2
        return score

    if active_vibes and candidates:
        candidates.sort(key=score_book, reverse=True)

    # If library has candidates:
    if candidates:
        picked = candidates[0]
        spice_note = f"{picked.get('spice_rating', 0)}/5 🌶️" if picked.get('spice_rating') else "unrated spice"
        vibe_mention = f"with {', '.join(payload.vibes[:2])}" if payload.vibes else "from your shelves"
        reginald_quips = [
            f"Honk! The Fates have woven their golden threads and selected '{picked['title']}' by {picked['author']}! A splendid match {vibe_mention} ({spice_note})!",
            f"Honk honk! Gaze upon your destiny: '{picked['title']}'! My goose instincts tell me you will devour this one.",
            f"By the feathers of destiny! '{picked['title']}' has risen to the top of your queue ({spice_note}). Prepare your tea and blankets!"
        ]
        reginald_msg = random.choice(reginald_quips)
        return {
            "type": "library_pick",
            "rejection_count": payload.rejected_count,
            "book": picked,
            "reginald_message": reginald_msg,
            "vibe_tags": payload.vibes
        }
    else:
        # No library matches left: automatically suggest external!
        rec = generate_external_oracle_recommendation(payload.vibes, owned_titles_set, payload.media_type or "any", 0)
        if rec and not rec.get("cover_url"):
            try:
                candidates_ext = search_online_metadata_candidates(f"{rec['title']} {rec.get('author', '')}", limit=1)
                if candidates_ext and candidates_ext[0].get("cover_url"):
                    rec["cover_url"] = candidates_ext[0]["cover_url"]
            except Exception:
                pass
        return {
            "type": "external_pick",
            "rejection_count": max(3, payload.rejected_count),
            "book": {
                "id": None,
                "title": rec.get("title", "Unknown Title"),
                "author": rec.get("author", "Unknown Author"),
                "spice_rating": rec.get("spice_rating", 4),
                "tropes": rec.get("tropes", ""),
                "pitch": rec.get("pitch", ""),
                "cover_url": rec.get("cover_url", ""),
                "in_library": False
            },
            "reginald_message": rec.get("reginald_oracle_commentary") or f"Honk! Your library ran out of matching tales, so I have journeyed beyond to fetch you '{rec.get('title')}'!",
            "vibe_tags": payload.vibes
        }


# --- LOCAL COMPUTER FOLDER SCANNER ---
class ScanFolderPayload(BaseModel):
    folder_path: Optional[str] = ""


class ImportScannedFilesPayload(BaseModel):
    file_paths: list[str]


@app.post("/scanner/scan-folder")
def scan_local_folder(payload: ScanFolderPayload):
    target_dir = (payload.folder_path or "").strip()
    if not target_dir:
        target_dir = INBOX_DIR

    if not os.path.exists(target_dir):
        raise HTTPException(status_code=400, detail=f"Directory does not exist: {target_dir}")
    if not os.path.isdir(target_dir):
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {target_dir}")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT filename, title FROM books WHERE deleted_at IS NULL OR deleted_at = ''")
    existing_files = set()
    existing_titles = set()
    for fn, t in cursor.fetchall():
        if fn:
            existing_files.add(fn.lower().strip())
        if t:
            existing_titles.add(t.lower().strip())
    conn.close()

    allowed_exts = {".epub", ".pdf", ".mobi", ".azw3", ".m4b", ".mp3", ".m4a"}
    found_items = []

    for root, _, files in os.walk(target_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in allowed_exts:
                full_path = os.path.join(root, f)
                base_name = f
                clean_name = clean_search_query_from_filename(base_name)
                is_audio = ext in AUDIO_EXTENSIONS
                try:
                    size_mb = round(os.path.getsize(full_path) / (1024 * 1024), 2)
                except Exception:
                    size_mb = 0.0

                already_imported = (base_name.lower().strip() in existing_files) or (clean_name.lower().strip() in existing_titles)

                found_items.append({
                    "full_path": full_path,
                    "filename": base_name,
                    "clean_title": clean_name,
                    "extension": ext.replace(".", "").upper(),
                    "size_mb": size_mb,
                    "media_type": "audiobook" if is_audio else "ebook",
                    "already_in_library": already_imported
                })

    found_items.sort(key=lambda x: (x["already_in_library"], x["clean_title"].lower()))

    return {
        "folder_path": target_dir,
        "total_found": len(found_items),
        "new_count": len([x for x in found_items if not x["already_in_library"]]),
        "files": found_items
    }


@app.post("/scanner/import-files")
def import_scanned_files(payload: ImportScannedFilesPayload):
    imported_books = []
    errors = []

    for fp in payload.file_paths:
        if not os.path.exists(fp):
            errors.append(f"File not found: {fp}")
            continue
        try:
            with open(fp, "rb") as f:
                fbytes = f.read()
            orig_name = os.path.basename(fp)
            res = save_uploaded_book_file(
                file_bytes=fbytes,
                original_filename=orig_name,
                auto_rename_if_exists=True,
                reading_status_override="tbr"
            )
            imported_books.append(res)
        except Exception as e:
            errors.append(f"{os.path.basename(fp)}: {str(e)}")

    return {
        "status": "success",
        "imported_count": len(imported_books),
        "imported": imported_books,
        "errors": errors
    }


@app.get("/stats/years")
def get_available_stats_years():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT SUBSTR(date, 1, 4) FROM reading_logs WHERE date != ''")
    years = {r[0] for r in cursor.fetchall() if r[0] and len(r[0]) == 4}
    cursor.execute("SELECT DISTINCT SUBSTR(date_read, 1, 4) FROM books WHERE is_read = 1 AND date_read != ''")
    for r in cursor.fetchall():
        if r[0] and len(r[0]) == 4:
            years.add(r[0])
    conn.close()

    current_yr = str(datetime.date.today().year)
    years.add(current_yr)
    sorted_years = sorted(list(years), reverse=True)
    return {"years": sorted_years, "current_year": current_yr}


@app.get("/stats/overview")
def get_stats_overview_endpoint(year: Optional[str] = "2026"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    current_yr = str(datetime.date.today().year)
    target_year = (year or current_yr).strip().lower()

    # 1. Read books in year (excluding trashed books)
    if target_year == "all":
        cursor.execute("SELECT id, title, author, media_type, duration, page_count, rating, spice_rating, pace, genres, date_read, series_name FROM books WHERE is_read = 1 AND (deleted_at IS NULL OR deleted_at = '')")
    else:
        cursor.execute("""
            SELECT id, title, author, media_type, duration, page_count, rating, spice_rating, pace, genres, date_read, series_name
            FROM books
            WHERE is_read = 1 AND (deleted_at IS NULL OR deleted_at = '') AND (date_read LIKE ? OR (date_read = '' AND ? = ?))
        """, (f"{target_year}%", target_year, current_yr))
    read_rows = cursor.fetchall()

    books_read_count = len(read_rows)
    ebooks_read = [r for r in read_rows if r[3] != "audiobook"]
    audiobooks_read = [r for r in read_rows if r[3] == "audiobook"]

    # 2. Total pages read (finished books + currently reading in-progress books)
    book_pages = sum(r[5] or 0 for r in read_rows)
    in_progress_pages = 0
    if target_year == "all" or target_year == current_yr:
        cursor.execute("""
            SELECT COALESCE(SUM(CASE 
                WHEN current_page > 0 THEN current_page 
                WHEN page_count > 0 AND progress_percent > 0 THEN CAST(ROUND(page_count * progress_percent / 100.0) AS INTEGER)
                ELSE 0 
            END), 0)
            FROM books
            WHERE is_read = 0 AND (deleted_at IS NULL OR deleted_at = '') AND (current_page > 0 OR progress_percent > 0)
        """)
        in_progress_pages = cursor.fetchone()[0] or 0
    total_pages = book_pages + in_progress_pages

    # Audiobook hours (finished audiobooks + in-progress audiobook minutes)
    audio_minutes = 0
    for r in audiobooks_read:
        dur = r[4] or ""
        m_h = re.search(r"(\d+)\s*h", dur)
        m_m = re.search(r"(\d+)\s*m", dur)
        hours = int(m_h.group(1)) if m_h else 0
        mins = int(m_m.group(1)) if m_m else 0
        audio_minutes += (hours * 60 + mins)

    in_prog_audio_mins = 0
    if target_year == "all" or target_year == current_yr:
        cursor.execute("""
            SELECT duration, current_audio_minutes, progress_percent
            FROM books
            WHERE is_read = 0 AND media_type = 'audiobook' AND (deleted_at IS NULL OR deleted_at = '') AND (current_audio_minutes > 0 OR progress_percent > 0)
        """)
        for dur, cur_m, pct in cursor.fetchall():
            if cur_m and cur_m > 0:
                in_prog_audio_mins += cur_m
            elif dur and pct and pct > 0:
                m_h = re.search(r"(\d+)\s*h", dur)
                m_m = re.search(r"(\d+)\s*m", dur)
                tot = (int(m_h.group(1)) if m_h else 0) * 60 + (int(m_m.group(1)) if m_m else 0)
                if tot > 0:
                    in_prog_audio_mins += int(round(tot * (pct / 100.0)))

    total_audio_minutes = audio_minutes + in_prog_audio_mins
    total_audio_hours = round(total_audio_minutes / 60.0, 1)
    aud_h = total_audio_minutes // 60
    aud_m = total_audio_minutes % 60
    audio_time_formatted = f"{aud_h}h {aud_m}m" if aud_h > 0 else f"{aud_m}m"

    # Reading Timer Metrics
    cursor.execute("SELECT COALESCE(SUM(minutes_read), 0), COUNT(CASE WHEN minutes_read > 0 THEN 1 END) FROM reading_logs")
    t_row = cursor.fetchone()
    total_timer_minutes = t_row[0] or 0
    timer_sessions_count = t_row[1] or 0
    total_timer_hours = round(total_timer_minutes / 60.0, 1)

    # 3. Days Read (No streaks)
    cursor.execute("SELECT DISTINCT date FROM reading_logs ORDER BY date DESC")
    log_dates = {row[0] for row in cursor.fetchall()}
    cursor.execute("SELECT DISTINCT date_read FROM books WHERE is_read = 1 AND date_read != ''")
    for r in cursor.fetchall():
        log_dates.add(r[0])

    today = datetime.date.today()
    total_days_read = len(log_dates)
    days_read_in_year = sum(1 for d in log_dates if target_year == "all" or d.startswith(target_year))
    current_streak = 0
    longest_streak = 0

    last_7_days = []
    for i in range(6, -1, -1):
        day_i = today - datetime.timedelta(days=i)
        d_str = day_i.isoformat()
        last_7_days.append({
            "date": d_str,
            "day_name": day_i.strftime("%a"),
            "day_num": day_i.day,
            "is_today": (day_i == today),
            "read": (d_str in log_dates)
        })

    # 4. Genre breakdown
    genre_counts = {}
    for r in read_rows:
        raw_g = (r[9] or "")
        tokens = [t.strip().title() for t in raw_g.split(",") if t.strip()]
        for tok in tokens:
            genre_counts[tok] = genre_counts.get(tok, 0) + 1

    sorted_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)

    # 5. Author Loyalty
    if target_year == "all":
        cursor.execute("""
            SELECT author, COUNT(*) as read_cnt
            FROM books
            WHERE is_read = 1
            GROUP BY author
            ORDER BY read_cnt DESC, author ASC
        """ )
    else:
        cursor.execute("""
            SELECT author, COUNT(*) as read_cnt
            FROM books
            WHERE is_read = 1 AND (date_read LIKE ? OR (date_read = '' AND ? = ?))
            GROUP BY author
            ORDER BY read_cnt DESC, author ASC
        """, (f"{target_year}%", target_year, current_yr))
    author_loyalty = [{"author": r[0], "read_count": r[1]} for r in cursor.fetchall()]

    # 6. Series Completion Tracker & Missing Books
    cursor.execute("""
        SELECT id, title, author, series_name, series_number, is_read, reading_status, media_type
        FROM books
        WHERE series_name != ''
    """)
    all_series_books = cursor.fetchall()

    series_map = {}
    for r in all_series_books:
        s_name = r[3].strip()
        if s_name not in series_map:
            series_map[s_name] = []
        series_map[s_name].append({
            "id": r[0],
            "title": r[1],
            "author": r[2],
            "number": r[4],
            "is_read": bool(r[5]),
            "reading_status": r[6],
            "media_type": r[7]
        })

    cursor.execute("SELECT series_name, next_number, next_title, author FROM series_overrides")
    override_rows = cursor.fetchall()
    overrides_map = {r[0].lower().strip(): {"number": r[1], "title": r[2], "author": r[3]} for r in override_rows}

    series_progress = []
    for s_name, books in series_map.items():
        total_owned = len(books)
        total_read = sum(1 for b in books if b["is_read"])
        pct = round((total_read / total_owned) * 100) if total_owned else 0
        sorted_b = sorted(books, key=lambda x: parse_series_num(x["number"]))
        series_author = books[0]["author"]

        owned_nums = {parse_series_num(b["number"]): b for b in sorted_b if parse_series_num(b["number"]) < 900}
        read_nums = {parse_series_num(b["number"]) for b in sorted_b if b["is_read"] and parse_series_num(b["number"]) < 900}
        unread_owned = [b for b in sorted_b if not b["is_read"]]

        next_book = None
        missing_books = []

        s_key = s_name.lower().strip()
        if s_key in overrides_map:
            ov = overrides_map[s_key]
            ov_num = ov["number"]
            ov_title = ov["title"]
            ov_author = ov["author"] or series_author
            matching_owned = next((b for b in sorted_b if b["title"].lower().strip() == ov_title.lower().strip() or parse_series_num(b["number"]) == parse_series_num(ov_num)), None)
            if matching_owned:
                next_book = {
                    "id": matching_owned["id"],
                    "title": matching_owned["title"],
                    "author": matching_owned["author"],
                    "series_name": s_name,
                    "number": matching_owned["number"],
                    "is_read": bool(matching_owned["is_read"]),
                    "is_owned": True,
                    "is_override": True,
                    "reading_status": matching_owned["reading_status"],
                    "media_type": matching_owned["media_type"],
                    "search_links": build_search_links(matching_owned["title"], matching_owned["author"])
                }
            else:
                next_book = {
                    "id": None,
                    "title": ov_title,
                    "author": ov_author,
                    "series_name": s_name,
                    "number": ov_num,
                    "is_read": False,
                    "is_owned": False,
                    "is_override": True,
                    "reading_status": "unowned",
                    "media_type": "ebook",
                    "search_links": build_search_links(ov_title, ov_author)
                }
        elif read_nums:
            max_read = max(read_nums)
            target_next_num = max_read + 1.0
            if target_next_num in owned_nums:
                target_book = owned_nums[target_next_num]
                if not target_book["is_read"]:
                    next_book = {
                        "id": target_book["id"],
                        "title": target_book["title"],
                        "author": target_book["author"],
                        "series_name": s_name,
                        "number": target_book["number"],
                        "is_read": False,
                        "is_owned": True,
                        "reading_status": target_book["reading_status"],
                        "media_type": target_book["media_type"],
                        "search_links": build_search_links(target_book["title"], target_book["author"])
                    }
                else:
                    curr = target_next_num + 1.0
                    while curr in owned_nums and owned_nums[curr]["is_read"]:
                        curr += 1.0
                    if curr in owned_nums:
                        b_curr = owned_nums[curr]
                        next_book = {
                            "id": b_curr["id"],
                            "title": b_curr["title"],
                            "author": b_curr["author"],
                            "series_name": s_name,
                            "number": b_curr["number"],
                            "is_read": False,
                            "is_owned": True,
                            "reading_status": b_curr["reading_status"],
                            "media_type": b_curr["media_type"],
                            "search_links": build_search_links(b_curr["title"], b_curr["author"])
                        }
                    else:
                        next_book = resolve_series_next_book(s_name, series_author, curr)
            else:
                next_book = resolve_series_next_book(s_name, series_author, target_next_num)
        else:
            if unread_owned:
                first_unread = unread_owned[0]
                first_num = parse_series_num(first_unread["number"])
                next_book = {
                    "id": first_unread["id"],
                    "title": first_unread["title"],
                    "author": first_unread["author"],
                    "series_name": s_name,
                    "number": first_unread["number"],
                    "is_read": False,
                    "is_owned": True,
                    "reading_status": first_unread["reading_status"],
                    "media_type": first_unread["media_type"],
                    "search_links": build_search_links(first_unread["title"], first_unread["author"])
                }
                if first_num > 1.0 and first_num < 20.0:
                    for missing_n in range(1, int(first_num)):
                        mb = resolve_series_next_book(s_name, series_author, float(missing_n))
                        if mb:
                            missing_books.append(mb)
            else:
                next_book = resolve_series_next_book(s_name, series_author, 1.0)

        # Gaps check between owned books
        if sorted_b:
            min_num = min([parse_series_num(b["number"]) for b in sorted_b if parse_series_num(b["number"]) < 900] or [1.0])
            max_num = max([parse_series_num(b["number"]) for b in sorted_b if parse_series_num(b["number"]) < 900] or [1.0])
            if max_num - min_num > 1.0 and max_num < 30.0:
                for gap_n in range(int(min_num) + 1, int(max_num)):
                    if float(gap_n) not in owned_nums:
                        gb = resolve_series_next_book(s_name, series_author, float(gap_n))
                        if gb and not any(m["number"] == gb["number"] for m in missing_books) and (not next_book or next_book["number"] != gb["number"]):
                            missing_books.append(gb)

        is_complete = (next_book is None)
        next_links = next_book["search_links"] if next_book else None

        series_progress.append({
            "series_name": s_name,
            "author": series_author,
            "total_owned": total_owned,
            "total_read": total_read,
            "percent_completed": pct,
            "all_books": sorted_b,
            "next_book": next_book,
            "next_links": next_links,
            "missing_books": missing_books,
            "has_next": bool(next_book),
            "is_complete": is_complete
        })

    series_progress.sort(key=lambda s: (s["is_complete"], -s["total_read"], s["series_name"]))

    # 7. Achievements & Badges
    cursor.execute("""
        SELECT badge_id, name, description, icon, category, unlocked_at, reward_title
        FROM user_achievements
        ORDER BY CASE WHEN unlocked_at IS NOT NULL THEN 0 ELSE 1 END, badge_id ASC
    """)
    badges = []
    for r in cursor.fetchall():
        badges.append({
            "badge_id": r[0],
            "name": r[1],
            "description": r[2],
            "icon": r[3],
            "category": r[4],
            "unlocked": bool(r[5]),
            "unlocked_at": r[5],
            "reward_title": r[6]
        })

    unlocked_badges_cnt = sum(1 for b in badges if b["unlocked"])
    total_badges_cnt = len(badges)
    rewards_pct = round((unlocked_badges_cnt / total_badges_cnt) * 100) if total_badges_cnt else 0

    if rewards_pct >= 90:
        rewards_rank = "Grand High Priestess of Stories"
    elif rewards_pct >= 75:
        rewards_rank = "High Fae Scholar of the House of Wind"
    elif rewards_pct >= 50:
        rewards_rank = "Inner Circle Companion of Velaris"
    elif rewards_pct >= 25:
        rewards_rank = "Wingleader of the Quadrant"
    elif rewards_pct >= 10:
        rewards_rank = "Initiate of the Night Court"
    else:
        rewards_rank = "Novice Scribe of the Archives"

    # Average ratings & spice
    ratings = [r[6] for r in read_rows if r[6] and r[6] > 0]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0.0
    spices = [r[7] for r in read_rows if r[7] and r[7] > 0]
    avg_spice = round(sum(spices) / len(spices), 1) if spices else 0.0

    # Star rating distribution (1 to 5)
    rating_distribution = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    for r in read_rows:
        rt = int(round(r[6] or 0))
        if rt in rating_distribution:
            rating_distribution[rt] += 1

    # Spice distribution (0 to 5)
    spice_distribution = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0, 0: 0}
    for r in read_rows:
        sp = int(round(r[7] or 0))
        if sp in spice_distribution:
            spice_distribution[sp] += 1
        else:
            spice_distribution[0] += 1

    # Monthly pages & books breakdown for the selected year
    months_data = []
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    cur_m_idx = datetime.date.today().month
    for m_idx in range(1, 13):
        m_str = f"{m_idx:02d}"
        if target_year == "all":
            cursor.execute("SELECT SUM(page_count), COUNT(*) FROM books WHERE is_read = 1 AND (deleted_at IS NULL OR deleted_at = '') AND date_read LIKE ?", (f"____-{m_str}-%",))
        else:
            cursor.execute("SELECT SUM(page_count), COUNT(*) FROM books WHERE is_read = 1 AND (deleted_at IS NULL OR deleted_at = '') AND date_read LIKE ?", (f"{target_year}-{m_str}-%",))
        m_book_res = cursor.fetchone()
        m_book_pages = m_book_res[0] or 0
        m_books_count = m_book_res[1] or 0
        month_prog = in_progress_pages if (m_idx == cur_m_idx and (target_year == 'all' or target_year == current_yr)) else 0
        months_data.append({
            "month_num": m_idx,
            "month_name": month_names[m_idx - 1],
            "pages": m_book_pages + month_prog,
            "books_count": m_books_count
        })

    # Day of week breakdown (0=Mon ... 6=Sun)
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_counts = {i: 0 for i in range(7)}
    for d_str in log_dates:
        if target_year == "all" or d_str.startswith(target_year):
            try:
                dt = datetime.date.fromisoformat(d_str)
                day_counts[dt.weekday()] += 1
            except Exception:
                pass
    weekday_distribution = [{"day": day_names[i], "day_short": day_names[i][:3], "count": day_counts[i]} for i in range(7)]

    # Calendar dates map with pages and minutes
    cursor.execute("SELECT date, SUM(pages_read), SUM(minutes_read), COUNT(*) FROM reading_logs GROUP BY date")
    calendar_logs = {r[0]: {"pages": r[1] or 0, "minutes": r[2] or 0, "sessions": r[3]} for r in cursor.fetchall()}
    for d_str in log_dates:
        if d_str not in calendar_logs:
            calendar_logs[d_str] = {"pages": 0, "minutes": 0, "sessions": 1}

    # Detailed books list for drill-down
    drilldown_books = []
    for r in read_rows:
        cursor.execute("SELECT cover_url FROM books WHERE id = ?", (r[0],))
        c_url_row = cursor.fetchone()
        c_url = c_url_row[0] if c_url_row else ""
        drilldown_books.append({
            "id": r[0],
            "title": r[1],
            "author": r[2],
            "media_type": r[3],
            "duration": r[4],
            "page_count": r[5] or 0,
            "rating": r[6] or 0,
            "spice_rating": r[7] or 0,
            "pace": r[8],
            "genres": r[9] or "",
            "date_read": r[10] or "",
            "series_name": r[11] or "",
            "cover_url": c_url
        })

    # Spiciest reads (spice >= 2, sorted descending)
    spiciest_books = []
    for b in sorted([x for x in drilldown_books if (x["spice_rating"] or 0) >= 2], key=lambda x: (x["spice_rating"] or 0), reverse=True):
        spiciest_books.append(b)
        if len(spiciest_books) >= 12:
            break

    # Longest and Shortest books
    books_with_pages = [b for b in drilldown_books if b["page_count"] > 0]
    longest_book = max(books_with_pages, key=lambda x: x["page_count"]) if books_with_pages else None
    shortest_book = min(books_with_pages, key=lambda x: x["page_count"]) if books_with_pages else None

    conn.close()

    return {
        "year": target_year,
        "books_read_count": books_read_count,
        "ebooks_read_count": len(ebooks_read),
        "audiobooks_read_count": len(audiobooks_read),
        "total_pages_read": total_pages,
        "total_audio_hours": total_audio_hours,
        "total_audio_minutes": total_audio_minutes,
        "audio_time_formatted": audio_time_formatted,
        "total_timer_minutes": total_timer_minutes,
        "total_timer_hours": total_timer_hours,
        "timer_sessions_count": timer_sessions_count,
        "avg_rating": avg_rating,
        "avg_spice": avg_spice,
        "total_days_read": total_days_read,
        "current_streak": 0,
        "longest_streak": 0,
        "days_read_in_year": days_read_in_year,
        "read_today": (today.isoformat() in log_dates),
        "last_7_days": last_7_days,
        "top_genres": [{"genre": g, "count": c} for g, c in sorted_genres[:10]],
        "author_loyalty": author_loyalty,
        "series_progress": series_progress,
        "achievements": badges,
        "rewards_rank": rewards_rank,
        "unlocked_badges_count": unlocked_badges_cnt,
        "total_badges_count": total_badges_cnt,
        "rewards_pct": rewards_pct,
        "rating_distribution": rating_distribution,
        "spice_distribution": spice_distribution,
        "spiciest_books": spiciest_books,
        "months_data": months_data,
        "weekday_distribution": weekday_distribution,
        "calendar_logs": calendar_logs,
        "drilldown_books": drilldown_books,
        "longest_book": longest_book,
        "shortest_book": shortest_book
    }


# ==============================================================================
# --- 17. EXTERNAL SERVICE IMPORTERS (CALIBRE, AUDIOBOOKSHELF, FABLE) ---
# ==============================================================================

# COVERS_DIR initialized at startup (supports DATA_DIR for Docker volume persistence)
os.makedirs(COVERS_DIR, exist_ok=True)

def strip_html_tags(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = html.unescape(clean)
    return re.sub(r'\s+', ' ', clean).strip()

def normalize_title_for_match(t: str) -> str:
    if not t:
        return ""
    t = t.lower()
    t = re.sub(r'[:\-–—].*$', '', t) # remove subtitle
    t = re.sub(r'[^a-z0-9]', '', t)
    return t

class CalibreScanPayload(BaseModel):
    folder_path: str
    copy_files: Optional[bool] = False
    mark_read_min_rating: Optional[int] = 4

def extract_calibre_books(db_path: str):
    """
    Resiliently inspects and extracts books from any Calibre metadata.db SQLite database,
    handling differences across Calibre versions (e.g. isbn in identifiers vs books table,
    missing comments/tags/series/ratings tables, etc.).
    """
    c_conn = sqlite3.connect(db_path)
    c_cur = c_conn.cursor()
    try:
        c_cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0].lower() for r in c_cur.fetchall()}
        if "books" not in tables:
            raise Exception("Invalid Calibre database: 'books' table not found.")

        c_cur.execute("PRAGMA table_info(books)")
        book_cols = {r[1].lower() for r in c_cur.fetchall()}

        has_pubdate = "pubdate" in book_cols
        has_path = "path" in book_cols
        has_cover = "has_cover" in book_cols
        has_series_idx = "series_index" in book_cols
        has_isbn_col = "isbn" in book_cols

        has_authors = ("authors" in tables and "books_authors_link" in tables)
        has_series = ("series" in tables and "books_series_link" in tables)
        has_ratings = ("ratings" in tables and "books_ratings_link" in tables)
        has_tags = ("tags" in tables and "books_tags_link" in tables)
        has_identifiers = ("identifiers" in tables)

        bsl_cols = set()
        if "books_series_link" in tables:
            c_cur.execute("PRAGMA table_info(books_series_link)")
            bsl_cols = {col[1].lower() for col in c_cur.fetchall()}

        comments_cols = set()
        if "comments" in tables:
            c_cur.execute("PRAGMA table_info(comments)")
            comments_cols = {col[1].lower() for col in c_cur.fetchall()}
        has_comments = ("comments" in tables and "book" in comments_cols and "text" in comments_cols)

        author_expr = "(SELECT GROUP_CONCAT(a.name, ', ') FROM books_authors_link bal JOIN authors a ON bal.author = a.id WHERE bal.book = b.id)" if has_authors else "''"
        series_name_expr = "(SELECT s.name FROM books_series_link bsl JOIN series s ON bsl.series = s.id WHERE bsl.book = b.id LIMIT 1)" if has_series else "''"
        
        if has_series_idx:
            series_idx_expr = "b.series_index"
        elif "series_index" in bsl_cols:
            series_idx_expr = "(SELECT bsl.series_index FROM books_series_link bsl WHERE bsl.book = b.id LIMIT 1)"
        else:
            series_idx_expr = "''"

        comments_expr = "(SELECT c.text FROM comments c WHERE c.book = b.id LIMIT 1)" if has_comments else "''"
        rating_expr = "(SELECT r.rating FROM books_ratings_link brl JOIN ratings r ON brl.rating = r.id WHERE brl.book = b.id LIMIT 1)" if has_ratings else "0"
        tags_expr = "(SELECT GROUP_CONCAT(t.name, ', ') FROM books_tags_link btl JOIN tags t ON btl.tag = t.id WHERE btl.book = b.id)" if has_tags else "''"

        if has_identifiers and has_isbn_col:
            isbn_expr = "COALESCE(b.isbn, (SELECT val FROM identifiers WHERE book = b.id AND LOWER(type) = 'isbn' LIMIT 1), '')"
        elif has_identifiers:
            isbn_expr = "COALESCE((SELECT val FROM identifiers WHERE book = b.id AND LOWER(type) = 'isbn' LIMIT 1), '')"
        elif has_isbn_col:
            isbn_expr = "COALESCE(b.isbn, '')"
        else:
            isbn_expr = "''"

        pubdate_expr = "b.pubdate" if has_pubdate else "''"
        path_expr = "b.path" if has_path else "''"
        has_cover_expr = "b.has_cover" if has_cover else "0"

        query = f"""
        SELECT 
            b.id,
            b.title,
            {pubdate_expr} as pubdate,
            {path_expr} as path,
            {has_cover_expr} as has_cover,
            {isbn_expr} as isbn,
            {author_expr} as author,
            {series_name_expr} as series_name,
            {series_idx_expr} as series_number,
            {comments_expr} as comments,
            {rating_expr} as rating,
            {tags_expr} as tags
        FROM books b
        """
        c_cur.execute(query)
        return c_cur.fetchall()
    finally:
        try:
            c_conn.close()
        except Exception:
            pass

@app.post("/import/calibre/scan")
def import_calibre_from_folder(payload: CalibreScanPayload):
    folder = payload.folder_path.strip().strip('"').strip("'")
    if not os.path.exists(folder):
        raise HTTPException(status_code=400, detail=f"Folder not found: {folder}")
    
    db_file = os.path.join(folder, "metadata.db")
    if not os.path.exists(db_file):
        raise HTTPException(status_code=400, detail=f"No metadata.db found in {folder}. Make sure this is your Calibre Library root folder.")

    try:
        c_books = extract_calibre_books(db_file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read Calibre metadata.db: {str(e)}")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, title, author, filename, cover_url FROM books")
    existing_books = cur.fetchall()

    imported_count = 0
    updated_count = 0

    c_conn_data = None
    try:
        c_conn_data = sqlite3.connect(db_file)
        c_cur_data = c_conn_data.cursor()
    except Exception:
        pass

    for b in c_books:
        c_id, title, pubdate, path, has_cover, isbn, author, s_name, s_num, comments, c_rating, tags = b
        title = (title or "").strip()
        if not title:
            continue
        author = (author or "Unknown Author").strip()
        s_name = (s_name or "").strip()
        s_num = str(int(s_num)) if (s_num is not None and s_num == int(s_num)) else (str(s_num) if s_num is not None else "")
        description = strip_html_tags(comments or "")
        pub_year = str(pubdate[:4]) if (pubdate and len(pubdate) >= 4) else ""
        
        # Rating: Calibre is 2, 4, 6, 8, 10
        star_rating = int(round((c_rating or 0) / 2)) if c_rating else 0
        is_read_val = 1 if (star_rating >= payload.mark_read_min_rating and payload.mark_read_min_rating > 0) or (tags and "read" in tags.lower()) else 0
        reading_status = "read" if is_read_val else "tbr"
        date_read_val = datetime.date.today().isoformat() if is_read_val else ""

        # Cover image
        cover_url = ""
        if has_cover and path:
            calibre_cover = os.path.join(folder, path, "cover.jpg")
            if os.path.exists(calibre_cover):
                dest_cover_name = f"calibre_{c_id}_{re.sub(r'[^a-zA-Z0-9]', '', title)[:20]}.jpg"
                dest_cover_path = os.path.join(COVERS_DIR, dest_cover_name)
                try:
                    shutil.copy2(calibre_cover, dest_cover_path)
                    cover_url = f"/static/covers/{dest_cover_name}"
                except Exception:
                    pass

        # Check for ebook file in Calibre data table
        target_filename = ""
        if c_conn_data and path:
            try:
                c_cur_data.execute("SELECT format, name FROM data WHERE book = ?", (c_id,))
                formats = c_cur_data.fetchall()
                fmt_order = {"EPUB": 1, "PDF": 2, "MOBI": 3, "AZW3": 4, "AZW": 5}
                formats.sort(key=lambda x: fmt_order.get(x[0].upper(), 99))
                if formats:
                    chosen_fmt, file_stem = formats[0]
                    src_file = os.path.join(folder, path, f"{file_stem}.{chosen_fmt.lower()}")
                    if os.path.exists(src_file) and payload.copy_files:
                        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:40]
                        dest_file_name = f"{safe_title}_{c_id}.{chosen_fmt.lower()}"
                        dest_file_path = os.path.join(STORAGE_DIR, dest_file_name)
                        shutil.copy2(src_file, dest_file_path)
                        target_filename = dest_file_name
            except Exception:
                pass

        # Check existing match
        match = None
        norm_t = normalize_title_for_match(title)
        for eb in existing_books:
            if normalize_title_for_match(eb[1]) == norm_t:
                match = eb
                break

        if match:
            b_id, e_title, e_author, e_fname, e_cover = match
            updates = []
            params = []
            if not e_fname and target_filename:
                updates.append("filename = ?")
                params.append(target_filename)
            if not e_cover and cover_url:
                updates.append("cover_url = ?")
                params.append(cover_url)
            if s_name:
                updates.append("series_name = ?")
                params.append(s_name)
                updates.append("series_number = ?")
                params.append(s_num)
            if updates:
                params.append(b_id)
                cur.execute(f"UPDATE books SET {', '.join(updates)} WHERE id = ?", params)
                updated_count += 1
        else:
            cur.execute("""
                INSERT INTO books (
                    title, author, filename, description, isbn, cover_url, published_year,
                    source, series_name, series_number, is_read, reading_status, rating, review,
                    date_read, media_type, genres
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Calibre', ?, ?, ?, ?, ?, '', ?, 'ebook', ?)
            """, (
                title, author, target_filename, description, isbn or "", cover_url,
                pub_year, s_name, s_num, is_read_val, reading_status, star_rating,
                date_read_val, tags or ""
            ))
            imported_count += 1

    if c_conn_data:
        try:
            c_conn_data.close()
        except Exception:
            pass

    check_and_unlock_achievements(conn)
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": f"Successfully scanned Calibre Library! Imported {imported_count} new books and updated {updated_count} existing titles.",
        "imported_count": imported_count,
        "updated_count": updated_count,
        "total_calibre_books": len(c_books)
    }

@app.post("/import/calibre/upload-db")
async def import_calibre_uploaded_db(file: UploadFile = File(...)):
    filename_lower = (file.filename or "").lower()
    content = await file.read()
    if not (filename_lower.endswith((".db", ".sqlite", ".sqlite3")) or content.startswith(b"SQLite format 3\x00")):
        raise HTTPException(status_code=400, detail="Please upload a valid Calibre 'metadata.db' SQLite file.")
    
    unique_id = uuid.uuid4().hex
    temp_path = os.path.join(STATIC_DIR, f"temp_calibre_{unique_id}.db")
    try:
        with open(temp_path, "wb") as f:
            f.write(content)
        c_books = extract_calibre_books(temp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse uploaded metadata.db: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, title, author FROM books")
    existing_books = cur.fetchall()

    imported_count = 0
    updated_count = 0

    for b in c_books:
        c_id, title, pubdate, path, has_cover, isbn, author, s_name, s_num, comments, c_rating, tags = b
        title = (title or "").strip()
        if not title:
            continue
        author = (author or "Unknown Author").strip()
        s_name = (s_name or "").strip()
        s_num = str(int(s_num)) if (s_num is not None and s_num == int(s_num)) else (str(s_num) if s_num is not None else "")
        description = strip_html_tags(comments or "")
        pub_year = str(pubdate[:4]) if (pubdate and len(pubdate) >= 4) else ""
        star_rating = int(round((c_rating or 0) / 2)) if c_rating else 0
        is_read_val = 1 if star_rating >= 4 or (tags and "read" in tags.lower()) else 0
        reading_status = "read" if is_read_val else "tbr"

        norm_t = normalize_title_for_match(title)
        match = next((eb for eb in existing_books if normalize_title_for_match(eb[1]) == norm_t), None)

        if match:
            if s_name:
                cur.execute("UPDATE books SET series_name = ?, series_number = ? WHERE id = ?", (s_name, s_num, match[0]))
                updated_count += 1
        else:
            cur.execute("""
                INSERT INTO books (
                    title, author, filename, description, isbn, cover_url, published_year,
                    source, series_name, series_number, is_read, reading_status, rating, review,
                    date_read, media_type, genres
                )
                VALUES (?, ?, '', ?, ?, '', ?, 'Calibre', ?, ?, ?, ?, ?, '', '', 'ebook', ?)
            """, (
                title, author, description, isbn or "", pub_year, s_name, s_num,
                is_read_val, reading_status, star_rating, tags or ""
            ))
            imported_count += 1

    check_and_unlock_achievements(conn)
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": f"Imported {imported_count} books from Calibre metadata.db and updated {updated_count} existing titles.",
        "imported_count": imported_count,
        "updated_count": updated_count
    }


# --- AUDIOBOOKSHELF API SYNC ---

class AudiobookshelfTestPayload(BaseModel):
    server_url: str
    api_token: Optional[str] = ""

def clean_abs_url_and_lib(raw_url: str):
    raw_url = raw_url.strip().rstrip("/")
    if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
        raw_url = "https://" + raw_url
    lib_id = None
    lib_match = re.search(r'/library/([a-zA-Z0-9_-]+)', raw_url)
    if lib_match:
        lib_id = lib_match.group(1)
        raw_url = raw_url[:lib_match.start()]
    return raw_url, lib_id

@app.post("/import/audiobookshelf/test")
def test_audiobookshelf_connection(payload: AudiobookshelfTestPayload):
    url, detected_lib = clean_abs_url_and_lib(payload.server_url)

    headers = {}
    if payload.api_token and payload.api_token.strip():
        headers["Authorization"] = f"Bearer {payload.api_token.strip()}"

    try:
        r = requests.get(f"{url}/api/libraries", headers=headers, timeout=8)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Authentication failed: Invalid API Token. Check Settings → Users in Audiobookshelf.")
        r.raise_for_status()
        data = r.json()
        libraries = data.get("libraries", [])
        return {
            "status": "success",
            "server_url": url,
            "detected_library_id": detected_lib,
            "libraries": [
                {
                    "id": lib.get("id"),
                    "name": lib.get("name"),
                    "media_type": lib.get("mediaType", "book")
                }
                for lib in libraries
            ]
        }
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Could not connect to Audiobookshelf at {url}: {str(e)}")

class AudiobookshelfSyncPayload(BaseModel):
    server_url: str
    api_token: Optional[str] = ""
    library_id: Optional[str] = None
    sync_progress: Optional[bool] = True

@app.post("/import/audiobookshelf/sync")
def sync_audiobookshelf(payload: AudiobookshelfSyncPayload):
    url, detected_lib = clean_abs_url_and_lib(payload.server_url)
    effective_lib_id = payload.library_id or detected_lib

    headers = {}
    token = (payload.api_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        r = requests.get(f"{url}/api/libraries", headers=headers, timeout=8)
        r.raise_for_status()
        all_libs = r.json().get("libraries", [])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch libraries: {str(e)}")

    target_libs = [lib for lib in all_libs if (not effective_lib_id or lib.get("id") == effective_lib_id) and lib.get("mediaType", "book") in ["book", "audiobook"]]
    if not target_libs and all_libs:
        target_libs = [all_libs[0]]

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, title, author, duration, cover_url, progress_percent, reading_status FROM books WHERE media_type = 'audiobook'")
    existing_audios = cur.fetchall()

    imported_count = 0
    updated_count = 0

    for lib in target_libs:
        lib_id = lib.get("id")
        try:
            items_res = requests.get(f"{url}/api/libraries/{lib_id}/items?include=progress", headers=headers, timeout=25)
            items_res.raise_for_status()
            items_data = items_res.json()
            items = items_data.get("results", []) if isinstance(items_data, dict) else (items_data if isinstance(items_data, list) else [])
        except Exception as e:
            continue

        for it in items:
            media = it.get("media", {})
            meta = media.get("metadata", {})
            title = (meta.get("title") or it.get("name") or "").strip()
            if not title:
                continue

            authors_arr = meta.get("authors", [])
            author_names = [a.get("name") for a in authors_arr if isinstance(a, dict) and a.get("name")]
            author = ", ".join(author_names) if author_names else (meta.get("author") or "Unknown Author")

            narrators_arr = meta.get("narrators", [])
            narrator = ", ".join(narrators_arr) if isinstance(narrators_arr, list) else str(narrators_arr or "")

            series_arr = meta.get("series", [])
            series_name = ""
            series_num = ""
            if series_arr and isinstance(series_arr, list) and len(series_arr) > 0:
                s0 = series_arr[0]
                if isinstance(s0, dict):
                    series_name = s0.get("name") or ""
                    series_num = str(s0.get("sequence") or "")
                elif isinstance(s0, str):
                    series_name = s0

            published_year = str(meta.get("publishedYear") or "")
            description = strip_html_tags(meta.get("description") or "")
            genres = ", ".join(meta.get("genres", [])) if isinstance(meta.get("genres"), list) else ""

            duration_secs = media.get("duration") or 0
            if duration_secs:
                hrs = int(duration_secs // 3600)
                mins = int((duration_secs % 3600) // 60)
                duration_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"
            else:
                duration_str = ""

            # Listening Progress
            user_prog = it.get("userMediaProgress") or {}
            prog_ratio = float(user_prog.get("progress") or 0.0)
            is_finished = bool(user_prog.get("isFinished", False)) or prog_ratio >= 0.98

            if is_finished:
                reading_status = "read"
                is_read_val = 1
                prog_pct = 100
            elif prog_ratio > 0 and payload.sync_progress:
                reading_status = "reading"
                is_read_val = 0
                prog_pct = int(round(prog_ratio * 100))
            else:
                reading_status = "tbr"
                is_read_val = 0
                prog_pct = 0

            # Cover Caching
            cover_url = ""
            try:
                c_req_url = f"{url}/api/items/{it.get('id')}/cover"
                if token:
                    c_req_url += f"?token={token}"
                c_resp = requests.get(c_req_url, headers=headers, timeout=5)
                if c_resp.status_code == 200 and len(c_resp.content) > 500:
                    c_filename = f"abs_{it.get('id')}_{re.sub(r'[^a-zA-Z0-9]', '', title)[:20]}.jpg"
                    c_disk_path = os.path.join(COVERS_DIR, c_filename)
                    with open(c_disk_path, "wb") as cf:
                        cf.write(c_resp.content)
                    cover_url = f"/static/covers/{c_filename}"
            except Exception:
                cover_url = f"{url}/api/items/{it.get('id')}/cover" if not token else f"{url}/api/items/{it.get('id')}/cover?token={token}"

            # Check existing match
            norm_t = normalize_title_for_match(title)
            match = next((ea for ea in existing_audios if normalize_title_for_match(ea[1]) == norm_t), None)

            if match:
                b_id, e_t, e_a, e_dur, e_cov, e_pct, e_st = match
                cur.execute("""
                    UPDATE books
                    SET duration = COALESCE(NULLIF(?, ''), duration),
                        narrator = COALESCE(NULLIF(?, ''), narrator),
                        cover_url = COALESCE(NULLIF(?, ''), cover_url),
                        progress_percent = ?,
                        reading_status = ?,
                        is_read = ?
                    WHERE id = ?
                """, (duration_str, narrator, cover_url, prog_pct, reading_status, is_read_val, b_id))
                updated_count += 1
            else:
                cur.execute("""
                    INSERT INTO books (
                        title, author, filename, description, isbn, cover_url, published_year,
                        source, series_name, series_number, is_read, reading_status, rating, review,
                        date_read, media_type, narrator, duration, progress_percent, genres
                    )
                    VALUES (?, ?, '', ?, '', ?, ?, 'Audiobookshelf', ?, ?, ?, ?, 0, '', '', 'audiobook', ?, ?, ?, ?)
                """, (
                    title, author, description, cover_url, published_year,
                    series_name, series_num, is_read_val, reading_status,
                    narrator, duration_str, prog_pct, genres
                ))
                imported_count += 1

    check_and_unlock_achievements(conn)
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": f"Audiobookshelf sync complete! Imported {imported_count} audiobooks and updated {updated_count} existing titles.",
        "imported_count": imported_count,
        "updated_count": updated_count
    }


# --- FABLE BOOK APP IMPORTER ---

def process_fable_records(rows):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, title, author, rating, review, reading_status FROM books")
    existing_books = cur.fetchall()

    imported_count = 0
    updated_count = 0

    for r in rows:
        title = r.get("title", "").strip()
        if not title:
            continue
        author = r.get("author", "Unknown Author").strip()
        shelf = r.get("shelf", "").strip().lower()
        rating = r.get("rating", 0)
        review = r.get("review", "").strip()
        date_read = r.get("date_read", "").strip()
        progress_pct = r.get("progress_pct", 0)

        # Precise shelf mapping
        if any(w in shelf for w in ["currently", "reading", "in_progress"]):
            status = "reading"
            is_read = 0
            if not progress_pct:
                progress_pct = 25
        elif any(w in shelf for w in ["want to read", "to-read", "tbr", "wishlist", "queued"]):
            status = "tbr"
            is_read = 0
            progress_pct = 0
        elif any(w in shelf for w in ["read", "finished", "completed", "done"]):
            status = "read"
            is_read = 1
            progress_pct = 100
            if not date_read:
                date_read = datetime.date.today().isoformat()
        else:
            status = "tbr"
            is_read = 0

        norm_t = normalize_title_for_match(title)
        match = next((eb for eb in existing_books if normalize_title_for_match(eb[1]) == norm_t), None)

        if match:
            b_id, e_t, e_a, e_rat, e_rev, e_st = match
            updates = ["reading_status = ?", "is_read = ?", "progress_percent = ?"]
            params = [status, is_read, progress_pct]
            if rating > 0:
                updates.append("rating = ?")
                params.append(rating)
            if review:
                updates.append("review = ?")
                params.append(review)
            if date_read:
                updates.append("date_read = ?")
                params.append(date_read)
            params.append(b_id)
            cur.execute(f"UPDATE books SET {', '.join(updates)} WHERE id = ?", params)
            updated_count += 1
        else:
            cur.execute("""
                INSERT INTO books (
                    title, author, filename, description, isbn, cover_url, published_year,
                    source, series_name, series_number, is_read, reading_status, rating, review,
                    date_read, media_type, progress_percent
                )
                VALUES (?, ?, '', '', '', '', '', 'Fable', '', '', ?, ?, ?, ?, ?, 'ebook', ?)
            """, (
                title, author, is_read, status, rating, review, date_read, progress_pct
            ))
            imported_count += 1

    check_and_unlock_achievements(conn)
    conn.commit()
    conn.close()

    return imported_count, updated_count

def parse_fable_csv_text(text: str):
    # Detect delimiter
    first_line = text.splitlines()[0] if text.splitlines() else ""
    delim = "	" if "	" in first_line else (";" if ";" in first_line and "," not in first_line else ",")
    
    reader = csv.DictReader(io.StringIO(text.strip()), delimiter=delim)
    records = []
    for raw_row in reader:
        row = {re.sub(r'[^a-z0-9]', '', k.lower()): v.strip() for k, v in raw_row.items() if k}
        
        # Keys detection
        title = row.get("title") or row.get("booktitle") or row.get("name") or ""
        author = row.get("author") or row.get("authors") or row.get("bookauthor") or "Unknown Author"
        shelf = row.get("shelf") or row.get("list") or row.get("listname") or row.get("status") or "tbr"
        
        # Rating
        rating_val = 0
        r_str = row.get("rating") or row.get("myrating") or row.get("starrating") or "0"
        try:
            rating_val = max(0, min(5, int(round(float(r_str)))))
        except Exception:
            pass

        review = row.get("review") or row.get("notes") or row.get("thoughts") or row.get("reviewtext") or ""
        date_read = row.get("datefinished") or row.get("dateread") or row.get("completedat") or row.get("finisheddate") or ""
        
        # Progress
        prog_val = 0
        p_str = row.get("progress") or row.get("percent") or row.get("percentread") or "0"
        try:
            prog_val = max(0, min(100, int(float(p_str.replace("%", "")))))
        except Exception:
            pass

        records.append({
            "title": title,
            "author": author,
            "shelf": shelf,
            "rating": rating_val,
            "review": review,
            "date_read": date_read,
            "progress_pct": prog_val
        })
    return records

@app.post("/import/fable/upload")
async def import_fable_file(file: UploadFile = File(...)):
    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="ignore")

    records = []
    if file.filename.endswith(".json") or text.strip().startswith(("{", "[")):
        try:
            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("books", data.get("items", data.get("lists", [])))
            for it in items:
                records.append({
                    "title": it.get("title") or it.get("name") or "",
                    "author": it.get("author") or "Unknown Author",
                    "shelf": it.get("shelf") or it.get("list") or it.get("status") or "tbr",
                    "rating": int(it.get("rating") or 0),
                    "review": it.get("review") or it.get("notes") or "",
                    "date_read": it.get("date_read") or it.get("date_finished") or "",
                    "progress_pct": int(it.get("progress") or 0)
                })
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse JSON: {str(e)}")
    else:
        records = parse_fable_csv_text(text)

    if not records:
        raise HTTPException(status_code=400, detail="No valid book records found in uploaded file. Check headers.")

    imp_cnt, upd_cnt = process_fable_records(records)
    return {
        "status": "success",
        "message": f"Successfully processed Fable export! Imported {imp_cnt} new books and updated {upd_cnt} existing library books.",
        "imported_count": imp_cnt,
        "updated_count": upd_cnt,
        "total_records": len(records)
    }

class FableTextPayload(BaseModel):
    csv_text: str

@app.post("/import/fable/paste")
def import_fable_pasted_text(payload: FableTextPayload):
    records = parse_fable_csv_text(payload.csv_text)
    if not records:
        raise HTTPException(status_code=400, detail="Could not parse any rows from pasted CSV text.")
    imp_cnt, upd_cnt = process_fable_records(records)
    return {
        "status": "success",
        "message": f"Successfully processed Fable data! Imported {imp_cnt} new books and updated {upd_cnt} existing library books.",
        "imported_count": imp_cnt,
        "updated_count": upd_cnt,
        "total_records": len(records)
    }


# ==========================================
# AUTHENTICATION & USER MANAGEMENT
# ==========================================

class RegisterPayload(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""

class LoginPayload(BaseModel):
    username: str
    password: str

class ThemePreferencePayload(BaseModel):
    theme_preference: Optional[str] = None
    custom_themes: Optional[list] = None

def hash_user_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()

def verify_user_password(password: str, salt: str, password_hash: str) -> bool:
    calc = hash_user_password(password, salt)
    return secrets.compare_digest(calc, password_hash)

def get_current_user_from_request(request: Request) -> Optional[dict]:
    token = request.cookies.get("book_app_session")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    if not token:
        return None

    now_iso = datetime.datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT u.id, u.username, u.display_name, u.role, u.theme_preference, u.custom_themes
        FROM user_sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ? AND s.expires_at > ?
    """, (token, now_iso))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    try:
        custom_th = json.loads(row[5]) if row[5] else []
    except Exception:
        custom_th = []

    return {
        "id": row[0],
        "username": row[1],
        "display_name": row[2] or row[1],
        "role": row[3],
        "theme_preference": row[4] or "",
        "custom_themes": custom_th
    }

@app.get("/auth/status")
def auth_status(request: Request):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    user_count = cur.fetchone()[0]
    conn.close()

    user = get_current_user_from_request(request)
    return {
        "logged_in": bool(user is not None),
        "has_users": bool(user_count > 0),
        "user": user
    }

@app.post("/auth/register")
def auth_register(payload: RegisterPayload, response: Response):
    u = payload.username.strip()
    p = payload.password.strip()
    d = (payload.display_name or "").strip()

    if len(u) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
    if len(p) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    
    salt = secrets.token_hex(16)
    p_hash = hash_user_password(p, salt)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    role = "admin" if count == 0 else "reader"
    disp_name = d if d else u

    try:
        cur.execute("""
            INSERT INTO users (username, password_hash, salt, display_name, role)
            VALUES (?, ?, ?, ?, ?)
        """, (u, p_hash, salt, disp_name, role))
        user_id = cur.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="A user with that username already exists.")

    token = secrets.token_hex(32)
    expires = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
    cur.execute("""
        INSERT INTO user_sessions (token, user_id, expires_at)
        VALUES (?, ?, ?)
    """, (token, user_id, expires))
    conn.commit()
    conn.close()

    response.set_cookie(
        key="book_app_session",
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        path="/"
    )

    return {
        "status": "success",
        "message": f"Welcome, {disp_name}!",
        "token": token,
        "user": {
            "id": user_id,
            "username": u,
            "display_name": disp_name,
            "role": role,
            "theme_preference": "",
            "custom_themes": []
        }
    }

@app.post("/auth/login")
def auth_login(payload: LoginPayload, response: Response):
    u = payload.username.strip()
    p = payload.password.strip()

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, username, password_hash, salt, display_name, role, theme_preference, custom_themes
        FROM users
        WHERE LOWER(username) = LOWER(?)
    """, (u,))
    row = cur.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    user_id, uname, p_hash, salt, disp_name, role, theme_pref, cust_themes_raw = row
    if not verify_user_password(p, salt, p_hash):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = secrets.token_hex(32)
    expires = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
    cur.execute("""
        INSERT INTO user_sessions (token, user_id, expires_at)
        VALUES (?, ?, ?)
    """, (token, user_id, expires))
    conn.commit()
    conn.close()

    response.set_cookie(
        key="book_app_session",
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        path="/"
    )

    try:
        custom_th = json.loads(cust_themes_raw) if cust_themes_raw else []
    except Exception:
        custom_th = []

    return {
        "status": "success",
        "message": f"Welcome back, {disp_name or uname}!",
        "token": token,
        "user": {
            "id": user_id,
            "username": uname,
            "display_name": disp_name or uname,
            "role": role,
            "theme_preference": theme_pref or "",
            "custom_themes": custom_th
        }
    }

@app.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    token = request.cookies.get("book_app_session")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()

    response.delete_cookie(key="book_app_session", path="/")
    return {"status": "success", "message": "Logged out successfully."}

@app.get("/auth/me")
def auth_me(request: Request):
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return {"status": "success", "user": user}

@app.post("/auth/theme")
def auth_save_theme(payload: ThemePreferencePayload, request: Request):
    user = get_current_user_from_request(request)
    if user:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        if payload.theme_preference is not None:
            cur.execute("UPDATE users SET theme_preference = ? WHERE id = ?", (payload.theme_preference, user["id"]))
        if payload.custom_themes is not None:
            cur.execute("UPDATE users SET custom_themes = ? WHERE id = ?", (json.dumps(payload.custom_themes), user["id"]))
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Theme preferences saved to user profile."}
    else:
        if payload.theme_preference is not None:
            set_setting("app_theme", payload.theme_preference)
        return {"status": "success", "message": "Theme preference saved locally."}


