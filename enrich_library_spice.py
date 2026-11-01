import sqlite3, re, json, time, sys
import urllib.request

sys.path.insert(0, r'C:\Users\genni\my_book_app')
from main import POPULAR_ROMANCE_IO_CACHE, call_gemini_api

DB_PATH = r'C:\Users\genni\my_book_app\library.db'

def clean_book_info(title: str, author: str = ""):
    t = re.sub(r"^(?:_?oceanofpdf\.com_?|\[?audiobookbay(?:\.lu|\.nl)?\]?[-_ ]*)\s*", "", title, flags=re.IGNORECASE)
    # Strip paths if file path ended up in title
    if "\\" in t or "/" in t:
        t = re.split(r"[\\/]", t)[-1]
        t = re.sub(r"\.(?:epub|pdf|mobi|m4b|mp3)$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\(z-library.*?\)", "", t, flags=re.IGNORECASE)
    a = author.strip() if author else ""
    if (" - " in t or " by " in t.lower()) and (not a or "unknown" in a.lower()):
        if " - " in t:
            parts = t.split(" - ")
            t, a = parts[0].strip(), parts[1].strip()
        elif " by " in t.lower():
            parts = re.split(r"\s+by\s+", t, flags=re.IGNORECASE)
            t, a = parts[0].strip(), parts[1].strip()
    
    # Subtitles or series
    clean_t = re.sub(r"[:\(\[].*", "", t).strip()
    clean_a = re.sub(r"[\(\[].*", "", a).strip()
    if not clean_t:
        clean_t = t.strip()
    return clean_t, clean_a

def match_cache(title: str):
    clean_t, _ = clean_book_info(title)
    norm_t = re.sub(r"[^a-z0-9]", "", clean_t.lower())
    if not norm_t:
        return None
    for k, v in POPULAR_ROMANCE_IO_CACHE.items():
        norm_k = re.sub(r"[^a-z0-9]", "", k.lower())
        if norm_k == norm_t or norm_t.startswith(norm_k) or (len(norm_k) >= 6 and norm_k in norm_t):
            return {"spice_rating": v["spice_rating"], "tropes": v["tropes"]}
    return None

def safe_parse_json(text: str):
    if not text:
        return None
    cleaned = text.strip()
    m_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if m_block:
        cleaned = m_block.group(1).strip()
    m_json = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
    if m_json:
        cleaned = m_json.group(1).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            # If wrapped in dict like {"books": [...]}
            for k in ["books", "items", "results", "data"]:
                if k in data and isinstance(data[k], list):
                    return data[k]
        return data
    except Exception:
        return None

def enrich_all_in_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, author FROM books WHERE (spice_rating IS NULL OR spice_rating = 0)")
    rows = c.fetchall()
    print(f"Total unenriched books found: {len(rows)}")

    matched_cache_count = 0
    pending = []

    for r in rows:
        b_id, raw_title, raw_author = r[0], r[1], r[2]
        cache_hit = match_cache(raw_title)
        if cache_hit:
            c.execute("""
                UPDATE books
                SET spice_rating = ?,
                    tropes = CASE WHEN tropes IS NULL OR tropes = '' THEN ? ELSE tropes END
                WHERE id = ?
            """, (cache_hit["spice_rating"], cache_hit["tropes"], b_id))
            matched_cache_count += 1
            print(f"[CACHE] #{b_id} '{raw_title[:30]}' -> {cache_hit['spice_rating']} 🌶️ | {cache_hit['tropes']}")
        else:
            clean_t, clean_a = clean_book_info(raw_title, raw_author)
            pending.append({"id": b_id, "title": clean_t, "author": clean_a, "raw_title": raw_title})

    conn.commit()
    print(f"\nResolved {matched_cache_count} books instantly from cache! {len(pending)} remaining to query via AI.\n")

    # Batch query in chunks of 15
    chunk_size = 15
    ai_updated_count = 0

    for i in range(0, len(pending), chunk_size):
        chunk = pending[i:i + chunk_size]
        print(f"Querying chunk {i//chunk_size + 1}/{(len(pending) + chunk_size - 1)//chunk_size} ({len(chunk)} books)...")

        prompt = """
You are an expert on Romance.io ratings, romantasy, fantasy, and general books.
For each book listed below, provide its official Romance.io spice / steam rating from 1 to 5 and its main tropes / genre keywords.

Romance.io Spice Scale:
1: Glimpses / Clean
2: Behind closed doors / Warm
3: Open door / Steamy
4: Explicit open door / Very steamy
5: Explicit and plentiful / Ultra spicy
(For non-fiction, craft, crochet, or non-romance general fiction, assign spice_rating: 0 and genre as tropes).

Books to evaluate:
""" + "\n".join([f"- ID {b['id']}: \"{b['title']}\" by {b['author']}" for b in chunk]) + """

Return ONLY a JSON array of objects with "id", "spice_rating" (integer 0-5), and "tropes" (comma separated string):
[
  {"id": 1, "spice_rating": 3, "tropes": "fantasy, enemies to lovers"}
]
"""
        raw_text = call_gemini_api(prompt, json_mode=True, temperature=0.1)
        parsed = safe_parse_json(raw_text)

        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and 'id' in item:
                    b_id = int(item['id'])
                    spice = max(0, min(5, int(item.get('spice_rating') or 0)))
                    tropes = str(item.get('tropes') or '').strip()
                    c.execute("""
                        UPDATE books
                        SET spice_rating = ?,
                            tropes = CASE WHEN tropes IS NULL OR tropes = '' THEN ? ELSE tropes END
                        WHERE id = ?
                    """, (spice, tropes, b_id))
                    ai_updated_count += 1
                    print(f"  [AI] #{b_id} -> {spice} 🌶️ | {tropes}")
            conn.commit()
        else:
            print(f"  Warning: failed to parse chunk response: {raw_text[:120] if raw_text else 'None'}")
        
        time.sleep(1)

    conn.commit()
    conn.close()
    print(f"\nDone! Enriched {matched_cache_count + ai_updated_count} books total.")

if __name__ == '__main__':
    enrich_all_in_db()
