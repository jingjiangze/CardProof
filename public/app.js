const fileInput = document.querySelector("#fileInput");
const fileList = document.querySelector("#fileList");
const runBtn = document.querySelector("#runBtn");
const todayBtn = document.querySelector("#todayBtn");
const stopBtn = document.querySelector("#stopBtn");
const sourceText = document.querySelector("#sourceText");
const notes = document.querySelector("#notes");
const report = document.querySelector("#report");
const emptyState = document.querySelector("#emptyState");
const statusPill = document.querySelector("#statusPill");
const refreshOrdersBtn = document.querySelector("#refreshOrdersBtn");
const orderSearch = document.querySelector("#orderSearch");
const orderSummary = document.querySelector("#orderSummary");
const orderList = document.querySelector("#orderList");

let files = [];
let orders = [];
let selectedOrderId = "";

loadOrders();

refreshOrdersBtn.addEventListener("click", loadOrders);
orderSearch.addEventListener("input", renderOrders);

fileInput.addEventListener("change", async (event) => {
  const picked = Array.from(event.target.files || []);
  const converted = await Promise.all(picked.map(readFileAsDataUrl));
  files = [...files, ...converted].slice(0, 6);
  renderFiles();
  fileInput.value = "";
});

runBtn.addEventListener("click", async () => {
  if (!files.length) {
    setStatus("请先上传设计图", "warn");
    return;
  }

  runBtn.disabled = true;
  setStatus("正在核稿", "working");
  report.classList.add("hidden");
  emptyState.classList.remove("hidden");

  try {
    const response = await fetch("/api/proofread", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceText: sourceText.value.trim(),
        notes: notes.value.trim(),
        files: files.map((file, index) => ({
          name: file.name,
          type: file.type,
          label: index === 0 ? "当前导出版/设计图" : `参考图 ${index}`,
          dataUrl: file.dataUrl,
        })),
      }),
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "核稿失败。");
    renderReport(data);
    setStatus(data.demo ? "演示结果" : "核稿完成", data.demo ? "warn" : "ok");
  } catch (error) {
    renderReport({
      summary: error.message,
      recognized_text: [],
      must_fix: [{ title: "核稿失败", evidence: error.message, suggestion: "检查 API Key、网络或文件大小后再试。" }],
      confirm: [],
      looks_ok: [],
      missing_or_changed_elements: [],
      prepress_risks: [],
    });
    setStatus("需要处理", "warn");
  } finally {
    runBtn.disabled = false;
  }
});

todayBtn.addEventListener("click", async () => {
  todayBtn.disabled = true;
  runBtn.disabled = true;
  setStatus("正在检查今天 JPG", "working");
  report.classList.add("hidden");
  emptyState.classList.remove("hidden");

  try {
    const response = await fetch("/api/proofread-today", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        notes: notes.value.trim(),
        orderId: selectedOrderId,
      }),
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "自动核稿失败。");
    renderReport(data);
    setStatus(data.demo ? "演示结果" : "目录核稿完成", data.demo ? "warn" : "ok");
  } catch (error) {
    renderReport({
      summary: error.message,
      recognized_text: [],
      must_fix: [{ title: "自动核稿失败", evidence: error.message, suggestion: "检查目录权限、API Key、网络或文件大小后再试。" }],
      confirm: [],
      looks_ok: [],
      missing_or_changed_elements: [],
      prepress_risks: [],
    });
    setStatus("需要处理", "warn");
  } finally {
    todayBtn.disabled = false;
    runBtn.disabled = false;
  }
});

stopBtn.addEventListener("click", async () => {
  stopBtn.disabled = true;
  setStatus("正在停止服务", "working");

  try {
    const response = await fetch("/api/shutdown", { method: "POST" });
    if (!response.ok) throw new Error("停止请求没有成功发送。");
    setStatus("服务正在停止", "warn");
    report.classList.remove("hidden");
    report.innerHTML = "";
    const section = document.createElement("section");
    section.className = "report-section";
    section.innerHTML = '<div class="issue-card warn"><strong>服务正在停止</strong><p>如果窗口还在，过一两秒就会自动退出。</p></div>';
    report.append(section);
  } catch (error) {
    setStatus(error.message, "warn");
  } finally {
    setTimeout(() => {
      stopBtn.disabled = false;
    }, 1000);
  }
});

async function loadOrders() {
  refreshOrdersBtn.disabled = true;
  orderSummary.textContent = "正在读取今天修改过的 JPG...";
  orderList.innerHTML = "";

  try {
    const response = await fetch("/api/orders");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "读取订单失败。");
    orders = data.orders || [];
    if (!selectedOrderId && orders.length) selectedOrderId = orders[0].orderId;
    if (selectedOrderId && !orders.some((order) => order.orderId === selectedOrderId)) {
      selectedOrderId = orders[0]?.orderId || "";
    }
    orderSummary.textContent = `${data.rootDir || "监控目录"}：今天 ${orders.length} 个订单有 JPG 修改`;
    renderOrders();
  } catch (error) {
    orders = [];
    selectedOrderId = "";
    orderSummary.textContent = error.message;
    orderList.innerHTML = `<div class="order-empty">${escapeHtml(error.message)}</div>`;
  } finally {
    refreshOrdersBtn.disabled = false;
  }
}

function renderOrders() {
  const keyword = orderSearch.value.trim().toLowerCase();
  const visible = orders.filter((order) => {
    const haystack = `${order.orderId} ${order.folder} ${order.files?.map((file) => file.name).join(" ")}`.toLowerCase();
    return !keyword || haystack.includes(keyword);
  });

  if (!visible.length) {
    orderList.innerHTML = `<div class="order-empty">没有匹配的订单</div>`;
    return;
  }

  orderList.innerHTML = "";
  visible.forEach((order) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `order-item ${order.orderId === selectedOrderId ? "active" : ""}`;
    button.innerHTML = `
      <strong>${escapeHtml(order.orderId)}</strong>
      <span>${order.fileCount} 张 JPG，最新：${formatDate(order.latestModifiedAt)}</span>
    `;
    button.addEventListener("click", () => {
      selectedOrderId = order.orderId;
      renderOrders();
      setStatus(`已选择：${order.orderId}`, "working");
    });
    orderList.append(button);
  });
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({
      name: file.name,
      size: file.size,
      type: file.type || "application/octet-stream",
      dataUrl: reader.result,
    });
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function renderFiles() {
  fileList.innerHTML = "";
  files.forEach((file, index) => {
    const item = document.createElement("div");
    item.className = "file-item";

    const thumb = document.createElement(file.type.startsWith("image/") ? "img" : "div");
    thumb.className = "file-thumb";
    if (thumb.tagName === "IMG") thumb.src = file.dataUrl;
    if (thumb.tagName !== "IMG") thumb.textContent = "PDF";

    const meta = document.createElement("div");
    meta.className = "file-meta";
    meta.innerHTML = `<strong>${escapeHtml(file.name)}</strong><span>${formatSize(file.size)}</span>`;

    const remove = document.createElement("button");
    remove.className = "ghost-btn";
    remove.type = "button";
    remove.textContent = "移除";
    remove.addEventListener("click", () => {
      files.splice(index, 1);
      renderFiles();
    });

    item.append(thumb, meta, remove);
    fileList.append(item);
  });
}

function renderReport(data) {
  emptyState.classList.add("hidden");
  report.classList.remove("hidden");
  report.innerHTML = "";

  const summary = document.createElement("section");
  summary.className = "report-section";
  summary.innerHTML = `<h3>总览</h3><div class="issue-card ${data.must_fix?.length ? "danger" : "ok"}"><strong>${escapeHtml(data.summary || "已完成核稿")}</strong></div>`;
  report.append(summary);

  addIssueSection("必须修改", data.must_fix, "danger");
  addIssueSection("建议确认", data.confirm, "warn");
  addIssueSection("疑似缺失或变化", data.missing_or_changed_elements, "warn");
  addIssueSection("印前风险", data.prepress_risks, "warn");
  addScannedFiles(data.scanned_files);
  addTextSection("识别到的文字", data.recognized_text);
  addTextSection("看起来正常", data.looks_ok);
}

function addScannedFiles(items = []) {
  if (!items.length) return;
  const lines = items.map((item) => `${item.relativeFolder || item.folder}/${item.name}，修改时间：${formatDate(item.modifiedAt)}`);
  addTextSection("本次检查的文件", lines);
}

function addIssueSection(title, items = [], tone = "warn") {
  if (!items.length) return;
  const section = document.createElement("section");
  section.className = "report-section";
  const list = items.map((item) => `
    <li class="issue-card ${tone}">
      <strong>${escapeHtml(item.title || "未命名问题")}</strong>
      <p>${escapeHtml(item.evidence || "")}</p>
      <p>${escapeHtml(item.suggestion || "")}</p>
    </li>
  `).join("");
  section.innerHTML = `<h3>${title}</h3><ul class="issue-list">${list}</ul>`;
  report.append(section);
}

function addTextSection(title, items = []) {
  if (!items.length) return;
  const section = document.createElement("section");
  section.className = "report-section";
  const list = items.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("");
  section.innerHTML = `<h3>${title}</h3><ul class="text-list">${list}</ul>`;
  report.append(section);
}

function setStatus(text, tone) {
  statusPill.textContent = text;
  statusPill.style.color = tone === "ok" ? "#2e6846" : tone === "warn" ? "#8a5c00" : "#6c6a64";
}

function formatSize(size) {
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value) {
  if (!value) return "未知";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
