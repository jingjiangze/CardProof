# CardProof

[中文](#中文) | [English](#english)

CardProof 是一个本地运行的 AI 印前核稿工具，面向名片、卡片、小幅面印刷品以及由 CDR/CorelDRAW 导出的 JPG、PNG、截图或 PDF。它帮助设计、客服和印前人员在交付前快速检查文字差异、漏改、误删元素和常见印前风险。

> CardProof 不替代人工终审。它适合做第一轮或复核辅助，最终印刷前仍建议由熟悉订单和工艺的人确认。

---

## 中文

### 项目定位

CardProof 的目标是把“客户原稿”和“当前设计导出图”放在一起核对，让 AI 先指出明显风险，再由人决定是否修改或向客户确认。

它尤其适合这些场景：

- 名片、胸牌、标签、卡片等小幅面印刷品核稿。
- CDR/CorelDRAW 文件导出 JPG、PNG 或 PDF 后做交付前检查。
- 对比客户确认文字和设计稿中的 OCR 文字。
- 检查上一版确认图和当前导出图之间是否有元素被误删、移动或遮挡。
- 从 WebDAV/本地订单文件夹读取当天修改过的 JPG/JPEG，按订单批量核对。

### 核稿能力

CardProof 会重点提示：

- 错字、漏字、多字、繁简/大小写差异。
- 电话、邮箱、地址、网址、数字、金额、日期、职位等敏感字段错误。
- 标点、空格、公司后缀、英文大小写、符号格式问题。
- Logo、二维码、图标、底纹、边框、背面信息等疑似缺失或变化。
- 文字太靠边、被裁切、太小、对比度低、重叠、二维码不可确认等印前风险。

### 两种使用方式

#### 1. Windows 安装包

从 Releases 下载：

- `CardProof-Setup-v*.exe`：Windows 安装包。
- `CardProof-Portable-v*.zip`：免安装版，解压后运行 `CardProof.exe`。
- `CardProof-Source-v*.zip`：源码包。

最新版本可在这里查看：

https://github.com/jingjiangze/CardProof/releases

#### 2. 本地网页服务

需要 Node.js 18 或更高版本。

```powershell
copy start.local.example.ps1 start.local.ps1
notepad start.local.ps1
.\start.ps1
```

然后打开：

```text
http://localhost:4173
```

也可以直接运行：

```powershell
npm start
```

### 基本工作流

1. 把客户确认文字粘贴到“客户原稿”。
2. 上传当前设计导出的 JPG、PNG、PDF 或截图。
3. 如需比较版本，再上传上一版客户确认图或旧导出图。
4. 点击检查，阅读 `必须修改`、`需要确认`、`印前风险` 等结果。
5. 人工复核 AI 结果，再决定修改设计稿或向客户确认。

### WebDAV / 订单文件夹

CardProof 支持从 WebDAV 或本地目录读取订单图片，适合配合 Alist、NAS、共享盘或自动导出目录使用。

常见流程：

- 按订单号或客户名建立文件夹。
- 设计软件导出 JPG/JPEG 到订单文件夹。
- CardProof 读取今天修改过的图片。
- 左侧按订单聚合，选中订单后只核对该订单文件。

### 配置项

配置可以写在环境变量里，也可以复制 `start.local.example.ps1` 为 `start.local.ps1` 后填写。

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `OPENAI_API_KEY` | AI 核稿所需的 API Key | 空 |
| `OPENAI_MODEL` | 使用的模型 | `gpt-4.1-mini` |
| `OPENAI_BASE_URL` | OpenAI 兼容接口地址 | `https://api.openai.com/v1` |
| `SUB2API_URL` | `OPENAI_BASE_URL` 的备用写法 | 空 |
| `PORT` | 本地网页端口 | `4173` |
| `DAV_URL` | WebDAV 地址 | `http://127.0.0.1:5244/dav` |
| `DAV_USER` | WebDAV 用户名 | 空 |
| `DAV_PASS` | WebDAV 密码 | 空 |
| `MAX_TODAY_FILES` | 一次自动检查的文件数量上限 | `20` |

### 自动构建和发布

本仓库已配置 GitHub Actions：

- 推送 `v*` 标签会自动构建 Release。
- Windows runner 会用 PyInstaller 构建 `CardProof.exe`。
- Inno Setup 会生成 `CardProof-Setup-v*.exe` 安装包。
- Release 同时附带免安装 zip 和源码 zip。

发布新版本示例：

```powershell
git tag v1.0.2
git push origin v1.0.2
```

### 仓库结构

```text
.
├─ public/                    # 网页前端
├─ installer/                 # Inno Setup 安装包脚本
├─ .github/workflows/         # GitHub Actions 自动构建
├─ server.js                  # 本地网页服务和 AI 调用
├─ desktop_app.py             # 桌面版启动入口
├─ desktop_app_impl.pyc       # 桌面版实现组件
├─ CardProof.spec             # PyInstaller 构建配置
├─ requirements-desktop.txt   # 桌面版构建依赖
├─ start.ps1 / start.bat      # 网页服务启动脚本
└─ start.local.example.ps1    # 本地配置示例
```

### 隐私与安全

请不要把这些内容提交到公开仓库：

- `start.local.ps1`
- `.env` 或任何包含 API Key 的配置文件
- `cache/`
- `build/`
- `dist/`
- 客户订单文件、图片、PDF、历史版本、备注文件

本仓库的 `.gitignore` 已默认排除这些内容。历史上如果 API Key 已经出现在文件中，即使后来删除，也建议立即去服务商后台作废并重新生成。

### 常见问题

**可以直接上传 CDR 文件吗？**  
不建议。请先从 CorelDRAW 导出 JPG、PNG 或 PDF，再交给 CardProof 核稿。

**AI 结果一定准确吗？**  
不一定。它适合发现风险和减少漏看，但不能代替人工终审。

**没有 API Key 能用吗？**  
可以打开界面和查看演示结果，但真实 AI 核稿需要配置 API Key。

**为什么 Release 里同时有安装包和免安装包？**  
安装包适合普通用户；免安装包适合临时测试、U 盘携带或不想安装的场景。

---

## English

CardProof is a local AI-assisted prepress proofing tool for business cards, cards, labels, and artwork exported from CDR/CorelDRAW as JPG, PNG, screenshots, or PDF files.

### Highlights

- Compare client copy with exported artwork.
- Detect OCR text differences, typos, missing text, extra text, and numeric mistakes.
- Flag potentially missing logos, QR codes, icons, backgrounds, borders, or back-side content.
- Warn about common prepress risks such as cropped text, tiny text, low contrast, overlap, and edge proximity.
- Read recently modified JPG/JPEG files from local folders or WebDAV order folders.
- Build Windows installers automatically through GitHub Actions.

### Download

Open the Releases page:

https://github.com/jingjiangze/CardProof/releases

Available artifacts:

- `CardProof-Setup-v*.exe`: Windows installer.
- `CardProof-Portable-v*.zip`: portable executable.
- `CardProof-Source-v*.zip`: source package.

### Run the Local Web App

Requires Node.js 18 or later.

```powershell
copy start.local.example.ps1 start.local.ps1
notepad start.local.ps1
.\start.ps1
```

Then open:

```text
http://localhost:4173
```

### Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | API key for AI proofing | empty |
| `OPENAI_MODEL` | Model name | `gpt-4.1-mini` |
| `OPENAI_BASE_URL` | OpenAI-compatible API base URL | `https://api.openai.com/v1` |
| `SUB2API_URL` | Alternative name for `OPENAI_BASE_URL` | empty |
| `PORT` | Local web server port | `4173` |
| `DAV_URL` | WebDAV URL | `http://127.0.0.1:5244/dav` |
| `DAV_USER` | WebDAV username | empty |
| `DAV_PASS` | WebDAV password | empty |
| `MAX_TODAY_FILES` | Max files checked in one batch | `20` |

### Release Automation

Push a version tag to build and publish a new Release:

```powershell
git tag v1.0.2
git push origin v1.0.2
```

The workflow builds:

- Windows installer with Inno Setup.
- Portable executable zip.
- Source zip.

### Security

Do not publish local secrets, cache files, build outputs, or customer artwork. Keep `start.local.ps1`, `.env`, `cache/`, `build/`, `dist/`, and order files private.
