# 原项目验证案例

数据从用户指定的5090服务器原项目相关目录只读取回。STEP和文档不纳入本仓库Git，不随插件发布；仅用于本机开发与验收。

| 本地目录 | 原模型目录 | STEP字节数 | SHA256 |
|---|---|---:|---|
| `catch-original` | `/data/lbk/codex_web/cad_data/models/mdl_5fda0d85a44fea7c47523185/template` | 96478666 | `b08287d75f974a1698a2b3c9b704aa1bdbca1a96d756b7c5c161e91b3ed06845` |
| `satellite-assembly` | `/data/lbk/codex_web/cad_data/models/mdl_eeb9c173c82c39195f3d40c5/template` | 49374275 | `6fc811ef4efe5a974c4ae0424a60298264cb5586549b6ec5689b5475311ee65d` |

STEP来自各目录下 `.cad-assembly/source/original.step`，配套DOCX与XLSX来自 `00_inputs/`。本地与远端STEP的SHA256已逐一核对一致。文件名中的“CATCH”不能单独证明资料与每个CAD组件都能匹配，抽取过程中应保留出处并报告无法匹配项。

这两个目录是来源模型集合的标识，不承诺其原装配本身没有干涉或其他问题。验收应报告原始问题与简化引入的问题，不能把原始问题隐藏或错误归因于插件。

`real-thruster/original.step` 是第二份装配经无简化导入保存的源原型 `source/prototypes/P00002.step`，对应 `DawnAerospace_B20_Thruster_v2`。它包含 1 个实体、1756 个面，但拓扑检查无效；本机验收将它保留为有缺陷输入的回归案例，没有将“存在实体”当成“实体有效”。SHA256：`8e894238755a9e9db92387b1a922cc6bd50c4bdaea0d10b0fca6aac879c23ffa`。

`real-gearbox/original.step` 来自同一完整装配的源原型 `source/prototypes/P00008.step`，对应 `Compact_Planetary_Reduction_Gearbox_v6`，是经检查有效的 1 实体、133 面组件。用于单独验证有效真实组件的包络生成；单组件检查不替代整星装配或热接触验收。SHA256：`eabc4c4634b8bcdb27795900dae4c07394c891ba40a01352448945ae94b249d1`。
