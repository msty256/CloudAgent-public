# 提示词：生成 Java 诊断样本项目

> 用途：交给另一个 agent，产出 cross 域 6 道诊断题所依赖的 Java 样本项目。
> 生成后放回本仓，把 cross-001~006 的 `verification` 从 `external` 改成 `static`。
> 整理日期：2026-11-03

---

## 可直接复制的提示词

````text
你的任务：创建一个可编译的 Java 多租户后端示例项目，它会被用作"故障诊断 Agent"的
评测样本。项目里要**真实地埋入 6 个典型缺陷**，让诊断 Agent 通过读代码、找符号、
grep 关键词就能定位原因。

## 一、产物

一个 Maven 多模块项目，目录名 `tenant-platform/`，放在当前目录下：

```
tenant-platform/
├── pom.xml
├── README.md                  # 只说"这是什么系统"，不提任何缺陷
├── docs/
│   └── symptoms.md            # 6 条用户反馈（见第四节），只描述现象，不写原因
├── logs-sim/                  # 仿真日志，纯文本
│   ├── svc-a-2026-10-22.log
│   └── svc-b-2026-10-22.log
├── svc-a-gateway/             # 调用方服务
│   ├── pom.xml
│   └── src/main/java/com/example/tenanta/
│       ├── web/WorkbenchController.java
│       └── client/DeviceFeignClient.java
└── svc-b-device/              # 被调方服务（缺陷主要在这里）
    ├── pom.xml
    └── src/main/
        ├── java/com/example/tenantb/
        │   ├── repository/DeviceRepository.java
        │   ├── repository/TenantConfigRepository.java
        │   ├── web/TenantScopeFilter.java
        │   ├── mapper/DeviceMapper.java
        │   ├── mapper/DeviceMapper.xml
        │   ├── consumer/DeviceSyncConsumer.java
        │   ├── service/BatchSyncService.java
        │   └── service/ClueVersionService.java
        └── resources/application.yml
```

要求：`mvn -q compile` 能通过。允许用**最小的桩**（比如只声明接口、不引真实中间件），
但业务逻辑必须是真的、能读懂的 Java 代码。

## 二、项目背景（写进 README）

"租户云平台"：管理物联网设备的多租户 SaaS。
- `svc-a-gateway` 是 BFF/网关层，通过 Feign 调用 `svc-b-device`。
- `svc-b-device` 负责设备数据存储、租户范围隔离、批量同步（从上游拉设备）、
  版本化删除线索（clue）。
- 数据按租户隔离，租户信息从「会话」和「请求头」两处都能拿到。
- 批量同步用固定线程池并行拉取，全部完成后统一写库。

## 三、六个必须埋入的缺陷

**每个缺陷的类名、方法名必须逐字符一致**（诊断 Agent 会按这些符号搜索）。

### 缺陷 1：跨服务级联异常
- 文件：`svc-b-device/.../repository/TenantConfigRepository.java`
- 方法：`public TenantConfig resolveTenant(String tenantId)`
- 写法：从 `Map<String, TenantConfig> configCache` 里 `return configCache.get(tenantId);`
  **不判空**。当某个租户没有配置时返回 null。
- 调用它的地方（`DeviceRepository.findByTenant`）直接 `config.getRetentionDays()`，
  于是抛 `NullPointerException: tenant config missing`。
- `svc-a-gateway` 的 `DeviceFeignClient` 把 FeignException 包装后重新抛出，
  日志里表现为 svc-a 也报错——但**最早失败点在 svc-b**。
- 日志：`svc-b` 日志里先出现 NPE，`svc-a` 日志里晚 20~80ms 出现 `FeignException` / `500`。

### 缺陷 2：租户范围过滤把结果过滤为空
- 文件：`svc-b-device/.../web/TenantScopeFilter.java`
- 关键方法：`protected String currentTenant(HttpServletRequest req)`
- 写法：从 **session** 取租户：
  `return (String) req.getSession().getAttribute("tenantId");`
  而请求头里带的是**子租户** `X-Tenant-Id`，且两者在"客户从主账号切到子账号"时不一致。
- 下游 `DeviceMapper.listDevices` 用取到的租户拼 `WHERE tenant_id = #{tenantId}`，
  于是查不到（但表里确实有数据，属于另一个租户）。
- 日志：`listDevices` 的 SQL 日志里能看到 `tenant_id = 'T1001'`，
  而请求头是 `X-Tenant-Id: T1002`；表里 T1002 有 37 条设备记录。

### 缺陷 3：分页查询缺少唯一排序键导致跨页重复
- 文件：`svc-b-device/.../mapper/DeviceMapper.xml`
- 关键片段：`ORDER BY d.classification`（**只有这一个字段，没有 id 作为 tiebreaker**）
- 现象：同一页内的设备按 classification 排序时，值相同的行顺序不稳定，
  翻页时出现同一台设备重复出现、另一台被跳过。
- 同时 `BatchSyncService` 里按主键 upsert，所以**数据本身没有重复行**——
  必须能排除"同步重复写入"这个错误方向。

### 缺陷 4：消息重复消费
- 文件：`svc-b-device/.../consumer/DeviceSyncConsumer.java`
- 关键方法：`public void onMessage(DeviceSyncMessage msg)`
- 写法顺序错误：
  ```java
  // 先提交位点
  commitOffset(msg.getPartition(), msg.getOffset());
  try {
      deviceService.apply(msg);      // 业务处理
  } catch (Exception e) {
      throw new RuntimeException(e); // 抛出 → broker 重投 → 但位点已提交/或重复投递
  }
  ```
- 现象：上游一条设备变更消息被处理两次，同一设备出现两条审计记录。
- 日志：同一个 `msgId` 出现两次"apply"记录，中间夹一条异常。

### 缺陷 5：固定线程池 + 等待全部完成导致超时
- 文件：`svc-b-device/.../service/BatchSyncService.java`
- 写法：
  ```java
  private final ExecutorService pool = Executors.newFixedThreadPool(4);
  public void syncBatch(List<Device> devices) {
      List<Future<?>> futures = devices.stream()
          .map(d -> pool.submit(() -> fetchAndPrepare(d)))
          .collect(Collectors.toList());
      awaitAll(futures);            // 全部完成后才写库
      deviceRepository.batchSave(devices);
  }
  ```
- 关键参数：`corePoolSize = 4`；单设备 `fetchAndPrepare` 平均 150ms；
  `application.yml` 里 `sync.batch.timeout-ms: 2000`。
- 现象：单批设备数从 20 涨到 60 后，`(60/4)*150 = 2250ms` 超过 2000ms 阈值 → 整体超时。
- 日志：`awaitAll` 超时告警，且能看到批次大小从 20 → 60 的变化。

### 缺陷 6：批量删除未排序导致死锁环路
- 文件：`svc-b-device/.../service/ClueVersionService.java`
- 关键方法：`public void deleteClueVersion(List<Long> clueIds)`
- 写法：直接按传入顺序循环删：
  ```java
  for (Long id : clueIds) {
      clueMapper.deleteById(id);      // 没有先排序
  }
  ```
- 而 `insertClueVersion` 那边是按 `id` 升序插入/加锁的（要写出来，作为对照）。
- 现象：并发删除 + 插入时出现 `Deadlock found when trying to get lock`。
- 日志：`Deadlock` 出现两次，`clue_id` 顺序不同。

## 四、`docs/symptoms.md`：只写现象

写 6 条用户/运维视角的反馈，**不要出现"根因""因为""bug"这些词**：

1. "工作台加载设备列表报 500，网关日志里是 Feign 调用失败，设备服务日志里有空指针。"
2. "客户说看不到设备，但接口返回 200 且列表是空的，切到主账号能看到。"
3. "设备列表翻到第 3 页时，会重复出现第 2 页的设备，换个时间再翻又好了。"
4. "同一台设备今天产生了 3 条变更审计，本该只有 1 条。"
5. "批量同步昨天开始频繁超时，客户设备数从 20 台涨到 60 台后更明显。"
6. "线索版本管理偶发报死锁，重试就好，但每天都会出现。"

## 五、硬约束（违反任一条，这批样本就作废）

1. **绝对不能在代码里留 `BUG` / `FIXME` / `TODO` / `XXX` / `hack` 之类标记**，
   也不能写"这里有问题"之类的注释。诊断 Agent 要能靠推理找到，不能靠标记捡漏。
2. **每个缺陷附近要放合理的"正常代码"**：比如 `TenantScopeFilter` 里同时正确处理
   另外一个头，`BatchSyncService` 里有一处正确用了 `invokeAll` 的其他方法。
3. **不要在一处同时埋两个缺陷**，六个缺陷分散在六个不同的类里。
4. 代码里的**字符串字面量**（日志文本、异常消息）要真实，比如
   `"tenant config missing: {}"`、`"Deadlock found when trying to get lock"`。
5. 表结构写在 `docs/schema.sql`（设备表、租户配置表、线索版本表），
   并给出**能对得上日志的数据量**（例如 T1002 租户 37 条设备）。
6. `logs-sim/` 里的日志要能和时间线对上：先 svc-b 的 NPE，后 svc-a 的 Feign 错误。

## 六、交付前自检（逐条打勾再交）

- [ ] `mvn -q compile` 通过
- [ ] 六个关键符号全部存在且拼写一致：
      `resolveTenant` / `TenantScopeFilter` / `listDevices` /
      `commitOffset` / `awaitAll` / `deleteClueVersion`
- [ ] 全文 grep `BUG|FIXME|TODO|XXX|hack` 无命中
- [ ] `ORDER BY` 只按 `classification`，没有 id
- [ ] 线程池大小 4、单设备耗时与超时阈值能对上算式
- [ ] `insertClueVersion` 按 id 升序，`deleteClueVersion` 不排序
- [ ] `docs/symptoms.md` 六条都不含"因为/根因/问题在于"
- [ ] 日志里能查到：NPE 行、Feign 错误行、`tenant_id = 'T1001'` 的 SQL、
      同一 msgId 两次 apply、批次 20→60、两次 Deadlock

## 七、交付格式

输出完整文件树 + 每个文件的完整内容。不要省略（诊断 Agent 会真的去读这些文件，
"省略若干行"会让它取不到证据）。最后附一句自检结果。
````

---

## 拿到项目之后，本仓要做的事

1. 把 `tenant-platform/` 放进仓库（建议 `samples/java/`，体积不大，都是源码）；
2. 改 6 个 case 的 `verification`：`external` → `static`，
   `verified_against` 写成 `samples/java/tenant-platform/...` 的具体文件路径；
3. 跑 `tests/diagnosis/test_case_meta.py`——分布数字是锁死的，**必须同步更新**；
4. 更新 `docs/case-audit-2026-11-01.md` §9 的待办。

改完之后可核题数：17 → **23**（cross 6 题转正）。
