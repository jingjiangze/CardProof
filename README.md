# CardProof

[中文](#中文) | [English](#english)

---

## 中文

CardProof 是一个本地运行的 AI 印前核稿工具，用于对名片、JPG、PNG、截图或 PDF 进行文字与版面风险检查。

### 适合检查

- 客户原稿和设计稿中的文字差异
- 错字、漏字、多字、数字或标点错误
- Logo、二维码、电话、地址、邮箱图标等疑似缺失元素
- 文字过小、太靠边、被裁切、对比度低、重叠等印前风险
- WebDAV 中按订单读取当天修改过的 JPG/JPEG 文件

### 使用方式

1. 复制 `start.local.example.ps1` 为 `start.local.ps1`。
2. 填入你的 `OPENAI_API_KEY`，按需配置 WebDAV。
3. 启动本地服务：

```powershell
.\start.ps1
```

4. 打开：

```text
http://localhost:4173
```

### 配置项

- `OPENAI_API_KEY`：调用 AI 核稿所需的 API Key。
- `OPENAI_MODEL`：模型名，默认 `gpt-4.1-mini`。
- `OPENAI_BASE_URL`：OpenAI 兼容接口地址，默认 `https://api.openai.com/v1`。
- `PORT`：本地服务端口，默认 `4173`。
- `DAV_URL`：WebDAV 地址，默认 `http://127.0.0.1:5244/dav`。
- `DAV_USER` / `DAV_PASS`：WebDAV 用户名和密码，默认不发送认证信息。
- `MAX_TODAY_FILES`：一次自动检查的文件数量上限。

### 安全说明

不要把 `start.local.ps1`、`.env`、`cache/`、`build/`、`dist/` 或任何客户文件上传到公开仓库。本项目的 `.gitignore` 已默认排除这些内容。

---

## English

CardProof is a local AI-assisted prepress proofing tool for checking business cards, JPG, PNG, screenshots, and PDF files.

### What It Checks

- Text differences between client copy and exported artwork
- Typos, missing characters, extra characters, numbers, and punctuation issues
- Potentially missing elements such as logos, QR codes, phone/address/email icons
- Prepress risks such as tiny text, low contrast, cropped text, edge proximity, and overlap
- JPG/JPEG files modified today from a WebDAV order folder

### Usage

1. Copy `start.local.example.ps1` to `start.local.ps1`.
2. Fill in your `OPENAI_API_KEY` and optional WebDAV settings.
3. Start the local server:

```powershell
.\start.ps1
```

4. Open:

```text
http://localhost:4173
```

### Configuration

- `OPENAI_API_KEY`: API key used for AI proofing.
- `OPENAI_MODEL`: Model name. Defaults to `gpt-4.1-mini`.
- `OPENAI_BASE_URL`: OpenAI-compatible API base URL. Defaults to `https://api.openai.com/v1`.
- `PORT`: Local server port. Defaults to `4173`.
- `DAV_URL`: WebDAV URL. Defaults to `http://127.0.0.1:5244/dav`.
- `DAV_USER` / `DAV_PASS`: WebDAV username and password. Authentication is omitted by default.
- `MAX_TODAY_FILES`: Maximum number of files checked in one automatic run.

### Security Notes

Do not publish `start.local.ps1`, `.env`, `cache/`, `build/`, `dist/`, or any customer files. The included `.gitignore` excludes these by default.
