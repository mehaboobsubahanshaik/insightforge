-- Incremental-sync demo: run AFTER the first sync, then sync again.
-- Only these new rows (id > cursor) are extracted.
\connect demo_shop
INSERT INTO shop_orders (order_date, customer, region, product, quantity, unit_price, total) VALUES
('2026-07-08','Asha Retail','South','Widget C',2,210.00,420.00),
('2026-07-10','Bimal Traders','North','Widget B',6,120.00,720.00),
('2026-07-12','Hema Bazaar','West','Widget A',11,49.90,548.90);
