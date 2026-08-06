-- Adds 3 newer orders to demonstrate INCREMENTAL sync (cursor moves past id 12).
USE demo_shop_mysql;
INSERT INTO shop_orders (order_date, customer, region, product, quantity, unit_price, total) VALUES
('2026-07-08','Devi Stores','North','Widget A',6,49.90,299.40),
('2026-07-11','Harini Traders','South','Widget C',2,210.00,420.00),
('2026-07-14','Asha Retail','South','Widget B',4,120.00,480.00);
