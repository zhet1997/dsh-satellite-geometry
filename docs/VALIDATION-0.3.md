# 0.3.0 热设计工作台开发验收

日期：2026-10-10。工程：`D:\Codes\dsh-satellite-geometry`。需求先行提交为 `206d859`，等效包络基线为 `f0a10c2`；本轮实现提交以本报告所在提交和 `git log` 为准。

本轮完成了工程师修改当前模型、保存方案副本、查看和固定 Skill、记录经验及外部程序操作的功能闭环，并已部署到本机网页版 DSH。**真实 CATCH 算例的一键建模尚不能可靠地独立完成全部工程判断。** 最终可读导出是经过开发复核的候选基线，仍需工程师核实身份、表示和热接触；本报告不把软件任务完成等同于热分析前处理验收通过。

## 1. 软件、部署和自动检查

| 项目 | 实际结果 |
|---|---|
| DSH 宿主 | Windows npm `@deepseek-ai/dsh@0.2.0-rc.2`；未认证 Electron 桌面内置宿主 |
| 插件 / 服务 | `@lbk/dsh-satellite-geometry@0.3.0` / `dsh-satellite-geometry:0.3.0` |
| 工作台 | `http://127.0.0.1:3081/satellite-geometry/`，原生 DSH 会话与三维工作台同屏 |
| 计算服务 | `http://127.0.0.1:8787/api/health` 实际返回 `status:ok, version:0.3.0` |
| 后端回归 | `service.test_api`、`service.test_geometry`、`service.test_workbench`，36 项通过，最后完整运行约 33.4 秒 |
| 插件检查 | 7 项通过，覆盖实际 stdio MCP、稳定选择引用、会话 Skill 冻结及 DSH JSON 边界 |
| 构建 | 前端与插件构建通过，最终 JS `index-BCBi70Db.js`、CSS `index-DGLgJqZM.css` |
| 数据 | 保留 `dsh-satellite-geometry_project-data` 卷，原有项目和源文件未被验收工程覆盖 |

后端检查在 WSL 的 `/home/zhet/.venvs/dsh-satellite-geometry/bin/python` 环境中进行，项目路径为 `/mnt/d/Codes/dsh-satellite-geometry`。部署仍使用 WSL Ubuntu 内的原生 Docker daemon。普通 3080 profile 不作为本轮验收目标。

## 2. 需求完成情况

| 用户场景 | 已实现并核查的行为 | 验收边界 |
|---|---|---|
| 两层中文工程树 | 分组＋单机，原代号、名称依据和完整源映射保存在详情与数据中 | 名称由模型/资料匹配，候选不能作为已确认身份 |
| 原始与简化对比 | 默认并排，稳定单机颜色，选择单机自动隔离；TOP/ISO 保持局部聚焦；可返回整星 | 预置视角同步已实际检查；自由鼠标拖动同步未完成端到端验收 |
| 工程师修改单机 | source、box、cylinder、组合体和 surface_shell；重建更新当前模型 | 具体尺寸及工程表示仍须依据资料/人工判断 |
| 真正面壳 | 面集合、零实体，厚度/材料/热属性另存；拒绝无效表示 | 零实体体积不能证明没有穿透，不从包络体积推质量或热容 |
| 保存当前方案副本 | 手动命名、保存和载入重建；共用原始几何；指纹验证恢复 | 保存不等于工程接受；无逐步撤销历史和额外接受流程 |
| DSH 上下文与右键 | 树和几何画布右键带入；SG 固定引用；原生上下文工具返回文件入口、方案、接触和固定 Skill | 实际模型必须成功读取上下文，单纯回显指纹不是证据 |
| 干涉与贴面 | 原始实体干涉、简化重叠、面壳距离/交叠、几何候选和缺失项分别保留 | 曲面、无效源拓扑及预算受限配对可为未知 |
| 接触关系图 | 点击关系联动选择双方组件，可显示三维区域并编辑接触定义 | 区域未定义时明确提示；几何候选不能直接确认热导通 |
| Skill 查看与更替 | 正文、资源、不可变版本、指纹；候选导入/另存；按原生会话冻结 | 更换版本使用新会话，旧会话不被新规则替换 |
| 经验记录 | 保存意见、实际修改、会话摘要、Skill 指纹；完整对话仍由 DSH 保存 | `autoSkillUpdate:false`，仅收集，不实时升级 Skill |
| 外部测试接口 | HTTP 业务 API、25 个 MCP 工具及 `/evidence`；按钮与程序共享作业/修订校验 | 测试框架、调度、版本比较和 gate 评分在插件外部 |
| 导出 | STEP、GLB、properties、recipes、contacts、feedback 及 ZIP | 实际 STEP 回读验证与工程接受是两个独立判断 |

业务入口、参数、原生 DSH RPC 及确定性流程见 [workbench-api.md](/D:/Codes/dsh-satellite-geometry/docs/workbench-api.md)。界面和作业不要求另装本地大模型，继续沿用 DSH 已配置的模型连接。

## 3. 合成 API 与原生 DSH 流程

合成输入为三个组件的 `contact.step`，是明确指定尺寸的开发样例，不是真实卫星参数。

| 运行 | 工程 / 会话 | 实际结论 |
|---|---|---|
| 不经过 UI 的 API 流程 | 工程 `bb62c0b0d2cc490d8bd1f39953d51a76`；导出快照 revision 6 | 完成组合体重建、面壳、命名副本保存/修改/载入、检查、导出和 evidence 下载 |
| 原生 DSH 建模 | 工程 `0f13d851447549bb9a1978baa1d09b9c`，revision 5；会话 `v03-native-d5c9716f-aa44-4f39-a8c6-822bfab02512` | 模型真实调用资料、身份、方案、副本、检查、导出工具，得到一件源几何、一件圆柱＋底座实体、一件面壳 |
| 新默认 Skill 会话 | 复用第一工程，当前 revision 7；会话 `v03-review-5557a2c2-8114-42f1-abf5-32f63be6ede2` | 真实读取新 Skill 后，仅一次将 N00003 写为候选身份；证据保留 candidate 和 `autoSkillUpdate:false` |

第一工程 revision 6 的导出文件是固定验收快照；后来候选身份检查使当前工程进入 revision 7 并使旧导出失效。不能把磁盘快照当成当前修订的新导出。原生合成工程的 STEP 回读记录为 3 个实例、20 个面、2 个实体，表示检查通过；热接触仍为候选，`thermalStatus:needs_review`。它还记录了一处简化引入的重叠，不能称为所有包络问题已经自动消除。

原生合成测试首次 `satellite_workflow_context` 返回失败，模型曾使用其他工具继续执行。问题源于 CAD 法向中的负零不符合 DSH 原生持久 JSON 的严格要求。已增加 `nativeJson` 规范化和针对实际 `snapshotJsonValue` 边界的检查；修复后单独复测了上下文工具，确认实际成功返回正文、资源、指纹和三组件上下文。首次失败被保留，没有改写成全程成功。

最新默认 Skill 指纹：

```text
0580ef821e917d56e563306138cd174c549f557aabe9ebb9b29b8b862d0817da
```

CATCH 旧会话仍固定另一候选版本：

```text
ff58842798be6679c48f9b5e6ce850a0ca078b7419bb5be43aa0805ce6174fbd
```

已在界面确认旧会话不能绑定新版本，必须新建会话。新会话的工具记录、`loadedAt` 和修改记录共同证明实际读取了新正文，未替换旧会话。模型最终答复中的未经工具支持的“N X 侧验证”等文字不作为验证证据。

## 4. CATCH 真实整星算例

输入来自本机保存的原项目文件，未重跑或修改原远端应用：

- `D:\Codes\dsh-satellite-geometry\cases\catch-original\original.step`，96,478,666 字节，33 个组件实例。
- 同目录 `CATCH02设计需求.docx`、`CATCH整星配套表.xlsx`。
- 源 STEP SHA256：`b08287d75f974a1698a2b3c9b704aa1bdbca1a96d756b7c5c161e91b3ed06845`。

独立工程为 `4f7c0f1afb834c98a339d5931f1a6588`，名称“0.3 验收：CATCH 整星独立副本”。原生会话为 `v03-catch-5d88705c-2cf4-406e-82bd-16417a790225`，标题“0.3 CATCH 热设计工作台验收”。

### 首次一键建模的结果

实际模型成功读到绑定 Skill 和两份资料，执行身份、建模、参数和接触写入。但是它错误使用旧开发记录推断身份、花费较多步骤读实现源码，并发写入遇到 409，导出失败后多次猜错原因。该轮在 revision 16 后被停止，完整失败过程保留。这次运行证明集成能调用实际能力，**没有证明一键流程的工程质量可靠**。

后续开发复核清除了无充分匹配依据的参数，最终 11 件为 candidate，22 件为有尺寸依据的 identified。后者仍需工程师核实，不等于型号和工程表示已经认证。`N00002 Envelope_part` 从错误的“星箭分离机构”改为“整星外形参考体（待核实）”；角色不明，保留源几何，没有为了消除相交而擅自删除或移动。

### STEP 序列化问题与研发候选

复核发现旧 `write_shape` 缓存写出前的内存 BRep，随后的 `read_shape` 可能没有重新读取磁盘 STEP。已新增 `read_step_fresh`，在方案重建和完整导出中真正回读文件，再测量表示和拓扑。不能把旧内存缓存检查当作实际文件验证。

太阳电池阵 N00032 的原面集合在内存中有效，真实 STEP 序列化后无效。原方案已保存为“保留原面集合：STEP序列化需修复”副本。用于当前研发验收的替代方案按源几何实测的最大六个平面建立三主板面集合：每块 431 × 680 × 10 mm，Z 中心分别为 196.91654658442、218.91654658442、238.91654658442 mm，18 面、0 实体。**这个候选不包括小型铰链/附件，安装区域和热参数未知，不是已完成的太阳阵工程模型。**

### 最终 revision 22

通过实际 UI 为 MEMS 陀螺 N00024 保存并载入“面壳基线（开发验收）”副本：ID `e6ec748bcaa840d1a95360cbd5d43864`。当前方案和保存指纹一致，为 `73eea4a43c9437b0c4e8a278c60c9efe2a05c4f9699ec05450ef7b72e5de3902`，输出 6 面、0 实体。保存/载入记录关联原 CATCH 会话和冻结 Skill。载入使检查和导出待复核，随后已重新执行 check 和 export，没有再改方案。

| 最终检查项 | 实际结果 |
|---|---|
| 导出修订 | revision 22 |
| STEP 回读 | 可读、拓扑有效、表示检查通过 |
| 装配映射 | 33 个实例、33 个原型，实例结构已核查 |
| 表示 | 31 个 surface_shell，2 个 source；总计 222 面、3 实体 |
| 原始拓扑 | 13 个源组件存在缺陷，源证据保留 |
| 源检查完整性 | `sourceComplete:false`；34 个配对因源表示不足不能确定 |
| 相交记录 | 10 个源相交记录、1 个当前实体相交记录；参考体角色仍影响解释 |
| 热接触 | 16 条记录：13 个 candidate、3 个 needs_review；识别为 partial，无已确认热导通 |
| 工程状态 | `assemblyStatus:unknown`、`thermalStatus:unknown` |
| 导出状态 | `source_defects_review_required`、`acceptanceIsSeparate:true` |

导出有效性不证明材料、热容、安装孔、线缆、真实热导通或全部壳面穿透已检查。后续应先复核参考体角色、候选设备身份、太阳阵附件和双方安装区域，再决定哪些表示及热接触能够用于下游。

## 5. 浏览器和 CAD 视图

在实际 DSH 页面、1440 × 900 的临时桌面视口完成了中文两层树、单机隔离、TOP/ISO、整星返回、稳定配色、Skill 正文查看、旧会话更替限制、树/画布右键、带入草稿、副本保存/载入和接触双方联动检查。选中接触后实际显示双方组件和区域；缺少安装区域仍显示“待定义”。仅清理了本次自行加入的 SG 草稿，未发送额外修改指令。结束时已恢复视口。

自由鼠标拖动的相机同步因浏览器输入控制未完成端到端检查；这项不能宣称已完全验收。预置视角按钮下的同步与局部聚焦已实际核查。

截图保存在本机，不纳入 npm 包或源码提交：

- [单机对比与方案编辑](/D:/Codes/dsh-satellite-geometry/validation/screenshots/v03-workbench-final.jpg)
- [接触关系与双方组件](/D:/Codes/dsh-satellite-geometry/validation/screenshots/v03-catch-contact.jpg)
- [整星原始/简化对比](/D:/Codes/dsh-satellite-geometry/validation/screenshots/v03-catch-assembly.jpg)
- [CATCH STEP 等轴测快照](/D:/Codes/dsh-satellite-geometry/validation/screenshots/v03-catch-iso_20261010T024739Z.png)
- [反向等轴测](/D:/Codes/dsh-satellite-geometry/validation/screenshots/v03-catch-opposite_20261010T024739Z.png)、[俯视](/D:/Codes/dsh-satellite-geometry/validation/screenshots/v03-catch-top_20261010T024739Z.png)、[正视](/D:/Codes/dsh-satellite-geometry/validation/screenshots/v03-catch-front_20261010T024739Z.png)
- [合成圆柱＋底座快照](/D:/Codes/dsh-satellite-geometry/validation/screenshots/v03-surface-example_20261010T015721Z.png)

CATCH 最终实际 STEP 已经 CAD snapshot 工具生成并检查四视图。主板间隔可以看见；附件缺失和参考体问题以几何记录及上述边界说明为准，截图不替代安装认证。

已有独立 CAD Viewer 运行于本机 4178。实际浏览器确认这两条链接加载到 STEP 装配树：

- [CATCH 候选基线](http://127.0.0.1:4178/?file=catch%2Fcatch-baseline.step)
- [组合体和面壳合成样例](http://127.0.0.1:4178/?file=surface-example.step)

## 6. 标准 npm 安装包与独立安装

发布产物为 [lbk-dsh-satellite-geometry-0.3.0.tgz](/D:/Codes/dsh-satellite-geometry/release/lbk-dsh-satellite-geometry-0.3.0.tgz)，标准 `npm pack` 生成，273,303 字节、16 个条目。`private:true`，未发布到公共 npm。包含预构建三维页面、Host/client、25 个 MCP 工具、固定 Skill 入口和独立 profile 安装器，不包含原始资料、凭据或 CAD/Python 计算环境。

```text
SHA256  78a7c2fea17c33bd12b4045a8b70277d0e457cbdd6bc6a300b0ac297ee5bc7cf
npm SHA1  66f1f69e289875d6e81f7274dc79beb23b8edcf7
```

已在新的 `validation/package-install-smoke/v03-final` 目录仅安装生产依赖。实际验证了包版本、Host 导入、client 和预构建 Viewer、stdio MCP 25 工具及真实服务能力读取。随后使用隔离 `DSH_HOME` 安装 profile，在 3084 启动该**已打包安装的插件**，完成登录、工作台/Viewer 页面、计算 API 代理和设置 RPC 检查；结束已停止该临时进程。没有把生产 profile 改到临时目录。

本机 3081 profile 仍链接正式工程的 `plugin` 目录。迁移安装说明见 [plugin/README.md](/D:/Codes/dsh-satellite-geometry/plugin/README.md)；`.tgz` 和 Docker 服务是两个独立部署部分。

## 7. 产物、证据和后续使用

| 产物 | 修订 / 大小 | SHA256 |
|---|---|---|
| `validation/artifacts/v03/surface-example.step` | 合成 API revision 6 / 62,484 字节 | `29b5eb0eebb3c6662311bce1a41493196d802bc6213ab9a8ec15c01f67e27696` |
| `validation/artifacts/v03/catch/catch-baseline.step` | CATCH revision 22 / 882,745 字节 | `70a64baafcd4022513bc8d4e75d4773cdc9352d821b562d4650fe143879bf48c` |
| `validation/artifacts/v03/catch/catch-baseline.zip` | CATCH revision 22 / 348,054 字节 | `69c018e7335d9ddbc15f078f6ae38d6b79a92b314e63690831dd2cf07c0a2f9a` |

CATCH 同目录保留 `recipes.json`、`contacts.json` 和 `report.json`；ZIP 含 `simplified.step`、`simplified.glb`、`properties.json`、`recipes.json`、`contacts.json`、`feedback.json`。真正持久工程在 Docker 卷里，本机下载文件是带修订的证据快照。

原始验证证据位于 `validation/raw/v03`，受 `.gitignore` 保护：

- `api.json`：合成 API 全流程。
- `native-evidence.json`：原生模型建模、首次上下文问题和修复复测记录。
- `real-native-evidence.json`：CATCH 首次模型运行及失败；不覆盖为成功记录。
- `catch-identity-audit.json`、`catch-identity-correction.json`：开发身份复核。
- `catch-final-evidence.json`：CATCH revision 22 的完整工程与 evidence。
- `review-evidence.json`：新 Skill 实际读取与候选身份写入。
- `package-install.json`：最终包独立安装及临时宿主运行。
- `final-summary.json`：当前独立工程、源哈希、导出哈希和验收边界的汇总。

这些临时脚本和记录是本次开发的验收材料，不是插件内置测试框架。后续外部测试应使用新的独立工程和 DSH 会话，保存 Skill 正文/资源/指纹、真实工具结果和 `/evidence`，按工程目标自行评分。优先增加身份错误、源面序列化、参考几何、壳面穿透及安装区域映射的规定测试；不能仅用“作业 completed”或模型自然语言答复作 gate。
