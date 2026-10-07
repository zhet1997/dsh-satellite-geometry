# 本机工程迁移记录

日期：2026-10-07。

## 当前工程位置

| 环境 | 路径 |
|---|---|
| Windows 工程与 Git 仓库 | `D:\Codes\dsh-satellite-geometry` |
| WSL Ubuntu 对应路径 | `/mnt/d/Codes/dsh-satellite-geometry` |
| 原目录，现已迁出 | `D:\AgentPrj\my_new_computer\work\dsh-satellite-geometry` |
| 工作台 | `http://127.0.0.1:3081/satellite-geometry/` |
| 几何服务 | `http://127.0.0.1:8787/api/health` |

迁移使用同一磁盘内的目录移动。原目录不再保留副本或兼容链接，后续开发请使用新位置。原远端项目 `/data/lbk/codex_web/agent-web` 不受本次本机迁移影响。

## 保留的内容与 Git

- 迁移前后核对 **30,813 个文件，共 1,826,106,697 字节**，相对路径及长度完全一致；这个数量是修改路径和重新构建之前的快照。
- `.git` 原始历史完整保留，初始提交为 `6244c57f2c4836ae5e67220899bf5d11f362fe2e`。后续迁移提交保存 DSH 0.2 适配、启动脚本、交接资料和迁移改动，分支沿用 `master`。
- Git 仅配置本仓库的提交身份 `Codex <codex@local>`，没有创建或推送远端仓库。使用 `git log -1` 查看最新提交。
- `cases/`、`data/`、`service/data/`、`validation/` 中的本地测试产物、`runtime/`、`dist/`、`release/` 和依赖目录均随工程移动。
- 原始算例、运行数据、日志、凭据、依赖和发布包继续按 `.gitignore` 留在本地，不纳入 Git。单独复制 Git 仓库无法得到这些数据。
- 缺失的 `HANDOFF.md` 已从本会话上一次生成的交接内容恢复，并同步调整本机路径。其远端来源信息沿用同日交接核查记录。

正式几何项目依然保存在 WSL Docker 卷 **`dsh-satellite-geometry_project-data`**，挂载到容器 `/data`；该数据卷位于 WSL 中，不在 Windows 工程目录中。DSH 配置、会话和固定选区引用仍在 `C:\Users\49076\.dsh`。完整备份需另行备份这些持久数据。

## 已更新的启动与引用

- `satellite-geometry` 和 `desktop` 两个 DSH profile 的包引用与目录链接指向新工程的 `plugin/`；相关现有锁文件同步更新。桌面版这里只调整路径，不代表完成了桌面宿主兼容验收。
- 桌面的“卫星几何工作台”和“DSH 网页版”快捷方式均已指向新位置的脚本。
- 3 个历史安装验收目录中的内部链接同步调整；历史报告、旧源码 ZIP 和原始证据保留当时的路径信息。
- 开发配置、文档路径已更新，3 个原生对话验收脚本改为从脚本位置推导工程目录。
- WSL 保活进程改为从 Linux 根目录启动，避免继续占用工程目录。普通 DSH 的监控进程也已改从 `D:\AgentPrj` 启动；3080 主服务沿用原进程。
- Docker Compose 容器已从新目录重新创建，保留原数据卷和镜像；Compose 的工作目录标签为 `/mnt/d/Codes/dsh-satellite-geometry`。

本次修改前的 profile 清单、锁文件和快捷方式备份在 `runtime/migration-20261007/`，该目录不纳入 Git。

## 启动方式

继续双击桌面的“卫星几何工作台”，或在 PowerShell 中运行：

```powershell
& 'D:\Codes\dsh-satellite-geometry\scripts\Start-Workbench.ps1'
```

需要继续开发时：

```powershell
Set-Location 'D:\Codes\dsh-satellite-geometry'
git status
git log -3 --oneline
```

## 验证结果

- 文件清单核对一致；CATCH 原始 STEP、立方星原始 STEP 和 0.2.0 npm 包的 SHA256 与迁移前一致。
- 前端构建、插件构建成功；插件现有 5 项测试全部通过。
- 两个启动脚本均通过 Windows PowerShell 5.1 实际启动/复用检查。
- DSH 登录校验、工作台页面、三维页面及其 2 个静态资源通过；几何代理健康检查正常。
- 原有 **8 个几何项目的 ID、名称和修订号全部保持一致**。
- 新位置的 MCP 可发现 **15 个工具**，通过真实服务只读列出项目并读取减速箱案例。
- Docker 容器状态为 healthy；Git 对象完整性检查没有损坏，保留了迁移前已有的未引用对象。
- 交接文档 38 个本地绝对路径链接全部可找到目标。

机器可读记录见 [validation/workspace-migration-20261007.json](validation/workspace-migration-20261007.json)。本次没有修改几何算法，也没有重复运行耗时的整星简化验收；原始几何验证仍见 [VALIDATION.md](VALIDATION.md)，DSH 0.2 适配验证见 [UPGRADE-0.2.md](UPGRADE-0.2.md)。
