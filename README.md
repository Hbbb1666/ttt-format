# TTT 文件格式（`.ttt`）

一种**容器型**自定义文件格式：`56 字节二进制头` + `JSON 清单` + `ZIP 负载`。
目标是低实现成本、可校验、可扩展，并且能被任何语言在几百行内实现。

> **当前状态**：`v0.1` 容器层已实现（Python 参考实现 + 测试 + CI）；
> **内容语义层尚未定义** —— `content` 对象里放什么由业务侧约定，容器不关心。

## 分工

| 角色 | 负责 | 不负责 |
|---|---|---|
| **电脑端（主开发）** | 规范演进、参考实现与多语言 SDK、CI/发布、性能 | 真机适配验证 |
| **手机端（实机验证）** | `.ttt` 在真机上的打开/关联/MIME/权限/大文件验证；设备桥、ADB、构建工具链等环境辅助 | 语义设计与主代码 |

## 快速开始

```bash
python3 -m pip install -e .        # 可选；不安装也能直接用 python3 -m ttt.cli
python3 -m ttt.cli new -o demo.ttt --tag demo=1
python3 -m ttt.cli inspect demo.ttt
python3 -m ttt.cli validate demo.ttt
python3 -m ttt.cli extract demo.ttt -C out/

# 装好后等价于：
ttt validate demo.ttt
```

## 仓库结构

```
docs/SPEC-0.1.md        规范（容器层 v0.1，权威文本）
docs/REGISTRATION.md    各平台后缀/MIME/UTI 注册清单
docs/VERIFICATION.md    手机端实机验证清单与边界
ttt/                    参考实现（仅标准库）
tests/                  单元测试 + 畸形样本
.github/workflows/      CI（多版本 Python，跑测试 + 冒烟）
```

## 兼容承诺（v0.1 起）

1. 读取端遇到**未知 major** 必须拒绝（`UNSUPPORTED_VERSION`），不得猜测。
2. 读取端遇到**更高 minor** 应尽力读取，并在 `warnings` 里报告。
3. 未知的 header 字段与未知 flags 必须忽略，不得报错。
4. 负载 SHA-256 不匹配一律拒绝，不做"修复"。
5. 写入端默认只写 v0.1 字段集合；新增字段必须先改规范再改实现。

## 路线

见 `ROADMAP.md`。下一步（电脑端）：语义层草案、MIME 草案提交 IANA、多语言实现。

## 许可

MIT，见 `LICENSE`。
