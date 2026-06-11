import http from "node:http";
import https from "node:https";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(__dirname, "public");
const PORT = Number(process.env.PORT || 4173);
const MODEL = process.env.OPENAI_MODEL || "gpt-4.1-mini";
const OPENAI_BASE_URL = process.env.OPENAI_BASE_URL || process.env.SUB2API_URL || "https://api.openai.com/v1";
const DAV_URL = process.env.DAV_URL || "http://127.0.0.1:5244/dav";
const DAV_USER = process.env.DAV_USER || "";
const DAV_PASS = process.env.DAV_PASS || "";
const MAX_TODAY_FILES = Number(process.env.MAX_TODAY_FILES || 20);

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function sendJson(res, status, payload) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 24 * 1024 * 1024) {
      throw new Error("上传内容超过 24MB，请导出较小的 JPG/PNG 后再试。");
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function asInputPart(file) {
  if (!file?.dataUrl) return null;
  if (file.type === "application/pdf") {
    return {
      type: "input_file",
      filename: file.name || "proof.pdf",
      file_data: file.dataUrl,
    };
  }

  return {
    type: "input_image",
    image_url: file.dataUrl,
    detail: "high",
  };
}

function buildPrompt({ sourceText, notes, files }) {
  const fileList = files.map((file, index) => `${index + 1}. ${file.label || file.name || "设计图"}`).join("\n");
  return `
你是严谨的中文名片印前 AI 核稿员。请只基于客户原稿和上传的设计图/PDF判断，不要凭空补全。

任务目标：
1. OCR 识别设计中的所有可见文字。
2. 对照客户原稿，找出错字、漏字、多字、数字错误、标点错误、英文大小写错误、公司后缀遗漏。
3. 检查是否疑似缺少元素，例如 logo、二维码、电话/地址/邮箱图标、背面信息、工艺标注、边框或底纹。
4. 如果上传了“上一版/客户确认版”和“当前导出版”，比较两版是否有元素被误删、移动或遮挡。
5. 检查文字太靠边、被裁切、对比度低、太小、重叠、二维码不可确认等印前风险。

客户原稿：
${sourceText || "未提供客户原稿。请提醒用户：没有客户原稿时，只能做视觉核对，不能确认文字一定正确。"}

补充要求：
${notes || "无"}

上传文件：
${fileList}

请严格输出 JSON，不要输出 Markdown。字段如下：
{
  "summary": "一句话总结整体风险",
  "recognized_text": ["从设计中识别到的文字，逐条列出"],
  "must_fix": [{"title":"问题标题","evidence":"看到的证据","suggestion":"怎么改"}],
  "confirm": [{"title":"需要确认的点","evidence":"看到的证据","suggestion":"建议向客户或印厂确认什么"}],
  "looks_ok": ["看起来正常的项目"],
  "missing_or_changed_elements": [{"title":"疑似缺失或变化","evidence":"看到的证据","suggestion":"怎么复查"}],
  "prepress_risks": [{"title":"印前风险","evidence":"看到的证据","suggestion":"怎么处理"}]
}
`.trim();
}

function todayStart() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function webdavAuthHeader() {
  if (!DAV_USER && !DAV_PASS) return {};
  const token = Buffer.from(`${DAV_USER}:${DAV_PASS}`).toString("base64");
  return { Authorization: `Basic ${token}` };
}

function openAiUrl(relPath) {
  const root = OPENAI_BASE_URL.endsWith("/") ? OPENAI_BASE_URL : `${OPENAI_BASE_URL}/`;
  return new URL(relPath.replace(/^\//, ""), root).toString();
}

function webdavRequest(method, targetUrl, headers = {}, body = null) {
  return new Promise((resolve, reject) => {
    const url = new URL(targetUrl);
    const client = url.protocol === "https:" ? https : http;
    const req = client.request(
      url,
      {
        method,
        headers,
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          resolve({
            statusCode: res.statusCode || 0,
            statusMessage: res.statusMessage || "",
            headers: res.headers,
            body: Buffer.concat(chunks),
          });
        });
      }
    );

    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function davUrlForPath(relPath = "") {
  const root = DAV_URL.endsWith("/") ? DAV_URL : `${DAV_URL}/`;
  return new URL(encodePathSegments(relPath), root).toString();
}

function encodePathSegments(relPath) {
  return relPath
    .split("/")
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

function decodeDavPath(href) {
  try {
    const url = new URL(href, DAV_URL);
    const root = new URL(DAV_URL.endsWith("/") ? DAV_URL : `${DAV_URL}/`);
    let rel = url.pathname;
    if (rel.startsWith(root.pathname)) {
      rel = rel.slice(root.pathname.length);
    }
    rel = rel.replace(/^\/+/, "");
    return decodeURIComponent(rel);
  } catch {
    return href;
  }
}

function xmlUnescape(value) {
  return value
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'");
}

function parsePropfind(xml) {
  const responses = [];
  const blocks = xml.match(/<[^:>]*:response[\s\S]*?<\/[^:>]*:response>/g) || [];
  for (const block of blocks) {
    const href = block.match(/<[^:>]*:href>([\s\S]*?)<\/[^:>]*:href>/)?.[1];
    if (!href) continue;
    const isCollection = /<[^:>]*:collection\s*\/?>/i.test(block);
    const lastModified = block.match(/<[^:>]*:getlastmodified>([\s\S]*?)<\/[^:>]*:getlastmodified>/)?.[1];
    const contentLength = block.match(/<[^:>]*:getcontentlength>([\s\S]*?)<\/[^:>]*:getcontentlength>/)?.[1];
    responses.push({
      href: xmlUnescape(href.trim()),
      isCollection,
      lastModified: lastModified ? new Date(lastModified.trim()) : null,
      size: Number(contentLength || 0),
    });
  }
  return responses;
}

async function davPropfind(relPath = "", depth = 1) {
  const response = await webdavRequest("PROPFIND", davUrlForPath(relPath), {
    ...webdavAuthHeader(),
    Depth: String(depth),
  });

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(`WebDAV 读取失败：${response.statusCode} ${response.statusMessage}`);
  }

  const text = response.body.toString("utf8");
  return parsePropfind(text);
}

async function davStat(relPath = "") {
  const items = await davPropfind(relPath, 0);
  return items[0] || null;
}

async function davListRecursive(relPath = "") {
  const current = relPath;
  const items = await davPropfind(current, 1);
  const rootHref = davUrlForPath(current).replace(/\/?$/, "/");
  const results = [];

  for (const item of items) {
    const itemPath = decodeDavPath(item.href);
    if (!itemPath || item.href.replace(/\/?$/, "/") === rootHref) continue;
    const name = path.posix.basename(itemPath);
    if (!name) continue;

    if (item.isCollection) {
      const children = await davListRecursive(itemPath);
      results.push(...children);
      continue;
    }

    if (!/\.(jpe?g)$/i.test(name)) continue;
    results.push({
      path: itemPath,
      name,
      folder: path.posix.basename(path.posix.dirname(itemPath)),
      relativeFolder: path.posix.dirname(itemPath) === "." ? "" : path.posix.dirname(itemPath),
      modifiedAt: item.lastModified ? item.lastModified.toISOString() : null,
      size: item.size || 0,
    });
  }

  return results;
}

async function findTodayJpgs() {
  const start = todayStart().getTime();
  try {
    await davStat("");
  } catch (error) {
    throw new Error(`无法读取 WebDAV：${error.message}`);
  }

  const found = (await davListRecursive(""))
    .filter((file) => file.modifiedAt && new Date(file.modifiedAt).getTime() >= start)
    .sort((a, b) => new Date(b.modifiedAt) - new Date(a.modifiedAt));

  return found;
}

async function jpgToPayload(file) {
  const response = await webdavRequest("GET", davUrlForPath(file.path), {
    ...webdavAuthHeader(),
  });
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(`下载 WebDAV 文件失败：${file.path}`);
  }
  const buffer = Buffer.from(response.body);
  return {
    name: file.name,
    type: "image/jpeg",
    label: `文件夹：${file.relativeFolder} / 文件：${file.name}`,
    dataUrl: `data:image/jpeg;base64,${buffer.toString("base64")}`,
    folder: file.folder,
    relativeFolder: file.relativeFolder,
    modifiedAt: file.modifiedAt,
  };
}

function groupFilesByOrder(files) {
  const groups = new Map();
  for (const file of files) {
    const key = (file.relativeFolder || file.folder || "root").split(/[\\/]/)[0];
    const current = groups.get(key) || {
      orderId: key,
      folder: file.folder,
      relativeFolder: key,
      fileCount: 0,
      latestModifiedAt: file.modifiedAt,
      totalSize: 0,
      files: [],
    };

    current.fileCount += 1;
    current.totalSize += file.size || 0;
    current.files.push(file);
    if (new Date(file.modifiedAt) > new Date(current.latestModifiedAt)) {
      current.latestModifiedAt = file.modifiedAt;
    }
    groups.set(key, current);
  }

  return Array.from(groups.values())
    .map((order) => ({
      ...order,
      files: order.files.sort((a, b) => new Date(b.modifiedAt) - new Date(a.modifiedAt)),
    }))
    .sort((a, b) => new Date(b.latestModifiedAt) - new Date(a.latestModifiedAt));
}

async function getTodayOrders() {
  const files = await findTodayJpgs();
  return {
    rootDir: DAV_URL,
    orders: groupFilesByOrder(files),
  };
}

function buildFolderPrompt({ notes, files, rootDir }) {
  const fileList = files.map((file, index) => [
    `${index + 1}. 文件夹：${file.relativeFolder || file.folder || "未知文件夹"}`,
    `   文件：${file.name}`,
    `   修改时间：${file.modifiedAt || "未知"}`,
  ].join("\n")).join("\n");

  return `
你是严谨的中文名片印前 AI 核稿员。现在要自动检查一个临时目录中“今天修改过”的 JPG/JPEG 文件。

检查范围：
- 根目录：${rootDir}
- 只检查上传列表中的文件；这些文件都来自今天修改过的 JPG/JPEG。
- 必须按“文件夹名称/文件名”反馈问题，方便设计师定位。
- 文件夹名称通常包含客户名、订单名、款式、成品信息或客户确认文字线索。请把文件夹名称当作核对线索，但不要把它当成绝对完整原稿。

任务目标：
1. OCR 识别每张图中的所有可见文字。
2. 根据文件夹名称判断是否存在明显不一致，例如客户名、公司名、姓名、款式、正反面、数量、工艺或版本信息冲突。
3. 检查文字错字、漏字、数字异常、电话位数异常、邮箱/网址异常。
4. 检查是否疑似误删元素，例如 logo、二维码、电话/地址/邮箱图标、底纹、边框、背面信息。
5. 检查文字太靠边、被裁切、遮挡、低对比度、太小、二维码不可确认等印前风险。
6. 如果不能确定，放入“建议确认”，不要夸大为必须修改。

补充要求：
${notes || "无"}

今天修改过的文件：
${fileList}

请严格输出 JSON，不要输出 Markdown。字段如下：
{
  "summary": "一句话总结整体风险，必须提到检查了多少个今天修改过的文件",
  "recognized_text": ["按 文件夹/文件：识别文字 的格式列出"],
  "must_fix": [{"title":"必须修改的问题，标题中包含文件夹/文件","evidence":"看到的证据","suggestion":"怎么改"}],
  "confirm": [{"title":"需要确认的点，标题中包含文件夹/文件","evidence":"看到的证据","suggestion":"建议向客户或印厂确认什么"}],
  "looks_ok": ["按 文件夹/文件：看起来正常的项目 的格式列出"],
  "missing_or_changed_elements": [{"title":"疑似缺失或变化，标题中包含文件夹/文件","evidence":"看到的证据","suggestion":"怎么复查"}],
  "prepress_risks": [{"title":"印前风险，标题中包含文件夹/文件","evidence":"看到的证据","suggestion":"怎么处理"}]
}
`.trim();
}

async function proofread(payload) {
  const files = Array.isArray(payload.files) ? payload.files : [];
  if (!files.length) {
    throw new Error("请至少上传一张名片 JPG/PNG 截图，或 PDF。");
  }

  if (!process.env.OPENAI_API_KEY) {
    return {
      demo: true,
      summary: "当前还没有配置 OPENAI_API_KEY，所以这是演示结果。配置后即可进行真实 AI 核稿。",
      recognized_text: [],
      must_fix: [
        {
          title: "未连接 OpenAI API",
          evidence: "服务端没有读取到 OPENAI_API_KEY。",
          suggestion: "在启动前设置环境变量 OPENAI_API_KEY，然后重新启动网页服务。",
        },
      ],
      confirm: [
        {
          title: "CDR 需先导出",
          evidence: "AI 接口适合直接读取 JPG/PNG/截图/PDF，不能稳定直接读取 CDR 源文件。",
          suggestion: "从 CorelDRAW 导出客户确认图和当前导出版，再上传核对。",
        },
      ],
      looks_ok: [],
      missing_or_changed_elements: [],
      prepress_risks: [],
    };
  }

  const content = [{ type: "input_text", text: buildPrompt({ ...payload, files }) }];
  for (const file of files) {
    const part = asInputPart(file);
    if (part) content.push(part);
  }

  const response = await fetch(openAiUrl("responses"), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: MODEL,
      input: [{ role: "user", content }],
      text: {
        format: reportJsonFormat(),
      },
    }),
  });

  const data = await response.json();
  if (!response.ok) {
    const message = data?.error?.message || "OpenAI API 请求失败。";
    throw new Error(message);
  }

  const output = data.output_text || data.output?.flatMap((item) => item.content || [])
    .find((item) => item.type === "output_text")?.text;

  try {
    return JSON.parse(output);
  } catch {
    return {
      summary: "AI 已返回结果，但不是标准 JSON，下面保留原文。",
      recognized_text: [],
      must_fix: [],
      confirm: [{ title: "结果格式异常", evidence: output || "空结果", suggestion: "请重新核稿一次。" }],
      looks_ok: [],
      missing_or_changed_elements: [],
      prepress_risks: [],
    };
  }
}

async function proofreadToday(payload = {}) {
  const todayFiles = await findTodayJpgs();
  const selectedOrder = payload.orderId;
  const filtered = selectedOrder
    ? todayFiles.filter((file) => (file.relativeFolder || file.folder || "").split(/[\\/]/)[0] === selectedOrder)
    : todayFiles;
  const selected = filtered.slice(0, MAX_TODAY_FILES);

  if (!selected.length) {
    return {
      summary: selectedOrder
        ? `今天在订单 ${selectedOrder} 中没找到修改过的 JPG/JPEG 文件。`
        : `今天在 WebDAV 中没找到修改过的 JPG/JPEG 文件。`,
      recognized_text: [],
      must_fix: [],
      confirm: [],
      looks_ok: [],
      missing_or_changed_elements: [],
      prepress_risks: [],
      scanned_files: [],
    };
  }

  const files = await Promise.all(selected.map(jpgToPayload));

  if (!process.env.OPENAI_API_KEY) {
    return {
      demo: true,
      summary: `找到 ${files.length} 个今天修改过的 JPG/JPEG，但还没有配置 OPENAI_API_KEY，所以这是演示结果。`,
      recognized_text: files.map((file) => `${file.relativeFolder}/${file.name}：等待接入 API 后识别`),
      must_fix: [
        {
          title: "未连接 OpenAI API",
          evidence: "服务端没有读取到 OPENAI_API_KEY。",
          suggestion: "设置 OPENAI_API_KEY 后重新启动，再点击检查今天修改的 JPG。",
        },
      ],
      confirm: [],
      looks_ok: [],
      missing_or_changed_elements: [],
      prepress_risks: [],
      scanned_files: selected,
    };
  }

  const content = [{ type: "input_text", text: buildFolderPrompt({ ...payload, files, rootDir: DAV_URL }) }];
  for (const file of files) {
    const part = asInputPart(file);
    if (part) content.push(part);
  }

  const response = await fetch(openAiUrl("responses"), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: MODEL,
      input: [{ role: "user", content }],
      text: {
        format: reportJsonFormat(),
      },
    }),
  });

  const data = await response.json();
  if (!response.ok) {
    const message = data?.error?.message || "OpenAI API 请求失败。";
    throw new Error(message);
  }

  const output = data.output_text || data.output?.flatMap((item) => item.content || [])
    .find((item) => item.type === "output_text")?.text;

  try {
    return { ...JSON.parse(output), scanned_files: selected };
  } catch {
    return {
      summary: "AI 已返回结果，但不是标准 JSON，下面保留原文。",
      recognized_text: [],
      must_fix: [],
      confirm: [{ title: "结果格式异常", evidence: output || "空结果", suggestion: "请重新核稿一次。" }],
      looks_ok: [],
      missing_or_changed_elements: [],
      prepress_risks: [],
      scanned_files: selected,
    };
  }
}

function reportJsonFormat() {
  return {
    type: "json_schema",
    name: "business_card_proof_report",
    strict: true,
    schema: {
      type: "object",
      additionalProperties: false,
      properties: {
        summary: { type: "string" },
        recognized_text: { type: "array", items: { type: "string" } },
        must_fix: { type: "array", items: issueSchema() },
        confirm: { type: "array", items: issueSchema() },
        looks_ok: { type: "array", items: { type: "string" } },
        missing_or_changed_elements: { type: "array", items: issueSchema() },
        prepress_risks: { type: "array", items: issueSchema() },
      },
      required: [
        "summary",
        "recognized_text",
        "must_fix",
        "confirm",
        "looks_ok",
        "missing_or_changed_elements",
        "prepress_risks",
      ],
    },
  };
}

function issueSchema() {
  return {
    type: "object",
    additionalProperties: false,
    properties: {
      title: { type: "string" },
      evidence: { type: "string" },
      suggestion: { type: "string" },
    },
    required: ["title", "evidence", "suggestion"],
  };
}

async function serveStatic(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const cleanPath = url.pathname === "/" ? "/index.html" : decodeURIComponent(url.pathname);
  const filePath = path.join(publicDir, cleanPath);

  if (!filePath.startsWith(publicDir)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  try {
    const file = await readFile(filePath);
    const ext = path.extname(filePath);
    res.writeHead(200, { "Content-Type": mimeTypes[ext] || "application/octet-stream" });
    res.end(file);
  } catch {
    res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    res.end("Not found");
  }
}

let isShuttingDown = false;
let server;

server = http.createServer(async (req, res) => {
  try {
    if (req.method === "POST" && req.url === "/api/proofread") {
      const payload = JSON.parse(await readBody(req));
      sendJson(res, 200, await proofread(payload));
      return;
    }

    if (req.method === "POST" && req.url === "/api/proofread-today") {
      const payload = JSON.parse(await readBody(req) || "{}");
      sendJson(res, 200, await proofreadToday(payload));
      return;
    }

    if (req.method === "GET" && req.url === "/api/today-jpgs") {
      sendJson(res, 200, {
        rootDir: DAV_URL,
        files: (await findTodayJpgs()).slice(0, MAX_TODAY_FILES),
      });
      return;
    }

    if (req.method === "GET" && req.url === "/api/orders") {
      sendJson(res, 200, await getTodayOrders());
      return;
    }

    if (req.method === "POST" && req.url === "/api/shutdown") {
      if (isShuttingDown) {
        sendJson(res, 200, { ok: true, shuttingDown: true });
        return;
      }
      isShuttingDown = true;
      sendJson(res, 200, { ok: true, shuttingDown: true });
      setTimeout(() => {
        server.close(() => process.exit(0));
      }, 150);
      return;
    }

    if (req.method === "GET") {
      await serveStatic(req, res);
      return;
    }

    res.writeHead(405);
    res.end("Method not allowed");
  } catch (error) {
    sendJson(res, 400, { error: error.message || "请求失败。" });
  }
});

server.listen(PORT, () => {
  console.log(`AI proofreader is running at http://localhost:${PORT}`);
});
