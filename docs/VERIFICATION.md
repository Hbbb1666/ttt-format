# 手机端实机验证清单

本清单由**手机端（DSHA 容器）**执行；电脑端负责提供可安装的产物与"预期结果"。

## 边界（先认清，别反复试）

| 能力 | 状态 | 说明 |
|---|---|---|
| 容器内 Python 跑参考实现 | 可用 | 生成/校验/解包 `.ttt`，作为"金标准" |
| 设备 shell（adb-shell） | 命令白名单 | 可读设备文件、查包信息；`pm install`、`screencap`、`uiautomator` 一律被拦 |
| 安装 APK | **需用户手动点装** | `pm install` 被 POLICY_BLOCKED，终点是 `cp` 到 `/sdcard/Download/` 后手动安装 |
| 读屏/点按/截屏 | `/app/ui/*` | 仅 DSHA 在前台且已授权；MCP 的 `android_screenshot` 可能被拒 |
| 渲染网页 | 不可用 | 容器无 Chromium |
| 写系统目录 | 只读 | `/sdcard/Download` 可写 |

## 验证项（每项都要"预期 / 实测 / 结论"三列）

### A. 文件层面（不依赖 App）
- [ ] 1. 在容器生成 `demo.ttt`，`sha256sum` 记录
- [ ] 2. 用设备 shell 从 `/sdcard/Download/` 原样读回，比对 sha256 一致
- [ ] 3. 手工改 1 字节（改 magic / 改 payload），确认校验失败且错误码符合规范
- [ ] 4. 生成 100 MB 级 `.ttt`，确认真机读写不崩、耗时记录

### B. 系统识别
- [ ] 5. 设备上 `content query`/`file` 能读到 `.ttt` 时，系统上报的 MIME 是什么（预期 `application/vnd...`，实测常为 `application/octet-stream`）
- [ ] 6. 文件管理器里图标是否为自定义图标

### C. App 集成（等电脑端出 demo APK）
- [ ] 7. 手动安装 APK（用户点装，允许未知来源）
- [ ] 8. 从文件管理器点击 `.ttt` → 出现在"打开方式"里并成功启动
- [ ] 9. 用 `ACTION_VIEW` 从微信/QQ/下载管理器打开（这类链路最常失败）
- [ ] 10. SAF 选择器选中 `.ttt` 后，App 拿到的 URI 与 MIME
- [ ] 11. 大文件通过 `content://` 流式读取时内存不爆

### D. 跨端一致性
- [ ] 12. 手机端生成的 `.ttt`，PC 端参考实现能校验通过
- [ ] 13. PC 端生成的高 minor 版本文件，手机端给出 `warnings` 而非崩溃

## 回报格式

```
[序号] 预期: ... / 实测: ... / 结论: PASS|FAIL / 证据: sha256 或截图路径
```

FAIL 必须附最小复现（文件 + 命令 + 报错原文），否则电脑端无法定位。
