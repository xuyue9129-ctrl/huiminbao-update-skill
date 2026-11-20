# 惠民保官方资料更新 Skill

给 AI Agent 使用的惠民保年度信息更新工作流：寻找官方发布、读取公众号和小程序、记录逐字段依据、维护既有 Excel、验证公式与格式、断点续做和交付。

**不含保险产品数据、工作簿、采集原文、账号信息或凭据。不承诺自动绕过微信访问限制，也不支持支付、投保或聊天。**

## 安装

将本仓库 `skills/huiminbao-update` 整个目录复制到目标工作区：

```text
你的工作区/
  .factory/
    skills/
      huiminbao-update/
        SKILL.md
        references/
        scripts/
        examples/
```

然后启动新会话，在 `/skills` 确认已启用，输入：

```text
/huiminbao-update
更新当前工作区的惠民保汇总，目标保障年度2028。
先读取 latest_progress.json 确认最新底稿，仅使用官方来源。
先核查我指定的产品，不自动发布文件或操作投保。
```

其他支持 SKILL.md 的 Agent 可使用其对应 skills 目录；不支持自动发现的 Agent 直接读取 `SKILL.md` 及其中引用文件。项目规则与用户当次授权始终优先。

## 包含什么

| 组件 | 用途 |
| --- | --- |
| `SKILL.md` | 完整顺序、授权边界、停止条件和交付门槛 |
| `references/wechat.md` | 公众号/小程序实际调取、长图、H5、验证码和抢焦点处理 |
| `references/evidence.md` | 官方身份与年度证明、逐字段依据和冲突处理 |
| `references/workbook.md` | Summary字段、编号、插行、公式、来源表和重算 |
| `references/recovery.md` | 检查点、恢复、并发、常见失败 |
| `scripts/workflow.py` | 初始化批次、环境检查、证据校验、工作簿只读检查与受控补丁 |
| `scripts/recalculate.py` | 用独立Excel实例重算临时副本，提取真实缓存，不改正式文件 |
| `scripts/wechat/control.py` | Windows窗口定向UIA/消息/截图辅助入口，导航时自动启用前台拦截器 |
| `scripts/wechat/focus_gate.py`、`focus_gate.c`、`focus_gate_v6.dll` | 前台拦截器：Agent操作微信时不抢用户前台；DLL可用`build_focus_gate.ps1`从源码重建 |
| `scripts/test_workflow.py` | 合成文件回归测试，不连接微信、不操作真实工作簿 |
| `scripts/test_recalculate.py` | 显式开启的Excel集成测试，只创建临时合成工作簿 |

## 环境与快速检查

- 通用脚本：Python 3.10+，`openpyxl>=3.1,<4`、`lxml>=5,<7`。
- 微信辅助：Windows x64、64位Python、已登录微信、PowerShell 5.1、`Pillow>=10,<13`。重建DLL需`ziglang`（可选）。
- Excel重算：Windows桌面版Excel及`pywin32>=306`，可使用单独安装了pywin32的Python。
- 不自动安装依赖；遵循目标工作区依赖与安装授权。

```powershell
python -X utf8 .factory/skills/huiminbao-update/scripts/workflow.py preflight
python -X utf8 .factory/skills/huiminbao-update/scripts/test_workflow.py
python -X utf8 .factory/skills/huiminbao-update/scripts/wechat/test_control.py
python -X utf8 .factory/skills/huiminbao-update/scripts/wechat/test_focus_gate.py
```

可选的真实Excel重算测试（关闭本测试新建的独立Excel实例，不操作已有工作簿）：

```powershell
$env:HMB_TEST_EXCEL='1'
python -X utf8 .factory/skills/huiminbao-update/scripts/test_recalculate.py
Remove-Item Env:HMB_TEST_EXCEL
```

微信自测只使用不可见测试控件；真实页面必须逐次观察验证。导航命令自动启用前台拦截器：向微信进程加载拦截DLL，拒绝微信在后台操作期间抢前台，用户可继续使用其他软件。本机实测公众号导航、页内搜索、小程序打开均为前台零变化，详见验证记录。加载DLL存在被微信风控识别的风险，首次使用前须用户同意；命令报告前台受扰时停止该类操作，不重试。

## 重要限制

- `workflow.py apply` 是**已有单元格补丁工具**，不是万能插行器。新增产品行必须按实际工作簿结构实现迁移，再验证公式、名称、合并、表、验证范围和来源跳转。未知复杂结构必须停下，不能静默损坏。
- 自动校验不能证明“来源真是官方”或“引文真实”。Agent必须阅读原文和图像；域名/文件存在仅是必要条件。
- `latest_progress.json` 是定位线索，不是绝对真相。正式文件SHA256、当前表头和产品身份才是更新前置条件。
- 未披露、未取得正文、无字典映射均不猜填。`not_found` 不等于删除已有已证实的值。
- 重算后可能仍有旧底稿错误。对基准副本和候选副本独立重算比较，报告新增错误及遗留错误，不能宣称“零错误”。

## 发布安全

公开仓库只保留通用脚本、说明和虚构示例。证据、截图、工作簿和运行进度默认放在仓库外的实际工作区，且被`.gitignore`排除。发布前执行`workflow.py scan-package`并人工复核全部拟发布文件。扫描是辅助，不是无泄露保证。

Factory skill规范：<https://docs.factory.com/harness/skills.md>。
