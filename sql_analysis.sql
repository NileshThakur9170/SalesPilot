-- ============================================================
-- SalesPilot Dashboard
-- SQL Analysis Companion (MySQL / PostgreSQL compatible)
-- Data source: sales_data.csv (1,600 orders, FY2024-2025)
-- ============================================================

-- 1. SCHEMA
CREATE TABLE sales (
    order_id        VARCHAR(20)     PRIMARY KEY,
    order_date      DATE            NOT NULL,
    region          VARCHAR(20),
    city            VARCHAR(30),
    segment         VARCHAR(20),
    ship_mode       VARCHAR(20),
    category        VARCHAR(20),
    sub_category    VARCHAR(20),
    product_name    VARCHAR(60),
    sales_rep       VARCHAR(40),
    customer_name   VARCHAR(60),
    quantity        INT,
    unit_price      DECIMAL(10,2),
    discount        DECIMAL(4,2),
    sales           DECIMAL(12,2),
    cost            DECIMAL(12,2),
    profit          DECIMAL(12,2),
    profit_margin   DECIMAL(6,4)
);

-- Load with (MySQL):
-- LOAD DATA LOCAL INFILE 'sales_data.csv' INTO TABLE sales
-- FIELDS TERMINATED BY ',' ENCLOSED BY '"' LINES TERMINATED BY '\n' IGNORE 1 ROWS;

-- ============================================================
-- 2. KPI SUMMARY
-- ============================================================
SELECT
    ROUND(SUM(sales), 2)                       AS total_sales,
    ROUND(SUM(profit), 2)                      AS total_profit,
    ROUND(SUM(profit) / SUM(sales) * 100, 2)   AS profit_margin_pct,
    COUNT(*)                                   AS total_orders,
    ROUND(SUM(sales) / COUNT(*), 2)            AS avg_order_value
FROM sales;

-- ============================================================
-- 3. REVENUE & PROFIT BY REGION
-- ============================================================
SELECT
    region,
    ROUND(SUM(sales), 2)                       AS total_sales,
    ROUND(SUM(profit), 2)                      AS total_profit,
    ROUND(SUM(profit) / SUM(sales) * 100, 2)   AS profit_margin_pct,
    COUNT(*)                                   AS orders
FROM sales
GROUP BY region
ORDER BY total_sales DESC;

-- ============================================================
-- 4. MONTH-OVER-MONTH SALES TREND (window function)
-- ============================================================
SELECT
    DATE_FORMAT(order_date, '%Y-%m')           AS order_month,
    ROUND(SUM(sales), 2)                       AS monthly_sales,
    ROUND(SUM(profit), 2)                      AS monthly_profit,
    ROUND(
        (SUM(sales) - LAG(SUM(sales)) OVER (ORDER BY DATE_FORMAT(order_date, '%Y-%m')))
        / LAG(SUM(sales)) OVER (ORDER BY DATE_FORMAT(order_date, '%Y-%m')) * 100, 2
    )                                            AS mom_growth_pct
FROM sales
GROUP BY order_month
ORDER BY order_month;

-- ============================================================
-- 5. TOP 10 PRODUCTS BY PROFIT (with rank)
-- ============================================================
SELECT
    product_name,
    ROUND(SUM(sales), 2)   AS total_sales,
    ROUND(SUM(profit), 2)  AS total_profit,
    RANK() OVER (ORDER BY SUM(profit) DESC) AS profit_rank
FROM sales
GROUP BY product_name
ORDER BY total_profit DESC
LIMIT 10;

-- ============================================================
-- 6. LOW-MARGIN PRODUCTS FLAGGED FOR REVIEW (< 15% margin)
-- ============================================================
SELECT
    product_name,
    category,
    ROUND(SUM(sales), 2)                      AS total_sales,
    ROUND(SUM(profit) / SUM(sales) * 100, 2)  AS profit_margin_pct
FROM sales
GROUP BY product_name, category
HAVING SUM(profit) / SUM(sales) < 0.15
ORDER BY total_sales DESC;

-- ============================================================
-- 7. SALES REP LEADERBOARD WITH RUNNING TOTAL
-- ============================================================
SELECT
    sales_rep,
    ROUND(SUM(sales), 2) AS total_sales,
    ROUND(SUM(profit), 2) AS total_profit,
    COUNT(*) AS orders,
    ROUND(
        SUM(SUM(sales)) OVER (ORDER BY SUM(sales) DESC), 2
    ) AS running_total_sales
FROM sales
GROUP BY sales_rep
ORDER BY total_sales DESC;

-- ============================================================
-- 8. CUSTOMER SEGMENT PROFITABILITY
-- ============================================================
SELECT
    segment,
    ROUND(SUM(sales), 2)                       AS total_sales,
    ROUND(SUM(profit), 2)                      AS total_profit,
    ROUND(SUM(profit) / SUM(sales) * 100, 2)   AS profit_margin_pct,
    ROUND(SUM(sales) / COUNT(*), 2)            AS avg_order_value
FROM sales
GROUP BY segment
ORDER BY total_profit DESC;

-- ============================================================
-- 9. DISCOUNT IMPACT ON PROFIT MARGIN
-- ============================================================
SELECT
    CASE
        WHEN discount = 0 THEN 'No Discount'
        WHEN discount <= 0.10 THEN 'Low (1-10%)'
        WHEN discount <= 0.20 THEN 'Medium (11-20%)'
        ELSE 'High (>20%)'
    END                                          AS discount_band,
    COUNT(*)                                     AS orders,
    ROUND(SUM(sales), 2)                         AS total_sales,
    ROUND(SUM(profit) / SUM(sales) * 100, 2)     AS profit_margin_pct
FROM sales
GROUP BY discount_band
ORDER BY profit_margin_pct DESC;

-- ============================================================
-- 10. TOP CITY PER REGION (window function: ROW_NUMBER)
-- ============================================================
WITH city_sales AS (
    SELECT
        region, city,
        SUM(sales) AS total_sales,
        ROW_NUMBER() OVER (PARTITION BY region ORDER BY SUM(sales) DESC) AS rn
    FROM sales
    GROUP BY region, city
)
SELECT region, city, ROUND(total_sales, 2) AS total_sales
FROM city_sales
WHERE rn = 1
ORDER BY total_sales DESC;
