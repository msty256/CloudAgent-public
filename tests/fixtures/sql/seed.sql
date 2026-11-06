-- ---------------------------------------------------------------------------
-- tests/fixtures/sql/seed.sql — sql 域取证基线种子（幂等，可重复执行）
--
-- 这是 orders / customers 仿真数据的**仓库内唯一权威来源**（P1，2026-11-07）：
-- 旧仓 CloudAgent（私有）的 scripts/sql_db/seed.sql 迁入本仓，按本仓现状修正。
-- 执行者需为表 owner 或超级用户，目标库 cloudagent_sim（或等价临时库）：
--
--   psql -h 127.0.0.1 -p 5433 -U postgres -d cloudagent_sim -f tests/fixtures/sql/seed.sql
--
-- 被断言依赖的显式事实（sql 域 gt 的前提，改动任何一条都必须同步案例库）：
--   F1. orders 只有主键索引——tenant_id / created_at / customer_id / status
--       故意不建任何索引（sql-001/002/006/008/009 的 index_absent 断言依赖）
--   F2. customers.region 建普通二级索引 idx_customers_region（sql-003/004/014）
--   F3. orders.tenant_id = 1 + (i % 50)：取值 1..50，每租户恰好 1000 行
--   F4. orders.status 四值循环：created/paid/shipped/cancelled 各恰好 12500
--       行（sql-008 的选择性 ~25% 断言依赖）
--   F5. orders.created_at 固定基准往前推 ~30 天（见下方差异 D2）；
--       sql-002/009 的时间范围断言依赖「created_at 无索引 ⇒ 预估计划 Seq Scan」
--   F6. 末尾 ANALYZE（sql-003 的 Bitmap 代价比较与 sql-014 的 n_live_tup /
--       n_distinct 断言都依赖统计新鲜）
--
-- 与旧仓 seed 的差异（迁移时逐项核对过）：
--   D1.【保留】tenant_id / status / customer_id / amount 的生成式与旧仓一致，
--      与 cloudagent_sim 2026-11-07 实测现状逐项吻合（50000 行、每租户 1000、
--      每状态 12500、region 四值各 500）。
--   D2.【必改】created_at 由 `now() - (i % 43200) minutes`（30 天滚动）改为
--      固定基准 TIMESTAMPTZ '2026-10-14 00:00:00+08' 往前推：滚动时间会让
--      sql-002「近 1 天」断言随执行时刻漂移，固定基准保证分布可复现。
--      基准取历史 seed 日期（案例 notes 的人工实测日期）。
--      已知推论（2026-11-07 真库 EXPLAIN 验证过）：真实时刻晚于基准后，
--      sql-002/009 的范围条件实际命中 0 行，但 F1 保证无索引可选，
--      预估计划（explain_sql 无 ANALYZE）仍是 Seq Scan + Filter，断言成立。
--   D3.【新增】order_no 业务单号列（补列 + 回填，与 sync_seed_primary.sql
--      的写法保持一致）：日志/案例里的业务单号 order-778812 要能落到真实列。
--
-- 分工边界：tenants / devices 归 tests/fixtures/sql/sync_seed_primary.sql，
-- 两份 seed 不重叠——本文件 TRUNCATE 只碰 orders / customers。
-- 授权：只授予 SELECT；本文件不含任何凭据（角色由环境 bootstrap 预先创建）。
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS customers (
    id     bigint PRIMARY KEY,
    name   text NOT NULL,
    region text NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id          bigint PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES customers(id),
    tenant_id   bigint NOT NULL,
    created_at  timestamptz NOT NULL,
    status      text NOT NULL,
    amount      numeric(12, 2) NOT NULL
);

-- 幂等重放：清空后重新灌入。单条 TRUNCATE 同时列出两表以满足
-- orders → customers 的外键引用；主键为显式值，不做 RESTART
TRUNCATE orders, customers;

INSERT INTO customers (id, name, region)
SELECT i,
       'customer-' || i,
       (ARRAY['north', 'south', 'east', 'west'])[1 + (i % 4)]
FROM generate_series(1, 2000) AS i;

-- created_at 用固定基准（差异 D2）；i % 43200 覆盖 0..43199 分钟 ≈ 30 天
INSERT INTO orders (id, customer_id, tenant_id, created_at, status, amount)
SELECT i,
       1 + (i * 37 % 2000),
       1 + (i % 50),
       TIMESTAMPTZ '2026-10-14 00:00:00+08' - ((i % 43200) || ' minutes')::interval,
       (ARRAY['created', 'paid', 'shipped', 'cancelled'])[1 + (i % 4)],
       (i % 1000)::numeric / 10
FROM generate_series(1, 50000) AS i;

-- 对照用二级索引（F2）。orders 故意只有主键（F1）——不要在这里给 orders
-- 的 tenant_id / created_at / customer_id / status 加任何索引
CREATE INDEX IF NOT EXISTS idx_customers_region ON customers(region);

-- orders 的业务键列（差异 D3，与 sync_seed_primary.sql 相同的补列 + 回填）
ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_no text;
UPDATE orders SET order_no = 'order-' || id WHERE order_no IS NULL;

-- 统计信息必须新鲜（F6）
ANALYZE customers;
ANALYZE orders;

-- 只读角色授权（角色预先存在；本文件不含凭据）
GRANT USAGE ON SCHEMA public TO cloudagent_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cloudagent_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cloudagent_ro;
