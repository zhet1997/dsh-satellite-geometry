# Agent Web → DSH 插件开发交接

远端路径复核：**2026-10-07**；本机 0.3.0 开发与验收更新：**2026-10-10**。用途：接手本机卫星几何插件，或将原 Agent Web 的其他模块拆成可安装的 DSH 插件。远端路径、哈希与案例说明仍对应 10 月 7 日的只读观察；本轮没有再次修改或验证远端应用。

本机工程于 2026-10-07 迁到 **`D:\Codes\dsh-satellite-geometry`**。完整迁移记录见 [MIGRATION.md](MIGRATION.md)。本轮需求见 [requirements-20261009.md](docs/requirements-20261009.md)，业务接口见 [workbench-api.md](docs/workbench-api.md)，测试结论见 [VALIDATION-0.3.md](docs/VALIDATION-0.3.md)。

## 1. 接手时先知道这几件事

1. 用户所称的原始 `web_agent` 项目，实际代码目录是 5090 服务器上的 **`/data/lbk/codex_web/agent-web`**。`/data/lbk/codex_web` 是外围工作区，包含原项目、数据、DSH 定制仓库与其他服务。
2. 本机独立提取项目是 **`D:\Codes\dsh-satellite-geometry`**。它运行时不需要启动整个远端 Agent Web。
3. 本机网页版 DSH 是 **Windows npm 安装的 `@deepseek-ai/dsh@0.2.0-rc.2`**；卫星插件与计算服务均为 **0.3.0**。宿主与插件/计算服务版本号指不同层。
4. 3080 是普通 DSH web profile，3081 是卫星专用 profile，8787 是 Docker 几何服务。DSH Windows 桌面应用另有内置运行时，不能把网页版兼容验证等同于桌面版验证。
5. 原服务器上现在已有 **`/data/lbk/codex_web/deepseek-harness/packages/custom`**，含设计数据、设计结果、版本管理等 DSH 定制实现。迁移其他模块前，应先检查这里是否已有可复用实现，避免重复提取。
6. 原始卫星 STEP 有 **3 份**：立方星、CATCH、天空智算实验星。前两份已复制到本机并验证；第三份只核对了远端原文件、配套资料与哈希，尚未在本插件中验收。
7. 本机 Git 保留原始提取历史，后续提交包含 0.2 适配和本次目录迁移。远端 Agent Web 在复核时仍有大量未提交开发。**提取远端其他模块时，只复制远端 Git HEAD 可能遗漏当前实现；本机旧源码 ZIP 也不含 0.2 适配。** 原始算例、安装包和运行数据随目录保留，但不纳入 Git。

## 2. 环境与路径总表

### 2.1 本机源码、宿主与入口

| 对象 | 完整路径或地址 | 用途 |
|---|---|---|
| 独立插件项目根目录 | `D:\Codes\dsh-satellite-geometry` | 后续插件拆分的本机参考实现 |
| 同一目录的 WSL 路径 | `/mnt/d/Codes/dsh-satellite-geometry` | Windows/WSL 共用文件，并非第二份 checkout |
| Windows DSH CLI | `C:\Users\49076\AppData\Roaming\npm\dsh.cmd` | 终端启动命令 |
| Windows DSH npm 包 | `C:\Users\49076\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh` | 实际宿主；其 `node_modules/@deepseek-ai` 可核对当前 API |
| DSH 数据根目录 | `C:\Users\49076\.dsh` | profile、会话、存储和插件配置；可由 DSH_HOME 覆盖 |
| 普通 web profile | `C:\Users\49076\.dsh\profiles\web` | 3080，另有研究、Skills 管理、桥接等插件 |
| 卫星专用 profile | `C:\Users\49076\.dsh\profiles\satellite-geometry` | 3081，只组合官方 base/web 与卫星插件 |
| 专用 profile 的插件链接 | `C:\Users\49076\.dsh\profiles\satellite-geometry\node_modules\@lbk\dsh-satellite-geometry` | 已核实指向本机项目的 `plugin` 目录 |
| 普通网页版 | `http://127.0.0.1:3080/` | 从桌面“DSH 网页版”进入 |
| 卫星工作台 | `http://127.0.0.1:3081/satellite-geometry/` | 原生 DSH 对话与三维界面并排 |
| 几何 API | `http://127.0.0.1:8787/api` | 本机 Docker 服务，不是 DSH 页面 |
| 几何健康检查 | `http://127.0.0.1:8787/api/health` | 可直接只读检查 |
| DSH 的文件/API 代理 | `http://127.0.0.1:3081/api/cad` | 需要 DSH 浏览器认证 |
| Windows 桌面应用的包 | `D:\Install\Dsh\resources\app.asar` | 与 npm 网页版不同，本次未更新该内置宿主 |
| Python 开发环境 | `/home/zhet/.venvs/dsh-satellite-geometry/bin/python`，WSL Ubuntu | Python 3.12 / CadQuery 2.8.0；生产计算在容器里 |

2026-10-02 已确认：WSL 中发现的 `dsh` 命令实际指向 Windows npm 路径，未发现另一套 WSL 全局 npm DSH。新机器仍应分别检查 Windows 和 WSL，不要根据浏览器所在系统推断服务所在系统。

### 2.2 启动器、日志和持久数据

| 对象 | 完整位置 | 说明 |
|---|---|---|
| 普通网页快捷方式 | `D:\Desktop\DSH 网页版.lnk` | 调用 `scripts/Start-DshWeb.ps1`，处理新版登录 |
| 卫星快捷方式 | `D:\Desktop\卫星几何工作台.lnk` | 调用 `scripts/Start-Workbench.ps1` |
| 普通 DSH 启动脚本 | [Start-DshWeb.ps1](/D:/Codes/dsh-satellite-geometry/scripts/Start-DshWeb.ps1) | 复用或启动 3080，读取本机登录链接 |
| 卫星启动脚本 | [Start-Workbench.ps1](/D:/Codes/dsh-satellite-geometry/scripts/Start-Workbench.ps1) | 启动/复用 WSL Docker、8787、3081，并保持 WSL 活跃 |
| 主网页版后台监控 | `C:\Users\49076\.dsh\tools\dsh-watchdog.ps1` | 已适配 DSH 登录校验；不要再用旧匿名主页检查替换 |
| 主网页版监控状态 | `C:\Users\49076\.dsh\runtime\web-status.json` | 2026-10-07 复核为 healthy |
| 主网页版监控日志 | `C:\Users\49076\.dsh\runtime\logs` | `dsh-web-*.out.log` / `*.err.log` |
| 卫星启动日志、PID | `D:\Codes\dsh-satellite-geometry\runtime` | `dsh.stdout.log`、`dsh.stderr.log`、`dsh.pid`、`wsl-keepalive.pid`；PID 不应写死 |
| 2026-10-02 升级备份 | `D:\Codes\dsh-satellite-geometry\runtime\dsh-backup-20261002` | 旧配置和监控脚本，可能含凭据；不打入发布包 |
| 几何生产容器 | `dsh-satellite-geometry-geometry-1` | 镜像 `dsh-satellite-geometry:0.3.0`；2026-10-10 已更新并核对健康入口 |
| Docker 命名卷 | `dsh-satellite-geometry_project-data` → 容器 `/data` | **正式项目状态及产物的主要持久位置** |
| DSH 会话和存储 | `C:\Users\49076\.dsh\sessions`、`C:\Users\49076\.dsh\storages` | 不在几何 Docker 卷内 |
| 固定选区引用 | `C:\Users\49076\.dsh\satellite-geometry\selection-contexts` | 绑定 DSH 会话、几何服务、projectId、revision 和组件 ID |
| 会话固定 Skill | `C:\Users\49076\.dsh\satellite-geometry\workflow-contexts` | 正文、资源、内容指纹及实际读取时间；另一版本须使用新会话 |
| 原始案例副本 | `D:\Codes\dsh-satellite-geometry\cases` | 原 STEP、DOCX、XLSX；不纳入 Git |
| 历史导出和测试产物 | `D:\Codes\dsh-satellite-geometry\validation\artifacts` | 证据快照，不保证等于当前生产修订 |

本机使用 WSL Ubuntu 内原生 Docker daemon：`/usr/bin/docker -H unix:///var/run/docker.sock`。不是依赖 Docker Desktop 界面。Compose 文件实际名为 [compose.yaml](/D:/Codes/dsh-satellite-geometry/compose.yaml)。

仓库 `data` 是历史开发数据，裸 Python 默认使用 `service/data`；二者均不能当成生产卷的自动同步副本。备份完整成果需同时考虑：源码及未提交改动、原始案例、Docker 卷、DSH 会话/存储/选区引用。`node_modules`、构建产物和缓存可重建。

### 2.3 当前安装包与基线

| 文件 | 状态 |
|---|---|
| [lbk-dsh-satellite-geometry-0.3.0.tgz](/D:/Codes/dsh-satellite-geometry/release/lbk-dsh-satellite-geometry-0.3.0.tgz) | 当前热设计工作台包；面向 DSH 0.2.0-rc.2；含预构建 UI、MCP 与固定 Skill 入口 |
| [lbk-dsh-satellite-geometry-0.2.0.tgz](/D:/Codes/dsh-satellite-geometry/dist/lbk-dsh-satellite-geometry-0.2.0.tgz) | 历史适配包；261,890 字节 |
| [dsh-satellite-geometry-0.1.0.tgz](/D:/Codes/dsh-satellite-geometry/dist/dsh-satellite-geometry-0.1.0.tgz) | 旧包；261,441 字节；当前磁盘文件名如左，历史报告使用带 `lbk-` 前缀的名称 |
| [dsh-satellite-geometry-source-0.1.0.zip](/D:/Codes/dsh-satellite-geometry/release/dsh-satellite-geometry-source-0.1.0.zip) | 旧源码发布快照，不含后来的 0.2 宿主适配 |
| 本机 Git 基线 | 初始提取提交 `6244c57f2c4836ae5e67220899bf5d11f362fe2e`；迁移后的提交包含 DSH 0.2 适配，最新状态以 `git log -1` 为准 |

0.3.0 包 SHA256 见 [VALIDATION-0.3.md](docs/VALIDATION-0.3.md)。历史 0.2.0 包 SHA256：`29ecc888781b0f6376bbfdecefd26d1554d88fc09caffee1f199226b8f1c9d6e`。

旧包 SHA256：`d02dcba9fc3e8c2dccc0466b66cce320dc51660af1ab45e26c8abd7ac8abdc61`。

包是可本地安装的标准 npm `.tgz`，没有发布到公共 npm 仓库；`package.json` 使用 `private: true`。包内包含预构建前端、Host、MCP、Skill 与安装脚本，不含 Python/CAD 计算环境、原始卫星数据和模型密钥。

## 3. 5090 服务器与原项目

### 3.1 连接方式及版本追溯

SSH 配置别名：**`work-server-5090-ali`**。本次只读连接落在用户 `xie`、家目录 `/home/xie`；目标项目主要由 `lbk` 所有。复用现有 SSH 配置，不在交接文档中复制私钥、密码或 API Key。

```powershell
ssh -o BatchMode=yes -o ClearAllForwardings=yes work-server-5090-ali
```

| 对象 | 远端完整路径 |
|---|---|
| 外围工作区 | `/data/lbk/codex_web` |
| 原 Agent Web 仓库 | `/data/lbk/codex_web/agent-web` |
| 原仓库开发说明 | `/data/lbk/codex_web/agent-web/AGENTS.md`、`/data/lbk/codex_web/agent-web/README.md` |
| 原架构概要 | `/data/lbk/codex_web/agent-web-architecture.md` |
| 后端、前端 | `/data/lbk/codex_web/agent-web/backend`、`/data/lbk/codex_web/agent-web/frontend` |
| 原专业服务 | `/data/lbk/codex_web/agent-web/services` |
| 领域 Skill 和脚本 | `/data/lbk/codex_web/agent-web/workflow_agents` |
| 模型与 CAD 数据 | `/data/lbk/codex_web/cad_data`，含 `models`、`catalog`、`objects`、`cad`、`cache` |
| 用户工作区物理目录 | `/data/lbk/codex_web/data/users` |
| 原应用 DSH 数据物理目录 | `/data/lbk/codex_web/data/dsh` |
| 上传/语音物理目录 | `/data/lbk/codex_web/agent-web/data/input_data`、`/data/lbk/codex_web/agent-web/data/voice_input` |
| 示例配置、真实配置位置 | `/data/lbk/codex_web/agent-web/config.example.json`、`/data/lbk/codex_web/agent-web/config.json` |
| 外围部署文件 | `/data/lbk/codex_web/deployment/docker-compose.yml`、`/data/lbk/codex_web/deployment/README.md` |
| 原应用启动脚本 | `/data/lbk/codex_web/agent-web/start_agent_web.sh` |
| 当前 Python 依赖基线 | `/data/lbk/codex_web/agent-web/pyproject.toml`、`/data/lbk/codex_web/agent-web/uv.lock` |
| GNC 共享资源候选 | `/data/lbk/codex_web/AIGNC` |
| 数字地球项目 | `/data/lbk/codex_web/digital_earth` |
| 拓扑相关独立目录 | `/data/lbk/codex_web/topo`，尚未在本次完成模块级分析 |

上述物理目录已检查存在；真实 `config.json` 对当前 SSH 用户不可读，因此没有复核它的实际端口、数据库连接或所有有效根目录。原 README 规定主前后端端口由配置决定，不能随意填入旧的默认端口。原 CAD 服务 README 记载同机 `8012` 和代理前缀 `/api/workspace/cad-assembly`，这属于服务约定，不是本次存活检测结果。

2026-09-29 提取时观察的原仓库 HEAD：`bd4b5062d14e7d5e426a5762897ac1ac6646418b`。2026-10-07 观察的当前 HEAD：`2b31f95f21ff0010ced4a63184e0e79a9343d3d6`（提交日期 2026-09-30），工作目录有大量未提交修改及新增文件，尤其涉及 PostgreSQL 状态、计算服务、资料流程和三维界面。

跨所有者读取 Git 状态可使用单次命令级设置，无需改变服务器全局 Git 配置：

```bash
git -c safe.directory=/data/lbk/codex_web/agent-web -C /data/lbk/codex_web/agent-web status --short
```

### 3.2 已存在的远端 DSH 定制工程

**先读 `/data/lbk/codex_web/deepseek-harness/packages/custom/README.zh.md`。** 该仓库根 `package.json` 自报 `@deepseek-ai/dsh-root@0.2.0-rc.2`，不代表其私有修改已经发布到 npm，也不等于本机官方 npm 包。

| 完整路径 | 当前 README 描述的职责 | 对后续工作的价值 |
|---|---|---|
| `/data/lbk/codex_web/deepseek-harness/packages/custom/agent-page` | DSH 原生会话嵌入定制工作台 | 布局与扩展插槽参考 |
| `/data/lbk/codex_web/deepseek-harness/packages/custom/design-data` | PostgreSQL 型号/组件库、原生 Skill 解析、候选校验与发布 | 资料抽取/组件库可能已迁移，先核对现有实现 |
| `/data/lbk/codex_web/deepseek-harness/packages/custom/design-results` | CAD、温度场、外热流、支架、安装孔及结果流程 | 复杂可视化模块的直接参考；查看器在其 `viewer` 子目录 |
| `/data/lbk/codex_web/deepseek-harness/packages/custom/workspace-versions` | 版本树、快照、分支与原生工作区 | 避免重写原应用的整套会话/版本体系 |
| `/data/lbk/codex_web/deepseek-harness/packages/custom/engineering-tools` | FreeCAD、ParaView、COMSOL、数字地球接入 | 专业软件仍需独立运行，不因装插件而自动具备 |
| `/data/lbk/codex_web/deepseek-harness/packages/custom/agent-files` | 工作区文件与配置面板 | 文件交互可复用 |
| `/data/lbk/codex_web/deepseek-harness/packages/custom/custom-support` | 会话、账户、路径范围等共享支持 | 提取时需识别实际依赖 |
| `/data/lbk/codex_web/deepseek-harness/packages/custom/agent-page-plugin-guide.zh.md` | Agent 页面插件开发指南 | 后续 UI 插槽接入文档入口 |
| `/data/lbk/codex_web/dsh-satellite-geometry-0.1.0` | 已存在的远端卫星插件副本，manifest 为 0.1.0 | 历史副本，不是本机 0.2.0 最新工作目录 |

这里只核对目录、manifest 和 README，没有运行这些定制插件的测试，也没有认定它们能直接作为独立 npm 包安装到本机。其共享包、账户网关、数据库与构建链是否可拆开，需要针对下一模块继续检查。

### 3.3 原 Agent Web 模块导航

以下均为远端完整路径。先从领域 `module.ts` 看路由/工作区/Skill 的组合，再追到独立算法和数据接口。

| 模块 | 优先阅读的入口 |
|---|---|
| STEP 导入、简化、装配 | `/data/lbk/codex_web/agent-web/services/cad-assembly/backend/cad/import_pipeline.py`、`step_components.py`、`step_occurrences.py`、`step_lightweight.py`、`placement.py`、`mount_faces.py`、`world_export.py`（后六个文件与第一个位于同目录） |
| CAD API 与持久化 | `/data/lbk/codex_web/agent-web/services/cad-assembly/backend/app/routes.py`、`/data/lbk/codex_web/agent-web/services/cad-assembly/backend/domain/assembly_service.py`、`/data/lbk/codex_web/agent-web/services/cad-assembly/backend/infrastructure/postgres_state.py` |
| 原 CAD 前后端对接 | `/data/lbk/codex_web/agent-web/backend/src/modules/thermomechanical/cadAssembly.routes.ts`、`/data/lbk/codex_web/agent-web/frontend/src/pages/workspace/cad-assembly` |
| 主三维界面 | `/data/lbk/codex_web/agent-web/frontend/src/pages/ModelViewerPage.tsx`、`/data/lbk/codex_web/agent-web/frontend/src/pages/viewer3d` |
| 支架与安装孔 | `/data/lbk/codex_web/agent-web/services/bracket-design`、`/data/lbk/codex_web/agent-web/services/cad-assembly/backend/app/bracket_design.py`、`/data/lbk/codex_web/agent-web/frontend/src/pages/viewer3d/BracketConfirmationPanel.tsx` |
| 外热流与温度 | `/data/lbk/codex_web/agent-web/backend/src/modules/thermomechanical/heatflux.routes.ts`、`temperature.routes.ts`、`computationApi.ts`（同目录）；计算移至 `/data/lbk/codex_web/agent-web/services/cad-assembly/backend/computation`，含 `heatflux.ts`、`temperature.ts`、`python` |
| 热设计输入与 CAD 生成 | `/data/lbk/codex_web/agent-web/workflow_agents/thermal_skills/cad-builder`、`extract-component-json`、`satellite-design-docx-extractor`（同级 Skill 目录） |
| NX/UG、热报告 | `/data/lbk/codex_web/agent-web/workflow_agents/thermal_skills/nx-ug-thermal`、`/data/lbk/codex_web/agent-web/workflow_agents/thermal_skills/report-agent` |
| GNC 工作流与轨迹 | `/data/lbk/codex_web/agent-web/backend/src/modules/gnc/module.ts`、同模块的 `config/managedWorkflow.ts` 和 `trajectory/trajectory.routes.ts`；`/data/lbk/codex_web/agent-web/frontend/src/pages/workspace/GncDashboardPanel.tsx`；`/data/lbk/codex_web/agent-web/workflow_agents/gnc_skills` |
| 合规/降额检查 | `/data/lbk/codex_web/agent-web/backend/src/modules/compliance/module.ts`、`/data/lbk/codex_web/agent-web/services/compliance`、`/data/lbk/codex_web/agent-web/frontend/src/pages/ComplianceCheckPanel.tsx`、`/data/lbk/codex_web/agent-web/workflow_agents/check_skills` |
| 语音 | `/data/lbk/codex_web/agent-web/backend/src/modules/speech`；外部 FunASR/CosyVoice 连接来自配置，尚未单独分析 |
| 原应用 DSH SDK 适配 | `/data/lbk/codex_web/agent-web/backend/src/adapters/dsh/DshAgentExecutor.ts`、同目录的 `DshRun.ts`、`runtimeConfig.ts`、`mcpPatch.ts` |

原应用已经调用 DSH SDK，不表示所有业务能力已是可独立安装的 DSH 插件。下一模块应复用 DSH 的会话、模型配置和工具机制，提取业务接口与 UI；不要无条件把原 Fastify 服务器、账户系统和嵌套 Agent 执行器一起复制。

当前远端 Python 环境已改为根目录 `uv.lock` 管理，README 指定 `uv sync --locked --all-packages --no-dev`。本机卫星提取服务采用自己的 `requirements.lock` 与 Dockerfile。两边的依赖安装方式不能混用。原仓库 AGENTS.md 的部分结构/测试说明早于现有重构，执行前以实际 package scripts、当前 README 和文件为准。

## 4. 三个原始卫星算例

来源模型名以各模型目录下的 `model.json` 为准。下面三份 STEP 的大小与 SHA256 均在 2026-10-07 从远端重新读取；前两份本机副本也再次核对一致。这里“原始”表示原项目留存的输入文件，不承诺它们没有拓扑或装配缺陷。

| 名称 | 原模型 ID | 原 STEP 字节数 | 本机提取/验收状态 |
|---|---|---:|---|
| 立方星 | `mdl_eeb9c173c82c39195f3d40c5` | 49,374,275 | 已复制；卫星装配案例，历史验收 194 组件 |
| CATCH | `mdl_5fda0d85a44fea7c47523185` | 96,478,666 | 已复制；历史验收 33 组件、配套资料抽取 |
| 天空智算实验星 | `mdl_1a3ded2babd91401a0c15a80` | 191,809,774 | 远端已找到；本机尚无该整星案例，未验收 |

### 4.1 立方星

远端 STEP：

```text
/data/lbk/codex_web/cad_data/models/mdl_eeb9c173c82c39195f3d40c5/template/.cad-assembly/source/original.step
```

本机：[原始 STEP](/D:/Codes/dsh-satellite-geometry/cases/satellite-assembly/original.step)。

SHA256：`6fc811ef4efe5a974c4ae0424a60298264cb5586549b6ec5689b5475311ee65d`。

配套文件：

```text
/data/lbk/codex_web/cad_data/models/mdl_eeb9c173c82c39195f3d40c5/template/00_inputs/CATCH02设计需求.docx
/data/lbk/codex_web/cad_data/models/mdl_eeb9c173c82c39195f3d40c5/template/00_inputs/CATCH整星配套表.xlsx
```

这些文件也位于本机 `cases/satellite-assembly`。**原项目的“立方星”目录配的是 CATCH 命名资料，不能据此认定每个零件与资料匹配。** 后续要继续保留字段出处、匹配依据和未知项。

### 4.2 CATCH

远端 STEP：

```text
/data/lbk/codex_web/cad_data/models/mdl_5fda0d85a44fea7c47523185/template/.cad-assembly/source/original.step
```

本机：[原始 STEP](/D:/Codes/dsh-satellite-geometry/cases/catch-original/original.step)。

SHA256：`b08287d75f974a1698a2b3c9b704aa1bdbca1a96d756b7c5c161e91b3ed06845`。

配套文件：

```text
/data/lbk/codex_web/cad_data/models/mdl_5fda0d85a44fea7c47523185/template/00_inputs/CATCH02设计需求.docx
/data/lbk/codex_web/cad_data/models/mdl_5fda0d85a44fea7c47523185/template/00_inputs/CATCH整星配套表.xlsx
```

本机对应目录：`D:\Codes\dsh-satellite-geometry\cases\catch-original`。

### 4.3 天空智算实验星

远端 STEP：

```text
/data/lbk/codex_web/cad_data/models/mdl_1a3ded2babd91401a0c15a80/template/.cad-assembly/source/original.step
```

SHA256：`26e582d3f0081cca9c141c5d39a2cacb18951cc2b705661b8830ea1cd57ed202`。

配套文件：

```text
/data/lbk/codex_web/cad_data/models/mdl_1a3ded2babd91401a0c15a80/template/00_inputs/天空智算试验卫星轨道设计需求.docx
/data/lbk/codex_web/cad_data/models/mdl_1a3ded2babd91401a0c15a80/template/00_inputs/天空智算试验卫星单机产品配套表.xlsx
```

模型名称写“实验星”，配套文件写“试验卫星”，以上均保留真实名称。未来取回时建议新建单独案例目录，复制原 STEP 和配套文件，再对照上面的哈希；本次没有下载或导入该模型。

## 5. 本机项目 ID、历史验收与当前修订

以下 projectId 属于**独立几何服务**，不是 DSH 会话 ID，也不是远端 `mdl_...` 模型库 ID。操作前读取当前项目，不能硬编码历史 revision。

| 项目 | 几何 projectId | 2026-09-29 报告修订 | 2026-10-07 只读查询修订 |
|---|---|---:|---:|
| 立方星整星装配 | `715007d362fe43fd8a7f62b536132501` | 4 | 4 |
| CATCH 卫星 | `51cf1056426043b59c23257fcf7695b6` | 5 | **7** |
| 有效行星减速箱组件 | `ea3a894c85e243edaab17500b65a0af7` | 2 | 2 |
| Dawn 推进器组件 | `827c9dd165e246c1a292fb7df2bd196f` | 2 | **3** |
| 四脚接触演示 | `7a21b084584347cdabc8fe6df873c67f` | 2 | 2 |
| 接触保留验收 | `60c5d49617a94642801511ebc002b019` | 2 | 2 |
| DSH-MCP 资料抽取验收 A | `e3146949d1fd46d1b89d6118d3cfee4f` | 1 | 1 |
| DSH-MCP 资料抽取验收 B | `4a11df37a4394074b88f32d11905272c` | 3 | 3 |

当前修订查询只证明项目存在及版本号，不重新认证当前几何。下面结论对应已保存的历史产物：

| 案例 | 历史结果 | 适合用来验证什么 |
|---|---|---|
| 立方星 194 组件 | 3 简化、191 保留，位姿未改；8 对包络假干涉经细化变为 0；43 对源相交；16 个源实例拓扑无效；装配/热检查仍 unknown | 大装配、重复实例、性能、来源问题与简化问题的区分 |
| CATCH 33 组件 | 0 简化、33 保留；13 个源组件拓扑无效；10 对源相交；导出只作复核 | 复杂/缺陷源几何保护、文档属性抽取 |
| 减速箱 | 133 面 → 6 面，有效 1 实体，180×180×187.5 mm | 快速验证正常包络生成、前后对比及有效 STEP 导出 |
| 推进器 | 1,756 面，源拓扑无效；保留原几何，复核用途导出 | 坏输入处理；不应算成成功简化案例 |
| 四脚合成夹具 | 已知接触面积 36 mm² | 接触保护和断言；不能替代真实整星验收 |

减速箱与推进器均取自立方星整装配的源原型，**不是第三、第四颗卫星**：

- [减速箱原始组件](/D:/Codes/dsh-satellite-geometry/cases/real-gearbox/original.step)：`P00008 / Compact_Planetary_Reduction_Gearbox_v6`，SHA256 `eabc4c4634b8bcdb27795900dae4c07394c891ba40a01352448945ae94b249d1`。
- [推进器原始组件](/D:/Codes/dsh-satellite-geometry/cases/real-thruster/original.step)：`P00002 / DawnAerospace_B20_Thruster_v2`，SHA256 `8e894238755a9e9db92387b1a922cc6bd50c4bdaea0d10b0fca6aac879c23ffa`。

历史导出目录位于 `D:\Codes\dsh-satellite-geometry\validation\artifacts` 下的 `satellite-assembly-container`、`catch-container`、`gearbox-container`、`thruster-container`。每个目录保留 `simplified.step`、结构化属性及相应验证证据。历史整星装配最终 STEP 为 194 实例/34 原型；194/194 实例的世界变换与实际几何位置独立核对通过。独立大型 STEP 截图工具两次失败，只有工作台 GLB 截图，不能写成独立 STEP 截图验证通过。

CATCH 原生 DSH 文档验收会话：`satellite-catch-documents-20260929`，标题“CATCH 卫星真实资料抽取验收”。DOCX ID `509a10db20e24aaf82edc90433060c79`，XLSX ID `a8170e5c4808458589f7e6ecde0de7cf`。13 个组件写入质量/功耗，共 26 个带精确原文的字段，其余 20 个组件保持未知。尺寸唯一匹配是有记录的推断，不是工程身份认证。

## 6. 当前独立插件的实现地图

下表路径均在本机；可作为下一插件的参考，不建议只复制整个目录后改包名。

| 文件/目录 | 责任 |
|---|---|
| [plugin/package.json](/D:/Codes/dsh-satellite-geometry/plugin/package.json) | npm 入口、files、DSH bundle/client 声明及宿主 peerDependencies |
| [plugin/cordis.patch.yml](/D:/Codes/dsh-satellite-geometry/plugin/cordis.patch.yml) | 注册 `satellite-geometry` entry，初始服务地址与 MCP 开关 |
| [plugin/src/index.mjs](/D:/Codes/dsh-satellite-geometry/plugin/src/index.mjs) | Host：设置、凭据、认证路由、文件代理、MCP 启停、原生选区工具 |
| [plugin/src/client.jsx](/D:/Codes/dsh-satellite-geometry/plugin/src/client.jsx) | DSH 设置标签、会话输入区、选区写入草稿 |
| [plugin/src/selection-context.mjs](/D:/Codes/dsh-satellite-geometry/plugin/src/selection-context.mjs) | 固定选区引用的保存、分页、会话与服务范围校验 |
| [plugin/mcp/server.mjs](/D:/Codes/dsh-satellite-geometry/plugin/mcp/server.mjs) | stdio MCP → 几何 HTTP；25 个工具 |
| [plugin/src/workflow-context.mjs](/D:/Codes/dsh-satellite-geometry/plugin/src/workflow-context.mjs) | 会话固定 Skill 与严格 DSH JSON 兼容；OCCT 的负零数值规范化 |
| [插件 Skill](/D:/Codes/dsh-satellite-geometry/plugin/skills/satellite-geometry/SKILL.md) | 指导模型理解业务边界、资料来源与操作顺序 |
| [plugin/public/workbench.html](/D:/Codes/dsh-satellite-geometry/plugin/public/workbench.html) | 原生对话 iframe、业务查看器 iframe、分栏、同源消息 |
| [web/src/App.tsx](/D:/Codes/dsh-satellite-geometry/web/src/App.tsx)、[Viewer.tsx](/D:/Codes/dsh-satellite-geometry/web/src/Viewer.tsx) | 独立业务界面与三维交互 |
| [service/app.py](/D:/Codes/dsh-satellite-geometry/service/app.py) | 参数校验、项目/文档/计划/几何 API |
| [service/geometry.py](/D:/Codes/dsh-satellite-geometry/service/geometry.py) | CAD 导入、原型/实例、简化、相交、接触、导出 |
| [service/workbench.py](/D:/Codes/dsh-satellite-geometry/service/workbench.py)、[modeling.py](/D:/Codes/dsh-satellite-geometry/service/modeling.py) | recipe、面壳、安装区域、副本、身份、接触、意见和外部证据接口 |
| [service/skill_versions.py](/D:/Codes/dsh-satellite-geometry/service/skill_versions.py)、[建模 Skill](/D:/Codes/dsh-satellite-geometry/service/resources/thermal-modeling/SKILL.md) | 内容寻址版本、正文/资源快照、默认规则；不实时训练或自我升级 |
| [service/tasks.py](/D:/Codes/dsh-satellite-geometry/service/tasks.py)、[worker.py](/D:/Codes/dsh-satellite-geometry/service/worker.py) | 异步原生计算隔离、进度与取消 |
| [service/storage.py](/D:/Codes/dsh-satellite-geometry/service/storage.py)、[documents.py](/D:/Codes/dsh-satellite-geometry/service/documents.py) | 独立项目存储、文档读取和来源记录 |
| [Dockerfile](/D:/Codes/dsh-satellite-geometry/Dockerfile)、[requirements.lock](/D:/Codes/dsh-satellite-geometry/requirements.lock) | 可迁移计算环境 |
| [vendor/PROVENANCE.md](/D:/Codes/dsh-satellite-geometry/vendor/PROVENANCE.md) | 原始复用代码的路径、时间与哈希 |

运行链路是：用户在 DSH 对话提出任务 → 模型调用插件工具 → stdio MCP 桥接到 Docker HTTP 服务 → 后台作业执行 → 工具查询状态/结果 → 工作台展示并下载工件。大 STEP/GLB 通过文件代理传输，不作为大段文本塞入模型上下文。

Skill 提供操作说明，MCP 提供可执行工具，npm DSH 插件负责把 UI、配置、Skill 与工具装配起来。仅有 Skill 不能替代计算服务，也不会自动生成 UI。

实际原样复用文件为 `/data/lbk/codex_web/agent-web/services/cad-assembly/backend/cad/step_occurrences.py`，本机在 `vendor/step_occurrences.py`。2026-10-07 远端哈希仍为 `9e1c8cb494e98fc57755132caebf09e0317c0283877bc343bccbee1a8a6b5548`，与提取记录相同。其他代码是独立适配实现，并非已同步原仓库全部最新能力。

## 7. 已确认的产品边界与可复用约定

- 模型连接沿用 DSH；Docker 主要提供几何和文档处理，不要求部署离线 LLM。
- 输入为 STEP 与配套文件。缺少质量、材料、功耗或约束时保留未知，字段来源和模型推断分开记录。
- 当前工作台用途为热分析，检查聚焦真实干涉、简化重叠及安装接触。输出 STEP、组件方案/属性和热接触清单；不做网格和求解。旧底层 API 保留其他用途兼容性。
- 单机方案为可重建对象：box/cylinder/source 组成、实体/面壳、原位姿、独立热属性、安装区域和证据。当前方案直接修改，仅手动副本；不建设完整撤销历史。
- 中文名称需区分可靠、候选和未知；配套表行序不足以证明匹配。面壳是零实体的面集合，禁止按包络体积推质量或热容。实际 STEP 回读不得使用写前 BRep 缓存。
- 意见与对话摘要留存供以后集中升级 Skill；默认 Skill 修改生成新内容版本，已绑定会话的正文不能替换。外部测试框架调用业务 API 与 `/evidence`，插件不内置 gate。
- 默认保留原布局。只有真实装配问题或用户明确要求优化，且有充分约束时才尝试移动。包络假干涉优先细化/拆分，不能移动真实零件掩盖问题。
- STEP 的源原型、装配树和原位姿不可变；编辑状态另存。写操作带 revision，后台长作业返回 jobId，完成前不能宣称结果已生成。
- API 的位置单位为 mm、Z-up；GLB 为 m、Y-up，映射 `[x,z,-y]/1000`。复用查看器时不能重复转换。
- 选区上下文应绑定会话、业务项目、修订和组件 ID；后续点击不应改变先前消息引用。
- 文件可读取、拓扑有效、装配检查完成、热用途合格是不同结论。超时、跳过及源缺陷必须明确表示，不能把 unknown 写成通过。
- 当前实现没有通用全局布局优化器；复杂整星保守处理后可能大部分仍保留原几何。

这些是卫星几何插件已确认的约定。下一模块的界面形态、业务范围及验收标准仍需结合用户的新目标确定。

## 8. DSH 0.2 接口适配经验

1. **设置接口变更**：旧的 `ctx.settings.register` 已移除。当前使用 schema `.volatile()`、引用 `.get()`、`ctx.settings.configure` 和 `ctx.settings.update(entryId, patch)`。
2. **设置 UI 插槽**：`settings.plugin.item` 改为 `settings.plugins.tab`；会话输入区仍使用 `conversation.input.dock` 及其标准 props。
3. **认证**：新版浏览器 API 需要签名 cookie。快捷方式通过本机启动登录链接换取 cookie；文档与发布包不记录 token。仅访问裸 URL 得到 401 不代表进程故障。
4. **RPC 路由**：0.2.0-rc.2 自定义 `connection.rpc.handle` 曾遇到宿主 `webServer` 注入错误。卫星插件使用 `ctx.connection.fetch.register` 注册 `/api/satellite-geometry/{operation}` 精确路由，继续走 DSH 的认证。
5. **客户端 RPC 参数**：channel 为 `/api`，method 为 `satellite-geometry/settings` 等；不能把 `/api/satellite-geometry` 当 channel。请求 envelope 中 method 也要一致。
6. **具名包与前端**：只按文件路径 overlay 加载 Host 不足以保证浏览器插件被发现。保留 npm 包名、DSH client 声明和 profile bundle。
7. **构建顺序**：先 `web`，再 `plugin`；`plugin/build.mjs` 将预构建查看器复制进包。只改源码未构建，会导致浏览器仍运行旧资源。
8. **跨系统路径**：Windows DSH 接收 `D:\...`，WSL DSH 接收 `/mnt/d/...`；由 DSH 服务进程解释路径。PS 5.1 下调用 `wslpath` 使用正斜杠并保留脚本 UTF-8 BOM。
9. **WSL 生命周期**：本机曾在最后一个 Linux 客户端退出后关闭 WSL，连带停止 Docker。当前启动器保留后台 WSL 会话。
10. **版本范围**：依赖和 peerDependencies 明确指向验证过的宿主版本。升级 npm DSH 不会升级 Electron 桌面内置宿主，也不证明所有其他插件兼容。

2026-10-02 已观察到普通 web profile 的研究插件 0.1.0、Skills 管理器 0.1.48 与桥接插件 2.10.6 存在兼容问题；本次没有重新测试或修复它们。卫星专用 profile 不依赖这些插件。

## 9. 开发、安装和验证入口

### 9.1 日常启动与只读检查

```powershell
Set-Location 'D:\Codes\dsh-satellite-geometry'
& .\scripts\Start-Workbench.ps1
dsh.cmd --version
Invoke-RestMethod 'http://127.0.0.1:8787/api/health'
```

Docker 状态查询：

```powershell
wsl -d Ubuntu -u root --exec /usr/bin/docker -H unix:///var/run/docker.sock ps -a --filter name=satellite
```

### 9.2 构建和本地安装包

以下是开发操作，不是阅读交接文档时必须执行的步骤：

```powershell
Set-Location 'D:\Codes\dsh-satellite-geometry\web'
npm ci
npm run build
Set-Location '..\plugin'
npm ci
npm test
npm run build
npm pack --pack-destination ..\dist
```

整体本机构建脚本：[Build-Local.ps1](/D:/Codes/dsh-satellite-geometry/scripts/Build-Local.ps1)，会构建前端、插件、安装 profile 并构建 Docker。仅修插件 UI 不必重建 CAD 镜像。

异机 `.tgz` 安装流程见 [plugin/README.md](/D:/Codes/dsh-satellite-geometry/plugin/README.md)。要点是 `npm install --omit=dev <tgz绝对路径>` 后运行包内 `install-profile.mjs`。安装路径需长期保留，profile 链接到这里。同名 profile 指向其他安装目录时，安装脚本会拒绝覆盖。

宿主升级、依赖安装、构建及打包是不同操作；npm 包不含 Docker 镜像。远程计算只需部署服务并修改连接地址，必要时使用 SSH 隧道，不必把 CAD 环境安装到轻客户端。

### 9.3 已有验收证据与重跑范围

| 入口 | 内容 |
|---|---|
| [VALIDATION.md](/D:/Codes/dsh-satellite-geometry/VALIDATION.md) | 2026-09-29 几何与端到端验收；24 后端测试、5 插件测试和真实案例限制 |
| [UPGRADE-0.2.md](/D:/Codes/dsh-satellite-geometry/UPGRADE-0.2.md) | 2026-10-02 DSH 适配验收及其他插件限制 |
| [validation/final-summary.json](/D:/Codes/dsh-satellite-geometry/validation/final-summary.json) | 历史案例项目/修订、产物哈希、检查结果 |
| [validation/native-integration-summary.json](/D:/Codes/dsh-satellite-geometry/validation/native-integration-summary.json) | 实际 DSH 模型读取资料、26 字段出处核验 |
| [validation/dsh-upgrade-0.2.0.json](/D:/Codes/dsh-satellite-geometry/validation/dsh-upgrade-0.2.0.json) | 登录、路由、设置、MCP 重连、8 项目及独立安装证据 |
| [scripts/validate_dsh_upgrade.mjs](/D:/Codes/dsh-satellite-geometry/scripts/validate_dsh_upgrade.mjs) | 重测 DSH 集成；会保存当前服务地址、重连 MCP 并创建测试选区引用，并非纯只读 |
| [scripts/validate_http.py](/D:/Codes/dsh-satellite-geometry/scripts/validate_http.py) | 实际几何 HTTP 流程；支持 `--existing-project` 与 `--export-only`，避免不必要的重复导入/简化 |

后端检查在项目根目录执行 `python -m unittest service.test_api service.test_geometry service.test_workbench -v`。本轮 36 项通过，插件 7 项通过。真实 DSH 合成与 CATCH 流程、失败及人工复核说明见 [VALIDATION-0.3.md](docs/VALIDATION-0.3.md)。原生模型测试会调用已配置模型；安装检查和普通 `npm test` 不调用模型。

本轮主要独立验收工程如下，不覆盖原有案例工程：

| 工程 ID | 当前修订与用途 | 对应会话 / 证据 |
|---|---|---|
| `bb62c0b0d2cc490d8bd1f39953d51a76` | 当前 7；无界面 API 与新版候选身份检查；磁盘导出快照为 6 | `v03-review-5557a2c2-8114-42f1-abf5-32f63be6ede2`；`validation/raw/v03/api.json`、`review-evidence.json` |
| `0f13d851447549bb9a1978baa1d09b9c` | 5；真实原生 DSH 合成建模，组合实体＋面壳 | `v03-native-d5c9716f-aa44-4f39-a8c6-822bfab02512`；`native-evidence.json` |
| `4f7c0f1afb834c98a339d5931f1a6588` | 22；CATCH 真实整星候选基线，经开发复核导出，工程判断仍未知 | `v03-catch-5d88705c-2cf4-406e-82bd-16417a790225`；`catch-final-evidence.json` |

本轮原始证据、截图和案例下载在 `D:\Codes\dsh-satellite-geometry\validation`，受 `.gitignore` 保护，不随 npm 或 Git 源码分发。最终包已在隔离 `DSH_HOME` 的临时 3084 宿主上运行验证，临时进程已停止；正式工作台仍在 3081。当前 CATCH 有 11 个候选身份、13 个源拓扑缺陷组件及部分未知接触；不能把可读 STEP 当作已认证热工程模型。

临时测试容器 `satellite-geometry-validation` 当前已停止；不需要重启旧开发端口 8789。历史原始对话包含早期失败与过时端口，后续应以最终验证摘要和当前服务配置为准。

## 10. 下一模块建议的迁移步骤

1. **先判断是否已有迁移实现。** 同时检查原 Agent Web 模块与远端 DSH `packages/custom`。选择独立 npm 插件还是继续定制 DSH 仓库，需根据用户希望的安装方式决定。
2. **列清依赖和输入输出。** 记录前端入口、API、数据库、文件目录、Skill、原生程序、外部软件、模型调用、作业和取消机制。尤其分清远端当前 PostgreSQL 权威状态与旧磁盘 JSON 投影。
3. **冻结可追溯来源。** 记录源路径、日期、Git HEAD、未提交差异及实际取回文件哈希。保持原应用与模板只读，在独立目录提取。
4. **先约定一个最小可用闭环。** 例如“选择版本 → 上传输入 → 调用计算 → 查询进度 → 人工检查 → 导出”。界面确认、自动化权限及工程验收与该模块实际用途对应。
5. **分开业务服务和宿主适配。** 重型原生依赖放服务/容器；DSH 插件提供连接设置、鉴权代理、MCP/原生工具、Skill 和业务 UI。已有的 DSH 会话及模型配置继续复用。
6. **明确数据身份与编辑边界。** 使用业务项目 ID、版本、作业 ID 和工件清单；不要将组件名称当唯一身份，不允许浏览器任意指定服务端文件路径。
7. **单独 profile 验证。** 新插件使用独立包名、entry ID、路由、工具前缀、端口和数据卷。不能沿用卫星插件的 ID 或修改其生产数据。
8. **先小样本，再真实案例。** 确认失败处理、取消、重启恢复、来源字段和 UI 联动，再用原项目实际输入验证；明确哪些检查未完成。
9. **验收最终安装包。** 在干净目录安装 `.tgz`，验证预构建 UI、依赖、宿主版本和 MCP，不能仅证明开发源码可运行。
10. **交付可复现资料。** 记录安装、启动、服务部署、数据备份、真实算例路径、输出哈希和限制。只有打算公开发布时才进入公共 npm 发布流程。

尚需为下一模块重新确认：业务范围、用户界面位置、自动执行与人工确认边界、数据共享方式、是否依赖工程软件授权、目标运行环境与验收算例。卫星几何模块的需求访谈结果不能自动套用到所有模块。

## 11. 可直接交给后续开发者的任务背景

> 先阅读 `D:\Codes\dsh-satellite-geometry\HANDOFF.md`、`docs/workbench-api.md` 和 `docs/VALIDATION-0.3.md`。本机宿主是 Windows npm 的 DSH 0.2.0-rc.2，插件和计算服务为 0.3.0，服务运行于 WSL Docker。请把它作为集成参考。原 Agent Web 位于 SSH 别名 work-server-5090-ali 的 `/data/lbk/codex_web/agent-web`；同级 `deepseek-harness/packages/custom` 已有部分 DSH 迁移实现。先只读检查我指定的下一模块、当前未提交代码及既有定制插件，列清依赖和可复用部分，再按新任务确定范围。保持原模板、会话与生产项目；所有写操作使用当前修订。不要把旧源码 ZIP、旧验收修订或远端 0.1.0 插件副本当成最新本机实现。

远端路径和原始案例哈希仍为 2026-10-07 的只读复核。2026-10-10 在本机独立工程运行了本轮测试和 CATCH 建模；没有认证远端定制插件或 Windows 桌面内置宿主兼容性。
