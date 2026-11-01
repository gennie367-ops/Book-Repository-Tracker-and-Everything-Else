import sqlite3
import sys
sys.path.insert(0, r"C:\Users\genni\my_book_app")
from main import call_gemini_api, lookup_romance_io_spice, batch_lookup_romance_io_spice, get_active_gemini_key

key = get_active_gemini_key()
print("Active Gemini Key:", "Present" if key else "MISSING!")
if key:
    print("Key starts with:", key[:8] + "...")

print("\n--- Test call_gemini_api ---")
res = call_gemini_api("Hello! Return a 1-sentence greeting.")
print("call_gemini_api result:", repr(res))

print("\n--- Test lookup_romance_io_spice ---")
res2 = lookup_romance_io_spice("A Court of Thorns and Roses", "Sarah J. Maas")
print("lookup_romance_io_spice result:", res2)

print("\n--- Test unrated book lookup ---")
res3 = lookup_romance_io_spice("The Serpent and the Wings of Night", "Carissa Broadbent")
print("lookup res3:", res3)
