-- Demo MySQL source database for InsightForge connector testing/walkthroughs.
-- Run as root:  mysql -u root < database/seeds/demo_shop_mysql.sql
-- Creates database demo_shop_mysql + user demo/devpassword with 12 orders.
CREATE DATABASE IF NOT EXISTS demo_shop_mysql;
CREATE USER IF NOT EXISTS 'demo'@'127.0.0.1' IDENTIFIED BY 'devpassword';
CREATE USER IF NOT EXISTS 'demo'@'localhost' IDENTIFIED BY 'devpassword';
CREATE USER IF NOT EXISTS 'demo'@'%' IDENTIFIED BY 'devpassword';
GRANT ALL ON demo_shop_mysql.* TO 'demo'@'127.0.0.1';
GRANT ALL ON demo_shop_mysql.* TO 'demo'@'localhost';
GRANT ALL ON demo_shop_mysql.* TO 'demo'@'%';
USE demo_shop_mysql;
DROP TABLE IF EXISTS shop_orders;
CREATE TABLE shop_orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_date DATE NOT NULL,
  customer VARCHAR(120) NOT NULL,
  region VARCHAR(40),
  product VARCHAR(80) NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  total DECIMAL(12,2) NOT NULL
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
('2026-06-27','Eshan Mart','West','Widget B',3,120.00,360.00);
