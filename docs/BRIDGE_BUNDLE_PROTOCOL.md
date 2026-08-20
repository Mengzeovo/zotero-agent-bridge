# XPI Bridge Bundle Protocol v1

本协议定义 Zotero Agent Bridge 0.3.x 如何在 XPI 中携带、校验、安装和启动 Windows x64 自包含 Bridge。

## 固定版本

- Bundle schema：`1`
- Lifecycle protocol：`1`
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
  "bridge_version": "0.3.0",
  "protocol_version": 1,
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
  "bridge_version": "0.3.0",
  "protocol_version": 1,
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
  "current_version": "0.3.0",
  "last_known_good": "0.3.0",
  "pending_version": null,
  "updated_at": "<UTC ISO-8601>"
}
```

- `current_version`：当前 XPI 携带并选择的版本。
- `pending_version`：已安装但尚未通过 `/lifecycle` 验证的版本。
- `last_known_good`：至少成功启动并通过生命周期验证一次的兼容版本。
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
  "bridge_version": "0.3.0",
  "protocol_version": 1,
  "distribution": "xpi-bundled"
}
```

插件只能将满足以下条件的实例视为兼容 shared/owned Bridge：

- `protocol_version == 1`
- `bridge_version` 是非空合法版本
- `distribution` 为已知值：`xpi-bundled` 或受支持的 legacy distribution

未知协议不得被静默复用。

## 运行时定位文件

Bridge Home 中写入 `bridge-runtime.json`：

```json
{
  "runtime_schema_version": 1,
  "bridge_version": "0.3.0",
  "protocol_version": 1,
  "distribution": "xpi-bundled",
  "executable": "<absolute verified path>",
  "config_path": "<absolute managed config path>",
  "manifest_sha256": "<sha256>",
  "updated_at": "<UTC ISO-8601>"
}
```

外部客户端可以读取该文件定位内置 Bridge，但不能据此获得 owner token。

## 回滚规则

- 新版本安装后先标记为 `pending_version`。
- 只有 `/lifecycle` 返回相同版本和兼容协议后，才能更新 `last_known_good`。
- 新版本失败时可回退到具有有效哨兵且协议兼容的 `last_known_good`。
- 回退必须在 UI 和日志中明确显示，不能静默长期运行旧版本。

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
