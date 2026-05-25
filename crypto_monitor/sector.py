# -*- coding: utf-8 -*-
"""板块分析 - 从币安API实时获取币种板块归属"""
import requests
import time

TAG_NAMES = {
    "Layer1_Layer2": "公链/L2",
    "defi": "DeFi",
    "AI": "AI概念",
    "Meme": "Meme币",
    "RWA": "RWA资产",
    "Gaming": "链游",
    "Solana": "Solana生态",
    "Payments": "支付",
    "NFT": "NFT",
    "Infrastructure": "基础设施",
    "bnbchain": "BNB Chain",
    "fan_token": "粉丝币",
}

MAINSTREAM_TAGS = set(TAG_NAMES.keys())

_cache_data = None
_cache_time = 0
CACHE_TTL = 600

def _get_proxy():
    try:
        from config import get_config
        url = get_config().get("proxy", "")
        return {"http": url, "https": url} if url else None
    except:
        return None

def _fetch_binance_tags():
    global _cache_data, _cache_time
    now = time.time()
    if _cache_data is not None and now - _cache_time < CACHE_TTL:
        return _cache_data
    try:
        resp = requests.get(
            "https://www.binance.com/bapi/asset/v1/public/asset-service/product/get-products?includeEtf=false",
            timeout=15, proxies=_get_proxy()
        )
        if resp.status_code != 200:
            return _cache_data or {}
        data = resp.json()
        products = data.get("data", [])
        coin_tags = {}
        for p in products:
            symbol = p.get("s", "")
            if not symbol.endswith("USDT"):
                continue
            coin = symbol[:-4]
            tags = [str(t).strip() for t in p.get("tags", []) if str(t).strip() in MAINSTREAM_TAGS]
            if tags:
                coin_tags[coin] = tags
        _cache_data = coin_tags
        _cache_time = now
        return coin_tags
    except Exception as e:
        return _cache_data or {}

def analyze_sectors(coins):
    coin_tags = _fetch_binance_tags()
    sector_data = {}
    for c in coins:
        sym = c["symbol"].upper()
        if sym not in coin_tags:
            continue
        pct = c.get("change_24h", 0) or 0
        for tag in coin_tags[sym]:
            if tag not in MAINSTREAM_TAGS:
                continue
            if tag not in sector_data:
                sector_data[tag] = {"total_pct": 0.0, "count": 0, "top_coins": []}
            sector_data[tag]["total_pct"] += pct
            sector_data[tag]["count"] += 1
            sector_data[tag]["top_coins"].append((sym, pct))
            sector_data[tag]["top_coins"].sort(key=lambda x: x[1], reverse=True)
            sector_data[tag]["top_coins"] = sector_data[tag]["top_coins"][:2]
    for tag, data in sector_data.items():
        top_syms = set(s for s, _ in data["top_coins"])
        laggards = []
        for c in coins:
            sym = c["symbol"].upper()
            if sym not in coin_tags or tag not in coin_tags[sym]:
                continue
            if sym in top_syms:
                continue
            chg = c.get("change_24h", 0) or 0
            vol = c.get("volume_24h", 0) or 0
            if 0 < chg < 8 and vol >= 200000:
                laggards.append((sym, chg, vol))
        import collector as _coll
        enhanced = []
        for sym, chg, vol in laggards[:10]:
            quality = 0
            try:
                oi_val, oi_chg = _coll.get_open_interest(sym)
                if oi_chg is not None:
                    if oi_chg > 3: quality += 2
                    elif oi_chg > 0: quality += 1
                    elif oi_chg < -3: quality -= 1
            except: pass
            try:
                ratio, ob_label = _coll.get_orderbook_ratio(sym)
                if ratio >= 1.3: quality += 2
                elif ratio >= 1.1: quality += 1
                elif ratio <= 0.7: quality -= 1
            except: pass
            try:
                corr = _coll.get_btc_correlation(sym)
                if corr is not None and corr < 0.5: quality += 2
                elif corr is not None and corr < 0.7: quality += 1
            except: pass
            enhanced.append((sym, chg, vol, quality))
        enhanced.sort(key=lambda x: x[3], reverse=True)
        data["laggards"] = [(s, c, v) for s, c, v, q in enhanced[:2]]
    results = []
    for tag, data in sector_data.items():
        if data["count"] < 2 or data["total_pct"] / data["count"] < 2.5:
            continue
        avg = data["total_pct"] / data["count"]
        name = TAG_NAMES.get(tag, tag)
        results.append({
            "sector": tag,
            "name": name,
            "avg_pct": round(avg, 1),
            "count": data["count"],
            "top_coins": data["top_coins"],
            "laggards": data.get("laggards", []),
        })
    results.sort(key=lambda x: x["avg_pct"], reverse=True)
    return results
