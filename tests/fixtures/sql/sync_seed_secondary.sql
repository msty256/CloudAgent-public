-- 同步诊断仿真数据：secondary（下游）
-- 变更 add-sync-analysis-skill（design D7）
--
-- 与 sync_seed_primary.sql 配合使用：devices 完全一致（已同步），
-- tenants 多出 8 行（上游没有）——用来推翻「下游整库不同步」的假设。

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

-- 8 个租户：上游没有这些行
INSERT INTO tenants (id, name, region)
SELECT g,
       'tenant-' || lpad(g::text, 3, '0'),
       CASE WHEN g % 2 = 0 THEN 'north' ELSE 'south' END
FROM generate_series(1, 8) AS g;

-- 与上游完全一致的 50 台设备（同 id / model / status）
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
