-- Common grocery categories. INSERT OR IGNORE keeps setup repeatable.
INSERT OR IGNORE INTO categories(name) VALUES
  ('Fruit & Vegetables'), ('Bakery'), ('Dairy & Eggs'), ('Meat & Poultry'),
  ('Fish & Seafood'), ('Frozen'), ('Pantry'), ('Snacks & Chocolates'),
  ('Drinks'), ('Alcohol'), ('Household'), ('Health & Beauty'), ('Baby'), ('Pet');
