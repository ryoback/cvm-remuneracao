#!/usr/bin/env python3
"""
Dados de mercado e de resultado para dimensionar a remuneracao dos administradores:
receita, acoes ex-tesouraria, preco e market cap.

Fontes:
  DFP  dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_AAAA.zip
       ...composicao_capital_AAAA.csv -> acoes integralizadas e em tesouraria (ON/PN)
       ...DRE_con_AAAA.csv            -> receita liquida, conta 3.01 (cai para _ind)
  Yahoo Finance (query1.finance.yahoo.com/v8/finance/chart) -> precos + splits

Por que nao o FRE para acoes: o quadro de posicao acionaria do FRE traz "Acoes
Tesouraria", mas com a data-base do proprio formulario (tipicamente 30/04 do ano
seguinte) e repetido em varios recortes. A composicao de capital da DFP vem casada
com o encerramento do exercicio, que e a data certa para confrontar com a
remuneracao daquele exercicio.

Cuidado com preco historico: a Yahoo devolve `close` ajustado por desdobramento.
Multiplicar esse preco pela quantidade de acoes da epoca subestima o market cap
pelo fator acumulado de splits. Aqui o preco e desajustado com os eventos de split
antes de virar market cap.
"""
from __future__ import annotations

import datetime
import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from cvm_remuneracao import baixar, linhas_do_zip, norm, num, so_digitos, indice_fca

URL_DFP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip"
URL_YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{tk}.SA"
             "?range=25y&interval=1mo&events=split")
CONTA_RECEITA = "3.01"
ESCALA = {"MIL": 1000.0, "UNIDADE": 1.0, "MILHAO": 1e6, "MILHAR": 1000.0}


def _escala(v):
    return ESCALA.get((v or "").strip().upper(), 1.0)


def _ano(data):
    return int(str(data)[:4]) if data else None


# ------------------------------------------------------------------------ DFP
def coletar_fre_capital(anos, cnpjs, nomes, cache, log=print):
    """Acoes pelo FRE: {(cnpj, ano): {total, on, pn, tesouraria}}.

    Serve para dois fins: cobrir os exercicios anteriores a 2020 (a DFP so passou a
    publicar composicao de capital naquele ano) e aferir a escala da DFP, que ora
    vem em unidades, ora em milhares. O FRE sempre vem em unidades.
    """
    def bate(r):
        if so_digitos(r.get("CNPJ_Companhia", "")) in cnpjs:
            return True
        return any(t in norm(r.get("Nome_Companhia", "")) for t in nomes)

    fora, vers = {}, {}
    for ano in anos:
        zp = os.path.join(cache, f"fre_{ano}.zip")
        if not os.path.exists(zp):
            continue
        for r in linhas_do_zip(zp, "capital_social"):
            if r.get("Tipo_Capital") != "Capital Integralizado" or not bate(r):
                continue
            cnpj, ex = so_digitos(r["CNPJ_Companhia"]), _ano(r["Data_Referencia"])
            v = int(num(r.get("Versao")))
            if vers.get(("cap", cnpj, ex), -1) > v:
                continue
            vers[("cap", cnpj, ex)] = v
            fora.setdefault((cnpj, ex), {}).update({
                "total": num(r["Quantidade_Total_Acoes"]),
                "on": num(r["Quantidade_Acoes_Ordinarias"]),
                "pn": num(r["Quantidade_Acoes_Preferenciais"]),
            })
        # tesouraria: linha "Acoes Tesouraria" do quadro de posicao acionaria. O
        # quadro repete varios recortes por data-base; fica a maior quantidade.
        for r in linhas_do_zip(zp, "posicao_acionaria"):
            if "tesouraria" not in norm(r.get("Acionista", "")) or not bate(r):
                continue
            cnpj, ex = so_digitos(r["CNPJ_Companhia"]), _ano(r["Data_Referencia"])
            v = int(num(r.get("Versao")))
            if vers.get(("tes", cnpj, ex), -1) > v:
                continue
            if vers.get(("tes", cnpj, ex), -1) < v:
                vers[("tes", cnpj, ex)] = v
                fora.setdefault((cnpj, ex), {})["tesouraria"] = 0.0
            d = fora.setdefault((cnpj, ex), {})
            d["tesouraria"] = max(d.get("tesouraria", 0.0),
                                  num(r.get("Quantidade_Total_Acoes_Circulacao")))
    return fora


def conciliar_acoes(dados_dfp, cap_fre, log=print):
    """Resolve escala da DFP (unidades x milhares) e completa os anos sem DFP.

    Escreve em cada slot: acoes_integralizadas / acoes_tesouraria / acoes_ex_tesouraria
    ja em unidades, mais 'origem_acoes' e eventuais alertas.
    """
    chaves = set(dados_dfp) | set(cap_fre)
    for k in chaves:
        d = dados_dfp.setdefault(k, {})
        fre = cap_fre.get(k) or {}
        integr, tes = d.get("acoes_integralizadas"), d.get("acoes_tesouraria")
        tot_fre = fre.get("total") or 0.0
        alertas = []

        escala = 1.0
        if integr and tot_fre:
            r = tot_fre / integr
            if 300 < r < 3000:
                escala = 1000.0      # DFP veio em milhares
            elif not (0.5 < r < 2):
                alertas.append(f"acoes DFP e FRE divergem ({integr:,.0f} x {tot_fre:,.0f})")

        if integr:
            for campo in ("acoes_integralizadas", "acoes_tesouraria",
                          "acoes_on", "acoes_pn",
                          "acoes_on_tesouraria", "acoes_pn_tesouraria"):
                if d.get(campo):
                    d[campo] *= escala
            d["acoes_ex_tesouraria"] = d["acoes_integralizadas"] - d.get("acoes_tesouraria", 0.0)
            d["origem_acoes"] = ("DFP" if escala == 1 else "DFP (corrigido de milhares)")
        elif tot_fre:
            # sem DFP: cai para o FRE, que cobre os exercicios antigos
            d["acoes_integralizadas"] = tot_fre
            d["acoes_on"], d["acoes_pn"] = fre.get("on", 0.0), fre.get("pn", 0.0)
            d["acoes_tesouraria"] = fre.get("tesouraria", 0.0)
            d["acoes_on_tesouraria"] = d["acoes_pn_tesouraria"] = 0.0
            d["acoes_ex_tesouraria"] = tot_fre - d["acoes_tesouraria"]
            d["origem_acoes"] = "FRE"
            if "tesouraria" not in fre:
                alertas.append("tesouraria nao informada no FRE; tratada como zero")
        if escala != 1.0:
            alertas.append("quantidade de acoes da DFP estava em milhares")
        if alertas:
            d["alertas_acoes"] = "; ".join(alertas)
    return dados_dfp


def coletar_dfp(anos, cnpjs, nomes, cache, log=print):
    """{(cnpj_digitos, exercicio): {receita, acoes_*}} a partir das DFPs."""
    pares = [(URL_DFP.format(ano=a), os.path.join(cache, f"dfp_{a}.zip")) for a in anos]
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda p: baixar(p[0], p[1], log), pares))

    def bate(r):
        if so_digitos(r.get("CNPJ_CIA", "")) in cnpjs:
            return True
        n = norm(r.get("DENOM_CIA", ""))
        return any(t in n for t in nomes)

    dados, versoes = {}, {}

    def slot(cnpj, ano):
        return dados.setdefault((cnpj, ano), {})

    for ano in anos:
        zp = os.path.join(cache, f"dfp_{ano}.zip")
        if not os.path.exists(zp):
            continue

        # --- composicao de capital: acoes integralizadas e em tesouraria
        for r in linhas_do_zip(zp, "composicao_capital"):
            if not bate(r):
                continue
            cnpj, ex = so_digitos(r["CNPJ_CIA"]), _ano(r["DT_REFER"])
            v = int(num(r.get("VERSAO")))
            if versoes.get(("cap", cnpj, ex), -1) > v:
                continue          # ja temos versao mais nova deste exercicio
            versoes[("cap", cnpj, ex)] = v
            integr = num(r.get("QT_ACAO_TOTAL_CAP_INTEGR"))
            tes = num(r.get("QT_ACAO_TOTAL_TESOURO"))
            d = slot(cnpj, ex)
            d.update({
                "empresa": r.get("DENOM_CIA", "").strip(),
                "acoes_on": num(r.get("QT_ACAO_ORDIN_CAP_INTEGR")),
                "acoes_pn": num(r.get("QT_ACAO_PREF_CAP_INTEGR")),
                "acoes_integralizadas": integr,
                "acoes_tesouraria": tes,
                "acoes_on_tesouraria": num(r.get("QT_ACAO_ORDIN_TESOURO")),
                "acoes_pn_tesouraria": num(r.get("QT_ACAO_PREF_TESOURO")),
                "acoes_ex_tesouraria": integr - tes,
                "dfp_capital": ano,
            })

        # --- receita: consolidada quando existe, senao individual
        for sufixo, marca in (("con", "dre_con"), ("ind", "dre_ind")):
            for r in linhas_do_zip(zp, marca):
                if r.get("CD_CONTA") != CONTA_RECEITA or not bate(r):
                    continue
                ordem = norm(r.get("ORDEM_EXERC", ""))
                ex = _ano(r.get("DT_FIM_EXERC"))
                cnpj = so_digitos(r["CNPJ_CIA"])
                v = int(num(r.get("VERSAO")))
                # ULTIMO e o exercicio da propria DFP; PENULTIMO cobre o ano anterior
                # de graca, mas so vale se ninguem melhor preencheu aquele ano.
                peso = (2 if ordem.startswith("ultimo") else 1,
                        2 if sufixo == "con" else 1, v)
                if versoes.get(("rec", cnpj, ex), (0, 0, -1)) >= peso:
                    continue
                versoes[("rec", cnpj, ex)] = peso
                d = slot(cnpj, ex)
                d["receita"] = num(r["VL_CONTA"]) * _escala(r.get("ESCALA_MOEDA"))
                d["receita_origem"] = f"DRE_{sufixo} {ano}"
                d.setdefault("empresa", r.get("DENOM_CIA", "").strip())
    return dados


# ---------------------------------------------------------------------- precos
def _http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def precos_yahoo(ticker, log=print):
    """{'atual': preco, 'moeda': .., 'por_ano': {ano: preco nominal no fim do ano}}.

    Devolve None se o papel nao existir na Yahoo. Os precos por ano sao
    DESAJUSTADOS de splits, para casar com a quantidade de acoes daquele exercicio.
    """
    try:
        d = _http_json(URL_YAHOO.format(tk=ticker))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        log(f"  preco {ticker}: falha ({type(e).__name__})")
        return None
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        return None
    res = res[0]
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []

    splits = sorted(
        ((int(s["date"]), float(s["numerator"]) / float(s["denominator"]))
         for s in ((res.get("events") or {}).get("splits") or {}).values()),
        key=lambda x: x[0])

    def fator_apos(t):
        """Produto dos splits ocorridos DEPOIS de t (para desajustar o preco)."""
        f = 1.0
        for quando, r in splits:
            if quando > t:
                f *= r
        return f

    por_ano = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        ano = datetime.date.fromtimestamp(t).year
        # ultima observacao do ano manda
        if ano not in por_ano or t >= por_ano[ano][0]:
            por_ano[ano] = (t, c * fator_apos(t))
    return {
        "ticker": ticker,
        "atual": meta.get("regularMarketPrice"),
        "moeda": meta.get("currency"),
        "por_ano": {a: p for a, (_t, p) in por_ano.items()},
        "splits": len(splits),
    }


def _papel_valido(tk):
    return (len(tk) >= 5 and tk[:4].isalpha() and tk[4:].isdigit()
            and tk[4:] in ("3", "4", "5", "6", "7", "8", "11"))


def tickers_por_cnpj(cnpjs, cache, log=print, extras=None):
    """{cnpj_digitos: [tickers]} pelo FCA, so papeis a vista (ON/PN/UNIT).

    `extras` ({cnpj: [tickers]}, vindo da carteira) e somado ao que o FCA conhece.
    Faz falta em dois casos reais: o FCA nao lista as ON/PN da Klabin (so a unit
    KLBN11) e traz o codigo do BTG corrompido como "000000".
    """
    fora = {}
    for r in indice_fca(cache, log):
        tk = r["ticker"]
        if not _papel_valido(tk):
            continue
        c = so_digitos(r["cnpj"])
        if c in cnpjs and tk not in fora.setdefault(c, []):
            fora[c].append(tk)
    for c, tks in (extras or {}).items():
        if c not in cnpjs:
            continue
        for tk in tks:
            tk = (tk or "").upper()
            if _papel_valido(tk) and tk not in fora.setdefault(c, []):
                fora[c].append(tk)
    return fora


def _classe(tk):
    return {"3": "ON", "11": "UNIT"}.get(tk[4:], "PN")


def cotacoes(mapa_tickers, log=print):
    """{cnpj: {'ON': dados, 'PN': dados, 'UNIT': dados}}."""
    todos = sorted({tk for tks in mapa_tickers.values() for tk in tks})
    if not todos:
        return {}
    log(f"buscando precos de {len(todos)} papel(is): {', '.join(todos)}")
    with ThreadPoolExecutor(max_workers=8) as ex:
        precos = dict(zip(todos, ex.map(lambda t: precos_yahoo(t, log), todos)))

    fora = {}
    for cnpj, tks in mapa_tickers.items():
        porclasse = {}
        for tk in tks:
            p = precos.get(tk)
            if not p or not p.get("por_ano"):
                continue
            cl = _classe(tk)
            # se ha mais de um papel da mesma classe, fica o de historico mais longo
            if cl not in porclasse or len(p["por_ano"]) > len(porclasse[cl]["por_ano"]):
                porclasse[cl] = p
        if porclasse:
            fora[cnpj] = porclasse
    return fora


# ------------------------------------------------------------------ market cap
def market_cap(fin, precos_cia, ano, usar_atual=False):
    """(valor, alertas, precos_usados). Soma ON x preco_ON + PN x preco_PN, ex-tesouraria.

    precos_usados = {classe: preco} - as classes de uma mesma companhia negociam a
    precos bem diferentes (ALPA3 a 10,62 e ALPA4 a 14,42), entao mostrar o preco de
    uma so classe induz a erro; quem chama monta a media ponderada a partir daqui.
    """
    if not precos_cia:
        return None, "sem cotacao", {}
    on = fin.get("acoes_on", 0.0) - fin.get("acoes_on_tesouraria", 0.0)
    pn = fin.get("acoes_pn", 0.0) - fin.get("acoes_pn_tesouraria", 0.0)
    ext = fin.get("acoes_ex_tesouraria", 0.0)
    if ext <= 0:
        return None, "sem quantidade de acoes", {}

    def preco(cl):
        p = precos_cia.get(cl)
        if not p:
            return None
        return p.get("atual") if usar_atual else p.get("por_ano", {}).get(ano)

    alertas = []
    p_on, p_pn, p_unit = preco("ON"), preco("PN"), preco("UNIT")

    usados = {}
    if pn > 0 and p_pn and p_on:                      # duas classes, dois precos
        valor = on * p_on + pn * p_pn
        usados = {"ON": p_on, "PN": p_pn}
    elif pn > 0 and p_unit and not (p_on and p_pn):
        # so ha UNIT negociada: aproxima tratando o capital todo pelo preco da unit
        return None, "capital em units; market cap nao calculado", {}
    elif pn > 0 and (p_on or p_pn):
        p = p_on or p_pn
        valor = ext * p
        usados = {"ON" if p_on else "PN": p}
        alertas.append("empresa tem ON e PN, mas so um preco disponivel: "
                       "market cap aproximado")
    elif p_on or p_pn:
        valor = ext * (p_on or p_pn)
        usados = {"ON" if p_on else "PN": p_on or p_pn}
    else:
        return None, "sem cotacao no exercicio", {}
    return valor, "; ".join(alertas), usados


def montar_mercado(remuneracao_por_exerc, dados_dfp, precos, log=print):
    """Junta remuneracao (total da empresa por exercicio) com receita e market cap.

    remuneracao_por_exerc: {(cnpj_digitos, exercicio): {empresa, total, ...}}
    """
    linhas = []
    for (cnpj, ex), rem in sorted(remuneracao_por_exerc.items(),
                                  key=lambda kv: (kv[1]["empresa"], kv[0][1])):
        fin = dados_dfp.get((cnpj, ex), {})
        pc = precos.get(cnpj) or {}
        mc, alerta_mc, precos_usados = (market_cap(fin, pc, ex) if fin
                                        else (None, "sem DFP", {}))
        ext = fin.get("acoes_ex_tesouraria") or 0
        receita = fin.get("receita")
        total = rem["total"]

        d = {
            "cnpj": rem.get("cnpj_fmt", cnpj),
            "empresa": rem["empresa"],
            "exercicio": ex,
            "remuneracao_total": total,
            "remuneracao_diretoria": rem.get("diretoria"),
            "remuneracao_conselho_adm": rem.get("conselho_adm"),
            "remuneracao_conselho_fiscal": rem.get("conselho_fiscal"),
            "receita": receita,
            "acoes_integralizadas": fin.get("acoes_integralizadas"),
            "acoes_tesouraria": fin.get("acoes_tesouraria"),
            "acoes_ex_tesouraria": fin.get("acoes_ex_tesouraria"),
            "origem_acoes": fin.get("origem_acoes"),
            "tickers": "/".join(f"{c}:{p['ticker']}" for c, p in sorted(pc.items())),
            # media ponderada pelas quantidades de cada classe, que e o preco que
            # de fato produz o market cap; o detalhe por classe fica ao lado
            "preco_medio_ponderado": (mc / ext) if (mc and ext) else None,
            "precos_por_classe": " / ".join(
                f"{pc[c]['ticker']} {v:.2f}" for c, v in sorted(precos_usados.items())
                if pc.get(c)),
            "market_cap": mc,
            "rem_sobre_receita_pct": (100 * total / receita) if receita else None,
            "rem_sobre_market_cap_pct": (100 * total / mc) if mc else None,
            "previsao": rem.get("previsao", False),
            "parcela_previsao": rem.get("parcela_previsao", 0.0),
            "receita_origem": fin.get("receita_origem"),
            "alertas_mercado": "; ".join(
                x for x in (alerta_mc, fin.get("alertas_acoes")) if x),
        }
        linhas.append(d)
    return linhas
