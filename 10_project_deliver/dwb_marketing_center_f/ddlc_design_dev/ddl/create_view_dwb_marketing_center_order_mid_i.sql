/* I视图: slmar.dwb_marketing_center_order_mid_i（营销中心宽表，F表镜像，对外消费接口） */
CREATE OR REPLACE VIEW slmar.dwb_marketing_center_order_mid_i AS
SELECT
    order_cnt,
    gmv_amount,
    participant_cnt,
    total_discount_amount,
    new_user_rate
FROM slmar.dwb_marketing_center_order_mid_f;

COMMENT ON TABLE slmar.dwb_marketing_center_order_mid_i IS '营销中心宽表（视图）';

COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_i.order_cnt IS '活动订单数';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_i.gmv_amount IS '活动GMV';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_i.participant_cnt IS '参与人数';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_i.total_discount_amount IS '活动优惠金额';
COMMENT ON COLUMN slmar.dwb_marketing_center_order_mid_i.new_user_rate IS '新客占比(%)';
