INSERT INTO dwb_product_center_f (
    product_id,
    product_name,
    category_id,
    category_name,
    brand_id,
    brand_name,
    price,
    status,
    create_time,
    update_time,
    etl_cycle_id
)
SELECT
    p.product_id,
    p.product_name,
    c.category_id,
    c.category_name,
    b.brand_id,
    b.brand_name,
    p.price,
    CASE WHEN p.status = 1 THEN 'active' ELSE 'inactive' END AS status,
    p.create_time,
    CURRENT_TIMESTAMP AS update_time,
    '${P_CYCLE_ID}' AS etl_cycle_id
FROM dim_product_f p
LEFT JOIN dim_category_f c ON p.category_id = c.category_id
LEFT JOIN dim_brand_f b ON p.brand_id = b.brand_id
WHERE p.dt = '${P_CYCLE_ID}'
DISTRIBUTE BY HASH(product_id)
WITH (ORIENTATION=COLUMN, COMPRESSION=MIDDLE);
