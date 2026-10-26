-- 同步诊断仿真数据：primary（上游）
-- 变更 add-sync-analysis-skill（design D7）
--
-- 幂等：可重复执行。执行者需为表 owner 或超级用户；末尾显式授权只读角色，
-- 不依赖 ALTER DEFAULT PRIVILEGES 的时序。
--
-- 四张表的对照关系（orders / customers 由既有 seed.sql 提供）：
--   orders     50000 行 vs 下游 0     —— 上游有、下游无（未落库）
--   customers   2000 行 vs 下游 0     —— 同向未同步
--   devices       50 行 vs 下游 50    —— 两侧一致（对照组）
--   tenants        0 行 vs 下游 8     —— 上游无、下游有（反向差异）

CREATE TABLE IF NOT EXISTS tenants (
    id      bigint PRIMARY KEY,
    name    text NOT NULL,
    region  text NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id         bigint PRIMARY KEY,
    tenant_id  bigint NOT NULL,
    model      text NOT NULL,
    status     text NOT NULL
);

TRUNCATE tenants;
TRUNCATE devices;

-- 上游刻意没有租户行：与下游的 8 行形成反向差异
-- 50 台设备：两侧同 id / 同型号 / 同状态，构成「已同步」对照组
INSERT INTO devices (id, tenant_id, model, status)
SELECT g,
       1000 + (g % 5),
       'NE-' || lpad(((g % 7) + 1)::text, 2, '0'),
       CASE WHEN g % 11 = 0 THEN 'offline' ELSE 'online' END
FROM generate_series(1, 50) AS g;

-- orders 的业务键列（日志/案例里的 order-778812 要能落到真实列上；
-- 既有 seed.sql 的 orders 只有 bigint id，没有业务单号列）
ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_no text;
UPDATE orders SET order_no = 'order-' || id WHERE order_no IS NULL;

GRANT SELECT ON devices, tenants TO cloudagent_ro;
