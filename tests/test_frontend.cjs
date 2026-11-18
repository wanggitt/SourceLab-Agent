// Node-only frontend regression harness; no browser or third-party packages.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Node {
  constructor(tag) {
    this.tag = tag;
    this.attrs = {};
    this.children = [];
    this.disabled = true;
    this.value = "";
    this.textContent = "";
    this.style = {setProperty(key, value) { this[key] = value; }};
    this.classList = {
      values: new Set(), add(key) {this.values.add(key);},
      remove(key) {this.values.delete(key);},
      toggle(key, enabled) {
        if (enabled) this.values.add(key); else this.values.delete(key);
      },
      contains(key) {return this.values.has(key);}
    };
  }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  cloneNode(deep) {
    const other = new Node(this.tag);
    other.attrs = {...this.attrs};
    other.style = {...this.style};
    other.textContent = this.textContent;
    if (deep) other.children = this.children.map(node =>
      node?.cloneNode ? node.cloneNode(true) : node);
    return other;
  }
  querySelector(selector) {
    return selector === "svg" ?
      this.children.find(node => node.tag === "svg") : null;
  }
  querySelectorAll(selector) {
    const attr = selector === "[data-paper-id]" ? "data-paper-id" :
      selector === "[data-edge-source]" ? "data-edge-source" : "";
    return attr ? this.children.filter(node => node.attrs[attr]) : [];
  }
  append(...items) { this.children.push(...items); }
  prepend(...items) { this.children.unshift(...items); }
  replaceChildren(...items) { this.children = [...items]; }
  addEventListener(name, handler) { (this.listeners ||= {})[name] = handler; }
  focus() {}
}
const elements = new Map();
function get(selector) {
  if (!elements.has(selector)) elements.set(selector, new Node(selector));
  return elements.get(selector);
}
const sandbox = {
  document: {
    querySelector: get,
    createElement: tag => new Node(tag),
    createElementNS: (_, tag) => new Node(tag),
    documentElement: new Node("html"),
    addEventListener() {},
  },
  window: {innerWidth: 1600, addEventListener() {}},
  localStorage: {
    data: {}, getItem(key) {return this.data[key] || null;},
    setItem(key, value) {this.data[key] = value;}
  },
  console,
  TextDecoder,
  setTimeout() { return 1; },
  clearTimeout() {},
};
vm.createContext(sandbox);
const code = fs.readFileSync(path.join(__dirname, "..", "static", "app.js"), "utf8");
const template = fs.readFileSync(path.join(__dirname, "..", "static", "index.html"), "utf8");
assert.equal(template.includes("引用 [n] ↔ 参考文献（仅数字编号）"), false);
assert.ok(template.includes("参考文献下钻 · 原文候选"));
vm.runInContext(code.replace(/\bstartup\(\);\s*$/, ""), sandbox);
const run = script => vm.runInContext(script, sandbox);
assert.equal(get("#font-level").textContent, "100%");
get("#font-larger").onclick();
assert.equal(get("#font-level").textContent, "110%");
get("#toggle-library").onclick();
assert.equal(get("#library-panel").hidden, true);
assert.equal(get("#toggle-library").attrs["aria-expanded"], "false");
get("#toggle-library").onclick();
assert.equal(get("#library-panel").hidden, false);
get("#focus-assistant").onclick();
assert.equal(get("#page-layout").classList.contains("focus-assistant"), true);
get("#focus-assistant").onclick();
get("#layout-reset").onclick();
assert.equal(get("#font-level").textContent, "100%");
run("state.csvRows=parseCsv('metric,accuracy\\nA,0.2\\nB,0.7\\nC,0.5');state.csvSummary=null;document.querySelector('#chart-type').value='bar';drawChart()");
assert.equal(get("#chart-open").disabled, false);
sandbox.document.querySelector = selector =>
  selector === "#chart svg" ? get("#chart").children[0] : get(selector);
get("#chart-open").onclick();
assert.equal(get("#chart-window").hidden, false);
assert.equal(get("#chart-window-preview").children[0].tag, "svg");
get("#chart-close").onclick();
  assert.equal(get("#chart-window").hidden, true);
assert.equal(get("#graph-expand").disabled, true);
assert.equal(get("#diagram-expand").disabled, true);
get("#focus-assistant").onclick();
get("#focus-assistant").onclick();
assert.equal(get("#page-layout").classList.contains("focus-assistant"), false);
assert.equal(get("#assistant-panel").hidden, false);
assert.equal(get("#page-layout").classList.contains("hide-library"), false);
console.log("chart zoom/close and Agent focus restored without hiding READ");
assert.equal(get("#assistant-resizer").attrs["aria-valuenow"], "370");
get("#library-resizer").listeners.keydown({
  key: "ArrowRight", preventDefault() {}
});
assert.equal(get("#library-resizer").attrs["aria-valuenow"], "330");
get("#library-resizer").listeners.keydown({key: "Home", preventDefault() {}});
assert.equal(get("#library-resizer").attrs["aria-valuenow"], "260");
const event = {mode: "needs_attention", id: 1, created_at: "2026-01-01T00:00:00Z",
  question: "两篇论文有无共同点?", evidence_ids: [],
  steps: [{tool: "compare_papers", status: "needs_input", message: "请先勾选两篇论文"}]};
run("renderAuditRows(document.querySelector('#audit-list'), ["
  + JSON.stringify(event) + "])");
assert.equal(get("#audit-list").children[0].children[0].textContent, "需要操作");
assert.match(get("#audit-list").children[0].children[3].textContent, /没有可供核对/);
run("renderAuditRows(document.querySelector('#audit-list'), Array.from({length:8}, (_, i) => ({"
  + "id:i+1,created_at:'2026-01-01T00:00:00Z',question:'问题'+i,"
  + "mode:'evidence_only',evidence_ids:[],steps:[]})))");
assert.equal(get("#audit-list").children.length, 5);
assert.equal(get("#audit-more").hidden, false);
run("auditExpanded=true; renderAuditRows(document.querySelector('#audit-list'), "
  + "Array.from({length:8}, (_, i) => ({id:i+1,created_at:'2026-01-01T00:00:00Z',"
  + "question:'问题'+i,mode:'evidence_only',evidence_ids:[],steps:[]})))");
assert.equal(get("#audit-list").children.length, 8);
run("auditExpanded=false");
run(`renderStructure({
  note:"仅候选，须核验", metadata:{authors:["A"], affiliations:["Lab"], abstract:"A summary"},
  heading_tree:[{title:"1 Introduction",level:1,page_no:1,children:[
    {title:"1.1 Methods",level:2,page_no:2,children:[]}]}],
  captions:[{type:"figure_caption",excerpt:"Figure 1: Model",page_no:2}],
  equations:[],appendices:[],
  references:{headings:[],numbered_entries:[]}
}, "aaaaaaaaaaaaaa")`);
const structureGroups = get("#structure-results").children.filter(child =>
  child.tag === "details");
assert.equal(structureGroups.length >= 3, true);
assert.match(structureGroups[0].children[0].textContent, /图注与表题/);
assert.match(structureGroups[0].children[1].children[0].textContent, /Figure 1/);
assert.equal(structureGroups.some(group =>
  group.children[0].textContent.includes("标题树")), false);

const rows = run("parseCsv('epoch,accuracy,loss\\n1,0.72,0.5\\n2,0.8,0.4\\n3,0.84,0.33\\n')");
assert.equal(rows.length, 4);
assert.equal(run("parseCsv('category,value\\n\"A,B\",42\\nC,43')")[1][0], "A,B");
run("state.csvRows = parseCsv('epoch,accuracy,loss\\n1,0.72,0.5\\n2,0.8,0.4\\n3,0.84,0.33')");
get("#chart-type").value = "bar";
run("drawChart()");
let svg = get("#chart").children[0];
assert.equal(svg.tag, "svg");
assert.equal(svg.children.filter(x => x.tag === "rect").length, 8); // six bars, two swatches
assert.match(get("#caption").textContent, /accuracy 的最大值 0\.84/);
assert.match(get("#caption").textContent, /loss 的最大值 0\.5/);
assert.equal(get("#export-chart").disabled, false);
get("#chart-type").value = "line";
run("drawChart()");
svg = get("#chart").children[0];
assert.equal(svg.children.filter(x => x.tag === "path").length, 2);
assert.equal(get("#data-table").children[0].tag, "table");
assert.equal(get("#data-table").children[0].children.length, 4);
run("state.csvRows = parseCsv('metric,modelA,modelB\\nA,0.2,0.4\\nB,0.7,0.6\\nC,0.8,1.0')");
get("#chart-type").value = "radar";
run("drawChart()");
svg = get("#chart").children[0];
assert.equal(svg.children.filter(x => x.tag === "polygon").length, 6);
assert.match(get("#caption").textContent, /二维雷达图/);
get("#chart-type").value = "radar3d";
run("drawChart()");
svg = get("#chart").children[0];
assert.equal(svg.children.filter(x => x.tag === "polygon").length, 4);
assert.match(get("#caption").textContent, /z仅表示数据系列层级/);
assert.equal(get("#export-chart").disabled, false);
run("state.csvRows = parseCsv('metric,modelA\\nA,0.2\\nB,0.7\\nC,2.0')");
get("#chart-type").value = "radar3d";
run("drawChart()");
assert.match(get("#toast").textContent, /归一化到 0–1/);
console.log("frontend CSV / multiseries bar / line / caption checks passed");

const report = JSON.parse(
  fs.readFileSync(path.join(__dirname, "graph20_report.json"), "utf8")
);
const nodeMap = new Map(report.papers.map(paper => [paper.filename, paper]));
const graph = {
  nodes: report.papers.map(paper => ({
    id: paper.id, title: paper.title, filename: paper.filename,
    in_degree: report.all_edges.filter(edge => edge.target_filename === paper.filename).length,
    pagerank: 1 / report.papers.length,
  })),
  edges: report.all_edges.map(edge => ({
    source: nodeMap.get(edge.source_filename).id,
    target: nodeMap.get(edge.target_filename).id,
    page_no: edge.source_page,
    match_type: edge.match_type,
    excerpt: edge.excerpt,
  })),
  collapsed_versions: false, note: "graph20 offline trial",
};
sandbox.fetch = async () => ({
  ok: true, json: async () => graph,
});
run("drawGraph()").then(() => {
  const graphSvg = get("#graph").children.find(node => node.tag === "svg");
  assert.ok(graphSvg, "graph SVG must render");
  assert.equal(get("#graph-expand").disabled, false);
  sandbox.document.querySelector = selector =>
    selector === "#graph svg" ? get("#graph").children.find(node => node.tag === "svg")
      : selector === "#diagram-preview svg" ?
        get("#diagram-preview").children.find(node => node.tag === "svg")
      : selector === "#visual-preview svg" ?
        get("#visual-preview").children.find(node => node.tag === "svg")
      : selector === "#chart svg" ? get("#chart").children[0] : get(selector);
  get("#graph-expand").onclick();
  assert.equal(get("#visual-window").hidden, false);
  assert.equal(get("#visual-preview").children[0].tag, "svg");
  assert.ok(get("#visual-preview").children[0].children.some(node =>
    node.attrs["data-paper-id"] && typeof node.onclick === "function"));
  get("#visual-larger").onclick();
  assert.equal(get("#visual-scale").textContent, "125%");
  get("#visual-close").onclick();
  assert.equal(get("#visual-window").hidden, true);
  assert.equal(graphSvg.children.filter(node => node.tag === "g").length, 20);
  assert.equal(graphSvg.children.filter(node => node.tag === "line").length,
    report.graph_edges);
  get("#graph-search").oninput({target: {value: "layer normalization"}});
  let updated = get("#graph").children.find(node => node.tag === "svg");
  let highlighted = updated.children.filter(node => node.tag === "g"
    && node.attrs.opacity === "1");
  assert.ok(highlighted.length >= 1 && highlighted.length < 20);
  assert.match(get("#graph-selection").textContent, /搜索.*匹配/);
  get("#graph-edge-filter").onchange({target: {value: "arxiv_id"}});
  updated = get("#graph").children.find(node => node.tag === "svg");
  const strongEdges = report.all_edges.filter(edge => edge.match_type === "arxiv_id");
  assert.equal(updated.children.filter(node => node.tag === "line").length,
    strongEdges.length);
  run(`state.graphQuery = ""; state.graphFocus = "${nodeMap.get("1706.03762v7.pdf").id}"; renderGraph()`);
  updated = get("#graph").children.find(node => node.tag === "svg");
  assert.ok(updated.children.filter(node => node.tag === "line"
    && node.attrs.opacity === "0.12").length > 0);
  assert.match(get("#graph-selection").textContent, /直接邻居/);
  get("#graph-clear").onclick();
  updated = get("#graph").children.find(node => node.tag === "svg");
  assert.equal(updated.children.filter(node => node.tag === "line").length,
    report.graph_edges);
  console.log("20-paper graph frontend render checks passed");
  const calls = [];
  sandbox.fetch = async url => {
    calls.push(url);
    const value = url.startsWith("/api/recommendations?")
      ? {note: "来自 arXiv", items: [{
        identifier: "2411.12345v1", title: "Local Test Paper",
        published: "2024-11-20", authors: ["Example"],
        reasons: ["关键词"], score: 0.8, feedback: 0
      }]}
      : url.startsWith("/api/arxiv/metadata?")
        ? {paper: {identifier: "2411.12345v1",
          title: "Local Test Paper", authors: ["Example"],
          published: "2024-11-20"}}
        : url === "/api/arxiv/download"
          ? {id: "aaaaaaaaaaaaaa", status: "processing"}
        : url === "/api/publication/verify"
          ? {venue: "ICLR", year: "2015", type: "conference",
            venue_source: "DBLP bibliographic index",
            matches: [{source: "DBLP", title: "Local Test Paper",
              venue: "ICLR", year: "2015"}],
            errors: [], impact_note: "JCR 年度数据未核验",
            note: "严格题名匹配",
            manual_links: {
              dblp: "https://dblp.org/search?q=Local%20Test%20Paper",
              crossref: "https://search.crossref.org/?q=Local%20Test%20Paper",
              google_scholar: "https://scholar.google.com/scholar?q=Local%20Test%20Paper",
              jcr: "https://jcr.clarivate.com/",
            }}
        : null;
    if (!value) throw new Error(`Unexpected request: ${url}`);
    return {ok: true, json: async () => value};
  };
  sandbox.window.confirm = () => false;
  get("#recent-topic").value = "machine learning";
  return run("document.querySelector('#recent-form').onsubmit({preventDefault(){}})")
    .then(async () => {
      const card = get("#recent-results").children[1];
      const cached = JSON.parse(sandbox.localStorage.getItem("sourcelab-recent-results-v1"));
      assert.equal(cached.topic, "machine learning");
      assert.equal(cached.data.items[0].identifier, "2411.12345v1");
      const venue = card.children.find(child =>
        child.className === "publication-verification");
      assert.ok(venue, "manual metadata lookup must be available on each candidate");
      await venue.children[1].onclick();
      assert.ok(calls.includes("/api/publication/verify"));
      assert.match(venue.children[2].children[1].textContent, /ICLR/);
      assert.ok(venue.children[2].children.some(child =>
        child.tag === "a" && child.href?.includes("scholar.google.com")));
      const buttons = card.children.find(child => child.className === "recommend-actions");
      const download = buttons.children.find(child =>
        child.tag === "button" && child.textContent.includes("下载 PDF"));
      assert.ok(download, "recent arXiv candidates must have a download action");
      await download.onclick();
      assert.ok(calls.some(url => url.startsWith("/api/arxiv/metadata?")));
      assert.ok(!calls.some(url => url === "/api/arxiv/download"),
        "no PDF download without user confirmation");
      assert.match(card.children.at(-1).textContent, /取消了下载/);
      sandbox.window.confirm = () => true;
      run("refresh = async () => {}"); // test only the explicit download control
      await download.onclick();
      assert.ok(calls.some(url => url === "/api/arxiv/download"),
        "confirmed official candidate must submit one explicit PDF import");
      assert.match(card.children.at(-1).textContent, /已开始导入/);
      run("restoreRecentResults()");
      assert.match(get("#recent-results").children[0].textContent, /上次查询缓存/);
      assert.equal(get("#recent-topic").value, "machine learning");
      console.log("recent arXiv candidate verify / cancel / confirmed import checks passed");
      sandbox.fetch = async url => ({
        ok: true, json: async () => url.includes("/future-work")
          ? {note: "原文限制候选", items: [{
              source_page: 9, signal: "Limitations and Outlook",
              source_excerpt: "Tight screening requires a sufficient number of conflicts.",
              status: "待人工核验", related_local_papers: []
            }]}
          : url === "/api/translate"
            ? {translation: "严格筛选需要足够多的冲突样本。",
               audit_id: 48}
            : {}
      });
      run("state.selected='aaaaaaaaaaaaaa'; state.papers=[{id:'aaaaaaaaaaaaaa',status:'ready',title:'Example'}]; state.modelConfigured=true");
      return run("document.querySelector('#future-btn').onclick()")
        .then(async () => {
          const result = get("#future-results").children[1];
          const translate = result.children.find(x => x.tag === "button"
            && x.textContent.includes("翻译这条"));
          assert.ok(translate);
          await translate.onclick();
          assert.ok(result.children.some(node =>
            node.textContent.includes("严格筛选需要足够多的冲突样本")));
          console.log("Future Work optional translation keeps original English evidence");
          const requested = [];
          sandbox.fetch = async (url, options) => {
            requested.push([url, options?.body]);
            if (url.endsWith("/equations/explain-all")) return {
              ok: true, json: async () => ({
                count: 2, total_candidates: 2, truncated: false,
                missing_number_candidates: [2],
                message: "离线模拟：原文候选", audit_id: 3,
                warning: "须核对 PDF", draft: null,
                equations: [
                  {source_id: "E1", page_no: 4, formula: "a = b (1)", context: ""},
                  {source_id: "E2", page_no: 4, formula: "y = a (3)", context: ""}
                ]
              })
            };
            if (url === "/api/audit") return {ok: true, json: async () => ({items: []})};
            throw new Error(`Unexpected request: ${url}`);
          };
          run(`renderStructure({
            note:"仅候选", equations:[
              {page_no:4,excerpt:"a = b (1)"},
              {page_no:4,excerpt:"y = a (3)"}
            ], captions:[], appendices:[], references:{headings:[]}
          }, "aaaaaaaaaaaaaa")`);
          assert.match(get("#explain-all-equations").textContent, /全部已识别/);
          return get("#explain-all-equations").onclick().then(() => {
            assert.ok(requested.some(([url, body]) =>
              url.endsWith("/equations/explain-all") && JSON.parse(body).confirm_cost));
            const nodes = get("#equations-all-results").children;
            assert.equal(nodes.filter(node => node.className === "equation-batch-row").length, 2);
            assert.ok(nodes.some(node => node.textContent.includes("编号间隔")));
            sandbox.fetch = async (url) => ({
              ok: true, json: async () => url === "/api/audit" ? {items: []} : ({
                count: 2, total_candidates: 2, truncated: false,
                total_groups: 2, attempted_groups: 2, completed_groups: 1,
                status: "partial_needs_review",
                message: "第二组输出被截断；重新请求可能重复计费",
                warning: "须核对 PDF", audit_id: 4,
                usage: {total_tokens: 290, estimated_cost_usd: null},
                draft: {equations: [{
                  source_id: "E1", input: "输入 [E1]", transformation: "变换 [E1]",
                  output: "输出 [E1]", why: "原文未说明 [E1]",
                  uncertainty: "需核对", source_quote: "a = b (1)"
                }, null], chain: "仅第一组", chain_uncertainty: "第二组未完成"},
                equations: [
                  {source_id: "E1", page_no: 4, formula: "a = b (1)", context: ""},
                  {source_id: "E2", page_no: 4, formula: "y = a (3)", context: ""}
                ]
              })
            });
            return get("#explain-all-equations").onclick().then(() => {
              const updated = get("#equations-all-results").children;
              assert.equal(updated.filter(node => node.className === "equation-batch-row").length, 2);
              assert.ok(updated.some(node => node.textContent.includes("本次实际向模型请求 2 组")));
              assert.ok(updated.some(node => node.textContent.includes("290 tokens")));
              console.log("all detected equations batch / partial draft / usage checks passed");
            });
          });
        });
    });
}).catch(error => {
  console.error(error);
  process.exitCode = 1;
});

// Test chunk boundaries inside quoted fields and a bounded dataset summary.
const largeCsv = '\uFEFFmetric,value\n"A,B",0\r\n'
  + Array.from({length: 120}, (_, i) => `row${i},${i + 1}\r\n`).join("")
  + 'invalid,NA\r\n';
const bytes = Buffer.from(largeCsv);
const streamedFile = {
  size: bytes.length,
  stream() {
    let cursor = 0;
    return {getReader() {return {
      read: async () => {
        if (cursor >= bytes.length) return {done: true};
        const value = bytes.subarray(cursor, cursor + 7);
        cursor += value.length;
        return {done: false, value};
      },
      releaseLock() {}
    };}};
  }
};
// No model call or network request is involved in CSV streaming.
sandbox.fixtureFile = streamedFile;
run("sampleCsvFile(fixtureFile)").then(result => {
  assert.equal(result.summary.total, 122);
  assert.equal(result.summary.valid, 121);
  assert.equal(result.summary.discarded, 1);
  assert.equal(result.summary.maxima[0], 120);
  assert.equal(result.rows.length, 21);
  assert.equal(result.rows[0][0], "metric");
  sandbox.fixtureResult = result;
  run("state.csvRows = fixtureResult.rows; state.csvSummary = fixtureResult.summary");
  get("#chart-type").value = "line";
  run("drawChart()");
  assert.match(get("#caption").textContent, /全量 121\/122 条有效/);
  assert.match(get("#caption").textContent, /确定性抽样 20 条/);
  assert.match(get("#caption").textContent, /全量最大值 120/);
  assert.equal(get("#data-table").children[0].children.length, 21);
  console.log("streaming CSV / quoted boundary / deterministic sample checks passed");
  const topology = {
    diagram: {nodes: [
      {id: "N1", label: "原文编码器", kind: "source",
        source_id: "E1", source_quote: "The encoder creates representations."},
      {id: "N2", label: "提出适配", kind: "proposal", source_id: "", source_quote: ""}
    ], edges: [{from: "N1", to: "N2", label: "待验证连接"}]},
    evidence: [{source_id: "E1", paper_id: "aaaaaaaaaaaaaa", page_no: 4}],
    message: "待核对设计", audit_id: 50, status: "draft_needs_review",
    usage: {total_tokens: 55},
    note: "证据仅词面匹配"
  };
  sandbox.fixtureTopology = topology;
  run("renderProposedTopology(fixtureTopology)");
  assert.match(get("#diagram-code").textContent, /flowchart LR/);
  assert.match(get("#diagram-code").textContent, /N1.*E1/);
  assert.match(get("#diagram-code").textContent, /待验证设计/);
  assert.equal(get("#diagram-preview").children[0].tag, "svg");
  assert.equal(get("#diagram-preview").children[1].tag, "button");
  assert.equal(get("#diagram-expand").disabled, false);
  get("#diagram-expand").onclick();
  assert.equal(get("#visual-window").hidden, false);
  get("#visual-close").onclick();
  console.log("optional evidence-linked topology SVG / Mermaid checks passed");
  const big = Buffer.from("metric,value\n" +
    Array.from({length: 85000}, (_, i) => `item_${i},${i}\n`).join(""));
  assert.ok(big.length > 1024 * 1024);
  sandbox.bigFixture = {
    size: big.length,
    stream() {
      let pos = 0;
      return {getReader() {return {
        read: async () => pos >= big.length ? {done: true} :
          {done: false, value: big.subarray(pos, pos += 16384).subarray(0, 16384)},
        releaseLock() {}
      };}};
    }
  };
  return run("sampleCsvFile(bigFixture)").then(bigResult => {
    assert.equal(bigResult.summary.total, 85000);
    assert.equal(bigResult.summary.maxima[0], 84999);
    assert.equal(bigResult.rows.length, 21);
    console.log("CSV >1 MB streams all records and draws bounded sample");
    sandbox.datasetFile = {size: 450, text: async () =>
      "md5hash,fitzpatrick_scale,fitzpatrick_centaur,label,nine_partition_label,three_partition_label,qc,url\n"
      + "hash1,3,3,drug induced pigmentary changes,inflammatory,non-neoplastic,,https://example.org/a\n"
      + "hash2,1,1,photodermatoses,inflammatory,non-neoplastic,,https://example.org/b\n"
      + "hash3,3,3,dermatofibroma,benign dermal,benign,,https://example.org/c\n"
    };
    return run("sampleCsvFile(datasetFile)").then(dataset => {
      assert.equal(dataset.summary.mode, "category_count");
      assert.equal(dataset.summary.column, "fitzpatrick_scale");
      assert.equal(dataset.summary.total, 3);
      assert.equal(dataset.rows[1][0], "3");
      assert.equal(dataset.rows[1][1], "2");
      sandbox.datasetFixture = dataset;
      run("state.csvRows = datasetFixture.rows; state.csvSummary = datasetFixture.summary; state.csvGroups = datasetFixture.groups");
      get("#chart-type").value = "bar";
      run("drawChart()");
      assert.match(get("#caption").textContent, /不是论文模型准确率/);
      assert.equal(get("#chart").children[0].attrs.viewBox.endsWith("340"), true);
      const labels = get("#chart").children[0].children.filter(x => x.tag === "text");
      assert.ok(labels.some(node => node.textContent === "样本数"));
      assert.ok(labels.some(node => node.attrs.transform?.startsWith("rotate(-46")));
      console.log("Fitzpatrick-style image metadata categorized; axes and tick labels rendered");
      sandbox.imageFixture = {size: 500, text: async () =>
        ",ImageID,Vesicle,Papule,Macule,Do not consider this image\n"
        + "0,a.jpg,1,0,1,0\n1,b.jpg,0,1,1,0\n"
        + "2,c.jpg,0,1,0,1\n3,d.jpg,1,1,0,0\n"
      };
      return run("sampleCsvFile(imageFixture)").then(multi => {
        assert.equal(multi.summary.mode, "multilabel_count");
        assert.equal(multi.summary.valid, 3);
        assert.equal(multi.summary.ignored, 1);
        assert.equal(multi.summary.label_count, 3);
        assert.equal(multi.rows.find(row => row[0] === "Papule")[1], "2");
        sandbox.multiFixture = multi;
        run("state.csvRows=multiFixture.rows;state.csvSummary=multiFixture.summary;state.csvGroups=null;drawChart()");
        assert.match(get("#caption").textContent, /一张图像可同时有多个标签/);
        console.log("ImageID binary multi-label CSV supports filtered frequency counts");
      });
    });
  });
}).catch(error => {console.error(error); process.exitCode = 1;});

// Translation failure cards remain accessible but do not dominate the page.
sandbox.fetch = async url => {
  if (url.startsWith("/api/translation-jobs?")) return {
    ok: true, json: async () => ({jobs: [
      {id: "aaaaaaaaaaaaaaaa", status: "completed", first_page: 1,
        last_page: 1, target_language: "zh-CN", processed_units: 3, total_units: 3},
      {id: "bbbbbbbbbbbbbbbb", status: "error", first_page: 1, last_page: 1,
        target_language: "zh-CN", processed_units: 1, total_units: 3,
        error: "模型拒绝"},
    ]})
  };
  if (url === "/api/translation-jobs/bbbbbbbbbbbbbbbb") return {
    ok: true, json: async () => ({deleted: "bbbbbbbbbbbbbbbb"})
  };
  throw new Error(`unexpected translation mock URL ${url}`);
};
run("state.selected='aaaaaaaaaaaaaa'; loadTranslationJobs('aaaaaaaaaaaaaa')")
  .then(() => {
    const group = get("#bilingual-jobs").children.find(node =>
      node.className === "bilingual-failed-history");
    assert.ok(group);
    assert.equal(group.open, undefined);
    assert.match(group.children[0].textContent, /失败历史（1 条/);
    assert.ok(group.children[1].children.some(node =>
      node.tag === "button" && node.textContent === "删除这条记录"));
    console.log("failed translations collapsed with explicit delete control");
  }).catch(error => {console.error(error); process.exitCode = 1;});
