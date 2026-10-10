---
name: satellite-thermal-modeling
description: 根据配套资料和工程师经验修正单机热分析几何、面壳和接触关系。
---

先调用 satellite_workflow_context 读取当前会话固定的工程、Skill 内容与指纹；SG 引用用 satellite_selection_context 解析。写前读取当前 revision，等待所有异步任务完成并复读结果。

## 工程识别

读取工程资料列表及必要原文，按稳定组件 ID 匹配。优先从配套表取得中文名称；有可靠依据才提交中文名称和分类，不知道则保持“待识别”。保留原 STEP 树与源代号。身份依据和热参数依据分别记录。

identify_equipment 的 nameStatus 必须按证据显式选择：可靠匹配为 identified，有候选但冲突未解为 candidate，无依据为 unidentified（省略时默认 candidate）。配套表行序、P 编号顺序或另一工程的旧映射不能证明身份；逐组件核对当前 ID、源名、三轴尺寸、重复型号和资料，尺寸矛盾不能用臆测消除。候选名称不能用于自动搬运该产品的质量、功耗或材料。Envelope 等整星外形/参考体不可硬套为某个单机；保留源几何并注明角色待核实，不能未经工程师确认就删除。

## 建模方案

使用 satellite_read_recipes / satellite_rebuild_recipes，方案组成允许 box、cylinder、source。坐标为源局部 Z-up 毫米，centerMm 表示几何中心，圆柱 axis 表示轴向。默认保持原装配位姿。常见纠正：陀螺仪用圆柱加矩形底座；电子设备壳体用 surface_shell 表示。先读取源 localBoundsMm、原位姿和配套尺寸再选择参数。

面壳是面集合，输出不含实体；thicknessMm、material、massKg、specificHeatJPerKgK、conductivityWPerMK、powerW 单独存在 thermal 中。没有物理数据时填 null，禁止从包络体积推算质量和热容。dimensionBasis 与 reason 明确尺寸/判断依据，资料引用须精确匹配原文。

修改当前方案直接执行，不增加逐步接受流程。用户要求保留时使用 satellite_save_recipe_copy 命名副本，需要恢复时使用 satellite_load_recipe_copy。工程师意见通过 context.feedback、sessionId、selectionRef 关联记录。只记录意见，不修改当前 Skill、不在线提炼规则。

## 安装与接触

regions 定义 partId 和 xmin/xmax/ymin/ymax/zmin/zmax/lateral/all 区域。优先保留原安装尺寸。几何接触候选只是证据，不能认证热连接；利用 satellite_read_contacts 和 satellite_update_contacts 整理双方区域、面积、确认/待复核状态及证据。导通未知保留 null。修改单机后相关接触会变成 needs_review，复核后再更新，不能自动宣称通过。

真实干涉与简化新增重叠分别检查。后者优先细化/拆分方案，无法解决则列入问题。真实组件移动仅在用户要求优化布局或真实安装问题且充分约束存在时使用既有受约束位姿工具，不能借移动消除粗包络重叠。

## 完成与导出

使用卫星检查工具，区分 completed、unknown、needs_review。大型整星检查可能达到时间预算，完整性不足如实说明。导出简化 STEP、方案/属性和热接触清单。确认任务实际完成，复读组件 representation、outputGeometry、接触映射和下载地址后再报告。文件可读不等同于热工程验收。

同一工程的写操作顺序执行，每次取得新 revision 后再进行下一次写入。read_job 不会阻塞到任务结束，避免密集重复调用；不得用 DSH 自己的后台任务工具查询几何服务 jobId。优先使用插件提供的资料和业务工具，不读开发源码或历史验收文件来猜接口。导出失败时如实记录原因，不为绕过检查而改变有效性标记、恢复无关组件或无依据地替换几何。

外部系统通过相同 API 独立创建工程/会话、指定 Skill 并取得结构化证据；评分和批量测试由外部负责。
