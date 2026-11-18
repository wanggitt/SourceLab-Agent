"use strict";
const $ = (sel) => document.querySelector(sel);
const state = {
  papers: [], selected: "", csvRows: null, csvSummary: null, csvGroups: null,
  navigationLoadedId: "",
  graphData: null, graphFocus: "", graphQuery: "", graphEdgeFilter: "all",
  translationJobId: "", translationPage: 1, modelConfigured: false
};
const statusText = { ready: "已解析", processing: "解析中", error: "失败", ocr_required: "需 OCR" };
const toast = (msg) => {
  const el = $("#toast"); el.textContent = msg; el.classList.add("visible");
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove("visible"), 4600);
};
async function api(path, options = {}) {
  const res = await fetch(path, options);
  let data; try { data = await res.json(); } catch { throw new Error(`请求失败 (${res.status})`); }
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}
const visualViewer = {name: "", scale: 1, baseWidth: 900};
function visualCanvas() {
  return $("#visual-preview").querySelector("svg");
}
function applyVisualScale() {
  const svg = visualCanvas();
  if (!svg) return;
  svg.style.width = `${Math.round(visualViewer.baseWidth * visualViewer.scale)}px`;
  svg.style.height = "auto";
  $("#visual-scale").textContent = `${Math.round(visualViewer.scale * 100)}%`;
}
function openVisual(name, source, hint) {
  if (!source) return toast("请先生成图形");
  visualViewer.name = name;
  visualViewer.scale = 1;
  const vb = source.getAttribute("viewBox")?.split(/\s+/).map(Number) || [];
  visualViewer.baseWidth = Math.max(680, Math.min(1900, vb[2] || 900));
  $("#visual-title").textContent = name === "citation" ?
    "局域引用关系 · 点击小图节点可选中原文" : "方法拓扑 · 来源与拟议设计";
  $("#visual-caption").textContent = hint;
  const copy = source.cloneNode(true);
  if (name === "citation" && typeof copy.querySelectorAll === "function") {
    copy.querySelectorAll("[data-paper-id]").forEach(node => {
      node.style.cursor = "pointer";
      node.onclick = () => {
        closeVisual();
        const id = node.getAttribute("data-paper-id");
        state.graphFocus = id;
        renderGraph();
        selectPaper(id);
      };
    });
    copy.querySelectorAll("[data-edge-source]").forEach(line => {
      line.style.cursor = "pointer";
      line.onclick = () => {
        closeVisual();
        selectPaper(line.getAttribute("data-edge-source"),
          Number(line.getAttribute("data-edge-page")) || 1);
      };
    });
  }
  $("#visual-preview").replaceChildren(copy);
  $("#visual-window").hidden = false;
  $("#page-layout").inert = true;
  applyVisualScale();
  $("#visual-close").focus();
}
function closeVisual() {
  $("#visual-window").hidden = true;
  $("#page-layout").inert = false;
  (visualViewer.name === "citation" ? $("#graph-expand") : $("#diagram-expand")).focus();
}
function downloadSvg(svg, name) {
  if (!svg) return;
  const raw = new XMLSerializer().serializeToString(svg);
  const url = URL.createObjectURL(new Blob([raw], {
    type: "image/svg+xml;charset=utf-8",
  }));
  const anchor = el("a");
  anchor.href = url; anchor.download = name + ".svg"; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 2500);
}
$("#visual-close").onclick = closeVisual;
$("#visual-smaller").onclick = () => {
  visualViewer.scale = Math.max(.5, visualViewer.scale - .25); applyVisualScale();
};
$("#visual-larger").onclick = () => {
  visualViewer.scale = Math.min(3, visualViewer.scale + .25); applyVisualScale();
};
$("#visual-reset").onclick = () => {
  visualViewer.scale = 1; applyVisualScale();
};
$("#visual-download").onclick = () =>
  downloadSvg(visualCanvas(), visualViewer.name === "citation" ?
    "sourcelab_local_citation_graph" : "sourcelab_method_topology");
$("#graph-expand").onclick = () => openVisual(
  "citation", $("#graph").querySelector("svg"),
  "局域引用边仅代表所导入文献的 References 匹配；请在下方来源列表核对 PDF 页。");
$("#diagram-expand").onclick = () => openVisual(
  "topology", $("#diagram-preview").querySelector("svg"),
  "来源节点只具备页码定位；拟议节点和箭头不是实验验证。");
$("#diagram-download").onclick = () =>
  downloadSvg($("#diagram-preview").querySelector("svg"), "sourcelab_method_topology");
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("#visual-window").hidden) closeVisual();
});
const LAYOUT_KEY = "sourcelab-layout-v1";
const layoutDefaults = { left: 310, right: 370, scale: 1, hideLeft: false, hideRight: false, focus: false };
let layout = { ...layoutDefaults };
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
function layoutLimits() {
  const available = Math.max(0, window.innerWidth / clamp(Number(layout.scale) || 1, .85, 1.6) - 90);
  return {
    leftMax: Math.max(260, Math.min(640, available - (layout.hideRight ? 0 : layout.right) - 380)),
    rightMax: Math.max(320, Math.min(850, available - (layout.hideLeft ? 0 : layout.left) - 380))
  };
}
function applyLayout(save = true) {
  layout.scale = clamp(Number(layout.scale) || 1, .85, 1.6);
  layout.left = clamp(Number(layout.left) || 310, 260, 640);
  layout.right = clamp(Number(layout.right) || 370, 320, 850);
  const stacked = window.innerWidth / layout.scale < 1080;
  if (!stacked) {
    layout.left = clamp(layout.left, 260, layoutLimits().leftMax);
    layout.right = clamp(layout.right, 320, layoutLimits().rightMax);
  }
  const root = document.documentElement;
  root.style.setProperty("--ui-scale", String(layout.scale));
  root.style.setProperty("--left-width", `${layout.left}px`);
  root.style.setProperty("--right-width", `${layout.right}px`);
  const page = $("#page-layout");
  const hideLeft = layout.hideLeft || layout.focus;
  const hideRight = layout.hideRight && !layout.focus;
  page.classList.toggle("hide-library", hideLeft);
  page.classList.toggle("hide-assistant", hideRight);
  page.classList.toggle("focus-assistant", layout.focus);
  page.classList.toggle("stacked-layout", stacked);
  $("#library-panel").hidden = hideLeft;
  $("#assistant-panel").hidden = hideRight;
  $("#library-resizer").hidden = hideLeft;
  $("#assistant-resizer").hidden = hideRight || layout.focus;
  $("#toggle-library").textContent = hideLeft ? "展开文献库" : "收起文献库";
  $("#toggle-library").setAttribute("aria-expanded", String(!hideLeft));
  $("#toggle-assistant").textContent = hideRight ? "展开 Agent 栏" : "收起 Agent 栏";
  $("#toggle-assistant").setAttribute("aria-expanded", String(!hideRight));
  $("#focus-assistant").textContent = layout.focus ? "退出 Agent 专注" : "Agent 专注模式";
  $("#focus-assistant").setAttribute("aria-pressed", String(layout.focus));
  $("#font-level").textContent = `${Math.round(layout.scale * 100)}%`;
  for (const [name, width] of [["library", layout.left], ["assistant", layout.right]]) {
    const handle = $(`#${name}-resizer`);
    handle.setAttribute("aria-valuenow", String(width));
    handle.setAttribute("aria-valuetext", `${width} 像素`);
  }
  if (save) {
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch { /* private mode */ }
  }
}
function initLayout() {
  try {
    const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY));
    if (saved && typeof saved === "object") layout = { ...layoutDefaults, ...saved };
  } catch { /* invalid or blocked storage */ }
  applyLayout(false);
  $("#toggle-library").onclick = () => {
    if (layout.focus) { layout.focus = false; layout.hideLeft = false; }
    else layout.hideLeft = !layout.hideLeft;
    applyLayout();
  };
  $("#toggle-assistant").onclick = () => {
    if (layout.focus) { layout.focus = false; layout.hideRight = false; }
    else layout.hideRight = !layout.hideRight;
    applyLayout();
  };
  $("#focus-assistant").onclick = () => { layout.focus = !layout.focus; applyLayout(); };
  $("#font-smaller").onclick = () => { layout.scale = clamp(Math.round(layout.scale * 10 - 1) / 10, .85, 1.6); applyLayout(); };
  $("#font-larger").onclick = () => { layout.scale = clamp(Math.round(layout.scale * 10 + 1) / 10, .85, 1.6); applyLayout(); };
  $("#layout-reset").onclick = () => { layout = { ...layoutDefaults }; applyLayout(); };
  for (const [name, side] of [["library", "left"], ["assistant", "right"]]) {
    const handle = $(`#${name}-resizer`);
    handle.addEventListener("pointerdown", event => {
      if (window.innerWidth / layout.scale < 1080) return;
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      const startX = event.clientX, startWidth = layout[side];
      const move = pointer => {
        const bounds = layoutLimits();
        layout[side] = clamp(startWidth + (side === "left" ? 1 : -1) *
          (pointer.clientX - startX), side === "left" ? 260 : 320,
        side === "left" ? bounds.leftMax : bounds.rightMax);
        applyLayout();
      };
      const stop = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
    });
    handle.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const limits = layoutLimits();
      const min = side === "left" ? 260 : 320;
      const max = side === "left" ? limits.leftMax : limits.rightMax;
      if (event.key === "Home") layout[side] = min;
      else if (event.key === "End") layout[side] = max;
      else layout[side] = clamp(layout[side] + (event.key === "ArrowRight" ? 1 : -1) *
        (side === "left" ? 20 : -20), min, max);
      applyLayout();
    });
  }
  window.addEventListener("resize", () => applyLayout(false));
}
initLayout();
async function refresh() {
  state.papers = (await api("/api/papers")).papers;
  $("#count").textContent = `${state.papers.length} 篇`;
  const list = $("#papers"); list.replaceChildren();
  if (!state.papers.length) list.append(el("p", "empty", "暂无论文。先上传一篇，或导入官方样例。"));
  for (const paper of state.papers) {
    const item = el("div", "paper" + (paper.id === state.selected ? " active" : ""));
    item.tabIndex = 0;
    item.append(el("div", "paper-title", paper.title || paper.filename));
    const meta = el("div", "paper-meta");
    meta.append(el("span", "state " + paper.status, statusText[paper.status] || paper.status));
    meta.append(el("span", "", paper.status === "processing"
      ? `${paper.processed_pages || 0}/${paper.pages || "?"} 页已处理`
      : `${paper.pages || "—"} 页 · ${paper.ocr_pages || 0} 页OCR · ${paper.chunks || 0} 片段`));
    if (paper.created_at) {
      const when = new Date(paper.created_at);
      if (!Number.isNaN(when.getTime()))
        meta.append(el("span", "paper-imported-at",
          `导入 ${when.toLocaleString("zh-CN", {hour12: false})}`));
    }
    if (paper.version) meta.append(el("span", "", "v" + paper.version));
    if (paper.status === "ocr_required" || paper.status === "error"
        || (paper.status === "ready" && paper.ocr_pages && !paper.ocr_boxes)) {
      const retry = el("button", "retry",
        paper.status === "ready" ? "重建OCR定位" : "重新解析");
      retry.type = "button";
      retry.onclick = async (event) => {
        event.stopPropagation();
        try {
          await api(`/api/papers/${paper.id}/retry`, { method: "POST" });
          await refresh(); toast("已开始重新解析");
        } catch (error) { toast(error.message); }
      };
      meta.append(retry);
    }
    const del = el("button", "delete", "删除"); del.type = "button"; del.title = "从本地文献库删除";
    del.onclick = async (event) => {
      event.stopPropagation();
      if (!window.confirm(`从文献库删除「${paper.filename}」？`)) return;
      try {
        await api(`/api/papers/${paper.id}`, { method: "DELETE" });
        if (state.selected === paper.id) { state.selected = ""; showReader(null); }
        await refresh(); toast("已从文献库删除");
      } catch (error) { toast(error.message); }
    };
    meta.append(del); item.append(meta);
    if (paper.duplicate_of && paper.duplicate_resolution === "pending") {
      const old = state.papers.find(x => x.id === paper.duplicate_of);
      const advice = old?.version && paper.version
        ? `；${old.version > paper.version ? "库中版本更新，建议保留旧记录" : "本次版本更新，可人工选择保留或删除旧记录"}`
        : "；请人工核对版本";
      item.append(el("div", "paper-alert", `⚠ 正文相似度 ${Math.round(paper.similarity * 100)}%，疑似与 ${old?.filename || "另一篇论文"} 重复${advice}`));
      if (old && paper.status === "ready" && old.status === "ready") {
        const actions = el("div", "duplicate-actions");
        for (const [action, label] of [
          ["keep_existing", "保留库中版本"],
          ["replace_existing", "用本次版本替换"],
          ["keep_both", "两版都保留"]
        ]) {
          const button = el("button", "btn light", label);
          button.type = "button";
          button.onclick = async (event) => {
            event.stopPropagation();
            const removed = action === "keep_existing" ? paper
              : action === "replace_existing" ? old : null;
            if (!window.confirm(
              `${label}？${removed ? `将从文献库移除「${removed.filename}」及其索引。` : "不移除任何论文。"}`
            )) return;
            let confirmOlder = false;
            if (action === "replace_existing" && (
              !paper.version || !old.version || paper.version < old.version
            )) {
              if (!window.confirm(
                `警告：本次上传 ${paper.filename} 较库中 ${old.filename} 更旧或版本未知。`
                + "确认仍要移除库中记录并替换吗？"
              )) return;
              confirmOlder = true;
            }
            button.disabled = true;
            try {
              const response = await api(
                `/api/papers/${paper.id}/resolve-duplicate`, {
                  method: "POST", headers: {"Content-Type": "application/json"},
                  body: JSON.stringify({
                    existing_id: old.id, action, confirm_older: confirmOlder
                  })
                }
              );
              if (state.selected === response.removed_id) {
                state.selected = ""; showReader(null);
              }
              await refresh();
              toast(`${label}已完成。${response.removed_id ? "已移除旧索引。" : ""}`);
            } catch (error) {
              button.disabled = false; toast(error.message);
            }
          };
          actions.append(button);
        }
        item.append(actions);
      }
    }
    if (paper.duplicate_resolution === "kept_both")
      item.append(el("p", "hint", "已确认：两版均保留。"));
    if (paper.error) item.append(el("div", "paper-alert", paper.error));
    item.onclick = () => selectPaper(paper.id);
    item.onkeydown = (event) => { if (event.key === "Enter") selectPaper(paper.id); };
    list.append(item);
  }
  const scope = $("#scope"), prior = scope.value;
  scope.replaceChildren(new Option("全部已解析文献", ""));
  for (const paper of state.papers.filter(x => x.status === "ready")) {
    scope.append(new Option(paper.title || paper.filename, paper.id));
  }
  if ([...scope.options].some(x => x.value === prior)) scope.value = prior;
  if (state.selected && !state.papers.some(x => x.id === state.selected)) {
    state.selected = ""; showReader(null);
  }
  if (state.selected && state.navigationLoadedId !== state.selected
      && state.papers.some(x => x.id === state.selected && x.status === "ready")) {
    loadNavigation(state.selected);
  }
  showVersionPanel();
  updateCompareChoices();
  updateTaskChoices();
  updateWritingChoices();
}
function versionPeer(paper) {
  if (!paper || paper.status !== "ready" || !paper.arxiv_id) return null;
  const candidates = state.papers.filter(p => p.status === "ready" && p.id !== paper.id
    && p.arxiv_id === paper.arxiv_id && p.version !== paper.version);
  return candidates.sort((a, b) => (b.version || 0) - (a.version || 0))[0] || null;
}
function showVersionPanel() {
  const paper = state.papers.find(p => p.id === state.selected), other = versionPeer(paper);
  $("#version-panel").hidden = !other;
  if (!other) return;
  const relation = (paper.version || 0) > (other.version || 0) ? "更早" : "更新";
  $("#version-description").textContent =
    `同一 arXiv ID：当前 ${paper.filename}；库中还有 ${other.filename}（${relation}）。对比不会删除任何版本。`;
}
$("#version-compare").onclick = async () => {
  const current = state.papers.find(x => x.id === state.selected), other = versionPeer(current);
  if (!current || !other) return;
  const old = (current.version || 0) < (other.version || 0) ? current : other;
  const latest = old === current ? other : current;
  const box = $("#version-results"); box.replaceChildren(el("p", "hint", "正在对比正文词序列…"));
  try {
    const data = await api(`/api/versions/compare?first=${old.id}&second=${latest.id}`);
    box.replaceChildren();
    box.append(el("p", "hint", `${data.first.filename} → ${data.second.filename}；词序列相似比值 ${Math.round(data.similarity * 100)}%。${data.note}`));
    if (!data.candidates.length) box.append(el("p", "hint", "未发现达到筛选长度的候选差异。"));
    data.candidates.forEach((item, index) => {
      const block = el("div", "diff-block");
      block.append(el("strong", "", `候选 ${index + 1} · ${item.priority} · ${item.kind}`));
      for (const [paper, page, text, prefix] of [
        [old, item.before_page, item.before, "旧"], [latest, item.after_page, item.after, "新"]
      ]) {
        if (!page || !text) continue;
        const link = el("button", "diff-source", `${prefix}版 第 ${page} 页 ↗`);
        link.type = "button"; link.onclick = () => selectPaper(paper.id, page);
        block.append(link, el("p", "", text));
      }
      box.append(block);
    });
  } catch (error) { box.replaceChildren(el("p", "hint", error.message)); }
};
function showReader(paper, page = 1) {
  const iframe = $("#pdf-view"), empty = $("#reader-empty"), link = $("#open-pdf");
  $("#source-preview").hidden = true;
  $("#bilingual-reading").hidden = true;
  $("#bilingual-panel").hidden = !paper;
  if (!paper) {
    iframe.hidden = true; iframe.removeAttribute("src"); empty.hidden = false;
    $("#reader-title").textContent = "选择一篇论文阅读";
    $("#reader-page").textContent = "—"; link.removeAttribute("href");
    state.navigationLoadedId = "";
    $("#reader-navigation").hidden = true;
    $("#reader-size-hint").hidden = true;
    $("#structure-panel").hidden = true;
    $("#explain-all-equations").hidden = true;
    $("#equations-all-results").replaceChildren();
    $("#reference-drilldown-panel").hidden = true;
    return;
  }
  $("#reader-size-hint").hidden = false;
  $("#structure-panel").hidden = false;
  $("#reference-drilldown-panel").hidden = false;
  const source = `/api/papers/${paper.id}/file#page=${page}`;
  iframe.hidden = false; iframe.src = source; empty.hidden = true;
  link.href = source;
  $("#reader-title").textContent = paper.title || paper.filename;
  $("#reader-page").textContent = `第 ${page} / ${paper.pages || "?"} 页`;
  state.currentPage = page;
  $("#inspect-page").max = String(paper.pages || 1);
  $("#inspect-page").value = String(page);
  $("#layout-results").replaceChildren(el("p", "hint", `第 ${page} 页尚未检查。`));
}
function renderStructure(data, paperId) {
  const box = $("#structure-results");
  box.replaceChildren(el("p", "hint", data.note));
  if (data.symbol_note) box.append(el("p", "paper-alert", data.symbol_note));
  const allButton = $("#explain-all-equations");
  allButton.hidden = !data.equations?.length;
  if (data.equations?.length) allButton.textContent =
    `按顺序解释${data.equations.length <= 20 ? "全部已识别的" : "前 20 条已识别的"}编号公式（当前识别 ${data.equations.length} 条；需有效模型）`;
  if (Object.values(data.truncated || {}).some(Boolean))
    box.append(el("p", "paper-alert", "部分类型已达到展示上限；这里不是完整清单，请打开原 PDF 核查。"));
  box.append(el("p", "hint",
    "作者、机构、摘要和标题树请在上方阅读器“论文信息 / 章节目录”查看；此处只展示图表、公式、参考文献和附录候选。"));
  const layoutPages = new Map();
  async function showOriginalCrop(entry, row, button) {
    if (state.selected !== paperId) return;
    button.disabled = true;
    button.textContent = "正在从 PDF 截图…";
    try {
      if (!layoutPages.has(entry.page_no))
        layoutPages.set(entry.page_no, api(
          `/api/papers/${paperId}/layout?page=${entry.page_no}`
        ));
      const layout = await layoutPages.get(entry.page_no);
      if (state.selected !== paperId) return;
      const reference = entry.excerpt.match(/^(fig(?:ure)?\.?|table)\s*(\d{1,3})/i);
      const index = (layout.visuals || []).findIndex(visual => {
        const kind = reference?.[1]?.toLowerCase().startsWith("table") ?
          "table_crop_candidate" : "figure_crop_candidate";
        return visual.type === kind &&
          Number(visual.label.match(/\d+/)?.[0]) === Number(reference?.[2]);
      });
      if (index < 0) throw new Error("该页未检测到对应的可截取区域；请点击页码打开原 PDF。");
      const url = `/api/papers/${paperId}/visual-crop?page=${entry.page_no}&visual=${index}`;
      const image = el("img", "structure-crop-image");
      image.loading = "lazy";
      image.alt = `${entry.excerpt.slice(0, 100)}，从原 PDF 第 ${entry.page_no} 页截取的候选图表`;
      image.onerror = () => {
        image.remove();
        row.append(el("p", "paper-alert", "截图加载失败，请点击页码核对 PDF。"));
      };
      image.src = url;
      const warning = el("p", "hint", "原 PDF 局部截图（候选区域；可能包含相邻正文或不完整，请核对整页）。");
      const open = el("a", "btn light", "在新标签放大截图 ↗");
      open.href = url; open.target = "_blank"; open.rel = "noopener";
      row.append(image, warning, open);
      button.hidden = true;
    } catch (error) {
      button.textContent = "重试截图";
      row.append(el("p", "hint", error.message));
    } finally {
      button.disabled = false;
    }
  }
  function addGroup(title, entries, labelFor, depth = 0, cropped = false) {
    const section = el("details", "structure-group");
    if (cropped) section.open = true;
    section.append(el("summary", "", `${title}（${entries.length}）`));
    if (!entries.length) section.append(el("p", "hint", "未识别；不代表原文没有该结构。"));
    const addRows = (items, nested) => {
      items.forEach((item, index) => {
        const link = el("button", "nav-link structure-link", `${labelFor(item)} · p.${item.page_no}`);
        link.type = "button";
        link.style.paddingLeft = `${Math.min(3, nested) * 18 + 8}px`;
        link.onclick = () => selectPaper(paperId, item.page_no);
        if (cropped) {
          const row = el("div", "structure-crop-row");
          row.append(link);
          const crop = el("button", "btn light", "从原 PDF 截图");
          crop.type = "button";
          crop.onclick = () => showOriginalCrop(item, row, crop);
          row.append(crop);
          section.append(row);
          if (index < 6) crop.onclick();
        } else if (title.startsWith("公式")) {
          const row = el("div", "structure-crop-row");
          row.append(link);
          if (item.pdf_text_preview && item.pdf_text_preview !== item.excerpt)
            row.append(el("p", "nav-snippet",
              `原 PDF 同行文本拼合（仍可能丢失上下标/分式）：${item.pdf_text_preview}`));
          const match = item.excerpt.match(/\((\d{1,3})\)\s*$/);
          if (match) {
            const url = `/api/papers/${paperId}/equation-crop?page=${item.page_no}&number=${match[1]}`;
            const open = el("button", "btn light", "查看原 PDF 公式截图");
            open.type = "button";
            open.onclick = () => {
              const image = el("img", "equation-source-image");
              image.alt = `原 PDF 第 ${item.page_no} 页公式 (${match[1]}) 截图候选；需对照整页`;
              image.loading = "lazy";
              image.onerror = () => {
                image.remove();
                row.append(el("p", "paper-alert", "此编号公式无法可靠截图，打开原 PDF 核查"));
              };
              image.src = url;
              row.append(image, el("p", "hint", "来自原 PDF 像素；抽取文本有方框或符号缺损时请以原图为准。"));
              open.hidden = true;
            };
            row.append(open);
          }
          section.append(row);
        } else {
          section.append(link);
        }
        if (item.children) addRows(item.children, nested + 1);
      });
    };
    addRows(entries, depth);
    box.append(section);
  }
  addGroup("图注与表题候选 · 前 6 项自动截原图", data.captions, item => item.excerpt, 0, true);
  addGroup("公式编号候选（非 LaTeX）", data.equations, item => item.excerpt);
  addGroup("附录候选", data.appendices, item => item.excerpt);
  addGroup("参考文献区域位置", data.references.headings,
    item => item.excerpt);
  box.append(el("p", "hint",
    "按编号或作者—年份形式查看候选、查询官方元数据并确认下载：请到左侧文献库的“参考文献下钻”操作。"));
}
$("#explain-all-equations").onclick = async () => {
  const paperId = state.selected;
  if (!paperId) return toast("请先选中已解析的论文");
  if (!window.confirm(
    "一次点击会将最多 20 条已识别公式分成每组最多 4 条，按顺序发起最多 5 次模型请求；"
    + "没有缓存的组可能计费；相同原文、相同模型已通过校验的组将复用。"
    + "若某组失败，会停止后续调用。确认发送剩余的公式及同页短上下文吗？"
  )) return;
  const button = $("#explain-all-equations");
  const area = $("#equations-all-results");
  button.disabled = true;
  area.replaceChildren(el("p", "hint", "正在按 PDF 页准备全部公式证据；即使模型失败也会显示原始候选…"));
  try {
    const result = await api(`/api/papers/${paperId}/equations/explain-all`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({confirm_cost: true}),
    });
    if (state.selected !== paperId) return;
    area.replaceChildren(
      el("h3", "", `联合公式审查：${result.count}/${result.total_candidates} 条已识别候选（非全文全部公式）`),
      el("p", "hint", result.warning),
      el("p", result.status === "draft_needs_review" ? "capability-note" : "paper-alert",
        `${result.message} · 审计 #${result.audit_id}`)
    );
    if (result.attempted_groups) area.append(el(
      "p", "hint",
      `本次实际向模型请求 ${result.attempted_groups} 组；复用 ${
        result.reused_groups || 0} 组；累计完成 ${
        result.completed_groups}/${result.total_groups} 组。`
    ));
    if (result.redacted_numeric_fields?.length) area.append(el("p", "paper-alert",
      `以下字段出现当前公式/同页短上下文没有的数值，已隐藏该字段而保留其余草稿：${
        result.redacted_numeric_fields.join("、")}。需核对是否跨公式引用或模型臆测。`));
    if (result.system_added_labels?.length) area.append(el("p", "paper-alert",
      `模型漏标 ${result.system_added_labels.length} 处本条证据编号（${
        result.system_added_labels.slice(0, 12).join("、")}）；系统仅在短引文与原文匹配、`
      + "且未错引别条公式时补上编号。补标不代表论断获得语义证明，请核对原文。"));
    if (result.system_quote_anchors?.length) area.append(el("p", "paper-alert",
      `模型给出的 ${result.system_quote_anchors.join("、")} 短引文无法逐字定位；`
      + "系统改为显示对应 PDF 抽取的公式原始文字作为定位锚点。"
      + "该锚点不是模型论断的证据证明，请亲自核对 PDF 原图。"));
    if (result.thinking_mode === "disabled") area.append(el(
      "p", "hint",
      "本次 DeepSeek Flash 结构化解释已关闭默认高强度思考模式，避免推理耗尽输出上限；"
      + "这不保证解释正确，仍须逐条核对 PDF。"
    ));
    if (result.missing_number_candidates?.length) area.append(el(
      "p", "paper-alert",
      `检测到编号间隔：(${result.missing_number_candidates.join(")、(")})；可能漏检、跨页排版错序或原文编号不连续，`
      + "不能自动断言这些公式不存在。请到 PDF 核对。"
    ));
    if (result.truncated) area.append(el("p", "paper-alert",
      "候选超过单次 20 条上限，未覆盖的公式不能称已解释；仍可点击下方原始公式跳转 PDF。"));
    if (result.usage?.total_tokens) area.append(el("p", "metering",
      `本次模型返回 ${result.usage.total_tokens} tokens；${
        result.usage.estimated_cost_usd == null ? "费用无可靠单价，须查看服务商账单" :
          `本地价格估算 $${result.usage.estimated_cost_usd}`
      }`));
    else if (result.attempted_groups) area.append(el("p", "metering",
      "模型未返回可核验的 Token 用量；不能据此断言未计费，请核对服务商账单。"));
    result.equations.forEach((entry, i) => {
      const explanation = result.draft?.equations?.[i];
      const card = el("details", "equation-batch-row");
      card.open = Boolean(explanation);
      card.append(el("summary", "",
        `${entry.source_id} · PDF 第 ${entry.page_no} 页 · ${
          entry.formula.slice(0, 100)}`));
      card.append(el("p", "equation-raw", entry.formula));
      if (entry.pdf_text_preview &&
          entry.pdf_text_preview !== entry.formula)
        card.append(el("p", "nav-snippet",
          `PDF 文字位置拼合（不代表准确数学公式）：${entry.pdf_text_preview}`));
      const jump = el("button", "btn light", `核对 PDF 第 ${entry.page_no} 页`);
      jump.type = "button";
      jump.onclick = () => selectPaper(paperId, entry.page_no);
      card.append(jump);
      const printedNumber = entry.formula.match(/\((\d{1,3})\)\s*$/);
      if (printedNumber) {
        const sourceImage = el("img", "equation-source-image");
        sourceImage.loading = "lazy";
        sourceImage.alt = `原 PDF 第 ${entry.page_no} 页编号公式 ${printedNumber[1]} 的像素截图，非 LaTeX`;
        sourceImage.src =
          `/api/papers/${paperId}/equation-crop?page=${entry.page_no}&number=${printedNumber[1]}`;
        sourceImage.onerror = () => {
          sourceImage.remove();
          card.append(el("p", "paper-alert", "公式截图不可用，请点页码打开原 PDF 核对。"));
        };
        card.append(sourceImage);
      }
      if (entry.context) card.append(el("p", "nav-snippet",
        `同页文本候选（可能双栏错序）：${entry.context}`));
      if (explanation) {
        for (const [field, title] of [
          ["input", "输入/符号"], ["transformation", "如何变换"],
          ["output", "输出/供下一步使用"], ["why", "为什么这样做"],
          ["uncertainty", "未知与风险"], ["source_quote", "可定位的原文锚点（须核对 PDF）"],
        ]) card.append(el("p", "equation-review-field",
          `${title}：${explanation[field]}`));
      }
      area.append(card);
    });
    if (result.draft) area.append(
      el("h3", "", "跨公式衔接（仅待核验草稿）"),
      el("p", "equation-review-field", result.draft.chain),
      el("p", "paper-alert", `衔接不确定性：${result.draft.chain_uncertainty}`)
    );
    loadAudit();
  } catch (error) {
    area.replaceChildren(el("p", "paper-alert", error.message));
  } finally { button.disabled = false; }
};
$("#inspect-page").onchange = () => {
  const paper = state.papers.find(item => item.id === state.selected);
  const page = Number($("#inspect-page").value);
  if (paper && Number.isInteger(page) && page >= 1 && page <= paper.pages) {
    state.currentPage = page;
    showReader(paper, page);
  }
};
$("#load-structure").onclick = async () => {
  const paperId = state.selected;
  if (!paperId) return toast("请先选择已解析论文");
  const box = $("#structure-results");
  $("#explain-all-equations").hidden = true;
  $("#equations-all-results").replaceChildren();
  box.replaceChildren(el("p", "hint", "正在从已索引原文提取结构候选…"));
  try {
    const data = await api(`/api/papers/${paperId}/structure`);
    if (state.selected === paperId) renderStructure(data, paperId);
  } catch (error) {
    if (state.selected === paperId) box.replaceChildren(el("p", "hint", error.message));
  }
};
$("#inspect-layout").onclick = async () => {
  if (!state.selected) return toast("请先选择论文");
  const id = state.selected;
  const selectedPaper = state.papers.find(item => item.id === id);
  const page = Number($("#inspect-page").value);
  if (!Number.isInteger(page) || page < 1 || page > (selectedPaper?.pages || 0))
    return $("#layout-results").replaceChildren(el("p", "paper-alert",
      `请输入 1–${selectedPaper?.pages || "?"} 的 PDF 物理页码。`));
  const box = $("#layout-results");
  box.replaceChildren(el("p", "hint", `正在分析第 ${page} 页…`));
  try {
    const data = await api(`/api/papers/${id}/layout?page=${page}`);
    if (state.selected !== id || Number($("#inspect-page").value) !== page) return;
    box.replaceChildren(el("p", "hint", data.note));
    if (!data.candidates.length && !data.tables.length)
      box.append(el("p", "hint", "当前提取方式未发现高置信度结构，不能据此断言原文没有图表或公式。"));
    data.candidates.forEach(candidate => {
      const row = el("div", "layout-item");
      row.append(
        el("strong", "", `${candidate.label} · ${candidate.type}`),
        el("p", "nav-snippet", candidate.excerpt)
      );
      box.append(row);
    });
    (data.visuals || []).forEach((visual, index) => {
      const row = el("div", "layout-visual");
      const image = el("img", "layout-visual-image");
      image.alt = `${visual.label} 图表候选裁剪`;
      const open = el("a", "btn light", "在新标签页放大原图 ↗");
      open.href = `/api/papers/${id}/visual-crop?page=${page}&visual=${index}`;
      open.target = "_blank";
      open.rel = "noopener";
      const button = el("button", "btn light", `查看${visual.type === "table_crop_candidate" ? "表格" : "图表"}裁剪`);
      button.type = "button";
      button.onclick = async () => {
        button.disabled = true;
        try {
          const response = await fetch(
            `/api/papers/${id}/visual-crop?page=${page}&visual=${index}`
          );
          if (!response.ok) throw new Error("图表裁剪失败");
          if (state.selected !== id || Number($("#inspect-page").value) !== page) return;
          const objectURL = URL.createObjectURL(await response.blob());
          image.onload = () => URL.revokeObjectURL(objectURL);
          image.src = objectURL;
          image.hidden = false;
        } catch (error) { toast(error.message); }
        finally { button.disabled = false; }
      };
      row.append(el("strong", "", `${visual.label} · ${visual.visual_content_detected ? "检测到绘图/图像候选" : "文本区域候选"}`), button, open, image);
      image.hidden = true;
      box.append(row);
    });
    data.tables.forEach((table, index) => {
      const row = el("div", "layout-item");
      row.append(el("strong", "", `表格候选 ${index + 1} · ${table.rows} 行 × ${table.columns} 列`));
      table.cells.slice(0, 4).forEach(cells =>
        row.append(el("p", "nav-snippet", cells.join(" | "))));
      if (table.truncated) row.append(el("p", "hint", "仅预览前 15 行/12 列。"));
      box.append(row);
    });
  } catch (error) { box.replaceChildren(el("p", "hint", error.message)); }
};
$("#inspect-layout-preview").onclick = async () => {
  if (!state.selected) return toast("请先选择论文");
  const id = state.selected, page = Number($("#inspect-page").value);
  const paper = state.papers.find(item => item.id === id);
  if (!Number.isInteger(page) || page < 1 || page > (paper?.pages || 0))
    return toast("请先输入有效 PDF 物理页码");
  const image = $("#layout-preview-image");
  image.hidden = false;
  image.removeAttribute("src");
  $("#layout-results").prepend(el("p", "hint", `正在生成第 ${page} 页结构标注图…`));
  try {
    const response = await fetch(`/api/papers/${id}/layout-preview?page=${page}`);
    if (!response.ok) throw new Error("结构标注图生成失败");
    image.src = URL.createObjectURL(await response.blob());
    image.onload = () => URL.revokeObjectURL(image.src);
  } catch (error) {
    image.hidden = true;
    toast(error.message);
  }
};
$("#inspect-prev").onclick = () => {
  const max = Number($("#inspect-page").max) || 1;
  $("#inspect-page").value = String(Math.max(1, Math.min(max,
    (Number($("#inspect-page").value) || 1) - 1)));
  $("#inspect-layout").onclick();
};
$("#inspect-next").onclick = () => {
  const max = Number($("#inspect-page").max) || 1;
  $("#inspect-page").value = String(Math.min(max, (Number($("#inspect-page").value) || 0) + 1));
  $("#inspect-layout").onclick();
};
$("#close-preview").onclick = () => {
  $("#source-preview").hidden = true;
  $("#pdf-view").hidden = false;
};
async function showEvidence(item) {
  selectPaper(item.paper_id, item.page_no);
  document.querySelector(".reader").scrollIntoView({ behavior: "smooth", block: "start" });
  if (!item.chunk_id) return;
  const panel = $("#source-preview"), img = $("#preview-image");
  panel.hidden = false; $("#pdf-view").hidden = true;
  $("#preview-status").textContent = `第 ${item.page_no} 页 · 正在查找证据区域…`;
  img.removeAttribute("src");
  try {
    const response = await fetch(
      `/api/papers/${item.paper_id}/evidence-preview?chunk=${encodeURIComponent(item.chunk_id)}`
      + `&question=${encodeURIComponent($("#question").value.trim())}`
    );
    if (!response.ok) throw new Error("证据图像暂不可用");
    const blob = await response.blob();
    const objectURL = URL.createObjectURL(blob);
    img.onload = () => URL.revokeObjectURL(objectURL);
    img.src = objectURL;
    $("#preview-status").textContent = response.headers.get("X-Evidence-Highlight") === "yes"
      ? `第 ${item.page_no} 页 · ${response.headers.get("X-Evidence-Method") === "ocr" ? "OCR识别行" : "矢量短句"}候选高亮（仍请核对）`
      : `第 ${item.page_no} 页 · 未精确匹配，展示整页，请对照原文检查`;
  } catch (error) {
    panel.hidden = true; $("#pdf-view").hidden = false;
    toast(error.message);
  }
}
async function loadNavigation(paperId) {
  const panel = $("#reader-navigation");
  panel.hidden = false;
  loadProfile(paperId);
  $("#headings").replaceChildren(el("p", "hint", "读取章节目录中…"));
  try {
    const data = await api(`/api/papers/${paperId}/navigation`);
    if (state.selected !== paperId) return;
    state.navigationLoadedId = paperId;
    const headings = $("#headings");
    headings.replaceChildren();
    if (!data.headings.length) headings.append(el("p", "hint", "未检测到可信的章节编号"));
    data.headings.forEach(h => {
      const link = el("button", "nav-link indent-" + h.level, `${h.title} · p.${h.page_no}`);
      link.type = "button"; link.onclick = () => selectPaper(paperId, h.page_no);
      headings.append(link);
    });
    panel.title = data.note;
    loadReferences(paperId);
  } catch (error) {
    if (state.selected === paperId)
      $("#headings").replaceChildren(el("p", "hint", error.message));
  }
}
function autoPrepareSelectedPaper(paperId) {
  // These operations are local, deterministic and do not send data to an
  // external model.  Start them when the user selects a ready paper; paid or
  // destructive actions (translation, formula explanations, downloads) remain
  // explicit.
  if (state.selected !== paperId) return;
  const paper = state.papers.find(item => item.id === paperId);
  if (!paper || paper.status !== "ready") return;
  const status = $("#structure-results");
  status.replaceChildren(el("p", "hint", "已自动开始准备结构、引用和 Future Work；可直接展开对应面板查看。"));
  $("#load-structure").click();
  $("#future-btn").click();
  drawGraph();
  $("#frontier-refresh").click();
}
async function loadProfile(paperId) {
  const box = $("#profile");
  box.replaceChildren(el("p", "hint", "读取论文信息中…"));
  try {
    const data = await api(`/api/papers/${paperId}/profile`);
    if (state.selected !== paperId) return;
    box.replaceChildren(
      el("p", "profile-title", data.title),
      el("p", "nav-snippet", `${data.arxiv_id ? "arXiv:" + data.arxiv_id : "无 arXiv ID"} · ${data.pages} 页 · OCR ${data.ocr_pages} 页`),
      el("p", "nav-snippet", data.authors.length ? "作者： " + data.authors.join("；") : "作者：未可靠识别"),
      el("p", "nav-snippet", data.affiliations.length ? "机构： " + data.affiliations.join("；") : "机构：未可靠识别"),
      el("p", "nav-snippet", data.emails.length ? "邮箱： " + data.emails.join("；") : ""),
      el("p", "profile-abstract", data.abstract || "未检测到摘要"),
      el("p", "hint", data.note)
    );
    if (data.abstract) {
      const translate = el("button", "btn light", "翻译摘要（需模型配置）");
      translate.type = "button";
      translate.onclick = async () => {
        translate.disabled = true;
        const result = el("p", "profile-abstract", "正在请求学术翻译…");
        box.append(result);
        try {
          const translated = await api("/api/translate", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              text: data.abstract, source_language: "auto", target_language: "zh-CN"
            })
          });
          result.textContent = translated.translation;
          box.append(el("p", "hint", `${translated.note} 审计事件 #${translated.audit_id}`));
        } catch (error) {
          result.textContent = error.message;
          translate.disabled = false;
        }
      };
      box.append(translate);
    }
  } catch (error) {
    if (state.selected === paperId) box.replaceChildren(el("p", "hint", error.message));
  }
}
$("#refresh-references").onclick = () => {
  if (state.selected) loadReferences(state.selected);
};
async function loadReferences(paperId) {
  const box = $("#reference-candidates");
  box.replaceChildren(el("p", "hint", "正在提取可核对的引用…"));
  try {
    const data = await api(`/api/papers/${paperId}/references`);
    if (state.selected !== paperId) return;
    box.replaceChildren(el("p", "hint", data.note));
    if (!data.references.length) box.append(el("p", "hint", "未检测到数字型参考文献。"));
    for (const ref of data.references) {
      const row = el("div", "reference-item");
      const synthetic = ref.number_source === "author_year_arxiv_candidate";
      const jump = el("button", "nav-link",
        `${synthetic ? (ref.citation_label || "作者—年份候选") : `[${ref.number}]`} · 原文第 ${ref.page_no} 页 · ${
          ref.arxiv_id || "无明确 arXiv ID"}`);
      jump.type = "button";
      jump.onclick = () => selectPaper(paperId, ref.page_no);
      row.append(jump, el("p", "nav-snippet", ref.excerpt));
      if (ref.first_mention_page) {
        const mention = el("button", "nav-link",
          `↩ 首次正文 [${ref.number}] · 第 ${ref.first_mention_page} 页`);
        mention.onclick = () => selectPaper(paperId, ref.first_mention_page);
        row.append(mention);
      }
      if (synthetic) row.append(el("p", "hint",
        "作者—年份候选：序号不是 PDF 原文编号，仅用于本页列表与人工核查。"));
      if (ref.arxiv_id) {
        if (ref.already_imported) {
          row.append(el("p", "hint", "该 arXiv 编号已在文献库中；不重复下载。"));
        } else {
          const button = el("button", "btn light", "核查官方元数据");
          button.type = "button";
          button.onclick = async () => {
            button.disabled = true;
            const result = el("div", "reference-metadata", "正在查询官方 arXiv 元数据…");
            row.append(result);
            try {
              const {paper} = await api(
                "/api/arxiv/metadata?identifier=" + encodeURIComponent(ref.arxiv_id)
              );
              if (state.selected !== paperId) return;
              result.replaceChildren(
                el("strong", "", paper.title),
                el("p", "hint", `${paper.identifier} · ${paper.authors.join(", ")} · ${paper.published}`),
                el("p", "hint", paper.summary)
              );
              const confirm = el("button", "btn light", "确认此引用并下载入库");
              confirm.type = "button";
              confirm.onclick = async () => {
                if (!window.confirm(
                  `将 ${synthetic ? "作者—年份候选（非原文编号）" : `[${ref.number}]`} 对应的 ${
                    paper.title}（${paper.identifier}）下载入库？`
                )) return;
                confirm.disabled = true;
                try {
                  await api(`/api/papers/${paperId}/references/import`, {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({number: ref.number, identifier: paper.identifier})
                  });
                  toast(`正在导入${synthetic ? "作者—年份候选" :
                    `引用 [${ref.number}]`}：${paper.identifier}`);
                  await refresh();
                  await loadReferences(paperId);
                } catch (error) {
                  toast(error.message);
                  confirm.disabled = false;
                }
              };
              result.append(confirm);
            } catch (error) {
              result.replaceChildren(el("p", "hint", error.message));
              button.disabled = false;
            }
          };
          row.append(button);
        }
      }
      box.append(row);
    }
  } catch (error) {
    if (state.selected === paperId) box.replaceChildren(el("p", "hint", error.message));
  }
}
function selectPaper(id, page = 1) {
  const changed = state.selected !== id;
  state.selected = id;
  const paper = state.papers.find(x => x.id === id);
  if (paper) {
    if (changed) $("#structure-results").replaceChildren(el("p", "hint",
      "已切换论文，点击“提取当前论文结构”查看本篇结果。"));
    if (changed) {
      $("#explain-all-equations").hidden = true;
      $("#equations-all-results").replaceChildren();
    }
    if (changed) $("#reference-candidates").replaceChildren(el("p", "hint",
      "已切换论文，点击“刷新当前论文引用候选”查看本篇 References。"));
    showReader(paper, page);
    if (changed || state.navigationLoadedId !== id) loadNavigation(id);
    if (changed) {
      state.translationJobId = "";
      loadTranslationJobs(id);
      if (paper.status === "ready") {
        $("#scope").value = id;
        const hadWritingSelection =
          $("#writing-choices").querySelectorAll("input:checked").length > 0;
        updateWritingChoices();
        if (!hadWritingSelection) {
          const current = [...$("#writing-choices").querySelectorAll("input")]
            .find(node => node.value === id);
          if (current) current.checked = true;
        }
        autoPrepareSelectedPaper(id);
      }
    }
  }
  document.querySelectorAll(".paper").forEach((node, index) =>
    node.classList.toggle("active", state.papers[index]?.id === id));
  showVersionPanel();
}
$("#bilingual-refresh").onclick = () => {
  if (state.selected) loadTranslationJobs(state.selected);
};
$("#bilingual-create").onclick = async () => {
  const paper = state.papers.find(x => x.id === state.selected);
  if (!paper || paper.status !== "ready") return toast("请选择已解析论文");
  if (!state.modelConfigured) return toast("未配置模型，不能生成翻译");
  const first = Number($("#bilingual-first").value),
        last = Number($("#bilingual-last").value);
  const button = $("#bilingual-create"); button.disabled = true;
  try {
    const estimate = await api(
      `/api/papers/${paper.id}/translation-estimate?first=${first}&last=${last}`
    );
    if (!window.confirm(
      `翻译 ${first}–${last} 页，约 ${estimate.characters} 字符、最多 ${estimate.estimate_calls} 次模型请求，`
      + "费用由你承担。确认排队吗？"
    )) return;
    const job = await api("/api/translation-jobs", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        paper_id: paper.id, first_page: first, last_page: last,
        target_language: $("#bilingual-target").value, confirm_cost: true
      })
    });
    state.translationJobId = job.id;
    toast(`已排队：${job.estimate_calls} 个原译文本块，进度会持续更新`);
    await loadTranslationJobs(paper.id);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
};
async function loadTranslationJobs(paperId) {
  const box = $("#bilingual-jobs");
  if (!paperId) { box.replaceChildren(); return; }
  try {
    const list = await api(`/api/translation-jobs?paper_id=${paperId}`);
    if (state.selected !== paperId) return;
    box.replaceChildren();
    if (!list.jobs.length) {
      box.append(el("p", "hint", "尚无翻译任务；配置模型服务后可选择页码开始。"));
      return;
    }
    const failed = list.jobs.filter(job => job.status === "error");
    const history = failed.length ? el("details", "bilingual-failed-history") : null;
    if (history) history.append(el("summary", "",
      `失败历史（${failed.length} 条；默认收起，成功的翻译块不会自动丢失）`));
    for (const job of [
      ...list.jobs.filter(item => item.status !== "error"), ...failed
    ]) {
      const row = el("div", "bilingual-job");
      row.append(el("strong", "",
        `${job.first_page}–${job.last_page} 页 → ${job.target_language} · ${job.status} · ${job.processed_units}/${job.total_units} 块`));
      if (job.error) row.append(el("p", "paper-alert", job.error));
      const view = el("button", "btn light", "对照阅读");
      view.onclick = () => {
        state.translationJobId = job.id;
        state.translationPage = job.first_page;
        showBilingualPage(job.id, job.first_page);
      };
      row.append(view);
      if (job.status === "completed") {
        for (const [fmt, label] of [["html", "导出 HTML"], ["md", "导出 Markdown"]]) {
          const link = el("a", "btn light", label);
          link.href = `/api/translation-jobs/${job.id}/export?format=${fmt}`;
          row.append(link);
        }
      } else if (job.status === "paused" || job.status === "error") {
        const resume = el("button", "btn light", "继续翻译");
        resume.onclick = async () => {
          if (!window.confirm(`将继续翻译剩余的 ${Math.max(0,
            job.total_units - job.processed_units)} 块；之前成功的 ${
            job.processed_units} 块不会重新发送，但失败块的再次请求可能计费。继续吗？`)) return;
          try {
            await api(`/api/translation-jobs/${job.id}/resume`, {method: "POST"});
            await loadTranslationJobs(paperId);
          } catch (error) { toast(error.message); }
        };
        row.append(resume);
      }
      if (job.status !== "running" && job.status !== "queued") {
        const remove = el("button", "btn light", "删除这条记录");
        remove.type = "button";
        remove.onclick = async () => {
          if (!window.confirm(`删除 ${job.first_page}–${job.last_page} 页翻译任务？`
            + `这会永久删除已保存的 ${job.processed_units} 个译文块（如有），`
            + "无法恢复，也不会删除 PDF 或其他任务。确定吗？")) return;
          try {
            await api(`/api/translation-jobs/${job.id}`, {method: "DELETE"});
            if (state.translationJobId === job.id) state.translationJobId = "";
            await loadTranslationJobs(paperId);
          } catch (error) { toast(error.message); }
        };
        row.append(remove);
      }
      (job.status === "error" ? history : box).append(row);
    }
    if (history) box.append(history);
  } catch (error) { box.replaceChildren(el("p", "hint", error.message)); }
}
async function showBilingualPage(jobId, page) {
  try {
    const detail = await api(`/api/translation-jobs/${jobId}`);
    const data = await api(`/api/translation-jobs/${jobId}/page?n=${page}`);
    if (state.selected !== detail.paper_id) return;
    state.translationJobId = jobId;
    state.translationPage = page;
    $("#bilingual-reading").hidden = false;
    $("#pdf-view").hidden = true;
    $("#reader-empty").hidden = true;
    $("#bilingual-page-label").textContent = `PDF 第 ${page} 页 · 已译 ${data.units.length} 块`;
    $("#bilingual-prev").disabled = page <= detail.first_page;
    $("#bilingual-next").disabled = page >= detail.last_page;
    const source = $("#bilingual-source"), target = $("#bilingual-target-pane");
    source.replaceChildren(); target.replaceChildren();
    if (!data.units.length) source.append(el("p", "hint", "本页译文尚未生成，请等待任务进度。"));
    for (const unit of data.units) {
      const left = el("div", "bilingual-unit");
      left.append(el("small", "", `原文 p.${page} / 块 ${unit.ordinal + 1}`),
        el("p", "", unit.original));
      if (unit.translated) left.title = `已生成译文（悬停预览）：${unit.translated.slice(0, 650)}`;
      const jump = el("button", "nav-link", `查看原 PDF 第 ${page} 页`);
      jump.onclick = () => selectPaper(detail.paper_id, page);
      left.append(jump);
      source.append(left);
      const right = el("div", "bilingual-unit");
      right.append(el("small", "", `译文 p.${page} / 块 ${unit.ordinal + 1}`),
        el("p", "", unit.translated));
      right.title = `对应原文（悬停预览）：${unit.original.slice(0, 650)}`;
      target.append(right);
    }
    source.scrollTop = 0; target.scrollTop = 0;
  } catch (error) { toast(error.message); }
}
$("#bilingual-prev").onclick = () => showBilingualPage(
  state.translationJobId, state.translationPage - 1);
$("#bilingual-next").onclick = () => showBilingualPage(
  state.translationJobId, state.translationPage + 1);
$("#bilingual-close").onclick = () => {
  $("#bilingual-reading").hidden = true;
  $("#pdf-view").hidden = false;
};
$("#bilingual-selection-translate").onclick = async () => {
  const selection = window.getSelection();
  const chosen = selection?.toString().trim() || "";
  if (!selection?.anchorNode || !$("#bilingual-source").contains(selection.anchorNode))
    return toast("请在原文栏选中需要翻译的文字");
  if (chosen.length < 2 || chosen.length > 12000)
    return toast("选中文本长度需在 2–12000 字之间");
  const box = $("#bilingual-selection-result");
  box.textContent = "正在翻译选中文字…";
  try {
    const result = await api("/api/translate", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text: chosen, source_language: "auto",
        target_language: $("#bilingual-target").value
      })
    });
    box.textContent = `${result.translation}\n${result.note}`;
  } catch (error) { box.textContent = error.message; }
};
let bilingualScrollLock = false;
for (const [which, other] of [
  ["#bilingual-source", "#bilingual-target-pane"],
  ["#bilingual-target-pane", "#bilingual-source"]
]) {
  $(which).addEventListener("scroll", () => {
    if (bilingualScrollLock) return;
    const current = $(which), target = $(other);
    if (!current.children.length || !target.children.length) return;
    let index = 0;
    for (let i = 0; i < current.children.length; i++) {
      if (current.children[i].offsetTop <= current.scrollTop + 16) index = i;
    }
    bilingualScrollLock = true;
    target.scrollTop = target.children[Math.min(index, target.children.length - 1)].offsetTop;
    requestAnimationFrame(() => { bilingualScrollLock = false; });
  });
}
function updateCompareChoices() {
  const area = $("#compare-choices"), chosen = new Set(
    [...area.querySelectorAll("input:checked")].map(x => x.value));
  area.replaceChildren();
  for (const paper of state.papers.filter(x => x.status === "ready")) {
    const label = el("label", "compare-choice"), checkbox = el("input");
    checkbox.type = "checkbox"; checkbox.value = paper.id; checkbox.checked = chosen.has(paper.id);
    label.append(checkbox, el("span", "", `${paper.title} (${paper.filename})`));
    area.append(label);
  }
}
function updateTaskChoices() {
  const area = $("#task-choices");
  const selected = new Set(
    [...area.querySelectorAll("input:checked")].map(node => node.value)
  );
  area.replaceChildren();
  for (const paper of state.papers.filter(p => p.status === "ready")) {
    const label = el("label", "compare-choice"), checkbox = el("input");
    checkbox.type = "checkbox"; checkbox.value = paper.id;
    checkbox.checked = selected.has(paper.id);
    label.append(checkbox, el("span", "", `${paper.title} (${paper.filename})`));
    area.append(label);
  }
}
function updateWritingChoices() {
  const area = $("#writing-choices");
  const selected = new Set(
    [...area.querySelectorAll("input:checked")].map(node => node.value)
  );
  area.replaceChildren();
  for (const paper of state.papers.filter(p => p.status === "ready")) {
    const label = el("label", "compare-choice"), checkbox = el("input");
    checkbox.type = "checkbox"; checkbox.value = paper.id;
    checkbox.checked = selected.has(paper.id);
    label.append(checkbox, el("span", "",
      `${paper.title} · ${paper.arxiv_id ? `arXiv:${paper.arxiv_id}` :
        "无 arXiv ID：只能生成空引用框架"}`));
    area.append(label);
  }
}
$("#task-run").onclick = async () => {
  const box = $("#task-results");
  const paperIds = [...$("#task-choices").querySelectorAll("input:checked")]
    .map(node => node.value);
  const instruction = $("#task-instruction").value.trim();
  if (instruction.length < 3 || instruction.length > 400)
    return toast("请输入 3–400 字的科研任务");
  if (paperIds.length > 4) return toast("最多勾选 4 篇论文");
  if ($("#task-use-model").checked &&
      !window.confirm("将先请求 AI 规划白名单内的非破坏性工具，再在找到原文后"
        + "请求 AI 生成带引文的回答；最多两次可能计费的模型请求。"
        + "若没有证据只返回原文/提示，不会编造结论。继续吗？")) return;
  box.replaceChildren(el("p", "hint", "正在执行真实本地工具链…"));
  try {
    const response = await api("/api/tasks/run", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        instruction, paper_ids: paperIds,
        use_model: $("#task-use-model").checked
      })
    });
    box.replaceChildren(
      el("p", "hint", `${response.note} 规划来源：${
        response.plan_source === "rule" ? "本地规则" :
          response.plan_source === "rule_fallback" ? "模型建议不可用，回退本地规则" : "已校验的模型建议"
      }；`
        + `${response.plan_error ? "模型计划回退原因：" + response.plan_error + "；" : ""}`
        + `状态：${auditModes[response.status] || response.status}，审计 #${response.audit_id}`)
    );
    if (response.answer) box.append(
      el("h3", "", "AI 综合回答草稿 · 逐句核对原文"),
      el("p", "answer-text", response.answer),
      el("p", "hint", "只检验引文编号与数字；语义支持、研究结论和对照合理性仍须人工核验。"));
    else if (response.answer_warning) box.append(
      el("p", "paper-alert", response.answer_warning));
    (response.answer_evidence || []).forEach((hit, index) => {
      const jump = el("button", "nav-link",
        `[${index + 1}] 《${hit.title}》PDF 第 ${hit.page_no} 页 ↗`);
      jump.onclick = () => showEvidence(hit);
      box.append(jump, el("p", "nav-snippet", hit.content));
    });
    if (response.usage?.total_tokens) box.append(el("p", "metering",
      `本次记录模型返回 ${response.usage.total_tokens} tokens；若规划接口未返回用量，`
      + "此数字可能不包含规划消耗，实际费用以服务商账单为准。"));
    response.plan.forEach((step, index) => {
      const section = el("div", "task-step");
      section.append(
        el("strong", "", `${index + 1}. ${auditTools[step.tool] || step.tool} · ${
          auditStatuses[step.status] || step.status}`),
        el("p", "hint", `${step.reason}；${step.message}`)
      );
      const result = response.results[index];
      if (result?.tool === "version_comparison" && result.data) {
        const data = result.data;
        section.append(el("p", "hint",
          `${data.first.filename} → ${data.second.filename}：${data.candidates.length} 处候选差异`));
        data.candidates.slice(0, 3).forEach(change => {
          const link = el("button", "nav-link",
            `${change.before} → ${change.after} · 旧/新 PDF 页码 ${change.before_page}/${change.after_page}`);
          link.onclick = () => selectPaper(data.second.id, change.after_page || 1);
          section.append(link);
        });
      } else if ((result?.tool === "compare_papers" || result?.tool === "retrieve")
          && result.data) {
        const rows = result.data.rows || [{
          evidence: result.data.evidence || []
        }];
        rows.forEach(row => {
          if (row.title) section.append(el("strong", "", row.title));
          (row.evidence || []).slice(0, 2).forEach(hit => {
            const link = el("button", "nav-link",
              `${hit.title} · 第 ${hit.page_no} 页 · ${hit.retrieval || "检索"}`);
            link.onclick = () => showEvidence(hit);
            section.append(link, el("p", "nav-snippet", hit.content || ""));
          });
        });
      } else if (result?.tool === "future_work" && result.data) {
        result.data.papers.forEach(row => row.items.slice(0, 3).forEach(item => {
          const link = el("button", "nav-link",
            `${row.title} · 第 ${item.source_page} 页：${item.source_excerpt.slice(0, 100)}`);
          link.onclick = () => selectPaper(row.paper_id, item.source_page);
          section.append(link);
        }));
      } else if (result?.tool === "citation_graph" && result.data) {
        section.append(el("p", "hint",
          `${result.data.nodes.length} 个节点、${result.data.edges.length} 条引用边；详见左侧图谱。`));
      }
      box.append(section);
    });
    loadAudit();
  } catch (error) {
    box.replaceChildren(el("p", "hint", error.message));
  }
};
$("#compare-btn").onclick = async () => {
  const ids = [...$("#compare-choices").querySelectorAll("input:checked")].map(x => x.value);
  const question = $("#question").value.trim();
  if (ids.length < 2 || ids.length > 4) return toast("请选择 2–4 篇论文");
  if (question.length < 3) return toast("先在上方输入比较问题");
  const box = $("#compare-results");
  box.replaceChildren(el("p", "hint", "正在逐篇检索…"));
  try {
    const data = await api("/api/compare", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, paper_ids: ids })
    });
    box.replaceChildren(el("p", "hint", data.note));
    for (const row of data.rows) {
      const section = el("div", "compare-row");
      section.append(el("strong", "", row.title));
      if (!row.evidence.length) section.append(el("p", "hint", "没有检索到相关片段；不代表论文未讨论。"));
      for (const item of row.evidence) {
        const jump = el("button", "nav-link", `原文 p.${item.page_no} ↗`);
        jump.onclick = () => showEvidence(item);
        section.append(jump, el("p", "nav-snippet", item.content));
      }
      box.append(section);
    }
  } catch (error) { box.replaceChildren(el("p", "hint", error.message)); }
};
async function importFile(file) {
  if (file.size > 30 * 1024 * 1024) return toast(`${file.name} 超过 30 MB，请分批处理`);
  try {
    await api(`/api/upload?filename=${encodeURIComponent(file.name)}`, {
      method: "POST", headers: { "Content-Type": "application/pdf" }, body: file
    });
    toast(`已开始解析：${file.name}`); await refresh();
  } catch (error) { toast(`${file.name}：${error.message}`); }
}
$("#upload").addEventListener("change", async (event) => {
  for (const file of event.target.files) await importFile(file);
  event.target.value = "";
});
$("#sample-btn").onclick = async () => {
  if (!$("#sample").value) return toast("请选择一份样例论文");
  try {
    await api("/api/import-sample", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: $("#sample").value }) });
    await refresh(); toast("样例导入已启动");
  } catch (error) { toast(error.message); }
};
$("#arxiv-form").onsubmit = async (event) => {
  event.preventDefault();
  const title = $("#arxiv-title").value.trim();
  const box = $("#arxiv-candidates");
  box.replaceChildren(el("p", "hint", "正在查询 arXiv 官方元数据…"));
  try {
    const data = await api("/api/arxiv/search?title=" + encodeURIComponent(title));
    box.replaceChildren();
    if (!data.candidates.length) {
      box.append(el("p", "hint", "没有候选论文；请检查题名或网络。"));
      return;
    }
    for (const candidate of data.candidates) {
      const block = el("div", "arxiv-item");
      block.append(
        el("strong", "", candidate.title),
        el("p", "paper-meta", `arXiv:${candidate.identifier} · ${candidate.published} · ${candidate.authors.join(", ")}`),
        el("p", "hint", candidate.summary)
      );
      const button = el("button", "btn light", "确认并下载入库");
      button.type = "button";
      button.onclick = async () => {
        if (!window.confirm(`确认下载 ${candidate.title}（${candidate.identifier}）？`)) return;
        button.disabled = true;
        try {
          await api("/api/arxiv/download", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({identifier: candidate.identifier})
          });
          await refresh(); toast("已开始下载入库并解析：" + candidate.identifier);
        } catch (error) {
          button.disabled = false; toast(error.message);
        }
      };
      block.append(button); box.append(block);
    }
  } catch (error) { box.replaceChildren(el("p", "hint", error.message)); }
};
const RECENT_CACHE_KEY = "sourcelab-recent-results-v1";
function renderRecentResults(data, cached = false) {
    const box = $("#recent-results");
    box.replaceChildren(el("p", "hint", `${cached ? "上次查询缓存（非实时，点击查询刷新） · " : ""}${data.note || ""}`));
    if (!data.items.length) box.append(el("p", "hint", "目前没有新的候选，请换一个主题。"));
    for (const item of data.items) {
      const card = el("div", "arxiv-item");
      card.append(el("strong", "", item.title),
        el("p", "paper-meta", `${item.published} · ${item.identifier} · 关键词排序 ${item.score.toFixed(2)}`));
      card.append(el("p", "hint",
        `期刊/会议：${item.venue || item.journal_ref || "arXiv 未提供期刊/会议信息（预印本，不代表未发表）"}${
          item.venue_source ? " · " + item.venue_source : ""}`),
        el("p", "hint",
          `影响因子：${item.impact_factor == null ? "未核验／会议不适用" :
            `${item.impact_factor}（${item.impact_factor_source || "缺来源，请人工核实"}）`}`));
      const publication = el("details", "publication-verification");
      publication.append(el("summary", "", "查询 DBLP / Crossref 出版信息（手动）"));
      const venueResults = el("div", "publication-verification-results");
      const checkVenue = el("button", "btn light", "核对题名、期刊/会议");
      checkVenue.type = "button";
      checkVenue.onclick = async () => {
        checkVenue.disabled = true;
        venueResults.replaceChildren(el("p", "hint", "正在查询公开元数据；不调用 AI，也不查未经授权的影响因子…"));
        try {
          const info = await api("/api/publication/verify", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({title: item.title, doi: item.doi || ""}),
          });
          venueResults.replaceChildren(el("p", "hint", info.note),
            el("p", info.venue ? "capability-note" : "paper-alert",
              info.venue ? `出版候选：${info.venue} · ${info.year || "年份未知"} · ${
                info.type || "类型未提供"} · 来源：${info.venue_source}`
              : "两条查询路径均未严格核验出版信息；不代表论文未发表。"),
            el("p", "hint", `影响因子：${info.impact_note}`));
          for (const match of info.matches) venueResults.append(el("p", "nav-snippet",
            `${match.source}：${match.title} → ${match.venue} · ${match.year || "未知"}`));
          for (const error of info.errors) venueResults.append(el("p", "paper-alert",
            error));
          for (const [key, label] of [
            ["dblp", "手动打开 DBLP"], ["crossref", "手动打开 Crossref"],
            ["google_scholar", "手动打开 Google Scholar"],
            ["jcr", "手动核对年度 JCR 影响因子"],
          ]) {
            const a = el("a", "nav-link", label + " ↗");
            a.href = info.manual_links[key];
            a.target = "_blank"; a.rel = "noopener noreferrer";
            venueResults.append(a);
          }
        } catch (error) {
          venueResults.replaceChildren(el("p", "paper-alert", error.message));
        } finally { checkVenue.disabled = false; }
      };
      publication.append(checkVenue, venueResults);
      card.append(publication);
      const code = item.code_urls || [];
      if (code.length) {
        card.append(el("p", "hint", "仓库链接由 arXiv 摘要/备注/相关链接发现，未核验可用性："));
        for (const url of code) {
          if (!/^https:\/\/(?:www\.)?(?:github\.com|gitlab\.com|codeberg\.org)\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+/.test(url)) continue;
          const link = el("a", "nav-link", url);
          link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
          card.append(link);
        }
      } else {
        card.append(el("p", "hint", "开源代码：未发现明确仓库链接（状态未知，不能判定“未开源”）。"));
      }
      item.reasons.forEach(reason => card.append(el("p", "hint", reason)));
      const actions = el("div", "recommend-actions");
      const voteButtons = [];
      for (const [vote, label] of [[1,"👍"],[-1,"👎"]]) {
        const button = el("button", "btn light", label + (item.feedback === vote ? " 已记录" : ""));
        button.type = "button";
        button.onclick = async () => {
          try {
            await api("/api/recommendations/feedback", {
              method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({identifier: item.identifier, vote})
            });
            item.feedback = vote;
            voteButtons.forEach((node, i) =>
              node.textContent = (i === 0 ? "👍" : "👎") + (i === (vote === 1 ? 0 : 1) ? " 已记录" : ""));
            toast("偏好已保存；下一次查询时参与排序");
          } catch (error) { toast(error.message); }
        };
        voteButtons.push(button);
        actions.append(button);
      }
      const view = el("a", "btn light", "核对 arXiv 原文 ↗");
      view.href = `https://arxiv.org/abs/${encodeURIComponent(item.identifier)}`;
      view.target = "_blank"; view.rel = "noopener noreferrer";
      actions.append(view);
      const download = el("button", "btn light", "核对并下载 PDF 入库");
      download.type = "button";
      const result = el("p", "hint");
      download.onclick = async () => {
        let importedSuccess = false;
        if (!/^\d{4}\.\d{4,5}v[1-9]\d*$/.test(item.identifier)) {
          result.textContent = "arXiv 编号格式不符合安全要求，不能自动下载。";
          return;
        }
        download.disabled = true;
        result.textContent = "正在向 arXiv 核对所选论文的元数据；尚未下载…";
        try {
          const {paper} = await api(
            "/api/arxiv/metadata?identifier=" + encodeURIComponent(item.identifier)
          );
          const canonical = value => String(value).toLowerCase().replace(/[^a-z0-9]+/g, "");
          const base = identifier => identifier.replace(/v[1-9]\d*$/, "");
          if (base(paper.identifier) !== base(item.identifier) ||
              canonical(paper.title) !== canonical(item.title)) {
            result.textContent = `题名或编号存在冲突，不自动下载。候选：${item.title}；官方：${paper.title}（${paper.identifier}）。请人工检查。`;
            return;
          }
          result.textContent = `官方核对：${paper.title} · ${paper.identifier} · ${
            paper.authors.join("、") || "作者缺失"} · ${paper.published || "日期缺失"}。`;
          if (!window.confirm(`核对并下载此单篇 PDF 到本地文献库？\n${paper.title}\n${
            paper.identifier} · ${paper.published || "日期未知"}\n不会批量下载。`)) {
            result.textContent += " 用户取消了下载；未写入文献库。";
            return;
          }
          const imported = await api("/api/arxiv/download", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({identifier: paper.identifier})
          });
          result.textContent = `已开始导入 ${paper.identifier}（${imported.id}）；请在左侧查看解析进度。`;
          importedSuccess = true;
          try { await refresh(); }
          catch (error) { toast("已提交导入，但文献列表刷新失败：" + error.message); }
          download.textContent = "已发起导入";
        } catch (error) {
          result.textContent = `未下载：${error.message}。可稍后重试；本地文献不受影响。`;
        } finally {
          download.disabled = importedSuccess;
        }
      };
      actions.append(download);
      card.append(actions);
      card.append(result);
      box.append(card);
    }
}
$("#recent-form").onsubmit = async (event) => {
  event.preventDefault();
  const topic = $("#recent-topic").value.trim(), box = $("#recent-results");
  const progress = el("p", "hint", "正在查询 arXiv 最近投稿；上次结果仍可查看…");
  box.prepend(progress);
  try {
    const data = await api("/api/recommendations?topic=" + encodeURIComponent(topic));
    renderRecentResults(data);
    try {
      localStorage.setItem(RECENT_CACHE_KEY, JSON.stringify({
        topic, saved_at: new Date().toISOString(), data: {
          note: data.note, items: data.items.slice(0, 15)
        }
      }));
    } catch { /* storage unavailable: collapse still preserves DOM */ }
  } catch (error) {
    progress.textContent = `更新失败：${error.message}；之前的搜索结果仍保留。`;
    progress.className = "paper-alert";
  }
};
function restoreRecentResults() {
  try {
    const saved = JSON.parse(localStorage.getItem(RECENT_CACHE_KEY));
    if (!saved || typeof saved.topic !== "string" ||
        !Array.isArray(saved.data?.items) || saved.data.items.length > 15 ||
        !saved.data.items.every(item => item &&
          /^\d{4}\.\d{4,5}v[1-9]\d*$/.test(item.identifier) &&
          typeof item.title === "string" && item.title.length < 300 &&
          typeof item.published === "string" &&
          Number.isFinite(item.score) && Array.isArray(item.reasons))) return;
    $("#recent-topic").value = saved.topic;
    renderRecentResults(saved.data, true);
  } catch { /* corrupt browser cache: ignore and request a fresh search */ }
}
$("#tracking-form").onsubmit = async (event) => {
  event.preventDefault();
  const topic = $("#tracking-topic").value.trim();
  try {
    const response = await api("/api/subscriptions", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        topic, interval_minutes: Number($("#tracking-interval").value),
        max_results: 20
      })
    });
    $("#tracking-topic").value = "";
    toast(response.note);
    await loadSubscriptions();
  } catch (error) { toast(error.message); }
};
$("#tracking-reload").onclick = loadSubscriptions;
async function loadSubscriptions() {
  const box = $("#tracking-list");
  try {
    const data = await api("/api/subscriptions");
    box.replaceChildren();
    if (!data.subscriptions.length) {
      box.append(el("p", "hint", "尚无本机主题订阅。"));
      return;
    }
    for (const sub of data.subscriptions) {
      const card = el("div", "arxiv-item");
      card.append(
        el("strong", "", `${sub.topic} · ${sub.enabled ? "自动追踪中" : "已暂停"}`),
        el("p", "hint",
          `上次检查：${sub.last_run || "尚未执行"}；上次成功：${sub.last_success || "暂无"}；下一次：${sub.next_run || "暂停"}`)
      );
      if (sub.last_error)
        card.append(el("p", "paper-alert", `最近失败：${sub.last_error}`));
      const actions = el("div", "recommend-actions");
      const refresh = el("button", "btn light", "立即刷新");
      refresh.type = "button"; refresh.disabled = !sub.enabled;
      refresh.onclick = async () => {
        refresh.disabled = true;
        try {
          const result = await api(`/api/subscriptions/${sub.id}/refresh`, {method:"POST"});
          toast(`抓取 ${result.fetched} 条，新增作品 ${result.new_count} 篇，更新版本 ${result.updated_versions.length} 条`);
        } catch (error) { toast(error.message); }
        await loadSubscriptions();
      };
      const toggle = el("button", "btn light", sub.enabled ? "暂停" : "恢复");
      toggle.type = "button";
      toggle.onclick = async () => {
        try {
          await api(`/api/subscriptions/${sub.id}/${sub.enabled ? "pause" : "resume"}`,
            {method:"POST"});
          await loadSubscriptions();
        } catch (error) { toast(error.message); }
      };
      const remove = el("button", "btn light", "删除订阅");
      remove.type = "button";
      remove.onclick = async () => {
        if (!window.confirm(`删除「${sub.topic}」订阅及历史候选元数据？`)) return;
        try {
          await api(`/api/subscriptions/${sub.id}`, {method:"DELETE"});
          await loadSubscriptions();
        } catch (error) { toast(error.message); }
      };
      actions.append(refresh, toggle, remove);
      card.append(actions);
      const candidates = await api(`/api/subscriptions/${sub.id}/candidates`);
      if (!candidates.candidates.length) {
        card.append(el("p", "hint", "尚无已保存的候选；可立即刷新或等待计划任务。"));
      } else {
        card.append(el("p", "hint", `已保存 ${candidates.candidates.length} 条近期候选；仅元数据，不会自动下载。`));
        for (const item of candidates.candidates.slice(0, 8)) {
          const link = el("a", "nav-link",
            `${item.published} · ${item.title} · ${item.latest_identifier}`);
          link.href = `https://arxiv.org/abs/${item.latest_identifier}`;
          link.target = "_blank"; link.rel = "noopener noreferrer";
          card.append(link);
        }
      }
      box.append(card);
    }
  } catch (error) {
    box.replaceChildren(el("p", "hint", error.message));
  }
}
$("#ask-form").onsubmit = async (event) => {
  event.preventDefault();
  const question = $("#question").value.trim();
  if (!question) return;
  const submit = $("#ask-submit");
  submit.disabled = true;
  submit.textContent = "正在检索…";
  try {
  if (/^(?:这|那)?(?:两|二|几|多)?篇?(?:论文|文章|文献)(?:有无|有|是否有|有哪些|的)?(?:共同点|相同点|相似点|相似之处|异同|区别)[？?。!！]?$/.test(question)) {
    $("#compare-panel").open = true;
    const selected = [...$("#compare-choices").querySelectorAll("input:checked")];
    if (selected.length >= 2 && selected.length <= 4) {
      $("#answer").replaceChildren(el("p", "answer-text",
        "已按所选论文启动逐篇原文对照。请查看下方证据；不自动推断共同科研结论。"));
      await $("#compare-btn").onclick();
      return;
    }
  }
  $("#answer").replaceChildren(el("p", "empty", "正在检索原文…"));
  try {
    const data = await api("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, paper_id: $("#scope").value })
    });
    const box = $("#answer"); box.replaceChildren();
    box.append(el("p", "answer-text", data.answer));
    if (data.usage && data.usage.total_tokens) {
      const price = data.usage.estimated_cost_usd == null
        ? "价格未配置，暂不计算费用"
        : `估算费用 $${Number(data.usage.estimated_cost_usd).toFixed(6)}`;
      box.append(el("p", "metering",
        `本次模型消耗：输入 ${data.usage.prompt_tokens} tokens · 输出 ${
          data.usage.completion_tokens} tokens · 合计 ${data.usage.total_tokens} · ${price}`));
    } else if (data.mode === "evidence_only") {
      box.append(el("p", "metering",
        state.modelConfigured
          ? "未收到模型返回的 Token 用量，无法确认实际计费；请查看模型服务商账单。"
          : "本次仅运行本地检索，未向模型发送请求。"));
    }
    if (data.mode === "needs_attention") {
      const open = el("button", "btn light", "展开多篇论文证据对照并勾选论文");
      open.type = "button";
      open.onclick = () => {
        $("#compare-panel").open = true;
        $("#compare-panel").scrollIntoView?.({behavior: "smooth", block: "start"});
      };
      box.append(open);
    }
    if (data.audit_id) box.append(el("p", "hint", `审计事件 #${data.audit_id} 已保存`));
    for (const step of data.steps) box.append(el("div", "step", step));
    data.evidence.forEach((x, i) => {
      const card = el("div", "evidence");
      const link = el("a", "", `[${i + 1}] ${x.title} · 第 ${x.page_no} 页 · ${x.retrieval || "BM25"} ↗`);
      link.href = `/api/papers/${x.paper_id}/file#page=${x.page_no}`;
      link.onclick = (event) => {
        event.preventDefault(); showEvidence(x);
      };
      card.append(link, el("p", "", x.content)); box.append(card);
    });
    loadAudit();
  } catch (error) { $("#answer").replaceChildren(el("p", "empty", error.message)); }
  } finally {
    submit.disabled = false;
    submit.textContent = "检索证据 →";
  }
};
const auditModes = {
  completed: "已完成", partial: "部分完成", needs_attention: "需要操作",
  no_evidence: "未找到证据", evidence_only: "仅有原文证据",
  evidence_candidates: "写作证据候选", model_draft: "模型草稿（待核验）",
  grounded: "有原文证据", model_answer: "模型回答（请核对）"
};
const auditTools = {
  retrieve: "检索原文", compare_papers: "逐篇对照", future_work: "未来工作",
  version_comparison: "版本比较", citation_graph: "引用图谱",
  import_requires_confirmation: "等待确认导入"
};
const auditStatuses = {
  ok: "已完成", no_evidence: "无匹配证据", needs_input: "需要用户操作", error: "执行失败"
};
let auditExpanded = false;
function renderAuditRows(box, events) {
  box.replaceChildren();
  if (!events.length) {
    box.append(el("p", "hint", "尚无问答审计记录。")); return;
  }
  const visible = box === $("#audit-list") && !auditExpanded
    ? events.slice(0, 5) : events;
  visible.forEach(event => {
    const row = el("article", "audit-row");
    const stamp = new Date(event.created_at).toLocaleString();
    const evidenceCount = Array.isArray(event.evidence_ids) ? event.evidence_ids.length : 0;
    const tokenText = event.total_tokens
      ? ` · tokens ${event.total_tokens}${
        event.estimated_cost_usd == null ? "" :
          ` · $${Number(event.estimated_cost_usd).toFixed(6)}`
      }`
      : "";
    const badge = el("span", "audit-badge" +
      (["needs_attention", "no_evidence"].includes(event.mode) ? " warn" : ""),
      auditModes[event.mode] || event.mode || "未知状态");
    row.append(badge, el("span", "hint", `　#${event.id} · ${stamp}`),
      el("p", "audit-question", event.question),
      el("p", "hint", `原文证据 ${evidenceCount} 条${tokenText} · ${
        evidenceCount ? "请点击结果中的原文链接核对" :
          "没有可供核对的原文片段；不要将此记录当作论文结论"
      }`));
    if (Array.isArray(event.steps) && event.steps.length) {
      const details = el("details", "audit-steps");
      details.append(el("summary", "", `查看执行步骤（${event.steps.length}）`));
      event.steps.forEach(step => details.append(el("p", "",
        typeof step === "string" ? step
          : `${auditTools[step.tool] || step.tool || "工具"} · ${
            auditStatuses[step.status] || step.status || "未知"
          }：${step.message || step.reason || "没有附加说明"}`)));
      row.append(details);
    }
    box.append(row);
  });
  if (box === $("#audit-list") && events.length > 5) {
    $("#audit-more").hidden = false;
    $("#audit-more").textContent = auditExpanded
      ? "收起历史，仅看最近 5 条" : `查看全部 ${events.length} 条`;
  } else if (box === $("#audit-list")) {
    $("#audit-more").hidden = true;
  }
}
$("#audit-refresh").onclick = loadAudit;
$("#audit-more").onclick = () => {
  auditExpanded = !auditExpanded;
  $("#audit-panel").open = true;
  loadAudit();
};
$("#audit-large-refresh").onclick = loadAudit;
function closeAuditWindow() {
  $("#audit-window").hidden = true;
  $("#page-layout").inert = false;
  document.querySelector(".topbar").inert = false;
  document.querySelector(".view-controls").inert = false;
  $("#audit-expand").setAttribute("aria-expanded", "false");
  $("#audit-expand").focus();
}
$("#audit-expand").onclick = () => {
  $("#audit-window").hidden = false;
  $("#page-layout").inert = true;
  document.querySelector(".topbar").inert = true;
  document.querySelector(".view-controls").inert = true;
  $("#audit-expand").setAttribute("aria-expanded", "true");
  $("#audit-close").focus();
  loadAudit();
};
$("#audit-close").onclick = closeAuditWindow;
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("#audit-window").hidden) closeAuditWindow();
});
async function loadAudit() {
  try {
    const data = await api("/api/audit?limit=20");
    renderAuditRows($("#audit-list"), data.events);
    renderAuditRows($("#audit-large-list"), data.events);
  } catch (error) {
    renderAuditRows($("#audit-list"), []);
    $("#audit-large-list").replaceChildren(el("p", "hint", error.message));
    $("#audit-list").replaceChildren(el("p", "hint", error.message));
  }
}
$("#outline-form").onsubmit = async (event) => {
  event.preventDefault();
  const box = $("#outline"), submit = $("#outline-submit");
  submit.disabled = true;
  box.replaceChildren(el("p", "hint", "正在检索所选论文并整理框架候选…"));
  try {
    const ids = [...$("#writing-choices").querySelectorAll("input:checked")]
      .map(x => x.value);
    if (!ids.length || ids.length > 8) {
      box.replaceChildren(el("p", "paper-alert",
        "请先在上方勾选 1–8 篇已解析论文；无论文证据时不能生成有出处的框架。"));
      return;
    }
    const data = await api("/api/writing/grounded", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        idea: $("#idea").value, paper_ids: ids,
        use_model: $("#writing-use-model").checked
      }) });
    box.replaceChildren();
    box.append(el("p", "capability-note",
      `运行结果：${data.status === "no_evidence" ? "未找到相关原文，只有待验证模板" :
        "找到原文背景候选，仍需逐条核查"}；模型草稿：${
        data.model_status === "verified_rules" ? "已生成，仅通过引用/数字规则" :
        data.model_status === "fallback" ? "请求失败，已退回离线模板" :
        "未请求（未勾选模型）"
      } · 审计 #${data.audit_id || "—"}`));
    if (data.model_draft) {
      box.append(el("h3", "", "模型背景草稿 · 只通过引用/数字规则，不代表语义已核验"),
        el("p", "answer-text", data.model_draft),
        el("p", "hint", "草稿中的 [n] 对应下方「原文证据 [n]」；请逐句对照原 PDF。"));
    } else if (data.model_error) {
      box.append(el("p", "paper-alert", data.model_error));
    }
    box.append(el("p", "hint", data.note));
    for (const [title, text] of Object.entries(data.outline)) {
      box.append(el("h3", "", title), el("p", "", Array.isArray(text) ? (text.join("\n") || "暂无可核实引用") : text));
    }
    if (data.transfer_plan?.length) {
      box.append(el("h3", "", "迁移到目标领域：待验证研究计划"));
      box.append(el("p", "capability-note",
        data.target_domain_matches
          ? "已在所选原文中命中目标域词项；这只是先例线索，不证明方法适合迁移，也不证明创新。"
          : "当前所选论文未命中目标域词项；请补充目标领域文献，不能据此声称没有先例。"));
    }
    box.append(el("h3", "", "Related Work 候选 · 原文证据"));
    if (!data.evidence.length) box.append(el("p", "hint",
      "当前选择的论文未检索到足够候选原文，References 不得编造。"));
    data.evidence.forEach((item, index) => {
      const row = el("div", "evidence");
      const button = el("button", "nav-link",
        `原文证据 [${index + 1}] · 文献编号 [${item.reference_label}] · ${item.claim} ↗`);
      button.onclick = () => showEvidence({
        paper_id: item.paper_id, page_no: item.page_no,
        chunk_id: item.chunk_id
      });
      row.append(button, el("p", "nav-snippet", item.source_excerpt));
      box.append(row);
    });
    box.append(el("h3", "", "References 候选（编号待核实）"));
    data.references.forEach(ref =>
      box.append(el("p", "nav-snippet",
        `[${ref.label}] ${ref.title} · arXiv:${ref.arxiv_id} · ${ref.verification}`)));
    (data.skipped || []).forEach(item => box.append(
      el("p", "hint", `未引用《${item.title}》：${item.reason}`)));
    loadAudit();
  } catch (error) { box.replaceChildren(el("p", "paper-alert", error.message)); }
  finally { submit.disabled = false; }
};
$("#writing-plan-ai").onclick = async () => {
  const ids = [...$("#writing-choices").querySelectorAll("input:checked")]
    .map(item => item.value);
  const idea = $("#idea").value.trim();
  if (!ids.length || ids.length > 8 || idea.length < 5)
    return toast("请输入研究任务（至少 5 字）并选中 1–8 篇已解析论文");
  if (!window.confirm("将研究 Idea、填写的条件以及最多 6 条命中原文发送模型，"
    + "发起一次可能计费的研究计划请求。结果仅为待验证设计，不能写成已完成实验。继续吗？")) return;
  const button = $("#writing-plan-ai"), box = $("#writing-plan-results");
  button.disabled = true;
  box.replaceChildren(el("p", "hint", "正在拟定可证伪的研究任务和实验计划…"));
  try {
    const result = await api("/api/writing/plan", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        idea, details: $("#plan-details").value.trim(), paper_ids: ids,
        confirm_cost: true,
      }),
    });
    box.replaceChildren(el("p", result.plan ? "capability-note" : "paper-alert",
      `${result.message} · 审计 #${result.audit_id}`),
    el("p", "hint", result.note));
    if (result.usage?.total_tokens) box.append(el("p", "metering",
      `模型返回 ${result.usage.total_tokens} tokens，实际费用请核对服务商账单。`));
    if (result.plan) {
      for (const [key, title] of [
        ["task_scope", "任务与目标（拟议）"],
        ["method_hypothesis", "方法假设（待证伪）"],
        ["dataset_plan", "数据集、标签与划分（计划）"],
        ["experiment_plan", "对照、消融与评测（计划）"],
        ["risk_checks", "泄漏、偏差与失败案例（计划）"],
      ]) box.append(el("h3", "", title), el("p", "answer-text", result.plan[key]));
      for (const item of result.evidence) {
        const source = el("button", "nav-link",
          `${item.source_id}：《${item.title}》PDF 第 ${item.page_no} 页 ↗`);
        source.onclick = () => selectPaper(item.paper_id, item.page_no);
        box.append(source);
      }
    }
    loadAudit();
  } catch (error) { box.replaceChildren(el("p", "paper-alert", error.message)); }
  finally { button.disabled = !state.modelConfigured; }
};
$("#verify-writing-refs").onclick = async () => {
  const ids = [...$("#writing-choices").querySelectorAll("input:checked")]
    .map(x => x.value);
  if (!ids.length || ids.length > 8)
    return toast("请先勾选 1–8 篇待核验论文");
  const box = $("#writing-verification");
  box.replaceChildren(el("p", "hint", "正在逐篇向 arXiv 核对公开元数据…"));
  try {
    const result = await api("/api/writing/verify-references", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({paper_ids: ids})
    });
    box.replaceChildren(el("p", "hint", result.note));
    result.items.forEach(item => {
      const row = el("div", "compare-row");
      row.append(
        el("strong", "", `${item.local_title} · ${item.status}`),
        el("p", "hint", item.note)
      );
      if (item.official) {
        row.append(el("p", "nav-snippet",
          `${item.official.title} · arXiv:${item.official.identifier} · `
          + `${item.official.authors.join(", ")} · ${item.official.published}`));
      }
      box.append(row);
    });
  } catch (error) { box.replaceChildren(el("p", "hint", error.message)); }
};
$("#diagram-btn").onclick = () => {
  const idea = $("#idea").value.trim();
  if (!idea) return toast("请先填写研究想法");
  const names = ["研究问题", "本地文献线索", "原文证据", "任务/数据定义",
    "拟议方法假设", "对照与消融", "人工核验"];
  const edges = [[0,3],[1,2],[2,4],[3,4],[4,5],[5,6]].map(([from,to]) => ({
    from: `N${from+1}`, to: `N${to+1}`, label: "待验证流程",
  }));
  renderProposedTopology({diagram: {
    nodes: names.map((label, i) => ({
      id: `N${i+1}`, label: i === 0 ? `研究：${idea.slice(0, 27)}` : label,
      kind: "proposal", source_id: "", source_quote: "",
    })), edges,
  }, evidence: []}, true);
};
function renderProposedTopology(result, offline = false) {
  const {nodes, edges} = result.diagram;
  const safe = text => text.replace(/[^\p{L}\p{N}_ \-]/gu, " ").slice(0, 65);
  $("#diagram-code").textContent = [
    "flowchart LR",
    ...nodes.map(node =>
      `  ${node.id}["${safe(node.label)} · ${
        node.kind === "source" ? node.source_id : "待验证设计"}"]`),
    ...edges.map(edge => `  ${edge.from} -->|${safe(edge.label)}| ${edge.to}`),
  ].join("\n");
  const svg = renderMethodSvg(nodes, edges, offline);
  const preview = $("#diagram-preview");
  preview.replaceChildren(svg);
  $("#diagram-expand").disabled = false;
  $("#diagram-download").disabled = false;
  nodes.filter(node => node.kind === "source").forEach(node => {
    const source = result.evidence.find(item => item.source_id === node.source_id);
    if (!source) return;
    const link = el("button", "nav-link",
      `${node.id} · ${node.source_id}：${node.source_quote} · PDF 第 ${source.page_no} 页 ↗`);
    link.onclick = () => selectPaper(source.paper_id, source.page_no);
    preview.append(link);
  });
}
function renderMethodSvg(nodes, edges, offline = false) {
  // Adapted as an independent local implementation from reviewed diagram
  // skills' principles: layout follows dataflow, distinct source/proposal
  // color encodes provenance, and SVG must survive zoom/export inspection.
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  const byId = new Map(nodes.map(node => [node.id,node]));
  const indegree = new Map(nodes.map(node => [node.id, 0]));
  const successors = new Map(nodes.map(node => [node.id, []]));
  edges.forEach(edge => {
    if (byId.has(edge.from) && byId.has(edge.to)) {
      indegree.set(edge.to, indegree.get(edge.to) + 1);
      successors.get(edge.from).push(edge.to);
    }
  });
  const queue = nodes.filter(node => !indegree.get(node.id)).map(node => node.id);
  const layers = new Map(nodes.map(node => [node.id, 0]));
  const visited = new Set();
  while (queue.length) {
    const id = queue.shift();
    if (visited.has(id)) continue;
    visited.add(id);
    for (const next of successors.get(id)) {
      layers.set(next, Math.max(layers.get(next), layers.get(id) + 1));
      indegree.set(next, indegree.get(next) - 1);
      if (!indegree.get(next)) queue.push(next);
    }
  }
  // Cyclic proposed graphs have no strict dataflow order; preserve supplied
  // order rather than inventing a topological one.
  if (visited.size !== nodes.length)
    nodes.forEach((node, i) => layers.set(node.id, Math.floor(i / 2)));
  const columns = Math.max(...layers.values()) + 1;
  const columnRows = new Map();
  for (const node of nodes) {
    const column = layers.get(node.id);
    columnRows.set(column, [...(columnRows.get(column) || []), node.id]);
  }
  const rows = Math.max(...[...columnRows.values()].map(items => items.length));
  const width = Math.max(660, columns * 226 + 56);
  const height = Math.max(240, rows * 122 + 64);
  svg.setAttribute("xmlns", ns);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", offline ?
    "待验证的科研计划步骤图" : "按原文候选和拟议设计区分的研究方法拓扑");
  const make = (tag, attrs, text, parent = svg) => {
    const item = document.createElementNS(ns, tag);
    for (const [name,value] of Object.entries(attrs))
      item.setAttribute(name, String(value));
    if (text != null) item.textContent = text;
    parent.append(item); return item;
  };
  const defs = make("defs", {});
  const marker = make("marker", {id:"method-arrow",viewBox:"0 0 10 10",
    refX:8,refY:5,markerWidth:7,markerHeight:7,orient:"auto"}, null, defs);
  make("path", {d:"M 0 0 L 10 5 L 0 10 z",fill:"#6d8e7f"},null,marker);
  const positions = new Map();
  for (const [column, ids] of columnRows) {
    ids.forEach((id, row) => {
      positions.set(id,{x:28 + column * 226,
        y:32 + row * 122 + (rows - ids.length) * 61});
    });
  }
  edges.forEach((edge, index) => {
    const from = positions.get(edge.from), to = positions.get(edge.to);
    if (!from || !to) return;
    const goesBack = to.x <= from.x;
    const sx = from.x + 172, sy = from.y + 34;
    const tx = goesBack ? to.x + 86 : to.x - 5;
    const ty = goesBack ? to.y - 5 : to.y + 34;
    const mid = goesBack ? Math.max(12, Math.min(from.y,to.y) - 31 - (index%3)*13)
      : undefined;
    const d = goesBack ?
      `M${sx},${sy} C${sx+40},${mid} ${tx+30},${mid} ${tx},${ty}` :
      `M${sx},${sy} C${sx+22},${sy} ${tx-23},${ty} ${tx},${ty}`;
    const route = make("path",{d,fill:"none",stroke:goesBack?"#c58a42":"#6d8e7f",
      "stroke-width":2,"marker-end":"url(#method-arrow)"});
    make("title",{},`${edge.from} → ${edge.to}：${edge.label}`,route);
  });
  nodes.forEach(node => {
    const {x,y} = positions.get(node.id);
    const origin = node.kind === "source";
    const group = make("g",{});
    make("rect",{x,y,width:172,height:68,rx:11,
      fill:origin?"#e6f4ee":"#fff6e9",
      stroke:origin?"#3d9274":"#c99042","stroke-width":1.6},null,group);
    const raw = node.label.replace(/\s+/g," ").trim();
    const short = raw.length > 18 ? raw.slice(0,17)+"…" : raw;
    make("text",{x:x+12,y:y+27,"font-size":13,"font-weight":700,
      fill:"#234b3f"},short,group);
    make("text",{x:x+12,y:y+51,"font-size":10,fill:origin?"#217555":"#926225"},
      origin ? `${node.source_id} · PDF 来源候选` : "拟议方法 · 待验证",group);
    make("title",{},`${node.id}：${raw}；${origin?
      "来源仅可定位原文" : "方案假设，未开展实验"}`,group);
  });
  return svg;
}
$("#diagram-ai-btn").onclick = async () => {
  const ids = [...$("#writing-choices").querySelectorAll("input:checked")]
    .map(item => item.value);
  const idea = $("#idea").value.trim();
  if (!ids.length || ids.length > 8 || idea.length < 5)
    return toast("先输入至少 5 字的 Idea 并勾选 1–8 篇已解析论文");
  if (!window.confirm("AI 方法拓扑会把选中论文的命中原文片段发送给模型，"
    + "发生一次可能计费的请求；生成的节点/箭头仅是草稿。继续吗？")) return;
  const button = $("#diagram-ai-btn"), status = $("#diagram-ai-status");
  button.disabled = true;
  status.replaceChildren(el("p", "hint", "正在提取证据与生成候选拓扑…"));
  try {
    const result = await api("/api/writing/diagram", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({idea, paper_ids: ids, confirm_cost: true}),
    });
    status.replaceChildren(el("p",
      result.diagram ? "capability-note" : "paper-alert",
      `${result.message} · 审计 #${result.audit_id}`),
    el("p", "hint", result.note));
    if (result.usage?.total_tokens) status.append(el("p", "metering",
      `${result.usage.total_tokens} tokens；费用请按服务商账单核对`));
    if (result.diagram?.system_quote_anchors?.length) status.append(
      el("p", "paper-alert",
        `${result.diagram.system_quote_anchors.join("、")} 的模型引文无法在对应原文中逐字找到；`
        + "系统只替换为本地 PDF 抽取的定位锚点，不表示节点或箭头的科研含义得到证明。")
    );
    if (result.diagram) renderProposedTopology(result);
    loadAudit();
  } catch (error) {
    status.replaceChildren(el("p", "paper-alert", error.message));
  } finally { button.disabled = !state.modelConfigured; }
};
$("#graph-btn").onclick = drawGraph;
$("#graph-review").onclick = async () => {
  const box = $("#graph-review-results");
  box.replaceChildren(el("p", "hint", "正在整理本地引文事实…"));
  try {
    const report = await api("/api/graph/review");
    box.replaceChildren(el("p", "hint", report.summary + " " + report.note));
    for (const item of report.statements) {
      const row = el("div", "graph-review-item");
      const source = el("button", "nav-link", item.claim + " ↗");
      source.onclick = () => selectPaper(item.source_paper_id, item.source_page);
      row.append(source, el("p", "graph-snippet", item.source_excerpt));
      box.append(row);
    }
    if (!report.statements.length)
      box.append(el("p", "hint", "没有可核查的局域引用事实，不能编造综述内容。"));
  } catch (error) { box.replaceChildren(el("p", "hint", error.message)); }
};
$("#frontier-refresh").onclick = async () => {
  const box = $("#frontier-results");
  box.replaceChildren(el("p", "hint", "正在整理本地论文、引用边与未来工作原文…"));
  try {
    const data = await api("/api/frontier");
    box.replaceChildren(el("h3", "", data.summary), el("p", "paper-alert", data.note));
    const timeline = el("details", "compare-panel");
    timeline.append(el("summary", "", `本地时间线（${data.timeline.length} 篇）`));
    data.timeline.forEach(paper => {
      const jump = el("button", "nav-link",
        `${paper.arxiv_first_month || "初投月份未知"} · ${paper.title}`);
      jump.onclick = () => selectPaper(paper.paper_id);
      timeline.append(jump);
    });
    box.append(timeline);
    const references = el("details", "compare-panel");
    references.append(el("summary", "",
      `有原文来源的引文事实（${data.citation_facts.length} 条）`));
    data.citation_facts.forEach(item => {
      const jump = el("button", "nav-link",
        `${item.claim} · 打开来源 PDF ↗`);
      jump.onclick = () => selectPaper(item.source_paper_id, item.source_page);
      references.append(jump, el("p", "nav-snippet", item.excerpt));
    });
    box.append(references);
    box.append(el("h3", "", `待进一步检索的未来方向（${data.future_directions.length} 条）`));
    data.future_directions.forEach((item, index) => {
      const entry = el("details", "compare-panel");
      entry.append(el("summary", "",
        `${index + 1}. ${item.origin_title} · 第 ${item.source_page} 页 · ${item.status}`));
      const jump = el("button", "nav-link",
        `原文：${item.signal} · PDF 第 ${item.source_page} 页 ↗`);
      jump.onclick = () => selectPaper(item.origin_paper_id, item.source_page);
      entry.append(jump, el("p", "future-quote", item.source_excerpt));
      const single = el("button", "btn light", "到当前论文 Future Work 面板查看完整线索");
      single.onclick = async () => {
        selectPaper(item.origin_paper_id, item.source_page);
        await $("#future-btn").onclick();
        document.querySelector(".horizon-panel")?.scrollIntoView?.({
          behavior:"smooth",block:"start"
        });
      };
      entry.append(single);
      for (const lead of item.later_local_matches) {
        const link = el("button", "nav-link",
          `较晚本地候选（仅共同词）：${lead.title} · 第 ${lead.page_no} 页 ↗`);
        link.onclick = () => selectPaper(lead.paper_id, lead.page_no);
        entry.append(link);
      }
      const recent = el("button", "btn light",
        "手动查近期 arXiv 主题候选（不判定已解决）");
      const recentResults = el("div");
      recent.onclick = async () => {
        recent.disabled = true;
        recentResults.replaceChildren(el("p","hint","正在核查当前 Future Work 页并请求最近投稿元数据…"));
        try {
          const checked = await api(
            `/api/frontier/${item.origin_paper_id}/recent?page=${item.source_page}`
          );
          recentResults.replaceChildren(el("p","hint",
            `主题词：${checked.topic}；${checked.note}`));
          if (!checked.items.length) recentResults.append(
            el("p","paper-alert","本次最近窗口没有可靠双关键词候选，不代表没有后续论文。"));
          checked.items.forEach(candidate => {
            const a = el("a","nav-link",
              `${candidate.published} · ${candidate.title} · ${candidate.identifier} ↗`);
            a.href = `https://arxiv.org/abs/${encodeURIComponent(candidate.identifier)}`;
            a.target="_blank"; a.rel="noopener noreferrer";
            recentResults.append(a,el("p","hint",
              `共同词：${candidate.shared_terms.join(", ")} · ${candidate.status}`));
          });
        } catch(error) {
          recentResults.replaceChildren(el("p","paper-alert",error.message));
        } finally { recent.disabled = false; }
      };
      entry.append(recent,recentResults);
      box.append(entry);
    });
  } catch (error) {
    box.replaceChildren(el("p", "paper-alert", error.message));
  }
};
$("#frontier-model").onclick = async () => {
  if (!window.confirm("仅将当前已导入论文中最多 8 条可定位的未来工作原文片段发送"
    + "模型，发起一次可能计费的局域短综述请求。引用和数字只能词面检查，"
    + "不能自动判定方向已解决/具有新颖性。继续吗？")) return;
  const button = $("#frontier-model"), box = $("#frontier-model-results");
  button.disabled = true;
  box.replaceChildren(el("p","hint","正在核对本地未来工作来源…"));
  try {
    const data = await api("/api/frontier/review",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({confirm_cost:true}),
    });
    box.replaceChildren(el("p", data.answer ? "capability-note":"paper-alert",
      `${data.answer || data.warning} · 审计 #${data.audit_id}`),
      el("p","hint",data.note));
    if (data.usage?.total_tokens) box.append(el("p","metering",
      `${data.usage.total_tokens} tokens；实际费用以服务商账单为准。`));
    data.sources.forEach((item,index) => {
      const link = el("button","nav-link",
        `[${index+1}] 《${item.title}》PDF 第 ${item.page_no} 页 ↗`);
      link.onclick = () => showEvidence(item);
      box.append(link,el("p","nav-snippet",item.content));
    });
    loadAudit();
  } catch(error) {
    box.replaceChildren(el("p","paper-alert",error.message));
  } finally { button.disabled = !state.modelConfigured; }
};
$("#future-btn").onclick = async () => {
  const selected = state.papers.find(paper => paper.id === state.selected);
  if (!selected || selected.status !== "ready") return toast("请先选择已解析的论文");
  const paperId = selected.id, box = $("#future-results");
  box.replaceChildren(el("p", "hint", "正在读取 Future Work 原文和本地相关片段…"));
  try {
    const data = await api(`/api/papers/${paperId}/future-work`);
    if (state.selected !== paperId) return;
    box.replaceChildren(el("p", "hint", data.note));
    if (!data.items.length) {
      box.append(el("p", "empty",
        "未在本文索引中命中明确的 Future Work、计划或“Limitations and Outlook”信号；" +
        "这不是研究新颖性判断。下方如有结论/讨论页，请打开原 PDF 人工核对。"));
      (data.review_pages || []).forEach(page => {
        const jump = el("button", "nav-link", `人工核查：结论/讨论附近 · PDF 第 ${page} 页 ↗`);
        jump.onclick = () => selectPaper(paperId, page);
        box.append(jump);
      });
      return;
    }
    data.items.forEach((item, index) => {
      const card = el("div", "future-card");
      const original = el("button", "nav-link",
        `线索 ${index + 1} · ${item.signal.trim().replace(/\s+/g, " ")} · 原文第 ${item.source_page} 页 ↗`);
      original.onclick = () => {
        selectPaper(paperId, item.source_page);
        document.querySelector(".reader").scrollIntoView({ behavior: "smooth" });
      };
      card.append(original, el("p", "future-quote", item.source_excerpt),
        el("p", "hint", item.status));
      const translate = el("button", "btn light", "翻译这条原文为中文（可选）");
      translate.type = "button";
      const translated = el("p", "future-quote");
      translated.hidden = true;
      translate.onclick = async () => {
        if (!state.modelConfigured) {
          translated.hidden = false;
          translated.textContent = "未配置模型：仍可直接查看上方英文原文。";
          return;
        }
        if (!window.confirm(
          `仅将当前第 ${item.source_page} 页的这条原文（约 ${
            item.source_excerpt.length} 字符）发送到已配置模型翻译？可能产生费用。`
        )) return;
        translate.disabled = true;
        translated.hidden = false;
        translated.textContent = "正在翻译；英文原文始终保留…";
        try {
          const response = await api("/api/translate", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              text: item.source_excerpt, source_language: "en",
              target_language: "zh-CN"
            })
          });
          translated.textContent = `中文译文（模型生成，数字/术语须对照原文；审计 #${
            response.audit_id}）：${response.translation}`;
        } catch (error) {
          translated.textContent = `翻译未完成：${error.message}。上方英文原文仍可核对。`;
        } finally { translate.disabled = false; }
      };
      card.append(translate, translated);
      if (item.related_local_papers.length) {
        card.append(el("strong", "future-related-title",
          `仅关键词检索线索 · 源论文初投月份：${item.origin_arxiv_first_month || "未能从 arXiv ID 确认"} · 不证明研究相关或问题已解决`));
        item.related_local_papers.forEach(related => {
          const relation = {
            later_arxiv_month: "初投月份较晚（不能证明解决）",
            earlier_arxiv_month: "初投月份较早（不能算后续研究）",
            same_arxiv_month_unknown_order: "同月顺序未知",
            unknown: "时间未核实（不能列为后续成果）"
          }[related.time_relation] || "时间未核实";
          const link = el("button", "nav-link",
            `${related.title} · 第 ${related.page_no} 页 · ${relation} · 仅共同词：${related.shared_terms.join(", ")}`);
          link.onclick = () => {
            selectPaper(related.paper_id, related.page_no);
            document.querySelector(".reader").scrollIntoView({ behavior: "smooth" });
          };
          card.append(link, el("p", "nav-snippet", related.excerpt));
        });
      } else {
        card.append(el("p", "hint", "当前本地文献库未检索到相关候选；并非证明其他研究不存在。"));
      }
      box.append(card);
    });
  } catch (error) {
    box.replaceChildren(el("p", "hint", error.message));
  }
};
$("#graph-search").oninput = event => {
  state.graphFocus = "";
  state.graphQuery = event.target.value.trim().toLowerCase();
  renderGraph();
};
$("#graph-edge-filter").onchange = event => {
  state.graphEdgeFilter = event.target.value;
  renderGraph();
};
$("#graph-clear").onclick = () => {
  state.graphFocus = "";
  state.graphQuery = "";
  state.graphEdgeFilter = "all";
  $("#graph-search").value = "";
  $("#graph-edge-filter").value = "all";
  renderGraph();
};
async function drawGraph() {
  try {
    state.graphData = await api("/api/graph");
    if (state.graphFocus && !state.graphData.nodes.some(n => n.id === state.graphFocus))
      state.graphFocus = "";
    renderGraph();
  } catch (error) { toast(error.message); }
}
function renderGraph() {
  const data = state.graphData, box = $("#graph");
  if (!data) return;
  try {
    box.replaceChildren();
    if (data.nodes.length < 2) {
      box.append(el("p", "empty", "至少导入两篇已完成解析的论文。")); return;
    }
    if (!data.edges.length) {
      box.append(el("p", "hint", `${data.nodes.length} 篇不同作品，尚无可核对的局域引用边。仅凭正文提及某论文，不会自动生成引用关系。`));
    }
    const nodeById = new Map(data.nodes.map(node => [node.id, node]));
    const matchIds = new Set(data.nodes.filter(node =>
      state.graphQuery && (
        node.title.toLowerCase().includes(state.graphQuery) ||
        node.filename.toLowerCase().includes(state.graphQuery) ||
        (node.arxiv_id || "").includes(state.graphQuery)
      )).map(node => node.id));
    const selectedEdges = data.edges.filter(edge =>
      state.graphEdgeFilter === "all" || edge.match_type === state.graphEdgeFilter
    );
    const adjacent = new Set();
    if (state.graphFocus) {
      adjacent.add(state.graphFocus);
      selectedEdges.forEach(edge => {
        if (edge.source === state.graphFocus) adjacent.add(edge.target);
        if (edge.target === state.graphFocus) adjacent.add(edge.source);
      });
    }
    const focus = nodeById.get(state.graphFocus);
    $("#graph-selection").textContent = focus
      ? `${focus.title}：在当前边筛选下直接邻居 ${adjacent.size - 1} 篇；实线表示源论文引用目标论文。`
      : state.graphQuery
        ? `搜索「${state.graphQuery}」：匹配 ${matchIds.size} 篇；点击节点查看局部邻居。`
        : `显示 ${data.nodes.length} 篇论文、${selectedEdges.length} 条筛选后的引用边；点击节点可看邻居。`;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 650 200");
    const xy = new Map();
    data.nodes.forEach((node, i) => {
      const angle = 2 * Math.PI * i / data.nodes.length;
      xy.set(node.id, [325 + 240 * Math.cos(angle), 100 + 75 * Math.sin(angle)]);
    });
    for (const edge of selectedEdges) {
      const [x1, y1] = xy.get(edge.source), [x2, y2] = xy.get(edge.target);
      const line = document.createElementNS(ns, "line");
      const relevant = !state.graphFocus ||
        edge.source === state.graphFocus || edge.target === state.graphFocus;
      for (const [key, val] of Object.entries({
        x1, y1, x2, y2,
        stroke: relevant && state.graphFocus ? "#1c9871" : "#7bbf9a",
        "stroke-width": relevant && state.graphFocus ? 3.4 : 2,
        opacity: relevant ? 1 : 0.12
      }))
        line.setAttribute(key, String(val));
      const edgeTitle = document.createElementNS(ns, "title");
      edgeTitle.textContent = `${nodeById.get(edge.source)?.title || "论文"} → ${nodeById.get(edge.target)?.title || "论文"}；源论文第 ${edge.page_no} 页`;
      line.append(edgeTitle);
      line.setAttribute("data-edge-source", edge.source);
      line.setAttribute("data-edge-page", edge.page_no);
      line.style.cursor = "pointer";
      line.onclick = () => selectPaper(edge.source, edge.page_no);
      svg.append(line);
    }
    for (const [i, node] of data.nodes.entries()) {
      const [x, y] = xy.get(node.id);
      const g = document.createElementNS(ns, "g"), circle = document.createElementNS(ns, "circle");
      const emphasized = state.graphFocus ? adjacent.has(node.id)
        : !state.graphQuery || matchIds.has(node.id);
      g.setAttribute("opacity", emphasized ? "1" : "0.2");
      g.setAttribute("data-paper-id", node.id);
      circle.setAttribute("cx", x); circle.setAttribute("cy", y);
      circle.setAttribute("r", String(
        8 + Math.min(7, node.in_degree * 2) +
        (state.graphFocus === node.id || matchIds.has(node.id) ? 4 : 0)
      ));
      circle.setAttribute("fill",
        state.graphFocus === node.id ? "#d08337" : "#168061");
      g.append(circle);
      const title = document.createElementNS(ns, "title");
      title.textContent = `${node.title} · 入度 ${node.in_degree} · PageRank ${node.pagerank.toFixed(4)}`;
      g.append(title); g.style.cursor = "pointer";
      g.onclick = () => {
        state.graphFocus = node.id;
        renderGraph();
        selectPaper(node.id);
      };
      if (data.nodes.length < 12 || i < 5) {
        const text = document.createElementNS(ns, "text");
        text.setAttribute("x", x + 13); text.setAttribute("y", y + 4);
        text.setAttribute("font-size", "10"); text.setAttribute("fill", "#3e6056");
        text.textContent = node.title.slice(0, 18) + (node.title.length > 18 ? "…" : "");
        g.append(text);
      }
      svg.append(g);
    }
    box.append(svg, el("p", "hint", `${data.nodes.length} 篇不同论文，${selectedEdges.length}/${data.edges.length} 条筛选引用边。${data.collapsed_versions ? "已合并重复 arXiv 版本。" : ""}${data.note}`));
    $("#graph-expand").disabled = false;
    if (selectedEdges.length) {
      const ranking = el("div", "graph-ranking");
      ranking.append(el("strong", "", "局域排名 · PageRank / 入度（非全领域影响力）"));
      data.nodes.slice(0, 5).forEach((node, i) => {
        const line = el("button", "graph-row", `${i + 1}. ${node.title} · ${node.pagerank.toFixed(4)} / ${node.in_degree}`);
        line.onclick = () => {
          state.graphFocus = node.id;
          renderGraph();
          selectPaper(node.id);
        };
        ranking.append(line);
      });
      box.append(ranking);
      const evidenceList = el("div", "graph-evidence");
      evidenceList.append(el("strong", "", "引用边 · 点击核对原文"));
      selectedEdges.filter(edge => !state.graphFocus ||
        edge.source === state.graphFocus || edge.target === state.graphFocus
      ).forEach(edge => {
        const citing = nodeById.get(edge.source);
        const cited = nodeById.get(edge.target);
        const button = el("button", "graph-row", `${citing?.title || "未知"} → ${cited?.title || "未知"} · 第 ${edge.page_no} 页 · ${edge.match_type === "arxiv_id" ? "arXiv ID" : "完整题名"}`);
        button.onclick = () => {
          selectPaper(edge.source, edge.page_no);
          document.querySelector(".reader").scrollIntoView({ behavior: "smooth", block: "start" });
        };
        evidenceList.append(button, el("p", "graph-snippet", edge.excerpt));
      });
      box.append(evidenceList);
    }
  } catch (error) { toast(error.message); }
}
function parseCsv(text) {
  // 支持引号转义和字段中的逗号/换行；不使用 eval 或第三方依赖。
  const rows = []; let row = [], cell = "", quoted = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
      else quoted = !quoted;
    } else if (ch === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((ch === "\n" || ch === "\r") && !quoted) {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); if (row.some(x => x.trim())) rows.push(row);
      row = []; cell = "";
    } else cell += ch;
  }
  if (quoted) throw new Error("CSV 引号未闭合");
  row.push(cell); if (row.some(x => x.trim())) rows.push(row);
  return rows;
}
const MAX_CSV_BYTES = 256 * 1024 * 1024;
const MAX_CSV_RECORDS = 2000000;
function groupedCsvRows(column, counts) {
  const ranked = [...counts].sort((a, b) =>
    b[1] - a[1] || a[0].localeCompare(b[0]));
  const displayed = ranked.slice(0, 12);
  const remaining = ranked.slice(12).reduce((total, item) => total + item[1], 0);
  if (remaining) displayed.push(["其余类别（合并）", remaining]);
  return [[column, "样本数"], ...displayed.map(([label, count]) =>
    [label, String(count)])];
}
function csvPriority(index) {
  // Deterministic bounded priority sample; no claim of statistical inference.
  let x = (index + 1) >>> 0;
  x = Math.imul(x ^ x >>> 16, 0x7feb352d);
  x = Math.imul(x ^ x >>> 15, 0x846ca68b);
  return (x ^ x >>> 16) >>> 0;
}
async function sampleCsvFile(file, sampleSize = 20) {
  if (file.size > MAX_CSV_BYTES) throw new Error("CSV 文件最多 256 MB；更大的原始数据请先聚合后绘图");
  if (!Number.isInteger(sampleSize) || sampleSize < 2 || sampleSize > 200)
    throw new Error("CSV 抽样数须为 2–200");
  let header = null, total = 0, valid = 0, discarded = 0;
  let groupColumns = [], groups = {}, grouped = false;
  let multilabel = false, labelColumns = [], labelCounts = new Map(), ignored = 0;
  const sample = [], maxima = [], minima = [];
  let first = null, last = null;
  let quoted = false, pendingQuote = false, pendingCR = false, cell = "", row = [];
  const addCell = () => {
    if (row.length >= 512) throw new Error("CSV 超过 512 列，请先选择用于绘图的列");
    row.push(cell); cell = "";
  };
  const addRow = () => {
    addCell();
    if (!row.some(value => value.trim())) { row = []; return; }
    if (!header) {
      header = row.map(value => value.trim().replace(/^\uFEFF/, ""));
      if (header.length < 2) throw new Error("CSV 至少需要类别列和一个数值列");
      const imageIdAt = header.findIndex(name => /^image[_\s-]?id$/i.test(name));
      multilabel = (imageIdAt === 0 ||
        (imageIdAt === 1 && (!header[0] || /^(?:unnamed(?::\s*\d+)?|index)$/i.test(header[0]))))
        && header.length - imageIdAt >= 5;
      if (multilabel) {
        labelColumns = header.map((name, index) => ({name, index}))
          .filter(item => item.index > imageIdAt && item.name);
        labelCounts = new Map(labelColumns.map(item => [item.name, 0]));
      }
      groupColumns = header.map((name, index) => ({name, index}))
        .filter(item => item.index > 0 &&
          /(?:label|category|class|group|partition|scale|type)$/i.test(item.name))
        .slice(0, 8);
      grouped = /^(?:md5hash|sha256|.*(?:_id|_hash|_url|_path)|image|filename|url|id)$/i.test(header[0])
        && groupColumns.length > 0;
      if (grouped)
        groups = Object.fromEntries(groupColumns.map(item => [item.name, new Map()]));
      row = []; return;
    }
    total++;
    if (total > MAX_CSV_RECORDS) throw new Error("CSV 超过 200 万条记录；请先按实验指标聚合");
    if (multilabel) {
      if (labelColumns.some(({index}) =>
        row[index]?.trim() !== "0" && row[index]?.trim() !== "1")) {
        discarded++; row = []; return;
      }
      const ignore = labelColumns.find(({name}) =>
        /^do not consider this image$/i.test(name));
      if (ignore && row[ignore.index].trim() === "1") {
        ignored++; row = []; return;
      }
      valid++;
      for (const column of labelColumns) {
        if (column !== ignore && row[column.index].trim() === "1")
          labelCounts.set(column.name, labelCounts.get(column.name) + 1);
      }
      row = []; return;
    }
    if (grouped) {
      valid++;
      for (const column of groupColumns) {
        const label = (row[column.index] || "未标注").trim().slice(0, 100) || "未标注";
        const mapping = groups[column.name];
        const name = mapping.has(label) || mapping.size < 79 ? label : "其他类别（合并）";
        mapping.set(name, (mapping.get(name) || 0) + 1);
      }
      row = []; return;
    }
    const values = header.slice(1, 5).map((_, i) => Number(row[i + 1]));
    if (!row[0]?.trim() || values.some((v, i) =>
      !row[i + 1]?.trim() || !Number.isFinite(v))) { discarded++; row = []; return; }
    valid++;
    values.forEach((value, i) => {
      maxima[i] = Math.max(maxima[i] ?? -Infinity, value);
      minima[i] = Math.min(minima[i] ?? Infinity, value);
    });
    if (!first) first = values;
    last = values;
    const item = {index: total, priority: csvPriority(total),
      row: [row[0].slice(0, 160), ...values.map(String)]};
    if (sample.length < sampleSize) sample.push(item);
    else {
      let worst = 0;
      for (let i = 1; i < sample.length; i++)
        if (sample[i].priority > sample[worst].priority) worst = i;
      if (item.priority < sample[worst].priority) sample[worst] = item;
    }
    row = [];
  };
  const take = text => {
    for (const char of text) {
      if (pendingQuote) {
        pendingQuote = false;
        if (char === '"') { cell += '"'; continue; }
        quoted = false;
      }
      if (pendingCR) { pendingCR = false; if (char === "\n") continue; }
      if (quoted) {
        if (char === '"') pendingQuote = true;
        else cell += char;
      } else if (char === '"' && !cell.length) quoted = true;
      else if (char === '"') throw new Error("CSV 引号只允许出现在字段首位");
      else if (char === ",") addCell();
      else if (char === "\r" || char === "\n") {
        addRow();
        if (char === "\r") pendingCR = true;
      } else cell += char;
      if (cell.length > 100000) throw new Error("CSV 单字段超过 10 万字符，请先聚合");
    }
  };
  if (typeof file.stream === "function") {
    const reader = file.stream().getReader(), decoder = new TextDecoder("utf-8");
    try {
      while (true) {
        const {value, done} = await reader.read();
        if (done) break;
        take(decoder.decode(value, {stream: true}));
      }
      take(decoder.decode());
    } finally { reader.releaseLock(); }
  } else take(await file.text()); // Small-file fallback for older browsers.
  if (pendingQuote) { pendingQuote = false; quoted = false; }
  if (quoted) throw new Error("CSV 引号未闭合");
  if (cell || row.length) addRow();
  if (!header || (multilabel ? valid < 1 : valid < 2)) throw new Error(
    grouped ? "分组统计至少需要两行数据" :
      `这份 CSV 的前五列中没有至少两行“类别名 + 数值”。`
      + `例如 category,accuracy / A,0.9 / B,0.8。`
      + `当前列：${(header || []).slice(0, 5).join("、") || "未识别"}。`
      + "如是图像/标签元数据，请选择类别列进行频数统计，而不是把文件名或标签当准确率。"
  );
  if (multilabel) {
    const labels = [...labelCounts].filter(([name]) =>
      !/^do not consider this image$/i.test(name));
    return {
      rows: groupedCsvRows("图像特征标签", labels), groups: null,
      summary: {total, valid, discarded, ignored,
        mode: "multilabel_count", column: "图像特征标签",
        label_count: labels.length, sampled: 0,
        algorithm: "逐行统计多标签为 1 的图像数量；同一图像可计入多个类别"},
    };
  }
  if (grouped) {
    const pick = groupColumns.find(column => /^fitzpatrick_scale$/i.test(column.name))
      || groupColumns[0];
    return {rows: groupedCsvRows(pick.name, groups[pick.name]), groups: {
      columns: groupColumns.map(column => column.name),
      counts: Object.fromEntries(groupColumns.map(column => [
        column.name, [...groups[column.name].entries()]
      ])),
    }, summary: {total, valid, discarded, sampled: 0,
      mode: "category_count", column: pick.name,
      algorithm: "逐行全量类别频数统计，非模型结果"}};
  }
  const ordered = sample.sort((a, b) => a.index - b.index).map(item => item.row);
  return {rows: [header.slice(0, 5), ...ordered], groups: null,
    summary: {total, valid, discarded, sampled: ordered.length, maxima,
      minima, first, last, algorithm: "确定性哈希优先级抽样；全量逐行统计"}};
}
$("#csv").onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const result = await sampleCsvFile(file);
    state.csvRows = result.rows;
    state.csvSummary = result.summary;
    state.csvGroups = result.groups;
  const select = $("#csv-group"), chooser = $("#csv-group-control");
    chooser.hidden = !result.groups;
    select.replaceChildren();
    if (result.groups) {
      for (const column of result.groups.columns) select.append(new Option(column, column));
      select.value = result.summary.column;
      $("#chart-type").value = "bar";
    }
    drawChart();
  } catch (error) { toast(error.message); }
};
$("#csv-group").onchange = () => {
  if (!state.csvGroups || !state.csvSummary) return;
  const column = $("#csv-group").value;
  if (!state.csvGroups.columns.includes(column)) return;
  state.csvRows = groupedCsvRows(column, state.csvGroups.counts[column]);
  state.csvSummary.column = column;
  drawChart();
};
$("#chart-type").onchange = drawChart;
function closeChartWindow() {
  $("#chart-window").hidden = true;
  $("#page-layout").inert = false;
  $("#chart-open").focus();
}
$("#chart-open").onclick = () => {
  const svg = $("#chart svg");
  if (!svg) return toast("请先上传并生成图表");
  const copy = svg.cloneNode(true);
  const width = Number(svg.getAttribute("viewBox")?.split(/\s+/)[2]) || 900;
  copy.style.width = `${Math.max(700, width)}px`;
  copy.style.maxWidth = "none";
  copy.style.height = "auto";
  $("#chart-window-preview").replaceChildren(copy);
  $("#chart-window-caption").textContent = $("#caption").textContent;
  $("#chart-window").hidden = false;
  $("#page-layout").inert = true;
  $("#chart-close").focus();
};
$("#chart-close").onclick = closeChartWindow;
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("#chart-window").hidden) closeChartWindow();
});
$("#export-chart").onclick = () => {
  const svg = $("#chart svg");
  if (!svg) return;
  const data = new XMLSerializer().serializeToString(svg);
  const url = URL.createObjectURL(new Blob([data], {type: "image/svg+xml;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url; link.download = "sourcelab_figure.svg"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 2500);
};
function drawChart() {
  const rows = state.csvRows;
  if (!rows) return;
  const box = $("#chart");
  if (rows.length < 3 || rows[0].length < 2) return toast("CSV 至少需要表头及两行、两列数据");
  const headers = rows[0].slice(1, 5);
  const full = state.csvSummary;
  const multilabel = full?.mode === "multilabel_count";
  const datasetGroups = multilabel || full?.mode === "category_count";
  const validRows = rows.slice(1).filter(row =>
    row[0]?.trim() && headers.every((_, i) =>
      row[i + 1]?.trim() && Number.isFinite(Number(row[i + 1]))));
  const points = (datasetGroups ? validRows : validRows.slice(0, 20)).map(row => ({
      label: row[0], values: headers.map((_, i) => Number(row[i + 1]))
    }));
  if (points.length < (datasetGroups ? 1 : 2))
    return toast(datasetGroups ? "没有可展示的类别频数" :
      "需至少两条类别+数值完整记录；图像/标签 CSV 请使用类别频数统计");
  const chartKind = $("#chart-type").value;
  if ((chartKind === "radar" || chartKind === "radar3d") && (
    points.length < 3 || points.length > 10 || valuesOutsideUnitRange(points)
  )) return toast("雷达图只适合 3–10 个维度，且数值须预先归一化到 0–1；频数请改用柱状图");
  const values = points.flatMap(x => x.values);
  const high = Math.max(0, ...values), low = Math.min(0, ...values);
  const min = low === high ? low - 1 : low, max = low === high ? high + 1 : high;
  const colors = ["#23876d", "#d08b3e", "#4675b5", "#a05591"];
  const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("xmlns", ns);
  const plotWidth = Math.max(660, points.length * 100 + 135);
  svg.setAttribute("viewBox",
    chartKind === "radar" ? "0 0 600 280"
      : chartKind === "radar3d" ? "0 0 600 325" : `0 0 ${plotWidth} 340`);
  svg.style.width = chartKind === "radar" || chartKind === "radar3d"
    ? "600px" : `${plotWidth}px`;
  svg.style.height = chartKind === "radar3d" ? "325px" :
    chartKind === "radar" ? "280px" : "340px";
  const mk = (tag, attrs) => {
    const n = document.createElementNS(ns, tag);
    for (const [key, value] of Object.entries(attrs)) n.setAttribute(key, String(value));
    svg.append(n); return n;
  };
  if (chartKind === "radar") {
    const cx = 300, cy = 134, radius = 94;
    const spot = (i, value) => {
      const angle = -Math.PI / 2 + 2 * Math.PI * i / points.length;
      return [cx + Math.cos(angle) * radius * value,
        cy + Math.sin(angle) * radius * value];
    };
    for (const level of [.25,.5,.75,1]) {
      mk("polygon", {
        points: points.map((_,i) => spot(i,level).join(",")).join(" "),
        fill:"none",stroke:"#ccdcd3","stroke-width":1
      });
    }
    points.forEach((point,i) => {
      const [x,y] = spot(i,1);
      mk("line",{x1:cx,y1:cy,x2:x,y2:y,stroke:"#d3e4d8"});
      const [lx,ly] = spot(i,1.16);
      mk("text",{x:lx,y:ly,"text-anchor":"middle","font-size":10,fill:"#3c6151"})
        .textContent = point.label.slice(0,8);
    });
    headers.forEach((header,series) => {
      mk("polygon", {
        points:points.map((point,i) => spot(i,point.values[series]).join(",")).join(" "),
        fill:colors[series], "fill-opacity":.13,
        stroke:colors[series],"stroke-width":2
      });
    });
  } else if (chartKind === "radar3d") {
    // Data geometry: x,y = radial value on each category axis.
    // z = *categorical series index*, not a third measured outcome.
    // Isometric projection is deterministic so exported SVG is reproducible.
    const centerX = 260, baseY = 225, radius = 88, layerStep = 36;
    const project = (i, value, layer) => {
      const angle = -Math.PI / 2 + i * 2 * Math.PI / points.length;
      const dx = Math.cos(angle) * radius * value;
      const dy = Math.sin(angle) * radius * value;
      return [
        centerX + dx + layer * 14,
        baseY + dy * .68 - layer * layerStep - dx * .20
      ];
    };
    headers.forEach((header, series) => {
      const outer = points.map((_,i) => project(i,1,series));
      mk("polygon", {
        points:outer.map(pair => pair.join(",")).join(" "),
        fill:"none",stroke:"#cbded1","stroke-width":1
      });
      const origin = [centerX + series * 14, baseY - series * layerStep];
      outer.forEach(([x,y]) => mk("line", {
        x1:origin[0],y1:origin[1],x2:x,y2:y,stroke:"#e0ebe2"
      }));
      mk("polygon", {
        points:points.map((point,i) =>
          project(i,point.values[series],series).join(",")).join(" "),
        fill:colors[series],"fill-opacity":.19,stroke:colors[series],
        "stroke-width":2
      });
      if (series > 0) {
        const previous = [centerX + (series-1)*14,
          baseY - (series-1)*layerStep];
        mk("line", {
          x1:previous[0],y1:previous[1],x2:origin[0],y2:origin[1],
          stroke:"#8ba999","stroke-dasharray":"4,3"
        });
      }
      const plane = mk("text", {
        x:415,y:48 + series*17,"font-size":10,fill:colors[series]
      });
      plane.textContent = `z=${series+1}: ${header.slice(0,18)}（系列层）`;
    });
    points.forEach((point,i) => {
      const [x,y] = project(i,1,0);
      const label = mk("text", {
        x:x+(x>=centerX?12:-12),y:y+(y>=baseY?14:-9),
        "text-anchor":x>=centerX?"start":"end",
        "font-size":10,fill:"#33574a"
      });
      label.textContent = point.label.slice(0,8);
    });
  } else {
    const left = 90, right = plotWidth - 30, top = 34, bottom = 198;
    const lower = Math.min(0, low), upper = Math.max(0, high);
    const y = value => bottom - (value - lower) * (bottom - top) /
      (upper === lower ? 1 : upper - lower);
    const x = i => left + (i + 0.5) * (right - left) / points.length;
    const tick = value => Number.isInteger(value) ? String(value) :
      Number(value.toPrecision(3)).toString();
    for (let step = 0; step <= 4; step++) {
      const value = lower + step * (upper - lower) / 4;
      const yy = y(value);
      mk("line", {x1: left, x2: right, y1: yy, y2: yy,
        stroke: step === 0 ? "#aebeb6" : "#e3ede6", "stroke-width": 1});
      mk("text", {x: left - 9, y: yy + 4, "text-anchor": "end",
        "font-size": 11, fill: "#36554a"}).textContent = tick(value);
    }
    mk("line", {x1: left, y1: top, x2: left, y2: bottom,
      stroke: "#879f92", "stroke-width": 1.4});
    mk("line", {x1: left, y1: y(0), x2: right, y2: y(0),
      stroke: "#719481", "stroke-width": 1.4});
    mk("text", {x: left, y: 23, "font-size": 12, fill: "#345a4b"})
      .textContent = datasetGroups ? "样本数" : headers.join(" / ").slice(0, 54);
    points.forEach((point, i) => {
      const xx = x(i);
      const t = mk("text", {x: xx, y: 221, "text-anchor": "end",
        transform: `rotate(-46 ${xx} 221)`, "font-size": 11, fill: "#36584b"});
      t.textContent = point.label.length > 17
        ? point.label.slice(0, 16) + "…" : point.label;
      const tooltip = document.createElementNS(ns, "title");
      tooltip.textContent = point.label;
      t.append(tooltip);
    });
    mk("text", {x: (left + right) / 2, y: 298, "text-anchor": "middle",
      "font-size": 12, fill: "#345a4b"}).textContent = rows[0][0] || "类别";
    headers.forEach((header, series) => {
      if ($("#chart-type").value === "bar") {
        points.forEach((point, i) => {
          const w = Math.max(3, (right - left) / points.length * .68 / headers.length);
          const top = Math.min(y(point.values[series]), y(0));
          mk("rect", { x: x(i) - w * headers.length / 2 + w * series, y: top,
            width: w - 1, height: Math.max(1, Math.abs(y(0) - y(point.values[series]))),
            fill: colors[series], rx: 2 });
        });
      } else {
        const path = points.map((point, i) =>
          `${i ? "L" : "M"}${x(i)},${y(point.values[series])}`).join(" ");
        mk("path", { d:path, fill:"none", stroke:colors[series], "stroke-width":2.5 });
        points.forEach((point, i) => mk("circle", {
          cx:x(i), cy:y(point.values[series]), r:3.2, fill:colors[series]
        }));
      }
    });
  }
  headers.forEach((header, series) => {
    const legendX = 75 + series * 150;
    const legendY = chartKind === "radar" ? 255
      : chartKind === "radar3d" ? 300 : 320;
    mk("rect", {x:legendX,y:legendY,width:10,height:9,fill:colors[series]});
    mk("text", {x:legendX+14,y:legendY+9,"font-size":10,fill:"#52655b"}, header.slice(0,16))
      .textContent = header.slice(0,16);
  });
  box.replaceChildren(svg);
  $("#chart-open").disabled = false;
  $("#export-chart").disabled = false;
  const summaries = headers.map((header, index) => {
    if (datasetGroups) return `展示类别的最高频数 ${Math.max(...points.map(p => p.values[index]))}`;
    if (full) return `${header} 全量最大值 ${full.maxima[index]}`;
    const best = points.reduce((a, b) =>
      a.values[index] >= b.values[index] ? a : b);
    return `${header} 的最大值 ${best.values[index]}（${best.label}）`;
  });
  const radar = chartKind === "radar" || chartKind === "radar3d";
  const trend = chartKind === "line"
    ? `首末行变化：${headers.map((name,i) => {
      const delta = full
        ? full.last[i] - full.first[i]
        : points.at(-1).values[i] - points[0].values[i];
      return `${name} ${delta > 0 ? "增加" : delta < 0 ? "减少" : "不变"} ${Math.abs(delta).toFixed(4)}`;
    }).join("；")}。` : "";
  $("#caption").textContent =
    `Figure. ${chartKind === "radar3d"
      ? "三维分层雷达等轴投影（z仅表示数据系列层级，不是额外测量维度；数值均已在0–1）"
      : radar ? "二维雷达图（各维度原始数值均在 0–1）" : "数值图"}：`
    + `${rows[0][0] || "类别"}与 ${headers.join("、")}（${
      multilabel ? `原表 ${full.total} 行、有效 ${full.valid} 张图像；忽略“Do not consider this image”标记 ${full.ignored} 行，丢弃无效 ${full.discarded} 行；${full.label_count} 种标签中显示前列高频标签和合并的其他标签；一张图像可同时有多个标签（不是模型准确率）` :
      datasetGroups ? `全量 ${full.total} 行按「${full.column}」分组；图示 ${points.length} 个类别的频数（不是论文模型准确率）` :
      full ? `全量 ${full.valid}/${full.total} 条有效；图示确定性抽样 ${points.length} 条` :
      `${points.length} 条完整记录`}；${summaries.join("；")}）。`
    + `${trend}${full?.discarded ? `跳过 ${full.discarded} 条缺失或非数值行。` :
      !full && rows.length - 1 - points.length ?
        `跳过 ${rows.length - 1 - points.length} 条缺失或非数值行。` : ""}`
    + (datasetGroups && !multilabel ?
      "类别值按 CSV 原样保留；-1 等编码的含义须查数据集说明，不自动当成有效肤色类别。"
      : "")
    + "此图仅描述数据，不作因果推断。";
  const table = el("table", "data-preview");
  const head = el("tr");
  [rows[0][0], ...headers].forEach(label => head.append(el("th", "", label)));
  table.append(head);
  points.forEach(point => {
    const tr = el("tr");
    [point.label, ...point.values].forEach(cell => tr.append(el("td", "", cell)));
    table.append(tr);
  });
  $("#data-table").replaceChildren(table);
}
function valuesOutsideUnitRange(points) {
  return points.some(point => point.values.some(value => value < 0 || value > 1));
}
async function startup() {
  try {
    const health = await api("/api/health");
    state.modelConfigured = health.model_configured;
    $("#health").textContent = health.model_configured
      ? "● 已填写模型配置（鉴权待验证）" : "● 离线证据模式";
    $("#ask-mode").textContent = health.model_configured
      ? "已填写模型接口，但不保证密钥有效。检索原文后尝试生成带引用草稿；鉴权 401 或校验失败则退回原文证据。"
      : "未连接大模型：只检索并展示带 PDF 页码的原文证据，不自动生成科研结论。请先选论文并使用原文术语提问。";
    $("#writing-mode").textContent =
      health.model_configured
        ? "基础框架由本地证据生成；可自愿勾选模型背景草稿。发送命中的原文至所配模型；草稿只通过引用/数字规则，须人工核验。"
        : "未连接大模型：当前只能生成基于本地证据的框架模板；勾选论文并输入研究想法。";
    $("#writing-use-model").disabled = !health.model_configured;
    $("#frontier-model").disabled = !health.model_configured;
    $("#writing-plan-ai").disabled = !health.model_configured;
    $("#diagram-ai-btn").disabled = !health.model_configured;
    const samples = await api("/api/samples");
    for (const name of samples.files) $("#sample").append(new Option(name, name));
    await refresh();
    restoreRecentResults();
    await loadSubscriptions();
    setInterval(async () => {
      if (state.papers.some(p => p.status === "processing")) {
        try { await refresh(); } catch { /* 网络暂断，下次再试 */ }
      }
    }, 1800);
    setInterval(() => {
      if (state.selected && state.translationJobId) {
        loadTranslationJobs(state.selected);
      }
    }, 4000);
  } catch (error) { $("#health").textContent = "○ 服务不可用"; toast(error.message); }
}
startup();
