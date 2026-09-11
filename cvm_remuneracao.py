#!/usr/bin/env python3
"""
Historico de remuneracao (maxima / media / minima por orgao) do Formulario de
Referencia de qualquer companhia aberta brasileira, direto dos dados abertos da CVM.

Fontes (nada de scraping - sao CSVs oficiais):
  FRE  dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_AAAA.zip
       ...remuneracao_maxima_minima_media_AAAA.csv   -> item 8.16 (ex-13.11)
       ...remuneracao_total_orgao_AAAA.csv           -> item 8.2  (ex-13.2), com a
            abertura por verba: salario, beneficios, comites, bonus, participacao em
            resultados/reunioes, comissoes, pos-emprego, cessacao e baseada em acoes
  FCA  dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_AAAA.zip
       ...valor_mobiliario_AAAA.csv                  -> ticker B3 -> CNPJ

Uso:
    python cvm_remuneracao.py LREN3 VIVA3 CEAB3
    python cvm_remuneracao.py renner vivara "c&a modas"      # por nome
    python cvm_remuneracao.py 92.754.738/0001-62             # por CNPJ
    python cvm_remuneracao.py LREN3 --anos 2015-2026 --out renner.csv
    python cvm_remuneracao.py --buscar loja                  # descobre ticker/CNPJ

So stdlib. Os zips ficam em cache (--cache, padrao ./.cvm_cache); a partir da
2a execucao roda offline para os anos ja baixados.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import io
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

URL_FRE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FRE/DADOS/fre_cia_aberta_{ano}.zip"
URL_FCA = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip"
ANO_MIN = 2010
ANO_MAX = datetime.date.today().year + 1

ORDEM_ORGAO = {
    "diretoria estatutaria": 1,
    "conselho de administracao": 2,
    "conselho fiscal": 3,
}
RE_TICKER = re.compile(r"^[A-Za-z]{4}\d{1,2}$")
RE_CNPJ = re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$")

# Quadro 8.2 (ex-13.2) - "Remuneracao total do Exercicio Social", por orgao e por
# natureza da verba. (rotulo no formulario, campo de saida, coluna do CSV, grupo)
CAMPOS_82 = [
    ("Salario ou pro-labore",           "salario",                 "Salario",                      "fixa"),
    ("Beneficios direto e indireto",    "beneficios",              "Beneficios_Diretos_Indiretos", "fixa"),
    ("Participacoes em comites",        "participacoes_comites",   "Participacoes_Comites",        "fixa"),
    ("Outros (fixa)",                   "outros_fixos",            "Outros_Valores_Fixos",         "fixa"),
    ("Bonus",                           "bonus",                   "Bonus",                        "variavel"),
    ("Participacao de resultados",      "participacao_resultados", "Participacao_Resultados",      "variavel"),
    ("Participacao em reunioes",        "participacao_reunioes",   "Participacao_Reunioes",        "variavel"),
    ("Comissoes",                       "comissoes",               "Comissoes",                    "variavel"),
    ("Outros (variavel)",               "outros_variaveis",        "Outros_Valores_Variaveis",     "variavel"),
    ("Pos-emprego",                     "pos_emprego",             "Pos_emprego",                  "outros"),
    ("Cessacao do cargo",               "cessacao_cargo",          "Cessacao_Cargo",               "outros"),
    ("Baseada em acoes (incl. opcoes)", "baseada_acoes",           "Baseada_Acoes",                "outros"),
]
GRUPOS_82 = [("fixa", "Remuneracao fixa anual"), ("variavel", "Remuneracao variavel"),
             ("outros", "Outras verbas")]


# --------------------------------------------------------------------------- util
def norm(s):
    """minusculo, sem acento, espacos colapsados - para comparar nomes."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def so_digitos(s):
    return re.sub(r"\D", "", s or "")


def num(v):
    """CSV da CVM usa ponto decimal, mas ha campos vazios e, raramente, virgula."""
    if v is None:
        return 0.0
    v = str(v).strip()
    if not v:
        return 0.0
    if "," in v and "." not in v:
        v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return 0.0


def brl(v):
    if v is None:
        return "-"
    return f"{v:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


# ----------------------------------------------------------------------- download
def baixar(url, destino, log=print):
    """Baixa se ainda nao estiver em cache. Devolve o caminho, ou None se 404."""
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        return destino
    req = urllib.request.Request(url, headers={"User-Agent": "cvm-remuneracao/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(destino, "wb") as fh:
            fh.write(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    log(f"  baixado {os.path.basename(destino)} ({os.path.getsize(destino) / 1e6:.1f} MB)")
    return destino


def baixar_muitos(pares, log=print):
    """pares = [(url, destino)]. Devolve {destino: caminho ou None}."""
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(baixar, u, d, log): d for u, d in pares}
        return {d: f.result() for f, d in futs.items()}


def linhas_do_zip(zip_path, marcador):
    """Itera dicts de todo CSV do zip cujo nome contenha `marcador`."""
    if not zip_path or not os.path.exists(zip_path):
        return
    with zipfile.ZipFile(zip_path) as z:
        for nome in z.namelist():
            baixo = nome.lower()
            if marcador not in baixo or not baixo.endswith(".csv"):
                continue
            with z.open(nome) as raw:
                texto = io.TextIOWrapper(raw, encoding="latin-1", newline="")
                for linha in csv.DictReader(texto, delimiter=";"):
                    yield linha


# ---------------------------------------------------------------- alvos (empresas)
def indice_fca(cache, log=print):
    """[{ticker, cnpj, nome}] a partir do FCA mais recente disponivel."""
    fora = []
    for ano in range(ANO_MAX, ANO_MIN - 1, -1):
        zp = baixar(URL_FCA.format(ano=ano), os.path.join(cache, f"fca_{ano}.zip"), log)
        if not zp:
            continue
        for r in linhas_do_zip(zp, "valor_mobiliario"):
            cod = (r.get("Codigo_Negociacao") or "").strip().upper()
            if cod:
                fora.append({"ticker": cod, "cnpj": r["CNPJ_Companhia"],
                             "nome": (r.get("Nome_Empresarial") or "").strip()})
        if fora:
            break
    return fora


def resolver_alvos(termos, cache, log=print):
    """Devolve (cnpjs_alvo, termos_de_nome). Ticker vira CNPJ via FCA."""
    cnpjs, nomes, tickers = set(), [], []
    for t in termos:
        t = t.strip()
        if RE_CNPJ.match(t):
            cnpjs.add(so_digitos(t))
        elif RE_TICKER.match(t):
            tickers.append(t.upper())
        else:
            nomes.append(norm(t))

    if tickers:
        log(f"resolvendo ticker(s) {', '.join(tickers)} pelo FCA...")
        por_ticker = {}
        for r in indice_fca(cache, log):
            por_ticker.setdefault(r["ticker"], r)
        for tk in tickers:
            achado = por_ticker.get(tk)
            if achado:
                cnpjs.add(so_digitos(achado["cnpj"]))
                log(f"  {tk} -> {achado['nome']} ({achado['cnpj']})")
            else:
                log(f"  {tk} -> nao encontrado no FCA; tratando como nome")
                nomes.append(norm(tk))
    return cnpjs, nomes


def carregar_carteira(caminho, cache, log=print):
    """Le a carteira por setor. Devolve (cnpjs, nomes, meta, fora_cvm).

    meta = {cnpj_digitos: {'nome','setor','ticker'}}. O ticker informado prevalece
    sobre o que o FCA conhece, porque papel de companhia fechada some do FCA atual
    mas continua servindo para buscar preco historico.
    """
    import json
    with open(caminho, encoding="utf-8") as fh:
        bruto = json.load(fh)

    setores = {k: v for k, v in bruto.items() if not k.startswith("_")}
    meta, cnpjs, nomes, fora_cvm, por_ticker = {}, set(), [], [], {}

    pendentes = [(setor, it) for setor, itens in setores.items() for it in itens]
    precisa_fca = any(it.get("ticker") and not it.get("cnpj")
                      for _s, it in pendentes)
    if precisa_fca:
        for r in indice_fca(cache, log):
            por_ticker.setdefault(r["ticker"], r)

    for setor, it in pendentes:
        nome, tk = it["nome"], (it.get("ticker") or "").upper()
        if (it.get("mercado") or "").upper() == "US":
            fora_cvm.append((setor, nome))
            continue
        cnpj = so_digitos(it.get("cnpj", ""))
        if not cnpj and tk:
            achado = por_ticker.get(tk)
            if achado:
                cnpj = so_digitos(achado["cnpj"])
        if not cnpj:
            log(f"  ! {nome} ({tk or 'sem ticker'}): nao resolvido, sera ignorado")
            continue
        cnpjs.add(cnpj)
        meta[cnpj] = {"nome": nome, "setor": setor, "ticker": tk,
                      "tickers": [t.upper() for t in it.get("tickers", [])],
                      "obs": it.get("obs", "")}
    log(f"carteira: {len(meta)} companhias na CVM, "
        f"{len(fora_cvm)} listadas fora do Brasil (ignoradas)")
    for setor, nome in fora_cvm:
        log(f"  - {nome} ({setor}): sem registro na CVM")
    return cnpjs, nomes, meta, fora_cvm


def confrontar_previsao(por_fre, campos):
    """Cruza o que o FRE PREVIU para um exercicio com o que depois foi REALIZADO.

    O FRE do ano E descreve E como estimativa; os FREs seguintes redescrevem E ja
    realizado. Vale tanto para o quadro 8.2 (total por orgao) quanto para o 8.16
    (maxima/media/minima individual), por isso `campos` diz quais valores comparar:
    {rotulo_de_saida: campo_de_entrada}.

    Previsao = PRIMEIRA versao do FRE do proprio exercicio (o orcamento original,
    antes das revisoes que a companhia faz ao longo do ano).
    Realizado = documento mais recente entre os posteriores ao exercicio.
    """
    prev, real = {}, {}
    for d in por_fre:
        k = (d["cnpj"], d["empresa"], d["orgao"], d["exercicio"])
        marca = (d["data_referencia"], d["versao"])
        alvo = prev if d["previsao"] else real
        atual = alvo.get(k)
        if atual is None or marca > (atual["data_referencia"], atual["versao"]):
            alvo[k] = d

    linhas = []
    for k in sorted(set(prev) | set(real),
                    key=lambda k: (k[1], k[3], ORDEM_ORGAO.get(norm(k[2]), 9))):
        cnpj, empresa, orgao, ex = k
        p, r = prev.get(k), real.get(k)
        linha = {"cnpj": cnpj, "empresa": empresa, "orgao": orgao, "exercicio": ex}
        for rotulo, campo in campos.items():
            vp = p[campo] if p else None
            vr = r[campo] if r else None
            dv = (vr - vp) if (vp is not None and vr is not None) else None
            linha[f"previsto_{rotulo}"] = vp
            linha[f"realizado_{rotulo}"] = vr
            linha[f"desvio_{rotulo}"] = dv
            linha[f"desvio_{rotulo}_pct"] = (100 * dv / vp) if (dv is not None and vp) else None
        linha.update({
            "fre_previsao": p["fre"] if p else None,
            "fre_realizado": r["fre"] if r else None,
            "situacao": ("realizado" if r is not None and p is not None else
                         "so previsao" if p is not None else "so realizado"),
        })
        linhas.append(linha)
    return linhas


def previsto_x_realizado(q82_por_fre):
    """Confronto do quadro 8.2: total por orgao e numero de membros.

    Com os dois lados da conta da para comparar tambem o custo por membro previsto
    contra o efetivamente pago - o quadro 8.16 nao ajuda aqui porque a CVM so pede
    maxima/media/minima de exercicios ja encerrados, nunca estimativa.
    """
    linhas = confrontar_previsao(q82_por_fre,
                                 {"total": "total_orgao", "membros": "n_membros"})
    for d in linhas:
        for lado in ("previsto", "realizado"):
            tot, n = d[f"{lado}_total"], d[f"{lado}_membros"]
            d[f"{lado}_por_membro"] = (tot / n) if (tot is not None and n) else None
        pm, rm = d["previsto_por_membro"], d["realizado_por_membro"]
        d["desvio_por_membro_pct"] = (100 * (rm / pm - 1)) if (pm and rm) else None
    return linhas


def previsto_x_realizado_individual(mmm_por_fre):
    """Confronto do quadro 8.16 - maxima, media e minima individuais por orgao.

    Na pratica devolve so o lado realizado: o 8.16 nao tem previsao (ver acima).
    Fica aqui porque a serie realizada por orgao alimenta o dashboard.
    """
    return confrontar_previsao(mmm_por_fre,
                               {"maxima": "maxima", "media": "media", "minima": "minima"})


def buscar(termo, cache, log=print):
    alvo, vistos = norm(termo), set()
    print(f"\nCompanhias com '{termo}' no nome:\n")
    for r in sorted(indice_fca(cache, log), key=lambda r: r["nome"]):
        chave = (r["nome"], r["ticker"])
        if alvo in norm(r["nome"]) and chave not in vistos:
            vistos.add(chave)
            print(f"  {r['ticker']:<8} {r['cnpj']:<20} {r['nome']}")
    if not vistos:
        print("  (nada encontrado)")


# ------------------------------------------------------------------------- coleta
def bate(r, cnpjs, nomes):
    if so_digitos(r.get("CNPJ_Companhia", "")) in cnpjs:
        return True
    n = norm(r.get("Nome_Companhia", ""))
    return any(termo in n for termo in nomes)


def coletar(anos, cnpjs, nomes, cache, log=print):
    pares = [(URL_FRE.format(ano=a), os.path.join(cache, f"fre_{a}.zip")) for a in anos]
    zips = baixar_muitos(pares, log)
    mmm, tot = [], []
    for ano in anos:
        zp = zips.get(os.path.join(cache, f"fre_{ano}.zip"))
        if not zp:
            continue
        for destino, marcador in ((mmm, "remuneracao_maxima_minima_media"),
                                  (tot, "remuneracao_total_orgao")):
            for r in linhas_do_zip(zp, marcador):
                if bate(r, cnpjs, nomes):
                    r["_fre"] = ano
                    destino.append(r)
    return mmm, tot


def ultima_versao(linhas):
    """Mantem so a maior Versao de cada (CNPJ, Data_Referencia)."""
    melhor = {}
    for r in linhas:
        k = (r["CNPJ_Companhia"], r["Data_Referencia"])
        v = int(num(r["Versao"]))
        if k not in melhor or v > melhor[k]:
            melhor[k] = v
    return [r for r in linhas
            if int(num(r["Versao"])) == melhor[(r["CNPJ_Companhia"], r["Data_Referencia"])]]


# --------------------------------------------------------------------- montagem
def exercicio(r):
    return int(r["Data_Fim_Exercicio_Social"][:4])


def montar(mmm, tot):
    mmm, tot = ultima_versao(mmm), ultima_versao(tot)

    idx_tot = {(r["CNPJ_Companhia"], r["Data_Referencia"], int(num(r["Versao"])),
                exercicio(r), r["Orgao_Administracao"]): r for r in tot}

    # Fallback: o FRE que traz a max/min/media de um exercicio nem sempre traz o
    # quadro 8.2 dele (as coberturas dos dois quadros nao coincidem sempre). Guarda
    # a melhor linha de 8.2 por (cnpj, exercicio, orgao), preferindo realizado sobre
    # previsao e, dentro disso, o documento mais recente.
    melhor_tot = {}
    for r in tot:
        ex = exercicio(r)
        k = (r["CNPJ_Companhia"], ex, r["Orgao_Administracao"])
        cand = (ex < int(r["Data_Referencia"][:4]), r["Data_Referencia"], int(num(r["Versao"])))
        if k not in melhor_tot or cand > melhor_tot[k][0]:
            melhor_tot[k] = (cand, r)

    def linha(r):
        t = idx_tot.get((r["CNPJ_Companhia"], r["Data_Referencia"], int(num(r["Versao"])),
                         exercicio(r), r["Orgao_Administracao"]))
        if t is None:  # cai para o 8.2 mais recente disponivel daquele exercicio
            alt = melhor_tot.get((r["CNPJ_Companhia"], exercicio(r), r["Orgao_Administracao"]))
            t = alt[1] if alt else None
        total = num(t["Total_Remuneracao_Orgao"]) if t else None
        n_rem = num(r["Numero_Membros_Remunerados"])
        maxi = num(r["Valor_Maior_Remuneracao"])
        mini = num(r["Valor_Menor_Remuneracao"])
        med = num(r["Valor_Medio_Remuneracao"])
        implicita = (total / n_rem) if (total and n_rem) else None
        alertas = []
        if med and (med < mini or med > maxi):
            alertas.append("media fora do intervalo min-max")
        if implicita and med and abs(implicita - med) / max(med, 1.0) > 0.01:
            alertas.append("media != total/n_remunerados")
        return {
            "cnpj": r["CNPJ_Companhia"],
            "empresa": r["Nome_Companhia"],
            "orgao": r["Orgao_Administracao"],
            "exercicio": exercicio(r),
            "maxima": maxi,
            "media": med,
            "minima": mini,
            "n_membros": num(r["Numero_Membros"]),
            "n_membros_remunerados": n_rem,
            "total_orgao": total,
            "fre_total_orgao": t["_fre"] if t else None,
            "media_implicita": implicita,
            "alertas": "; ".join(alertas),
            # mesma regra do 8.2: o FRE do ano E estima a max/media/min de E
            "previsao": exercicio(r) >= int(r["Data_Referencia"][:4]),
            "fre": r["_fre"],
            "data_referencia": r["Data_Referencia"],
            "versao": int(num(r["Versao"])),
            "id_documento": r["ID_Documento"],
        }

    por_fre = sorted((linha(r) for r in mmm),
                     key=lambda d: (d["empresa"], ORDEM_ORGAO.get(norm(d["orgao"]), 9),
                                    d["exercicio"], d["data_referencia"], d["versao"]))

    # consolidado: para cada (empresa, orgao, exercicio) o documento mais recente
    melhor = {}
    for d in por_fre:
        k = (d["cnpj"], d["orgao"], d["exercicio"])
        atual = melhor.get(k)
        if atual is None or (d["data_referencia"], d["versao"]) > (
                atual["data_referencia"], atual["versao"]):
            melhor[k] = d
    consolidado = sorted(melhor.values(),
                         key=lambda d: (d["empresa"], ORDEM_ORGAO.get(norm(d["orgao"]), 9),
                                        d["exercicio"]))

    # quadro 8.2 completo, marcando previsao (exercicio >= ano de referencia do FRE)
    quadro_total = [linha_82(r) for r in tot]
    quadro_total.sort(key=lambda d: (d["empresa"], ORDEM_ORGAO.get(norm(d["orgao"]), 9),
                                     d["exercicio"], d["data_referencia"], d["versao"]))

    # consolidado do 8.2: documento mais recente por (empresa, orgao, exercicio)
    melhor_82 = {}
    for d in quadro_total:
        k = (d["cnpj"], d["orgao"], d["exercicio"])
        atual = melhor_82.get(k)
        if atual is None or (d["data_referencia"], d["versao"]) > (
                atual["data_referencia"], atual["versao"]):
            melhor_82[k] = d
    quadro_total_cons = sorted(melhor_82.values(),
                               key=lambda d: (d["empresa"], d["exercicio"],
                                              ORDEM_ORGAO.get(norm(d["orgao"]), 9)))
    return consolidado, por_fre, quadro_total_cons, quadro_total


def linha_82(r):
    """Uma linha do quadro 8.2, com todas as verbas do formulario."""
    ex = exercicio(r)
    d = {
        "cnpj": r["CNPJ_Companhia"],
        "empresa": r["Nome_Companhia"],
        "orgao": r["Orgao_Administracao"],
        "exercicio": ex,
        "n_membros": num(r["Numero_Membros"]),
        "n_membros_remunerados": num(r["Numero_Membros_Remunerados"]),
    }
    for _rotulo, campo, coluna, _grupo in CAMPOS_82:
        d[campo] = num(r.get(coluna))
    d["total_orgao"] = num(r["Total_Remuneracao_Orgao"])
    d["total_empresa"] = num(r.get("Total_Remuneracao"))

    soma = round(sum(d[campo] for _r, campo, _c, _g in CAMPOS_82), 2)
    d["soma_verbas"] = soma
    # a CVM nao valida o quadro: ha empresas cujo total declarado nao fecha com a
    # soma das verbas (verba omitida, arredondamento, ou total digitado a mao).
    dif = round(soma - d["total_orgao"], 2)
    d["dif_soma_total"] = dif
    if soma == 0 and d["total_orgao"]:
        # quadro entregue so com o total: a abertura por verba nao foi preenchida.
        # Sem isso, os zeros das verbas seriam lidos como "a empresa nao pagou".
        d["alertas_82"] = "verbas nao detalhadas (so o total foi informado)"
    elif abs(dif) > max(0.01, abs(d["total_orgao"]) * 0.001):
        d["alertas_82"] = "soma das verbas != total do orgao"
    else:
        d["alertas_82"] = ""

    d["desc_outras_fixas"] = (r.get("Descricao_Outros_Remuneracoes_Fixas") or "").strip()
    d["desc_outras_variaveis"] = (r.get("Descricao_Outros_Remuneracoes_Variaveis") or "").strip()
    d["observacao"] = " ".join((r.get("Observacao") or "").split())
    d["previsao"] = ex >= int(r["Data_Referencia"][:4])
    d["fre"] = r["_fre"]
    d["data_referencia"] = r["Data_Referencia"]
    d["versao"] = int(num(r["Versao"]))
    d["id_documento"] = r["ID_Documento"]
    return d


# -------------------------------------------------------------------------- saida
def gravar(linhas, caminho):
    if not linhas:
        return
    # uniao das chaves, na ordem em que aparecem: campos opcionais (como
    # escala_corrigida) so existem em algumas linhas e sumiriam se olhassemos so a 1a
    campos = {}
    for d in linhas:
        campos.update(dict.fromkeys(d))
    with open(caminho, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(campos), delimiter=";", restval="")
        w.writeheader()
        w.writerows(linhas)
    print(f"  {caminho}  ({len(linhas)} linhas)")


def imprimir(consolidado):
    atual = None
    for d in consolidado:
        chave = (d["empresa"], d["orgao"])
        if chave != atual:
            atual = chave
            print(f"\n### {d['empresa']} - {d['orgao']}")
            print(f"{'Exerc':<7}{'Maxima':>17}{'Media':>17}{'Minima':>17}"
                  f"{'N memb':>9}{'Total orgao':>19}  Fonte")
        alerta = "  <-- " + d["alertas"] if d["alertas"] else ""
        print(f"{d['exercicio']:<7}{brl(d['maxima']):>17}{brl(d['media']):>17}"
              f"{brl(d['minima']):>17}{d['n_membros']:>9.2f}{brl(d['total_orgao']):>19}"
              f"  FRE {d['fre']} v{d['versao']}{alerta}")


ESCALA = 1000.0


def _mediana(vals):
    v = sorted(x for x in vals if x)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def revisar_escala(q82_por_fre, mmm_por_fre, log=print):
    """Corrige erros de ordem de grandeza nos formularios.

    Nao ha campo de unidade no FRE: a CVM manda tudo em reais, mas parte das
    companhias digita em milhares. O erro aparece em tres formatos, cada um com uma
    evidencia diferente:

    1. total do orgao inflado 1000x, verbas certas - a soma das verbas denuncia
       (PetroRio 2018: total R$ 1,1 bilhao com salario de R$ 923 mil);
    2. quadro 8.16 em milhares, 8.2 em reais - a media individual comparada com
       total/n_remunerados denuncia (Alpargatas de 2023 em diante);
    3. linha isolada fora de escala com verbas igualmente infladas - so a serie
       historica da propria companhia denuncia (Copel, conselho fiscal 2025).

    O caso 3 nao tem prova interna, entao a linha e corrigida mas marcada como
    suspeita: o valor original fica em `total_orgao_original` para auditoria.
    """
    campos_verba = [campo for _rot, campo, _col, _g in CAMPOS_82]
    ajustes = {"total inflado (soma das verbas)": 0, "8.16 em milhares": 0,
               "linha fora da serie": 0}

    # --- 1. total inflado, verbas coerentes
    for d in q82_por_fre:
        soma, total = d["soma_verbas"], d["total_orgao"]
        if soma and total and abs(total - soma * ESCALA) <= 0.05 * abs(total):
            d["total_orgao_original"] = total
            d["total_orgao"] = soma
            d["escala_corrigida"] = "total estava 1000x acima da soma das verbas"
            d["alertas_82"] = ""
            ajustes["total inflado (soma das verbas)"] += 1

    # --- 3. linha isolada fora da serie da propria companhia/orgao
    series = {}
    for d in q82_por_fre:
        series.setdefault((d["cnpj"], d["orgao"]), []).append(d["total_orgao"])
    medianas = {k: _mediana(v) for k, v in series.items()}
    for d in q82_por_fre:
        med = medianas.get((d["cnpj"], d["orgao"]))
        t = d["total_orgao"]
        if not (med and t) or d.get("escala_corrigida"):
            continue
        if t > 100 * med and med / 5 <= t / ESCALA <= med * 5:
            d["total_orgao_original"] = t
            for campo in campos_verba:
                d[campo] = d[campo] / ESCALA
            d["total_orgao"] = t / ESCALA
            d["soma_verbas"] = round(d["soma_verbas"] / ESCALA, 2)
            d["escala_corrigida"] = "linha 1000x fora da serie da companhia (suspeita)"
            ajustes["linha fora da serie"] += 1

    # --- 2. quadro 8.16 em milhares: compara com o total/n_remunerados do 8.2
    tot82 = {}
    for d in q82_por_fre:
        chave = (d["cnpj"], d["exercicio"], d["orgao"])
        marca = (d["data_referencia"], d["versao"])
        atual = tot82.get(chave)
        if atual is None or marca > atual[0]:   # vale o documento mais recente
            tot82[chave] = (marca, d["total_orgao"])
    for d in mmm_por_fre:
        achado = tot82.get((d["cnpj"], d["exercicio"], d["orgao"]))
        total = achado[1] if achado else d["total_orgao"]
        d["total_orgao"] = total              # reaproveita o 8.2 ja corrigido
        n, med = d["n_membros_remunerados"], d["media"]
        if total and n and med and 300 < (total / n) / med < 3000:
            for campo in ("maxima", "media", "minima"):
                d[campo] = d[campo] * ESCALA
            d["escala_corrigida"] = "8.16 reportado em milhares"
            ajustes["8.16 em milhares"] += 1
        # alertas do 8.16 recalculados sobre os valores ja corrigidos
        d["media_implicita"] = (total / n) if (total and n) else None
        alertas = []
        if d["media"] and (d["media"] < d["minima"] or d["media"] > d["maxima"]):
            alertas.append("media fora do intervalo min-max")
        if d["media_implicita"] and d["media"] and \
                abs(d["media_implicita"] - d["media"]) / max(d["media"], 1.0) > 0.01:
            alertas.append("media != total/n_remunerados")
        d["alertas"] = "; ".join(alertas)

    feitos = {k: v for k, v in ajustes.items() if v}
    if feitos:
        log("revisao de escala: " + "; ".join(f"{v} linha(s) - {k}" for k, v in feitos.items()))
    return q82_por_fre, mmm_por_fre


def filtrar_por_exercicio(listas, exercicio_ref=None, log=print):
    """Tira do acompanhamento quem nao reportou o exercicio de referencia.

    Companhia que fechou capital ou foi incorporada continua no historico da CVM,
    mas para de entregar FRE - e ficar comparando quem parou em 2021 com quem
    reportou 2025 distorce qualquer ranking. Sem exercicio_ref, usa o exercicio
    realizado mais recente presente na base.
    """
    q82_cons = listas["q82_cons"]
    if exercicio_ref is None:
        realizados = [d["exercicio"] for d in q82_cons if not d["previsao"]]
        if not realizados:
            return listas, set()
        exercicio_ref = max(realizados)

    vivas = {so_digitos(d["cnpj"]) for d in q82_cons
             if d["exercicio"] == exercicio_ref and not d["previsao"]}
    nomes = {so_digitos(d["cnpj"]): d.get("apelido") or d["empresa"] for d in q82_cons}
    fora = {c: n for c, n in nomes.items() if c not in vivas}
    if fora:
        log(f"fora do acompanhamento (sem exercicio {exercicio_ref}): "
            + ", ".join(sorted(fora.values())))
    for nome, lista in listas.items():
        listas[nome] = [d for d in lista if so_digitos(d.get("cnpj", "")) in vivas]
    return listas, set(fora.values())


def remuneracao_por_exercicio(q82_cons):
    """Agrega o quadro 8.2 por (cnpj, exercicio) - base para os indicadores de mercado."""
    fora = {}
    campo = {"diretoria estatutaria": "diretoria",
             "conselho de administracao": "conselho_adm",
             "conselho fiscal": "conselho_fiscal"}
    for d in q82_cons:
        k = (so_digitos(d["cnpj"]), d["exercicio"])
        e = fora.setdefault(k, {"empresa": d["empresa"], "cnpj_fmt": d["cnpj"],
                                "total": 0.0, "total_previsto": 0.0, "orgaos": 0})
        e["total"] += d["total_orgao"]
        e["orgaos"] += 1
        if d["previsao"]:
            e["total_previsto"] += d["total_orgao"]
        c = campo.get(norm(d["orgao"]))
        if c:
            e[c] = e.get(c, 0.0) + d["total_orgao"]
    # Um exercicio costuma misturar orgaos ja realizados com algum ainda em previsao
    # (tipicamente um conselho fiscal zerado). So marca como previsao quando a maior
    # parte do valor vem de linhas previstas, e guarda a fracao para quem quiser ver.
    for e in fora.values():
        frac = (e["total_previsto"] / e["total"]) if e["total"] else 0.0
        e["parcela_previsao"] = frac
        e["previsao"] = frac > 0.5
    return fora


ABREV_ORGAO = {
    "diretoria estatutaria": "Diretoria Est.",
    "conselho de administracao": "Cons. Admin.",
    "conselho fiscal": "Cons. Fiscal",
}


def imprimir_82(quadro, modo):
    """Reproduz o quadro 8.2 do formulario: verbas nas linhas, orgaos nas colunas."""
    porexerc = {}
    for d in quadro:
        porexerc.setdefault((d["empresa"], d["exercicio"]), []).append(d)

    chaves = sorted(porexerc)
    if modo == "ultimo":  # so o exercicio mais recente de cada empresa
        ultimo = {}
        for emp, ex in chaves:
            ultimo[emp] = max(ultimo.get(emp, ex), ex)
        chaves = [(emp, ex) for emp, ex in chaves if ex == ultimo[emp]]

    for emp, ex in chaves:
        orgaos = sorted(porexerc[(emp, ex)],
                        key=lambda d: ORDEM_ORGAO.get(norm(d["orgao"]), 9))
        prev = " (previsao)" if any(d["previsao"] for d in orgaos) else ""
        cab = orgaos[0]
        print(f"\n### {emp} - remuneracao total do exercicio social {ex}{prev}"
              f"   [FRE {cab['fre']} v{cab['versao']}]")
        larg = 17
        print(f"{'':<34}" + "".join(
            f"{ABREV_ORGAO.get(norm(d['orgao']), d['orgao'][:15]):>{larg}}" for d in orgaos)
            + f"{'Total':>{larg}}")

        def linha(rotulo, vals, negrito=False):
            marca = "* " if negrito else "  "
            print(f"{marca}{rotulo:<32}" + "".join(f"{v:>{larg}}" for v in vals))

        linha("N total de membros", [f"{d['n_membros']:.2f}" for d in orgaos]
              + [f"{sum(d['n_membros'] for d in orgaos):.2f}"])
        linha("N de membros remunerados",
              [f"{d['n_membros_remunerados']:.2f}" for d in orgaos]
              + [f"{sum(d['n_membros_remunerados'] for d in orgaos):.2f}"])

        for grupo, titulo in GRUPOS_82:
            campos = [(rot, c) for rot, c, _col, g in CAMPOS_82 if g == grupo]
            if not any(d[c] for _rot, c in campos for d in orgaos):
                continue  # grupo inteiro zerado: nao polui a tabela
            print(f"  {titulo}")
            for rot, campo in campos:
                vals = [brl(d[campo]) for d in orgaos] + [brl(sum(d[campo] for d in orgaos))]
                linha("  " + rot, vals)

        linha("Total da remuneracao",
              [brl(d["total_orgao"]) for d in orgaos]
              + [brl(sum(d["total_orgao"] for d in orgaos))], negrito=True)

        for d in orgaos:
            if d["alertas_82"]:
                print(f"    <-- {ABREV_ORGAO.get(norm(d['orgao']), d['orgao'])}: "
                      f"{d['alertas_82']} (soma {brl(d['soma_verbas'])}, "
                      f"declarado {brl(d['total_orgao'])})")
        for rotulo, campo in (("Outras fixas", "desc_outras_fixas"),
                              ("Outras variaveis", "desc_outras_variaveis")):
            descs = {d[campo] for d in orgaos if d[campo] and d[campo] != "-"}
            for t in descs:
                print(f"    {rotulo}: {t[:150]}")
        obs = {d["observacao"] for d in orgaos if d["observacao"]}
        for t in obs:
            print(f"    Observacao: {t[:200]}")


def milhoes(v):
    return "-" if not v else f"{v / 1e6:,.1f}".replace(",", "@").replace(".", ",").replace("@", ".")


def imprimir_mercado(linhas):
    atual = None
    for d in linhas:
        if d["empresa"] != atual:
            atual = d["empresa"]
            print(f"\n### {atual} - remuneracao x receita x market cap"
                  f"{('  [' + d['tickers'] + ']') if d['tickers'] else ''}")
            print(f"{'Exerc':<8}{'Remuneracao':>14}{'Receita':>16}{'Market cap':>16}"
                  f"{'% receita':>12}{'% mkt cap':>12}   (R$ milhoes)")
        pr = f"{d['rem_sobre_receita_pct']:.3f}%" if d["rem_sobre_receita_pct"] else "-"
        pm = f"{d['rem_sobre_market_cap_pct']:.3f}%" if d["rem_sobre_market_cap_pct"] else "-"
        marca = " prev." if d["previsao"] else ""
        print(f"{str(d['exercicio']) + marca:<8}{milhoes(d['remuneracao_total']):>14}"
              f"{milhoes(d['receita']):>16}{milhoes(d['market_cap']):>16}{pr:>12}{pm:>12}"
              + (f"   <-- {d['alertas_mercado']}" if d["alertas_mercado"] else ""))


def parse_anos(txt):
    if "-" in txt:
        a, b = txt.split("-", 1)
    else:
        a = b = txt
    return range(max(ANO_MIN, int(a)), min(ANO_MAX, int(b)) + 1)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Remuneracao de administradores (FRE/CVM) por companhia.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("alvos", nargs="*", help="tickers (LREN3), CNPJs ou trechos do nome")
    p.add_argument("--anos", default=f"{ANO_MIN}-{ANO_MAX}", help="ex.: 2015-2026")
    p.add_argument("--out", default="remuneracao_cvm.csv", help="CSV consolidado de saida")
    p.add_argument("--cache", default=".cvm_cache", help="diretorio dos zips da CVM")
    p.add_argument("--buscar", metavar="TERMO", help="lista ticker/CNPJ por trecho do nome e sai")
    p.add_argument("--carteira", metavar="ARQUIVO.json",
                   help="roda a carteira por setor descrita no JSON (ver carteira.json)")
    p.add_argument("--quadro82", choices=("ultimo", "todos", "nao"), default="ultimo",
                   help="imprime o quadro 8.2 (verbas por orgao): so o ultimo exercicio "
                        "(padrao), todos, ou nao imprime")
    p.add_argument("--mercado", action="store_true",
                   help="baixa DFP (receita e acoes ex-tesouraria) e cotacoes, e calcula "
                        "remuneracao / receita e remuneracao / market cap")
    p.add_argument("--dashboard", metavar="ARQUIVO.html", nargs="?", const="dashboard.html",
                   help="gera o dashboard HTML consolidado (implica --mercado)")
    p.add_argument("--exercicio-ref", type=int, default=None, metavar="ANO",
                   help="exercicio que a companhia precisa ter reportado para seguir "
                        "no acompanhamento (padrao: o mais recente realizado na base)")
    p.add_argument("--manter-inativas", action="store_true",
                   help="mantem companhias que pararam de entregar FRE")
    p.add_argument("--quiet", action="store_true", help="nao imprime as tabelas")
    a = p.parse_args(argv)

    os.makedirs(a.cache, exist_ok=True)
    log = (lambda *x: None) if a.quiet else print

    if a.buscar:
        buscar(a.buscar, a.cache, log)
        return 0
    if not a.alvos and not a.carteira:
        p.error("informe ao menos um ticker, CNPJ ou nome (ou use --carteira/--buscar)")

    anos = parse_anos(a.anos)
    meta = {}
    if a.carteira:
        cnpjs, nomes, meta, _fora = carregar_carteira(a.carteira, a.cache, log)
        if a.alvos:  # permite somar alvos avulsos a uma carteira
            c2, n2 = resolver_alvos(a.alvos, a.cache, log)
            cnpjs |= c2
            nomes += n2
    else:
        cnpjs, nomes = resolver_alvos(a.alvos, a.cache, log)
    if not cnpjs and not nomes:
        print("Nenhum alvo valido.", file=sys.stderr)
        return 1

    log(f"lendo FREs {anos.start}-{anos.stop - 1} ...")
    mmm, tot = coletar(anos, cnpjs, nomes, a.cache, log)
    if not mmm:
        print("Nenhum dado de remuneracao encontrado para os alvos informados.", file=sys.stderr)
        print("Dica: use --buscar <trecho do nome> para achar o ticker/CNPJ certo.", file=sys.stderr)
        return 1

    consolidado, por_fre, q82_cons, q82_por_fre = montar(mmm, tot)
    # corrige ordem de grandeza antes de qualquer agregacao (as listas consolidadas
    # compartilham os mesmos dicts, entao a correcao se propaga sozinha)
    revisar_escala(q82_por_fre, por_fre, log)
    prev_real = previsto_x_realizado(q82_por_fre)
    prev_real_ind = previsto_x_realizado_individual(por_fre)

    def etiquetar(linhas):
        """Acrescenta setor e apelido da carteira; sem carteira, nao mexe."""
        for d in linhas:
            m = meta.get(so_digitos(d.get("cnpj", "")))
            d["setor"] = m["setor"] if m else ""
            d["apelido"] = m["nome"] if m else d.get("empresa", "")
        return linhas

    for grupo in (consolidado, por_fre, q82_cons, q82_por_fre,
                  prev_real, prev_real_ind):
        etiquetar(grupo)

    if not a.manter_inativas:
        listas = {"consolidado": consolidado, "por_fre": por_fre, "q82_cons": q82_cons,
                  "q82_por_fre": q82_por_fre, "prev_real": prev_real,
                  "prev_real_ind": prev_real_ind}
        listas, _fora = filtrar_por_exercicio(listas, a.exercicio_ref, log)
        consolidado, por_fre = listas["consolidado"], listas["por_fre"]
        q82_cons, q82_por_fre = listas["q82_cons"], listas["q82_por_fre"]
        prev_real, prev_real_ind = listas["prev_real"], listas["prev_real_ind"]

    if not a.quiet:
        imprimir(consolidado)
        if a.quadro82 != "nao":
            imprimir_82(q82_cons, a.quadro82)

    base = re.sub(r"\.csv$", "", a.out)
    print("\nArquivos gerados:")
    gravar(consolidado, f"{base}.csv")
    gravar(por_fre, f"{base}_por_fre.csv")
    gravar(q82_cons, f"{base}_total_orgao.csv")
    gravar(q82_por_fre, f"{base}_total_orgao_por_fre.csv")
    gravar(prev_real, f"{base}_previsto_realizado.csv")
    gravar(prev_real_ind, f"{base}_previsto_realizado_individual.csv")

    if a.mercado or a.dashboard:
        import cvm_mercado
        rem_exerc = remuneracao_por_exercicio(q82_cons)
        exercicios = sorted({ex for _c, ex in rem_exerc})
        # a DFP de um exercicio e publicada no proprio ano-calendario dele
        anos_dfp = [x for x in exercicios if ANO_MIN <= x <= ANO_MAX]
        log(f"\nlendo DFPs {anos_dfp[0]}-{anos_dfp[-1]} (receita e acoes) ...")
        dfp = cvm_mercado.coletar_dfp(anos_dfp, cnpjs, nomes, a.cache, log)
        cap_fre = cvm_mercado.coletar_fre_capital(anos, cnpjs, nomes, a.cache, log)
        dfp = cvm_mercado.conciliar_acoes(dfp, cap_fre, log)
        cnpjs_vistos = {c for c, _ex in rem_exerc}
        extras = {c: ([m["ticker"]] if m.get("ticker") else []) + m.get("tickers", [])
                  for c, m in meta.items()}
        precos = cvm_mercado.cotacoes(
            cvm_mercado.tickers_por_cnpj(cnpjs_vistos, a.cache, log, extras), log)
        mercado = etiquetar(cvm_mercado.montar_mercado(rem_exerc, dfp, precos, log))
        gravar(mercado, f"{base}_mercado.csv")
        if not a.quiet:
            imprimir_mercado(mercado)
        if a.dashboard:
            import cvm_dashboard
            cvm_dashboard.gerar(a.dashboard, mercado, q82_cons, consolidado,
                                prev_real, prev_real_ind, q82_por_fre)
            print(f"  {a.dashboard}  (dashboard)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
