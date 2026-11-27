"""The Local Analyst's operations. Each one answers with a data request until the Terminal has supplied everything.

It keeps nothing between calls: every call carries its rule and what the Terminal supplied so far, and the same inputs
ask for the same items (their ids are digests). The one thing it reads itself is a dynamic named list's public URLs
(lists.py), held in memory until the list's refresh interval passes. The one thing it writes itself is the opinion index
(index.py): a stock rule's opinions, once AssetStorage has kept them, for the sentiment strategies. The analysts are the Personas the Terminal lists
(`agents` items, local and remote alike); each job asks a Persona's `articles_summary` pulse, at that Persona's price.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

from phemacast.core.data_requests import AGENTS, MAX_ITEMS, MODEL_DATA, MODEL_SOURCES, REQUEST, SUPPLIED

from . import lists as named_lists, scoring
from .contracts import (ANALYST_PULSE, CALLS_PER_ROUND, CATCH_UP, MAX_TAG_ITEMS, NEWS_FIELDS, NEWS_MODEL, PULSE_INPUT, SCHEMAS,
                        TAG_BATCH, check)

STORE_PULSES = ['asset_put', 'asset_get', 'asset_list']
LISTED = 50  # AssetStorage lists at most 50 at a time, newest first
NEWS_LIMIT = 100
FIRST_LOOK = timedelta(hours=24)  # a tagging rule's first run tags what was published in the last day
# A run keeps up to MAX_TAG_ITEMS // TAG_BATCH batches, saved together, so the one updated last can be any of them:
# the rule's last two runs' batches are listed and the run starts after the newest of them.
RECENT_BATCHES = 2 * -(-MAX_TAG_ITEMS // TAG_BATCH)
MAX_GETS = 12


def request(items, receipt):
    return {'schema': REQUEST, 'requests': items, 'channel_receipt': receipt}


def short(value, limit=300):
    return str(value or '').strip()[:limit]


def failure(entry):
    """Why a supplied item failed, or '' when it completed."""
    if isinstance(entry, dict) and entry.get('status') == 'completed':
        return ''
    return short((entry or {}).get('error') if isinstance(entry, dict) else '', 300) or 'no answer was returned'


def payload(entry):
    return entry.get('payload') if isinstance(entry, dict) and isinstance(entry.get('payload'), dict) else {}


def unavailable(kind, reason, receipt, **extra):
    return {'response': {'kind': kind, 'status': 'unavailable', 'reason': reason, **extra}, 'channel_receipt': receipt}


def key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:20]


def model_data(item_id, agent, pulse, parameters, echo=None):
    return {'id': item_id, 'kind': MODEL_DATA, 'agentId': agent, 'pulse': pulse, 'parameters': parameters, **({'echo': echo} if echo else {})}


def asset_list(store, item_id, tag, limit=LISTED):
    return model_data(item_id, store['agentId'], 'asset_list', {'scope': 'mine', 'owner': 'user', 'asset_type': 'data', 'tag': tag, 'limit': limit})


def asset_get(store, asset):
    return model_data('get-' + key(store['agentId'], asset), store['agentId'], 'asset_get', {'asset_id': asset})


def ask(item_id, analyst, topic, articles, instructions):
    return model_data(item_id, analyst['agentId'], ANALYST_PULSE, {'topic': topic, 'articles': articles, 'instructions': instructions})


def points_of(entry):
    billing = ((entry or {}).get('provenance') or {}).get('billing') or {}
    points = billing.get('points')
    return points if isinstance(points, (int, float)) and not isinstance(points, bool) else 0


def store_name(store):
    return store.get('name') or 'AssetStorage'


# --- choices ---------------------------------------------------------------------------------------------------------
def news_choices(listing):
    rows = []
    for source in listing if isinstance(listing, list) else []:
        if not isinstance(source, dict) or not isinstance(source.get('agentId'), str) or source.get('available') is False:
            continue
        model = next((m for m in source.get('models') or [] if isinstance(m, dict) and m.get('schema') == NEWS_MODEL
                      and isinstance(m.get('modelRef'), dict)), None)
        if model:
            rows.append({'agentId': source['agentId'], 'name': short(source.get('name') or source.get('sourceId'), 80) or 'News',
                         'local': source.get('local') is True or source['agentId'].startswith('local-'), 'modelRef': deepcopy(model['modelRef'])})
    return rows


def choices(supplied, receipt):
    items = [{'id': 'analysts', 'kind': AGENTS, 'pulses': [ANALYST_PULSE]}, {'id': 'stores', 'kind': AGENTS, 'pulses': STORE_PULSES},
             {'id': 'news', 'kind': MODEL_SOURCES, 'models': [NEWS_MODEL]}]
    needed = [item for item in items if item['id'] not in supplied]
    if needed:
        return request(needed, receipt)
    problems = {name: failure(supplied[name]) for name in ('analysts', 'stores', 'news') if failure(supplied[name])}

    def agents(name):
        return [a for a in (supplied[name].get('agents') or []) if isinstance(a, dict) and a.get('agentId')] if name not in problems else []
    found = {'kind': 'choices', 'status': 'ready',
             # Every analyst Persona this Terminal can use, wherever it lives, as the Terminal names it.
             'analysts': [{'agentId': a['agentId'], 'name': short(a.get('name'), 80) or 'Analyst', 'local': a.get('local') is True}
                          for a in agents('analysts')],
             'news': news_choices(supplied['news'].get('sources') if 'news' not in problems else []),
             'stores': [{'agentId': s['agentId'], 'name': short(s.get('name'), 80) or 'AssetStorage', 'local': s.get('local') is True}
                        for s in agents('stores')]}
    # Ready-made named lists the view offers to add (all Taiwan stocks, currencies, industries).
    found['presets'] = deepcopy(named_lists.PRESETS)
    if problems:
        found['notes'] = [f'{name}: {reason}' for name, reason in problems.items()]
    return {'response': found, 'channel_receipt': receipt}


def list_check(params, receipt):
    try:
        found = named_lists.check(params['list'])
    except ValueError as error:
        found = {'status': 'incomplete', 'reason': str(error)[:300], 'sources': []}
    return {'response': {'kind': 'list', 'id': params['list']['id'], **found}, 'channel_receipt': receipt}


# --- tagging ---------------------------------------------------------------------------------------------------------
def news_item(rule):
    source = rule['news']
    return model_data('news-' + key(source['agentId'], rule['id']), source['agentId'], 'data_fetch',
                      {'target_model': deepcopy(source['modelRef']), 'model_request': {'fields': list(NEWS_FIELDS), 'limit': NEWS_LIMIT}})


def rows_of(entry):
    data = payload(entry)
    for path in (('canonical_data', 'items'), ('data', 'items'), ('items',)):
        value = data
        for part in path:
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def rule_lists(params):
    """The rule's named lists, read as entries; ValueError names a list that is missing or cannot be read."""
    rule, given = params['rule'], {x['id']: x for x in params.get('lists') or []}
    found = []
    for list_id in rule.get('lists') or []:
        if list_id not in given:
            raise ValueError('A named list this rule uses is missing; open the rule and choose its lists again.')
        try:
            found.append(named_lists.materialize(given[list_id]))
        except ValueError as error:
            raise ValueError(f'The list "{given[list_id]["name"]}" could not be read: {error}') from error
    return found


def tag(params, supplied, receipt, now, index=None):
    """Tag the items that are new since this rule's last run: its newest kept batch says up to when, and which items."""
    rule, store = params['rule'], params['store']
    if not rule.get('tags') and not rule.get('lists'):
        raise ValueError('A tagging rule needs tags or named lists.')
    try:
        lists = rule_lists(params)
    except ValueError as error:
        return unavailable('tag', str(error), receipt)
    found_in = named_lists.matcher(lists) if lists else None
    last = asset_list(store, 'last-' + key(store['agentId'], rule['id']), scoring.safe_tag('tagrule:' + rule['id']), RECENT_BATCHES)
    news = news_item(rule)
    needed = [item for item in (last, news) if item['id'] not in supplied]
    if needed:
        return request(needed, receipt)
    if failure(supplied[last['id']]):
        return unavailable('tag', store_name(store) + ' did not answer: ' + failure(supplied[last['id']]), receipt)
    if failure(supplied[news['id']]):
        return unavailable('tag', (rule['news'].get('name') or 'The news source') + ' gave no news: ' + failure(supplied[news['id']]), receipt)
    # Not the batch AssetStorage lists first (the one saved last, which may be the run's oldest), but the newest one.
    previous = max((row for row in map(scoring.listed_tagging, payload(supplied[last['id']]).get('assets') or []) if row),
                   key=lambda row: (row['upto'], row['from']), default=None)
    done = set()
    if previous:
        got = asset_get(store, previous['asset_id'])
        if got['id'] not in supplied:
            return request([got], receipt)
        try:
            kept = scoring.document(payload(supplied[got['id']]), scoring.TAGS_SCHEMAS)
            done = {item.get('id') for item in kept.get('items') or []}
            if index is not None:
                index.keep_tags(kept)
        except ValueError:
            done = set()
    since = scoring.moment(previous['upto']) if previous else now - FIRST_LOOK
    fresh = [item for item in scoring.news_items(rows_of(supplied[news['id']]))
             if scoring.moment(item['published_at']) >= since and item['id'] not in done]
    left = max(0, len(fresh) - MAX_TAG_ITEMS)
    fresh = fresh[:MAX_TAG_ITEMS]  # oldest first, so the next run starts where this one stops
    batches = [fresh[start:start + TAG_BATCH] for start in range(0, len(fresh), TAG_BATCH)]
    asks, results, points = [], [], 0
    for batch in batches:
        task = key(rule['id'], rule['analyst']['agentId'], rule['tags'], [x['name'] for x in lists], [item['id'] for item in batch])
        candidates = {index: found_in.find(item['title'] + '\n' + (item.get('summary') or '')) for index, item in enumerate(batch)} if lists else None
        entry = supplied.get('tag-' + task)
        if entry is None:
            asks.append(ask('tag-' + task, rule['analyst'], 'Tag news', scoring.articles(batch, numbered=True, candidates=candidates),
                            scoring.entity_instructions(rule['tags'], [x['name'] for x in lists]) if lists
                            else scoring.tag_instructions(rule['tags'])))
            continue
        points += points_of(entry)
        if failure(entry):
            results.append({'status': 'failed', 'items': len(batch), 'reason': failure(entry)})
            continue
        try:
            if lists:
                said = scoring.parse_entities(scoring.reply_text(payload(entry)), len(batch), rule['tags'], candidates, found_in)
                tagged = [{**item, **said.get(index, {'tags': [], 'entities': []})} for index, item in enumerate(batch)]
            else:
                found = scoring.parse_tags(scoring.reply_text(payload(entry)), len(batch), rule['tags'])
                tagged = [{**item, 'tags': found.get(index, [])} for index, item in enumerate(batch)]
        except ValueError as error:
            results.append({'status': 'unreadable', 'items': len(batch), 'reason': str(error)})
            continue
        put = supplied.get('put-' + task)
        if put is None:
            asks.append(model_data('put-' + task, store['agentId'], 'asset_put', scoring.tagging_asset(rule, tagged, now, lists)))
            continue
        row = {'items': len(batch), 'tagged': sum(1 for item in tagged if item['tags']),
               'tags': sorted({t for item in tagged for t in item['tags']}),
               **({'entities': len({(m['list'], m['code'] or m['name']) for item in tagged for m in item['entities']})} if lists else {})}
        results.append({**row, 'status': 'not_saved', 'reason': failure(put)} if failure(put) else {**row, 'status': 'saved'})
        if index is not None and not failure(put):  # what AssetStorage kept is indexed for readers of a story's tags
            index.keep_tags({'rule': rule['id'], 'analyst': rule['analyst'], 'items': tagged, 'tagged_at': scoring.stamp(now)})
    if asks:
        saves = [a for a in asks if a['id'].startswith('put-')]
        calls = [a for a in asks if a['id'].startswith('tag-')][:CALLS_PER_ROUND]
        return request((saves + calls)[:MAX_ITEMS], receipt)
    notes = [f'{x["name"]}: {note}' for x in lists for note in x['notes']]
    return {'response': {'kind': 'tag', 'status': 'ready', 'rule': rule['id'], 'new': len(fresh), 'batches': results, 'left': left,
                         'since': scoring.stamp(since), 'points': points,
                         **({'lists': [{'name': x['name'], 'entries': len(x['entries']), 'fetched_at': x['fetched_at']} for x in lists]} if lists else {}),
                         **({'notes': notes} if notes else {})}, 'channel_receipt': receipt}


# --- sentiment -------------------------------------------------------------------------------------------------------
def score(params, supplied, receipt, now, index=None):
    """Score each of the last CATCH_UP complete periods not kept yet, from the news tagged with this rule's tag."""
    rule, store, language = params['rule'], params['store'], params.get('language', 'en')
    kept = asset_list(store, 'kept-' + key(store['agentId'], rule['id']), scoring.safe_tag('sentrule:' + rule['id']))
    tagged = asset_list(store, 'tagged-' + key(store['agentId'], rule['tag']), scoring.tag_key(rule['tag']))
    first = [kept, {**tagged, 'echo': {'windows': scoring.windows(now, rule['period_hours'], CATCH_UP)}}]
    needed = [item for item in first if item['id'] not in supplied]
    if needed:
        return request(needed, receipt)
    for item in first:
        if failure(supplied[item['id']]):
            return unavailable('score', store_name(store) + ' did not answer: ' + failure(supplied[item['id']]), receipt)
    # The periods are fixed by the first call: every later round reads them back from that item's echo.
    spans = (supplied[tagged['id']].get('echo') or {}).get('windows') or first[1]['echo']['windows']
    done = {}
    for asset in payload(supplied[kept['id']]).get('assets') or []:
        row = scoring.listed_sentiment(asset)
        if row:
            done.setdefault(row['window_start'], row)
    batches = [row for row in map(scoring.listed_tagging, payload(supplied[tagged['id']]).get('assets') or []) if row]
    pending = [w for w in spans if w['start'] not in done]
    # Only the tagging batches whose time span meets a pending period are read.
    wanted = [b for b in batches if any(b['from'] < w['end'] and b['upto'] >= w['start'] for w in pending)][:MAX_GETS]
    gets = [asset_get(store, b['asset_id']) for b in wanted]
    needed = [item for item in gets if item['id'] not in supplied]
    if needed:
        return request(needed, receipt)
    items = {}
    for item in gets:
        if failure(supplied[item['id']]):
            return unavailable('score', store_name(store) + ' did not answer: ' + failure(supplied[item['id']]), receipt)
        try:
            batch = scoring.document(payload(supplied[item['id']]), scoring.TAGS_SCHEMAS)
            if index is not None:
                index.keep_tags(batch)
            for news in batch.get('items') or []:
                if isinstance(news, dict) and rule['tag'] in (news.get('tags') or []) and news.get('id'):
                    items.setdefault(news['id'], news)
        except ValueError:
            continue
    results, asks, points = [], [], 0
    for window in spans:
        base = {'window_start': window['start'], 'window_end': window['end']}
        if window['start'] in done:
            results.append({**base, 'status': 'kept', **{k: done[window['start']][k] for k in ('asset_id', 'score', 'label', 'comment')}})
            continue
        start, end = scoring.moment(window['start']), scoring.moment(window['end'])
        found = sorted((i for i in items.values() if (when := scoring.moment(i.get('published_at'))) and start <= when < end),
                       key=lambda i: (i['published_at'], i['id']))[-scoring.MAX_PERIOD_ITEMS:]
        if not found:
            results.append({**base, 'status': 'no_news', 'articles': 0})
            continue
        task = key(rule['id'], rule['analyst']['agentId'], rule['tag'], window['start'], [i['id'] for i in found])
        entry = supplied.get('score-' + task)
        if entry is None:
            asks.append(ask('score-' + task, rule['analyst'], rule['tag'], scoring.articles(found),
                            scoring.sentiment_instructions(rule['tag'], window, language)))
            continue
        points += points_of(entry)
        base['articles'] = len(found)
        if failure(entry):
            results.append({**base, 'status': 'failed', 'reason': failure(entry)})
            continue
        try:
            said = scoring.parse_opinion(scoring.reply_text(payload(entry)))
        except ValueError as error:
            results.append({**base, 'status': 'unreadable', 'reason': str(error)})
            continue
        put = supplied.get('put-' + task)
        if put is None:
            asks.append(model_data('put-' + task, store['agentId'], 'asset_put', scoring.sentiment_asset(rule, window, found, said, now)))
            continue
        row = {**base, 'score': said['sentiment']['score'], 'label': said['sentiment']['label'], 'comment': said['comment']}
        results.append({**row, 'status': 'not_saved', 'reason': failure(put)} if failure(put)
                       else {**row, 'status': 'saved', 'asset_id': (payload(put).get('asset') or {}).get('asset_id')})
    if asks:
        saves = [a for a in asks if a['id'].startswith('put-')]
        calls = [a for a in asks if a['id'].startswith('score-')][:CALLS_PER_ROUND]
        return request((saves + calls)[:MAX_ITEMS], receipt)
    return {'response': {'kind': 'score', 'status': 'ready', 'rule': rule['id'], 'tag': rule['tag'], 'results': results, 'points': points},
            'channel_receipt': receipt}


# --- per-stock news sentiment ---------------------------------------------------------------------------------------
def stock_score(params, supplied, receipt, now, index=None):
    """Score, per member, the news a tagging run found members of this rule's list in, since the rule's newest kept batch."""
    rule, store = params['rule'], params['store']
    named = params['lists'][0]
    if named['id'] != rule['list']:
        raise ValueError('The named list this rule uses is missing; open the rule and choose its list again.')
    list_name = named['name']
    kept = asset_list(store, 'stockkept-' + key(store['agentId'], rule['id']), scoring.safe_tag('stockrule:' + rule['id']), RECENT_BATCHES)
    tagged = asset_list(store, 'stocktagged-' + key(store['agentId'], list_name), scoring.tag_key(list_name))
    # A first run's start is fixed by its first call: every later round reads it back from that item's echo.
    first = [{**kept, 'echo': {'since': scoring.stamp(now - FIRST_LOOK)}}, tagged]
    needed = [item for item in first if item['id'] not in supplied]
    if needed:
        return request(needed, receipt)
    for item in first:
        if failure(supplied[item['id']]):
            return unavailable('stock', store_name(store) + ' did not answer: ' + failure(supplied[item['id']]), receipt)
    previous = max((row for row in map(scoring.listed_stock, payload(supplied[kept['id']]).get('assets') or []) if row),
                   key=lambda row: (row['upto'], row['from']), default=None)
    done = set()
    if previous:
        got = asset_get(store, previous['asset_id'])
        if got['id'] not in supplied:
            return request([got], receipt)
        try:
            done = {item.get('id') for item in scoring.document(payload(supplied[got['id']]), (scoring.STOCK_SCHEMA,)).get('items') or []}
        except ValueError:
            done = set()
    since = scoring.moment(previous['upto'] if previous else (supplied[kept['id']].get('echo') or {}).get('since')) or now - FIRST_LOOK
    batches = sorted((row for row in map(scoring.listed_tagging, payload(supplied[tagged['id']]).get('assets') or [])
                      if row and scoring.moment(row['upto']) >= since), key=lambda row: (row['from'], row['upto']))[:MAX_GETS]
    gets = [asset_get(store, row['asset_id']) for row in batches]
    needed = [item for item in gets if item['id'] not in supplied]
    if needed:
        return request(needed, receipt)
    items = {}
    for item in gets:
        if failure(supplied[item['id']]):
            return unavailable('stock', store_name(store) + ' did not answer: ' + failure(supplied[item['id']]), receipt)
        try:
            found = scoring.document(payload(supplied[item['id']]), scoring.TAGS_SCHEMAS)
        except ValueError:
            continue
        if index is not None:
            index.keep_tags(found)
        source = str((found.get('news_source') or {}).get('agentId') or '')
        for news in found.get('items') or []:
            if not isinstance(news, dict) or not news.get('id') or news['id'] in done:
                continue
            published, members = scoring.moment(news.get('published_at')), scoring.list_members(news, list_name)
            if members and published and published >= since:
                items.setdefault(news['id'], {**{k: news[k] for k in ('id', 'title', 'published_at', 'publisher', 'url', 'summary') if k in news},
                                              'news_source': source, 'members': members})
    fresh = sorted(items.values(), key=lambda news: (news['published_at'], news['id']))
    left = max(0, len(fresh) - MAX_TAG_ITEMS)
    fresh = fresh[:MAX_TAG_ITEMS]  # oldest first, so the next run starts where this one stops
    asks, results, points, indexed = [], [], 0, 0
    for batch in (fresh[start:start + TAG_BATCH] for start in range(0, len(fresh), TAG_BATCH)):
        task = key('stock', rule['id'], rule['analyst']['agentId'], list_name, [news['id'] for news in batch])
        members = {position: news['members'] for position, news in enumerate(batch)}
        entry = supplied.get('stock-' + task)
        if entry is None:
            asks.append(ask('stock-' + task, rule['analyst'], list_name + ' news', scoring.stock_articles(batch, members),
                            scoring.stock_instructions(list_name)))
            continue
        points += points_of(entry)
        if failure(entry):
            results.append({'status': 'failed', 'items': len(batch), 'reason': failure(entry)})
            continue
        try:
            said = scoring.parse_stock_opinions(scoring.reply_text(payload(entry)), members)
        except ValueError as error:
            results.append({'status': 'unreadable', 'items': len(batch), 'reason': str(error)})
            continue
        scored = [{**{k: v for k, v in news.items() if k not in ('members', 'summary')}, 'opinions': said.get(position, [])}
                  for position, news in enumerate(batch)]
        put = supplied.get('put-' + task)
        if put is None:
            # The time it was scored goes with the save, so the index keeps the same time as the kept file.
            asks.append(model_data('put-' + task, store['agentId'], 'asset_put', scoring.stock_asset(rule, list_name, scored, now),
                                   echo={'analyzed_at': scoring.stamp(now)}))
            continue
        row = {'items': len(batch), 'opinions': sum(len(news['opinions']) for news in scored),
               'members': len({m['code'] for news in scored for m in news['opinions']})}
        if failure(put):
            results.append({**row, 'status': 'not_saved', 'reason': failure(put)})
            continue
        if index is not None:
            analyzed = scoring.moment((put.get('echo') or {}).get('analyzed_at')) or now
            indexed += index.keep(rule['id'], rule['analyst'], list_name, scored, analyzed)
        results.append({**row, 'status': 'saved', 'asset_id': (payload(put).get('asset') or {}).get('asset_id')})
    if asks:
        saves = [a for a in asks if a['id'].startswith('put-')]
        calls = [a for a in asks if a['id'].startswith('stock-')][:CALLS_PER_ROUND]
        return request((saves + calls)[:MAX_ITEMS], receipt)
    return {'response': {'kind': 'stock', 'status': 'ready', 'rule': rule['id'], 'list': list_name, 'new': len(fresh),
                         'left': left, 'since': scoring.stamp(since), 'batches': results, 'points': points,
                         'indexed': indexed if index is not None else None}, 'channel_receipt': receipt}


# --- history and detail ----------------------------------------------------------------------------------------------
def history(params, supplied, receipt):
    store, limit = params['store'], params.get('limit', 40)
    sentiments = asset_list(store, 'history-' + key(store['agentId'], 's'), scoring.SENTIMENT_TAG, limit)
    taggings = asset_list(store, 'history-' + key(store['agentId'], 't'), scoring.TAGGING_TAG, 20)
    stocks = asset_list(store, 'history-' + key(store['agentId'], 'k'), scoring.STOCK_TAG, 20)
    needed = [item for item in (sentiments, taggings, stocks) if item['id'] not in supplied]
    if needed:
        return request(needed, receipt)
    for item in (sentiments, taggings, stocks):
        if failure(supplied[item['id']]):
            return unavailable('history', store_name(store) + ' did not answer: ' + failure(supplied[item['id']]), receipt)
    rows = [r for r in map(scoring.listed_sentiment, payload(supplied[sentiments['id']]).get('assets') or []) if r]
    tagged = [r for r in map(scoring.listed_tagging, payload(supplied[taggings['id']]).get('assets') or []) if r]
    rows.sort(key=lambda r: (r['window_start'], r['tag'], r['analyst']), reverse=True)
    tagged.sort(key=lambda r: r['upto'], reverse=True)
    scored = sorted((r for r in map(scoring.listed_stock, payload(supplied[stocks['id']]).get('assets') or []) if r),
                    key=lambda r: r['upto'], reverse=True)
    return {'response': {'kind': 'history', 'status': 'ready', 'rows': rows, 'tagging': tagged, 'stock': scored}, 'channel_receipt': receipt}


def detail(params, supplied, receipt):
    store = params['store']
    item = asset_get(store, params['asset_id'])
    entry = supplied.get(item['id'])
    if entry is None:
        return request([item], receipt)
    if failure(entry):
        return unavailable('detail', store_name(store) + ' did not answer: ' + failure(entry), receipt)
    try:
        found = scoring.document(payload(entry))
    except ValueError as error:
        return unavailable('detail', str(error), receipt)
    return {'response': {'kind': 'detail', 'status': 'ready', 'asset_id': params['asset_id'], 'record': found}, 'channel_receipt': receipt}


def dispatch(data, now=None, index=None):
    """The pulse: one envelope, answered with a data request, a result or an error."""
    receipt = data.get('request_key') if isinstance(data, dict) else None
    try:
        data = check(PULSE_INPUT, data)
        operation, supplied = data['operation'], data.get(SUPPLIED) or {}
        if operation not in SCHEMAS:
            raise ValueError('Choose a Local Analyst operation.')
        params = check(SCHEMAS[operation], data['parameters'])
        now = now or datetime.now(timezone.utc)
        if operation == 'analyst_choices':
            return choices(supplied, data['request_key'])
        if operation == 'analyst_tags':
            return {'response': {'kind': 'tags', 'status': 'ready', 'items': index.tags_for(params['urls']) if index is not None else []},
                    'channel_receipt': data['request_key']}
        if operation == 'analyst_tag':
            return tag(params, supplied, data['request_key'], now, index)
        if operation == 'analyst_score':
            return score(params, supplied, data['request_key'], now, index)
        if operation == 'analyst_stock_score':
            return stock_score(params, supplied, data['request_key'], now, index)
        if operation == 'analyst_history':
            return history(params, supplied, data['request_key'])
        if operation == 'analyst_list_check':
            return list_check(params, data['request_key'])
        return detail(params, supplied, data['request_key'])
    except ValueError as error:
        return {'error': str(error)[:300], **({'channel_receipt': receipt} if isinstance(receipt, str) else {})}
