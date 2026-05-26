import requests, re, time, json
from datetime import datetime, timedelta
from config import get_config

_cache_announce = None
_cache_announce_time = 0
_cache_unlocks = None
_cache_unlocks_time = 0


def _proxy():
    url = get_config().get("proxy", "")
    return {"http": url, "https": url} if url else None


def fetch_binance_announcements():
    """爬币安最新公告，返回 [{title, url, date}]"""
    global _cache_announce, _cache_announce_time
    now = time.time()
    if _cache_announce is not None and now - _cache_announce_time < 300:
        return _cache_announce
    
    results = []
    try:
        resp = requests.get(
            "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query",
            params={"type": "1", "pageNo": 1, "pageSize": 20},
            headers={"Accept": "application/json", "Accept-Language": "zh-CN"},
            timeout=10, proxies=_proxy()
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("catalogs", [])
            for cat in items:
                for article in cat.get("articles", []):
                    results.append({
                        "title": article.get("title", ""),
                        "url": f"https://www.binance.com/zh-CN/support/announcement/{article.get('code','')}",
                        "date": datetime.fromtimestamp(article.get("releaseDate", 0) / 1000).strftime("%m-%d %H:%M")
                    })
    except:
        pass
    
    _cache_announce = results
    _cache_announce_time = now
    return results


def fetch_token_unlocks():
    """获取未来48h代币解锁（简化版：使用CoinGecko趋势+手动列表）"""
    global _cache_unlocks, _cache_unlocks_time
    now = time.time()
    if _cache_unlocks is not None and now - _cache_unlocks_time < 600:
        return _cache_unlocks
    
    results = {}
    try:
        # 从CoinGecko获取top币种的解锁数据
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "order": "volume_desc", "per_page": 100, "page": 1},
            timeout=10, proxies=_proxy()
        )
        if resp.status_code == 200:
            for c in resp.json():
                sym = c.get("symbol", "").upper()
                mcap = c.get("market_cap", 0) or 0
                total_supply = c.get("total_supply") or 0
                circ_supply = c.get("circulating_supply") or 0
                if total_supply > circ_supply > 0:
                    locked_pct = round((1 - circ_supply / total_supply) * 100, 1)
                    if locked_pct > 5:
                        results[sym] = {
                            "locked_pct": locked_pct,
                            "note": f"锁仓{locked_pct}%"
                        }
    except:
        pass
    
    _cache_unlocks = results
    _cache_unlocks_time = now
    return results


def match_announcement(coin_symbol, announcements=None):
    """匹配币种相关的币安公告，返回公告标题或空字符串"""
    if announcements is None:
        announcements = fetch_binance_announcements()
    
    sym = coin_symbol.upper()
    for a in announcements[:10]:
        title = a.get("title", "").upper()
        url = a.get("url", "")
        # 直接匹配币名
        if sym in title:
            # 排除太泛的匹配
            title_words = title.split()
            sym_in_word = any(sym == w.strip("(),.!/") for w in title_words)
            sym_partial = sym in title and len(sym) >= 3
            if sym_in_word or sym_partial:
                return a.get("title", "")[:50]
    return ""


def match_unlock(coin_symbol, unlocks=None):
    """匹配代币解锁信息"""
    if unlocks is None:
        unlocks = fetch_token_unlocks()
    
    sym = coin_symbol.upper()
    if sym in unlocks:
        return unlocks[sym].get("note", "")
    return ""


def get_announcement_tags(signals):
    """批量获取所有信号的公告和解锁标签"""
    announcements = fetch_binance_announcements()
    unlocks = fetch_token_unlocks()
    
    for sig in signals:
        coin = sig.get("coin", "")
        if not coin or coin in ("MARKET", "ALTS", "BTC.D"):
            continue
        
        ann = match_announcement(coin, announcements)
        unl = match_unlock(coin, unlocks)
        
        tags = []
        if ann:
            tags.append(f"\U0001f4f0 {ann[:40]}")
        if unl:
            tags.append(f"\U0001f513 {unl}")
        
        sig["event_tags"] = tags

print("announcement.py ready")
