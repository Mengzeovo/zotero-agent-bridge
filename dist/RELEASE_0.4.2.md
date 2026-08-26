# Zotero Pi Assistant 0.4.2

`0.4.2` 是 Zotero Pi Assistant 的正式版本。本次发布将经过 beta 阶段验证的 Pi-only 文献助手升级为稳定版本，并保持 add-on ID、Bridge Home、API Token、Pi session 路径和文档 ID 规则不变。

## 下载

推荐安装：

- `zotero-agent-bridge-addon-0.4.2.xpi`
- Platform: Windows x64 bundled Bridge
- Add-on ID: `zotero-agent-bridge@local`
- Lifecycle protocol: `2`
- Product scope: `zotero-pi-only`
- SHA-256: `e686a25194b5c8e48f1a1e0271f7ac830b3b9695b25cf5c8c8e691022a6581b4`
- SHA-512: `f060a791803ecccb732e8466bee5714de17f1d519a4c611d200a79f6cf2bb4d6c407f2a8d0e1d853ca51496c64a7f70ccab60ced3277d3c11b39928fa3eec5de`

## 主要功能

- 在 Zotero Item Pane 和 PDF Reader 侧栏中使用 Pi 文献助手。
- 读取当前论文的本地 PDF、元数据、子笔记、批注和页码上下文。
- 支持流式回答、中止、新会话、模型与思考程度切换。
- 支持文字、图片以及文字加图片提问。
- 每篇论文独立保存 Pi session，支持历史恢复与孤儿会话找回。
- 支持 Markdown、KaTeX、代码块和复制时恢复原始 LaTeX。
- 用户确认后将完整问答保存为 Zotero 子笔记。
- 增量构建本地知识账本，并确定性重建唯一的 `Pi 经验笔记`。
- XPI 自带并管理 Windows x64 Bridge，普通用户不需要 Python 或仓库源码。

## 0.4.2 更新重点

- 增加异步、增量的经验笔记更新流水线。
- 引入可追溯的知识账本，保存问答证据、知识单元、关系、认知修正和来源状态。
- 未变化的问答不再重复调用 Pi；来源会话缺失时保留已提取知识并显示警告。
- 完善“保存问答”和“更新经验笔记”的 Zotero 交互反馈。
- 改进 README，对项目作用、使用场景、安全边界和局限性进行完整说明。
- 修正插件自动更新地址，使其指向仓库实际默认分支 `master`。

## 安装与升级

1. 下载 `zotero-agent-bridge-addon-0.4.2.xpi`。
2. 在 Zotero 打开 **工具 → 插件 → Install Plugin From File…**。
3. 选择 XPI 并重启 Zotero。
4. 确保 Pi CLI 已安装，并已配置可用模型与凭据。

升级不会删除现有 Pi session 或经验知识账本。升级前仍建议备份 Zotero 数据目录。

## 验证

- 169 项自动化测试通过。
- Python `compileall` 通过。
- Release 路径、Token 和机器路径扫描通过。
- XPI 从同一 Bridge bundle 重建后字节完全一致。
- Bundled EXE 启动冒烟测试通过：版本 `0.4.2`、protocol `2`、scope `zotero-pi-only`、distribution `xpi-bundled`，并可通过 owner-authenticated shutdown 正常退出。
- XPI 内部 add-on、Bridge manifest 和 SBOM 版本一致。
- 构建来源：`be00ab1ff208770a0321f0cd137ecc348e9a3c66`。

## 已知限制

- 自带 Bridge 当前仅支持 Windows x64。
- Pi CLI、模型和凭据需要单独配置。
- 不包含 OCR、云端同步或多机 session 同步。
- 同一 Bridge 同时只维护一个活动回答。
- Bridge EXE 尚未进行 Authenticode 签名。

## Supply chain

- `zotero-pi-assistant-0.4.2-SBOM.cdx.json`
- `THIRD_PARTY_NOTICES-0.4.2.md`
- `SHA512SUMS-0.4.2.txt`
