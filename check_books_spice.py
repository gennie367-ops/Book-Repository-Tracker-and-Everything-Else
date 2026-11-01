import sqlite3

conn = sqlite3.connect(r'C:\Users\genni\my_book_app\library.db')
c = conn.cursor()
c.execute('SELECT id, title, author, spice_rating, tropes FROM books LIMIT 30')
for row in c.fetchall():
    print(f'ID {row[0]}: "{row[1]}" by {row[2]} -> Spice: {row[3]}, Tropes: {row[4]}')
conn.close()
