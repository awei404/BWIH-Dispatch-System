# BWIH 调度系统

用于司机 Check-in、DMS 任务编号人工确认、发车记录、回货追踪和司机评分的本地桌面应用。

## 主要功能

- 司机、供应商、车辆、Dock 与 Check-in 信息录入
- DMS Excel 上传后，由调度员确认 MT 任务编码与司机的对应关系
- 回货结果、线路错误、迟到与人工扣分记录
- 司机近 30 天评分和任务历史
- 驾照照片本地保存；单张上传上限为 50MB

## 评分规则

- 跑错线路：本次任务 0 分
- 迟到：-45 分
- 回货未完成：-25 分；部分完成：-10 分
- 调度员人工扣分：0–100 分，并记录类型（行为异常／影响操作／其他）与原因

## 下载与运行

请到本仓库的 **Releases** 下载对应系统的独立包：

- macOS Apple Silicon（M1–M4）：解压后双击 `.app`
- Windows 10/11 x64：先完整解压 ZIP，再双击 `BWIH Dispatch.exe`

最终用户不需要安装 Python 或配置网页服务。

## 数据与隐私

应用不会上传业务数据。每位用户的数据仅保存在自己的电脑：

- macOS：`~/Library/Application Support/BWIH Dispatch`
- Windows：`%LOCALAPPDATA%\\BWIH Dispatch`

本公开仓库不包含任何本机司机记录、驾照照片或上传表格。

## 从源代码构建

```bash
python3 -m pip install -r requirements.txt pyinstaller
```

- macOS：运行 `packaging/build_macos.sh`
- Windows：运行 `packaging\\build_windows.bat`

Windows 发布包也会由 GitHub Actions 自动构建。
