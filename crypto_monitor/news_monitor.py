# -*- coding: utf-8 -*-
"""新闻热点监控
"""
import requests
from config import get_config

def _proxy():
    url = get_config().get('proxy', '')
    return {'http': url, 'https': url} if url else None

def fetch_coingecko_trending():
    try:
        resp = requests.get('https://api.coingecko.com/api/v3/search/trending', timeout=10, proxies=_proxy())
        if resp.status_code != 200: return []
        data = resp.json()
        coins = data.get('coins', [])[:10]
        ids = [c['item']['id'] for c in coins if c.get('item',{}).get('id')]
        # Fetch price changes in batch
        prices = {}
        if ids:
            try:
                pr = requests.get('https://api.coingecko.com/api/v3/simple/price', params={'ids': ','.join(ids), 'vs_currencies': 'usd', 'include_24hr_change': 'true'}, timeout=10, proxies=_proxy())
                if pr.status_code == 200:
                    prices = pr.json()
            except: pass
        results = []
        for coin in coins:
            item = coin.get('item', {})
            name = item.get('name', '')
            symbol = item.get('symbol', '').upper()
            rank = item.get('market_cap_rank', 0)
            cid = item.get('id', '')
            chg = prices.get(cid, {}).get('usd_24h_change')
            if chg is not None:
                direction = '\U0001f7e2' if chg > 0 else '\U0001f534'
                detail = f'{direction} {name}({symbol}) 24h:{chg:+.1f}%'
                if chg > 5: detail += ' \U0001f525'
                elif chg < -5: detail += ' \U0001f4c9'
            else:
                detail = f'{name}({symbol}) #{rank}'
            results.append({'source': 'CoinGecko', 'title': detail, 'symbol': symbol, 'change_24h': chg})
        return results
    except: return []




def fetch_santiment():
    key = get_config().get('santiment_key', '')
    if not key: return []
    try:
        query = '{ trendingWords(size: 10, from: "now-1h", to: "now") { word score } }'
        resp = requests.post('https://api.santiment.net/graphql', json={'query': query}, headers={'Authorization': f'Apikey {key}'}, timeout=10, proxies=_proxy())
        if resp.status_code != 200: return []
        words = resp.json().get('data', {}).get('trendingWords', [])
        return [{'source': 'Santiment', 'title': f'热门词: {w.get("word","")} (热度{w.get("score",0):.0f})'} for w in words[:10]]
    except: return []


def fetch_all_news():
    all_news = []
    cfg = get_config()
    if cfg.get('whale_alert_key'): all_news += fetch_whale_alert()
    if cfg.get('santiment_key'): all_news += fetch_santiment()
    all_news += fetch_coingecko_trending()
    return all_news
