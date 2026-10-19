# 平台注册清单（`.ttt`）

目标：让系统把 `.ttt` 认成"我们的类型"，能双击/点击打开、显示图标、正确上报 MIME。

> 原则：**magic 优先，后缀只是入口**。任何安全判断都不许只看后缀。

## 0. 查重（先做，别跳）

- IANA 媒体类型注册表 <https://www.iana.org/assignments/media-types/>
- freedesktop `shared-mime-info`（Linux 权威库）
- `/etc/mime.types`（Debian/Ubuntu 打包库）
- Wikipedia "List of file formats" 与 file-extensions.org
- 各应用商店与搜索引擎

结论记录到本文件末尾的"查重记录"。

## 1. IANA MIME

- 早期用 vendor tree：`application/vnd.<vendor>.ttt+zip`，不需要注册，但**必须**同时提供 magic 与后缀说明。
- 想成为 `application/ttt+zip`：需向 IANA 提交媒体类型注册（reviewed 或 standards tree），附规范稳定 URL、magic、安全考虑。规范必须先稳定，否则会被打回。
- 注册前**不要**在对外文档里声称"已注册"。

## 2. Windows

注册表（写入 `HKCU\Software\Classes`，免管理员）：

```
HKCU\Software\Classes\.ttt                (默认) = "TTTFile"
HKCU\Software\Classes\TTTFile             (默认) = "TTT 文件"
HKCU\Software\Classes\TTTFile\DefaultIcon (默认) = "<exe 路径>,0"
HKCU\Software\Classes\TTTFile\shell\open\command (默认) = "\"<exe>\" \"%1\""
HKCU\Software\Classes\TTTFile\Content Type = "application/vnd.<vendor>.ttt+zip"
HKCU\Software\Classes\TTTFile\PerceivedType = "document"
```

注意：
- 装完调用 `SHChangeNotify(SHCNE_ASSOCCHANGED, ...)`，否则资源管理器图标不刷新。
- 从浏览器/IM 保存的文件带 `Zone.Identifier`（Mark-of-the-Web），打开会多一步确认；不要试图绕过。
- 关联只在"未被别的程序抢占"时生效，Windows 10+ 用户可在"默认应用"里覆盖。

## 3. macOS / iOS

- 定义 UTI（`UTType`），遵循 `public.data`，后缀映射到该 UTI：
  - macOS：在 `Info.plist` 的 `UTExportedTypeDeclarations`（自身格式）或 `UTImportedTypeDeclarations`（读取他人格式）里声明。
  - iOS：`CFBundleDocumentTypes` + `LSItemContentTypes`；要"文件"App 里可见还需 `UISupportsDocumentBrowser` 或 `LSSupportsOpeningDocumentsInPlace`。
- macOS 13+ 可用 `UniformTypeIdentifiers` 框架动态声明，但静态 plist 更省事。
- 未声明的自定义后缀，系统会给"未知类型"，双击不会打开。

## 4. Linux

写 `shared-mime-info` XML（`/usr/share/mime/packages/ttt.xml`），然后 `update-mime-database /usr/share/mime`：

```xml
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-ttt">
    <comment>TTT document</comment>
    <magic priority="50"><match value="TTT1" type="string" offset="0"/></magic>
    <glob pattern="*.ttt"/>
  </mime-type>
</mime-info>
```

Linux **优先看 magic**：只要头部正确，改后缀也能认出来。

## 5. Android

- `AndroidManifest.xml`：`<intent-filter>` 用 `ACTION_VIEW` + `CATEGORY_DEFAULT` + `scheme="content"` / `scheme="file"`（视目标 API 而定），`mimeType` 用上面注册的类型。
- Android 7+ 必须 `FileProvider` 把 `file://` 换成 `content://`。
- Android 11+ 包可见性：需要 `<queries>` 声明，否则查不到能打开该类型的应用。
- 现实约束：**SAF / 文件选择器**对自定义后缀常直接给 `application/octet-stream`；很多国产 ROM 的文件管理器还会按后缀猜类型。要做"点开就能用"，必须实测（见 `VERIFICATION.md`）。

## 6. 查重记录

| 日期 | 来源 | 结果 |
|---|---|---|
| 2026-10-19 | 本机 `/etc/mime.types`（2323 条） | 无 `.ttt` 条目（仅 `.ttc`/`.ttml` 等） |
| 待补 | IANA media-types | 未查 |
| 待补 | freedesktop shared-mime-info | 未查 |
| 待补 | Wikipedia / 搜索引擎 | 首轮搜索无有效结果，需重查 |
