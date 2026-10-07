# DSH 0.2 升级与插件适配

验证日期：2026-10-02。npm `latest` 为 `@deepseek-ai/dsh@0.2.0-rc.2`（预发布版）。本机 Windows 全局 DSH 已由 0.1.1-rc.2 更新为此版本；WSL 使用这个 Windows 命令，没有另一套独立的全局 DSH 安装。

## 入口

- 主网页版：桌面 `DSH 网页版.lnk`，端口 3080。
- 卫星工作台：原桌面 `卫星几何工作台.lnk`，端口 3081。
- 新版需要浏览器认证；快捷方式从本机日志读取启动链接并换取 DSH 签名 cookie，不把令牌写入文档或安装包。首次直接访问普通网址可能得到 401，应使用快捷方式或终端输出的登录链接。
- 卫星配置页：设置 → 内置插件 → 卫星几何。

## 插件 0.2.0 的变化

- 以新版 volatile Config 和 settings.update 替代已移除的 settings.register；设置仍持久化到 profile。
- 更新 DSH MCP、Skill、Tools 依赖为 0.2.0-rc.2，并声明宿主兼容版本。旧宿主请继续使用 0.1.0 插件。
- 设置 UI 迁移到 settings.plugins.tab；保留会话输入区组件选择与固定引用。
- 插件 RPC 使用共享 /api 的精确 Fetch 路由，保留 DSH 认证，绕开新版自定义 RPC channel 的 webServer 注入错误。
- 文件代理和工作台都使用 DSH 浏览器认证；拒绝匿名与跨站请求。
- 启动器兼容新版认证，并保持 WSL 会话，避免没有 Linux 客户端时 WSL 自动关闭连带停止 Docker。
- 修正本机既有 dsh-watchdog.ps1 的健康检查：使用认证后的主页检查，避免把 401 误判为故障反复重启。原脚本及配置保存在 runtime/dsh-backup-20261002，不随发布包分发。

## 验证

- 5 项插件测试通过，覆盖真实 stdio MCP 15 个工具、请求错误、来源属性和固定选择引用。
- 新 tgz 在独立目录安装成功，安装后的 Host 入口可导入，预构建界面在包内。
- 运行 scripts/validate_dsh_upgrade.mjs：认证换取 cookie、匿名拒绝、跨域拒绝、工作台/前端加载、设置保存、MCP 重连、几何健康检查、8 个已有项目读取、组件引用创建通过。机器证据：validation/dsh-upgrade-0.2.0.json。
- 实际浏览器验证“保存并连接”“检查连接”、减速箱原型/简化几何显示、组件带入 DSH 草稿成功；测试后恢复原草稿，未发送模型请求。
- 截图：validation/screenshots/dsh-0.2-settings.png、validation/screenshots/dsh-0.2-workbench.png。
- 本次修改宿主集成，没有重新运行整星简化或将旧的工程验收结果当成新验收。几何容器仍为 0.1.0，项目数据继续使用原持久卷。

## 其他既有插件的限制

主 web profile 中研究插件 @dsh-scholar/research-plugin 0.1.0 与 Skills 管理器 @michengai/dsh-skills-manager 0.1.48 的宿主兼容范围不含新版，被 DSH 跳过。消息桥接 @wenbin_wb/dsh-bridge 2.10.6 遇到同类自定义 RPC 注入错误。保留它们的配置，没有放宽版本限制或冒充完成其适配。卫星专用 profile 不依赖这些插件。

## 安装包

`dist/lbk-dsh-satellite-geometry-0.2.0.tgz`

SHA256：`29ecc888781b0f6376bbfdecefd26d1554d88fc09caffee1f199226b8f1c9d6e`

这是 npm 本地安装包，未发布到公共 npm 仓库。Windows DSH 桌面应用仍使用其内置运行时，本次没有更新桌面应用，也没有宣称完成其运行验证。
