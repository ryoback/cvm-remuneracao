#!/usr/bin/env python3
"""
Dashboard HTML consolidado da remuneracao de administradores.

Uma aba por setor com o ranking das companhias; dentro de cada companhia, cinco
visoes: geral (proporcoes e crescimento), composicao por natureza da verba,
detalhe por orgao (maxima/media/minima), confronto previsto x realizado e o
quadro 8.2 aberto ano a ano.

Arquivo unico, sem dependencia externa (nada de CDN) - abre offline.
"""
from __future__ import annotations

import datetime
import html
import json

from cvm_remuneracao import CAMPOS_82, GRUPOS_82, ORDEM_ORGAO, norm

CAMPOS = [(rot, campo, grupo) for rot, campo, _col, grupo in CAMPOS_82]


def _r(v, casas=2):
    return None if v is None else round(float(v), casas)


def _chave_org(o):
    return ORDEM_ORGAO.get(norm(o), 9)


def _serie(linhas_mercado, q82, mmm, prev_real, prev_real_ind):
    """Monta {empresa: {..., serie: {orgao: {ano: metricas}}}}.

    As verbas vao como lista na ordem de CAMPOS_82 - com 66 companhias x 17 anos
    x 3 orgaos, repetir 12 chaves textuais por celula dobraria o tamanho do HTML.
    """
    emp = {}

    def chave(d):
        # indexa por CNPJ, nao por nome: companhia que troca de razao social
        # (Eletrobras -> Axia Energia, CCR -> Motiva) viraria duas empresas
        return "".join(ch for ch in str(d.get("cnpj", "")) if ch.isdigit())

    def slot(d):
        return emp.get(chave(d))

    for d in linhas_mercado:
        e = emp.setdefault(chave(d), {
            "empresa": d["empresa"],
            "apelido": d.get("apelido") or d["empresa"],
            "setor": d.get("setor") or "Sem setor",
            "cnpj": d["cnpj"], "id": chave(d), "tickers": d.get("tickers") or "",
            "anos": {}, "serie": {}, "_ultimo_ex": -1,
        })
        if d.get("tickers"):
            e["tickers"] = d["tickers"]
        if d["exercicio"] > e["_ultimo_ex"]:      # fica a razao social mais recente
            e["_ultimo_ex"] = d["exercicio"]
            e["empresa"] = d["empresa"]
        e["anos"][d["exercicio"]] = {
            "ex": d["exercicio"],
            "rem": _r(d["remuneracao_total"]),
            "receita": _r(d.get("receita")),
            "mcap": _r(d.get("market_cap")),
            "preco": _r(d.get("preco_medio_ponderado")),
            "precos": d.get("precos_por_classe") or "",
            "acoes": _r(d.get("acoes_ex_tesouraria"), 0),
            "p_rec": _r(d.get("rem_sobre_receita_pct"), 4),
            "p_mc": _r(d.get("rem_sobre_market_cap_pct"), 4),
            "previsao": bool(d.get("previsao")),
            "alerta": d.get("alertas_mercado") or "",
        }

    def celula(e, orgao, ex):
        return e["serie"].setdefault(orgao, {}).setdefault(str(ex), {})

    for d in q82:
        e = slot(d)
        if not e:
            continue
        c = celula(e, d["orgao"], d["exercicio"])
        c["v"] = [_r(d[campo]) for _rot, campo, _g in CAMPOS]
        c["tot"] = _r(d["total_orgao"])
        c["nm"] = _r(d["n_membros"])
        c["nr"] = _r(d["n_membros_remunerados"])
        if d.get("alertas_82"):
            c["al"] = d["alertas_82"]
        if d.get("observacao"):
            c["obs"] = d["observacao"][:400]

    for d in mmm:
        e = slot(d)
        if not e:
            continue
        c = celula(e, d["orgao"], d["exercicio"])
        c["mx"], c["md"], c["mn"] = _r(d["maxima"]), _r(d["media"]), _r(d["minima"])
        if d.get("alertas"):
            c["al16"] = d["alertas"]

    for d in prev_real:
        e = slot(d)
        if not e:
            continue
        c = celula(e, d["orgao"], d["exercicio"])
        c["pt"] = _r(d.get("previsto_total"))
        c["rt"] = _r(d.get("realizado_total"))
        c["pnm"] = _r(d.get("previsto_membros"))
        c["rnm"] = _r(d.get("realizado_membros"))

    for e in emp.values():
        e["anos"] = [e["anos"][a] for a in sorted(e["anos"])]
        e["orgaos"] = sorted(e["serie"], key=_chave_org)
        e.pop("_ultimo_ex", None)
    return sorted(emp.values(), key=lambda e: (e["setor"], e["apelido"]))


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--mut:#6b7280;--line:#e3e6ea;
--ac:#2563eb;--ac2:#0d9488;--ac3:#b45309;--ac4:#7c3aed;--ac5:#db2777;
--warn:#b91c1c;--warnbg:#fef2f2;--pos:#047857;--neg:#b91c1c;
--cardhov:#f1f2f4;--cardgrp:#f2f3f4;}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a20;--ink:#e8eaed;
--mut:#9aa3af;--line:#272b33;--ac:#60a5fa;--ac2:#2dd4bf;--ac3:#fbbf24;--ac4:#a78bfa;
--ac5:#f472b6;--warn:#fca5a5;--warnbg:#2a1416;--pos:#34d399;--neg:#f87171;
--cardhov:#1e222a;--cardgrp:#1d2027;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,
BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:1320px;margin:0 auto;padding:22px 20px 64px}
h1{font-size:21px;margin:0 0 2px}
.sub{color:var(--mut);font-size:13px;margin-bottom:16px;max-width:940px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin-bottom:16px}
h2{font-size:15px;margin:0 0 12px}
h3{font-size:12px;margin:20px 0 9px;color:var(--mut);text-transform:uppercase;
letter-spacing:.05em}
.tabs{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:14px}
.tab{padding:6px 13px;border-radius:7px;border:1px solid var(--line);cursor:pointer;
background:var(--card);font:inherit;font-size:13px;color:var(--ink)}
.tab:hover{border-color:var(--ac)}
.tab[aria-selected=true]{background:var(--ac);color:#fff;border-color:var(--ac)}
.tabs.mini .tab{padding:4px 10px;font-size:12px}
.tabs.sub2 .tab[aria-selected=true]{background:var(--ac4);border-color:var(--ac4)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;
margin-bottom:16px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 15px}
.kpi .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
.kpi .val{font-size:20px;font-weight:650;margin-top:5px;font-variant-numeric:tabular-nums}
.kpi .hint{font-size:11px;color:var(--mut);margin-top:3px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:right;
white-space:nowrap;font-variant-numeric:tabular-nums}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);
font-weight:600}
th:first-child,td:first-child{text-align:left}
tbody tr:hover{background:rgba(127,127,127,.06)}
tr.clic{cursor:pointer}
.grp td{font-weight:650;background:rgba(127,127,127,.05);font-size:11px;
text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
.tot td{font-weight:700;border-top:2px solid var(--line)}
.prev{color:var(--ac3);font-size:11px}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.warn{background:var(--warnbg);color:var(--warn);border:1px solid currentColor;
border-radius:7px;padding:8px 11px;margin:9px 0;font-size:12px}
.leg{display:flex;gap:15px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-top:8px}
.leg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.mut{color:var(--mut)}
.note{font-size:12px;color:var(--mut);margin-top:10px;line-height:1.6}
svg{display:block;max-width:100%}
.back{background:none;border:none;color:var(--ac);cursor:pointer;font:inherit;
padding:0;margin-bottom:10px}
.dois{display:grid;grid-template-columns:repeat(auto-fit,minmax(390px,1fr));gap:16px}
/* navegacao lateral: setores como rotulo, companhias abaixo */
.layout{display:grid;grid-template-columns:232px minmax(0,1fr);gap:18px;align-items:start}
.side{position:sticky;top:14px;max-height:calc(100vh - 28px);overflow:auto;
background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 10px}
.side input{width:100%;padding:6px 9px;border-radius:7px;border:1px solid var(--line);
background:var(--bg);color:var(--ink);font:inherit;font-size:13px}
.side .cnt{font-size:11px;color:var(--mut);margin:7px 2px 2px}
.side .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);
font-weight:600;margin:11px 0 3px;cursor:pointer;padding:3px 7px;border-radius:6px;
border:none;background:none;font-family:inherit;display:block;width:100%;text-align:left}
.side .lbl:hover{color:var(--ac);background:rgba(127,127,127,.08)}
.side .lbl[aria-selected=true]{color:var(--ac)}
.side .emp{display:block;width:100%;text-align:left;border:none;background:none;
font:inherit;font-size:13px;color:var(--ink);padding:4px 8px;border-radius:6px;
cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.side .emp:hover{background:rgba(127,127,127,.1)}
.side .emp[aria-selected=true]{background:var(--ac);color:#fff}
.side .vazio{font-size:12px;color:var(--mut);padding:8px 2px}
@media(max-width:900px){.layout{grid-template-columns:minmax(0,1fr)}
.side{position:static;max-height:290px}}
/* primeira coluna congelada: fica visivel enquanto a tabela rola na horizontal */
table.fix1 th:first-child,table.fix1 td:first-child{position:sticky;left:0;z-index:2;
background:var(--card);box-shadow:1px 0 0 var(--line)}
table.fix1 thead th:first-child{z-index:3}
table.fix1 tbody tr:hover td:first-child{background:var(--cardhov)}
table.fix1 tbody tr.grp td:first-child{background:var(--cardgrp)}
"""

JS = r"""
const DADOS=__DADOS__, CAMPOS=__CAMPOS__, GRUPOS=__GRUPOS__, SETORES=__SETORES__;
const $=s=>document.querySelector(s);
const st={setor:'Todos', empresa:null, aba:'geral', ex:null, org:'__todos__',
          orgSetor:'Diretoria Estatutária', busca:''};

const fmt=(v,d=2)=>v==null||isNaN(v)?'–':v.toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=(v,d=1)=>v==null||isNaN(v)?'–':fmt(v,d)+'%';
const pctMc=v=>pct(v,2);   // razao sobre market cap: mediana ~0,03%, 1 casa zeraria
const sinal=(v,d=1)=>v==null||isNaN(v)?'–':(v>0?'+':'')+fmt(v,d)+'%';
function curto(v){
  if(v==null||isNaN(v)) return '–';
  const a=Math.abs(v);
  if(a>=1e9) return 'R$ '+fmt(v/1e9,2)+' bi';
  if(a>=1e6) return 'R$ '+fmt(v/1e6,1)+' mi';
  if(a>=1e3) return 'R$ '+fmt(v/1e3,0)+' mil';
  return 'R$ '+fmt(v,0);
}
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
// minusculo e sem acento, para a busca casar "Azzas" com "AZZAS" e "Raizen" com "Raízen"
const norm=s=>String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().trim();
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const kpi=(l,v,h)=>`<div class="kpi"><div class="lbl">${l}</div><div class="val">${v}</div><div class="hint">${h||'&nbsp;'}</div></div>`;
const legenda=s=>`<div class="leg">${s.map(x=>`<span><i style="background:${x.cor}"></i>${esc(x.nome)}</span>`).join('')}</div>`;
const ultimo=e=>e.anos.filter(a=>!a.previsao).slice(-1)[0]||e.anos.slice(-1)[0]||{};
const ABREV={'Diretoria Estatutária':'Diretoria','Conselho de Administração':'Cons. Adm.','Conselho Fiscal':'Cons. Fiscal'};
const ab=o=>ABREV[o]||o;

/* anos com dado de quadro 8.2, para o recorte por orgao */
function anosDe(e,org){
  const s=new Set();
  const orgs = org==='__todos__' ? e.orgaos : [org];
  orgs.forEach(o=>Object.keys(e.serie[o]||{}).forEach(a=>s.add(+a)));
  return [...s].sort((a,b)=>a-b);
}
/* soma um campo entre orgaos (ou le de um so) */
function val(e,org,ano,f){
  const orgs = org==='__todos__' ? e.orgaos : [org];
  let t=null;
  orgs.forEach(o=>{const c=(e.serie[o]||{})[String(ano)]; if(!c) return;
    const v=f(c); if(v!=null&&!isNaN(v)) t=(t||0)+v;});
  return t;
}
/* soma das verbas de um grupo (fixa/variavel/outros) */
const idxGrupo=g=>CAMPOS.map((c,i)=>[c,i]).filter(([c])=>c[2]===g).map(([,i])=>i);
function grupoVal(e,org,ano,g){
  const ids=idxGrupo(g);
  return val(e,org,ano,c=>c.v?ids.reduce((s,i)=>s+(c.v[i]||0),0):null);
}

/* ---------------- graficos ---------------- */
/* Rotulos de valor com desvio de colisao: tenta desenhar todos e descarta os que
   cairiam em cima de um ja desenhado. Assim o grafico dosa sozinho a densidade -
   com poucos pontos aparecem todos, com muitos aparecem os que couberem. */
function criaRotulador(){
  const caixas=[];
  return (g,x,y,txt,cor)=>{
    if(txt==null||txt==='') return;
    const w=String(txt).length*4.6+4, h=10;
    const c={x0:x-w/2,x1:x+w/2,y0:y-h,y1:y+2};
    if(c.x0<0||c.x1>880) return;
    for(const b of caixas) if(!(c.x1<b.x0||c.x0>b.x1||c.y1<b.y0||c.y0>b.y1)) return;
    caixas.push(c);
    g.push(`<text x="${x}" y="${y}" text-anchor="middle" font-size="8.5" fill="${cor||css('--mut')}">${esc(txt)}</text>`);
  };
}
function eixoY(g,m,W,H,L0,L1,fmtE,n=4){
  for(let k=0;k<=n;k++){const yy=m.t+k*(H-m.t-m.b)/n, v=L1-(L1-L0)*k/n;
    g.push(`<line x1="${m.l}" x2="${W-m.r}" y1="${yy}" y2="${yy}" stroke="${css('--line')}"/>`,
      `<text x="${m.l-8}" y="${yy+4}" text-anchor="end" font-size="10" fill="${css('--mut')}">${fmtE(v)}</text>`);}
}
function rotX(g,rot,m,W,H,bw,rotacao){
  rot.forEach((a,i)=>{const tx=m.l+i*bw+bw/2;
    if(rotacao){const ty=H-m.b+13;
      g.push(`<text x="${tx}" y="${ty}" transform="rotate(-40 ${tx} ${ty})" text-anchor="end" font-size="10" fill="${css('--mut')}">${esc(String(a).slice(0,16))}</text>`);}
    else g.push(`<text x="${tx}" y="${H-8}" text-anchor="middle" font-size="10" fill="${css('--mut')}">${esc(a)}</text>`);});
}
/* linhas: series continuas, escala linear, formatador livre */
function gLinhas(rot,series,o={}){
  const W=880,H=o.alt||210,m={t:o.rotulos===false?14:22,r:16,b:26,l:o.l||62};
  const pts=series.flatMap(s=>s.vals.filter(v=>v!=null&&!isNaN(v)));
  if(!pts.length||rot.length<2) return '<p class="mut">Sem dados suficientes.</p>';
  let L1=Math.max(...pts), L0=Math.min(...pts);
  if(o.zero!==false) L0=Math.min(0,L0);
  const pad=(L1-L0)*0.1||Math.abs(L1)*0.1||1; L1+=pad; if(L0<0)L0-=pad;
  const x=i=>m.l+i*(W-m.l-m.r)/Math.max(1,rot.length-1);
  const y=v=>H-m.b-(v-L0)/((L1-L0)||1)*(H-m.t-m.b);
  const g=[]; eixoY(g,m,W,H,L0,L1,o.fmtE||(v=>fmt(v,2)));
  if(L0<0&&L1>0) g.push(`<line x1="${m.l}" x2="${W-m.r}" y1="${y(0)}" y2="${y(0)}" stroke="${css('--mut')}" stroke-dasharray="3 3"/>`);
  rot.forEach((a,i)=>g.push(`<text x="${x(i)}" y="${H-8}" text-anchor="middle" font-size="10" fill="${css('--mut')}">${esc(a)}</text>`));
  series.forEach(s=>{let d='',on=false;
    s.vals.forEach((v,i)=>{if(v==null||isNaN(v)){on=false;return;} d+=(on?'L':'M')+x(i)+' '+y(v); on=true;});
    if(d) g.push(`<path d="${d}" fill="none" stroke="${s.cor}" stroke-width="2" stroke-linejoin="round"${s.tracejado?' stroke-dasharray="5 4"':''}/>`);
    s.vals.forEach((v,i)=>{if(v!=null&&!isNaN(v)) g.push(`<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="${s.cor}"><title>${esc(s.nome)} ${rot[i]}: ${(o.fmtD||o.fmtE||(v=>fmt(v,2)))(v)}</title></circle>`);});});
  /* rotulos por ultimo, para ficarem por cima das linhas. Series marcadas com
     semRotulo saem de fora - e o caso do "% da receita", que divide o eixo com o
     "% do market cap" e dobraria os numeros sobre a mesma regiao. */
  if(o.rotulos!==false){
    const rotula=criaRotulador(), f=o.fmtR||o.fmtD||o.fmtE||(v=>fmt(v,2));
    series.forEach(s=>{ if(s.semRotulo) return;
      s.vals.forEach((v,i)=>{ if(v!=null&&!isNaN(v)) rotula(g,x(i),y(v)-7,f(v),s.cor); });});
  }
  return `<svg viewBox="0 0 ${W} ${H}" role="img">${g.join('')}</svg>`;
}
/* barras agrupadas ou empilhadas */
function gBarras(rot,series,o={}){
  const W=880,H=o.alt||210,m={t:o.rotulos===false?14:24,r:16,b:o.b||26,l:o.l||66};
  const emp=!!o.empilhado, log=!!o.log;
  let pts;
  if(emp) pts=rot.map((_,i)=>series.reduce((s,x)=>s+(x.vals[i]||0),0));
  else pts=series.flatMap(s=>s.vals.filter(v=>v!=null&&(log?v>0:true)));
  pts=pts.filter(v=>v!=null&&!isNaN(v));
  if(!pts.length) return '<p class="mut">Sem dados suficientes.</p>';
  const hi=Math.max(...pts), lo=Math.min(...pts);
  const f=v=>log?Math.log10(Math.max(v,Math.max(lo,hi/1e6)/10)):v;
  const L1=log?Math.log10(hi)*1.02:Math.max(hi*1.1,0), L0=log?f(Math.max(lo,hi/1e6)/10):Math.min(lo*1.1,0);
  const bw=(W-m.l-m.r)/Math.max(1,rot.length);
  const sw=emp?Math.min(38,bw-10):Math.min(24,(bw-8)/series.length);
  const g=[]; eixoY(g,m,W,H,L0,L1,o.fmtE||(v=>curto(log?Math.pow(10,v):v).replace('R$ ','')),3);
  const y=v=>m.t+(L1-f(v))/((L1-L0)||1)*(H-m.t-m.b);
  // rotulos acumulados e desenhados depois das barras, com desvio de colisao
  const fmtR=o.fmtR||(v=>curto(v).replace('R$ ',''));
  const pend=[];
  rot.forEach((a,i)=>{
    if(emp){
      let acc=0; const x0=m.l+i*bw+(bw-sw)/2;
      series.forEach(s=>{const v=s.vals[i]; if(!v) return;
        const y1=y(acc+v), y0=y(acc);
        g.push(`<rect x="${x0}" y="${y1}" width="${sw}" height="${Math.max(1,y0-y1)}" fill="${s.cor}"><title>${esc(s.nome)} ${a}: ${curto(v)}</title></rect>`);
        acc+=v;});
      if(acc) pend.push([x0+sw/2, y(acc)-5, fmtR(acc), css('--mut')]);
    } else {
      const x0=m.l+i*bw+(bw-sw*series.length)/2;
      series.forEach((s,j)=>{const v=s.vals[i]; if(v==null||isNaN(v)||(log&&v<=0)) return;
        const yv=y(v), y0=y(0);
        g.push(`<rect x="${x0+j*sw}" y="${Math.min(yv,y0)}" width="${sw-2}" height="${Math.max(1,Math.abs(y0-yv))}" fill="${s.cor}" rx="2"><title>${esc(s.nome)} ${a}: ${(o.fmtD||curto)(v)}</title></rect>`);
        pend.push([x0+j*sw+(sw-2)/2, v>=0?Math.min(yv,y0)-5:Math.max(yv,y0)+11, fmtR(v), s.cor]);});
    }});
  if(o.rotulos!==false){
    const rotula=criaRotulador();
    pend.forEach(([px,py,txt,cor])=>rotula(g,px,py,txt,cor));
  }
  rotX(g,rot,m,W,H,bw,o.rotacao);
  return `<svg viewBox="0 0 ${W} ${H}" role="img">${g.join('')}</svg>`;
}
function mediana(a){if(!a.length)return null;const s=a.slice().sort((x,y)=>x-y),m=s.length>>1;
  return s.length%2?s[m]:(s[m-1]+s[m])/2;}

/* ---------------- visao do setor ---------------- */
const DIRETORIA='Diretoria Estatut\u00e1ria', CADM='Conselho de Administra\u00e7\u00e3o', CFISC='Conselho Fiscal';
const SOMA='__soma__';
const FILTRO_ORG=[[DIRETORIA,'Diretoria Estatutaria'],[CADM,'Conselho de Administracao'],
                  [CFISC,'Conselho Fiscal'],[SOMA,'Todos somados']];
const daSetor=s=> s==='Todos' ? DADOS : DADOS.filter(e=>e.setor===s);

/* exercicios de referencia deduzidos dos dados: o ultimo realizado e o previsto */
const EX_REF=Math.max(...DADOS.flatMap(e=>e.anos.filter(a=>!a.previsao).map(a=>a.ex)));
const EX_FUT=Math.max(...DADOS.flatMap(e=>e.anos.filter(a=>a.previsao).map(a=>a.ex)),EX_REF);

const celOrg=(e,org,ano)=>(e.serie[org]||{})[String(ano)]||null;
/* remuneracao do orgao filtrado; SOMA agrega os orgaos */
function remOrg(e,ano,org){
  org=org||st.orgSetor;
  if(org===SOMA){let t=null; e.orgaos.forEach(o=>{const c=celOrg(e,o,ano);
    if(c&&c.tot!=null) t=(t||0)+c.tot;}); return t;}
  const c=celOrg(e,org,ano); return c?c.tot:null;
}
/* somar maximas nao faz sentido: em SOMA vale a maior individual entre os orgaos */
function maxOrg(e,ano,org){
  org=org||st.orgSetor;
  if(org===SOMA){let t=null; e.orgaos.forEach(o=>{const c=celOrg(e,o,ano);
    if(c&&c.mx!=null) t=(t==null)?c.mx:Math.max(t,c.mx);}); return t;}
  const c=celOrg(e,org,ano); return c?c.mx:null;
}
const anoDe=(e,ano)=>e.anos.find(a=>a.ex===ano)||null;
const mcapDe=(e,ano)=>{const a=anoDe(e,ano); return a?a.mcap:null;};
const recDe=(e,ano)=>{const a=anoDe(e,ano); return a?a.receita:null;};
const pctDe=(v,base)=>(v!=null&&base)?100*v/base:null;

function anosSetor(es,campo){
  const S=new Set();
  es.forEach(e=>{const orgs=st.orgSetor===SOMA?e.orgaos:[st.orgSetor];
    orgs.forEach(o=>{const d=e.serie[o]||{};
      Object.keys(d).forEach(a=>{if(d[a][campo]!=null) S.add(+a);});});});
  return [...S].sort((a,b)=>a-b);
}
function tabelaAnos(es,anos,getter,fmtCel){
  if(!anos.length) return '<p class="mut">Sem dados.</p>';
  const linhas=es.map(e=>({e,vals:anos.map(a=>getter(e,a))}))
                 .filter(l=>l.vals.some(v=>v!=null));
  if(!linhas.length) return '<p class="mut">Sem dados.</p>';
  const ult=l=>{for(let i=l.vals.length-1;i>=0;i--) if(l.vals[i]!=null) return l.vals[i]; return 0;};
  linhas.sort((a,b)=>ult(b)-ult(a));
  const ord=anos.map((_,i)=>i).reverse();
  let h=`<div class="scroll"><table class="fix1"><thead><tr><th>Companhia</th>
    ${ord.map(i=>`<th>${anos[i]}</th>`).join('')}</tr></thead><tbody>`;
  linhas.forEach(({e,vals})=>{
    h+=`<tr class="clic" data-emp="${esc(e.id)}"><td>${esc(e.apelido)}`
      +(st.setor==='Todos'?` <span class="mut">${esc(e.setor)}</span>`:'')+`</td>`
      +ord.map(i=>`<td>${vals[i]==null?'\u2013':fmtCel(vals[i])}</td>`).join('')+`</tr>`;});
  h+=`<tr class="tot"><td>Mediana</td>${ord.map(i=>{
    const v=mediana(linhas.map(l=>l.vals[i]).filter(x=>x!=null));
    return `<td>${v==null?'\u2013':fmtCel(v)}</td>`;}).join('')}</tr>`;
  return h+`</tbody></table></div>`;
}

function vistaSetor(){
  const es=daSetor(st.setor);
  if(!es.length) return '<p class="mut">Sem companhias neste setor.</p>';
  const rotOrg=(FILTRO_ORG.find(x=>x[0]===st.orgSetor)||['','']) [1];
  const soma=st.orgSetor===SOMA;
  const colSetor=st.setor==='Todos';

  let h=`<div class="tabs mini">${FILTRO_ORG.map(([v,l])=>
    `<button class="tab tsorg" data-o="${esc(v)}" aria-selected="${v===st.orgSetor}">${esc(l)}</button>`).join('')}</div>`;

  const L=es.map(e=>{const rem=remOrg(e,EX_REF), mc=mcapDe(e,EX_REF), rc=recDe(e,EX_REF);
    return {e,rem,mc,rc,pmc:pctDe(rem,mc),prec:pctDe(rem,rc)};});
  const comDado=L.filter(x=>x.rem!=null);
  const F=es.map(e=>{const rem=remOrg(e,EX_FUT), mc=mcapDe(e,EX_FUT), base=remOrg(e,EX_REF);
      return {e,rem,mc,base,pmc:pctDe(rem,mc),varia:(rem!=null&&base)?100*(rem/base-1):null};})
    .filter(x=>x.rem!=null);
  h+=`<div class="kpis">
    ${kpi('Companhias',comDado.length+'/'+es.length,rotOrg+' em '+EX_REF)}
    ${kpi('Remuneracao somada',curto(comDado.reduce((s,x)=>s+(x.rem||0),0)),'exercicio '+EX_REF)}
    ${kpi('Mediana % market cap',pctMc(mediana(L.filter(x=>x.pmc!=null).map(x=>x.pmc))),'em '+EX_REF)}
    ${kpi('Mediana % receita',pct(mediana(L.filter(x=>x.prec!=null).map(x=>x.prec))),'em '+EX_REF)}
  </div>`;

  /* rankings */
  const TOPO=20;
  const optDe=d=>({log:false,rotacao:true,b:64,alt:250,l:52,
    fmtE:v=>fmt(v,d)+'%',fmtD:v=>pct(v,d),fmtR:v=>fmt(v,d)+'%'});
  const corte=(conj,rot,sub,cor,campo,d)=>{
    const opt=optDe(d);
    const a=conj.filter(x=>x[campo]!=null).sort((x,y)=>y[campo]-x[campo]);
    if(!a.length) return '';
    const vis=a.slice(0,TOPO);
    const nota=a.length>TOPO?`<p class="note">Mostrando as ${TOPO} maiores de ${a.length};
      as tabelas abaixo trazem todas.</p>`:'';
    return `<div class="card"><h2>${rot} <span class="mut">(${esc(rotOrg)}, ${sub})</span></h2>
      ${gBarras(vis.map(x=>x.e.apelido),[{nome:rot,cor:cor,vals:vis.map(x=>x[campo])}],opt)}${nota}</div>`;};
  h+=corte(L,'Remuneracao sobre market cap',EX_REF+' realizado',css('--ac2'),'pmc',2);
  h+=corte(F,'Remuneracao prevista sobre market cap',EX_FUT+' previsto',css('--ac4'),'pmc',2);
  if(F.length) h+=`<p class="note" style="margin:-8px 0 16px">A previsao costuma ficar
    acima do que se paga (o desvio mediano da carteira e de -6% contra o orcado), entao
    esta barra tende a encolher quando ${EX_FUT} for realizado.</p>`;
  /* % da receita so compara dentro do setor: a conta 3.01 de banco e receita de
     intermediacao financeira, nao receita de vendas. E so do exercicio realizado:
     a DFP de EX_FUT ainda nao existe, entao nao ha receita para o previsto. */
  if(!colSetor) h+=corte(L,'Remuneracao sobre receita',EX_REF+' realizado',css('--ac'),'prec',1);

  /* tabela 1: exercicio realizado */
  h+=`<div class="card"><h2>${esc(rotOrg)} em ${EX_REF} <span class="mut">(realizado)</span></h2>
    <div class="scroll"><table class="fix1"><thead><tr><th>Companhia</th>
    ${colSetor?'<th>Setor</th>':''}<th>Remuneracao</th><th>Receita</th><th>Market cap</th>
    <th>% receita</th><th>% mkt cap</th></tr></thead><tbody>`;
  comDado.slice().sort((a,b)=>(b.rem||0)-(a.rem||0)).forEach(x=>{
    h+=`<tr class="clic" data-emp="${esc(x.e.id)}"><td>${esc(x.e.apelido)}
      <span class="mut">${esc((x.e.tickers||'').replace(/[A-Z]+:/g,''))}</span></td>`
      +(colSetor?`<td>${esc(x.e.setor)}</td>`:'')
      +`<td>${curto(x.rem)}</td><td>${curto(x.rc)}</td><td>${curto(x.mc)}</td>
      <td>${pct(x.prec)}</td><td>${pctMc(x.pmc)}</td></tr>`;});
  h+=`<tr class="tot"><td>Mediana</td>${colSetor?'<td></td>':''}
    <td>${curto(mediana(comDado.map(x=>x.rem)))}</td>
    <td>${curto(mediana(comDado.map(x=>x.rc).filter(v=>v!=null)))}</td>
    <td>${curto(mediana(comDado.map(x=>x.mc).filter(v=>v!=null)))}</td>
    <td>${pct(mediana(L.filter(x=>x.prec!=null).map(x=>x.prec)))}</td>
    <td>${pctMc(mediana(L.filter(x=>x.pmc!=null).map(x=>x.pmc)))}</td></tr>
    </tbody></table></div></div>`;

  /* tabela 2: expectativa do exercicio seguinte */
  if(F.length){
    h+=`<div class="card"><h2>${esc(rotOrg)} em ${EX_FUT} <span class="mut">(previsto no FRE)</span></h2>
      <div class="scroll"><table class="fix1"><thead><tr><th>Companhia</th>
      ${colSetor?'<th>Setor</th>':''}<th>Remuneracao prevista</th><th>Market cap</th>
      <th>% mkt cap</th><th>vs ${EX_REF}</th></tr></thead><tbody>`;
    F.slice().sort((a,b)=>(b.rem||0)-(a.rem||0)).forEach(x=>{
      h+=`<tr class="clic" data-emp="${esc(x.e.id)}"><td>${esc(x.e.apelido)}
        <span class="mut">${esc((x.e.tickers||'').replace(/[A-Z]+:/g,''))}</span></td>`
        +(colSetor?`<td>${esc(x.e.setor)}</td>`:'')
        +`<td>${curto(x.rem)}</td><td>${curto(x.mc)}</td><td>${pctMc(x.pmc)}</td>
        <td class="${x.varia==null?'':(x.varia>0?'neg':'pos')}">${sinal(x.varia)}</td></tr>`;});
    h+=`<tr class="tot"><td>Mediana</td>${colSetor?'<td></td>':''}
      <td>${curto(mediana(F.map(x=>x.rem)))}</td>
      <td>${curto(mediana(F.map(x=>x.mc).filter(v=>v!=null)))}</td>
      <td>${pctMc(mediana(F.filter(x=>x.pmc!=null).map(x=>x.pmc)))}</td>
      <td>${sinal(mediana(F.filter(x=>x.varia!=null).map(x=>x.varia)))}</td></tr>
      </tbody></table></div>
      <p class="note">O market cap de ${EX_FUT} usa a cotacao mais recente disponivel.
      A ultima coluna compara a previsao com o realizado de ${EX_REF}.</p></div>`;
  }

  /* series historicas no orgao filtrado */
  const anosTot=anosSetor(es,'tot');
  if(anosTot.length) h+=`<div class="card"><h2>${esc(rotOrg)} \u2013 remuneracao total por ano</h2>
    ${tabelaAnos(es,anosTot,(e,a)=>remOrg(e,a),v=>curto(v))}</div>`;

  const anosMx=anosSetor(es,'mx');
  if(anosMx.length) h+=`<div class="card"><h2>${esc(rotOrg)} \u2013 maxima remuneracao individual por ano
    <span class="mut">(item 8.16)</span></h2>
    ${tabelaAnos(es,anosMx,(e,a)=>maxOrg(e,a),v=>curto(v))}
    ${soma?'<p class="note">Com os orgaos somados esta tabela traz a maior remuneracao individual entre eles \u2013 somar maximas nao teria sentido.</p>':''}</div>`;
  return h;
}

/* ---------------- abas da companhia ---------------- */
const ABAS=[['geral','Visao geral'],['tipo','Por tipo de remuneracao'],
            ['orgao','Por orgao'],['prev','Previsto x realizado'],['q82','Quadro 8.2 detalhado']];

function seletorOrgao(e){
  const opts=[['__todos__','Todos os orgaos'],...e.orgaos.map(o=>[o,ab(o)])];
  return `<div class="tabs mini">${opts.map(([v,l])=>
    `<button class="tab torg" data-o="${esc(v)}" aria-selected="${v===st.org}">${esc(l)}</button>`).join('')}</div>`;
}

function abaGeral(e){
  const A=e.anos, rot=A.map(a=>a.ex);
  const S=[{nome:'% da receita',cor:css('--ac'),vals:A.map(a=>a.p_rec),semRotulo:true},
           {nome:'% do market cap',cor:css('--ac2'),vals:A.map(a=>a.p_mc)}];
  let h=`<div class="card"><h2>Remuneracao como % da receita e do market cap
    <span class="mut">(valores no grafico: % do market cap)</span></h2>
    ${gLinhas(rot,S,{fmtE:v=>fmt(v,2)+'%',fmtD:v=>pctMc(v),fmtR:v=>pctMc(v)})}${legenda(S)}</div>`;

  /* crescimento ano contra ano - tabela, para ler o numero direto */
  const yoy=(f)=>A.map((a,i)=>{const p=A[i-1]; const x=f(a), y=p?f(p):null;
    return (x!=null&&y)?100*(x/y-1):null;});
  const yr=yoy(a=>a.rem), yc=yoy(a=>a.receita), ym=yoy(a=>a.mcap);
  const idx=A.map((a,i)=>i).reverse();
  h+=`<div class="card"><h2>Crescimento ano contra ano</h2><div class="scroll"><table class="fix1">
    <thead><tr><th>Indicador</th>${idx.map(i=>`<th>${A[i].ex}${A[i].previsao?' <span class="prev">p</span>':''}</th>`).join('')}</tr></thead><tbody>`;
  [['Remuneracao',yr],['Receita',yc],['Market cap',ym],
   ['Remun. menos receita (p.p.)',A.map((a,i)=>(yr[i]!=null&&yc[i]!=null)?yr[i]-yc[i]:null)]
  ].forEach(([rotulo,serie],k)=>{
    h+=`<tr${k===3?' class="tot"':''}><td>${rotulo}</td>${idx.map(i=>{
      const v=serie[i];
      return `<td class="${v==null?'':(v>0?'neg':'pos')}">${v==null?'–':(k===3?(v>0?'+':'')+fmt(v,1):sinal(v))}</td>`;}).join('')}</tr>`;});
  h+=`</tbody></table></div>
    <p class="note">A ultima linha e a diferenca em pontos percentuais entre o crescimento
    da remuneracao e o da receita: positivo (vermelho) = a remuneracao cresceu mais rapido
    que o negocio naquele ano.</p></div>`;

  h+=`<div class="card"><h2>Serie anual</h2><div class="scroll"><table class="fix1"><thead><tr>
    <th>Exerc.</th><th>Remuneracao</th><th>YoY</th><th>Receita</th><th>YoY</th>
    <th>Market cap</th><th>YoY</th><th>Acoes ex-tes.</th><th>Preco medio</th>
    <th>% receita</th><th>% mkt cap</th></tr></thead><tbody>`;
  A.map((a,i)=>[a,i]).reverse().forEach(([a,i])=>{
    const cl=v=>v==null?'':(v>0?'neg':'pos');
    h+=`<tr><td>${a.ex}${a.previsao?' <span class="prev">prev.</span>':''}</td>
      <td>${curto(a.rem)}</td><td class="${cl(yr[i])}">${sinal(yr[i])}</td>
      <td>${curto(a.receita)}</td><td>${sinal(yc[i])}</td>
      <td>${curto(a.mcap)}</td><td>${sinal(ym[i])}</td>
      <td>${a.acoes?fmt(a.acoes,0):'–'}</td><td title="${esc(a.precos||'')}">${a.preco?fmt(a.preco,2):'–'}</td>
      <td>${pct(a.p_rec)}</td><td>${pctMc(a.p_mc)}</td></tr>`;});
  return h+`</tbody></table></div></div>`;
}

function abaTipo(e){
  const anos=anosDe(e,st.org), rot=anos.map(String);
  const cores={fixa:css('--ac'),variavel:css('--ac3'),outros:css('--ac4')};
  const S=GRUPOS.map(([g,titulo])=>({nome:titulo,cor:cores[g],
    vals:anos.map(a=>grupoVal(e,st.org,a,g))}));
  let h=seletorOrgao(e);
  h+=`<div class="card"><h2>Composicao da remuneracao por natureza <span class="mut">(empilhado)</span></h2>
    ${gBarras(rot,S,{empilhado:true,alt:230})}${legenda(S)}</div>`;

  /* evolucao verba a verba */
  const anosR=anos.slice().reverse();
  h+=`<div class="card"><h2>Evolucao verba a verba</h2><div class="scroll"><table class="fix1"><thead><tr>
    <th>Verba</th>${anosR.map(a=>`<th>${a}</th>`).join('')}</tr></thead><tbody>`;
  GRUPOS.forEach(([g,titulo])=>{
    const ids=idxGrupo(g);
    if(!ids.some(i=>anos.some(a=>val(e,st.org,a,c=>c.v?c.v[i]:null)))) return;
    h+=`<tr class="grp"><td colspan="${anosR.length+1}">${esc(titulo)}</td></tr>`;
    ids.forEach(i=>{
      const vs=anosR.map(a=>val(e,st.org,a,c=>c.v?c.v[i]:null));
      if(!vs.some(v=>v)) return;
      h+=`<tr><td>${esc(CAMPOS[i][0])}</td>${vs.map(v=>`<td>${curto(v)}</td>`).join('')}</tr>`;});
    h+=`<tr class="tot"><td>Subtotal ${esc(titulo.toLowerCase())}</td>${anosR.map(a=>`<td>${curto(grupoVal(e,st.org,a,g))}</td>`).join('')}</tr>`;});
  h+=`<tr class="tot"><td>Total</td>${anosR.map(a=>`<td>${curto(val(e,st.org,a,c=>c.tot))}</td>`).join('')}</tr>`;
  return h+`</tbody></table></div></div>`;
}

function abaOrgao(e){
  let h='';
  /* remuneracao total por orgao ao longo do tempo */
  const anos=anosDe(e,'__todos__'), rot=anos.map(String);
  const cores=[css('--ac'),css('--ac2'),css('--ac3'),css('--ac4'),css('--ac5')];
  const T=e.orgaos.map((o,i)=>({nome:ab(o),cor:cores[i%cores.length],
    vals:anos.map(a=>val(e,o,a,c=>c.tot))}));
  h+=`<div class="card"><h2>Remuneracao total por orgao</h2>${gBarras(rot,T,{alt:220})}${legenda(T)}</div>`;

  /* numero de membros */
  const M=e.orgaos.map((o,i)=>({nome:ab(o),cor:cores[i%cores.length],
    vals:anos.map(a=>val(e,o,a,c=>c.nm))}));
  h+=`<div class="card"><h2>Numero de membros por orgao</h2>
    ${gLinhas(rot,M,{fmtE:v=>fmt(v,1),fmtD:v=>fmt(v,2)+' membros'})}${legenda(M)}</div>`;

  /* max / media / min por orgao */
  e.orgaos.forEach(o=>{
    const an=Object.keys(e.serie[o]).map(Number).sort((a,b)=>a-b);
    const S=[{nome:'Maxima',cor:css('--ac3'),vals:an.map(a=>(e.serie[o][a]||{}).mx)},
             {nome:'Media',cor:css('--ac'),vals:an.map(a=>(e.serie[o][a]||{}).md)},
             {nome:'Minima',cor:css('--ac2'),vals:an.map(a=>(e.serie[o][a]||{}).mn)}];
    if(!S.some(s=>s.vals.some(v=>v))) return;
    h+=`<div class="card"><h2>${esc(o)} – remuneracao individual <span class="mut">(item 8.16)</span></h2>
      ${gLinhas(an.map(String),S,{fmtE:v=>curto(v).replace('R$ ','')})}${legenda(S)}
      <div class="scroll"><table class="fix1" style="margin-top:12px"><thead><tr><th>Exerc.</th>
      <th>Maxima</th><th>Media</th><th>Minima</th><th>Max/Min</th><th>N&ordm; membros</th>
      <th>Total do orgao</th></tr></thead><tbody>`;
    an.slice().reverse().forEach(a=>{const c=e.serie[o][a]||{};
      const raz=(c.mx&&c.mn)?c.mx/c.mn:null;
      h+=`<tr><td>${a}</td><td>${curto(c.mx)}</td><td>${curto(c.md)}</td><td>${curto(c.mn)}</td>
        <td>${raz?fmt(raz,1)+'x':'–'}</td><td>${c.nm!=null?fmt(c.nm,2):'–'}</td>
        <td>${curto(c.tot)}</td></tr>`;});
    h+=`</tbody></table></div>`;
    const al=[...new Set(an.map(a=>(e.serie[o][a]||{}).al16).filter(Boolean))];
    al.forEach(t=>h+=`<div class="warn">${esc(t)}</div>`);
    h+=`</div>`;});
  return h;
}

function abaPrev(e){
  let h=seletorOrgao(e);
  const anos=anosDe(e,st.org), rot=anos.map(String);
  const P=[{nome:'Previsto no FRE do proprio ano',cor:css('--ac4'),vals:anos.map(a=>val(e,st.org,a,c=>c.pt))},
           {nome:'Realizado',cor:css('--ac3'),vals:anos.map(a=>val(e,st.org,a,c=>c.rt))}];
  h+=`<div class="card"><h2>Remuneracao total: previsto x realizado</h2>
    ${gBarras(rot,P,{alt:220})}${legenda(P)}<div class="scroll"><table class="fix1" style="margin-top:12px">
    <thead><tr><th>Exerc.</th><th>Previsto</th><th>Realizado</th><th>Desvio</th><th>Desvio %</th>
    <th>Previsto / membro</th><th>Realizado / membro</th><th>Desvio %</th></tr></thead><tbody>`;
  anos.slice().reverse().forEach(a=>{
    const p=val(e,st.org,a,c=>c.pt), r=val(e,st.org,a,c=>c.rt);
    if(p==null&&r==null) return;
    const pn=val(e,st.org,a,c=>c.pnm), rn=val(e,st.org,a,c=>c.rnm);
    const pm=(p&&pn)?p/pn:null, rm=(r&&rn)?r/rn:null;
    const d=(p!=null&&r!=null)?r-p:null, dp=(d!=null&&p)?100*d/p:null;
    const dm=(pm&&rm)?100*(rm/pm-1):null;
    const cl=v=>v==null?'':(v>0?'neg':'pos');
    h+=`<tr><td>${a}${r==null?' <span class="prev">previsao</span>':''}</td>
      <td>${curto(p)}</td><td>${curto(r)}</td>
      <td class="${cl(dp)}">${d==null?'–':(d>0?'+':'')+curto(d)}</td>
      <td class="${cl(dp)}">${sinal(dp)}</td>
      <td>${curto(pm)}</td><td>${curto(rm)}</td>
      <td class="${cl(dm)}">${sinal(dm)}</td></tr>`;});
  h+=`</tbody></table></div>
    <p class="note"><b>Previsto</b> = quadro 8.2 do FRE entregue no proprio exercicio.
    <b>Realizado</b> = mesmo quadro nos FREs seguintes. As colunas por membro separam
    o que foi desvio de valor do que foi apenas orgao maior ou menor que o planejado.
    Desvio positivo (vermelho) = pagou acima do orcado.</p></div>`;

  /* custo por membro: previsto x realizado */
  const M=[{nome:'Previsto por membro',cor:css('--ac4'),tracejado:true,
            vals:anos.map(a=>{const p=val(e,st.org,a,c=>c.pt),n=val(e,st.org,a,c=>c.pnm);return (p&&n)?p/n:null;})},
           {nome:'Realizado por membro',cor:css('--ac3'),
            vals:anos.map(a=>{const r=val(e,st.org,a,c=>c.rt),n=val(e,st.org,a,c=>c.rnm);return (r&&n)?r/n:null;})}];
  if(M.some(s=>s.vals.some(v=>v)))
    h+=`<div class="card"><h2>Custo medio por membro: previsto x realizado</h2>
      ${gLinhas(rot,M,{fmtE:v=>curto(v).replace('R$ ','')})}${legenda(M)}</div>`;

  /* desvio por orgao */
  if(st.org==='__todos__'&&e.orgaos.length>1){
    const cores=[css('--ac'),css('--ac2'),css('--ac3'),css('--ac4'),css('--ac5')];
    const S=e.orgaos.map((o,i)=>({nome:ab(o),cor:cores[i%cores.length],
      vals:anos.map(a=>{const c=(e.serie[o]||{})[String(a)]||{};
        return (c.pt&&c.rt!=null)?100*(c.rt/c.pt-1):null;})}));
    h+=`<div class="card"><h2>Desvio por orgao <span class="mut">(realizado vs previsto)</span></h2>
      ${gLinhas(rot,S,{zero:false,fmtE:v=>fmt(v,0)+'%',fmtD:v=>sinal(v)})}${legenda(S)}
      <div class="scroll"><table class="fix1" style="margin-top:12px"><thead><tr><th>Orgao</th>
      ${anos.slice().reverse().map(a=>`<th>${a}</th>`).join('')}</tr></thead><tbody>`;
    e.orgaos.forEach(o=>{
      h+=`<tr><td>${esc(ab(o))}</td>${anos.slice().reverse().map(a=>{
        const c=(e.serie[o]||{})[String(a)]||{};
        const d=(c.pt&&c.rt!=null)?100*(c.rt/c.pt-1):null;
        return `<td class="${d==null?'':(d>0?'neg':'pos')}">${sinal(d)}</td>`;}).join('')}</tr>`;});
    h+=`</tbody></table></div></div>`;
  }

  const cores=[css('--ac'),css('--ac2'),css('--ac3'),css('--ac4'),css('--ac5')];
  const X=e.orgaos.map((o,i)=>({nome:ab(o),cor:cores[i%cores.length],
    vals:anos.map(a=>((e.serie[o]||{})[String(a)]||{}).mx)}));
  if(X.some(s=>s.vals.some(v=>v)))
    h+=`<div class="card"><h2>Maxima individual realizada <span class="mut">(item 8.16)</span></h2>
      ${gLinhas(rot,X,{fmtE:v=>curto(v).replace('R$ ','')})}${legenda(X)}
      <p class="note">O quadro 8.16 nao traz estimativa: a CVM so pede maxima, media e
      minima de exercicios ja encerrados, entao nao existe "maxima prevista" para
      confrontar. O teto estimado tambem nao e publicado - o dado aberto traz apenas a
      versao corrente de cada FRE, sem o historico de revisoes da previsao.</p></div>`;
  return h;
}

function abaQ82(e){
  const exs=Object.keys(e.serie[e.orgaos[0]]||{}).sort((a,b)=>b-a);
  const todos=[...new Set(e.orgaos.flatMap(o=>Object.keys(e.serie[o])))].sort((a,b)=>b-a);
  const sel=todos.includes(st.ex)?st.ex:todos[0];
  let h=`<div class="tabs mini">${todos.map(x=>`<button class="tab tex" data-ex="${x}" aria-selected="${x===sel}">${x}</button>`).join('')}</div>`;
  if(!sel) return h+'<p class="mut">Sem dados.</p>';
  const orgs=e.orgaos.filter(o=>e.serie[o][sel]);
  h+=`<div class="card"><div class="scroll"><table class="fix1"><thead><tr><th>Verba</th>
    ${orgs.map(o=>`<th>${esc(o)}</th>`).join('')}<th>Total</th></tr></thead><tbody>`;
  const lin=(rot,f,cls='')=>{const vs=orgs.map(o=>f(e.serie[o][sel]));
    const t=vs.reduce((s,v)=>s+(v||0),0);
    return `<tr class="${cls}"><td>${esc(rot)}</td>${vs.map(v=>`<td>${curto(v)}</td>`).join('')}<td>${curto(t)}</td></tr>`;};
  [['N&ordm; de membros','nm'],['N&ordm; remunerados','nr']].forEach(([r,k])=>{
    const vs=orgs.map(o=>e.serie[o][sel][k]);
    h+=`<tr><td>${r}</td>${vs.map(v=>`<td>${v!=null?fmt(v,2):'–'}</td>`).join('')}<td>${fmt(vs.reduce((s,v)=>s+(v||0),0),2)}</td></tr>`;});
  GRUPOS.forEach(([g,titulo])=>{
    const ids=idxGrupo(g);
    if(!ids.some(i=>orgs.some(o=>(e.serie[o][sel].v||[])[i]))) return;
    h+=`<tr class="grp"><td colspan="${orgs.length+2}">${esc(titulo)}</td></tr>`;
    ids.forEach(i=>{h+=lin(CAMPOS[i][0],c=>(c.v||[])[i]);});});
  h+=lin('Total da remuneracao',c=>c.tot,'tot')+`</tbody></table></div>`;
  orgs.forEach(o=>{const c=e.serie[o][sel];
    if(c.al) h+=`<div class="warn">${esc(o)}: ${esc(c.al)}</div>`;});
  [...new Set(orgs.map(o=>e.serie[o][sel].obs).filter(Boolean))].forEach(t=>{
    h+=`<p class="note"><b>Observacao da companhia:</b> ${esc(t)}</p>`;});
  return h+`</div>`;
}

function vistaEmpresa(){
  const e=DADOS.find(d=>d.id===st.empresa);
  if(!e) return vistaSetor();
  const u=ultimo(e);
  let h=`<button class="back" id="volta">&larr; ${esc(st.setor)}</button>
    <h2 style="font-size:18px">${esc(e.apelido)} <span class="mut" style="font-weight:400">
    ${esc(e.empresa)} · ${esc(e.cnpj)}${e.tickers?' · '+esc(e.tickers):''}</span></h2>
    <div class="kpis">
      ${kpi('Remuneracao total',curto(u.rem),'exercicio '+(u.ex||'–'))}
      ${kpi('Receita liquida',curto(u.receita),u.receita?'DFP conta 3.01':'sem DFP')}
      ${kpi('Market cap',curto(u.mcap),u.acoes?fmt(u.acoes,0)+' acoes ex-tes.':'–')}
      ${kpi('Remun. / receita',pct(u.p_rec),'')}
      ${kpi('Remun. / market cap',pctMc(u.p_mc),'')}
    </div>`;
  if(u.alerta) h+=`<div class="warn">${esc(u.alerta)}</div>`;
  h+=`<div class="tabs sub2">${ABAS.map(([k,l])=>
    `<button class="tab taba" data-a="${k}" aria-selected="${k===st.aba}">${l}</button>`).join('')}</div>`;
  const f={geral:abaGeral,tipo:abaTipo,orgao:abaOrgao,prev:abaPrev,q82:abaQ82}[st.aba]||abaGeral;
  return h+f(e);
}

/* ---------------- navegacao lateral ---------------- */
function renderLista(){
  const alvo=$('#listaEmp'); if(!alvo) return;
  const q=norm(st.busca);
  const setores=[...new Set(DADOS.map(e=>e.setor))].sort();
  let h='', achou=0;
  setores.forEach(sec=>{
    const es=DADOS.filter(e=>e.setor===sec &&
      (!q || norm(e.apelido).includes(q) || norm(e.empresa).includes(q) || norm(e.tickers||'').includes(q)));
    if(!es.length) return;
    achou+=es.length;
    h+=`<button class="lbl lsec" data-s="${esc(sec)}" aria-selected="${!st.empresa&&st.setor===sec}"
      title="Abrir a visao do setor">${esc(sec)}</button>`;
    es.sort((a,b)=>a.apelido.localeCompare(b.apelido,'pt-BR')).forEach(e=>{
      h+=`<button class="emp lemp" data-emp="${esc(e.id)}" aria-selected="${st.empresa===e.id}"
        title="${esc(e.empresa)}">${esc(e.apelido)}</button>`;});
  });
  alvo.innerHTML = achou ? h : '<p class="vazio">Nenhuma companhia com esse termo.</p>';
  alvo.querySelectorAll('.lsec').forEach(b=>b.onclick=()=>{
    st.setor=b.dataset.s; st.empresa=null; st.ex=null; st.aba='geral'; st.org='__todos__';
    render(); scrollTo(0,0);});
  alvo.querySelectorAll('.lemp').forEach(b=>b.onclick=()=>{
    const e=DADOS.find(x=>x.id===b.dataset.emp);
    if(e) st.setor=e.setor;              // o "voltar" cai no setor certo
    st.empresa=b.dataset.emp; st.ex=null; st.aba='geral'; st.org='__todos__';
    render(); scrollTo(0,0);});
}

function render(){
  $('#abas').innerHTML=SETORES.map(s=>
    `<button class="tab tset" data-s="${esc(s)}" aria-selected="${s===st.setor}">${esc(s)}</button>`).join('');
  $('#out').innerHTML=st.empresa?vistaEmpresa():vistaSetor();
  document.querySelectorAll('.tset').forEach(b=>b.onclick=()=>{st.setor=b.dataset.s;st.empresa=null;st.ex=null;st.aba='geral';st.org='__todos__';render();});
  document.querySelectorAll('.tsorg').forEach(b=>b.onclick=()=>{st.orgSetor=b.dataset.o;render();});
  renderLista();
  document.querySelectorAll('tr.clic').forEach(t=>t.onclick=()=>{st.empresa=t.dataset.emp;st.ex=null;st.aba='geral';st.org='__todos__';render();scrollTo(0,0);});
  document.querySelectorAll('.taba').forEach(b=>b.onclick=()=>{st.aba=b.dataset.a;render();});
  document.querySelectorAll('.torg').forEach(b=>b.onclick=()=>{st.org=b.dataset.o;render();});
  document.querySelectorAll('.tex').forEach(b=>b.onclick=()=>{st.ex=b.dataset.ex;render();});
  const v=$('#volta'); if(v) v.onclick=()=>{st.empresa=null;render();};
}
const busca=$('#busca');
if(busca) busca.oninput=()=>{st.busca=busca.value; renderLista();};
render();
"""


def gerar(caminho, linhas_mercado, q82, mmm, prev_real=(), prev_real_ind=(),
          q82_por_fre=(), titulo="Monitoramento de remuneracao"):
    dados = _serie(linhas_mercado, q82, mmm, list(prev_real), list(prev_real_ind))
    setores = ["Todos"] + sorted({e["setor"] for e in dados})
    campos = [[rot, campo, grupo] for rot, campo, grupo in CAMPOS]
    grupos = [[g, t] for g, t in GRUPOS_82]
    js = (JS.replace("__DADOS__", json.dumps(dados, ensure_ascii=False, default=float))
            .replace("__CAMPOS__", json.dumps(campos, ensure_ascii=False))
            .replace("__GRUPOS__", json.dumps(grupos, ensure_ascii=False))
            .replace("__SETORES__", json.dumps(setores, ensure_ascii=False)))
    ger = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    doc = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title><style>{CSS}</style></head><body>
<div class="wrap">
  <h1>{html.escape(titulo)}</h1>
  <p class="sub">Remuneracao de administradores (FRE, itens 8.2 e 8.16) confrontada com
  receita liquida (DFP, conta 3.01) e market cap (acoes ex-tesouraria x cotacao).
  {len(dados)} companhias em {len(setores)} setores. Gerado em {ger}.</p>
  <div class="tabs" id="abas"></div>
  <div class="layout">
    <aside class="side">
      <input id="busca" type="search" placeholder="Buscar companhia ou ticker"
             aria-label="Buscar companhia">
      <div class="cnt">{len(dados)} companhias</div>
      <div id="listaEmp"></div>
    </aside>
    <div id="out"></div>
  </div>
  <p class="note">
  <b>Como ler.</b> Market cap = acoes integralizadas menos acoes em tesouraria (DFP,
  composicao de capital do encerramento do exercicio) vezes a cotacao do ultimo pregao
  daquele exercicio; cotacoes historicas sao desajustadas de desdobramentos para casarem
  com a quantidade de acoes da epoca. <b>% da receita so compara dentro do mesmo setor</b>
  – a conta 3.01 de banco e receita de intermediacao financeira, nao receita de vendas.
  Exercicios marcados <span class="prev">prev.</span> sao previsao de remuneracao ainda
  nao realizada. Companhias listadas apenas no exterior nao constam: nao entregam FRE.
  </p>
</div>
<script>{js}</script></body></html>"""
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return caminho
