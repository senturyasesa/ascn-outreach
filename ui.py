#!/usr/bin/env python3
"""
ui.py — вся вёрстка дашборда. Дизайн-система ASCN: светлая тема, Geist,
зелёный акцент #27CC2E, скругления 8/16, мягкие тени.

Токены названы так же, как в дизайн-системе сайта (assets/css/variables),
чтобы правки палитры переносились один в один.

Экранов два:
  MAIN_TPL      — «Рассылка»: статистика, отправка пачки, таблица лидов с правкой
  SETTINGS_TPL  — «Настройки»: аккаунты, api-ключи, журнал отправок
плюс ONBOARD_TPL (первый запуск) и CODE_TPL (ввод кода при логине).
"""

# ─── токены + базовые стили ────────────────────────────────────────────
CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    /* цвета — из дизайн-системы ASCN */
    --color-black:#242D35; --color-white:#fff;
    --color-grey-100:#F6F6F6; --color-grey-200:#F9F9F9; --color-grey-300:#EEE;
    --color-grey-400:#E1DFDD; --color-grey-500:#959595; --color-grey-600:#535353;
    --color-accent:#27CC2E; --color-accent-100:#D8ECD9; --color-accent-200:#BBF7BE;
    --color-accent-400:#4ADE51; --color-accent-700:#1A871F;
    --color-text:var(--color-black); --color-text-light:#4f5b67; --color-text-lighter:#77818a;
    --color-red:#EB5757; --color-red-bg:#ffdbdc;
    --color-orange:#E19639; --color-orange-light:#FBF0E3;
    --color-green-bg:#EFFAF2;
    /* шкалы */
    --fs-xs:12px; --fs-sm:13px; --fs-base:14px; --fs-lg:16px;
    --fw-normal:400; --fw-medium:500; --fw-semibold:600;
    --radius-xs:4px; --radius-sm:8px; --radius:16px; --radius-full:999px;
    --shadow-100:0 4px 40px 0 rgba(0,0,0,.04);
    --field-bg:var(--color-grey-100);
  }
  *{box-sizing:border-box}
  body{margin:0;padding:40px 24px 64px;background:var(--color-grey-200);color:var(--color-text);
       font-family:'Geist',-apple-system,'Segoe UI',Roboto,sans-serif;font-size:var(--fs-base);
       font-weight:var(--fw-normal);line-height:1.5;-webkit-font-smoothing:antialiased}
  .wrap{max-width:980px;margin:0 auto}
  a{color:var(--color-accent-700);text-decoration:none}
  a:hover{text-decoration:underline}

  /* header */
  header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:8px}
  .brand{font-size:20px;font-weight:var(--fw-semibold);letter-spacing:-.01em}
  .brand b{color:var(--color-accent);font-weight:var(--fw-semibold)}
  .top-link{display:inline-flex;align-items:center;gap:6px;font-size:var(--fs-sm);
            color:var(--color-text-light);padding:8px 14px;border-radius:var(--radius-sm);
            background:var(--color-white);border:1px solid var(--color-grey-300)}
  .top-link:hover{text-decoration:none;border-color:var(--color-grey-400);color:var(--color-text)}

  /* плитки статистики — читаются с одного взгляда */
  .tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
  .tile{background:var(--color-white);border:1px solid var(--color-grey-300);
        border-radius:var(--radius);box-shadow:var(--shadow-100);padding:16px 18px}
  .tile .n{font-size:26px;font-weight:var(--fw-semibold);line-height:1.1;letter-spacing:-.02em}
  .tile .l{font-size:var(--fs-sm);color:var(--color-text-lighter);margin-top:2px}
  .tile.ok .n{color:var(--color-accent-700)}
  .tile.ans .n{color:var(--color-accent)}
  .tile.mut .n{color:var(--color-text-ex-light)}
  .tile .pct{color:var(--color-accent);font-weight:var(--fw-medium)}

  /* фильтры и инструменты в шапке таблицы */
  .tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .pill{font-size:var(--fs-sm);padding:6px 12px;border-radius:var(--radius-full);
        color:var(--color-text-light);background:var(--color-grey-100);border:1px solid transparent}
  .pill:hover{text-decoration:none;border-color:var(--color-grey-400)}
  .pill.on{background:var(--color-accent-100);border-color:var(--color-accent);
           color:var(--color-accent-700);font-weight:var(--fw-medium)}
  .count{font-size:var(--fs-sm);color:var(--color-text-lighter);font-weight:var(--fw-normal)}
  .th-hint{font-weight:var(--fw-normal);color:var(--color-text-ex-light)}

  /* «Добавить контакты» больше не занимает пол-экрана */
  details.add{margin-bottom:16px;border:1px dashed var(--color-grey-400);
              border-radius:var(--radius-sm);padding:10px 14px}
  details.add summary{cursor:pointer;font-size:var(--fs-sm);color:var(--color-accent-700);
                      font-weight:var(--fw-medium);list-style:none}
  details.add summary::-webkit-details-marker{display:none}
  details.add[open]{padding-bottom:14px}
  details.add[open] summary{margin-bottom:12px}
  .row-end{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:10px}

  /* кнопка отправки всегда рядом с фразой */
  .btn-go{margin-left:6px}

  /* панель сохранения липнет к низу — правку сверху не надо искать глазами */
  .savebar{position:sticky;bottom:0;display:flex;align-items:center;justify-content:space-between;
           gap:12px;background:var(--color-white);border-top:1px solid var(--color-grey-300);
           padding:14px 0 2px;margin-top:8px}
  .savebar.hot{border-top-color:var(--color-accent)}
  .savebar.hot .note{color:var(--color-accent-700);font-weight:var(--fw-medium)}

  /* карточки */
  .card{background:var(--color-white);border:1px solid var(--color-grey-300);
        border-radius:var(--radius);box-shadow:var(--shadow-100);padding:24px;margin-bottom:20px}
  .card-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}
  .card-head h2{margin:0;font-size:var(--fs-lg);font-weight:var(--fw-medium)}
  .card-head .note{font-size:var(--fs-sm);color:var(--color-text-lighter)}
  h1.page{margin:0 0 4px;font-size:24px;font-weight:var(--fw-semibold)}
  .lead{margin:0 0 24px;color:var(--color-text-light);font-size:var(--fs-sm)}

  /* «предложение» — форма, которая читается фразой */
  .sentence{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:var(--fs-lg);
            line-height:2.2}
  .sentence .txt{color:var(--color-text-light)}
  input,textarea,select{font-family:inherit;font-size:var(--fs-base);color:var(--color-text);
        background:var(--field-bg);border:1px solid var(--color-grey-300);
        border-radius:var(--radius-sm);padding:8px 12px}
  input:focus,textarea:focus{outline:none;border-color:var(--color-accent);background:var(--color-white)}
  input.num{width:70px;text-align:center;font-weight:var(--fw-medium)}
  label.field{display:block;font-size:var(--fs-sm);color:var(--color-text-light);margin-bottom:6px}

  /* чипы аккаунтов */
  .chips{display:inline-flex;flex-wrap:wrap;gap:8px;vertical-align:middle}
  .chip{display:inline-flex;align-items:center;gap:7px;padding:6px 14px;font-size:var(--fs-base);
        background:var(--color-white);border:1px solid var(--color-grey-400);
        border-radius:var(--radius-full);cursor:pointer;user-select:none}
  .chip:hover{border-color:var(--color-accent-400)}
  .chip:has(input:checked){background:var(--color-accent-100);border-color:var(--color-accent);
        color:var(--color-accent-700);font-weight:var(--fw-medium)}
  .chip input{width:auto;margin:0;accent-color:var(--color-accent)}

  /* кнопки */
  button{font-family:inherit;font-size:var(--fs-base);font-weight:var(--fw-medium);
         border-radius:var(--radius-sm);padding:10px 20px;cursor:pointer;border:1px solid transparent}
  .btn{background:var(--color-accent);color:var(--color-white)}
  .btn:hover{background:var(--color-accent-400)}
  .btn:disabled{background:var(--color-grey-300);color:var(--color-text-lighter);cursor:not-allowed}
  .btn-ghost{background:var(--color-white);border-color:var(--color-grey-400);color:var(--color-text-light)}
  .btn-ghost:hover{border-color:var(--color-grey-500);color:var(--color-text)}
  .btn-danger{background:var(--color-white);border-color:var(--color-red-bg);color:var(--color-red)}
  .btn-danger:hover{background:var(--color-red-bg)}
  .btn-sm{padding:6px 12px;font-size:var(--fs-sm)}
  .btn-x{background:none;border:0;color:var(--color-grey-500);font-size:var(--fs-lg);
         padding:4px 8px;line-height:1}
  .btn-x:hover{color:var(--color-red)}

  /* подсказки, баннеры, флеш */
  .hint{font-size:var(--fs-sm);color:var(--color-text-lighter);margin-top:12px}
  .flash{background:var(--color-grey-100);border-left:3px solid var(--color-accent);
         border-radius:var(--radius-sm);padding:12px 16px;margin-bottom:16px;font-size:var(--fs-sm)}
  .banner{display:flex;align-items:center;justify-content:space-between;gap:16px;
          background:var(--color-accent-100);border-radius:var(--radius);padding:16px 24px;
          margin-bottom:20px;font-size:var(--fs-base);font-weight:var(--fw-medium)}
  .empty{background:var(--color-grey-100);border-radius:var(--radius-sm);padding:20px;
         font-size:var(--fs-base);color:var(--color-text-light);text-align:center}

  /* таблицы */
  table{width:100%;border-collapse:collapse}
  th{text-align:left;font-size:var(--fs-sm);font-weight:var(--fw-medium);
     color:var(--color-text-lighter);padding:0 12px 10px;border-bottom:1px solid var(--color-grey-300)}
  td{padding:12px;border-bottom:1px solid var(--color-grey-100);vertical-align:top}
  tr:last-child td{border-bottom:0}
  .nick{font-weight:var(--fw-medium);white-space:nowrap}
  /* поля видно, что они поля: светлый фон, а не невидимая рамка */
  table.leads td{padding:10px 12px}
  .nick{width:180px}
  .nick input{display:block;width:100%;padding:5px 8px;font-weight:var(--fw-medium);
              background:var(--color-grey-100);border-color:transparent}
  .nick input.sub{margin-top:4px;font-size:var(--fs-sm);font-weight:var(--fw-normal);
                  color:var(--color-text-lighter)}
  .msg textarea{width:100%;padding:7px 9px;line-height:1.4;resize:vertical;overflow:hidden;
                background:var(--color-grey-100);border-color:transparent}
  .nick input:hover,.msg textarea:hover{border-color:var(--color-grey-400)}
  .st{width:170px}
  .del{width:36px;text-align:right}
  .when{font-size:var(--fs-sm);color:var(--color-text-lighter);white-space:nowrap}
  .acc{font-size:var(--fs-sm);color:var(--color-accent-700);white-space:nowrap}

  .chip .cnt{font-size:var(--fs-xs);color:var(--color-text-lighter);font-weight:var(--fw-normal)}
  .chip.off{opacity:.55}
  .chip.off .cnt{color:var(--color-red)}
  /* превью и ответ — одна строка с обрезкой, полный текст в подсказке */
  .preview{margin:5px 0 0;font-size:var(--fs-sm);color:var(--color-text-lighter);
           border-left:2px solid var(--color-accent-200);padding-left:9px;
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:420px}
  .warn{margin:5px 0 0;font-size:var(--fs-sm);color:var(--color-red)}
  .warn code,.note code{background:var(--color-grey-100);border-radius:var(--radius-xs);
           padding:1px 5px;font-size:var(--fs-xs)}

  /* бейджи статусов */
  .badge{display:inline-block;padding:3px 10px;border-radius:var(--radius-full);
         font-size:var(--fs-xs);font-weight:var(--fw-medium);white-space:nowrap}
  .b-ok{background:var(--color-green-bg);color:var(--color-accent-700)}
  .b-err{background:var(--color-red-bg);color:var(--color-red)}
  .b-send{background:var(--color-orange-light);color:var(--color-orange)}
  .b-wait{background:var(--color-grey-100);color:var(--color-text-lighter)}
  .b-ans{background:var(--color-accent);color:var(--color-white)}
  .stats .ans{color:var(--color-accent-700)}
  .reply{margin-top:5px;font-size:var(--fs-sm);color:var(--color-text-light);
         background:var(--color-green-bg);border-radius:var(--radius-sm);padding:5px 8px;
         white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}

  @media(max-width:900px){ .tiles{grid-template-columns:repeat(2,1fr)} }
  @media(max-width:760px){
    body{padding:24px 16px 48px}
    .sentence{font-size:var(--fs-base);line-height:2}
    .when,.reply,.th-hint{display:none}
    .st{width:auto}
  }
</style>
"""


def _page(title, body):
    return ("""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>""" + title +
            """</title>""" + CSS + """</head><body><div class="wrap">""" + body +
            """</div></body></html>""")


FLASH = """{% with msgs = get_flashed_messages() %}{% for m in msgs %}
  <div class="flash">{{ m }}</div>{% endfor %}{% endwith %}"""


# ─── экран 1: рассылка ─────────────────────────────────────────────────
MAIN_TPL = _page("ASCN Outreach", """
{% if sending_n or just %}<meta http-equiv="refresh" content="8">{% endif %}
<header>
  <div class="brand"><b>ASCN</b> Outreach</div>
  <a class="top-link" href="/inbox">💬 Ответы</a>
  <a class="top-link" href="/stats">📈 Статистика</a>
  <a class="top-link" href="/followups">🔁 Фоллоапы</a>
  <a class="top-link" href="/settings">⚙ Настройки</a>
</header>

<div class="tiles">
  <div class="tile"><div class="n">{{ queue }}</div><div class="l">в очереди</div></div>
  <div class="tile ok"><div class="n">{{ done }}</div><div class="l">отправлено</div></div>
  <div class="tile ans"><div class="n">{{ answered }}</div><div class="l">ответили
    {% if done %}<span class="pct">{{ (100 * answered / done) | round | int }}%</span>{% endif %}</div></div>
  <div class="tile mut"><div class="n">{{ errors }}</div><div class="l">не примут</div></div>
</div>
""" + FLASH + """
{% if checking %}
<div class="banner"><span>Идёт проверка{{ ' базы' if checking.get('что')=='leads' else ' ответов' }}
  с {{ checking.get('начали','') }}. Ничего не отправляется.</span></div>
{% endif %}
{% if sending_n or just %}
<div class="banner">
  <span>{% if sending_n %}Рассылка идёт: {{ sending_n }} в работе.{% else %}Рассылка запущена, первое сообщение готовится.{% endif %}
    Страница обновляется сама каждые 8 сек.</span>
  <form method="post" action="/stop" style="margin:0">
    <button class="btn-danger" onclick="return confirm('Остановить рассылку?')">Остановить</button>
  </form>
</div>
{% endif %}

<div class="card">
  {% if not sessions %}
    <div class="empty">
      Слать пока нечем — нет ни одного аккаунта Telegram.<br>
      <a href="/settings">Добавь аккаунт в настройках</a>, это займёт минуту.
    </div>
  {% elif not queue %}
    <div class="empty">Все лиды обработаны. Добавь новых — блок ниже.</div>
  {% elif not room_total %}
    <div class="empty">Дневные лимиты на сегодня выбраны.
      Это защита от бана — <a href="/settings">можно поднять</a>, но лучше продолжить завтра.</div>
  {% else %}
  <form method="post" action="/send">
    <div class="mode-row" style="margin:0 0 12px;display:flex;gap:18px;flex-wrap:wrap">
      <label style="cursor:pointer"><input type="radio" name="mode" value="personal" checked onchange="toggleMode()"> Персонально <span class="count">(каждому своё из базы)</span></label>
      <label style="cursor:pointer"><input type="radio" name="mode" value="broadcast" onchange="toggleMode()"> Единое сообщение <span class="count">(один текст всем)</span></label>
    </div>
    <div id="bcast" style="display:none;margin:0 0 14px">
      <textarea name="broadcast" rows="3"
        style="width:100%;box-sizing:border-box;padding:10px;border:1px solid var(--color-border);border-radius:8px;font:inherit;resize:vertical"
        placeholder="Впиши текст — уйдёт всем, кто сейчас в очереди."></textarea>
      <div class="hint">Уйдёт всем в очереди одним текстом. Кто уже получил — пропускается,
        поэтому следующей пачке можно вписать другое сообщение и разослать отдельно.</div>
    </div>
    <div class="sentence">
      <span class="txt">Отправить</span>
      <input class="num" type="number" name="limit" id="lim"
             value="{{ [5, queue, room_total] | min }}" min="1"
             max="{{ [queue, room_total] | min }}" oninput="est()">
      <span class="txt">сообщений с</span>
      <span class="chips">
        {% for s in sessions %}
        <label class="chip {{ 'off' if not room.get(s) }}">
          <input type="checkbox" name="sessions" value="{{ s }}" {{ '' if not room.get(s) else 'checked' }}>
          {{ s }} <span class="cnt">{{ today.get(s,0) }}/{{ caps.get(s,0) }}</span></label>
        {% endfor %}
      </span>
      <span class="txt">пауза</span>
      <input class="num" type="number" name="pause_min" id="pmin" value="90" min="0" max="1200" oninput="est()">
      <span class="txt">–</span>
      <input class="num" type="number" name="pause_max" id="pmax" value="240" min="0" max="1200" oninput="est()">
      <span class="txt">сек</span>
      <button class="btn btn-go" type="submit">Отправить →</button>
    </div>
    <div class="hint">
      <span id="est"></span>
      Сегодня осталось <b>{{ room_total }}</b> по лимитам (<a href="/settings">изменить</a>).
      Одному человеку дважды не уйдёт, пачка идёт в фоне.
    </div>
  </form>
  <script>
    function est(){
      var n=+document.getElementById('lim').value||0,
          a=+document.getElementById('pmin').value||0, b=+document.getElementById('pmax').value||0;
      var m=Math.round(Math.max(0,n-1)*(a+b)/2/60);
      document.getElementById('est').textContent =
        n ? 'Займёт примерно ' + (m<1 ? 'меньше минуты' : m + ' мин') + '. ' : '';
    }
    function toggleMode(){
      var b=document.querySelector('input[name=mode][value=broadcast]').checked;
      document.getElementById('bcast').style.display = b ? '' : 'none';
    }
    est(); toggleMode();
  </script>
  {% endif %}
</div>

<div class="card">
  <div class="card-head"><h2>Дневной режим</h2>
    <span class="note">Задай число на день — само растянется по окну 09–21 МСК</span></div>
  {% if daily_active %}
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <span>✅ Включён: <b>{{ daily_target }}</b> сообщений в день. Раскидывается по аккам сам, весь день.</span>
      <form method="post" action="/daily/stop" style="margin:0">
        <button class="btn-danger">Выключить</button>
      </form>
    </div>
  {% else %}
    <form method="post" action="/daily/start" id="dailyform">
      <div class="mode-row" style="margin:0 0 12px;display:flex;gap:18px;flex-wrap:wrap">
        <label style="cursor:pointer"><input type="radio" name="mode" value="personal" checked onchange="dToggle()"> Персонально <span class="count">(из базы)</span></label>
        <label style="cursor:pointer"><input type="radio" name="mode" value="broadcast" onchange="dToggle()"> Единое сообщение <span class="count">(один текст всем)</span></label>
      </div>
      <div id="dbcast" style="display:none;margin:0 0 12px">
        <textarea name="broadcast" rows="3"
          style="width:100%;box-sizing:border-box;padding:10px;border:1px solid var(--color-border);border-radius:8px;font:inherit;resize:vertical"
          placeholder="Единый текст всем. Уйдёт по чуть-чуть в течение дня."></textarea>
      </div>
      <div class="sentence">
        <span class="txt">Отправлять</span>
        <input class="num" type="number" name="target" value="50" min="1" max="500">
        <span class="txt">сообщений в день</span>
        <button class="btn btn-go" type="submit">Включить дневной режим →</button>
      </div>
      <div class="hint">Растянется равномерно по рабочему дню (09–21 МСК), раскидается по всем аккам. Не успело всё — завтра продолжит. С ручной рассылкой не пересечётся.</div>
    </form>
    <script>
      function dToggle(){
        var f=document.getElementById('dailyform');
        var b=f.querySelector('input[name=mode][value=broadcast]').checked;
        document.getElementById('dbcast').style.display=b?'':'none';
      }
      dToggle();
    </script>
  {% endif %}
</div>

<div class="card">
  <div class="card-head">
    <h2>Лиды <span class="count">{{ shown }} из {{ total }}</span></h2>
    <div class="tools">
      {% for key, name in [('all','Все'),('queue','В очереди'),('answered','Ответили'),('bad','Не примут')] %}
        <a class="pill {{ 'on' if f == key }}" href="/?f={{ key }}">{{ name }}</a>
      {% endfor %}
      <form method="post" action="/check/leads" style="margin:0">
        <button class="btn-ghost btn-sm">Проверить базу</button></form>
      <form method="post" action="/check/replies" style="margin:0">
        <button class="btn-ghost btn-sm">Кто ответил</button></form>
    </div>
  </div>

  <details class="add">
    <summary>+ Добавить контакты</summary>
    <form method="post" action="/leads/add">
      <textarea name="contacts" rows="3" style="width:100%"
        placeholder="@ivan&#10;t.me/petr&#10;@anna&#9;Анна&#9;дорогая реклама&#9;Привет, {имя}!"></textarea>
      <div class="row-end">
        <span class="note">Список ников, по строке. Или с полями через табуляцию /
          <code>;</code>: <code>ник · имя · боль · сообщение</code></span>
        <button class="btn" type="submit">Добавить</button>
      </div>
    </form>
  </details>

  {% if not leads %}
    <div class="empty">В этом фильтре пусто. <a href="/?f=all">Показать всех</a></div>
  {% else %}
  <form method="post" action="/leads/save" id="leads" oninput="dirty()">
    <table class="leads">
      <tr>
        <th>Кому</th>
        <th>Сообщение <span class="th-hint">— правится тут: {имя}, {Привет|Хай}</span></th>
        <th>Статус</th><th></th>
      </tr>
      {% for l in leads %}
      <tr>
        <td class="nick">
          <input name="ник__{{ l._i }}" value="{{ l[nick_col] }}">
          <input class="sub" name="главная боль__{{ l._i }}"
                 value="{{ l.get('главная боль','') }}" placeholder="боль клиента">
        </td>
        <td class="msg">
          <textarea name="сообщение для захода__{{ l._i }}" rows="1"
                    placeholder="что пишем этому человеку">{{ l.get('сообщение для захода','') }}</textarea>
          {% if l._bad %}<div class="warn">нет колонок:
            {% for b in l._bad %}<code>{{ b }}</code>{% endfor %}</div>
          {% elif l._preview and l._preview != l.get('сообщение для захода','') %}
            <div class="preview" title="{{ l._preview }}">→ {{ l._preview }}</div>{% endif %}
        </td>
        <td class="st">
          {% if l._status=='ответил' %}<span class="badge b-ans">ответил</span>
          {% elif l._status=='мёртвый ник' %}<span class="badge b-err">ника нет</span>
          {% elif l._status=='отправлено' %}<span class="badge b-ok">отправлено</span>
          {% elif l._status=='ошибка' %}<span class="badge b-err">не примет</span>
          {% elif l._status=='отправляется' %}<span class="badge b-send">идёт…</span>
          {% else %}<span class="badge b-wait">в очереди</span>{% endif %}
          {% if l._when %}<div class="when">{{ l._when }}{% if l._acc %} · {{ l._acc }}{% endif %}</div>{% endif %}
          {% if l._reply %}<div class="reply" title="{{ l._reply }}">💬 {{ l._reply }}</div>{% endif %}
        </td>
        <td class="del">
          <button class="btn-x" name="del_nick" value="{{ l[nick_col] }}" formaction="/lead/delete"
                  formnovalidate title="удалить из базы"
                  onclick="return confirm('Удалить {{ l[nick_col] }} из базы?')">×</button>
        </td>
      </tr>
      {% endfor %}
    </table>
    <div class="savebar" id="savebar">
      <span class="note" id="savenote">Правки сохраняются в data/leads.xlsx</span>
      <button class="btn" type="submit">Сохранить</button>
    </div>
  </form>
  <script>
    function dirty(){
      document.getElementById('savebar').classList.add('hot');
      document.getElementById('savenote').textContent = 'Есть несохранённые правки';
    }
    // textarea растёт под текст, но не занимает полэкрана в покое
    document.querySelectorAll('.msg textarea').forEach(function(t){
      function fit(){ t.style.height='auto'; t.style.height=Math.min(t.scrollHeight,160)+'px'; }
      t.addEventListener('input', fit); t.addEventListener('focus', fit); fit();
    });
  </script>
  {% endif %}
</div>
""")


# ─── экран 2: настройки ────────────────────────────────────────────────
SETTINGS_TPL = _page("Настройки · ASCN Outreach", """
<header>
  <div class="brand"><b>ASCN</b> Outreach</div>
  <a class="top-link" href="/">← К рассылке</a>
</header>
<h1 class="page">Настройки</h1>
<p class="lead">Аккаунты, с которых уходят сообщения, ключи Telegram и журнал отправок.</p>
""" + FLASH + """

<div class="card">
  <div class="card-head"><h2>Аккаунты</h2>
    <span class="note">5–10 сообщений в день с одного — больше рискованно</span></div>
  {% if sessions %}
  <table>
    <tr><th>Аккаунт</th><th>Прокси</th><th></th></tr>
    {% for s in sessions %}
    <tr>
      <td class="nick" style="padding-top:18px">{{ s }}</td>
      <td>
        <form method="post" action="/account/proxy" style="display:flex;gap:8px">
          <input type="hidden" name="name" value="{{ s }}">
          <input name="proxy" value="{{ proxies.get(s,'') }}" style="flex:1"
                 placeholder="socks5://user:pass@1.2.3.4:1080">
          <button class="btn-ghost btn-sm" type="submit">Сохранить</button>
        </form>
      </td>
      <td style="text-align:right;white-space:nowrap;padding-top:14px">
        <form method="post" action="/account/logout" style="display:inline">
          <input type="hidden" name="name" value="{{ s }}">
          <button class="btn-danger btn-sm"
                  onclick="return confirm('Разлогинить {{ s }}?')">Разлогинить</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <div class="empty">Аккаунтов нет. Добавь первый — без него рассылка не запустится.</div>
  {% endif %}
</div>

<div class="card">
  <div class="card-head"><h2>Добавить аккаунт</h2></div>
  <form method="post" action="/account/code" class="sentence" style="line-height:1.6">
    <div><label class="field">Название (латиницей)</label>
      <input name="name" placeholder="akk1" required></div>
    <div><label class="field">Номер телефона</label>
      <input name="phone" placeholder="+79001234567" required></div>
    <div style="flex:1;min-width:220px"><label class="field">Прокси (необязательно)</label>
      <input name="proxy" placeholder="socks5://user:pass@1.2.3.4:1080" style="width:100%"></div>
    <div style="align-self:end"><button class="btn" type="submit">Прислать код</button></div>
    <div class="hint" style="flex-basis:100%">
      Код придёт в Telegram на этот номер. Для нескольких аккаунтов держи каждый на своём прокси.
    </div>
  </form>
</div>

<div class="card">
  <div class="card-head"><h2>🧊 На заморозке (@SpamBot)</h2>
    <span class="note">акки в спам-лимите — вернутся сами по сроку</span></div>
  {% if frozen %}
  <div style="display:grid;grid-template-columns:1fr auto;gap:8px 16px">
    {% for acc, info in frozen.items() %}
    <div style="font-weight:var(--fw-medium)">{{ acc }}</div>
    <div style="text-align:right;color:#e0a34a">заморожен до {{ info.until_msk }} МСК</div>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty">Замороженных нет — все акки в работе.</div>
  {% endif %}
</div>

<div class="card">
  <div class="card-head"><h2>Темп и дневные лимиты</h2>
    <span class="note">Паузы сами растягиваются ночью и сужаются в рабочие часы</span></div>
  <form method="post" action="/limits/save">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 18px;
                padding:0 0 16px;border-bottom:1px solid var(--color-border)">
      <label class="field" style="margin:0">Общий лимит в день на аккаунт</label>
      <input class="num" name="default" value="{{ default_cap }}">
      <span class="hint" style="margin:0">сообщений с одного аккаунта в сутки — действует на всех, у кого ниже не задано своё</span>
    </div>

    <div style="display:grid;grid-template-columns:1fr auto 130px;gap:10px 16px;align-items:center">
      <div class="hint" style="margin:0;font-weight:var(--fw-medium)">Аккаунт</div>
      <div class="hint" style="margin:0;text-align:right">Доставлено / попыток</div>
      <div class="hint" style="margin:0">Свой лимит/день</div>
      {% for s in sessions %}
      <div style="font-weight:var(--fw-medium)">{{ s }}</div>
      <div style="text-align:right;color:var(--color-text-lighter)"><b>{{ today_ok.get(s,0) }}</b> / {{ today.get(s,0) }} · лимит {{ caps.get(s, default_cap) }}</div>
      <input class="num" name="cap__{{ s }}" value="{{ limits.get(s,'') }}"
             placeholder="{{ default_cap }} (общий)" style="width:100%;box-sizing:border-box">
      {% endfor %}
    </div>

    <div style="display:flex;align-items:center;gap:14px;margin-top:18px;flex-wrap:wrap">
      <button class="btn" type="submit">Сохранить</button>
      <span class="hint" style="margin:0">Пусто в поле — берётся общий лимит. Формат: <b>доставлено</b> / попыток · лимит. В лимит идут и неудачные попытки (для Telegram это всё равно запрос).</span>
    </div>
  </form>
</div>

<div class="card">
  <div class="card-head"><h2>Ключи Telegram</h2>
    <span class="note">api_id {{ api_id }} · получены на my.telegram.org</span></div>
  <form method="post" action="/onboarding/save" class="sentence" style="line-height:1.6">
    <div><label class="field">api_id</label><input name="api_id" value="{{ api_id }}" required></div>
    <div style="flex:1;min-width:260px"><label class="field">api_hash</label>
      <input name="api_hash" value="{{ api_hash }}" style="width:100%" required></div>
    <div style="align-self:end"><button class="btn-ghost" type="submit">Обновить</button></div>
  </form>
</div>

<div class="card">
  <div class="card-head"><h2>Что работает</h2>
    <span class="note">Ответили {{ stats['ответили'] }} из {{ stats['отправлено'] }}
      — {{ stats['процент'] }}% reply rate</span></div>
  {% if stats['отправлено'] %}
    <table>
      <tr><th>Вариант текста</th><th>Отправлено</th><th>Ответили</th><th>Reply rate</th></tr>
      {% for name, v in stats['по вариантам'].items() %}
      <tr><td>{{ name }}</td><td>{{ v['отправлено'] }}</td><td>{{ v['ответили'] }}</td>
          <td><b>{{ v['процент'] }}%</b></td></tr>
      {% endfor %}
    </table>
    <table style="margin-top:20px">
      <tr><th>Аккаунт</th><th>Отправлено</th><th>Ответили</th><th>Reply rate</th></tr>
      {% for name, v in stats['по аккаунтам'].items() %}
      <tr><td class="nick">{{ name }}</td><td>{{ v['отправлено'] }}</td>
          <td>{{ v['ответили'] }}</td><td><b>{{ v['процент'] }}%</b></td></tr>
      {% endfor %}
    </table>
    <div class="hint">Считается по нажатию «Кто ответил» на главном экране.
      Вариант — то, что выпало из <code>{а|б}</code>: видно, какая формулировка заходит.</div>
  {% else %}
    <div class="empty">Пока нечего считать — рассылка ещё не отправляла сообщений.</div>
  {% endif %}
</div>

<div class="card">
  <div class="card-head"><h2>Защита данных</h2>
    <span class="note">{{ protected }} файлов: сессии, ключи, база, логи</span></div>
  <form method="post" action="/lock" class="sentence" style="line-height:1.6">
    <div><label class="field">Пароль</label>
      <input name="password" type="password" required></div>
    <div><label class="field">Повтори</label>
      <input name="password2" type="password" required></div>
    <div style="align-self:end"><button class="btn-ghost" type="submit">Заблокировать</button></div>
    <div class="hint" style="flex-basis:100%">
      Файл сессии — это полный доступ к твоему Telegram: у кого есть папка
      <code>data/</code>, у того есть аккаунт. Блокировка прячет всё в один
      зашифрованный файл. Пока данные разблокированы, они лежат открыто —
      иначе рассылка не сможет работать; смысл в том, чтобы блокировать,
      когда не работаешь.
    </div>
  </form>
</div>

<div class="card">
  <div class="card-head"><h2>Журнал отправок</h2>
    <span class="note">{{ ok }} доставлено · {{ fail }} не ушло</span></div>
  {% if rows %}
  <table>
    <tr><th>Когда</th><th>Кому</th><th>Аккаунт</th><th>Статус</th><th>Причина</th></tr>
    {% for r in rows %}
    <tr>
      <td class="when">{{ r.get('время','') }}</td>
      <td class="nick">{{ r.get('ник','') }}</td>
      <td class="acc">{{ r.get('аккаунт','') }}</td>
      <td>{% if r.get('статус')=='ok' %}<span class="badge b-ok">доставлено</span>
          {% else %}<span class="badge b-err">не ушло</span>{% endif %}</td>
      <td style="font-size:var(--fs-sm);color:var(--color-text-lighter)">{{ r.get('ошибка','') }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <div class="empty">Пока ничего не отправлялось.</div>
  {% endif %}
</div>
""")


# ─── первый запуск ─────────────────────────────────────────────────────
ONBOARD_TPL = _page("Настройка · ASCN Outreach", """
<header><div class="brand"><b>ASCN</b> Outreach</div></header>
<h1 class="page">Один шаг до начала</h1>
<p class="lead">Нужны ключи Telegram — бесплатно и на две минуты. Хранятся только у тебя,
   в файле <code>data/config.json</code>.</p>
""" + FLASH + """
<div class="card">
  <div class="card-head"><h2>Где взять ключи</h2></div>
  <ol style="margin:0 0 24px;padding-left:22px;color:var(--color-text-light);font-size:var(--fs-base)">
    <li>Открой <a href="https://my.telegram.org" target="_blank" rel="noopener">my.telegram.org</a>
        и войди по своему номеру.</li>
    <li>Раздел <b>API development tools</b>.</li>
    <li>Заполни App title и Short name латиницей (например <code>outreach</code>).</li>
    <li>Скопируй оттуда <b>api_id</b> и <b>api_hash</b>.</li>
  </ol>
  <form method="post" action="/onboarding/save" class="sentence" style="line-height:1.6">
    <div><label class="field">api_id — число</label>
      <input name="api_id" value="{{ api_id }}" placeholder="1234567" required></div>
    <div style="flex:1;min-width:260px"><label class="field">api_hash — строка ~32 символа</label>
      <input name="api_hash" value="{{ api_hash }}" style="width:100%" required></div>
    <div style="align-self:end"><button class="btn" type="submit">Сохранить и начать</button></div>
  </form>
</div>
""")


# ─── данные заблокированы паролем ──────────────────────────────────────
UNLOCK_TPL = _page("Данные заблокированы · ASCN Outreach", """
<header><div class="brand"><b>ASCN</b> Outreach</div></header>
<h1 class="page">Данные заблокированы</h1>
<p class="lead">Сессии аккаунтов, база и логи лежат в зашифрованном
   <code>data/vault.enc</code>. Введи пароль, чтобы продолжить работу.</p>
""" + FLASH + """
<div class="card">
  <form method="post" action="/unlock" class="sentence" style="line-height:1.6">
    <div style="flex:1;min-width:240px"><label class="field">Пароль</label>
      <input name="password" type="password" style="width:100%" autofocus required></div>
    <div style="align-self:end"><button class="btn" type="submit">Разблокировать</button></div>
    <div class="hint" style="flex-basis:100%">
      Пароль нигде не хранится. Если он потерян, данные восстановить нельзя —
      придётся заново залогинить аккаунты и загрузить базу.
    </div>
  </form>
</div>
""")


# ─── ввод кода при логине аккаунта ─────────────────────────────────────
CODE_TPL = _page("Код подтверждения · ASCN Outreach", """
<header><div class="brand"><b>ASCN</b> Outreach</div></header>
<h1 class="page">{% if need2fa %}Пароль двухфакторной защиты{% else %}Код из Telegram{% endif %}</h1>
<p class="lead">Аккаунт <b>{{ name }}</b>.
  {% if need2fa %}На этом аккаунте включён облачный пароль — введи его.
  {% else %}Код пришёл в приложение Telegram (или SMS, если номер новый).{% endif %}</p>
""" + FLASH + """
<div class="card">
  <form method="post" action="/account/signin" class="sentence" style="line-height:1.6">
    <input type="hidden" name="name" value="{{ name }}">
    {% if need2fa %}
      <div><label class="field">Облачный пароль</label>
        <input name="password" type="password" autofocus required></div>
    {% else %}
      <div><label class="field">Код</label>
        <input name="code" inputmode="numeric" placeholder="12345" autofocus required></div>
    {% endif %}
    <div style="align-self:end"><button class="btn" type="submit">Войти</button></div>
  </form>
</div>
<p class="lead"><a href="/settings">← Отмена, вернуться в настройки</a></p>
""")


INBOX_TPL = _page("Ответы · ASCN Outreach", """
<div class="topbar">
  <a class="top-link" href="/">← К рассылке</a>
  <a class="top-link" href="/settings">⚙ Настройки</a>
</div>
<h1 class="page">💬 Ответы лидов</h1>
<div class="card">
  {% if items %}
  <div style="display:flex;flex-direction:column">
    {% for nick, info in items %}
    <a href="/inbox/{{ nick.lstrip('@') }}" style="display:grid;grid-template-columns:1fr auto;
       gap:4px 12px;padding:13px 6px;border-bottom:1px solid var(--color-border);
       text-decoration:none;color:inherit">
      <div style="font-weight:var(--fw-medium)">{{ nick }}</div>
      <div class="hint" style="margin:0;text-align:right">{{ info.get('аккаунт','') }} · {{ info.get('когда','') }}</div>
      <div class="hint" style="margin:0;grid-column:1/3;color:var(--color-text-lighter)">{{ info.get('текст','')[:100] }}</div>
    </a>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty">Пока никто не ответил.</div>
  {% endif %}
</div>
""")


DIALOG_TPL = _page("Диалог · ASCN Outreach", """
<div class="topbar">
  <a class="top-link" href="/inbox">← Все ответы</a>
</div>
<h1 class="page">{{ nick }}</h1>
<div class="card">
  <div class="hint" style="margin:0 0 10px">Отвечаешь с аккаунта: <b>{{ acc or '—' }}</b></div>
  {% if err %}<div class="empty">{{ err }}</div>{% endif %}
  {% if msgs %}
  <div style="display:flex;flex-direction:column;gap:8px;max-height:58vh;overflow:auto;padding:8px 0">
    {% for m in msgs %}
    <div style="align-self:{{ 'flex-end' if m.out else 'flex-start' }};max-width:78%;
                background:{{ '#3a6df0' if m.out else 'var(--color-grey-200)' }};
                color:{{ '#ffffff' if m.out else 'var(--color-text)' }};
                padding:8px 12px;border-radius:14px">
      <div style="white-space:pre-wrap;word-break:break-word">{{ m.text }}</div>
      <div style="font-size:11px;opacity:.65;text-align:right;margin-top:2px">{{ m.date }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}
  <form method="post" action="/inbox/ai_draft" style="margin:6px 0 0">
    <input type="hidden" name="nick" value="{{ nick }}">
    <input type="hidden" name="acc" value="{{ acc }}">
    <button type="submit" style="background:#eef1f4;border:1px solid var(--color-border);border-radius:8px;padding:9px 14px;cursor:pointer;font-family:inherit;font-size:inherit">🤖 Черновик от ИИ</button>
  </form>
  <form method="post" action="/inbox/send" style="display:flex;gap:8px;margin-top:14px;align-items:flex-start">
    <input type="hidden" name="nick" value="{{ nick }}">
    <input type="hidden" name="acc" value="{{ acc }}">
    <textarea name="text" placeholder="Написать ответ клиенту…" required rows="5"
              style="flex:1;box-sizing:border-box;resize:vertical;font-family:inherit;
                     font-size:inherit;padding:10px;line-height:1.45" autofocus>{{ draft or '' }}</textarea>
    <button class="btn" type="submit">Отправить</button>
  </form>
  <div class="hint" style="margin:10px 0 0">Уйдёт клиенту с аккаунта {{ acc }}. Обнови страницу, чтобы увидеть его ответ.</div>
</div>
""")


STATS_TPL = _page("Статистика · ASCN Outreach", """
<div class="topbar">
  <a class="top-link" href="/">← К рассылке</a>
  <a class="top-link" href="/inbox">💬 Ответы</a>
</div>
<h1 class="page">📈 Отклик (reply-rate)</h1>
<div class="hint" style="margin:-6px 0 14px">
  Отклик = ответивших / отправлено, за всё время. Малые числа — статистический шум,
  смотри процент только рядом с объёмом (ответов/отправлено).
</div>

<div class="card">
  <h3 style="margin:2px 0 10px">Воронка по базе</h3>
  {% if funnel %}
  <div style="overflow-x:auto">
  <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:560px">
    <tr class="hint"><th style="text-align:left">База</th><th style="text-align:right;white-space:nowrap">Отпр.</th><th style="text-align:right;white-space:nowrap">Ответ.</th>
      <th style="text-align:right;white-space:nowrap">🔥 Интерес</th><th style="text-align:right;white-space:nowrap">🙅 Отказ</th>
      <th style="text-align:right;white-space:nowrap">😠 Негатив</th><th style="text-align:right;white-space:nowrap">🤖 Бот</th><th style="text-align:right;white-space:nowrap">Интерес%</th></tr>
    {% for name,s,rep,interes,otkaz,neg,bot in funnel %}
    <tr style="border-top:1px solid var(--color-border)">
      <td style="padding:8px 0">{{ name }}</td>
      <td style="text-align:right;white-space:nowrap">{{ s }}</td><td style="text-align:right;white-space:nowrap">{{ rep }}</td>
      <td style="text-align:right;white-space:nowrap"><b style="color:var(--color-accent)">{{ interes }}</b></td>
      <td style="text-align:right;white-space:nowrap">{{ otkaz }}</td><td style="text-align:right;white-space:nowrap">{{ neg }}</td><td style="text-align:right;white-space:nowrap">{{ bot }}</td>
      <td style="text-align:right;white-space:nowrap"><b>{{ (100*interes/s)|round(1) if s else 0 }}%</b></td></tr>
    {% endfor %}
  </table>
  </div>
  <div class="hint" style="margin:10px 0 0">🔥 Интерес = реально тёплые (спросил цену, как работает, согласен). Оценивай это, а не «ответили» скопом.</div>
  {% else %}<div class="empty">Пока нет данных.</div>{% endif %}
</div>

<div class="card">
  <h3 style="margin:2px 0 10px">По аккаунту</h3>
  {% if accs %}
  <table style="width:100%;border-collapse:collapse">
    <tr class="hint"><th style="text-align:left">Аккаунт</th><th style="text-align:right;white-space:nowrap">Отправлено</th>
      <th style="text-align:right;white-space:nowrap">Ответов</th><th style="text-align:right;white-space:nowrap">Отклик</th></tr>
    {% for acc,s,rr,rate in accs %}
    <tr style="border-top:1px solid var(--color-border)">
      <td style="padding:9px 0">{{ acc }}</td>
      <td style="text-align:right;white-space:nowrap">{{ s }}</td><td style="text-align:right;white-space:nowrap">{{ rr }}</td>
      <td style="text-align:right;white-space:nowrap"><b>{{ rate }}%</b></td></tr>
    {% endfor %}
  </table>
  {% else %}<div class="empty">Пока нет данных.</div>{% endif %}
</div>
""")


FOLLOWUPS_TPL = _page("Фоллоапы · ASCN Outreach", """
<div class="topbar">
  <a class="top-link" href="/">← К рассылке</a>
  <a class="top-link" href="/stats">📈 Статистика</a>
</div>
<h1 class="page">🔁 Фоллоапы</h1>
<div class="hint" style="margin:-6px 0 14px">
  Лид не ответил {{ day2 }} дн → касание №2, {{ day3 }} дн → касание №3. Тексты свои под каждую
  базу (пусто = ИИ напишет сам). Шлётся автоматически раз в день с того же аккаунта.
</div>

<div class="card">
  <h3 style="margin:2px 0 10px">Что происходит</h3>
  {% if rows %}
  <div style="overflow-x:auto">
  <table style="width:100%;border-collapse:collapse;font-size:14px;min-width:520px">
    <tr class="hint"><th style="text-align:left">База</th><th style="text-align:right;white-space:nowrap">Первое</th><th style="text-align:right;white-space:nowrap">Ответили</th>
      <th style="text-align:right;white-space:nowrap">Ждут добивки</th><th style="text-align:right;white-space:nowrap">№2</th><th style="text-align:right;white-space:nowrap">№3</th>
      <th style="text-align:right;white-space:nowrap">Ответ после добивки</th></tr>
    {% for name,first,rep,due,s2,s3,after in rows %}
    <tr style="border-top:1px solid var(--color-border)">
      <td style="padding:8px 0">{{ name }}</td>
      <td style="text-align:right;white-space:nowrap">{{ first }}</td><td style="text-align:right;white-space:nowrap">{{ rep }}</td>
      <td style="text-align:right;white-space:nowrap"><b>{{ due }}</b></td><td style="text-align:right;white-space:nowrap">{{ s2 }}</td><td style="text-align:right;white-space:nowrap">{{ s3 }}</td>
      <td style="text-align:right;white-space:nowrap"><b style="color:var(--color-accent)">{{ after }}</b></td></tr>
    {% endfor %}
  </table>
  </div>
  <div class="hint" style="margin:10px 0 0">«Ждут добивки» уйдут в ближайшие прогоны (есть дневной кап).
    «Ответ после добивки» = добивка сработала, лид ответил.</div>
  {% else %}<div class="empty">Пока нет данных.</div>{% endif %}
</div>

<form method="post" action="/followups/save">
  <input type="hidden" name="bases" value="{{ bases|join('|') }}">
  {% for b in bases %}
  <div class="card">
    <h3 style="margin:2px 0 10px">Тексты: {{ b }}</h3>
    <label class="field">Касание №2 (через {{ day2 }} дн)</label>
    <textarea name="t_{{ loop.index0 }}_2" rows="3" style="width:100%;box-sizing:border-box;
      font-family:inherit;font-size:inherit;padding:9px;resize:vertical"
      placeholder="{% if b != 'default' %}пусто = возьмётся из default{% else %}текст касания №2{% endif %}">{{ texts.get(b,{}).get('2','') }}</textarea>
    <label class="field" style="margin-top:10px;display:block">Касание №3 (через {{ day3 }} дн)</label>
    <textarea name="t_{{ loop.index0 }}_3" rows="3" style="width:100%;box-sizing:border-box;
      font-family:inherit;font-size:inherit;padding:9px;resize:vertical"
      placeholder="{% if b != 'default' %}пусто = возьмётся из default{% else %}текст касания №3{% endif %}">{{ texts.get(b,{}).get('3','') }}</textarea>
  </div>
  {% endfor %}
  <button class="btn" type="submit">Сохранить тексты</button>
</form>
""")
