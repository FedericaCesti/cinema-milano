#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cinema-milano · update.py
------------------------
Rigenera cinema-data.js (i dati della pagina index.html) leggendo le fonti:

  1. Cinema Beltrade      → feed iCalendar ufficiale + schede film (lingua, regia)
  2. spazioCinema/Anteo   → API JSON interna @@get-calendario (settimana completa:
                            spettacoli, sale, lingua per spettacolo, link biglietti,
                            locandine) + home per gli eventi
  3. Multisala Colosseo    → HTML della pagina programmazione (strutturata)
  + arricchimento da MyMovies (colosseo): le proiezioni in inglese sono
    "versione originale con sottotitoli" → badge sott. ITA

Uso:        python3 update.py
Output:     cinema-data.js  (nella stessa cartella di questo script)
In caso di errore su un cinema viene riutilizzato il blocco del run precedente.

Solo stdlib: nessuna dipendenza da installare.
"""

import html as htmlmod
import json
import re
import sys
import time
import unicodedata
import datetime as dt
import urllib.request
import urllib.error
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    _TZ = ZoneInfo('Europe/Rome')          # anche sui runner GitHub (UTC)
except Exception:
    _TZ = None

def now():
    return dt.datetime.now(_TZ) if _TZ else dt.datetime.now()

BASE = Path(__file__).resolve().parent
DATA_FILE = BASE / 'cinema-data.js'

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) cinema-milano-updater'

BE_ICS = 'https://bandhi.it/bah/beltrade/wp-content/uploads/sites/2/beltrade.ics'
BE_SITE = 'https://bandhi.it/bah/beltrade/'
BE_TICKETS = 'https://bandhi.it/bah/beltrade/biglietti/'
AN_HOME = 'https://www.spaziocinema.info/milano'
AN_CAL = 'https://www.spaziocinema.info/cinema/@@get-calendario?town=Milano&dt='
AN_TICKETS = 'https://spaziocinema.18tickets.it/select_cinema?mandatory=true'
CO_PAGE = 'https://www.ilregnodelcinema.com/colosseo/'
MM_COLOSSEO = 'https://www.mymovies.it/cinema/milano/5445/'   # solo arricchimento "sott. ITA"

WEEKDAYS = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
WD_SHORT = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
MONTHS = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
          'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']

COUNTRY_LANG = {'francia': 'francese', 'giappone': 'giapponese', 'spagna': 'spagnolo',
                'regno unito': 'inglese', 'stati uniti': 'inglese', 'usa': 'inglese',
                'corea del sud': 'coreano', 'corea': 'coreano', 'germania': 'tedesco',
                'austria': 'tedesco', 'russia': 'russo'}
AN_VENUES = {'anteo palazzo del cinema': 'Anteo Palazzo del Cinema',
             'citylife anteo': 'CityLife Anteo',
             'ariosto': 'Ariosto spazioCinema'}
TITLE_STOPWORDS = {'di', 'dei', 'del', 'della', 'delle', 'degli', 'e', 'il', 'lo', 'la',
                   'le', 'un', 'una', 'con', 'per', 'che', 'da', 'al', 'alla', 'ai', 'agli',
                   'sul', 'sulla', 'nel', 'nella', 'a', 'in', 'ma', 'se', 'come', 'anche', 'del'}


# ------------------------------------------------------------------ utils
def log(msg):
    print(now().strftime('%Y-%m-%d %H:%M:%S') + '  ' + msg)


def fetch(url, tries=2, timeout=30):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,text/calendar,application/json,*/*',
                'Accept-Encoding': 'identity'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError('fetch failed %s: %s' % (url, last))


def strip_tags(raw):
    raw = re.sub(r'<script.*?</script>', ' ', raw, flags=re.S | re.I)
    raw = re.sub(r'<style.*?</style>', ' ', raw, flags=re.S | re.I)
    txt = htmlmod.unescape(re.sub(r'<[^>]+>', '\n', raw))
    return [l.strip() for l in txt.split('\n') if l.strip()]


def slugify(s):
    s = unicodedata.normalize('NFKD', s.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-') or 'film'


def smart_title(t):
    words = t.split(' ')
    out = []
    for i, w in enumerate(words):
        if i > 0 and w.lower() in TITLE_STOPWORDS:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return ' '.join(out)


def day_key(d):
    return '%04d-%02d-%02d' % (d.year, d.month, d.day)


def day_meta(d, today):
    return {'key': day_key(d),
            'short': '%s %d' % (WD_SHORT[d.weekday()], d.day),
            'long': '%s %d %s %s' % (WEEKDAYS[d.weekday()], d.day, MONTHS[d.month - 1], d.year),
            'today': d == today}


def load_previous():
    if not DATA_FILE.exists():
        return None
    try:
        raw = DATA_FILE.read_text(encoding='utf-8')
        m = re.search(r'window\.DATA\s*=\s*(\{.*\})\s*;?\s*$', raw, re.S)
        return json.loads(m.group(1))
    except Exception:
        return None


def prev_films_by_url(prev, cinema_id):
    out = {}
    if not prev:
        return out
    for c in prev.get('cinemas', []):
        if c.get('id') == cinema_id:
            for f in c.get('films', []):
                out[f.get('url')] = f
    return out


def short_plot(p, n=170):
    if not p:
        return None
    p = re.sub(r'\s+', ' ', p).strip()
    p = p[0].upper() + p[1:].lower()
    if len(p) <= n:
        return p
    cut = p[:n]
    sp = cut.rfind(' ')
    return (cut[:sp] if sp > 80 else cut) + '…'


# ------------------------------------------------------------------ Beltrade
def parse_ics(text):
    lines, ev, out = [], None, []
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    for ln in text.split('\n'):                      # unfold (righe di continuazione)
        if ln[:1] in (' ', '\t') and lines:
            lines[-1] += ln[1:]
        else:
            lines.append(ln)
    for ln in lines:
        if ln.startswith('BEGIN:VEVENT'):
            ev = {'url': ''}
        elif ln.startswith('END:VEVENT'):
            if ev:
                out.append(ev)
            ev = None
        elif ev is not None:
            if ln.startswith('SUMMARY:'):
                ev['summary'] = htmlmod.unescape(ln[8:].strip())
            elif ln.startswith('DTSTART'):
                m = re.search(r'(\d{8})T(\d{6})', ln)
                if m:
                    ev['when'] = dt.datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')
            elif ln.startswith('URL:'):
                ev['url'] = htmlmod.unescape(ln[4:].strip())
    return [e for e in out if 'when' in e and 'summary' in e]


def be_lang_from_page(text):
    lines = strip_tags(text)
    lang_line = None
    for l in lines:
        if re.match(r'^v\.?\s*o\.?\s', l.lower()):
            lang_line = l
            break
    if not lang_line:
        return None
    line = lang_line.split('–')[0].split('—')[0].strip()
    low = line.lower()
    sub = None
    if 'con sottotitoli in italiano' in low:
        sub = 'sott. ITA'
    elif 'con sottotitoli in inglese' in low:
        sub = 'sott. in inglese'
    audio = re.sub(r'^v\.?\s*o\.?\s*', '', line, flags=re.I)
    audio = re.split(r'\s+con\s+sottotitoli', audio)[0].strip().rstrip(',').rstrip('·')
    audio = re.sub(r'\s*,\s*|\s+e\s+', ' · ', audio).strip(' ·')
    if sub == 'sott. in inglese' and audio.lower().startswith('italiano'):
        return {'cat': 'voita', 'audio': 'V.O. italiana', 'sub': 'sott. in inglese'}
    if audio.lower() == 'italiano':
        return {'cat': 'ita', 'audio': 'In italiano'}
    if sub == 'sott. ITA' and audio.lower() == 'inglese':
        return {'cat': 'eng', 'audio': 'V.O. inglese', 'sub': 'sott. ITA'}
    if not audio:
        return {'cat': 'vo', 'audio': 'V.O.', 'sub': sub}
    return {'cat': 'vo', 'audio': 'V.O. ' + audio, 'sub': sub}


def be_film_details(url, cache):
    if url in cache and cache[url].get('_details'):
        f = dict(cache[url])
        f['lang'] = cache[url].get('lang') or {'cat': 'vo', 'audio': 'V.O.'}
        return f, True
    try:
        text = fetch(url)
    except Exception as e:
        log('  ! scheda non raggiungibile (%s): %s' % (url, e))
        return {'title': '', 'lang': None}, False
    m = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.S)
    title = re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', '', m.group(1)))).strip() if m else ''
    pm = re.search(r'property="og:image"\s+content="([^"]+)"', text) or \
         re.search(r'content="([^"]+)"\s+property="og:image"', text)
    poster = pm.group(1) if pm else None
    lines = strip_tags(text)
    det = {'title': title, 'dir': '', 'cast': '', 'meta': '', 'poster': poster}
    for l in lines:
        if not det['dir'] and re.match(r'^un film di ', l):
            det['dir'] = re.sub(r'^un film di ', '', l)
        if not det['cast'] and re.match(r'^con .{3,}', l) and 'clicca' not in l.lower():
            det['cast'] = re.sub(r'^con ', '', l).rstrip(',')
        if not det['meta'] and '●' in l and re.search(r'(19|20)\d{2}', l):
            meta = l.replace('●', '·').replace('minuti', '').strip()
            meta = re.sub(r'(\d+)\s*$', r'\1′', meta)
            det['meta'] = re.sub(r'\s+', ' ', re.sub(r'\s*,\s*', ' · ', meta)).strip(' ·')
    det['lang'] = be_lang_from_page(text)
    if det['lang'] is None and re.search(r'(senza dialoghi|non ci sono dialoghi)',
                                         ' '.join(lines), re.I):
        det['lang'] = {'cat': 'none', 'audio': 'Senza dialoghi'}
    return det, False


def update_beltrade(today, week_keys, prev):
    log('Beltrade: leggo il calendario iCal…')
    events = parse_ics(fetch(BE_ICS))
    films, by_url = [], {}
    upcoming = []
    week_end = today + dt.timedelta(days=6)
    for ev in events:
        d = ev['when'].date()
        if d < today:
            continue
        t = ev['when'].strftime('%H:%M')
        summary = ev['summary']
        tbd = 'orario da definire' in summary.lower()
        title = re.sub(r'\s*[-–]\s*orario da definire.*$', '', summary, flags=re.I).strip()
        if d > week_end:
            if t >= '08:00' and d <= today + dt.timedelta(days=30):
                upcoming.append((d, re.sub(r'\s*[-–]\s*DAL\s+\d+\s+\w+.*$', '',
                                           summary, flags=re.I).strip()))
            continue
        if t < '08:00' and not tbd:
            continue
        url = ev['url'] or (BE_SITE + 'production/' + slugify(title) + '/')
        f = by_url.get(url)
        if f is None:
            f = {'id': slugify(title), 'title': title, 'url': url,
                 'shows': defaultdict(list), 'tbd': []}
            by_url[url] = f
            films.append(f)
        if tbd:
            f['tbd'].append(day_key(d))
        else:
            f['shows'][day_key(d)].append(t)
    log('Beltrade: %d film in settimana, scarico le schede…' % len(films))
    cache = prev_films_by_url(prev, 'beltrade')
    out = []
    for f in films:
        det, cached = be_film_details(f['url'], cache)
        title = det.get('title') or f['title']
        title = re.sub(r'\s*[-–]\s*orario da definire.*$', '', title, flags=re.I).strip()
        lang = det.get('lang') or (cache.get(f['url'], {}).get('lang')) \
            or {'cat': 'vo', 'audio': 'V.O.'}
        out.append({'id': f['id'], 'title': title,
                    'dir': det.get('dir') or None, 'cast': det.get('cast') or None,
                    'meta': det.get('meta') or None, 'genre': None, 'url': f['url'],
                    'poster': det.get('poster') or None,
                    'slots': [{'lang': lang,
                               'shows': {k: sorted(f['shows'][k]) for k in week_keys if f['shows'].get(k)},
                               'tbd': [k for k in week_keys if k in f['tbd']]}]})
        if not cached:
            time.sleep(0.2)
    extra = []
    seen = set()
    for d, s in sorted(upcoming):
        if s.lower() in seen:
            continue
        seen.add(s.lower())
        extra.append('<b>%s</b> — dal %s' % (htmlmod.escape(s), d.strftime('%d/%m')))
        if len(extra) >= 6:
            break
    cinema = {
        'id': 'beltrade', 'name': 'Cinema Beltrade', 'short': 'Beltrade',
        'tagline': 'Cinema d\u2019essai e di repertorio nel quartiere Pasteur — spettacoli mattutini, pomeridiani e serali, quasi tutto in lingua originale con sottotitoli.',
        'address': 'Via Nino Oxilia 10, 20127 Milano',
        'map': 'https://www.google.com/maps/search/?api=1&query=' + urllib.request.quote('Cinema Beltrade, Via Nino Oxilia 10, Milano'),
        'phone': '02 26820592', 'transport': 'M1 Pasteur · Tram 1 Morbegno',
        'site': BE_SITE, 'tickets': BE_TICKETS, 'keepVisible': False,
        'noDayText': 'Nessuno spettacolo in questo giorno.',
        'films': out,
    }
    if extra:
        cinema['extra'] = [{'h': 'Prossimamente al Beltrade', 'items': extra}]
    return cinema


# ------------------------------------------------------------------ Anteo (API JSON)
def an_title_clean(t):
    t = unicodedata.normalize('NFC', re.sub(r'\s+', ' ', (t or '').strip()))
    orig = None
    m = re.search(r'\s*\(([^)]{2,})\)\s*$', t)
    if m:
        orig = m.group(1)
        t = t[:m.start()].strip()
    t = re.sub(r'^v\.?\s*o\.?\s*sott\.?\s*ita[l.]?\s*[-–]?\s*', '', t, flags=re.I)
    t = re.sub(r'\s*[-–]\s*v\.?\s*o\.?\s*\.?$', '', t, flags=re.I)
    if t.islower():
        t = smart_title(t)
    return t, orig


def an_parse_langfield(field, country):
    s = unicodedata.normalize('NFC', (field or '')).strip().lower()
    s = re.sub(r'\s+', ' ', s)
    sub = None
    audio = s
    m = re.match(r'(.+?)\s+con\s+sott', s)
    if m:
        audio = m.group(1).strip(' -–·,')
        sub = 'sott. ITA'
    if not audio or audio == 'italiano':
        if (country or '').strip().lower() == 'italia':
            return {'cat': 'ita', 'audio': 'In italiano'}
        return {'cat': 'ita', 'audio': 'In italiano (doppiato)'}
    if re.search(r'diverse lingue|varie lingue|versione originale', audio):
        return {'cat': 'vo', 'audio': 'V.O.', 'sub': sub}
    audio = re.sub(r'\s*,\s*|\s+e\s+', ' · ', audio).strip(' ·')
    cat = 'eng' if 'inglese' in audio else 'vo'
    return {'cat': cat, 'audio': 'V.O. ' + audio, 'sub': sub}


PALAZZO_HOST = 'https://anteo.spaziocinema.18tickets.it/'


def update_anteo(today, week_keys, prev):
    log('Anteo Palazzo: interrogo l\u2019API del calendario (7 giorni)…')
    films_by_url, order, hall2venue = {}, [], {}
    for d in week_keys:
        try:
            day_films = json.loads(fetch(AN_CAL + d))
        except Exception as e:
            log('  ! calendario %s non disponibile: %s' % (d, e))
            continue
        for f in day_films:
            # mappa sala → venue dalle occupations (per gli spettacoli senza
            # link: ci serve solo per capire chi sta al Palazzo)
            for o in f.get('film_occupations') or []:
                sala = (o.get('theater_name') or '').strip()
                cine = (o.get('cinema_name') or '').strip()
                if sala and cine and sala not in hall2venue:
                    hall2venue[sala] = cine
            u = f.get('URL') or f.get('title')
            film = films_by_url.get(u)
            if film is None:
                film = films_by_url[u] = {'f': f, 'shows': []}
                order.append(u)
            for o in f.get('orari') or []:        # orari completi del giorno richiesto
                if o.get('hour'):
                    film['shows'].append({'date': o.get('date') or d, 't': o['hour'],
                                          'sala': (o.get('sala') or '').strip(),
                                          'link': o.get('projection_url') or '',
                                          'tech': o.get('technologies') or []})
    log('Anteo Palazzo: %d titoli nel calendario di settimana.' % len(order))

    def is_palazzo(show):
        link = show.get('link') or ''
        if link.startswith(PALAZZO_HOST):
            return True
        if 'spaziocinema.18tickets.it' in link:
            return False                          # biglietto di un'altra sede
        return hall2venue.get(show.get('sala'), '').lower() == 'anteo palazzo del cinema'

    def nshows(v):
        return sum(len(x) for s in v['slots'] for x in s['shows'].values())

    films, countries = [], {}
    for u in order:
        m = films_by_url[u]
        f = m['f']
        title, orig = an_title_clean(f.get('title', ''))
        if not title or not m['shows']:
            continue
        shows = [s for s in m['shows'] if s['date'] in week_keys and is_palazzo(s)]
        if not shows:
            continue
        country = (f.get('country_name') or '').strip()
        countries[title.upper()] = country
        base_lang = an_parse_langfield(f.get('language'), country)
        film_is_vo = base_lang['cat'] in ('vo', 'eng')
        slotmap, seen = {}, set()
        for s in shows:
            sig = (s['date'], s['t'], s['sala'])
            if sig in seen:
                continue
            seen.add(sig)
            has_lingua = any('LINGUA ORIGINALE' in str(x).upper() for x in s['tech'])
            if film_is_vo:
                lang = base_lang
            elif has_lingua:
                lname = COUNTRY_LANG.get(country.lower())
                lang = ({'cat': 'eng' if lname == 'inglese' else 'vo',
                         'audio': 'V.O. ' + lname, 'sub': 'sott. ITA'} if lname else
                        {'cat': 'vo', 'audio': 'V.O.', 'sub': 'sott. ITA'})
            else:
                lang = base_lang
            key = lang['cat'] + '|' + lang['audio'] + '|' + (lang.get('sub') or '')
            sl = slotmap.setdefault(key, {'lang': lang, 'shows': defaultdict(list)})
            sl['shows'][s['date']].append({'t': s['t'], 'hall': s['sala'], 'link': s['link']})
        slots = [{'lang': sl['lang'],
                  'shows': {k: sorted(v, key=lambda x: x['t'])
                            for k, v in sl['shows'].items() if v}}
                 for sl in slotmap.values()]
        cast = f.get('cast') or ''
        meta_bits = [b for b in [country, str(f.get('year') or ''),
                                 ('%d\u2032' % f['length']) if f.get('length') else '',
                                 (f.get('genre') or '').strip()] if b]
        films.append({'id': slugify(title), 'title': title, 'orig': orig,
                      'dir': (f.get('director') or '').strip() or None,
                      'year': f.get('year') or None,
                      'cast': ', '.join(cast.split(', ')[:3]) or None,
                      'meta': ' · '.join(meta_bits) or None,
                      'genre': None, 'url': f.get('URL') or AN_HOME,
                      'poster': f.get('playbill_path') or None,
                      'plot': short_plot(f.get('plot')), 'age': f.get('age') or None,
                      'slots': slots})

    # unisci le versioni (v.o. / doppiato) dello stesso film: stesso slug
    # oppure stessa regia + anno
    groups = []
    for f in films:
        fdir = (f.get('dir') or '').strip().lower()
        fyear = str(f.get('year') or '')
        dkey = (fdir + '|' + fyear) if (fdir and fyear and fyear not in ('None', '0')) else None
        target = None
        for g in groups:
            if g['slug'] == f['id'] or (dkey and g['dkey'] == dkey):
                target = g
                break
        if target is None:
            groups.append({'slug': f['id'], 'dkey': dkey, 'films': [f]})
        else:
            target['films'].append(f)
    merged = []
    for g in groups:
        variants = sorted(g['films'], key=nshows, reverse=True)
        rep = dict(variants[0])
        rep['id'] = g['slug']
        slotmap = {}
        for v in variants:
            for s in v['slots']:
                skey = s['lang']['cat'] + '|' + s['lang']['audio'] + '|' + (s['lang'].get('sub') or '')
                tgt = slotmap.setdefault(skey, {'lang': s['lang'], 'shows': defaultdict(list)})
                for date, lst in s['shows'].items():
                    for item in lst:
                        sig = (item['t'], item.get('hall', ''))
                        if sig not in [(x['t'], x.get('hall', '')) for x in tgt['shows'][date]]:
                            tgt['shows'][date].append(item)
        rep['slots'] = [{'lang': v['lang'],
                         'shows': {k: sorted(x, key=lambda y: y['t'])
                                   for k, x in v['shows'].items() if x}}
                        for v in slotmap.values()]
        for v in variants[1:]:
            for k in ('poster', 'plot', 'orig', 'age', 'dir', 'cast', 'meta'):
                if not rep.get(k) and v.get(k):
                    rep[k] = v[k]
        rep.pop('year', None)
        merged.append(rep)
    log('Anteo Palazzo: %d film in programmazione.' % len(merged))

    # eventi in evidenza sulla home (solo quelli della sede del Palazzo)
    events = []
    try:
        home = fetch(AN_HOME)
        h1s = [(m.start(), m.end(), re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', '', m.group(1)))).strip())
               for m in re.finditer(r'<h1[^>]*>(.*?)</h1>', home, re.S)]
        h2s = [(m.start(), m.end(), re.sub(r'\s+', ' ', htmlmod.unescape(
            re.sub(r'<[^>]+>', ' ', m.group(1)))).strip())
            for m in re.finditer(r'<h2[^>]*>(.*?)</h2>', home, re.S)]
        seen_titles, seen_links = set(), set()
        for i, (hs, he, htitle) in enumerate(h1s):
            block_end = h1s[i + 1][0] if i + 1 < len(h1s) else len(home)
            pick = None
            for s, e, w in h2s:                 # primo h2 «con data» nel blocco di questo h1
                if s >= block_end:
                    break
                if s > he and re.search(r'(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre).{0,90}ore', w, re.I):
                    pick = (e, w)
                    break
            if not pick:
                continue
            e, when = pick
            if re.search(r'citylife|ariosto', when, re.I):
                continue
            tkey = htitle.split('|')[0].strip().lower()[:50]
            if not tkey or tkey in seen_titles:
                continue
            seen_titles.add(tkey)
            lm = re.search(r'href="([^"]+)"', home[e:min(len(home), e + 1500)])
            link = lm.group(1) if lm else ''
            if link and link in seen_links:
                continue
            if link:
                seen_links.add(link)
            events.append('<span class="when">%s</span> — <b>%s</b> %s' % (
                htmlmod.escape(when), htmlmod.escape(htitle.split('|')[0].strip()),
                ('· <a href="%s" target="_blank" rel="noopener">dettagli ↗</a>' % link) if link else ''))
            if len(events) >= 4:
                break
    except Exception as e:
        log('  ! eventi Anteo non disponibili: %s' % e)
    cinema = {
        'id': 'anteo', 'name': 'Anteo Palazzo del Cinema', 'short': 'Anteo Palazzo',
        'tagline': 'La sede di riferimento del circuito spazioCinema/Anteo a Milano: nove sale a due passi da Garibaldi e Brera — d\u2019essai e prima visioni, gran parte in lingua originale sottotitolata.',
        'address': 'Piazza XXV Aprile 8, 20121 Milano',
        'map': 'https://www.google.com/maps/search/?api=1&query=' + urllib.request.quote('Anteo Palazzo del Cinema, Piazza XXV Aprile 8, Milano'),
        'phone': '', 'transport': 'M2/M5 Garibaldi · zona Isola / Brera',
        'site': AN_HOME, 'tickets': AN_TICKETS, 'keepVisible': False,
        'noDayText': 'Nessuno spettacolo in questo giorno.',
        'cineNote': 'In questa pagina solo gli spettacoli della sede di Piazza XXV Aprile (per CityLife, Ariosto e le altre sale del circuito Anteo vedi il sito). Clicca un orario per comprare il biglietto di quello spettacolo.',
        'films': merged,
    }
    if events:
        cinema['extra'] = [{'h': 'Eventi speciali Anteo Palazzo', 'items': events}]
    return cinema, countries


# ------------------------------------------------------------------ MyMovies (arricchimento)
def mymovies_vo_subtitles():
    """title (maiuscolo) → True se il film ha proiezioni "versione originale
    con sottotitoli" al Colosseo secondo MyMovies."""
    try:
        page = fetch(MM_COLOSSEO)
    except Exception as e:
        log('MyMovies: non disponibile (%s) — nessun arricchimento' % e)
        return {}
    out = {}
    marks = list(re.finditer(r'schedine-titolo', page))
    for i, mm in enumerate(marks):
        seg = page[mm.end(): marks[i + 1].start() if i + 1 < len(marks) else len(page)]
        tm = re.search(r'<a[^>]*>(.*?)</a>', seg, re.S)
        if not tm:
            continue
        title = re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', '', tm.group(1)))).strip().upper()
        if title and re.search(r'versione originale con sottotitoli', seg, re.I):
            out[title] = True
    log('MyMovies: %d film con v.o. sottotitolata al Colosseo' % len(out))
    return out


# ------------------------------------------------------------------ Colosseo
def update_colosseo(today, week_keys, prev, other_countries, mm_vo):
    log('Colosseo: leggo la pagina programmazione…')
    page = fetch(CO_PAGE)
    chunks = re.split(r'<div class="filmContainer', page)[1:]
    raw_films, ospiti = {}, []
    seen_ids = set()
    for ch in chunks:
        def grab(cls):
            m = re.search(r'<div class="%s">(.*?)</div>' % cls, ch, re.S)
            return re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', '', m.group(1)))).strip() if m else ''
        idm = re.search(r"idfilm='m?_(\d+)'", ch) or re.search(r'idFilm="(\d+)"', ch)
        fid = idm.group(1) if idm else ''
        if fid and fid in seen_ids:
            continue
        if fid:
            seen_ids.add(fid)
        title = grab('titolo').replace('NEW!', '').strip()
        title = re.sub(r'\s*\[\d{4}\]\s*$', '', title).strip()
        if not title:
            continue
        flags = {'eng': 'FILM IN INGLESE' in title, 'anteprima': 'ANTEPRIMA' in title,
                 'ospiti': 'OSPITI IN SALA' in title}
        for suffix in ('FILM IN INGLESE', 'ANTEPRIMA', 'OSPITI IN SALA'):
            title = re.sub(r'\s*\|\s*' + suffix + r'\s*$', '', title, flags=re.I).strip()
        regia = re.sub(r'^Regia:\s*', '', grab('regia'))
        genere = re.sub(r'^Genere:\s*', '', grab('genere'))
        durata = re.sub(r'^Durata:\s*', '', grab('durata'))
        cast = re.sub(r'^Cast:\s*', '', grab('cast'))
        shows = {}
        nshows = 0
        for lm in re.finditer(r'<div class="dayName">(.*?)</div>(.*?)(?=</li>)', ch, re.S):
            dm = re.search(r'(\d{1,2})/(\d{1,2})', lm.group(1))
            if not dm:
                continue
            d, mo = int(dm.group(1)), int(dm.group(2))
            year = today.year if mo >= today.month else today.year + 1
            key = '%04d-%02d-%02d' % (year, mo, d)
            times = re.findall(r'<span class="orario_"[^>]*>(\d{1,2}:\d{2})</span>', lm.group(2))
            nshows += len(times)
            if times:
                shows.setdefault(key, []).extend(times)
        if nshows == 0:
            continue
        entry = {'title': title, 'regia': regia, 'genere': genere, 'durata': durata,
                 'cast': cast, 'shows': shows, 'poster':
                 ('https://www.ilregnodelcinema.com/cvu/modules/img_switcher.php?idfilm=%s&type=446&ext=jpg' % fid) if fid else None,
                 **flags}
        if flags['ospiti']:
            dm = re.search(r'<div class="dayName">(.*?)</div>', ch)
            when = re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', '', dm.group(1)))).strip() if dm else ''
            ospiti.append('<span class="when">%s</span> — <b>%s</b> · proiezione con ospiti in sala (%s)' % (
                htmlmod.escape(when), htmlmod.escape(title),
                ', '.join(t for k in shows for t in shows[k])))
        else:
            raw_films.setdefault(title.upper(), []).append(entry)
    films = []
    for tkey, variants in raw_films.items():
        base = variants[0]
        slots = []
        for v in variants:
            if v['eng']:
                lang = {'cat': 'eng', 'audio': 'V.O. inglese'}
                if mm_vo.get(tkey):
                    lang['sub'] = 'sott. ITA'
            else:
                country = (other_countries.get(tkey) or '').lower()
                if country and 'italia' not in country:
                    lang = {'cat': 'ita', 'audio': 'In italiano (doppiato)'}
                else:
                    lang = {'cat': 'ita', 'audio': 'In italiano'}
            slots.append({'lang': lang,
                          'shows': {k: sorted(v['shows'][k]) for k in week_keys if v['shows'].get(k)},
                          'anteprima': v['anteprima'] or None})
        slots = [s for s in slots if s['shows']]
        if not slots:
            continue
        films.append({'id': slugify(base['title']), 'title': base['title'],
                      'dir': base['regia'] or None, 'cast': base['cast'] or None,
                      'meta': base['durata'] or None, 'genre': base['genere'] or None,
                      'url': CO_PAGE, 'poster': base.get('poster'),
                      'slots': slots})
    prevendita = []
    for pm in re.finditer(r'<div class="longprog_title">(.*?)</div>\s*<div class="longprog_data">(.*?)</div>', page, re.S):
        pt = re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', '', pm.group(1)))).strip()
        if 'FILM IN INGLESE' in pt.upper():
            continue
        pd = re.sub(r'\s+', ' ', htmlmod.unescape(re.sub(r'<[^>]+>', ' ', pm.group(2)))).strip()
        pd = re.sub(r'^Data di uscita:\s*', '', pd).strip()
        prevendita.append('<b>%s</b> · %s' % (htmlmod.escape(pt), htmlmod.escape(pd)))
    prevendita = [p for i, p in enumerate(prevendita) if p not in prevendita[:i]][:4]
    extra = []
    if ospiti:
        extra.append({'h': 'Eventi al Colosseo', 'items': ospiti[:3]})
    if prevendita:
        extra.append({'h': 'In prevendita al Colosseo', 'items': prevendita})
    return {
        'id': 'colosseo', 'name': 'Multisala Colosseo', 'short': 'Colosseo',
        'tagline': 'Multisala di prima visione verso Porta Romana — i grandi titoli del momento, in italiano e (per molti) anche in versione originale inglese.',
        'address': 'Viale Monte Nero 84, Milano',
        'map': 'https://www.google.com/maps/search/?api=1&query=' + urllib.request.quote('Multisala Colosseo, Viale Monte Nero 84, Milano'),
        'phone': '', 'transport': '',
        'site': CO_PAGE, 'tickets': CO_PAGE, 'keepVisible': False,
        'noDayText': 'Nessuno spettacolo in questo giorno.',
        'cineNote': 'Gli orari sono cliccabili sul loro sito per prenotare.',
        'films': films, 'extra': extra or None,
    }


# ------------------------------------------------------------------ main
def embed_into_index(js_text):
    """mantiene fresca la copia di riserva dei dati dentro index.html
    (usata solo se cinema-data.js non si carica, es. file spostato da solo)"""
    idx = BASE / 'index.html'
    if not idx.exists():
        return
    html = idx.read_text(encoding='utf-8')
    marker = re.compile(r'const EMBEDDED = .*?; /\*EMBED-DATA\*/', re.S)
    if not marker.search(html):
        log('  ! marker EMBED-DATA non trovato in index.html (fallback non aggiornato)')
        return
    html = marker.sub(lambda m: 'const EMBEDDED = ' + js_text + '; /*EMBED-DATA*/', html, count=1)
    idx.write_text(html, encoding='utf-8')
    log('fallback dei dati aggiornato anche dentro index.html')


def main():
    today = now().date()
    week = [today + dt.timedelta(days=i) for i in range(7)]
    week_keys = [day_key(d) for d in week]
    prev = load_previous()
    log('aggiornamento iniziato — oggi è %s' % day_meta(today, today)['long'])

    mm_vo = mymovies_vo_subtitles()

    cinemas, errors = [], []
    try:
        cinemas.append(update_beltrade(today, week_keys, prev))
    except Exception as e:
        errors.append('beltrade: %s' % e)
        log('  ERRORE Beltrade: %s' % e)
    an_countries = {}
    try:
        an, an_countries = update_anteo(today, week_keys, prev)
        cinemas.append(an)
    except Exception as e:
        errors.append('anteo: %s' % e)
        log('  ERRORE Anteo: %s' % e)

    # titoli → paese di produzione (per capire se un film al Colosseo è doppiato)
    other_countries = dict(an_countries)
    for c in cinemas:
        if c.get('id') == 'beltrade':
            for f in c.get('films', []):
                countries = re.sub(r'\d+', '', f.get('meta') or '').replace('·', ' ').replace('′', ' ')
                other_countries[f['title'].upper()] = re.sub(r'\s+', ' ', countries).strip()
    try:
        cinemas.append(update_colosseo(today, week_keys, prev, other_countries, mm_vo))
    except Exception as e:
        errors.append('colosseo: %s' % e)
        log('  ERRORE Colosseo: %s' % e)

    if prev and errors:
        prev_by_id = {c.get('id'): c for c in prev.get('cinemas', [])}
        for cid in ('beltrade', 'anteo', 'colosseo'):
            if not any(c.get('id') == cid for c in cinemas) and prev_by_id.get(cid):
                cinemas.append(prev_by_id[cid])
                log('  ↻ uso i dati del run precedente per %s' % cid)

    data = {
        'updated': now().strftime('%d/%m/%Y %H:%M'),
        'updatedLong': day_meta(today, today)['long'],
        'today': day_key(today),
        'days': [day_meta(d, today) for d in week],
        'cinemas': sorted(cinemas, key=lambda c: ('beltrade', 'anteo', 'colosseo').index(c['id'])),
        'errors': errors or None,
    }
    tmp = DATA_FILE.with_suffix('.tmp')
    js_text = json.dumps(data, ensure_ascii=False, indent=1)
    tmp.write_text('window.DATA = ' + js_text + ';\n', encoding='utf-8')
    tmp.replace(DATA_FILE)
    try:
        embed_into_index(js_text)
    except Exception as e:
        log('  ! aggiornamento fallback in index.html: %s' % e)
    log('scritto %s (%d cinema, %d film totali)' % (
        DATA_FILE.name, len(cinemas), sum(len(c.get('films', [])) for c in cinemas)))
    for e in errors:
        log('avviso: ' + e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
