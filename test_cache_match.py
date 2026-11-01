import re, sys
sys.path.insert(0, r'C:\Users\genni\my_book_app')
from main import POPULAR_ROMANCE_IO_CACHE

def match_romance_io_cache(title: str):
    clean_t = re.sub(r'^(?:_?oceanofpdf\.com_?|\[?audiobookbay(?:\.lu|\.nl)?\]?[-_ ]*)\s*', '', title, flags=re.IGNORECASE)
    if ' - ' in clean_t:
        clean_t = clean_t.split(' - ')[0].strip()
    elif ' by ' in clean_t.lower():
        clean_t = re.split(r'\s+by\s+', clean_t, flags=re.IGNORECASE)[0].strip()
    clean_t = re.sub(r'[:\(\[].*', '', clean_t).strip()
    norm_t = re.sub(r'[^a-z0-9]', '', clean_t.lower())
    if not norm_t:
        return None
    for k, v in POPULAR_ROMANCE_IO_CACHE.items():
        norm_k = re.sub(r'[^a-z0-9]', '', k.lower())
        if norm_k == norm_t or norm_t.startswith(norm_k) or (len(norm_k) >= 6 and norm_k in norm_t):
            return {'spice_rating': v['spice_rating'], 'tropes': v['tropes']}
    return None

samples = [
    'A Deal with the Elf King: A Standalone Fantasy Romance',
    "A Demon's Guide to Wooing a Witch - Sarah Hawley",
    'A Court of Mist and Fury',
    'A Soul to Keep: Duskwalker Brides Book 1',
    'A Touch of Malice: Hades and Persephone, Book 3',
    'A Rivalry of Hearts'
]

for s in samples:
    print(s[:40], '->', match_romance_io_cache(s))
