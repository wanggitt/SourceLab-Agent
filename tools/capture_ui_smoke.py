"""Optional local Chrome screenshots, using an isolated empty document library.

Run manually; this never reads or modifies research_agent_mvp/data.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import json
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app

# This subprocess is exclusively an offline UI test. Never send the fixture's
# question or paper excerpt to a real configured API (or incur model charges).
app.os.environ["LLM_CHAT_ENDPOINT"] = ""
app.os.environ["LLM_MODEL"] = ""
app.os.environ["LLM_API_KEY"] = ""


class SmokeHandler(app.Handler):
    """Chrome may close idle keep-alive sockets when its process exits."""

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def log_message(self, *_args):
        pass


def check_interactions(chrome, url, folder):
    """Exercise real-browser DOM/CSS behaviour via local-only Chrome DevTools."""
    try:
        import websocket
    except ImportError:
        print("未安装 websocket-client，跳过自动点击验收；截图仍可使用")
        return
    profile = Path(folder) / "interaction"
    process = subprocess.Popen([
        str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=0", "--remote-allow-origins=http://localhost",
        f"--user-data-dir={profile}", "--window-size=1500,950", url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    connection = None
    try:
        active = profile / "DevToolsActivePort"
        for _ in range(100):
            if active.is_file() or process.poll() is not None:
                break
            time.sleep(.1)
        if not active.is_file():
            raise RuntimeError("Chrome CDP 端口未启动")
        port = active.read_text().splitlines()[0]
        pages = json.load(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json", timeout=3
        ))
        target = next(page for page in pages if page.get("type") == "page"
                      and url in page.get("url", ""))
        connection = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=18, origin="http://localhost"
        )
        serial = 0

        def call(method, params):
            nonlocal serial
            serial += 1
            request_id = serial
            connection.send(json.dumps(
                {"id": request_id, "method": method, "params": params}
            ))
            while True:
                result = json.loads(connection.recv())
                if result.get("id") == request_id:
                    if "error" in result:
                        raise RuntimeError(str(result["error"]))
                    return result.get("result", {})

        def evaluate(expression):
            result = call("Runtime.evaluate", {
                "expression": expression, "returnByValue": True,
                "awaitPromise": True,
            })
            if result.get("exceptionDetails"):
                raise RuntimeError(str(result["exceptionDetails"]))
            return result.get("result", {}).get("value")

        for _ in range(50):
            if evaluate("document.readyState === 'complete' && (document.getElementById('scope')?.options.length || 0) > 1"):
                break
            time.sleep(.1)
        assert evaluate("getComputedStyle(document.querySelector('main')).display") == "grid"
        assert evaluate("document.getElementById('font-larger').click(); document.getElementById('font-level').textContent") == "110%"
        assert evaluate("document.getElementById('toggle-library').click(); document.getElementById('library-panel').hidden") is True
        assert evaluate("document.getElementById('toggle-library').click(); document.getElementById('library-panel').hidden") is False
        assert evaluate("document.getElementById('focus-assistant').click(); getComputedStyle(document.querySelector('.workspace')).display") == "none"
        assert evaluate("document.getElementById('focus-assistant').click(); document.getElementById('focus-assistant').getAttribute('aria-pressed')") == "false"
        assert evaluate("document.getElementById('audit-expand').click(); document.getElementById('audit-window').hidden") is False
        assert evaluate("document.getElementById('audit-close').click(); document.getElementById('audit-window').hidden") is True
        assert evaluate("""(() => {
            state.graphData = {
              nodes: [
                {id:'aaaaaaaaaaaaaa',title:'Source A',filename:'a.pdf',
                 arxiv_id:'',in_degree:0,pagerank:.5},
                {id:'bbbbbbbbbbbbbb',title:'Source B',filename:'b.pdf',
                 arxiv_id:'',in_degree:1,pagerank:.5}
              ],
              edges:[{source:'aaaaaaaaaaaaaa',target:'bbbbbbbbbbbbbb',
                      page_no:1,match_type:'title',excerpt:'PDF source line'}],
              collapsed_versions:false,note:'local fixture'
            };
            renderGraph();
            document.getElementById('graph-expand').click();
            const visible = !document.getElementById('visual-window').hidden
              && !!document.querySelector('#visual-preview svg');
            document.getElementById('visual-larger').click();
            const scaled = document.getElementById('visual-scale').textContent === '125%';
            const svg = document.querySelector('#visual-preview svg');
            const first = svg.querySelector('[data-paper-id="aaaaaaaaaaaaaa"]');
            const interactive = !!first && typeof first.onclick === 'function';
            if (interactive) first.dispatchEvent(new MouseEvent('click',{bubbles:true}));
            else document.getElementById('visual-close').click();
            return visible && scaled && interactive
              && document.getElementById('visual-window').hidden;
        })()""") is True
        assert evaluate("""(() => {
            document.getElementById('idea').value = 'Source A experimental proposal';
            document.getElementById('diagram-btn').click();
            document.getElementById('diagram-expand').click();
            const svg = document.querySelector('#visual-preview svg');
            const visible = !!svg && !document.getElementById('visual-window').hidden
              && svg.querySelectorAll('rect').length >= 2;
            document.getElementById('visual-close').click();
            return visible && document.getElementById('visual-window').hidden;
        })()""") is True
        assert evaluate("""(async () => {
            state.selected = 'aaaaaaaaaaaaaa';
            document.getElementById('structure-panel').hidden = false;
            document.getElementById('structure-panel').open = true;
            await document.getElementById('load-structure').onclick();
            return !!document.querySelector('.structure-crop-row');
        })()""") is True
        evaluate("document.querySelector('.structure-crop-row').scrollIntoView()")
        for _ in range(40):
            if evaluate("""(() => {
                const image = document.querySelector('.structure-crop-image');
                return !!image && image.complete && image.naturalWidth > 80;
            })()"""):
                break
            time.sleep(.1)
        assert evaluate("""(() => {
            const image = document.querySelector('.structure-crop-image');
            return !!image && image.complete && image.naturalWidth > 80;
        })()""") is True, evaluate("""JSON.stringify({
            text: document.querySelector('.structure-crop-row')?.innerText.slice(0, 400),
            image: document.querySelector('.structure-crop-image')?.getAttribute('src'),
            complete: document.querySelector('.structure-crop-image')?.complete,
            width: document.querySelector('.structure-crop-image')?.naturalWidth
        })""")
        assert evaluate("""(async () => {
            const id = 'aaaaaaaaaaaaaa';
            document.getElementById('scope').value = id;
            document.getElementById('question').value = 'Transformer GPU';
            await document.getElementById('ask-form').onsubmit({preventDefault(){}});
            return document.getElementById('answer').textContent;
        })()""").find("已找到以下原文片段") >= 0
        assert evaluate("""(async () => {
            document.getElementById('idea').value = 'Transformer attention';
            const checkbox = document.querySelector('#writing-choices input');
            checkbox.checked = true;
            await document.getElementById('outline-form').onsubmit({preventDefault(){}});
            return document.getElementById('outline').textContent;
        })()""").find("Related Work 候选") >= 0
        evaluate("window.scrollTo(0, 0)")
        before = evaluate("parseInt(document.documentElement.style.getPropertyValue('--left-width'))")
        rect = json.loads(evaluate("""JSON.stringify((() => {
            const r = document.getElementById('library-resizer').getBoundingClientRect();
            return {x:r.x+r.width/2,y:r.y+Math.min(r.height/2,180)};
        })())"""))
        for kind, shift in (("mousePressed", 0), ("mouseMoved", 55),
                            ("mouseReleased", 55)):
            call("Input.dispatchMouseEvent", {
                "type": kind, "x": rect["x"] + shift, "y": rect["y"],
                "button": "left", "buttons": 1 if kind != "mouseReleased" else 0,
                "clickCount": 1 if kind != "mouseMoved" else 0,
            })
        assert evaluate("parseInt(document.documentElement.style.getPropertyValue('--left-width'))") > before
        call("Emulation.setDeviceMetricsOverride", {
            "width": 680, "height": 950, "deviceScaleFactor": 1, "mobile": False,
        })
        for _ in range(25):
            if evaluate("document.getElementById('page-layout').classList.contains('stacked-layout')"):
                break
            time.sleep(.05)
        assert evaluate("document.getElementById('page-layout').classList.contains('stacked-layout')") is True
        assert evaluate("getComputedStyle(document.getElementById('library-resizer')).display") == "none"
        print("Chrome interactions passed: page zoom, collapse, drag, audit, graph/diagram enlarge+zoom+close, original-PDF figure crop, narrow layout")
    finally:
        if connection:
            connection.close()
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    chrome = next((path for path in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ) if path.is_file()), None)
    if chrome is None:
        raise SystemExit("未检测到 Chrome 或 Edge，跳过浏览器截图")
    original = (app.DATA, app.FILES, app.DB_FILE)
    server = None
    with tempfile.TemporaryDirectory(prefix="sourcelab-ui-") as folder:
        app.DATA = Path(folder)
        app.FILES = app.DATA / "uploads"
        app.DB_FILE = app.DATA / "test.sqlite3"
        try:
            app.init_db()
            with app.db() as connection:
                paper_id = "a" * 14
                sample = ROOT.parent / "pdf" / "1706.03762v7.pdf"
                connection.execute(
                    """INSERT INTO papers(id,filename,filepath,title,arxiv_id,version,
                       status,pages,chunks,created_at)
                       VALUES(?,?,?,?,?,?,'ready',15,2,?)""",
                    (paper_id, "sample.pdf", str(sample), "Attention Is All You Need",
                     "1706.03762", 7, app.now()),
                )
                source = "Transformer attention uses GPU acceleration in training."
                row = connection.execute(
                    "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,?,?)",
                    (paper_id, 1, source),
                )
                connection.execute(
                    "INSERT INTO chunks_fts(rowid,paper_id,page_no,content) VALUES(?,?,?,?)",
                    (row.lastrowid, paper_id, 1, source),
                )
                caption = "Figure 2: Multi-Head Attention diagram in the source PDF."
                connection.execute(
                    "INSERT INTO chunks(paper_id,page_no,content) VALUES(?,?,?)",
                    (paper_id, 4, caption),
                )
            server = ThreadingHTTPServer(("127.0.0.1", 0), SmokeHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{server.server_port}/"
            for label, width, height in (
                ("desktop", 1500, 950), ("narrow", 680, 950)
            ):
                screenshot = ROOT / "tests" / f"ui_qa_{label}.png"
                result = subprocess.run([
                    str(chrome), "--headless=new", "--disable-gpu",
                    "--no-first-run", "--no-default-browser-check",
                    f"--user-data-dir={Path(folder) / label}",
                    f"--window-size={width},{height}",
                    "--virtual-time-budget=3000",
                    f"--screenshot={screenshot}", url,
                ], capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=45)
                if result.returncode or not screenshot.is_file() or screenshot.stat().st_size < 1000:
                    raise RuntimeError(
                        f"{label} 浏览器截图失败（退出码 {result.returncode}）："
                        + (result.stderr or "")[-800:]
                    )
                print(f"{label}: {screenshot} ({screenshot.stat().st_size} bytes)")
            check_interactions(chrome, url, folder)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            app.DATA, app.FILES, app.DB_FILE = original


if __name__ == "__main__":
    main()
