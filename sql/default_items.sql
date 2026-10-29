-- Default Item catalogue generated from a reviewed local database.
-- Run: python -m spending.database --export-default-items

INSERT OR IGNORE INTO Brand(name) VALUES
  ('Butterkist'), ('Denny'), ('Hovis'), ('Lidl'), ('Lurpak'),
  ('Stockwell & Co.'), ('Swizzels'), ('Tesco'), ('Walkers'), ('Woodside Farms');

INSERT INTO Item(name, brand_id, category_id, barcode, pack_size, pack_unit) VALUES
  ('Nectarines', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Fruit & Vegetables'), NULL, NULL, NULL),
  ('Bananas', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Fruit & Vegetables'), NULL, NULL, NULL),
  ('Melon Honeydew', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Fruit & Vegetables'), NULL, NULL, NULL),
  ('Red Grapes Punnet', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Fruit & Vegetables'), NULL, NULL, NULL),
  ('Plain Flour', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Pantry'), NULL, NULL, NULL),
  ('Large Free Range Eggs 18piece', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Dairy & Eggs'), NULL, 18.0, 'item'),
  ('Croissant Chocolate', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Bakery'), NULL, NULL, NULL),
  ('Croissant Butter', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Bakery'), NULL, NULL, NULL),
  ('Croissant Almond', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Bakery'), NULL, NULL, NULL),
  ('Digestive Biscuits', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Snacks & Confectionery'), NULL, NULL, NULL),
  ('Tortilla Chips', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Snacks & Confectionery'), NULL, NULL, NULL),
  ('Non bio powder', (SELECT id FROM Brand WHERE name='Lidl'), (SELECT id FROM categories WHERE name='Household'), NULL, NULL, NULL),
  ('5 Custard Doughnuts', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Bakery'), NULL, 5.0, 'item'),
  ('Max Kentucky Fried Chicken Flavour Ridged Potato Crips', (SELECT id FROM Brand WHERE name='Walkers'), (SELECT id FROM categories WHERE name='Snacks & Confectionery'), NULL, 140.0, 'g'),
  ('Wholemeal Medium Sliced Bread', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Bakery'), NULL, 800.0, 'g'),
  ('Sweetheart Cabbage Each', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Fruit & Vegetables'), NULL, NULL, NULL),
  ('Pork Sausage Meat', (SELECT id FROM Brand WHERE name='Denny'), (SELECT id FROM categories WHERE name='Meat & Poultry'), NULL, 454.0, 'g'),
  ('Cheese Twists', (SELECT id FROM Brand WHERE name='Stockwell & Co.'), (SELECT id FROM categories WHERE name='Bakery'), NULL, 125.0, 'g'),
  ('Luxury Soft Flushable Moist Toilet Tissues - Coconut Oil 60', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Household'), NULL, NULL, NULL),
  ('Cooking Bacon', (SELECT id FROM Brand WHERE name='Woodside Farms'), (SELECT id FROM categories WHERE name='Meat & Poultry'), NULL, 500.0, 'g'),
  ('Microwave Popcorn Sweet & Salted', (SELECT id FROM Brand WHERE name='Butterkist'), (SELECT id FROM categories WHERE name='Snacks & Confectionery'), NULL, 180.0, 'g'),
  ('Sweet Shop Favourites Tub', (SELECT id FROM Brand WHERE name='Swizzels'), (SELECT id FROM categories WHERE name='Snacks & Confectionery'), NULL, 650.0, 'g'),
  ('Brown Onions', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Fruit & Vegetables'), NULL, 1.0, 'kg'),
  ('10 Mild Slices', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Dairy & Eggs'), NULL, 200.0, 'g'),
  ('Slightly Salted Spreadable Blend Of Butter And Rapeseed Oil', (SELECT id FROM Brand WHERE name='Lurpak'), (SELECT id FROM categories WHERE name='Dairy & Eggs'), NULL, 750.0, 'g'),
  ('Chicken Thighs', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Meat & Poultry'), NULL, 2.0, 'kg'),
  ('Wafer Thin Cooked Ham', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Meat & Poultry'), NULL, 400.0, 'g'),
  ('Broccoli', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Fruit & Vegetables'), NULL, 375.0, 'g'),
  ('Soft White Thick Sliced Bread', (SELECT id FROM Brand WHERE name='Hovis'), (SELECT id FROM categories WHERE name='Bakery'), NULL, 800.0, 'g'),
  ('Family Pack Chestnut Vitamin D Mushrooms', (SELECT id FROM Brand WHERE name='Tesco'), (SELECT id FROM categories WHERE name='Fruit & Vegetables'), NULL, 485.0, 'g');
