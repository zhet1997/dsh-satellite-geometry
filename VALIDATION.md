# 第一版开发与验收记录

记录日期：2026-09-29。运行环境：Windows、WSL Ubuntu、Linux Docker，DSH 0.1.1-rc.2，CadQuery 2.8.0。原服务器项目只读，独立代码位于本仓库。

## 验收结论的范围

四个案例的应用流程、最终 HTTP 导出和下载验证完成。**流程完成不等于 STEP 拓扑有效；拓扑有效也不等于工程验收合格。** 下表逐项保留真实判定；`unknown` 表示检查未确定，不能按通过处理。有源拓扑缺陷的文件只作为复核资料，源与输出均无效时仅供复核与修复，不适合作为已验收的下游 CAD / CAE 输入。

## 实际交付

桌面快捷方式：`D:\Desktop\卫星几何工作台.lnk`。工作台：<http://127.0.0.1:3081/satellite-geometry/>。独立 Docker 服务：`127.0.0.1:8787`，持久卷：`dsh-satellite-geometry_project-data`。使用 DSH 已配置模型，插件包含界面、15 个 MCP 工具和操作 Skill。

## 原项目真实案例

两份整星 STEP 与配套资料来自用户指定的 5090 服务器。减速箱和 Dawn 推进器是其中的真实源原型。来源和 SHA256 见 [cases/README.md](cases/README.md)。正式容器复用了已经保存的导入与简化状态；本次最终验证执行导出、下载、文件哈希比对、STEP 回读和命名实例检查。早期结果保存在各案例的 `initial-export-attempt.json`，没有把早期失败记录覆盖为通过。

| 案例 | 组件数 | 简化 / 保留 | 装配 / 热状态 | 原始真实干涉 | 包络假干涉：初始 → 最终 |
|---|---:|---:|---|---:|---:|
| 原项目卫星装配 | 194 | 3 / 191 | unknown / unknown | 43 | 8 → 0 |
| 原项目 CATCH | 33 | 0 / 33 | unknown / unknown | 10 | 0 → 0 |
| 有效行星减速箱组件 | 1 | 1 / 0 | passed / passed | 0 | 0 → 0 |
| Dawn 推进器源缺陷回归 | 1 | 0 / 1 | unknown / unknown | 0 | 0 → 0 |

两份整星按热分析用途保留接触原形：卫星装配仅简化 **3 / 194** 个组件，CATCH 简化 **0 / 33** 个。这是有限简化率，不能表述为完成了大幅减面。卫星装配发现的 8 对包络新增假干涉经细化或回退后剩余 0 对，原始 43 对真实干涉保留并报告。四个案例全部组件在项目记录中的当前位姿字段与原始位姿字段逐一相同，没有提交移动零件来消除干涉的操作；这项记录级核对与导出文件中的世界几何核对分开报告。

194 组件整星最终 STEP 已另作逐实例核对，证据哈希与最终下载文件一致：完成 194 个组件的世界变换与世界 BRep 范围比较，最大世界变换矩阵元素差 9.99201e-15，最大世界几何边界差 1.7053e-13 mm，面数逐项一致。该项位置核对结论为**通过**。比较了原样保留组件与已保存简化候选，范围限于上述位置、范围及面数事实，不能替代拓扑或工程验收。可视检查工具旋转原型局部包围盒后的保守最大 Z 为 1072.484423 mm，紧致世界 BRep 最大 Z 为 1070.679511 mm；两种范围算法不同，不能用外框差异认定零件漂移。详细证据见 [assembly-final-placement-check.json](validation/assembly-final-placement-check.json)。

| 案例 | STEP 可读 | 源拓扑（缺陷组件数） | 导出回读拓扑 | 实例 / 原型数 | STEP 字节数 | 用途说明 |
|---|---|---|---|---:|---:|---|
| 原项目卫星装配 | 是 | 未通过（16） | 未通过 | 194 / 34 | 50,533,575 | 源与输出拓扑无效；仅供复核与修复 |
| 原项目 CATCH | 是 | 未通过（13） | 未通过 | 33 / 33 | 98,104,999 | 源与输出拓扑无效；仅供复核与修复 |
| 有效行星减速箱组件 | 是 | 通过（0） | 通过 | 1 / 1 | 17,846 | 源与输出拓扑通过；工程适用性另行确认 |
| Dawn 推进器源缺陷回归 | 是 | 未通过（1） | 未通过 | 1 / 1 | 11,584,086 | 源与输出拓扑无效；仅供复核与修复 |

完整的 `stepReadable`、`stepReadbackValid`、`sourceTopologyValid`、`invalidSourceComponentIds`、`status`、实例数、原型数与哈希保存在每个案例的 `properties.json`，机器摘要保留相同事实。源缺陷和输出缺陷并未认证为一一对应；不能仅凭“源本来无效”推断导出没有任何新增缺陷。有效输入若导出后新出现无效拓扑，回归测试要求作业失败并禁止发布产物。

两份整星最终 STEP 的独立 CAD 检查均与最终文件哈希绑定，并确认 194 与 33 个叶实例，记录见 [assembly-final-inspection.json](validation/assembly-final-inspection.json) 和 [catch-final-inspection.json](validation/catch-final-inspection.json)。检查器的 shapeCount 指标不等于实体数；本报告不将其当作实体统计。

- **原项目卫星装配**：接触候选 63 对，未确定组件 129 个。未确定配对分类：`{"pairTimeouts": 12, "checkBudgetPairs": 232, "pairLimitPairs": 0, "geometryErrorPairs": 0, "invalidSourcePairs": 16}`。成功源配对复用 206 次。最终导出验证耗时 174.6 秒，含排队，不含之前的导入和简化。产物：[案例目录](validation/artifacts/satellite-assembly-container)；早期记录：[initial-export-attempt.json](validation/artifacts/satellite-assembly-container/initial-export-attempt.json)。

- **原项目 CATCH**：接触候选 2 对，未确定组件 27 个。未确定配对分类：`{"pairTimeouts": 0, "checkBudgetPairs": 0, "pairLimitPairs": 0, "geometryErrorPairs": 0, "invalidSourcePairs": 31}`。成功源配对复用 17 次。最终导出验证耗时 260.9 秒，含排队，不含之前的导入和简化。产物：[案例目录](validation/artifacts/catch-container)；早期记录：[initial-export-attempt.json](validation/artifacts/catch-container/initial-export-attempt.json)。

- **有效行星减速箱组件**：接触候选 0 对，未确定组件 0 个。未确定配对分类：`{"pairTimeouts": 0, "checkBudgetPairs": 0, "pairLimitPairs": 0, "geometryErrorPairs": 0, "invalidSourcePairs": 0}`。成功源配对复用 0 次。最终导出验证耗时 270.6 秒，含排队，不含之前的导入和简化。产物：[案例目录](validation/artifacts/gearbox-container)；早期记录：[initial-export-attempt.json](validation/artifacts/gearbox-container/initial-export-attempt.json)。

- **Dawn 推进器源缺陷回归**：接触候选 0 对，未确定组件 1 个。未确定配对分类：`{"pairTimeouts": 0, "checkBudgetPairs": 0, "pairLimitPairs": 0, "geometryErrorPairs": 0, "invalidSourcePairs": 0}`。成功源配对复用 0 次。最终导出验证耗时 268.8 秒，含排队，不含之前的导入和简化。产物：[案例目录](validation/artifacts/thruster-container)；早期记录：[initial-export-attempt.json](validation/artifacts/thruster-container/initial-export-attempt.json)。

有效减速箱源实体有 **133 面**，最终下载 STEP 含 **1 个实体、6 个面**，包络尺寸 **180 × 180 × 187.5 mm**。最终产物的独立几何检查确认 6 面及相同尺寸，记录见 [gearbox-final-inspection.json](validation/gearbox-final-inspection.json)，并已核对检查文件的 STEP 哈希与最终下载产物一致。初次产物的独立检查另存于 [gearbox-inspection.json](validation/gearbox-inspection.json)。单组件几何检查不能代替整星装配或热接触验收。

Dawn 推进器源原型包含 1 个实体、1756 个面，但源拓扑无效；它被保留为缺陷输入回归，没有把“存在实体”或“所有面属于实体”当作“拓扑有效”。有实体与游离曲面混合的原型也会保持未确定，例如 CATCH 中已有 2 实体、430 面而 6 面不属于实体的记录。复杂相交默认每对 10 秒、每轮 300 秒预算，超时或覆盖不完整的组件保留原形、列为未知，可提高预算后重新检查。

## LLM 资料提取与对话联动

实际使用 DSH 原生模型读取真实 DOCX/XLSX，为 **13 个组件写入 26 个质量/功耗字段**。数值与 Excel 原列逐项一致，引用精确存在于原文；**20 个无法唯一匹配的组件保留未知**。材料、固定性与运动约束缺失时不编造。尺寸匹配是记录了误差和出处的推断，不能替代器件身份认证。机器证据见 [native-integration-summary.json](validation/native-integration-summary.json)。

浏览器实测原生聊天与三维并排、实体渲染、树和三维点选联动、固定引用草稿、194 组件全选的真实回执及 DSH 代理 ZIP 下载。新增导出页分别显示有效拓扑与源缺陷警告；成功下载不会被显示为工程验收通过。用户改变选区不会改变已发送引用；引用绑定会话、项目修订和服务地址。详细浏览器断言与截图记录见 [ui-smoke.json](validation/ui-smoke.json)。

最终真实截图：[完整装配的候选 GLB](validation/screenshots/assembly-candidate-workbench.png)、[工作台](validation/screenshots/workbench-final.png)、[源缺陷导出提示](validation/screenshots/export-review.png)。

194 组件整星的独立 STEP 截图尝试 2 次未完成，错误为 `CAD snapshot browser closed during Page.evaluate`。已保留工作台中最终候选 GLB 的真实截图，但它不能替代独立 STEP 截图；本报告不把该项视觉验收列为通过。

## 回归、打包和持久化

- 后端 **24 项**测试通过，数量动态取自 [backend-final-tests.log](validation/backend-final-tests.log)：实例与变换、36 mm² 脚接触、源干涉与包络误报、自动细化与失败回原、受约束移动、字段出处、分组导出、取消、超时与预算、缓存和子进程回收，以及有效输入新出现无效输出时禁止发布。
- 插件 **5 项**测试通过，数量取自 [package-install-summary.json](validation/package-install-summary.json)。最终安装包在干净目录实际安装，Host、预构建界面、独立 profile、15 个 MCP 工具、194 组件分页与源缺陷证据读取均验证成功。
- 小型接触案例完成容器 HTTP 导入、简化、导出与回读，脚接触仍为 **36 mm²**。原始验证记录独立保留，没有将其拓扑结果套用到四个真实案例。
- 正式容器冷重启后，8 个项目的版本、组件数、资料数与已有导出 STEP 哈希逐项不变，包含上述四个案例的最终产物。工作台与 DSH 文件代理已重新检查可用。已停止独立 DSH 实例与正式 Compose 服务，再通过 Windows PowerShell 5.1 的桌面启动脚本成功启动；路径处理修正也已在停止状态复验。证据见 [container-persistence-production.json](validation/container-persistence-production.json)。

最终插件包：`dist/lbk-dsh-satellite-geometry-0.1.0.tgz`，261,441 字节，SHA256：`d02dcba9fc3e8c2dccc0466b66cce320dc51660af1ab45e26c8abd7ac8abdc61`。报告生成前重新核对了包字节数和哈希与安装证据一致。

## 仍需明确的限制

首版以保守包络、多盒与有限分层细化为主；接触密集、开放曲面、源拓扑缺陷或计算未确定的组件可能完整保留，不能承诺大幅简化率。已有受约束位姿候选验证，尚无通用全局布局优化器。导出不自动修复源拓扑。接触表是几何候选，不是热导通认证；电缆、孔位配合、安装顺序、完整壳体包含性、网格和求解不在验收范围。扫描 PDF 需先 OCR。Docker 实测为当前 Linux x86-64 环境，其他架构需另行构建验证。

完整机器摘要见 [validation/final-summary.json](validation/final-summary.json)。原始模型、完整对话及开发运行数据仅留在本机，不进入插件发布包。
