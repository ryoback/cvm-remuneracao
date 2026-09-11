#!/usr/bin/env python3
"""
Servidor Flask para o dashboard de remuneracao de administradores.

    python servidor.py                    # http://127.0.0.1:8000
    python servidor.py --porta 9000
    python servidor.py --publico          # aceita conexoes da rede local
    python servidor.py --arquivo azzas.html

Serve o HTML gerado por cvm_remuneracao.py e deixa os CSVs do mesmo lote
disponiveis para download em /csv.

O servidor nao regenera nada - so le o que ja esta em disco. Para atualizar os
dados, rode a coleta e recarregue a pagina (o HTML e servido sem cache):

    python cvm_remuneracao.py --carteira carteira.json --anos 2010-2026 \
        --quadro82 nao --dashboard monitor.html --out monitor.csv
"""
from __future__ import annotations

import argparse
import datetime
import html
import os
import threading
import webbrowser

from flask import Flask, Response, abort, send_from_directory

RAIZ = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.config["DASHBOARD"] = "monitor.html"

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--mut:#6b7280;--line:#e3e6ea;--ac:#2563eb}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a20;--ink:#e8eaed;
--mut:#9aa3af;--line:#272b33;--ac:#60a5fa}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,
BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:40px 20px}
h1{font-size:20px;margin:0 0 6px}
p{color:var(--mut)}
a{color:var(--ac)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:6px 16px;margin-top:16px}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{padding:8px 6px;border-bottom:1px solid var(--line);text-align:right}
td:first-child,th:first-child{text-align:left}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
tr:last-child td{border-bottom:none}
code{background:rgba(127,127,127,.12);padding:2px 6px;border-radius:5px;font-size:12px}
"""


def _ip_local():
    """IP desta maquina na rede local. O socket UDP nao chega a mandar pacote:
    serve so para o SO dizer qual interface usaria para sair."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _enderecos(host, porta):
    """URLs uteis para quem for abrir - inclusive o IP a divulgar para a rede."""
    if host == "0.0.0.0":
        ip = _ip_local()
        return [f"http://127.0.0.1:{porta}/"] + ([f"http://{ip}:{porta}/"] if ip else [])
    return [f"http://{host}:{porta}/"]


def _pagina(titulo, corpo):
    return Response(
        f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title><style>{CSS}</style></head>
<body><div class="wrap">{corpo}</div></body></html>""",
        mimetype="text/html")


def _sem_cache(resp):
    """O HTML e regerado por fora; sem isto o navegador serviria a versao velha."""
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


def _csvs():
    """CSVs do mesmo lote do dashboard, do maior para o menor."""
    base = os.path.splitext(app.config["DASHBOARD"])[0]
    fora = []
    for nome in sorted(os.listdir(RAIZ)):
        if not nome.lower().endswith(".csv") or not nome.startswith(base):
            continue
        caminho = os.path.join(RAIZ, nome)
        fora.append((nome, os.path.getsize(caminho),
                     datetime.datetime.fromtimestamp(os.path.getmtime(caminho))))
    return fora


@app.route("/")
def dashboard():
    arquivo = app.config["DASHBOARD"]
    if not os.path.exists(os.path.join(RAIZ, arquivo)):
        return _pagina("Dashboard nao encontrado", f"""
          <h1>Dashboard nao encontrado</h1>
          <p>O arquivo <code>{html.escape(arquivo)}</code> ainda nao existe nesta pasta.
          Gere-o com:</p>
          <div class="card"><p><code>python cvm_remuneracao.py --carteira carteira.json
          --anos 2010-2026 --quadro82 nao --dashboard {html.escape(arquivo)}
          --out monitor.csv</code></p></div>
          <p>Depois recarregue esta pagina.</p>"""), 404
    return _sem_cache(send_from_directory(RAIZ, arquivo))


@app.route("/csv/")
def lista_csv():
    arquivos = _csvs()
    if not arquivos:
        linhas = '<tr><td colspan="3">Nenhum CSV gerado ainda.</td></tr>'
    else:
        linhas = "".join(
            f'<tr><td><a href="/csv/{html.escape(n)}">{html.escape(n)}</a></td>'
            f"<td>{tam / 1024:,.0f} KB</td>"
            f'<td>{mod.strftime("%d/%m/%Y %H:%M")}</td></tr>'
            for n, tam, mod in arquivos)
    return _pagina("CSVs gerados", f"""
      <h1>CSVs gerados</h1>
      <p><a href="/">&larr; voltar ao dashboard</a></p>
      <div class="card"><table>
        <thead><tr><th>Arquivo</th><th>Tamanho</th><th>Gerado em</th></tr></thead>
        <tbody>{linhas}</tbody></table></div>""")


@app.route("/csv/<path:nome>")
def baixar_csv(nome):
    # send_from_directory ja barra path traversal; a checagem extra evita servir
    # qualquer outro arquivo da pasta do projeto
    if not nome.lower().endswith(".csv") or nome not in {n for n, _t, _m in _csvs()}:
        abort(404)
    return send_from_directory(RAIZ, nome, as_attachment=True)


@app.errorhandler(404)
def nao_encontrado(_e):
    return _pagina("Nao encontrado", """
      <h1>404</h1><p>Pagina nao encontrada.
      <a href="/">Ir para o dashboard</a> ou <a href="/csv/">ver os CSVs</a>.</p>"""), 404


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--arquivo", default="monitor.html",
                   help="HTML do dashboard a servir (padrao: monitor.html)")
    p.add_argument("--publico", action="store_true",
                   help="escuta em 0.0.0.0, aceitando conexoes da rede local")
    p.add_argument("--host", default=None, metavar="IP",
                   help="endereco especifico para escutar (ex.: 10.20.0.106); "
                        "por padrao 127.0.0.1, ou 0.0.0.0 com --publico")
    p.add_argument("--abrir", action="store_true", help="abre o navegador ao subir")
    p.add_argument("--debug", action="store_true", help="recarrega ao editar o codigo")
    a = p.parse_args(argv)

    app.config["DASHBOARD"] = a.arquivo
    host = a.host or ("0.0.0.0" if a.publico else "127.0.0.1")
    exposto = not host.startswith("127.")

    # O debugger do Werkzeug expoe um console que executa Python arbitrario em
    # qualquer traceback. Na rede local isso e uma porta aberta para a maquina.
    if a.debug and exposto:
        p.error(f"--debug com host {host} exporia o console do Werkzeug, que executa "
                "codigo arbitrario, para a rede inteira. Use so um dos dois: "
                "--debug em 127.0.0.1, ou o host publico sem --debug.")

    caminho = os.path.join(RAIZ, a.arquivo)
    print(f"\n  dashboard : {a.arquivo}"
          f"{'' if os.path.exists(caminho) else '   (ainda nao gerado)'}")
    print(f"  CSVs      : {len(_csvs())} em /csv/")
    print(f"  escutando : {host}:{a.porta}")
    for url in _enderecos(host, a.porta):
        print(f"  acesse    : {url}")
    if exposto:
        print("  atencao   : visivel para toda a rede local, sem autenticacao")
    print("\n  Ctrl+C para parar.\n")

    if a.abrir and not a.debug:   # com o reloader ligado isto abriria duas abas
        threading.Timer(1.0, webbrowser.open,
                        [f"http://127.0.0.1:{a.porta}/"]).start()
    app.run(host=host, port=a.porta, debug=a.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
