# 卫星几何工作台 · DSH 插件

后续继续开发或拆分原 Agent Web 其他模块，请先阅读 [开发交接文档](HANDOFF.md)，其中汇总本机/5090 路径、三个卫星算例、DSH 适配经验和迁移入口（2026-10-07 复核）。

本轮热设计工程师工作台改进以 [2026-10-09 需求与验收](docs/requirements-20261009.md) 为准，包含可重建单机方案、面壳、接触关系、Skill 版本与外部测试接口。

独立的 STEP 几何简化、装配检查与资料整理工作台。左侧使用 DSH 原生对话及其现有模型连接；右侧提供三维视图、装配树、局部操作和检查报告。几何内核及文档读取运行在独立 Docker 服务中。

当前版本是 **0.3.0 热设计工作台**，适配 DSH **0.2.0-rc.2**。保存原始文件、稳定组件 ID、原位姿和属性出处；工程师修改当前方案，按需保存命名副本。业务接口见 [workbench-api.md](docs/workbench-api.md)，本轮验收见 [VALIDATION-0.3.md](docs/VALIDATION-0.3.md)；[VALIDATION.md](VALIDATION.md) 保留早期版本的测试记录。

## 在这台电脑上使用

工程位置：`D:\Codes\dsh-satellite-geometry`（WSL：`/mnt/d/Codes/dsh-satellite-geometry`）。本地 Git 仓库保留了原始开发历史；目录迁移和验证记录见 [MIGRATION.md](MIGRATION.md)。

双击桌面的 **卫星几何工作台**。启动器会复用或启动 WSL Ubuntu 内的 Docker 服务及独立的 DSH `satellite-geometry` 配置，然后打开：

**http://127.0.0.1:3081/satellite-geometry/**

也可以从 PowerShell 运行：

```powershell
& .\scripts\Start-Workbench.ps1
```

本机几何服务为 `http://127.0.0.1:8787`。工作台已使用单独的 DSH 配置，不需要关闭原有 3080 实例。这里的 Docker 运行于 WSL Ubuntu，不依赖 Docker Desktop 窗口是否打开。

1. 在左侧选择工作区或会话。在右侧新建项目，导入 STEP；配套 DOCX、XLSX、PDF 或文本可以随后加入。
2. 点击顶部 **Skill** 查看正文和资源，选择版本并绑定当前 DSH 会话。需要更换版本时在 DSH 新建会话；旧会话保留已固定的规则、内容指纹和对话。
3. 点击 **一键建模**，任务交给 DSH 当前模型。Agent 阅读配套文件，整理中文两层工程树，建立单机方案，默认保持原位姿。缺乏可靠匹配时显示待识别或候选待核实。检查页聚焦干涉与安装接触。
4. 点选单机自动进入局部原始/简化对比，左右视角默认同步；“整星”返回全体，“相邻安装件”显示接触对象。目录或三维右键 **带入 DSH 聊天**，草稿包含固定 SG 引用，编辑后发送。后续选区不改变已发引用。
5. 直接要求“陀螺仪改成圆柱加底座”“计算机只建面壳”，或在右侧修改结构化方案并 **应用并重建**。需要保留时使用 **保存当前方案为副本**；副本可载入重建。意见及修改只做记录，留待后续集中升级 Skill。
6. 在“资料与导出”生成完整交付包，下载 STEP、三维预览、组件属性及接触清单。导出文件对应明确的项目修订。

导出页将“文件可读取”“拓扑检查通过”和工程用途检查分开显示。源模型本身有拓扑缺陷时，可导出明确标记的复核包，用于检查和修复；即使文件可以打开，也不表示它已适合下游热分析。若有效源模型在导出后出现新的拓扑失败，服务会拒绝发布。

对于输入不足的属性，模型应保留未知；人工补充会单独标记为人工来源。可以要求 DSH 解释任一属性来自哪个文件的哪段原文。扫描版 PDF 当前需要先做 OCR。

## 已实现的边界

- 原始 STEP 的实例、装配层次和变换被保留。普通简化不移动组件。
- 包络体使用几何内核生成；模型负责理解资料、选择策略和组织操作，不直接执行生成的任意 Python 代码。
- 对接触、关键组件或检查不确定项，热分析模式可以保留完整原实体。因此“完成处理”不保证每个组件都被大幅简化。
- 原始真实干涉与包络引入的假干涉分别记录。包络问题优先细化，必要时恢复原实体，不以移动零件消除假干涉。
- 移动必须有明确授权和约束。已有真实问题的自动修复必须降低干涉；候选动作还要通过新碰撞、位移/转角限制和接触保护检查。首版没有全局布局优化求解器。
- 几何接触候选不等同于已确认的热连接。报告不认证材料、热导率、线缆、安装顺序或孔位配合；不生成网格或求解模型。
- 大型复杂 STEP 可能耗时数分钟或更长。几何作业运行于独立进程，可以取消；未完成结果不会覆盖已保存版本。达到检查上限或计算失败的项目标为未知。

## 输出与持久数据

交付 ZIP 包含：

| 文件 | 内容 |
|---|---|
| `simplified.step` | 按工作装配树组织的命名实体，保留当前组件位姿 |
| `simplified.glb` | 三维预览，包含稳定组件标识 |
| `properties.json` | 组件属性、字段出处、原始/当前位姿、来源装配树、简化策略及检查结果 |
| `contacts.json` | 几何接触候选、真实干涉、检查完整性与待确认事项 |
| `recipes.json` | 可重建单机方案、面壳/实体表示、独立热属性、安装区域及指纹 |
| `feedback.json` | 工程师意见、实际修改及关联会话摘要；`autoSkillUpdate:false` |

正式容器的项目数据保存在 Docker 卷 `dsh-satellite-geometry_project-data`。重启容器不丢失项目。源文件及开发验收数据另保留于本仓库的 `cases/`、`data/` 和 `validation/`，不随源码发布。备份项目时需备份 Docker 数据卷；DSH 对话与几何引用保存在当前用户的 DSH 数据目录中。

## 构建与迁移

本机源代码构建需要 Node.js、DSH **0.2.0-rc.2**、WSL Ubuntu 和可运行的 Docker：

```powershell
& .\scripts\Build-Local.ps1
& .\scripts\Install-Shortcut.ps1
```

Docker 镜像固定 Python/CAD 依赖版本。另一台 Linux 主机只需 Docker 与 Compose，在源码根目录运行：

```sh
docker compose build
docker compose up -d
```

复杂相交的默认计算时限为每对 10 秒、每轮精确配对 300 秒、每个作业 1 小时；STEP 读取时间不计入配对预算。超时会保留原几何并列为未知。需要更深入检查时，将 `.env.example` 复制为 `.env`、提高相应时限、重建容器后再运行检查。已有成功配对可复用，超时项会重新尝试。

默认仅监听该主机的回环地址。如果使用远程计算，建议通过 SSH 隧道访问：

```sh
ssh -N -L 8787:127.0.0.1:8787 your-server
```

本机桌面启动器固定使用 `8787`。其他部署可以修改 `SATCAD_PORT`，但需要手动运行 Compose，并在插件中填写对应地址；桌面启动器会对非默认端口给出即时提示，避免等待后误报超时。远程计算时直接打开 DSH 即可，无须再用本机计算服务启动器。

在本机 DSH 的“设置 → 内置插件 → 卫星几何”填写计算服务地址并检查连接。也可使用已配置访问控制的 HTTPS 地址；如服务配置 `SATCAD_TOKEN`，在插件设置中保存同一访问令牌。令牌保存在 DSH 凭据服务，不写入模型对话或前端源码。

插件包含 Node stdio MCP 桥接器：DSH 通过 MCP 调用它，它再访问几何 HTTP 服务。远程部署只改变服务地址，不需要在轻量客户端安装 CadQuery。STEP/GLB 文件由代理传输，避免把大文件作为模型上下文。

`plugin/` 可以构建并打成 npm 安装包。包内带三维界面、MCP 桥接器和操作 Skill，安装说明见 [plugin/README.md](plugin/README.md)。Skill 描述操作规则；MCP 暴露真实计算能力；插件把这些能力、界面和连接设置装在一起。

## 开发与检查

```sh
python -m pip install -r requirements-dev.txt
python -m unittest service.test_api service.test_geometry service.test_workbench -v
cd web && npm ci && npm run build
cd ../plugin && npm ci && npm test && npm run build
```

后端协议与几何判定边界见 [service/README.md](service/README.md)，来源案例见 [cases/README.md](cases/README.md)。移植自用户原项目的代码出处见 [vendor/PROVENANCE.md](vendor/PROVENANCE.md) 和 [vendor/NOTICE.md](vendor/NOTICE.md)。本仓库是用户本地项目的独立提取，没有将原项目素材或代码公开发布。
# 本机部署状态（2026-10-10）

本机网页版宿主为 DSH **0.2.0-rc.2**；本轮插件和计算服务均为 **0.3.0**。设置接口、浏览器认证、插件设置页和桌面启动器保持适配。使用桌面“卫星几何工作台”进入。宿主升级历史见 [升级与验证说明](UPGRADE-0.2.md)，当前工程师建模平台验收见 [VALIDATION-0.3.md](docs/VALIDATION-0.3.md)。
