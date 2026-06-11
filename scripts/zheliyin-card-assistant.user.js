// ==UserScript==
// @name         折立印名片套版助手
// @namespace    https://github.com/jingjiangze/CardProof
// @version      0.3.0
// @description  在 diy.zheliyin.com 设计器里识别客户名片资料，补齐正反面文字图层并优化排版。
// @author       jingjiangze
// @match        https://diy.zheliyin.com/diyWeb/third/*
// @match        https://diy.zheliyin.com/diyWeb/third/*/*/thirdLoginDiyEdit.do*
// @match        https://diy.zheliyin.com/diyWeb/third/*/*/*/thirdDiyAdd.do*
// @match        https://diy.zheliyin.com/diyWeb/*thirdDiyAdd.do*
// @match        https://diy.zheliyin.com/diyWeb/*thirdLoginDiyEdit.do*
// @match        http://diy.zheliyin.com/diyWeb/third/*
// @match        http://diy.zheliyin.com/diyWeb/third/*/*/thirdLoginDiyEdit.do*
// @match        http://diy.zheliyin.com/diyWeb/third/*/*/*/thirdDiyAdd.do*
// @match        http://diy.zheliyin.com/diyWeb/*thirdDiyAdd.do*
// @match        http://diy.zheliyin.com/diyWeb/*thirdLoginDiyEdit.do*
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_addStyle
// @grant        GM_setClipboard
// @connect      ark.cn-beijing.volces.com
// @connect      raw.githubusercontent.com
// @connect      github.com
// @connect      *
// @updateURL    https://raw.githubusercontent.com/jingjiangze/CardProof/main/scripts/zheliyin-card-assistant.user.js
// @downloadURL  https://raw.githubusercontent.com/jingjiangze/CardProof/main/scripts/zheliyin-card-assistant.user.js
// ==/UserScript==

(function () {
  "use strict";

  const VERSION = "0.3.0";
  const BRIDGE_SOURCE = "zy-card-assistant";
  const PAGE_SOURCE = "zy-card-assistant-page";
  const DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3";
  const DEFAULT_MODEL = "doubao-seed-2-0-mini-260428";
  const UPDATE_URL = "https://raw.githubusercontent.com/jingjiangze/CardProof/main/scripts/zheliyin-card-assistant.user.js";
  const MIN_FONT_SIZE = 14;

  const FIELD_LABELS = {
    company_cn: "中文公司",
    company_en: "英文公司",
    name: "姓名",
    title: "职位",
    phones: "电话",
    wechats: "微信",
    emails: "邮箱",
    websites: "网址",
    addresses: "地址",
    business: "主营业务"
  };

  const state = {
    fields: emptyFields(),
    logs: [],
    busy: false,
    minimized: false
  };

  function emptyFields() {
    return {
      company_cn: "",
      company_en: "",
      name: "",
      title: "",
      phones: [],
      wechats: [],
      emails: [],
      websites: [],
      addresses: [],
      business: []
    };
  }

  function getConfig() {
    return {
      apiKey: GM_getValue("zyArkApiKey", ""),
      baseUrl: GM_getValue("zyArkBaseUrl", DEFAULT_BASE_URL),
      model: GM_getValue("zyArkModel", DEFAULT_MODEL)
    };
  }

  function saveConfig(config) {
    GM_setValue("zyArkApiKey", config.apiKey || "");
    GM_setValue("zyArkBaseUrl", config.baseUrl || DEFAULT_BASE_URL);
    GM_setValue("zyArkModel", config.model || DEFAULT_MODEL);
  }

  function addStyles() {
    GM_addStyle(`
      #zy-card-assistant {
        position: fixed;
        top: 80px;
        right: 14px;
        width: 390px;
        max-height: calc(100vh - 96px);
        z-index: 2147483647;
        background: #ffffff;
        color: #172033;
        border: 1px solid #d7dce5;
        border-radius: 8px;
        box-shadow: 0 14px 36px rgba(16, 24, 40, .20);
        font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
        overflow: hidden;
      }
      #zy-card-assistant * { box-sizing: border-box; letter-spacing: 0; }
      #zy-card-assistant.zy-min { width: 226px; }
      #zy-card-assistant.zy-min .zy-body { display: none; }
      .zy-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 10px 12px;
        background: #1f6feb;
        color: #fff;
        cursor: move;
        user-select: none;
      }
      .zy-title { font-weight: 700; font-size: 14px; }
      .zy-head-actions { display: flex; gap: 6px; }
      .zy-icon-btn {
        border: 0;
        background: rgba(255,255,255,.18);
        color: #fff;
        border-radius: 5px;
        height: 26px;
        min-width: 28px;
        cursor: pointer;
      }
      .zy-body {
        padding: 12px;
        display: grid;
        gap: 10px;
        max-height: calc(100vh - 146px);
        overflow: auto;
      }
      .zy-row { display: grid; gap: 5px; }
      .zy-label {
        font-size: 12px;
        color: #475467;
        font-weight: 700;
      }
      .zy-input, .zy-textarea {
        width: 100%;
        border: 1px solid #d7dce5;
        border-radius: 6px;
        padding: 8px;
        color: #172033;
        background: #fff;
        font: 12px/1.45 "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      }
      .zy-textarea { min-height: 112px; resize: vertical; }
      .zy-actions {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 6px;
      }
      .zy-actions.two {
        grid-template-columns: 1.2fr 1fr;
      }
      .zy-btn {
        border: 0;
        border-radius: 6px;
        min-height: 34px;
        background: #1f6feb;
        color: white;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
      }
      .zy-btn.secondary { background: #eef2f7; color: #1f2937; }
      .zy-btn:disabled { opacity: .55; cursor: wait; }
      .zy-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px;
      }
      .zy-field { display: grid; gap: 4px; }
      .zy-field span {
        font-size: 11px;
        color: #667085;
      }
      .zy-field input, .zy-field textarea {
        width: 100%;
        border: 1px solid #d7dce5;
        border-radius: 5px;
        padding: 6px;
        font-size: 12px;
        font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      }
      .zy-field textarea { min-height: 54px; resize: vertical; }
      .zy-status {
        min-height: 20px;
        font-size: 12px;
        color: #667085;
        white-space: pre-wrap;
      }
      .zy-divider {
        height: 1px;
        background: #e4e7ec;
        margin: 2px 0;
      }
      .zy-url {
        display: grid;
        gap: 3px;
        padding: 7px;
        border: 1px solid #e4e7ec;
        border-radius: 6px;
        background: #fbfcfe;
        color: #667085;
        font-size: 11px;
        line-height: 1.35;
        word-break: break-all;
      }
    `);
  }

  function renderPanel() {
    addStyles();
    installPageBridge();

    const old = document.getElementById("zy-card-assistant");
    if (old) old.remove();

    const config = getConfig();
    const panel = document.createElement("section");
    panel.id = "zy-card-assistant";
    if (state.minimized) panel.classList.add("zy-min");
    applySavedPanelPosition(panel);
    panel.innerHTML = `
      <div class="zy-head">
        <div class="zy-title">名片套版助手</div>
        <div class="zy-head-actions">
          <button class="zy-icon-btn" id="zy-min-btn" title="收起/展开">${state.minimized ? "□" : "-"}</button>
          <button class="zy-icon-btn" id="zy-close-btn" title="关闭">×</button>
        </div>
      </div>
      <div class="zy-body">
        <div class="zy-url">
          <div>当前网址：${escapeHtml(location.href)}</div>
          <div>版本：${VERSION}，匹配范围：diy.zheliyin.com/diyWeb/third/*</div>
        </div>
        <div class="zy-row">
          <label class="zy-label" for="zy-api-key">豆包 API Key</label>
          <input class="zy-input" id="zy-api-key" type="password" value="${escapeHtml(config.apiKey)}" placeholder="粘贴 ark 开头的 API Key">
        </div>
        <div class="zy-row">
          <label class="zy-label" for="zy-model">模型</label>
          <input class="zy-input" id="zy-model" value="${escapeHtml(config.model)}">
        </div>
        <div class="zy-row">
          <label class="zy-label" for="zy-raw">客户文字</label>
          <textarea class="zy-textarea" id="zy-raw" placeholder="把微信、表格或客户发来的名片资料粘贴到这里。点“追加信息”会叠加到现有字段，不会清空原字段。"></textarea>
        </div>
        <div class="zy-actions two">
          <button class="zy-btn" id="zy-parse-apply">识别并填正面</button>
          <button class="zy-btn secondary" id="zy-apply-back">填背面</button>
        </div>
        <div class="zy-actions">
          <button class="zy-btn secondary" id="zy-append">追加信息</button>
          <button class="zy-btn secondary" id="zy-parse-only">仅识别</button>
          <button class="zy-btn secondary" id="zy-copy-fields">复制字段</button>
        </div>
        <div class="zy-divider"></div>
        <div class="zy-grid" id="zy-fields">${renderFieldInputs(state.fields)}</div>
        <div class="zy-actions two">
          <button class="zy-btn" id="zy-apply-front">填正面</button>
          <button class="zy-btn secondary" id="zy-clear">清空</button>
        </div>
        <div class="zy-status" id="zy-status">${escapeHtml(state.logs.join("\n"))}</div>
      </div>
    `;
    document.body.appendChild(panel);
    bindPanelEvents(panel);
    makePanelDraggable(panel);
    checkForUpdateSoon();
  }

  function renderFieldInputs(fields) {
    return Object.keys(FIELD_LABELS).map((key) => {
      const value = Array.isArray(fields[key]) ? fields[key].join("\n") : (fields[key] || "");
      const multiline = ["phones", "wechats", "emails", "websites", "addresses", "business"].includes(key);
      if (multiline) {
        return `<label class="zy-field"><span>${FIELD_LABELS[key]}</span><textarea data-field="${key}">${escapeHtml(value)}</textarea></label>`;
      }
      return `<label class="zy-field"><span>${FIELD_LABELS[key]}</span><input data-field="${key}" value="${escapeHtml(value)}"></label>`;
    }).join("");
  }

  function bindPanelEvents(panel) {
    panel.querySelector("#zy-min-btn").addEventListener("click", () => {
      state.minimized = !state.minimized;
      renderPanel();
    });
    panel.querySelector("#zy-close-btn").addEventListener("click", () => panel.remove());
    panel.querySelector("#zy-parse-apply").addEventListener("click", () => parseFields({ append: false, applySide: "front" }));
    panel.querySelector("#zy-append").addEventListener("click", () => parseFields({ append: true, applySide: null }));
    panel.querySelector("#zy-parse-only").addEventListener("click", () => parseFields({ append: false, applySide: null }));
    panel.querySelector("#zy-apply-front").addEventListener("click", () => {
      readFieldsFromPanel();
      applyFieldsToPage(state.fields, "front");
    });
    panel.querySelector("#zy-apply-back").addEventListener("click", () => {
      readFieldsFromPanel();
      applyFieldsToPage(state.fields, "back");
    });
    panel.querySelector("#zy-copy-fields").addEventListener("click", () => {
      readFieldsFromPanel();
      GM_setClipboard(formatFields(state.fields));
      setStatus("字段已复制。");
    });
    panel.querySelector("#zy-clear").addEventListener("click", () => {
      state.fields = emptyFields();
      state.logs = [];
      renderPanel();
    });
  }

  function applySavedPanelPosition(panel) {
    const left = Number(GM_getValue("zyPanelLeft", NaN));
    const top = Number(GM_getValue("zyPanelTop", NaN));
    if (Number.isFinite(left) && Number.isFinite(top)) {
      panel.style.left = clamp(left, 6, window.innerWidth - 80) + "px";
      panel.style.top = clamp(top, 6, window.innerHeight - 44) + "px";
      panel.style.right = "auto";
    }
  }

  function makePanelDraggable(panel) {
    const head = panel.querySelector(".zy-head");
    if (!head) return;
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let startLeft = 0;
    let startTop = 0;

    head.addEventListener("pointerdown", (event) => {
      if (event.target && event.target.closest && event.target.closest("button")) return;
      dragging = true;
      const rect = panel.getBoundingClientRect();
      startX = event.clientX;
      startY = event.clientY;
      startLeft = rect.left;
      startTop = rect.top;
      panel.style.left = rect.left + "px";
      panel.style.top = rect.top + "px";
      panel.style.right = "auto";
      head.setPointerCapture(event.pointerId);
      event.preventDefault();
    });

    head.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const nextLeft = clamp(startLeft + event.clientX - startX, 6, window.innerWidth - Math.min(panel.offsetWidth, window.innerWidth - 12));
      const nextTop = clamp(startTop + event.clientY - startY, 6, window.innerHeight - 44);
      panel.style.left = nextLeft + "px";
      panel.style.top = nextTop + "px";
    });

    head.addEventListener("pointerup", (event) => {
      if (!dragging) return;
      dragging = false;
      const rect = panel.getBoundingClientRect();
      GM_setValue("zyPanelLeft", Math.round(rect.left));
      GM_setValue("zyPanelTop", Math.round(rect.top));
      try { head.releasePointerCapture(event.pointerId); } catch (_error) {}
    });
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  async function parseFields(options) {
    const panel = document.getElementById("zy-card-assistant");
    const rawText = panel.querySelector("#zy-raw").value.trim();
    const config = {
      apiKey: panel.querySelector("#zy-api-key").value.trim(),
      baseUrl: DEFAULT_BASE_URL,
      model: panel.querySelector("#zy-model").value.trim() || DEFAULT_MODEL
    };
    saveConfig(config);

    if (!rawText) {
      setStatus("请先粘贴客户文字。");
      return;
    }

    setBusy(true);
    try {
      const ruleResult = parseByRules(rawText);
      const aiResult = config.apiKey ? await parseByDoubao(rawText, ruleResult, config) : {};
      const parsed = mergeFields(ruleResult, aiResult, rawText);
      state.fields = options.append ? mergeTwoFields(state.fields, parsed) : parsed;
      renderFieldArea();
      setStatus(options.append ? "追加完成。" : "识别完成。");
      if (options.applySide) applyFieldsToPage(state.fields, options.applySide);
    } catch (error) {
      const parsed = normalizeFields(parseByRules(rawText));
      state.fields = options.append ? mergeTwoFields(state.fields, parsed) : parsed;
      renderFieldArea();
      setStatus("豆包识别失败，已使用本地规则识别。\n" + String(error && error.message ? error.message : error));
    } finally {
      setBusy(false);
    }
  }

  function renderFieldArea() {
    const box = document.getElementById("zy-fields");
    if (box) box.innerHTML = renderFieldInputs(state.fields);
  }

  function setBusy(busy) {
    state.busy = busy;
    document.querySelectorAll("#zy-card-assistant button").forEach((btn) => {
      if (!btn.classList.contains("zy-icon-btn")) btn.disabled = busy;
    });
  }

  function setStatus(text) {
    state.logs = String(text || "").split("\n").filter(Boolean).slice(-8);
    const node = document.getElementById("zy-status");
    if (node) node.textContent = state.logs.join("\n");
  }

  function readFieldsFromPanel() {
    const fields = emptyFields();
    document.querySelectorAll("#zy-fields [data-field]").forEach((node) => {
      const key = node.getAttribute("data-field");
      if (Array.isArray(fields[key])) fields[key] = splitList(node.value);
      else fields[key] = clean(node.value);
    });
    state.fields = normalizeFields(fields);
  }

  function parseByRules(raw) {
    const text = String(raw || "").replace(/\r/g, "\n");
    const lines = text.split(/\n+/).map(clean).filter(Boolean);
    const result = emptyFields();

    result.phones = unique(Array.from(text.matchAll(/(?:\+?86[-\s]?)?(1[3-9]\d{9})/g)).map((match) => match[1]));
    result.emails = unique(Array.from(text.matchAll(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi)).map((match) => match[0]));

    const websiteMatches = Array.from(text.matchAll(/(?:https?:\/\/)?(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+\S*/gi));
    result.websites = unique(websiteMatches.map((match) => {
      const before = text[Math.max(0, match.index - 1)] || "";
      const value = match[0].replace(/[，。,;；]+$/, "");
      return before === "@" || result.emails.some((email) => email.includes(value)) ? "" : value;
    }).filter(Boolean));

    const wechatLines = lines.filter((line) => /微信|wechat|wx/i.test(line));
    result.wechats = unique(wechatLines.map((line) => clean(line.replace(/^(微信|wechat|wx)[:：]?\s*/i, ""))).filter(Boolean));

    const titleWords = /(销售经理|客户经理|业务经理|总经理|经理|主管|总监|工程师|负责人|Sales Manager|Manager|Director|Engineer)/i;
    for (const line of lines) {
      if (!result.company_cn && /公司|集团|科技|贸易|实业|有限公司/.test(line) && /[\u4e00-\u9fa5]/.test(line)) result.company_cn = line;
      if (!result.company_en && /\b(CO\.?|COMPANY|LTD\.?|LIMITED|TRADING|TECH|TECHNOLOGY)\b/i.test(line) && /[A-Z]/i.test(line)) result.company_en = line;
      if (!result.title && titleWords.test(line)) result.title = line.match(titleWords)[0];
      if (/(省|市|区|县|镇|街道|路|大厦|楼|室|座|号)/.test(line) && line.length >= 8) result.addresses.push(line);
    }

    const compactLines = lines.filter((line) => ![result.company_cn, result.company_en].includes(line) && !result.addresses.includes(line));
    for (const line of compactLines) {
      if (!result.name && /^[\u4e00-\u9fa5]{2,4}$/.test(line) && !titleWords.test(line)) result.name = line;
      if (!result.name) {
        const nameTitle = line.match(/^([\u4e00-\u9fa5]{2,4})\s+(.+)$/);
        if (nameTitle && titleWords.test(nameTitle[2])) {
          result.name = nameTitle[1];
          result.title = result.title || nameTitle[2];
        }
      }
    }

    const businessStart = lines.findIndex((line) => /主营|业务|经营|产品|服务器|DDR|芯片|进出口|贸易/.test(line));
    if (businessStart >= 0) {
      result.business = lines.slice(businessStart)
        .join("；")
        .split(/；|;|、|，|,/)
        .map((item) => clean(item.replace(/^主营业务[:：]?/, "")))
        .filter(Boolean);
    }
    result.addresses = unique(result.addresses);
    return normalizeFields(result);
  }

  function parseByDoubao(rawText, ruleResult, config) {
    const prompt = [
      "你是名片资料字段识别助手。请从客户文字中提取字段，只输出严格 JSON，不要 Markdown。",
      "JSON 字段固定为：company_cn, company_en, name, title, phones, wechats, emails, websites, addresses, business。",
      "phones, wechats, emails, websites, addresses, business 都必须是字符串数组。没有的信息填空字符串或空数组。",
      "不要虚构信息；不要把公司名、姓名、电话、地址、网址重复放进 business。",
      "",
      "本地规则初步结果：",
      JSON.stringify(ruleResult, null, 2),
      "",
      "客户文字：",
      rawText
    ].join("\n");

    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: "POST",
        url: config.baseUrl.replace(/\/+$/, "") + "/chat/completions",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + config.apiKey
        },
        data: JSON.stringify({
          model: config.model,
          temperature: 0,
          response_format: { type: "json_object" },
          messages: [
            { role: "system", content: "你是字段抽取程序。必须只返回可被 JSON.parse 解析的 JSON 对象，禁止解释、Markdown、示例和虚构信息。" },
            { role: "user", content: prompt }
          ]
        }),
        timeout: 30000,
        onload: (response) => {
          try {
            if (response.status < 200 || response.status >= 300) {
              reject(new Error("API HTTP " + response.status + ": " + response.responseText.slice(0, 220)));
              return;
            }
            const body = JSON.parse(response.responseText);
            const content = body && body.choices && body.choices[0] && body.choices[0].message && body.choices[0].message.content;
            resolve(parseJsonFromText(content || "{}"));
          } catch (error) {
            reject(error);
          }
        },
        onerror: () => reject(new Error("API 请求失败")),
        ontimeout: () => reject(new Error("API 请求超时"))
      });
    });
  }

  function parseJsonFromText(text) {
    const raw = String(text || "").trim().replace(/^```json\s*/i, "").replace(/^```\s*/i, "").replace(/```$/i, "").trim();
    try {
      return JSON.parse(raw);
    } catch (_error) {
      const match = raw.match(/\{[\s\S]*\}/);
      return match ? JSON.parse(match[0]) : {};
    }
  }

  function normalizeFields(input) {
    const source = input || {};
    const out = emptyFields();
    ["company_cn", "company_en", "name", "title"].forEach((key) => {
      out[key] = clean(source[key]);
    });
    ["phones", "wechats", "emails", "websites", "addresses", "business"].forEach((key) => {
      out[key] = normalizeArrayField(source[key] || source[key.replace(/s$/, "")]);
    });
    out.business = out.business.filter((item) => {
      return item && item !== out.company_cn && item !== out.company_en && item !== out.name &&
        !out.phones.includes(item) && !out.websites.includes(item) && !out.addresses.includes(item);
    });
    return out;
  }

  function normalizeArrayField(value) {
    if (Array.isArray(value)) return unique(value.map(clean).filter(Boolean));
    return splitList(value);
  }

  function splitList(value) {
    return unique(String(value || "")
      .split(/\n|；|;/)
      .map(clean)
      .filter(Boolean));
  }

  function mergeFields(ruleResult, aiResult, rawText) {
    const rule = normalizeFields(ruleResult || {});
    const ai = normalizeFields(aiResult || {});
    const raw = String(rawText || "");
    const out = normalizeFields(rule);
    ["company_cn", "company_en", "name", "title"].forEach((key) => {
      if (!ai[key]) return;
      if (!out[key] || (rawIncludes(raw, ai[key]) && !rawIncludes(raw, out[key]))) out[key] = ai[key];
    });
    ["phones", "wechats", "emails", "websites", "addresses"].forEach((key) => {
      out[key] = unique([].concat(out[key] || [], (ai[key] || []).filter((item) => rawIncludes(raw, item))));
    });
    const business = [].concat(out.business || []);
    (ai.business || []).forEach((item) => {
      if (!business.length || rawIncludes(raw, item)) business.push(item);
    });
    out.business = unique(business);
    return normalizeFields(out);
  }

  function mergeTwoFields(base, extra) {
    const out = normalizeFields(base || {});
    const next = normalizeFields(extra || {});
    ["company_cn", "company_en", "name", "title"].forEach((key) => {
      if (next[key]) out[key] = out[key] ? out[key] : next[key];
    });
    ["phones", "wechats", "emails", "websites", "addresses", "business"].forEach((key) => {
      out[key] = unique([].concat(out[key] || [], next[key] || []));
    });
    return normalizeFields(out);
  }

  function rawIncludes(raw, value) {
    const needle = clean(value).replace(/\s+/g, "");
    const haystack = String(raw || "").replace(/\s+/g, "");
    return needle && haystack.includes(needle);
  }

  function applyFieldsToPage(fields, side) {
    window.postMessage({ source: BRIDGE_SOURCE, type: "apply", fields: normalizeFields(fields), side: side || "front" }, location.origin);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || !event.data || event.data.source !== PAGE_SOURCE) return;
    if (event.data.type === "applyResult") {
      if (event.data.ok) {
        setStatus("已处理 " + event.data.applied.length + " 个文字图层。\n" + event.data.applied.join("\n"));
      } else {
        setStatus(event.data.message || "没有拿到画布对象。请先打开模板，等待加载完成后再试。");
      }
    }
  });

  function installPageBridge() {
    if (document.getElementById("zy-card-assistant-page-bridge")) return;
    const script = document.createElement("script");
    script.id = "zy-card-assistant-page-bridge";
    script.textContent = "(" + pageBridge.toString() + ")();";
    (document.head || document.documentElement).appendChild(script);
    script.remove();
  }

  function pageBridge() {
    const BRIDGE_SOURCE_IN_PAGE = "zy-card-assistant";
    const PAGE_SOURCE_IN_PAGE = "zy-card-assistant-page";
    const MIN_FONT_SIZE_IN_PAGE = 14;

    window.addEventListener("message", function (event) {
      if (event.source !== window || !event.data || event.data.source !== BRIDGE_SOURCE_IN_PAGE) return;
      if (event.data.type === "apply") withCanvas(event.data.side || "front", function (canvas, side) {
        const result = applyAndLayout(canvas, event.data.fields || {}, side);
        post("applyResult", result);
      }, function (message) {
        post("applyResult", { ok: false, message: message, applied: [] });
      });
    });

    function post(type, payload) {
      window.postMessage(Object.assign({ source: PAGE_SOURCE_IN_PAGE, type: type }, payload), location.origin);
    }

    function withCanvas(side, done, fail) {
      const canvas = findCanvasForSide(side);
      if (canvas) {
        done(canvas, side || "front");
        return;
      }
      fail("未找到设计器画布，请等待模板加载完成。");
    }

    function findCanvasForSide(side) {
      const CanvasObjVO = getLoadedModule("CanvasObjVO") || window.CanvasObjVO;
      const total = CanvasObjVO && CanvasObjVO.totalCanvasArray;
      const index = side === "back" ? 1 : 0;
      if (Array.isArray(total) && total[index]) {
        const selected = unwrapCanvas(total[index]) || findCanvasIn(total[index]);
        if (selected) return selected;
      }
      if (Array.isArray(total) && total.length) {
        const fallback = unwrapCanvas(total[0]) || findCanvasIn(total[0]);
        if (fallback) return fallback;
      }
      const CurrentCanvas = getLoadedModule("CurrentCanvas") || window.CurrentCanvas;
      if (CurrentCanvas && CurrentCanvas.getCurrentCanvas && side !== "back") {
        const current = CurrentCanvas.getCurrentCanvas();
        const currentCanvas = unwrapCanvas(current) || findCanvasIn(current);
        if (currentCanvas) return currentCanvas;
      }
      return findCanvasFromGlobals();
    }

    function getLoadedModule(name) {
      const req = window.requirejs || window.require;
      const context = req && req.s && req.s.contexts && req.s.contexts._;
      if (context && context.defined && context.defined[name]) return context.defined[name];
      return null;
    }

    function findCanvasFromGlobals() {
      const candidates = [];
      ["canvas", "currentCanvas", "canvasDiy", "diyCanvas", "CanvasDiy", "CanvasObjVO"].forEach(function (key) {
        if (window[key]) candidates.push(window[key]);
      });
      const loaded = getLoadedModule("CanvasObjVO");
      if (loaded) candidates.push(loaded);
      for (let i = 0; i < candidates.length; i += 1) {
        const found = findCanvasIn(candidates[i]);
        if (found) return found;
      }
      return null;
    }

    function findCanvasIn(root) {
      const seen = [];
      function walk(value, depth) {
        if (!value || depth > 4) return null;
        if (seen.indexOf(value) >= 0) return null;
        seen.push(value);
        const unwrapped = unwrapCanvas(value);
        if (unwrapped) return unwrapped;
        if (Array.isArray(value)) {
          for (let i = 0; i < value.length; i += 1) {
            const found = walk(value[i], depth + 1);
            if (found) return found;
          }
          return null;
        }
        if (typeof value === "object") {
          const keys = ["canvas", "_canvas", "fabricCanvas", "lowerCanvas", "currentCanvas", "stage", "totalCanvasArray"];
          for (let i = 0; i < keys.length; i += 1) {
            const found = walk(value[keys[i]], depth + 1);
            if (found) return found;
          }
        }
        return null;
      }
      return walk(root, 0);
    }

    function unwrapCanvas(value) {
      if (!value) return null;
      if (typeof value.getObjects === "function" && (typeof value.renderAll === "function" || typeof value.requestRenderAll === "function")) return value;
      if (value.canvas && typeof value.canvas.getObjects === "function") return value.canvas;
      return null;
    }

    function getTextObjects(canvas) {
      return canvas.getObjects().filter(isTextObject);
    }

    function isTextObject(obj) {
      if (!obj) return false;
      const type = String(obj.type || "").toLowerCase();
      if (["text", "textbox", "i-text", "curvedtext"].indexOf(type) >= 0) return true;
      if (obj.text != null && typeof obj.set === "function") return true;
      const mediaType = String(obj.mediaMediaType || (obj.media && obj.media.mediaType) || "").toLowerCase();
      return mediaType.indexOf("text") >= 0;
    }

    function applyAndLayout(canvas, fields, side) {
      const items = side === "back" ? buildBackItems(fields) : buildFrontItems(fields);
      cleanupKnownText(canvas, items);
      const objects = getTextObjects(canvas);
      const used = [];
      const applied = [];
      const base = getBase(canvas, side);
      items.forEach(function (item, index) {
        const target = pickObject(objects, used, item);
        const box = target || createTextObject(canvas, item);
        if (!box) return;
        used.push(box);
        setObjectText(box, item.text);
        styleTextObject(box, item, base, index, side);
        box.zyAutoLayout = true;
        box.zyFieldKey = item.key;
        applied.push(item.label + " -> " + item.text);
      });
      removeUnusedAutoLayout(canvas, items);
      if (canvas.requestRenderAll) canvas.requestRenderAll();
      else if (canvas.renderAll) canvas.renderAll();
      return applied.length ? { ok: true, applied: applied } : { ok: false, message: "没有可填入的字段。", applied: [] };
    }

    function buildFrontItems(fields) {
      const items = [];
      addItem(items, "company_cn", "中文公司", fields.company_cn);
      addItem(items, "company_en", "英文公司", fields.company_en);
      addItem(items, "name_title", "姓名职位", [fields.name, fields.title].filter(Boolean).join("  "));
      (fields.phones || []).forEach(function (value, index) { addItem(items, "phone" + (index + 1), "电话" + (index + 1), "电话" + (index + 1) + "：" + value); });
      (fields.wechats || []).forEach(function (value, index) { addItem(items, "wechat" + (index + 1), "微信" + (index + 1), "微信" + (index + 1) + "：" + value); });
      (fields.emails || []).forEach(function (value, index) { addItem(items, "email" + (index + 1), "邮箱" + (index + 1), "邮箱" + (index + 1) + "：" + value); });
      (fields.websites || []).forEach(function (value, index) { addItem(items, "website" + (index + 1), "网址" + (index + 1), "网址" + (index + 1) + "：" + value); });
      (fields.addresses || []).forEach(function (value, index) { addItem(items, "address" + (index + 1), "地址" + (index + 1), "地址" + (index + 1) + "：" + value); });
      return items;
    }

    function buildBackItems(fields) {
      const items = [];
      if (fields.business && fields.business.length) addItem(items, "business", "主营业务", "主营业务\n" + fields.business.join("\n"));
      addItem(items, "company_cn", "中文公司", fields.company_cn);
      (fields.websites || []).forEach(function (value, index) { addItem(items, "website" + (index + 1), "网址" + (index + 1), value); });
      return items;
    }

    function addItem(items, key, label, text) {
      const value = String(text || "").trim();
      if (value) items.push({ key: key, label: label, text: value });
    }

    function cleanupKnownText(canvas, items) {
      const wanted = items.map(function (item) { return item.key; });
      getTextObjects(canvas).forEach(function (obj) {
        const key = obj.zyFieldKey || guessKnownFieldKey(String(obj.text || ""));
        if (!key || wanted.indexOf(key) >= 0) return;
        if (obj.zyAutoLayout || isPlaceholderText(obj.text)) canvas.remove(obj);
      });
    }

    function removeUnusedAutoLayout(canvas, items) {
      const wanted = items.map(function (item) { return item.key; });
      getTextObjects(canvas).forEach(function (obj) {
        if (obj.zyAutoLayout && wanted.indexOf(obj.zyFieldKey) < 0) canvas.remove(obj);
      });
    }

    function isPlaceholderText(text) {
      return /姓名|职位|电话|手机|微信|邮箱|网址|地址|主营|业务|Name|Title|Tel|Phone|Mail|Web|Address/i.test(String(text || ""));
    }

    function guessKnownFieldKey(text) {
      if (/电话|手机|Tel|Phone|Mobile/i.test(text)) return "phone1";
      if (/微信|Wechat|WX/i.test(text)) return "wechat1";
      if (/邮箱|Mail|Email|@/i.test(text)) return "email1";
      if (/网址|网站|Web|www\.|https?:\/\//i.test(text)) return "website1";
      if (/地址|Address|省|市|区|路|街道|大厦|楼|室/i.test(text)) return "address1";
      if (/主营|业务|Business|DDR|芯片|服务器/i.test(text)) return "business";
      return "";
    }

    function pickObject(objects, used, item) {
      let best = null;
      let bestScore = -9999;
      objects.forEach(function (obj, index) {
        if (used.indexOf(obj) >= 0) return;
        const text = String(obj.text || "").trim();
        const score = scoreObject(text, item, index, objects.length);
        if (score > bestScore) {
          best = obj;
          bestScore = score;
        }
      });
      return bestScore >= 40 ? best : null;
    }

    function scoreObject(text, item, index, total) {
      const key = item.key;
      let score = 0;
      if (text === item.text) score += 100;
      if (item.label && text.indexOf(item.label.replace(/\d+$/, "")) >= 0) score += 80;
      if (key.indexOf("phone") === 0 && /电话|手机|tel|phone|mobile/i.test(text)) score += 80;
      if (key.indexOf("wechat") === 0 && /微信|wechat|wx/i.test(text)) score += 80;
      if (key.indexOf("email") === 0 && /邮箱|mail|@/i.test(text)) score += 80;
      if (key.indexOf("website") === 0 && /网址|网站|web|www\.|https?:\/\//i.test(text)) score += 80;
      if (key.indexOf("address") === 0 && /地址|address|省|市|区|路|街道|大厦|楼|室/i.test(text)) score += 80;
      if (key === "company_cn" && /公司|集团|科技|贸易|有限公司/.test(text)) score += 80;
      if (key === "company_en" && /\b(co|ltd|limited|company|trading|technology)\b/i.test(text)) score += 80;
      if (key === "name_title" && (/姓名|职位/.test(text) || /^[\u4e00-\u9fa5]{2,4}$/.test(text))) score += 80;
      score += total ? ((total - index) / total) * 5 : 0;
      return score;
    }

    function createTextObject(canvas, item) {
      const fabric = window.fabric || (canvas.constructor && canvas.constructor.fabric);
      if (!fabric || !fabric.Textbox) return null;
      const obj = new fabric.Textbox(item.text, {
        left: 0,
        top: 0,
        width: 240,
        fontSize: MIN_FONT_SIZE_IN_PAGE,
        fill: "#1f2937",
        fontFamily: "Microsoft YaHei, Arial",
        editable: true
      });
      canvas.add(obj);
      return obj;
    }

    function setObjectText(obj, value) {
      const text = String(value || "");
      if (typeof obj.setText === "function") obj.setText(text);
      else if (typeof obj.set === "function") obj.set("text", text);
      else obj.text = text;
      obj.text = text;
      obj.dirty = true;
      if (typeof obj.initDimensions === "function") obj.initDimensions();
    }

    function styleTextObject(obj, item, base, index, side) {
      const isCompany = item.key === "company_cn";
      const isEnglishCompany = item.key === "company_en";
      const isName = item.key === "name_title";
      const isBackBusiness = side === "back" && item.key === "business";
      const fontSize = Math.max(MIN_FONT_SIZE_IN_PAGE, isCompany ? 20 : isName ? 18 : isBackBusiness ? 16 : isEnglishCompany ? 14 : 14);
      const lineHeight = isBackBusiness ? 1.45 : 1.25;
      const top = base.top + getOffset(index, item, side);
      const options = {
        left: base.left,
        top: top,
        width: base.width,
        fontSize: fontSize,
        lineHeight: lineHeight,
        fill: isCompany || isName ? "#111827" : "#374151",
        fontFamily: "Microsoft YaHei, Arial",
        fontWeight: isCompany || isName || isBackBusiness ? "bold" : "normal"
      };
      if (typeof obj.set === "function") obj.set(options);
      else Object.assign(obj, options);
      if (typeof obj.setCoords === "function") obj.setCoords();
    }

    function getBase(canvas, side) {
      const width = Number(canvas.width || (canvas.getWidth && canvas.getWidth()) || 360);
      const height = Number(canvas.height || (canvas.getHeight && canvas.getHeight()) || 216);
      return side === "back"
        ? { left: width * 0.12, top: height * 0.18, width: width * 0.76 }
        : { left: width * 0.10, top: height * 0.12, width: width * 0.80 };
    }

    function getOffset(index, item, side) {
      if (side === "back") return index === 0 ? 0 : 116 + (index - 1) * 24;
      if (item.key === "company_cn") return 0;
      if (item.key === "company_en") return 30;
      if (item.key === "name_title") return 64;
      return 92 + Math.max(0, index - 3) * 24;
    }
  }

  function checkForUpdateSoon() {
    const today = new Date().toISOString().slice(0, 10);
    if (GM_getValue("zyUpdateCheckedDate", "") === today) return;
    GM_setValue("zyUpdateCheckedDate", today);
    setTimeout(checkForUpdate, 1500);
  }

  function checkForUpdate() {
    GM_xmlhttpRequest({
      method: "GET",
      url: UPDATE_URL + "?t=" + Date.now(),
      timeout: 15000,
      onload: (response) => {
        if (response.status < 200 || response.status >= 300) return;
        const match = String(response.responseText || "").match(/@version\s+([^\s]+)/);
        if (!match) return;
        const latest = match[1];
        if (compareVersion(latest, VERSION) > 0) {
          setStatus("发现脚本新版 " + latest + "，当前 " + VERSION + "。\n请到 GitHub 或脚本猫更新。");
          alert("折立印名片套版助手发现新版 " + latest + "，当前版本 " + VERSION + "。");
        }
      }
    });
  }

  function compareVersion(a, b) {
    const pa = String(a).split(".").map(Number);
    const pb = String(b).split(".").map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
      const da = pa[i] || 0;
      const db = pb[i] || 0;
      if (da > db) return 1;
      if (da < db) return -1;
    }
    return 0;
  }

  function formatFields(fields) {
    return Object.keys(FIELD_LABELS).map((key) => {
      const value = Array.isArray(fields[key]) ? fields[key].join("；") : (fields[key] || "");
      return FIELD_LABELS[key] + "：" + value;
    }).filter((line) => !/：$/.test(line)).join("\n");
  }

  function unique(list) {
    return Array.from(new Set((list || []).map(clean).filter(Boolean)));
  }

  function clean(value) {
    return String(value == null ? "" : value).replace(/\s+/g, " ").replace(/^[：:，,；;\-\s]+|[：:，,；;\-\s]+$/g, "").trim();
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderPanel);
  } else {
    renderPanel();
  }

  console.info("折立印名片套版助手已加载", VERSION);
})();
