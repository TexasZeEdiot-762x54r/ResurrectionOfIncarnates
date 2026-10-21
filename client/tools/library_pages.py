"""Read-only, bounded, account-independent Library pages for the local client."""
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent/'library'
LANGUAGES = ('en','fr','it','de','es','ru','pt-br','pl')
TABS = ('characters','stages','howtoplay','story')
HEADERS = {
    'Content-Type': 'text/html; charset=utf-8',
    'X-Content-Type-Options': 'nosniff',
    'Cache-Control': 'no-cache',
    'Content-Security-Policy': "default-src 'none'; img-src 'self'; style-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
}


def catalogue():
    path = ROOT/'catalogue.json'
    if path.is_symlink() or path.stat().st_size>262144:
        raise ValueError('Unsafe Library catalogue')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('format')!='roi-local-library' or value.get('version')!=1:
        raise ValueError('Unsupported Library catalogue')
    return value


def escape(value):
    return html.escape(str(value),quote=True)


def transcript():
    path = ROOT/'text.json'
    if path.is_symlink() or path.stat().st_size>262144:
        raise ValueError('Unsafe Library text')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('format')!='roi-library-text' or value.get('version')!=1:
        raise ValueError('Unsupported Library text')
    return value


def paragraphs(entry):
    parts=[]
    for paragraph in entry['paragraphs']:
        tag='h2' if paragraph in ('1. Transform','2. Deuteros','3. Servant-master') else 'p'
        parts.append('<'+tag+'>'+escape(paragraph)+'</'+tag+'>')
    return ''.join(parts)


def details(values):
    return '<dl>'+''.join('<div><dt>'+escape(k)+'</dt><dd>'+escape(v)+'</dd></div>'
                         for k,v in values.items())+'</dl>'


def image(asset, title, cls='page-image'):
    return ('<img class="'+cls+'" src="/library/assets/'+escape(asset['file'])+'" width="'+
            str(int(asset['width']))+'" height="'+str(int(asset['height']))+'" alt="'+escape(title)+'">')


def render(language, tab, query, data, text):
    entries = data.get(tab,[])
    key = query.get('item',[''])[0]
    selected = next((p for p in entries if p['id']==key),entries[0] if entries else None)
    prefix = '/library/'+language+'/'+tab
    nav, content = [], []
    for entry in entries:
        current = selected and entry['id']==selected['id']
        nav.append('<a'+(' class="selected" aria-current="page"' if current else '')+
                   ' href="'+prefix+'?item='+escape(entry['id'])+'">'+escape(entry['title'])+'</a>')
    if tab=='howtoplay':
        content.append('<section class="empty"><h1>How to Play</h1><p>Original Library page not recovered.</p></section>')
    elif selected:
        if tab=='characters':
            entry=text['characters'][selected['id']]
            content.append('<header>'+image(selected['portrait'],selected['title'],'portrait')+
                           '<div class="identity"><h1>'+escape(selected['human'])+'</h1><p>'+escape(selected['title'])+'</p></div>'+
                           details(entry['details'])+'</header>')
            variant_key = query.get('view',['human'])[0]
            variant = next((v for v in selected['variants'] if v['id']==variant_key),selected['variants'][0])
            content.append('<nav class="variants" aria-label="Character sections">')
            for v in selected['variants']:
                content.append('<a'+(' class="selected" aria-current="page"' if v is variant else '')+
                    ' href="'+prefix+'?item='+escape(selected['id'])+'&amp;view='+escape(v['id'])+'">'+escape(v['title'])+'</a>')
            content.append('</nav>')
            if variant['id'] in ('bio','daimon-bio'):
                content.append('<article class="prose">'+paragraphs(entry[variant['id']])+'</article>')
            elif variant['id']=='moves':
                content.append('<section class="prose"><h2>Move List (Human)</h2><table class="moves">'
                    '<thead><tr><th scope="col">Command</th><th scope="col">Properties</th><th scope="col">Details</th></tr></thead><tbody>')
                for row in entry['moves']['rows']:
                    content.append('<tr><th scope="row">'+escape(row['command'])+'</th><td>'+escape(row['properties'])+
                        '</td><td>'+escape(row['details'])+'</td></tr>')
                content.append('</tbody></table></section>')
            else:
                for asset in variant['assets']:
                    content.append(image(asset,variant['title']))
        else:
            if selected.get('status')=='unrecovered':
                content.append('<section class="empty"><h1>'+escape(selected['title'])+'</h1><p>Original Library page not recovered.</p></section>')
            else:
                entry=text[tab][selected['id']]
                if tab=='stages':
                    content.append('<header><h1>'+escape(selected['title'])+'</h1><p>'+escape(entry['country'])+'</p></header>')
                content.append(image(entry['illustration'],selected['title']))
                content.append('<article class="prose">')
                if tab=='story':
                    content.append('<h1 class="story-title">'+escape(entry['title'])+'</h1>')
                else:
                    content.append(details(entry['details']))
                content.append(paragraphs(entry)+'</article>')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+escape(tab.title())+' | Rise of Incarnates</title>'
            '<link rel="stylesheet" href="/library/assets/library.css"></head><body>'
            '<nav class="index" aria-label="'+escape(tab.title())+'">'+''.join(nav)+'</nav>'
            '<main id="article">'+''.join(content)+'</main></body></html>').encode('utf-8')


def respond(method, target):
    """None means not a Library URL; never fall through to profile APIs on errors."""
    if not (target=='/library' or target.startswith('/library/')):
        return None
    headers = dict(HEADERS)
    if len(target)>1024 or method not in ('GET','HEAD'):
        return (405 if method not in ('GET','HEAD') else 400),headers,b'Library request rejected'
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or parts.fragment or '%' in parts.path or '\\' in parts.path:
        return 404,headers,b'Library page not found'
    try:
        data = catalogue()
        text = transcript()
        asset_match = re.fullmatch(r'/library/assets/([a-z0-9][a-z0-9-]*\.(?:jpg|css))',parts.path)
        if asset_match:
            name = asset_match[1]
            artwork={p['illustration']['file'] for tab in ('story','stages') for p in text[tab].values()}
            if parts.query or name not in set(data['asset_sha256'])|artwork|{'library.css'}:
                return 404,headers,b'Library asset not found'
            path = ROOT/name
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()) or path.stat().st_size>4194304:
                return 404,headers,b'Library asset not found'
            headers['Content-Type'] = 'image/jpeg' if name.endswith('.jpg') else 'text/css; charset=utf-8'
            headers['Cache-Control'] = 'no-cache'
            return 200,headers,path.read_bytes()
        match = re.fullmatch(r'/library/([a-z-]+)/([a-z]+)',parts.path)
        if not match or match[1] not in LANGUAGES or match[2] not in TABS:
            return 404,headers,b'Library page not found'
        query = parse_qs(parts.query,keep_blank_values=True,max_num_fields=4)
        if set(query)-{'item','view'} or any(len(v)!=1 or not re.fullmatch('[a-z0-9-]{0,100}',v[0]) for v in query.values()):
            return 400,headers,b'Library query rejected'
        return 200,headers,render(match[1],match[2],query,data,text)
    except (OSError,ValueError,KeyError,TypeError):
        return 503,headers,b'Local Library content missing or invalid. Reapply the complete client patch.'
