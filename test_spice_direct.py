import sys
sys.path.insert(0, r"C:\Users\genni\my_book_app")
from main import lookup_romance_io_spice, get_active_gemini_key

key = get_active_gemini_key()
print("Active Gemini Key:", key[:10] + "..." if key else "NONE")

test_books = [
    ("Fourth Wing", "Rebecca Yarros"),
    ("A Court of Thorns and Roses", "Sarah J. Maas"),
    ("From Blood and Ash", "Jennifer L. Armentrout"),
    ("The Serpent and the Wings of Night", "Carissa Broadbent"),
    ("Haunting Adeline", "H.D. Carlton"),
    ("Icebreaker", "Hannah Grace"),
]

for title, author in test_books:
    res = lookup_romance_io_spice(title, author)
    print(f"'{title}' by '{author}': {res}")
