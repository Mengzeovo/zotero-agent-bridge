# XPI Bridge Bundle Schema v1 / Lifecycle Protocol v2

本协议定义 Zotero Pi Assistant 如何在 XPI 中携带、校验、安装和启动 Windows x64 自包含 Bridge，并说明从 lifecycle protocol v1 升级到 Pi-only protocol v2 的兼容边界。

## 固定版本

- Bundle schema：`1`
- Lifecycle protocol：`2`
- Product scope：`zotero-pi-only`
- Distribution：`xpi-bundled`
- Platform：`windows`
- Architecture：`x64`

Schema 文件：`packaging/bridge-manifest.schema.json`

## XPI 布局

```text
bridge/windows-x64/
├─ bridge-manifest.json
└─ zab-bridge/
   ├─ zab-bridge.exe
   ├─ python312.dll
   ├─ _internal/
   └─ ...
```

`bridge-manifest.json` 自身不列入 `files`，防止自引用哈希。`files` 必须覆盖 `zab-bridge/` 下的所有普通文件，不能遗漏或包含额外文件。

## Manifest 示例

```json
{
  "bundle_schema_version": 1,
  "bridge_version": "0.4.2",
  "protocol_version": 2,
  "product_scope": "zotero-pi-only",
  "distribution": "xpi-bundled",
  "platform": "windows",
  "architecture": "x64",
  "entrypoint": "zab-bridge/zab-bridge.exe",
  "sentinel": ".zab-bundle-installed.json",
  "build": {
    "python_version": "3.12.10",
    "pyinstaller_version": "6.21.0",
    "built_at": "2026-08-19T00:00:00Z",
    "source_revision": "git:<commit-or-dirty-tree-digest>"
  },
  "files": [
    {
      "path": "zab-bridge/zab-bridge.exe",
      "size": 1234567,
      "sha256": "<64 lowercase hex characters>"
    }
  ]
}
```

## 规范化规则

- 所有 manifest 相对路径必须使用 `/`。
- 禁止绝对路径、盘符、反斜杠、NUL、空路径和 `..` 路径段。
- `files` 按 Unicode code point 的路径升序排列。
- 每个路径只能出现一次。
- SHA-256 必须为 64 位小写十六进制。
- `entrypoint` 必须同时出现在 `files` 中。
- 安装器必须拒绝 manifest 未列出的 Bundle 文件。
- 安装器不得跟随 staging 或正式 Bundle 中的符号链接、junction 或 reparse point。

## 安装目录

```text
%LOCALAPPDATA%\ZoteroAgentBridge\bridge\
├─ install.lock
├─ install-state.json
├─ .staging-<uuid>\
└─ 0.3.0\
   ├─ .zab-bundle-installed.json
   └─ zab-bridge\...
```

可变 Bridge 数据不放在上述目录，而保留在：

```text
<Zotero Data Directory>\zotero-agent-bridge\
```

## 安装事务

1. 获取 binary root 下的跨实例安装锁。
2. 创建新的 `.staging-<uuid>`；不得复用未知 staging。
3. 从 XPI 提取 manifest 中列出的文件。
4. 每写入一个文件后验证字节大小和 SHA-256。
5. 验证文件集合与 manifest 完全一致。
6. 验证 entrypoint 存在且规范路径位于 staging 根内。
7. 写入 `.zab-bundle-installed.json`。
8. 将 staging 原子重命名为 `<bridge_version>`。
9. 原子更新 `install-state.json`。

如果目标版本目录已经存在，只能在有效哨兵、manifest digest、文件集合与哈希全部匹配时复用；否则必须拒绝启动并报告冲突，不能覆盖未知目录。

## 安装哨兵

`.zab-bundle-installed.json` 至少包含：

```json
{
  "sentinel_schema_version": 1,
  "bridge_version": "0.4.2",
  "protocol_version": 2,
  "product_scope": "zotero-pi-only",
  "manifest_sha256": "<sha256 of canonical manifest bytes>",
  "installed_at": "<UTC ISO-8601>",
  "entrypoint": "zab-bridge/zab-bridge.exe"
}
```

哨兵必须最后写入。缺少、格式错误或 manifest digest 不匹配的目录不得执行，也不得作为回滚目标。

## install-state.json

```json
{
  "state_schema_version": 1,
  "current_version": "0.4.2",
  "current_protocol_version": 2,
  "current_product_scope": "zotero-pi-only",
  "last_known_good": "0.4.2",
  "last_known_good_protocol_version": 2,
  "last_known_good_product_scope": "zotero-pi-only",
  "pending_version": null,
  "pending_protocol_version": null,
  "pending_product_scope": null,
  "protocol_floor": 2,
  "pi_only_established_at": "<UTC ISO-8601>",
  "updated_at": "<UTC ISO-8601>"
}
```

- `current_*`：当前选择的版本、协议和产品范围。
- `pending_*`：已安装但尚未通过 `/lifecycle` 验证的版本、协议和产品范围。
- `last_known_good_*`：至少成功启动并通过生命周期验证一次的兼容 runtime。
- `protocol_floor`：`0.4.1-beta` 读取任何旧状态时都会规范化为 `2`；低于该值的 bundle 不得回滚。
- `pi_only_established_at`：首次成功启动 Pi-only v2 的时间；旧状态中已有值时保留。
- 旧 schema 1 状态文件会安全投影到 protocol floor 2，不改写用户会话或 Token。过渡版本留下的 legacy fallback 诊断字段仅作为未知历史字段保留，不参与任何选择或启动逻辑。
- 状态文件使用临时文件加原子替换写入。

## 生命周期兼容

Bridge `/lifecycle` 必须返回：

```json
{
  "managed": true,
  "owner_id": "...",
  "pid": 1234,
  "started_at": "...",
  "exit_with_addon": true,
  "bridge_version": "0.4.2",
  "protocol_version": 2,
  "product_scope": "zotero-pi-only",
  "distribution": "xpi-bundled"
}
```

当前 Pi-only Bridge 必须满足：

- `protocol_version == 2`
- `product_scope == "zotero-pi-only"`
- `bridge_version` 是非空合法版本
- bundled 启动时 `distribution == "xpi-bundled"`，且版本/协议与已校验 manifest 一致

`0.4.1-beta` 不再接受 protocol v1 或缺少 lifecycle protocol 的实例。未知或低于 v2 的协议不得被复用或作为回滚目标。

## 运行时定位文件

Bridge Home 中写入 `bridge-runtime.json`：

```json
{
  "runtime_schema_version": 1,
  "bridge_version": "0.4.2",
  "protocol_version": 2,
  "product_scope": "zotero-pi-only",
  "distribution": "xpi-bundled",
  "executable": "<absolute verified path>",
  "config_path": "<absolute managed config path>",
  "manifest_sha256": "<sha256>",
  "updated_at": "<UTC ISO-8601>"
}
```

该文件只用于 Zotero add-on 的内部运行时定位和升级诊断；它不是对外客户端发现机制，也不包含 owner token。

## 回滚规则

- 新版本安装后先写入 `pending_version`、`pending_protocol_version` 和 `pending_product_scope`。
- 只有 `/lifecycle` 返回相同版本、协议和 product scope 后，才能更新 `last_known_good_*`。
- 读取安装状态时先建立 `protocol_floor=2`；所有 protocol v1 rollback candidate 均被拒绝，且旧 v1 manifest 不再由安装器解析。
- Pi-only v2 成功后更新 `protocol_floor=2` 和 `pi_only_established_at`。
- v2 到 v2 的回滚仍可使用，但候选必须具有有效 manifest、`product_scope=zotero-pi-only`、哨兵和文件哈希。
- 回退必须在 UI、状态和日志中明确显示，不能静默长期运行旧版本。

## 安全拒绝条件

遇到以下任一情况必须拒绝执行 Bundle：

- schema、平台、架构或协议不支持；
- manifest 路径不安全或重复；
- 文件遗漏、额外文件、大小或哈希不匹配；
- entrypoint 不在受控根目录；
- reparse point、junction 或符号链接；
- 哨兵缺失或与 manifest 不匹配；
- 版本目录与 manifest 版本不一致；
- 端口上的 Bridge 返回未知生命周期协议。
