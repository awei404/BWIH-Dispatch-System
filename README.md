# BWIH 调度系统

司机 Check-in、DMS 任务确认、发车记录、回货追踪和司机评分的本地应用。

## 下载与运行

到 **Releases** 下载对应系统的独立包：

**macOS (Apple Silicon M1–M4)**
1. 下载并解压 ZIP
2. 双击 `BWIH调度系统.app`
3. 浏览器会自动打开系统页面
4. 首次打开若提示"无法确认开发者"：按住 Control 点击 → 选择"打开" → 再次确认

**Windows 10/11 x64**
1. 下载并完整解压 ZIP 到一个文件夹
2. 双击 `BWIH Dispatch.exe`
3. 浏览器会自动打开系统页面
4. 首次运行若弹出防火墙提示，选择"允许"

不需要安装 Python，不需要安装其他运行环境。

## 主要功能

- 司机、供应商、车辆、Dock 与 Check-in 信息录入
- DMS Excel 上传后，由调度员确认 MT 任务编码与司机的对应关系
- 回货结果、线路错误、迟到与人工扣分记录
- 司机近 30 天评分和任务历史
- 驾照照片本地保存

## 评分规则

- 跑错线路：本次任务 0 分
- 迟到：-45 分
- 回货未完成：-25 分；部分完成：-10 分
- 调度员人工扣分：0–100 分，并记录类型与原因

## 数据与隐私

所有数据保存在本地，不会上传：
- macOS：`~/Library/Application Support/BWIH Dispatch`
- Windows：`%LOCALAPPDATA%\BWIH Dispatch`

## 从源代码构建

```bash
pip install -r requirements.txt pyinstaller
```

- macOS：`./packaging/build_macos.sh`
- Windows：`packaging\build_windows.bat`

Windows 版也会由 GitHub Actions 自动构建（推送 `v*` tag 或手动触发）。
