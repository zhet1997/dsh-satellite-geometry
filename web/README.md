# 卫星几何工作台

独立 React + Three.js 界面，由 DSH 插件同源加载，也可由几何服务提供静态页面。业务数据均来自真实几何服务，页面没有内置假聊天或演示结果。

## 本地构建

```powershell
cd D:\AgentPrj\my_new_computer\work\dsh-satellite-geometry\web
npm ci
npm run build
```

产物：`web/dist/index.html` 与 `web/dist/assets/*`。资源路径采用相对路径，可部署在 `/satellite-geometry/viewer/`。

开发：`npm run dev`，地址 `http://127.0.0.1:5177`。Vite 将 `/api` 转发到 `http://127.0.0.1:8787/api`，将 DSH 兼容路径 `/api/cad` 转发到 `/api`。

## API 与宿主边界

- DSH `/satellite-geometry/*` 页面默认接口 `/api/cad`；独立计算服务页面默认 `/api`。
- 可用查询参数 `apiBase`、`projectId` 覆盖初始连接和项目。API Base 必须指向 API 根，例如 `http://127.0.0.1:8787/api`，不能含访问凭据。
- 全部 HTTP 访问集中在 `src/api.ts`，每个 API client 有独立 base，不共享全局项目上下文。
- 更新几何、属性、语义分组时发送期望修订号；服务返回 409 后重新读取项目，要求用户基于当前修订重试。
- GLB 为标准 Y-up 米，几何服务输出组件 `extras.componentId`。显示端使用模型变换，不再次转换源 CAD 坐标。API 中尺寸、位置为 Z-up 毫米。
- 原几何、简化几何各有真实 Three.js 场景，支持点选、Ctrl/Shift 多选、隐藏、聚焦、等轴/俯视和线框。

## iframe 消息

所有消息只接受直接父窗口，origin 必须等于 document.referrer 的 origin。无 referrer 时使用当前 origin。

工作台发给父窗口：

```ts
{ type: 'satellite-geometry:ready' }
{ type: 'satellite-geometry:selection', projectId, revision,
  selection: [{ nodeId, name }], purpose }
{ type: 'satellite-geometry:ask-selection', projectId, revision,
  selection: [{ nodeId, name }], purpose, prompt }
{ type: 'satellite-geometry:project-updated', projectId }
```

`ask-selection` 只在用户点击“带入 DSH 聊天”时发出，父插件将建议文字写入 DSH 原生输入框，不自动发送。

父窗口发给工作台：

```ts
{ type: 'satellite-geometry:context', projectId?, revision?, apiBase?, theme? }
{ type: 'satellite-geometry:selection-result', ok: boolean, message: string }
```

项目切换/修订变化触发重新读取服务端状态。theme 字段保留协议兼容，当前工作台使用自身的浅色工程配色。

带入聊天时先显示等待状态，只有收到 `selection-result` 的成功回执后才显示成功。失败或 30 秒未收到回执会显示明确错误，不乐观宣称成功。

## 功能与验证范围

页面包含项目创建/切换、STEP 与文档上传、文字提取状态和预览、装配树、组件重命名/语义分组/解除分组、原始/简化对比、按用途简化、局部返工、保留原实体及位姿、组件属性与人工约束、检查问题定位、任务进度与取消、STEP/GLB/报告/热接触清单/ZIP 下载。

默认保持装配位姿并保留接触组件的原始几何；热分析用途始终开启接触保护。装配检查使用多层包络、空间包络使用单层包络，用户可在非热用途显式关闭接触原形保护，让相连组件参与简化后再检查；不确定和热关键组件仍由计算服务保留。检查页分别显示装配几何、热接触保留的工程状态，未完成、错误或不确定的检查不会显示为通过。任务成功、文件导出成功、工程检查通过是独立状态。扫描 PDF 无文字时显示“需要 OCR”，不声称已完成内容理解。

`npm run build` 已验证 TypeScript 和产物构建。真实浏览器与几何案例的最终验证由集成任务执行，工作台子任务未声称已通过浏览器验证。
