# 发布验证记录

日期：2026-11-20。此记录只说明本次实际验证，不保证其他电脑、微信版本或任意复杂工作簿兼容。

## 已通过

- Windows本地Python 3.12：16项合成工作流测试，覆盖基准哈希、原值前置条件、禁止覆盖、重复补丁、ZIP非目标部件保留、日期/文本/公式/错误缓存、CVErr数值拒绝、证据路径、官方H5父链、年度门槛、not_found/withdraw区分、无dimension工作表、公开包扫描。
- Windows本地Python 3.12：6项微信辅助自测，覆盖URL脱敏、坐标/UTF-16、前台输入拒绝、主聊天窗口输入拒绝、非微信进程拒绝、不可见合成控件实际接收中文/表情。测试前后前台窗口未改变。
- Windows本地Python 3.9及桌面Excel：1项显式启用的真实Excel集成测试，独立实例重算临时合成工作簿，数值SUM=5、NA()得到错误字符串#N/A、日期缓存正常序列化，原文件SHA256不变。推荐环境仍为Python3.10+。
- 公开发布包扫描：未发现真实token、会话URL、个人绝对路径、工作簿或图片等研究数据。

## 未测试或不作保证

- 没有为封装测试点击真实微信页面；未重新采集任何产品资料。
- 未证明任意小程序/公众号导航不抢焦点。历史经验已在手册明确，动作触发激活必须停止。
- Linux CI配置已提供；发布前未在本机执行Linux系统测试，GitHub运行结果以仓库Actions为准。
- 没有真实工作簿通用插行迁移器；新增行是Agent按具体模板实现并验证的步骤，不支持用已有单元格补丁工具偷换。
- 没有自动证明引用内容真实、来源官方或保险解释正确；这些仍需研究Agent阅读核验。
- 包扫描是辅助规则，不能取代发布前人工审阅。

## 复验

```powershell
python -X utf8 scripts/test_workflow.py
python -X utf8 scripts/wechat/test_control.py
$env:HMB_TEST_EXCEL='1'
python -X utf8 scripts/test_recalculate.py
Remove-Item Env:HMB_TEST_EXCEL
```

在skill目录运行上面命令，或为脚本提供绝对路径。无Excel/pywin32或未设置环境变量时，集成测试会明确skip，不计为通过真实重算。
