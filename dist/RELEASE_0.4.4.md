# Zotero Pi Assistant 0.4.4

本次更新改善 Zotero 与 Pi 的会话连接、提问状态恢复和生成完成判断，并支持 Zotero 7–10。

## 更新内容

- 每次提问使用固定的 `request_id`。连接超时或中断后，插件查询原请求状态并恢复回答进度；重复提交相同请求可以继续读取原来的结果。
- 提问与中止操作校验当前 Bridge 实例、会话和论文，防止操作应用到已经切换的会话。
- 使用 Pi 的 `agent_settled` 事件判断生成完成，支持生成期间的自动压缩和重试。
- 完善标题与经验笔记生成的结果检查及独立进程清理。
- 插件与 Bridge 启动时检查版本一致性，确保使用配套的 `0.4.4` 组件。

## 安装与升级

1. 下载 `zotero-agent-bridge-addon-0.4.4.xpi`。
2. 在 Zotero 中打开 **工具 → 插件**，通过齿轮菜单选择 **Install Plugin From File…**。
3. 选择下载的 XPI，完成安装并重启 Zotero。
4. 确保 Pi CLI 已安装，并已配置可用模型与凭据。
5. 打开带有本地 PDF 的文献，在条目侧栏或 PDF Reader 侧栏打开 **Pi 文献助手**。

当前发行平台为 Windows x64。XPI 自带 Bridge，使用者无需安装 Python。升级保留已有模型设置、Pi 会话、Zotero 笔记及经验知识账本。

## 发布验证

- 版本安装包与通用安装包内容一致，SHA-512 与自动更新清单一致。
- XPI 内插件文件与当前源码逐字节一致，Bridge 内应用模块与当前源码编译结果一致。
- XPI 内全部文件 CRC、Bridge 清单文件大小和 SHA-256 检查通过，SBOM 引用的清单哈希正确。
- 安装包通过个人目录、密钥及私人配置文件扫描。
- Bundled Bridge 在独立目录与端口真实启动，版本、生命周期协议、HTTP 鉴权及授权关闭检查通过，进程正常退出。

## 发布附件

- `zotero-agent-bridge-addon-0.4.4.xpi`：安装包。
- `zotero-agent-bridge-addon.xpi`：相同内容的通用文件名安装包。
- `SHA512SUMS-0.4.4.txt`：发布文件的 SHA-512 校验值。
- `zotero-pi-assistant-0.4.4-SBOM.cdx.json`：CycloneDX 依赖清单。
- `THIRD_PARTY_NOTICES-0.4.4.md`：第三方依赖许可说明。
