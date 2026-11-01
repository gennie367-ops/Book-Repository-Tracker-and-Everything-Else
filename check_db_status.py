import sqlite3

conn = sqlite3.connect(r'C:\Users\genni\my_book_app\library.db')
c = conn.cursor()
c.execute("SELECT COUNT(id) FROM books")
total = c.fetchone()[0]
c.execute("SELECT COUNT(id) FROM books WHERE spice_rating > 0")
with_spice = c.fetchone()[0]
c.execute("SELECT COUNT(id) FROM books WHERE tropes IS NOT NULL AND tropes != ''")
with_tropes = c.fetchone()[0]
c.execute("SELECT COUNT(id) FROM books WHERE (spice_rating IS NULL OR spice_rating = 0) AND (tropes IS NULL OR tropes = '')")
completely_empty = c.fetchone()[0]

print(f"Total books: {total}")
print(f"Books with spice > 0: {with_spice}")
print(f"Books with tropes: {with_tropes}")
print(f"Completely empty (neither spice nor tropes): {completely_empty}")
