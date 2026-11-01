import sys
sys.path.insert(0, r'C:\Users\genni\my_book_app')
from main import lookup_romance_io_spice

test_books = [
    (56, "A Demon's Guide to Wooing a Witch - Sarah Hawley", 'Unknown Author'),
    (75, 'A Rivalry of Hearts', 'Tessonja Odette'),
    (76, 'A Sensual Summoning', 'Rachel J. Roman'),
    (78, 'A Shadow in the Ember. Un’ombra fra le braci', 'Jennifer L. Armentrout'),
    (81, 'A Soul to Guide', 'Opal Reyne'),
    (82, 'A Soul to Heal: Duskwalker Brides, Book Two', 'Opal Reyne'),
    (87, 'A Touch of Chaos', 'Scarlett St.  Clair'),
    (89, 'A Touch of Malice: Hades & Persephone, Book 3', 'Scarlett St. Clair'),
]

for b_id, title, author in test_books:
    res = lookup_romance_io_spice(title, author)
    print(f'{b_id}: {title[:35]} -> {res}')
