from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .runtime import initialize_runtime

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>BGM Factory Analytics</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#101318;color:#edf2f7}
body{max-width:1100px;margin:0 auto;padding:28px}h1{font-size:1.5rem;margin:0 0 20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:#181d25;border:1px solid #2d3642;border-radius:12px;padding:16px}
.label{color:#9aa7b7;font-size:.82rem}.value{font-size:1.7rem;font-weight:600;margin-top:5px}
h2{font-size:1rem;margin-top:28px}svg{width:100%;height:260px;background:#141921;border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{padding:10px;border-bottom:1px solid #2d3642;text-align:left}
th{color:#9aa7b7}td.num,th.num{text-align:right}.empty{color:#9aa7b7;padding:30px;text-align:center}
@media(max-width:600px){body{padding:16px}.table-wrap{overflow-x:auto}}
</style></head><body>
<h1>BGM Factory / YouTube Analytics</h1>
<div class="stats"><div class="card"><div class="label">総再生数</div><div id="views" class="value">–</div></div>
<div class="card"><div class="label">高評価</div><div id="likes" class="value">–</div></div>
<div class="card"><div class="label">コメント</div><div id="comments" class="value">–</div></div>
<div class="card"><div class="label">登録動画</div><div id="videos" class="value">–</div></div></div>
<h2>日別再生数</h2><svg id="chart" viewBox="0 0 900 260" role="img" aria-label="日別再生数"></svg>
<h2>動画別</h2><div class="table-wrap"><table><thead><tr><th>動画</th><th>種類</th><th>状態</th><th class="num">再生</th><th class="num">高評価</th><th class="num">コメント</th></tr></thead><tbody id="rows"></tbody></table></div>
<script>
const fmt=new Intl.NumberFormat('ja-JP');
function draw(data){
 document.getElementById('views').textContent=fmt.format(data.totals.views||0);
 document.getElementById('likes').textContent=fmt.format(data.totals.likes||0);
 document.getElementById('comments').textContent=fmt.format(data.totals.comments||0);
 document.getElementById('videos').textContent=fmt.format(data.videos.length);
 const rows=document.getElementById('rows'); rows.innerHTML='';
 if(!data.videos.length){rows.innerHTML='<tr><td colspan="6" class="empty">投稿動画はまだありません</td></tr>'}
 for(const v of data.videos){const tr=document.createElement('tr');tr.innerHTML=`<td>${escapeHtml(v.title)}</td><td>${v.kind}</td><td>${v.upload_state}</td><td class="num">${fmt.format(v.views)}</td><td class="num">${fmt.format(v.likes)}</td><td class="num">${fmt.format(v.comments)}</td>`;rows.appendChild(tr)}
 const svg=document.getElementById('chart');svg.innerHTML='';const values=data.daily.map(d=>Number(d.views));
 if(!values.length){svg.innerHTML='<text x="450" y="135" text-anchor="middle" fill="#9aa7b7">Analyticsデータはまだありません</text>';return}
 const max=Math.max(...values,1),left=54,right=875,top=20,bottom=225,step=(right-left)/Math.max(values.length-1,1);
 let points=values.map((v,i)=>`${left+i*step},${bottom-(v/max)*(bottom-top)}`).join(' ');
 svg.innerHTML=`<line x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}" stroke="#465366"/><line x1="${left}" y1="${top}" x2="${left}" y2="${bottom}" stroke="#465366"/><polyline points="${points}" fill="none" stroke="#66a6ff" stroke-width="3"/><text x="${left}" y="248" fill="#9aa7b7">${data.daily[0].metric_date}</text><text x="${right}" y="248" text-anchor="end" fill="#9aa7b7">${data.daily.at(-1).metric_date}</text><text x="45" y="${top+5}" text-anchor="end" fill="#9aa7b7">${fmt.format(max)}</text>`;
}
function escapeHtml(v){const d=document.createElement('div');d.textContent=v;return d.innerHTML}
fetch('/api/analytics').then(r=>r.json()).then(draw).catch(e=>{document.getElementById('chart').innerHTML=`<text x="450" y="135" text-anchor="middle" fill="#ef8585">${escapeHtml(e.message)}</text>`});
</script></body></html>"""


def make_handler(repository):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/analytics":
                payload = json.dumps(repository.dashboard_data(), ensure_ascii=False).encode()
                self._send(payload, "application/json; charset=utf-8")
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _send(self, payload: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    return DashboardHandler


def main() -> None:
    _, config, repository = initialize_runtime()
    server = ThreadingHTTPServer(
        (config.dashboard.host, config.dashboard.port), make_handler(repository)
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
