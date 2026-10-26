CREATE TABLE Brand (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0)
);

INSERT OR IGNORE INTO Brand(name)
SELECT DISTINCT trim(brand) FROM Item
WHERE brand IS NOT NULL AND length(trim(brand)) > 0;

ALTER TABLE Item ADD COLUMN brand_id INTEGER REFERENCES Brand(id) ON DELETE RESTRICT;

UPDATE Item
SET brand_id = (SELECT id FROM Brand WHERE name=trim(Item.brand) COLLATE NOCASE)
WHERE brand IS NOT NULL AND length(trim(brand)) > 0;
