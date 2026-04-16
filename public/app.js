const state = {
  config: null,
  projects: [],
  currentProject: null,
  currentChapterId: null,
};

const elements = {
  projectList: document.querySelector("#project-list"),
  projectTitleInput: document.querySelector("#project-title-input"),
  projectDescriptionInput: document.querySelector("#project-description-input"),
  newProjectBtn: document.querySelector("#new-project-btn"),
  appSidebar: document.querySelector("#app-sidebar"),
  toggleSidebarBtn: document.querySelector("#toggle-sidebar-btn"),
  projectTitle: document.querySelector("#project-title"),
  projectDescription: document.querySelector("#project-description"),
  modelStatus: document.querySelector("#model-status"),
  modelBaseUrl: document.querySelector("#model-base-url"),
  modelName: document.querySelector("#model-name"),
  modelApiKey: document.querySelector("#model-api-key"),
  modelSettingsHint: document.querySelector("#model-settings-hint"),
  saveModelSettingsBtn: document.querySelector("#save-model-settings-btn"),
  workspace: document.querySelector("#workspace"),
  worldSetting: document.querySelector("#world-setting"),
  worldCoreSetting: document.querySelector("#world-core-setting"),
  saveWorldBtn: document.querySelector("#save-world-btn"),
  chapterList: document.querySelector("#chapter-list"),
  newChapterBtn: document.querySelector("#new-chapter-btn"),
  chapterEditor: document.querySelector("#chapter-editor"),
  chapterEditorTitle: document.querySelector("#chapter-editor-title"),
  chapterTitle: document.querySelector("#chapter-title"),
  chapterPlot: document.querySelector("#chapter-plot"),
  chapterRelationships: document.querySelector("#chapter-relationships"),
  chapterStyleGuide: document.querySelector("#chapter-style-guide"),
  chapterCharacterSelector: document.querySelector("#chapter-character-selector"),
  chapterEntrySelector: document.querySelector("#chapter-entry-selector"),
  chapterRelatedSelector: document.querySelector("#chapter-related-selector"),
  chapterBody: document.querySelector("#chapter-body"),
  chapterSummary: document.querySelector("#chapter-summary"),
  chapterHint: document.querySelector("#chapter-hint"),
  saveChapterBtn: document.querySelector("#save-chapter-btn"),
  generateChapterBtn: document.querySelector("#generate-chapter-btn"),
  regenerateChapterBtn: document.querySelector("#regenerate-chapter-btn"),
  characterId: document.querySelector("#character-id"),
  characterName: document.querySelector("#character-name"),
  characterGender: document.querySelector("#character-gender"),
  characterPersonality: document.querySelector("#character-personality"),
  characterRelatedInfo: document.querySelector("#character-related-info"),
  saveCharacterBtn: document.querySelector("#save-character-btn"),
  characterList: document.querySelector("#character-list"),
  entryId: document.querySelector("#entry-id"),
  entryName: document.querySelector("#entry-name"),
  entryRelatedInfo: document.querySelector("#entry-related-info"),
  saveEntryBtn: document.querySelector("#save-entry-btn"),
  entryList: document.querySelector("#entry-list"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  const rawText = await response.text();
  let data = null;
  if (rawText) {
    try {
      data = JSON.parse(rawText);
    } catch (error) {
      const snippet = rawText.trim().slice(0, 240) || "<empty response>";
      throw new Error(`接口返回了非 JSON 内容：${snippet}`);
    }
  } else {
    data = {};
  }

  if (!response.ok) {
    throw new Error(data.detail || data.error || "Request failed");
  }
  return data;
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function selectedProject() {
  return state.currentProject;
}

function selectedChapter() {
  return state.currentProject?.chapters.find((item) => item.id === state.currentChapterId) || null;
}

function renderProjects() {
  elements.projectList.innerHTML = state.projects
    .map(
      (project) => `
        <li class="${state.currentProject?.id === project.id ? "active" : ""}" data-project-id="${project.id}">
          <div class="item-title">${escapeHtml(project.title)}</div>
          <div class="item-meta">${project.chapterCount || 0} 章</div>
        </li>
      `
    )
    .join("");

  elements.projectList.querySelectorAll("[data-project-id]").forEach((node) => {
    node.addEventListener("click", () => loadProject(node.dataset.projectId));
  });
}

function renderProjectDetail() {
  const project = selectedProject();
  if (!project) {
    elements.workspace.classList.add("hidden");
    elements.projectTitle.textContent = "请选择或创建作品";
    elements.projectDescription.textContent = "";
    return;
  }

  elements.workspace.classList.remove("hidden");
  elements.projectTitle.textContent = project.title;
  elements.projectDescription.textContent = project.description || "未填写作品简介";
  elements.worldSetting.value = project.world.setting || "";
  elements.worldCoreSetting.value = project.world.coreSetting || "";
  renderChapterList();
  renderCharacterList();
  renderEntryList();
  renderChapterSelectors();
  renderActiveChapter();
}

function renderChapterList() {
  const chapters = selectedProject()?.chapters || [];
  elements.chapterList.innerHTML = chapters
    .map(
      (chapter) => `
        <li class="${state.currentChapterId === chapter.id ? "active" : ""}" data-chapter-id="${chapter.id}">
          <div class="item-title">${escapeHtml(chapter.title)}</div>
          <div class="item-meta">${chapter.summary ? escapeHtml(chapter.summary.slice(0, 42)) : "未生成摘要"}</div>
        </li>
      `
    )
    .join("");
  elements.chapterList.querySelectorAll("[data-chapter-id]").forEach((node) => {
    node.addEventListener("click", () => {
      state.currentChapterId = node.dataset.chapterId;
      renderChapterList();
      renderChapterSelectors();
      renderActiveChapter();
    });
  });
}

function renderCharacterList() {
  const characters = selectedProject()?.characters || [];
  elements.characterList.innerHTML = characters
    .map(
      (character) => `
        <li data-character-id="${character.id}">
          <div class="item-title">${escapeHtml(character.name || "未命名角色")}</div>
          <div class="item-meta">${escapeHtml((character.personality || "").slice(0, 40) || "未填写性格")}</div>
        </li>
      `
    )
    .join("");

  elements.characterList.querySelectorAll("[data-character-id]").forEach((node) => {
    node.addEventListener("click", () => {
      const character = selectedProject().characters.find((item) => item.id === node.dataset.characterId);
      elements.characterId.value = character.id;
      elements.characterName.value = character.name || "";
      elements.characterGender.value = character.gender || "";
      elements.characterPersonality.value = character.personality || "";
      elements.characterRelatedInfo.value = character.relatedInfo || "";
    });
  });
}

function renderEntryList() {
  const entries = selectedProject()?.entries || [];
  elements.entryList.innerHTML = entries
    .map(
      (entry) => `
        <li data-entry-id="${entry.id}">
          <div class="item-title">${escapeHtml(entry.name || "未命名词条")}</div>
          <div class="item-meta">${escapeHtml((entry.relatedInfo || "").slice(0, 40) || "未填写信息")}</div>
        </li>
      `
    )
    .join("");
  elements.entryList.querySelectorAll("[data-entry-id]").forEach((node) => {
    node.addEventListener("click", () => {
      const entry = selectedProject().entries.find((item) => item.id === node.dataset.entryId);
      elements.entryId.value = entry.id;
      elements.entryName.value = entry.name || "";
      elements.entryRelatedInfo.value = entry.relatedInfo || "";
    });
  });
}

function checkboxItem(label, description, checked, attrs = {}) {
  return `
    <label class="checkbox-item">
      <input type="checkbox" ${checked ? "checked" : ""} ${Object.entries(attrs)
        .map(([key, value]) => `${key}="${escapeHtml(value)}"`)
        .join(" ")} />
      <div>
        <div class="item-title">${escapeHtml(label)}</div>
        <div class="item-meta">${escapeHtml(description || " ")}</div>
      </div>
    </label>
  `;
}

function renderChapterSelectors() {
  const project = selectedProject();
  const chapter = selectedChapter();
  if (!project) {
    return;
  }

  const selectedCharacterIds = new Set(chapter?.selectedCharacterIds || []);
  const selectedEntryIds = new Set(chapter?.selectedEntryIds || []);
  const relatedMap = new Map((chapter?.relatedChapters || []).map((item) => [item.chapterId, item]));

  elements.chapterCharacterSelector.innerHTML = project.characters
    .map((character) =>
      checkboxItem(character.name, character.relatedInfo?.slice(0, 60), selectedCharacterIds.has(character.id), {
        "data-character-select": character.id,
      })
    )
    .join("");

  elements.chapterEntrySelector.innerHTML = project.entries
    .map((entry) =>
      checkboxItem(entry.name, entry.relatedInfo?.slice(0, 60), selectedEntryIds.has(entry.id), {
        "data-entry-select": entry.id,
      })
    )
    .join("");

  elements.chapterRelatedSelector.innerHTML = project.chapters
    .filter((item) => item.id !== state.currentChapterId)
    .map((related) => {
      const relation = relatedMap.get(related.id) || { useBody: false, useSummary: false };
      return `
        <div class="checkbox-item">
          <div>
            <div class="item-title">${escapeHtml(related.title)}</div>
            <div class="item-meta">${escapeHtml((related.summary || "未生成摘要").slice(0, 60))}</div>
            <label><input type="checkbox" data-related-body="${related.id}" ${relation.useBody ? "checked" : ""} /> 正文</label>
            <label><input type="checkbox" data-related-summary="${related.id}" ${relation.useSummary ? "checked" : ""} /> 摘要</label>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderActiveChapter() {
  const chapter = selectedChapter();
  if (!chapter) {
    elements.chapterEditor.classList.add("hidden");
    return;
  }

  elements.chapterEditor.classList.remove("hidden");
  elements.chapterEditorTitle.textContent = `章节工作区 · ${chapter.title}`;
  elements.chapterTitle.value = chapter.title || "";
  elements.chapterPlot.value = chapter.plot || "";
  elements.chapterRelationships.value = chapter.relationships || "";
  elements.chapterStyleGuide.value = chapter.styleGuide || "";
  elements.chapterBody.value = chapter.body || "";
  elements.chapterSummary.value = chapter.summary || "";

  const autoCharacters = chapter.autoLoadedCharacterIds?.length
    ? `自动加载角色：${chapter.autoLoadedCharacterIds.length} 个`
    : "未自动加载角色";
  const autoEntries = chapter.autoLoadedEntryIds?.length
    ? `自动加载词条：${chapter.autoLoadedEntryIds.length} 个`
    : "未自动加载词条";
  elements.chapterHint.textContent = `${autoCharacters}；${autoEntries}。未手动勾选时会根据名称自动匹配。`;
}

function collectChapterPayload() {
  return {
    title: elements.chapterTitle.value.trim(),
    plot: elements.chapterPlot.value.trim(),
    relationships: elements.chapterRelationships.value.trim(),
    styleGuide: elements.chapterStyleGuide.value.trim(),
    body: elements.chapterBody.value,
    summary: elements.chapterSummary.value,
    selectedCharacterIds: Array.from(
      elements.chapterCharacterSelector.querySelectorAll("[data-character-select]:checked")
    ).map((node) => node.dataset.characterSelect),
    selectedEntryIds: Array.from(elements.chapterEntrySelector.querySelectorAll("[data-entry-select]:checked")).map(
      (node) => node.dataset.entrySelect
    ),
    relatedChapters: selectedProject().chapters
      .filter((chapter) => chapter.id !== state.currentChapterId)
      .map((chapter) => ({
        chapterId: chapter.id,
        useBody: Boolean(elements.chapterRelatedSelector.querySelector(`[data-related-body="${chapter.id}"]`)?.checked),
        useSummary: Boolean(
          elements.chapterRelatedSelector.querySelector(`[data-related-summary="${chapter.id}"]`)?.checked
        ),
      }))
      .filter((item) => item.useBody || item.useSummary),
  };
}

async function refreshProjects(preserveProjectId) {
  state.projects = await api("/api/projects");
  renderProjects();

  if (preserveProjectId) {
    await loadProject(preserveProjectId);
  }
}

async function loadConfig() {
  state.config = await api("/api/config");
  elements.modelStatus.textContent = state.config.modelConfigured
    ? `模型已配置：${state.config.model} · ${state.config.baseUrl} · 流式生成已启用`
    : "未配置模型，将使用本地回退草稿模式。";
}

async function loadModelSettings() {
  const settings = await api("/api/settings/model");
  elements.modelBaseUrl.value = settings.baseUrl || "https://api.openai.com/v1";
  elements.modelName.value = settings.model || "gpt-4.1-mini";
  elements.modelApiKey.value = "";
  elements.modelSettingsHint.textContent = settings.hasApiKey
    ? "当前已保存 Token。留空并保存会保留原 Token；输入新值并保存会覆盖。"
    : "当前尚未保存 Token。保存后，章节生成会优先使用这里的本地配置。";
}

async function saveModelSettings() {
  const payload = {
    baseUrl: elements.modelBaseUrl.value.trim(),
    model: elements.modelName.value.trim(),
  };
  if (elements.modelApiKey.value.trim()) {
    payload.apiKey = elements.modelApiKey.value.trim();
  }
  await api("/api/settings/model", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  elements.modelApiKey.value = "";
  await loadConfig();
  await loadModelSettings();
}

async function loadProject(projectId) {
  state.currentProject = await api(`/api/projects/${projectId}`);
  state.currentChapterId = state.currentProject.chapters[0]?.id || null;
  renderProjects();
  renderProjectDetail();
}

async function createProject() {
  const title = elements.projectTitleInput.value.trim();
  if (!title) {
    alert("请先填写作品名称。");
    return;
  }
  const project = await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({
      title,
      description: elements.projectDescriptionInput.value.trim(),
    }),
  });
  elements.projectTitleInput.value = "";
  elements.projectDescriptionInput.value = "";
  await refreshProjects(project.id);
}

async function saveWorld() {
  const project = selectedProject();
  if (!project) {
    return;
  }
  await api(`/api/projects/${project.id}/world`, {
    method: "PUT",
    body: JSON.stringify({
      setting: elements.worldSetting.value,
      coreSetting: elements.worldCoreSetting.value,
    }),
  });
  await loadProject(project.id);
}

async function saveCharacter() {
  const project = selectedProject();
  if (!project) {
    return;
  }
  const payload = {
    name: elements.characterName.value.trim(),
    gender: elements.characterGender.value.trim(),
    personality: elements.characterPersonality.value.trim(),
    relatedInfo: elements.characterRelatedInfo.value.trim(),
  };
  if (!payload.name) {
    alert("角色名称不能为空。");
    return;
  }
  const characterId = elements.characterId.value;
  if (characterId) {
    await api(`/api/projects/${project.id}/characters/${characterId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  } else {
    await api(`/api/projects/${project.id}/characters`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  elements.characterId.value = "";
  elements.characterName.value = "";
  elements.characterGender.value = "";
  elements.characterPersonality.value = "";
  elements.characterRelatedInfo.value = "";
  await loadProject(project.id);
}

async function saveEntry() {
  const project = selectedProject();
  if (!project) {
    return;
  }
  const payload = {
    name: elements.entryName.value.trim(),
    relatedInfo: elements.entryRelatedInfo.value.trim(),
  };
  if (!payload.name) {
    alert("词条名称不能为空。");
    return;
  }
  const entryId = elements.entryId.value;
  if (entryId) {
    await api(`/api/projects/${project.id}/entries/${entryId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  } else {
    await api(`/api/projects/${project.id}/entries`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
  elements.entryId.value = "";
  elements.entryName.value = "";
  elements.entryRelatedInfo.value = "";
  await loadProject(project.id);
}

async function createChapter() {
  const project = selectedProject();
  if (!project) {
    return;
  }
  const chapter = await api(`/api/projects/${project.id}/chapters`, {
    method: "POST",
    body: JSON.stringify({ title: `第${project.chapters.length + 1}章` }),
  });
  await loadProject(project.id);
  state.currentChapterId = chapter.id;
  renderChapterList();
  renderChapterSelectors();
  renderActiveChapter();
}

async function saveChapter() {
  const project = selectedProject();
  const chapter = selectedChapter();
  if (!project || !chapter) {
    return;
  }
  await api(`/api/projects/${project.id}/chapters/${chapter.id}`, {
    method: "PUT",
    body: JSON.stringify(collectChapterPayload()),
  });
  await loadProject(project.id);
  state.currentChapterId = chapter.id;
  renderChapterList();
  renderChapterSelectors();
  renderActiveChapter();
}

async function generateChapter() {
  const project = selectedProject();
  const chapter = selectedChapter();
  if (!project || !chapter) {
    return;
  }

  await saveChapter();
  setGenerationState(true);
  elements.chapterBody.value = "";
  elements.chapterSummary.value = "";
  elements.chapterHint.textContent = "正在建立流式连接...";

  const response = await fetch(`/api/projects/${project.id}/chapters/${chapter.id}/generate-stream`, {
    method: "POST",
  });
  if (!response.ok) {
    setGenerationState(false);
    throw new Error(`生成请求失败：HTTP ${response.status}`);
  }
  if (!response.body) {
    setGenerationState(false);
    throw new Error("浏览器未返回可读取的流。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let result = null;
  let streamError = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const messages = buffer.split("\n\n");
    buffer = messages.pop() || "";
    for (const message of messages) {
      const parsed = parseSseMessage(message);
      if (!parsed) {
        continue;
      }
      if (parsed.event === "status") {
        elements.chapterHint.textContent = parsed.data.message || "正在生成...";
      } else if (parsed.event === "body_delta") {
        elements.chapterBody.value += parsed.data.content || "";
      } else if (parsed.event === "summary") {
        elements.chapterSummary.value = parsed.data.summary || "";
      } else if (parsed.event === "complete") {
        result = parsed.data;
      } else if (parsed.event === "error") {
        streamError = parsed.data.detail || "生成失败";
      }
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    const parsed = parseSseMessage(buffer);
    if (parsed) {
      if (parsed.event === "status") {
        elements.chapterHint.textContent = parsed.data.message || "正在生成...";
      } else if (parsed.event === "body_delta") {
        elements.chapterBody.value += parsed.data.content || "";
      } else if (parsed.event === "summary") {
        elements.chapterSummary.value = parsed.data.summary || "";
      } else if (parsed.event === "complete") {
        result = parsed.data;
      } else if (parsed.event === "error") {
        streamError = parsed.data.detail || "生成失败";
      }
    }
  }

  setGenerationState(false);
  if (streamError) {
    throw new Error(streamError);
  }
  if (!result) {
    throw new Error("流式生成未返回完成事件。");
  }

  await loadProject(project.id);
  state.currentChapterId = result.chapter.id;
  renderChapterList();
  renderChapterSelectors();
  renderActiveChapter();
  const modelLabel = result.model === "local-fallback" ? "本地回退草稿" : result.model;
  elements.chapterHint.textContent = `生成完成，模型：${modelLabel}。自动加载角色 ${result.autoLoadedCharacterIds.length} 个，词条 ${result.autoLoadedEntryIds.length} 个。`;
}

function parseSseMessage(message) {
  const lines = message.split("\n");
  let event = "message";
  const dataLines = [];
  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line) {
      continue;
    }
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (!dataLines.length) {
    return null;
  }
  return {
    event,
    data: JSON.parse(dataLines.join("\n")),
  };
}

function setGenerationState(isGenerating) {
  elements.generateChapterBtn.disabled = isGenerating;
  elements.regenerateChapterBtn.disabled = isGenerating;
  elements.saveChapterBtn.disabled = isGenerating;
}

function bindEvents() {
  elements.newProjectBtn.addEventListener("click", () => createProject().catch(handleError));
  elements.toggleSidebarBtn.addEventListener("click", toggleSidebar);
  elements.saveModelSettingsBtn.addEventListener("click", () => saveModelSettings().catch(handleError));
  elements.saveWorldBtn.addEventListener("click", () => saveWorld().catch(handleError));
  elements.saveCharacterBtn.addEventListener("click", () => saveCharacter().catch(handleError));
  elements.saveEntryBtn.addEventListener("click", () => saveEntry().catch(handleError));
  elements.newChapterBtn.addEventListener("click", () => createChapter().catch(handleError));
  elements.saveChapterBtn.addEventListener("click", () => saveChapter().catch(handleError));
  elements.generateChapterBtn.addEventListener("click", () => generateChapter().catch(handleError));
  elements.regenerateChapterBtn.addEventListener("click", () => generateChapter().catch(handleError));
}

function toggleSidebar() {
  const collapsed = elements.appSidebar.classList.toggle("collapsed");
  elements.toggleSidebarBtn.textContent = collapsed ? "展开" : "折叠";
}

function handleError(error) {
  console.error(error);
  alert(error.message);
  elements.chapterHint.textContent = error.message;
}

async function init() {
  bindEvents();
  await loadConfig();
  await loadModelSettings();
  await refreshProjects();
}

init().catch(handleError);
