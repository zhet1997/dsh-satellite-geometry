# 热设计工作台业务接口（0.3.0）

此文档供外部流程测试和 gate 使用。插件提供可重建方案、确定的版本绑定和几何证据；测试调度、评分和 Skill 升级由外部系统负责。协议版本为 `apiVersion: 2`，完整请求结构可在计算服务 `/openapi.json` 或 `/docs` 查看。

## 连接、身份与版本

本机计算服务为 `http://127.0.0.1:8787`，DSH 工作台为 `http://127.0.0.1:3081/satellite-geometry/`。浏览器经 DSH 的 `/api/cad` 代理访问相同业务接口。外部客户端可直接访问计算服务；配置 `SATCAD_TOKEN` 时发送 `Authorization: Bearer ...`。

每个 STEP 在独立工程中导入，导入后源文件不可覆盖。组件使用稳定 `id`，中文名称只影响展示，`sourceName`、`sourceTree` 和 `sourceNodeIds` 保留来源。所有写操作带当前 `revision`，旧版本返回 409；同一工程只运行一个 CAD 作业。不要在提交之后猜测修订号，应等待作业结束再读取工程。

身份提交包含 `componentId`、`displayName`、`engineeringGroup`、`nameStatus`、`basis`、`sources`。`nameStatus` 为 `identified`（可靠匹配）、`candidate`（候选待核实）、`unidentified`（无可靠身份），省略默认 `candidate`。API 保存状态与原文，不替代语义审核；配套表行序或源代号顺序不足以证明匹配。`/evidence` 包含身份状态及依据，供外部 gate 核对。

几何坐标为局部 Z-up 毫米；`pose` 将其转换到装配世界坐标。GLB 为 Y-up 米，变换 `[x,z,-y]/1000`，不得重复转换。圆柱的 `centerMm` 是中心而非底点。

## 界面操作与业务入口

下表中的 `{p}`、`{c}`、`{s}`、`{v}`、`{copy}` 分别是工程、组件、会话、Skill 版本和副本 ID。

| 界面动作 | 业务接口 |
|---|---|
| 新建工程 / 工程列表 | `POST /api/projects` / `GET /api/projects` |
| 导入 STEP / 配套文件 | `POST /api/projects/{p}/import` / `POST /api/projects/{p}/documents`，multipart 字段 `file` |
| 读取资料 / 原文件 | `GET /api/projects/{p}/documents/{id}` / 在同一路径加 `/file` |
| 重新读取 / Agent 选择恢复方法 | `POST /api/projects/{p}/documents/{id}/recover` |
| 一次性自动恢复领取 / 入队回执 | `POST /api/projects/{p}/documents/recovery-request` |
| 工程与单机上下文 | `GET /api/projects/{p}/context` |
| 中文名称与工程分类 | `POST /api/projects/{p}/identities` |
| 查看当前建模方案 | `GET /api/projects/{p}/recipes` |
| 应用并重建 | `POST /api/projects/{p}/recipes/rebuild` |
| 保存当前方案副本 | `POST /api/projects/{p}/components/{c}/recipe-copies` |
| 载入方案副本 | `POST /api/projects/{p}/components/{c}/recipe-copies/{copy}/load` |
| 读取 / 编辑热接触 | `GET` / `POST /api/projects/{p}/thermal-contacts` |
| 干涉与贴面检查 | `POST /api/projects/{p}/check` |
| 导出模型与清单 | `POST /api/projects/{p}/export`；文件地址取工程 `artifacts` |
| 作业状态 / 取消 | `GET /api/jobs/{id}` / `POST /api/jobs/{id}/cancel` |
| Skill 列表 / 查看 / 导入候选 | `GET /api/skills`、`GET /api/skills/{v}`、`POST /api/skills` |
| 固定一个流程会话的版本 | `POST /api/projects/{p}/workflow-bindings` |
| 读取结果、参数缺失与操作证据 | `GET /api/projects/{p}/evidence` |
| 意见记录 / 关联对话摘要 | `GET` / `POST /api/projects/{p}/feedback`、`GET /api/projects/{p}/session-records` |

相机、隔离、线框和左右视角同步属于显示状态；无需操作这些按钮即可测试建模和接触流程。外部系统可直接取得 GLB、区域世界坐标和面网格，自行渲染。显示状态不会改动几何或作业修订。

## 不经过界面的确定性流程

### 资料读取与恢复（0.3.1）

资料上传返回 `{document, revision, duplicate?}`。文件格式无法解析仍返回 HTTP 200，并登记原文件和真实状态：`extracted`、`needs_recovery`、`needs_ocr`、`empty` 或最终 `unreadable`。文件超过上传限制、格式不受支持、工程忙或服务故障仍按实际 HTTP 状态返回 JSON；不能把保存失败当成解析失败。相同 SHA-256 的上传直接返回既有资料，不重复增加修订或自动恢复次数。

读取接口返回 `text`、`sections`、`sha256`、`fileUrl`、`extractionMethod`、`warnings`、`diagnostics.attempts`、`diagnostics.availableRecoveryMethods` 和 `recovery`。`xlsx_empty_fill_compat` 只补齐内存副本的空填充项，保留数值、日期格式和公式缓存。XML恢复带单元格/行引用，但不推断格式、日期、单位或无缓存公式的结果。

恢复请求：`{revision, method, reason, sessionId?}`。方法为 `retry`、`xlsx_xml`（仅 XLSX）、`docx_xml`（仅 DOCX）和 `mark_unreadable`。后一项必须有原因。Agent使用领取任务时的 `sessionId`，最多执行两次恢复尝试；人工“重新读取”不需要会话。服务不接受自由编写的替代原文。实际内容或终态更新增加工程修订并使旧导出失效，原始字节不变。读取成功的资料不会被重复恢复降级。

自动请求接口接收 `{sessionId, requestId, documentIds, action, message?}`。`action` 为 `claim`、`submitted` 或 `dispatch_failed`。会话须已绑定此工程，且当前没有几何作业。`claim`原子地登记每个资料唯一的自动尝试；其他页面或刷新后领取返回空列表。随后使用同一请求ID向 DSH `session/prompt` 排队，并提交回执。队列结果不确定时不会自动重发，资料保留供复核。领取和回执仅更新恢复元数据，不增加工程修订。当前状态与请求ID均可通过资料读取接口核对。

工作台会继续导入其他资料和 STEP；几何作业结束、当前 DSH 会话就绪后触发恢复。缺少OCR、密码或可用正文时仍如实记录未读取，不认证参数完整性。

1. 创建工程，上传 STEP，等待 import 作业 `completed`；随后上传配套资料。
2. `GET /api/skills` 选择版本，用独立 `sessionId` 固定 Skill；可由外部执行器读取该版本正文后组织操作。
3. 根据实际文件和局部尺寸提交身份、属性、建模方案，逐次等候作业完成。
4. 保存命名副本；修改方案；通过 load 接口重建副本，比较当前 `recipeFingerprint` 和保存时的指纹。
5. 检查、整理双方安装区域及接触证据，导出，再读取 `/evidence` 与导出清单。
6. 外部评分使用实际测量、完整性、未知项和文件回读证据；不能把任务 `completed` 等价为热工程通过。

异步操作返回 `jobId`。完成条件为作业状态 `completed`；`failed`、`cancelled` 均不提交候选到当前工程。检查本身可能“任务完成、配对部分未知”，需另看 `sourceComplete`、`envelopeComplete`、`unknownPairCounts`、`contactDiscovery`。

下面是重建“圆柱＋底座”的请求主体；外部测试应从真实工程取得 `{p}`、组件 ID 和当前修订，尺寸也应明确来自测试规约或工程资料。

```json
{
  "revision": 3,
  "changes": [{
    "componentId": "N00003",
    "reason": "工程师要求圆柱主体加矩形底座",
    "recipe": {
      "schemaVersion": 1,
      "representation": "solid",
      "parts": [
        {"id":"base","name":"矩形底座","kind":"box","centerMm":[0,0,1],"sizeMm":[10,10,2]},
        {"id":"body","name":"圆柱主体","kind":"cylinder","centerMm":[0,0,5],"radiusMm":3,"heightMm":6,"axis":[0,0,1]}
      ],
      "regions": [{"id":"mount","name":"底部安装面","partId":"base","selector":"zmin"}],
      "thermal": {"massKg":null,"material":null,"powerW":null},
      "dimensionBasis": "本合成测试指定的局部尺寸；非真实卫星参数",
      "notes": ""
    }
  }],
  "context": {"sessionId":"external-run-001","skillFingerprint":"实际绑定指纹","feedback":"本次工程师意见"}
}
```

`representation` 可为 `source`、`solid` 或 `surface_shell`。面壳输出面集合，不含实体，厚度和热参数另存在 `thermal`。源表示须为单一 `source` 组成。各组成可为盒体、圆柱或源几何；非源组合融合后再提取外边界。区域选择器为 `xmin/xmax/ymin/ymax/zmin/zmax/lateral/all`，必须映射到最终实际保留的输出面。内部面拒绝作为安装区域；部分被覆盖的面使用剩余外露区域，清单给出 `selectedAreaMm2` 与 `exposedAreaMm2`。

所有物理量缺失使用 null；尤其不能用包络体积推质量、热容或导热。`sources` 提供资料 `documentId/quote/field/reference`，quote 必须出现在提取原文中。服务验证引用存在性，身份匹配和物理解释仍需工程师复核。

副本只保存结构化方案、源哈希和名称，与原始几何共用来源。`engineeringAccepted:false` 表示“保存不等于工程认证”。载入副本是一次重建，不包含接触自动认证或完整历史回滚。

## 热接触与检查证据

接触记录包括 `a/b.componentId`、`a/b.regionId`、面积、导通或 null、证据和状态。`candidate` 是候选，`confirmed` 为有明确双方区域的人工/资料确认，`needs_review` 为待复核，`excluded` 为排除。纯几何 origin 不允许直接 confirmed；资料 origin 需要原文引用。

几何检查在源 BRep 上测量接触。平面接触区域可显示 patches；曲面、配对/时间预算及求交失败明确标为 partial。`contactDiscovery.sourceGeometryComplete` 与 `incompletePatchContacts` 区分几何配对和可视区域映射的完整性。源存在真实干涉、简化新增重叠和未确定对分别保留。

修改关联几何或位姿后，接触决策变为 needs_review。此时旧面积和导通是历史待复核值，不能作为当前已确认数据。安装面映射随当前方案重建。面壳没有实体体积，检查结果会标 `volumeInterferenceApplicable:false`，不得把零体积解释为没有穿透。

## 实际调用 DSH 模型进行流程测试

仅调用计算服务不包含 LLM 执行。要测试更换 Skill 后的真实 Agent 行为，外部框架还应创建独立 DSH 会话，绑定版本并发送任务。DSH 0.2.0-rc.2 使用经过浏览器登录认证的 RPC 请求；不要把启动令牌写进测试报告或模型消息。

公共 RPC 包络：

```json
{"type":"client-request","rpcId":"独立请求编号","method":"session/create","payload":{"args":{"request":{"sessionId":"独立会话编号","cwd":"实际工作区绝对路径"}}}}}
```

将它 POST 到 DSH `/api/session/create`。重命名为 `/api/session/rename`，原生发起任务为 `/api/session/prompt`；后者 `payload.args.request` 含 `requestId`（另一个唯一 UUID）、`sessionId`、`mode:"queue"`、`content:[{"type":"text","text":"任务"}]` 和 `clientTimeZone`。一键建模使用同一接口。

插件 RPC `/api/satellite-geometry/workflow.bind` 使用 `method:"satellite-geometry/workflow.bind"`，payload 为 `{sessionId,projectId,skillId,selection:[]}`，此插件自定义入口不包 `args.request`。`workflow.select` 更新工程与当前选区，未固定版本的会话只暂存选区；`selection.snapshot` 创建持久 SG 引用，供模型的 `satellite_selection_context` 读取。外部框架可直接把 SG 引用写入原生任务，无须鼠标操作。

实际模型必须成功调用 `satellite_workflow_context`，取得冻结的 Skill 正文、资源、指纹和真实工程上下文。插件在写工具前检查此读取以及工程一致性。单纯填写或回显一个指纹不能证明使用了指定规则。用于评估的原生对话可通过 `session/projections` 取得 `asOfSeq`，再 `session/page` 读取：`{address:{kind:"session",sessionId},throughSeq:asOfSeq,maxMessages:...}`，同样放入 `args.request`。工具结果 `message.isError`、实际返回的 Skill 内容、工程反馈和测量共同作为证据。

## Skill 版本与经验收集

`POST /api/skills` 接收 `{label,content,resources:{"relative/file.md":"文本"}}`，返回不可变 ID 和指纹。正文与附属资源均参与指纹；同内容重复导入复用已有版本。资源只接受安全的相对文本路径。

会话固定正文及资源后不允许替换版本或计算服务。不同测试版本使用不同会话；同会话可以明确切换工程、继续修改选区。版本绑定不增加几何修订。`boundAt` 为绑定，`loadedAt` 为实际上下文工具读取标记；仍应核查工具是否成功返回。

工程师意见、建模变更及关联消息保留在 feedback/session-records，`autoSkillUpdate:false`。完整原生对话继续由 DSH 保存。记录只有收集用途，本插件不实时提炼 Skill、不内置 gate 打分或批量测试调度。

导出 ZIP 包含 `simplified.step`、`simplified.glb`、`properties.json`、`recipes.json`、`contacts.json` 和 `feedback.json`。外部系统应同时保存软件版本、Skill 指纹、源文件哈希、组件映射和导出修订，以便重放与比较。
