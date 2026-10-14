# 0.3.1 资料容错与 Agent 恢复验收

日期：2026-10-14。工程：`D:\Codes\dsh-satellite-geometry`。本补丁按用户确认的路线实现，维持 DSH 0.2.0-rc.2、Windows 插件及 WSL Docker 部署。

## 实现范围

- 原生解析优先；XLSX空白填充项在内存副本补齐。原字节、原SHA-256、数值格式及公式缓存保留，成功时记录兼容方法与警告。
- 解析失败保留原件并登记`needs_recovery`，扫描PDF为`needs_ocr`，空资料为`empty`。不把页码标记当成正文，也不将部分解析当成完整资料。
- 界面继续其他资料和STEP导入；正常会话就绪且几何作业结束后，将待恢复资料送入当前DSH Agent。没有会话时保留等待状态。
- 同内容资料按SHA-256去重。自动恢复先领取唯一请求，再排入会话；刷新、并行页面及不确定回执不自动重发。Agent每份资料最多两次工具尝试。
- 新增`recover_document`工具及HTTP恢复、领取/回执接口。备用读取支持XLSX和DOCX内部XML；输出附单元格或表行引用，未解释日期、单位及显示格式。工具不接受Agent编写的替代原文。
- 无法恢复时登记`unreadable`并写明缺失项，保留下载和人工重新读取入口。扫描件OCR、缺失密码和实质损坏文件没有新增万能恢复能力。
- 上传失败保留HTTP状态；后台未捕获异常返回规范JSON。插件失败回执补齐DSH 0.2 rc2要求的`error.details`，避免客户端将业务失败误报成协议错误。
- 不修改现有冻结Skill；恢复任务明确只读取资料，不修改工程几何、位姿、装配、热参数。

## 自动与实际运行验证

| 验证 | 结果与证据 |
|---|---|
| 后端回归 | `service.test_documents`、`service.test_api`、`service.test_workbench`共33项通过；日志`validation/document-recovery-backend-tests.log` |
| 插件回归 | 10项通过；含真实stdio MCP发现新工具、恢复路由参数、并行/刷新只发送一次、切换会话及不确定入队保护 |
| 前端与镜像 | TypeScript/Vite、插件构建、Docker 0.3.1镜像构建通过；Vite保留已有大包提示 |
| 真实问题XLSX | 原上传16973字节；SHA-256 `d063d96a4f402cd7dcde4e9144935c05185fd50aef440bda8140e81b3c78f0ff`。三张表169个非空行恢复成功，源字节不变 |
| 隔离HTTP流程 | 临时容器、临时内存数据目录：问题表恢复、损坏表登记、正常文本读取、随后STEP导入完成并有3组件、去重、重复领取拒绝、无法读取终态及原件下载均通过；结果`validation/document-recovery-http.raw.json` |
| 原用户工程 | `00700f34f3344c0a900868c294f2f7dd`“天元卫星几何简化”：用此前留存的失败上传原字节，经实际页面导入`problem-excel-20261014.xlsx`，修订0→1，资料`extracted`/`xlsx_empty_fill_compat`；没有导入或修改该工程几何 |
| 实际Agent会话 | 测试工程`9eb31af3cd7149b8867f10c6806b70e6`，会话`session-0d7c2973-849f-4bd6-9b05-42eb1689ae30`。当前模型DeepSeek-V41-Flash；混合上传两份异常表、正常文本及实例STEP后，Agent自动执行一轮恢复，约20秒完成 |
| Agent成功分支 | `agent-fallback-test.xlsx`：原生styles解析失败，Agent选择`xlsx_xml`，一次工具尝试后`extracted`/`resolved`；明确日期序列46309和无缓存公式为未解释/未知 |
| Agent失败分支 | `corrupt-upload-test.xlsx`：不是ZIP容器，`xlsx_xml`及`retry`两次均失败，Agent调用`mark_unreadable`并说明全部工作表内容缺失；最终`unreadable`/`needs_review` |
| 几何与参数保护 | Agent测试工程3组件仍为source表示，pose等于originalPose；未写入质量、功耗或材料，正常文本未触发恢复；证据`validation/document-recovery-native.raw.json` |
| 一次性与记录 | 两份异常表各`automaticAttempts=1`，正常表为0；31条关联会话记录中只有1条自动恢复用户请求，刷新后未增加；`validation/raw/document-recovery-native-session.json` |
| DSH失败回执 | 安装后通过认证代理核对0.3.1健康及故意缺失测试资料的失败回执：`ok:false,error:{code,message,details}`；脚本`scripts/validate_document_recovery_host.mjs`，结果`validation/document-recovery-host.raw.json` |

用于回归的合成表不替代卫星建模算例验收。此补丁验证文件读取与恢复流程，不重新认证此前的几何质量、组件身份或热分析适用性。CATCH正式验收工程更新前为修订28，本次保持该修订。

## 部署、发布与保留

- 工作台：`http://127.0.0.1:3081/satellite-geometry/`；计算服务：`http://127.0.0.1:8787/api/health`，返回`version:0.3.1`。
- 容器：`dsh-satellite-geometry-geometry-1`；镜像`dsh-satellite-geometry:0.3.1`；沿用原`dsh-satellite-geometry_project-data`卷。
- 新插件包：`release/lbk-dsh-satellite-geometry-0.3.1.tgz`；包不包含原卫星或测试资料、凭据、Python环境。SHA-256记录在`release/lbk-dsh-satellite-geometry-0.3.1.sha256`。
- 更新前工程元数据、资料、Skill及会话绑定备份：`runtime/backups/satcad-pre-documents-031-20261014.tar.gz`。该备份不含完整几何产物，原完整数据仍在生产卷中。
- 页面截图：`validation/screenshots/excel-recovery-031-20261014.png`及`validation/screenshots/agent-document-recovery-031-20261014.png`。
- 独立测试工程/会话保留供查看；临时隔离HTTP容器已停止，其测试目录未写入生产卷。

先前失败请求生成的13份相同原文件仍保留，没有进行删除或批量重写。此次成功登记只增加一份资料记录。
