const state = {
  caseId: createId(),
  messages: [],
  facts: {},
  lastQuery: "",
  loading: false,
  meta: null,
  llm: loadStoredLlm(),
  history: loadHistory(),
  currentInteractionId: null,
};

const elements = {
  conversation: document.querySelector("#conversation"),
  queryForm: document.querySelector("#queryForm"),
  queryInput: document.querySelector("#queryInput"),
  submitButton: document.querySelector("#submitButton"),
  composerNote: document.querySelector("#composerNote"),
  resetButton: document.querySelector("#resetButton"),
  roleInput: document.querySelector("#roleInput"),
  eventDateInput: document.querySelector("#eventDateInput"),
  workLocationInput: document.querySelector("#workLocationInput"),
  addFactButton: document.querySelector("#addFactButton"),
  customFacts: document.querySelector("#customFacts"),
  sourceBadge: document.querySelector("#sourceBadge"),
  modelButton: document.querySelector("#modelButton"),
  modelButtonLabel: document.querySelector("#modelButtonLabel"),
  modelDialog: document.querySelector("#modelDialog"),
  modelForm: document.querySelector("#modelForm"),
  closeModelDialog: document.querySelector("#closeModelDialog"),
  llmBaseUrlInput: document.querySelector("#llmBaseUrlInput"),
  llmModelInput: document.querySelector("#llmModelInput"),
  llmApiKeyInput: document.querySelector("#llmApiKeyInput"),
  llmTemperatureInput: document.querySelector("#llmTemperatureInput"),
  temperatureOutput: document.querySelector("#temperatureOutput"),
  rememberKeyInput: document.querySelector("#rememberKeyInput"),
  modelTestResult: document.querySelector("#modelTestResult"),
  disableModelButton: document.querySelector("#disableModelButton"),
  testModelButton: document.querySelector("#testModelButton"),
  resolveButton: document.querySelector("#resolveButton"),
  historyButton: document.querySelector("#historyButton"),
  historyCount: document.querySelector("#historyCount"),
  historyDialog: document.querySelector("#historyDialog"),
  closeHistoryDialog: document.querySelector("#closeHistoryDialog"),
  historyList: document.querySelector("#historyList"),
  clearHistoryButton: document.querySelector("#clearHistoryButton"),
  metaJurisdiction: document.querySelector("#metaJurisdiction"),
  metaSources: document.querySelector("#metaSources"),
  metaProvisions: document.querySelector("#metaProvisions"),
  testWarning: document.querySelector("#testWarning"),
  toast: document.querySelector("#toast"),
};

const statusLabels = {
  answered: "已找到來源",
  need_more_facts: "需要補充事實",
  insufficient_sources: "來源不足",
  escalate_human: "需要真人處理",
  out_of_scope: "超出支援法域",
};

const factLabels = {
  event_date: "事件日期",
  work_location: "工作地點",
  wage_period: "工資期間",
  work_schedule: "工作安排",
  termination_type: "終止方式",
  injury_status: "受傷及申報情況",
  foreign_employee_status: "外地僱員許可",
  issue_description: "爭議類型",
};

document.addEventListener("DOMContentLoaded", initialize);

async function initialize() {
  addFactRow();
  bindEvents();
  updateModelButton();
  updateHistoryButton();
  refreshIcons();
  await loadMeta();
  render();
}

function bindEvents() {
  elements.queryForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = elements.queryInput.value.trim();
    if (!query) {
      return;
    }
    const roleChanged =
      state.messages.length > 0 &&
      elements.roleInput.dataset.lockedRole &&
      elements.roleInput.value !== elements.roleInput.dataset.lockedRole;
    if (roleChanged) {
      resetCase(false);
    }
    elements.queryInput.value = "";
    elements.roleInput.dataset.lockedRole = elements.roleInput.value;
    ask(query, { appendUser: true });
  });

  elements.queryInput.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key === "Enter") {
      event.preventDefault();
      elements.queryForm.requestSubmit();
    }
  });

  elements.queryInput.addEventListener("input", () => {
    elements.queryInput.style.height = "auto";
    elements.queryInput.style.height = `${Math.min(
      elements.queryInput.scrollHeight,
      180,
    )}px`;
  });

  elements.resetButton.addEventListener("click", () =>
    startNewCase("已建立新案件。"),
  );
  elements.addFactButton.addEventListener("click", () => addFactRow());
  elements.modelButton.addEventListener("click", openModelDialog);
  elements.closeModelDialog.addEventListener("click", () =>
    elements.modelDialog.close(),
  );
  elements.llmTemperatureInput.addEventListener("input", () => {
    elements.temperatureOutput.textContent =
      elements.llmTemperatureInput.value;
  });
  elements.modelForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveModelSettings();
  });
  elements.disableModelButton.addEventListener("click", disableModel);
  elements.testModelButton.addEventListener("click", testModelConnection);
  elements.modelDialog.addEventListener("click", (event) => {
    if (event.target === elements.modelDialog) {
      elements.modelDialog.close();
    }
  });
  elements.resolveButton.addEventListener("click", resolveCurrentIssue);
  elements.historyButton.addEventListener("click", openHistoryDialog);
  elements.closeHistoryDialog.addEventListener("click", () =>
    elements.historyDialog.close(),
  );
  elements.clearHistoryButton.addEventListener("click", clearHistory);
  elements.historyDialog.addEventListener("click", (event) => {
    if (event.target === elements.historyDialog) {
      elements.historyDialog.close();
    }
  });
  elements.historyList.addEventListener("click", handleHistoryAction);

  elements.customFacts.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-fact]");
    if (!button) {
      return;
    }
    const row = button.closest(".fact-row");
    row.remove();
    if (!elements.customFacts.children.length) {
      addFactRow();
    }
  });

  document.querySelectorAll("[data-query]").forEach((button) => {
    button.addEventListener("click", () => {
      const query = button.dataset.query;
      elements.queryInput.value = query;
      elements.queryInput.dispatchEvent(new Event("input"));
      elements.queryForm.requestSubmit();
    });
  });

  elements.conversation.addEventListener("submit", (event) => {
    const form = event.target.closest(".missing-form");
    if (!form) {
      return;
    }
    event.preventDefault();
    const additions = {};
    form.querySelectorAll("[data-missing-code]").forEach((input) => {
      const value = input.value.trim();
      if (value) {
        additions[input.dataset.missingCode] = value;
      }
    });
    Object.assign(state.facts, additions);
    ask(state.lastQuery, { appendUser: false, allowIncomplete: false });
  });

  elements.conversation.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-trace]");
    if (!button) {
      return;
    }
    const traceId = button.dataset.copyTrace;
    try {
      await navigator.clipboard.writeText(traceId);
      showToast("Trace ID 已複製。");
    } catch {
      showToast(`Trace ID：${traceId}`);
    }
  });
}

async function loadMeta() {
  try {
    const response = await fetch("/api/meta");
    if (!response.ok) {
      throw new Error("無法讀取來源資料。");
    }
    state.meta = await response.json();
    elements.metaJurisdiction.textContent = state.meta.jurisdiction;
    elements.metaSources.textContent = state.meta.approved_source_count;
    elements.metaProvisions.textContent = state.meta.provision_count;
    elements.sourceBadge.textContent = state.meta.test_only
      ? "測試核准"
      : state.meta.approved_source_count > 0
        ? "來源已載入"
        : "沒有來源";
    elements.sourceBadge.className = `status-pill ${
      state.meta.test_only ? "test" : "ready"
    }`;
    elements.testWarning.classList.toggle("hidden", !state.meta.test_only);
  } catch (error) {
    elements.sourceBadge.textContent = "來源讀取失敗";
    showToast(error.message);
  }
}

function loadStoredLlm() {
  const fallback = {
    enabled: false,
    base_url: "https://api.openai.com/v1",
    model: "gpt-5-mini",
    provider: "auto",
    api_key: "",
    temperature: 0.1,
    json_mode: true,
    remember: false,
  };
  try {
    const stored = window.sessionStorage.getItem("laborlaw-agent-llm");
    if (!stored) {
      return fallback;
    }
    const parsed = JSON.parse(stored);
    return {
      ...fallback,
      ...parsed,
      enabled: Boolean(parsed.enabled),
      remember: true,
    };
  } catch {
    return fallback;
  }
}

function openModelDialog() {
  elements.llmBaseUrlInput.value = state.llm.base_url;
  elements.llmModelInput.value = state.llm.model;
  elements.llmApiKeyInput.value = state.llm.api_key;
  elements.llmTemperatureInput.value = String(state.llm.temperature);
  elements.temperatureOutput.textContent = String(state.llm.temperature);
  elements.rememberKeyInput.checked = state.llm.remember;
  elements.modelTestResult.classList.add("hidden");
  elements.modelTestResult.classList.remove("error");
  if (!elements.modelDialog.open) {
    elements.modelDialog.showModal();
  }
}

function saveModelSettings() {
  const config = modelConfigFromForm();
  if (!config.base_url || !config.model) {
    showToast("請填寫 Base URL 與模型名稱。");
    return;
  }
  if (!config.api_key && !isLocalModelUrl(config.base_url)) {
    showToast("遠端模型 API 必須填寫 API Key。");
    return;
  }
  state.llm = {
    ...config,
    enabled: true,
    remember: elements.rememberKeyInput.checked,
  };
  persistLlmSettings();
  updateModelButton();
  elements.modelDialog.close();
  showToast(`AI 模型已啟用：${state.llm.model}`);
}

function disableModel() {
  state.llm = {
    ...state.llm,
    enabled: false,
    api_key: "",
    remember: false,
  };
  try {
    window.sessionStorage.removeItem("laborlaw-agent-llm");
  } catch {
    // 瀏覽器停用 sessionStorage 時仍可停用本次記憶體設定。
  }
  updateModelButton();
  elements.modelDialog.close();
  showToast("已切換至規則模式。");
}

async function testModelConnection() {
  const config = {
    ...modelConfigFromForm(),
    enabled: true,
  };
  if (!config.api_key && !isLocalModelUrl(config.base_url)) {
    setModelTestResult("遠端模型 API 必須填寫 API Key。", true);
    return;
  }
  elements.testModelButton.disabled = true;
  setModelTestResult("正在測試模型連線...", false, true);
  try {
    const response = await fetch("/api/llm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ llm: config }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "模型連線失敗。");
    }
    setModelTestResult(`連線成功：${payload.model}`, false);
  } catch (error) {
    setModelTestResult(error.message || "模型連線失敗。", true);
  } finally {
    elements.testModelButton.disabled = false;
  }
}

function modelConfigFromForm() {
  const baseUrl = elements.llmBaseUrlInput.value.trim();
  return {
    base_url: baseUrl,
    provider: isDeepSeekUrl(baseUrl) ? "deepseek" : "auto",
    model: elements.llmModelInput.value.trim(),
    api_key: elements.llmApiKeyInput.value.trim(),
    temperature: Number(elements.llmTemperatureInput.value),
    json_mode: true,
  };
}

function currentLlmPayload() {
  if (!state.llm.enabled) {
    return null;
  }
  return {
    enabled: true,
    base_url: state.llm.base_url,
    provider: state.llm.provider || "auto",
    model: state.llm.model,
    api_key: state.llm.api_key,
    temperature: state.llm.temperature,
    json_mode: state.llm.json_mode,
  };
}

function persistLlmSettings() {
  try {
    if (state.llm.remember) {
      window.sessionStorage.setItem(
        "laborlaw-agent-llm",
        JSON.stringify(currentLlmPayload()),
      );
    } else {
      window.sessionStorage.removeItem("laborlaw-agent-llm");
    }
  } catch {
    // 不阻止模型在目前頁面記憶體中使用。
  }
}

function updateModelButton() {
  elements.modelButton.classList.toggle("enabled", state.llm.enabled);
  elements.modelButtonLabel.textContent = state.llm.enabled
    ? state.llm.model || "AI 已啟用"
    : "規則模式";
  elements.modelButton.dataset.tooltip = state.llm.enabled
    ? `AI 模型：${state.llm.model}`
    : "設定 AI 模型";
}

function setModelTestResult(message, isError, loading = false) {
  elements.modelTestResult.textContent = message;
  elements.modelTestResult.classList.remove("hidden");
  elements.modelTestResult.classList.toggle("error", isError);
  elements.testModelButton.disabled = loading;
}

function isLocalModelUrl(value) {
  try {
    const url = new URL(value);
    return ["127.0.0.1", "localhost", "::1"].includes(url.hostname);
  } catch {
    return false;
  }
}

function isDeepSeekUrl(value) {
  try {
    return new URL(value).hostname.endsWith("deepseek.com");
  } catch {
    return false;
  }
}

async function resolveCurrentIssue() {
  await startNewCase("問題已標記為解決，已清除目前上下文。");
}

async function startNewCase(message) {
  const previousCaseId = state.caseId;
  try {
    await fetch("/api/case/close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case_id: previousCaseId }),
    });
  } catch {
    // 即使後端暫時不可用，前端仍會切換到新的 case ID，避免繼續混用舊上下文。
  }
  resetCase(false);
  showToast(message);
}

function loadHistory() {
  try {
    const stored = window.localStorage.getItem("laborlaw-agent-history-v1");
    if (!stored) {
      return [];
    }
    const parsed = JSON.parse(stored);
    return Array.isArray(parsed) ? parsed.slice(0, 30) : [];
  } catch {
    return [];
  }
}

function persistHistory() {
  try {
    window.localStorage.setItem(
      "laborlaw-agent-history-v1",
      JSON.stringify(state.history.slice(0, 30)),
    );
  } catch {
    // History is optional; an unavailable localStorage must not block the agent.
  }
}

function recordHistory({ query, answer, llm, interactionId }) {
  if (!answer) {
    return;
  }
  const entry = {
    id: interactionId,
    timestamp: new Date().toISOString(),
    query,
    status: answer.status,
    partial: Boolean(answer.partial),
    summary: answer.summary || "",
    trace_id: answer.trace_id || "",
    model: llm?.model || null,
    role: answer.role,
    articles: (answer.applicable_law || []).map((item) => ({
      article: item.article,
      title: item.law_title,
      page_start: item.page_start || null,
    })),
  };
  state.history = [
    entry,
    ...state.history.filter((item) => item.id !== interactionId),
  ].slice(0, 30);
  persistHistory();
  updateHistoryButton();
}

function updateHistoryButton() {
  const count = state.history.length;
  elements.historyCount.textContent = String(count);
  elements.historyCount.classList.toggle("hidden", count === 0);
  elements.historyButton.dataset.tooltip =
    count > 0 ? `歷史紀錄（${count}）` : "歷史紀錄";
}

function openHistoryDialog() {
  renderHistory();
  if (!elements.historyDialog.open) {
    elements.historyDialog.showModal();
  }
}

function renderHistory() {
  elements.historyList.replaceChildren();
  if (!state.history.length) {
    elements.historyList.append(
      element("div", "history-empty", "目前沒有歷史紀錄。"),
    );
    return;
  }
  state.history.forEach((entry) => {
    elements.historyList.append(renderHistoryItem(entry));
  });
  refreshIcons(elements.historyList);
}

function renderHistoryItem(entry) {
  const item = element("article", "history-item");
  const header = element("div", "history-item-header");
  const content = element("div");
  const status = element(
    "span",
    `status-badge ${entry.partial ? "partial" : entry.status}`,
    entry.partial ? "有限分析" : statusLabels[entry.status] || entry.status,
  );
  const question = element("h3", "", entry.query);
  const meta = element(
    "p",
    "",
    `${formatHistoryTime(entry.timestamp)} · ${entry.trace_id}`,
  );
  content.append(status, question, meta);
  const deleteButton = iconButton("trash-2", "刪除此紀錄");
  deleteButton.dataset.deleteHistory = entry.id;
  header.append(content, deleteButton);
  item.append(header);

  if (entry.summary) {
    item.append(element("p", "", entry.summary));
  }
  if (entry.articles?.length) {
    const laws = element("div", "history-laws");
    entry.articles.forEach((law) => {
      laws.append(element("span", "", law.article));
    });
    item.append(laws);
  }
  const actions = element("div", "history-item-actions");
  const reuse = element("button", "secondary-button");
  reuse.type = "button";
  reuse.dataset.reuseHistory = entry.id;
  reuse.append(iconNode("rotate-ccw"), document.createTextNode("重用問題"));
  actions.append(reuse);
  item.append(actions);
  return item;
}

function handleHistoryAction(event) {
  const reuseButton = event.target.closest("[data-reuse-history]");
  if (reuseButton) {
    const entry = state.history.find(
      (item) => item.id === reuseButton.dataset.reuseHistory,
    );
    if (entry) {
      elements.queryInput.value = entry.query;
      elements.queryInput.dispatchEvent(new Event("input"));
      elements.historyDialog.close();
      elements.queryInput.focus();
    }
    return;
  }
  const deleteButton = event.target.closest("[data-delete-history]");
  if (deleteButton) {
    state.history = state.history.filter(
      (item) => item.id !== deleteButton.dataset.deleteHistory,
    );
    persistHistory();
    updateHistoryButton();
    renderHistory();
  }
}

function clearHistory() {
  if (!state.history.length) {
    return;
  }
  if (!window.confirm("確定要清除全部歷史紀錄？")) {
    return;
  }
  state.history = [];
  persistHistory();
  updateHistoryButton();
  renderHistory();
}

function formatHistoryTime(value) {
  try {
    return new Date(value).toLocaleString("zh-MO", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

async function ask(query, { appendUser, allowIncomplete = false }) {
  if (state.loading || !query) {
    return;
  }
  state.lastQuery = query;
  if (appendUser) {
    state.currentInteractionId = createId();
    state.messages.push({ role: "user", text: query });
  }
  state.loading = true;
  setBusy(true);
  render();

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        role: elements.roleInput.value,
        case_id: state.caseId,
        facts: buildFacts(),
        llm: currentLlmPayload(),
        allow_incomplete: allowIncomplete,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Agent 執行失敗。");
    }
    if (!appendUser && state.messages.at(-1)?.role === "assistant") {
      state.messages.pop();
    }
    state.messages.push({
      role: "assistant",
      answer: payload.answer,
      llm: payload.llm,
    });
    recordHistory({
      query,
      answer: payload.answer,
      llm: payload.llm,
      interactionId: state.currentInteractionId || createId(),
    });
  } catch (error) {
    state.messages.push({
      role: "error",
      text: error.message || "無法連接 Agent。",
    });
    showToast(error.message || "無法連接 Agent。");
  } finally {
    state.loading = false;
    setBusy(false);
    render();
  }
}

function buildFacts() {
  const facts = { ...state.facts };
  const eventDate = elements.eventDateInput.value.trim();
  const workLocation = elements.workLocationInput.value.trim();
  if (eventDate) {
    facts.event_date = eventDate;
  }
  if (workLocation) {
    facts.work_location = workLocation;
  }
  elements.customFacts.querySelectorAll(".fact-row").forEach((row) => {
    const key = row.querySelector("[data-fact-key]").value.trim();
    const value = row.querySelector("[data-fact-value]").value.trim();
    if (key && value) {
      facts[key] = value;
    }
  });
  return facts;
}

function render() {
  elements.conversation.replaceChildren();

  if (!state.messages.length && !state.loading) {
    elements.conversation.append(renderEmptyState());
  } else {
    for (const message of state.messages) {
      if (message.role === "user") {
        elements.conversation.append(renderUserMessage(message.text));
      } else if (message.role === "assistant") {
        elements.conversation.append(
          renderAnswer(message.answer, message.llm),
        );
      } else {
        elements.conversation.append(renderError(message.text));
      }
    }
    if (state.loading) {
      elements.conversation.append(renderLoading());
    }
  }
  scrollToLatest();
  refreshIcons();
}

function renderEmptyState() {
  const container = element("div", "empty-state");
  const icon = element("div", "empty-icon");
  icon.append(iconNode("message-square-text"));
  const heading = element("h2", "", "描述你的澳門勞動法問題");
  const actions = element("div", "quick-actions");
  [
    ["banknote", "工資支付期限", "工資最遲應在何時支付？"],
    ["clock-3", "正常工作時間", "正常工作時間每日不得超過多少小時？"],
    ["calendar-check-2", "每週休息日", "每週休息日有什麼規定？"],
  ].forEach(([iconName, label, query]) => {
    const button = element("button");
    button.type = "button";
    button.append(iconNode(iconName), document.createTextNode(label));
    button.addEventListener("click", () => {
      elements.queryInput.value = query;
      elements.queryForm.requestSubmit();
    });
    actions.append(button);
  });
  container.append(icon, heading, actions);
  return container;
}

function renderUserMessage(text) {
  const message = element("div", "message user");
  const bubble = element("div", "user-bubble", text);
  message.append(bubble);
  return message;
}

function renderLoading() {
  const message = element("div", "message assistant");
  const wrapper = element("div", "answer");
  const loading = element("div", "loading-state");
  loading.append(
    element("div", "loading-line"),
    element("div", "loading-line"),
    element("div", "loading-line"),
  );
  wrapper.append(loading);
  message.append(wrapper);
  return message;
}

function renderError(text) {
  const message = element("div", "message");
  message.append(element("div", "error-message", text));
  return message;
}

function renderAnswer(answer, llmInfo = null) {
  const message = element("div", "message assistant");
  const article = element("article", "answer");

  const header = element("header", "answer-header");
  const headingWrap = element("div", "answer-heading");
  const badge = element(
    "span",
    `status-badge ${answer.partial ? "partial" : answer.status}`,
    answer.partial
      ? "有限分析"
      : statusLabels[answer.status] || answer.status,
  );
  const heading = element("h2", "", answer.summary || "Agent 回答");
  const meta = element("div", "answer-meta");
  meta.append(
    element("span", "", `角色：${roleLabel(answer.role)}`),
    element("span", "", `狀態：${answer.status}`),
  );
  if (llmInfo?.enabled) {
    const mode = llmInfo.analysis_used
      ? "AI 分析"
      : llmInfo.plan_used
        ? "AI 檢索規劃"
        : "AI 已設定";
    meta.append(
      element(
        "span",
        "",
        `模型：${llmInfo.model || "未指定"} · ${mode}`,
      ),
    );
  }
  headingWrap.append(badge, heading, meta);

  const trace = element("div", "trace-actions");
  trace.append(element("code", "trace-code", answer.trace_id || ""));
  const copyButton = iconButton("copy", "複製 Trace ID");
  copyButton.dataset.copyTrace = answer.trace_id || "";
  trace.append(copyButton);
  header.append(headingWrap, trace);
  article.append(header);

  if (answer.escalation?.required) {
    article.append(
      alertBlock(
        "user-round-check",
        answer.escalation.reasons?.join("；") ||
          "此問題需要澳門法律專業人士處理。",
        true,
      ),
    );
  }

  if (answer.missing_facts?.length) {
    article.append(
      renderMissingFacts(answer.missing_facts, Boolean(answer.partial)),
    );
  }

  if (answer.known_facts?.length) {
    article.append(renderKnownFacts(answer.known_facts));
  }

  if (answer.applicable_law?.length) {
    article.append(renderLawSources(answer.applicable_law));
  }

  const lawContents = new Set(
    (answer.applicable_law || []).map((item) => item.content),
  );
  const distinctAnalysis = (answer.analysis || []).filter(
    (item) => !lawContents.has(item),
  );
  if (distinctAnalysis.length) {
    article.append(
      renderListBlock("scan-text", "分析", distinctAnalysis, true),
    );
  }

  if (answer.options?.length) {
    article.append(renderListBlock("route", "可行選項", answer.options));
  }

  if (answer.next_steps?.length) {
    article.append(
      renderListBlock("arrow-right", "下一步", answer.next_steps),
    );
  }

  if (answer.risks?.length) {
    const block = element("section", "answer-block");
    const title = sectionTitle("triangle-alert", "風險與提醒");
    block.append(title);
    answer.risks.forEach((risk) => {
      block.append(alertBlock("triangle-alert", risk, false));
    });
    article.append(block);
  }

  if (answer.disclaimer) {
    const block = element("section", "answer-block");
    block.append(element("p", "disclaimer", answer.disclaimer));
    article.append(block);
  }

  message.append(article);
  return message;
}

function renderMissingFacts(items, partial = false) {
  const section = element("section", "answer-block");
  section.append(
    sectionTitle(
      partial ? "circle-help" : "list-plus",
      partial ? "未提供資料" : "需要補充",
    ),
  );
  if (partial) {
    section.append(
      alertBlock(
        "info",
        "以下資料未提供，本次結果只根據目前已有的信息分析。",
        false,
      ),
    );
  }
  const form = element("form", "missing-form");
  items.forEach((item) => {
    const row = element("label", "missing-question");
    const question = element("p", "", item.question);
    question.append(element("small", "", item.reason || ""));
    const input = element("input");
    input.type = item.code.endsWith("date") ? "date" : "text";
    input.required = true;
    input.dataset.missingCode = item.code;
    input.value = state.facts[item.code] || "";
    row.append(question, input);
    form.append(row);
  });
  const actions = element("div", "missing-actions");
  const submit = element("button", "primary-button");
  submit.type = "submit";
  submit.disabled = state.loading;
  submit.append(iconNode("arrow-right"), document.createTextNode("繼續分析"));
  const skip = element("button", "secondary-button");
  skip.type = "button";
  skip.disabled = state.loading;
  skip.append(
    iconNode("file-search-2"),
    document.createTextNode("按現有資料分析"),
  );
  skip.addEventListener("click", () => {
    ask(state.lastQuery, {
      appendUser: false,
      allowIncomplete: true,
    });
  });
  actions.append(submit, skip);
  form.append(actions);
  section.append(form);
  return section;
}

function renderKnownFacts(items) {
  const section = element("section", "answer-block");
  section.append(sectionTitle("clipboard-check", "已知事實"));
  const list = element("dl", "facts-grid");
  items.forEach((item) => {
    const row = element("div");
    row.append(
      element("dt", "", factLabels[item.code] || item.code),
      element("dd", "", item.value),
    );
    list.append(row);
  });
  section.append(list);
  return section;
}

function renderLawSources(items) {
  const section = element("section", "answer-block");
  section.append(sectionTitle("book-open-check", "適用法源"));
  const list = element("div", "law-list");
  items.forEach((item, index) => {
    const details = element("details", "law-item");
    if (index === 0) {
      details.open = true;
    }
    const summary = element("summary");
    const titleWrap = element("div", "law-summary-title");
    titleWrap.append(
      element("strong", "", `${item.article} ${lawHeading(item.content)}`),
      element("span", "", item.law_title),
    );
    const summarySide = element("div", "law-summary-side");
    summarySide.append(
      document.createTextNode(item.source_type === "law" ? "法律" : "官方來源"),
      iconNode("chevron-down"),
    );
    summary.append(titleWrap, summarySide);
    details.append(summary);

    const body = element("div", "law-body");
    body.append(element("blockquote", "", readableLawText(item.content)));
    const links = element("div", "law-links");
    links.append(
      element(
        "span",
        "",
        `${item.version_label} · ${dateRange(item.effective_from, item.effective_to)}`,
      ),
    );
    if (item.pdf_url && item.page_start) {
      const pdfLink = element("a");
      pdfLink.href = `${item.pdf_url}#page=${item.page_start}`;
      pdfLink.target = "_blank";
      pdfLink.rel = "noopener noreferrer";
      pdfLink.append(
        iconNode("file-text"),
        document.createTextNode(pdfPageLabel(item)),
      );
      links.append(pdfLink);
    }
    const link = element("a");
    link.href = item.official_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.append(iconNode("external-link"), document.createTextNode("官方來源"));
    links.append(link);
    body.append(links);
    details.append(body);
    list.append(details);
  });
  section.append(list);
  return section;
}

function renderListBlock(iconName, title, items, preserveWhitespace = false) {
  const section = element("section", "answer-block");
  section.append(sectionTitle(iconName, title));
  const list = element("ul", "item-list");
  items.forEach((item) => {
    const li = element("li", "", item);
    if (preserveWhitespace) {
      li.style.whiteSpace = "pre-wrap";
    }
    list.append(li);
  });
  section.append(list);
  return section;
}

function sectionTitle(iconName, text) {
  const heading = element("h3");
  heading.append(iconNode(iconName), document.createTextNode(text));
  return heading;
}

function alertBlock(iconName, text, danger) {
  const box = element("div", `alert-box${danger ? " danger" : ""}`);
  box.append(iconNode(iconName), element("p", "", text));
  return box;
}

function iconButton(iconName, tooltip) {
  const button = element("button", "icon-button");
  button.type = "button";
  button.dataset.tooltip = tooltip;
  button.setAttribute("aria-label", tooltip);
  button.append(iconNode(iconName));
  return button;
}

function addFactRow() {
  const row = element("div", "fact-row");
  const key = element("input");
  key.type = "text";
  key.placeholder = "欄位";
  key.dataset.factKey = "";
  key.setAttribute("aria-label", "事實欄位");
  const value = element("input");
  value.type = "text";
  value.placeholder = "內容";
  value.dataset.factValue = "";
  value.setAttribute("aria-label", "事實內容");
  const remove = iconButton("x", "移除事實欄位");
  remove.dataset.removeFact = "";
  row.append(key, value, remove);
  elements.customFacts.append(row);
  refreshIcons(row);
}

function resetCase(showMessage) {
  state.caseId = createId();
  state.messages = [];
  state.facts = {};
  state.lastQuery = "";
  state.currentInteractionId = null;
  elements.roleInput.dataset.lockedRole = "";
  elements.customFacts.replaceChildren();
  addFactRow();
  elements.queryInput.value = "";
  elements.queryInput.style.height = "";
  render();
  if (showMessage) {
    showToast("已建立新案件。");
  }
}

function setBusy(isBusy) {
  elements.submitButton.disabled = isBusy;
  elements.queryInput.disabled = isBusy;
  elements.resetButton.disabled = isBusy;
  elements.composerNote.textContent = isBusy ? "Agent 正在檢索及驗證資料" : "";
}

function scrollToLatest() {
  requestAnimationFrame(() => {
    elements.conversation.scrollTop = elements.conversation.scrollHeight;
  });
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    elements.toast.classList.remove("visible");
  }, 2600);
}

function refreshIcons(root = document) {
  if (window.lucide) {
    window.lucide.createIcons({
      attrs: { "aria-hidden": "true" },
      nameAttr: "data-lucide",
      root,
    });
  }
}

function iconNode(name) {
  const icon = element("i");
  icon.dataset.lucide = name;
  icon.setAttribute("aria-hidden", "true");
  return icon;
}

function element(tagName, className = "", text = "") {
  const node = document.createElement(tagName);
  if (className) {
    node.className = className;
  }
  if (text) {
    node.textContent = text;
  }
  return node;
}

function createId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `case-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function localIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function roleLabel(role) {
  return (
    {
      employee: "僱員",
      employer: "僱主",
      representative: "代理人",
      other: "其他",
      unknown: "未指定",
    }[role] || role
  );
}

function lawHeading(content) {
  return content.split("\n", 1)[0] || "";
}

function readableLawText(content) {
  const lines = content
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const paragraphs = [];
  let current = "";
  for (const line of lines) {
    const startsParagraph =
      /^[一二三四五六七八九十百]+、/.test(line) ||
      /^（[一二三四五六七八九十]+）/.test(line);
    if (!current) {
      current = line;
    } else if (startsParagraph) {
      paragraphs.push(current);
      current = line;
    } else {
      current += line;
    }
  }
  if (current) {
    paragraphs.push(current);
  }
  return paragraphs.join("\n");
}

function dateRange(from, to) {
  return to ? `${from} 至 ${to}` : `${from} 起`;
}

function pdfPageLabel(item) {
  if (item.page_end && item.page_end !== item.page_start) {
    return `PDF 第 ${item.page_start}-${item.page_end} 頁`;
  }
  return `PDF 第 ${item.page_start} 頁`;
}
