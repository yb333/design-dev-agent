CREATE TABLE IF NOT EXISTS dwb_product_center_f (
    product_id          BIGINT          NOT NULL,
    product_name        VARCHAR(200)    NOT NULL,
    category_id         BIGINT,
    category_name       VARCHAR(100),
    brand_id            BIGINT,
    brand_name          VARCHAR(100),
    price               DECIMAL(18,2),
    status              VARCHAR(20)     DEFAULT 'active',
    create_time         TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    update_time         TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    etl_cycle_id        VARCHAR(50),
    CONSTRAINT pk_product_center PRIMARY KEY (product_id)
)
DISTRIBUTE BY HASH(product_id)
WITH (ORIENTATION=COLUMN, COMPRESSION=MIDDLE);
