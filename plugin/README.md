# 卫星几何 DSH 插件

为 DSH 0.1.1-rc.2 提供真实 MCP 工具、资料抽取 Skill、服务地址设置、连接检查以及宽屏几何工作台。工作台左侧直接加载原生 DSH，右侧加载独立三维界面；聊天、模型配置和审批全部保留。分栏可以拖动，不受 DSH 原详情栏 520px 上限影响。

先构建仓库 `web/`，再在本目录运行 `npm install`、`npm run build`。默认独立几何服务为 `http://127.0.0.1:8787`。

安装到测试 profile（使用已配置模型的同一个 DSH_HOME；不要覆盖正在运行的配置）：

```powershell
npm run install:profile
dsh.cmd --profile satellite-geometry --port 3081 --no-open
```

安装脚本创建独立的 satellite-geometry profile，仅包含官方 base、web 和本插件；复用同一个 DSH_HOME 的全局模型配置，不复制或输出模型密钥，不修改现有 web profile。直接用文件路径 overlay 可以加载 Host 代码，但该版本不会把它识别成带浏览器界面的包，因此必须通过具名包/profile 安装。

在另一台 Windows 机器安装 `.tgz` 发布包时，先安装 Node.js 24 LTS，并准备已配置模型的 DSH 0.1.1-rc.2。需要安装 DSH 时运行 `npm install -g @deepseek-ai/dsh@0.1.1-rc.2`，随后在 DSH 自己的设置中配置模型。几何服务需要独立启动，或准备好可访问的远程服务地址。

下面在一个长期保留的目录中安装发布包；请把 `$satcadPackage` 改为实际下载位置。发布包包含预构建界面和运行时依赖清单，无需下载本仓库、Python、前端构建工具或运行 `npm run build`。

```powershell
$satcadPackage = 'D:\Downloads\lbk-dsh-satellite-geometry-0.1.0.tgz'
New-Item -ItemType Directory -Path 'D:\DSHPlugins\satellite-geometry' -Force | Out-Null
Set-Location 'D:\DSHPlugins\satellite-geometry'
npm init -y
npm install --omit=dev $satcadPackage
node .\node_modules\@lbk\dsh-satellite-geometry\install-profile.mjs
dsh.cmd --profile satellite-geometry --port 3081 --no-open
```

打开 `http://127.0.0.1:3081/satellite-geometry/`，在“设置 → 插件 → 卫星几何工作台”配置几何服务地址。安装目录不能在安装后删除或移动，因为 profile 链接到这里的插件。若端口 3081 已占用，启动时选一个空闲端口并相应修改浏览器地址。同名 profile 若已指向另一安装位置，脚本会拒绝覆盖；应在原目录升级并重新启动该 profile。

不要对解压后的发布包直接运行 `npm ci`：`.tgz` 不包含本仓库开发用的锁文件。上面的 `npm install` 会在安装目录生成自己的 `package-lock.json`；以后在这个目录恢复同一依赖版本时，可以运行 `npm ci --omit=dev`，并保留该锁文件引用的原 `.tgz`。Linux/macOS 使用相同的 npm 安装流程和 `node node_modules/@lbk/dsh-satellite-geometry/install-profile.mjs`，把目录换为本机路径，最后使用 `dsh` 代替 `dsh.cmd`。

打开新 DSH 实例的 `/satellite-geometry/`。左侧选择工作区/会话，右侧上传 STEP 与资料；选中组件后点击“带入聊天”，草稿只显示组件名和简短几何引用，用户编辑后发送。后台在 DSH_HOME/satellite-geometry/selection-contexts 保存该条消息的固定选择快照，模型通过原生工具 satellite_selection_context 读取精确项目、版本与组件 ID。引用绑定原会话和几何服务地址，重启后保留；后续选择不会覆盖它。未选会话时上下文暂存在工作台，不自动发送。

一次可以带入最多 2,000 个组件，草稿只展示前四个名称及总数；模型每次读取最多 100 个引用项，并通过 `nextOffset` 继续读取。界面收到原生聊天的实际回执后才显示带入成功；空选择、超出上限或保存失败会明确提示。若要让 DSH 阅读整个项目的配套资料，请在左侧消息里明确项目名称，或先从几何视图选择组件并带入聊天。

“设置 → 插件 → 卫星几何工作台”可以更改地址、保存访问令牌并检查连接。令牌由 DSH credentials 服务保存，仅用于 Host 代理和 MCP 请求，不返回浏览器、不放入模型上下文。也支持启动环境的 SATCAD_SERVICE_TOKEN。MCP 由插件自动启动 `mcp/server.mjs`，stdio 桥接到几何 HTTP 服务；将来改为远程服务地址时，工具协议和用户界面无需更换。远端使用 HTTPS 或受控通道；本机默认服务可不设令牌。

已运行在 3081 端口的插件也可用下列 PowerShell 命令切换到本机 8787 服务，无需重启 DSH。它只修改服务地址并重连 MCP；省略 `token` 和 `clearToken` 会保留已有访问凭据，命令不会读取或输出模型密钥。应在当前几何任务和模型工具调用结束后切换；旧几何引用绑定原地址，切换后需重新带入选择。

```powershell
$satcadRequest = @{
    type = 'client-request'
    rpcId = [guid]::NewGuid().ToString()
    method = 'configure'
    payload = @{ serviceUrl = 'http://127.0.0.1:8787' }
} | ConvertTo-Json -Depth 5
$satcadResponse = Invoke-RestMethod -Method Post `
    -Uri 'http://127.0.0.1:3081/satellite-geometry-rpc/configure' `
    -ContentType 'application/json' -Body $satcadRequest
if (-not $satcadResponse.result.ok) { throw $satcadResponse.result.error.message }
$satcadResponse.result.value
```

成功响应包含 `serviceUrl: http://127.0.0.1:8787` 和 `connected: true`，说明地址已保存、MCP 桥接已重新连接；几何服务是否可达还需通过插件里的“检查连接”确认。

发布包包含构建后的 viewer 静态文件。开发时如果尚未复制，Host 也会读取相邻 `web/dist`。MCP 只传控制与结构化结果，STEP/GLB 从 `/api/cad` 文件代理传输。

“资料与导出”页分别显示 STEP 是否可读取、回读拓扑是否有效，以及源模型是否已有拓扑缺陷。可读取但拓扑无效的产物用于复核与修复，页面会保留源缺陷组件数和导出说明。拓扑检查通过以后，热、装配、接触与约束等工程检查仍按各自结果判断。

插件自己的测试 `npm test` 验证 MCP 实际 stdio 握手、工具发现、HTTP 调用、按组件读取、错误传播，以及选择引用的持久化、不变性与会话隔离，不会调用推理模型。`tests/native-*.mjs` 是显式集成验收脚本，会调用已配置模型；仅在测试数据和目标项目核对后运行，不属于安装流程。紧凑验收结果位于仓库 `validation/native-integration-summary.json`；完整对话仅在本地 `validation/raw/` 保留，不打入插件包。

模型提交资料属性时，MCP 默认使用 `origin:document`，服务逐字段校验来源并保存 provenance。人工明确赋值使用 `origin:manual`；未提供属性保持未知。对于较大的模型，`satellite_read_project` 支持 `componentIds`，可以分批读取和核验，避免整项目结果过长。尺寸唯一匹配属于有记录的推断，不能替代工程身份确认。
