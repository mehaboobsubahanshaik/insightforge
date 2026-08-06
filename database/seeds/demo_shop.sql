-- Example PostgreSQL SOURCE database for the PostgreSQL connector.
-- Run:  psql -h 127.0.0.1 -U postgres -f seed/demo_shop.sql
-- Creates a separate database "demo_shop" that InsightForge connects TO
-- (do not point the connector at the insightforge control-plane database).
DROP DATABASE IF EXISTS demo_shop;
CREATE DATABASE demo_shop;
\connect demo_shop
CREATE TABLE shop_orders (
  id serial PRIMARY KEY,           -- cursor column for incremental sync
  order_date date NOT NULL,
  customer text NOT NULL,
  region text,                     -- NULLs on purpose: exercises R001 missing-value rule
  product text NOT NULL,
  quantity integer NOT NULL,
  unit_price numeric(10,2) NOT NULL,
  total numeric(12,2) NOT NULL
);
INSERT INTO shop_orders (order_date, customer, region, product, quantity, unit_price, total) VALUES
('2026-06-01','Asha Retail','South','Widget A',10,49.90,499.00),
('2026-06-03','Bimal Traders','North','Widget B',5,120.00,600.00),
('2026-06-05','Chetan & Co','South','Widget A',8,49.90,399.20),
('2026-06-08','Devi Stores',NULL,'Widget C',3,210.00,630.00),
('2026-06-10','Asha Retail','South','Widget B',2,120.00,240.00),
('2026-06-12','Eshan Mart','West','Widget A',12,49.90,598.80),
('2026-06-15','Farhan Goods','East','Widget C',6,210.00,1260.00),
('2026-06-18','Bimal Traders','North','Widget A',4,49.90,199.60),
('2026-06-20','Gita Supplies',NULL,'Widget B',7,120.00,840.00),
('2026-06-22','Chetan & Co','South','Widget C',2,210.00,420.00),
('2026-06-25','Asha Retail','South','Widget A',15,49.90,748.50),
('2026-06-27','Eshan Mart','West','Widget B',3,120.00,360.00),
('2026-06-29','Devi Stores','North','Widget A',9,49.90,449.10),
('2026-07-02','Farhan Goods','East','Widget B',4,120.00,480.00),
('2026-07-05','Gita Supplies','West','Widget C',5,210.00,1050.00);
