# -*- coding: utf-8 -*-
"""
数据采集模块：币安公开 API + 恐惧贪婪指数
"""
import time
import requests
from config import get_config

def _get_proxy():
    url = get_config().get('proxy', '')
    return {'http': url, 'https': url} if url else None

BINANCE_URL = 'https://api.binance.com/api/v3'

# Weight tracking globals
_weight_used = 0
_weight_minute_start = 0

def _track_weight(w):
    global _weight_used, _weight_minute_start
    now = time.time()
    if now - _weight_minute_start > 60:
        _weight_used = 0
        _weight_minute_start = now
    _weight_used += w

def get_weight_status():
    """Returns (used, limit, remaining_seconds)"""
    global _weight_used, _weight_minute_start
    now = time.time()
    if now - _weight_minute_start > 60:
        _weight_used = 0
        _weight_minute_start = now
    remaining = max(0, 60 - (now - _weight_minute_start))
    return _weight_used, 1200, int(remaining)

_BINANCE_WEIGHTS = {
    '/ticker/24hr': 40,
    '/exchangeInfo': 10,
    '/klines': 1,
    '/depth': 5,
    '/aggTrades': 1,
    '/fapi/v1/premiumIndex': 1,
}

def _get_binance(path, params=None):
    url = f"{BINANCE_URL}{path}"
    headers = {'accept': 'application/json'}
    resp = requests.get(url, params=params, headers=headers, timeout=15, proxies=_get_proxy())
    # Track weight
    w = _BINANCE_WEIGHTS.get(path, 1)
    _track_weight(w)
    if resp.status_code == 429:
        time.sleep(10)
        return _get_binance(path, params)
    resp.raise_for_status()
    return resp.json()

_spot_symbols = None
_margin_symbols = None
_exchange_info_time = 0

def _get_spot_symbols(force_refresh=False):
    global _spot_symbols, _margin_symbols, _exchange_info_time
    now = time.time()
    # Refresh if forced, never loaded, or cache older than 5 minutes
    if force_refresh or _spot_symbols is None or (now - _exchange_info_time > 300):
        data = _get_binance('/exchangeInfo')
        _spot_symbols = set()
        _margin_symbols = set()
        for s in data.get('symbols', []):
            if s.get('status') == 'TRADING' and s.get('isSpotTradingAllowed', False):
                _spot_symbols.add(s['symbol'])
            if s.get('isMarginTradingAllowed', False):
                _margin_symbols.add(s['symbol'])
        _exchange_info_time = now
    return _spot_symbols

def _is_spot(symbol):
    return symbol in _get_spot_symbols()

def can_margin_trade(symbol, force_refresh=False):
    """检查币种在币安是否可借币(全仓/逐仓保证金)"""
    _get_spot_symbols(force_refresh)
    return f'{symbol}USDT' in (_margin_symbols or set())

def get_top_coins(n=100):
    data = _get_binance('/ticker/24hr')
    usdt_pairs = [d for d in data if d['symbol'].endswith('USDT') and not d['symbol'].endswith('UPUSDT') and not d['symbol'].endswith('DOWNUSDT')]
    usdt_pairs = [d for d in usdt_pairs if float(d.get('quoteVolume', 0)) >= 500000 and _is_spot(d['symbol'])]
    usdt_pairs.sort(key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
    coins = []
    for c in usdt_pairs[:n]:
        symbol = c['symbol'][:-4]
        coins.append({
            'id': symbol.lower(),
            'symbol': symbol,
            'name': symbol,
            'price': float(c.get('lastPrice', 0)),
            'market_cap': 0,
            'volume_24h': float(c.get('quoteVolume', 0)),
            'change_1h': float(c.get('priceChangePercent', 0)),
            'change_24h': float(c.get('priceChangePercent', 0)),
            'change_7d': 0,
            'high_24h': float(c.get('highPrice', 0)),
            'low_24h': float(c.get('lowPrice', 0)),
            'amplitude': round((float(c.get('highPrice', 0)) - float(c.get('lowPrice', 0))) / float(c.get('openPrice', 1)) * 100, 2) if float(c.get('openPrice', 0)) > 0 else 0,
        })
    return coins

def get_trending(coins=None):
    """If coins list is provided (from get_top_coins), reuse it to save API call."""
    if coins:
        usdt_pairs = sorted(coins, key=lambda x: x.get('change_24h', 0) or 0, reverse=True)
        result = []
        for idx, c in enumerate(usdt_pairs[:20]):
            result.append({
                'id': c['symbol'].lower(),
                'symbol': c['symbol'],
                'name': c['name'],
                'market_cap_rank': idx + 1,
                'change_pct': c.get('change_24h', 0) or 0,
            })
        return result
    data = _get_binance('/ticker/24hr')
    usdt_pairs = [d for d in data if d['symbol'].endswith('USDT') and not d['symbol'].endswith('UPUSDT') and not d['symbol'].endswith('DOWNUSDT')]
    usdt_pairs = [d for d in usdt_pairs if float(d.get('quoteVolume', 0)) >= 500000 and _is_spot(d['symbol'])]
    usdt_pairs.sort(key=lambda x: float(x.get('priceChangePercent', 0)), reverse=True)
    coins = []
    for idx, c in enumerate(usdt_pairs[:20]):
        symbol = c['symbol'][:-4]
        coins.append({
            'id': symbol.lower(),
            'symbol': symbol,
            'name': symbol,
            'market_cap_rank': idx + 1,
            'change_pct': float(c.get('priceChangePercent', 0)),
        })
    return coins

def get_global_data():
    return {
        'btc_dominance': 0,
        'eth_dominance': 0,
        'total_market_cap': 0,
        'total_volume_24h': 0,
        'fear_greed': _get_fear_greed(),
    }

def _get_fear_greed():
    try:
        resp = requests.get('https://api.alternative.me/fng/', timeout=3, proxies=_get_proxy())
        data = resp.json()
        if data.get('data'):
            val = data['data'][0].get('value', '0')
            return int(val)
    except Exception:
        pass
    return 50

def get_klines(symbol, interval="1h", limit=5):
    try:
        data = _get_binance("/klines", {"symbol": symbol + "USDT", "interval": interval, "limit": limit})
        return [float(k[4]) for k in data]
    except Exception:
        return []

_prev_oi = {}

def get_open_interest(symbol):
    """获取合约持仓量并返回变化方向"""
    global _prev_oi
    _track_weight(1)  # fapi/openInterest
    try:
        resp = requests.get(
            f'https://fapi.binance.com/fapi/v1/openInterest',
            params={'symbol': symbol + 'USDT'},
            timeout=5, proxies=_get_proxy()
        )
        if resp.status_code != 200:
            return None, ''
        oi = float(resp.json().get('openInterest', 0))
        prev = _prev_oi.get(symbol)
        _prev_oi[symbol] = oi
        if prev and prev > 0:
            change = (oi / prev - 1) * 100
            return oi, change
        return oi, None
    except:
        return None, ''


def get_orderbook_ratio(symbol, limit=50):
    """买卖盘深度比: >1 买强, <1 卖强"""
    try:
        data = _get_binance('/depth', {'symbol': symbol + 'USDT', 'limit': limit})
        bids = sum(float(b[1]) for b in data.get('bids', []))
        asks = sum(float(a[1]) for a in data.get('asks', []))
        if asks > 0:
            ratio = round(bids / asks, 2)
            if ratio >= 1.3:
                label = '买盘强'
            elif ratio <= 0.7:
                label = '卖盘强'
            else:
                label = '均衡'
            return ratio, label
        return 1.0, '-'
    except:
        return 1.0, '-'


def get_large_trades(symbol, min_notional=10000):
    """大单成交统计: 返回(买量,卖量,标签)"""
    try:
        data = _get_binance('/aggTrades', {'symbol': symbol + 'USDT', 'limit': 100})
        buy_vol = 0.0
        sell_vol = 0.0
        for t in data:
            price = float(t['p'])
            qty = float(t['q'])
            notional = price * qty
            if notional >= min_notional:
                if t.get('m', False):  # Buyer is maker = sell
                    sell_vol += notional
                else:
                    buy_vol += notional
        if buy_vol + sell_vol == 0:
            return 0, 0, '-'
        buy_ratio = buy_vol / (buy_vol + sell_vol) if (buy_vol + sell_vol) > 0 else 0.5
        if buy_ratio >= 0.6:
            label = '大单净买'
        elif buy_ratio <= 0.4:
            label = '大单净卖'
        else:
            label = '均衡'
        return round(buy_vol, 0), round(sell_vol, 0), label
    except:
        return 0, 0, '-'


_btc_klines_cache = None
_btc_klines_time = 0

def get_btc_correlation(symbol):
    """计算与BTC的1h相关性(-1到1)"""
    global _btc_klines_cache, _btc_klines_time
    try:
        coin_kl = _get_binance('/klines', {'symbol': symbol + 'USDT', 'interval': '1h', 'limit': 24})
        # Cache BTC klines for 5 minutes
        now = time.time()
        if _btc_klines_cache is None or now - _btc_klines_time > 300:
            _btc_klines_cache = _get_binance('/klines', {'symbol': 'BTCUSDT', 'interval': '1h', 'limit': 24})
            _btc_klines_time = now
        btc_kl = _btc_klines_cache
        if len(coin_kl) < 5 or len(btc_kl) < 5:
            return None
        # Calculate returns
        coin_ret = []
        for i in range(len(coin_kl)):
            coin_ret.append(float(coin_kl[i][4]) / float(coin_kl[i][1]) - 1)
        btc_ret = []
        for i in range(len(btc_kl)):
            btc_ret.append(float(btc_kl[i][4]) / float(btc_kl[i][1]) - 1)
        # Pearson correlation
        n = min(len(coin_ret), len(btc_ret))
        if n < 5:
            return None
        mean_c = sum(coin_ret[:n]) / n
        mean_b = sum(btc_ret[:n]) / n
        num = sum((coin_ret[i] - mean_c) * (btc_ret[i] - mean_b) for i in range(n))
        den_c = sum((r - mean_c) ** 2 for r in coin_ret[:n])
        den_b = sum((r - mean_b) ** 2 for r in btc_ret[:n])
        if den_c == 0 or den_b == 0:
            return None
        corr = num / ((den_c * den_b) ** 0.5)
        return round(corr, 2)
    except:
        return None


_market_caps_cache = None
_market_caps_time = 0


def get_funding_rate(symbol):
    """获取永续合约资金费率"""
    try:
        data = _get_binance('/fapi/v1/premiumIndex', {'symbol': symbol + 'USDT'})
        return float(data.get('lastFundingRate', 0)) * 100
    except:
        return None

def get_orderbook_depth(symbol, limit=10):
    """获取买卖盘深度 (前N档)"""
    try:
        data = _get_binance('/depth', {'symbol': symbol + 'USDT', 'limit': str(limit)})
        bids = [(float(b[0]), float(b[1])) for b in data.get('bids', [])[:limit]]
        asks = [(float(a[0]), float(a[1])) for a in data.get('asks', [])[:limit]]
        return bids, asks
    except:
        return [], []

def calc_rsi(closes, period=14):
    """计算RSI"""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_ma(closes):
    """计算MA5/MA10/MA30"""
    result = {}
    for period in [5, 10, 30]:
        if len(closes) >= period:
            result[f'MA{period}'] = sum(closes[-period:]) / period
    return result

def calc_volatility(closes):
    """计算7日波动率 (标准差)"""
    if len(closes) < 7:
        return None
    import statistics
    returns = []
    for i in range(1, len(closes)):
        returns.append((closes[i] / closes[i-1] - 1) * 100)
    return round(statistics.stdev(returns[-7:]) * (252**0.5), 2) if returns else None

def get_market_caps():
    """从CoinGecko获取市值，返回 {symbol: market_cap_usd}"""
    global _market_caps_cache, _market_caps_time
    _track_weight(5)  # CoinGecko
    now = time.time()
    if _market_caps_cache is not None and now - _market_caps_time < 600:
        return _market_caps_cache
    result = {}
    try:
        for page in [1, 2]:
            resp = requests.get(
                'https://api.coingecko.com/api/v3/coins/markets',
                params={'vs_currency': 'usd', 'order': 'volume_desc', 'per_page': 250, 'page': page, 'sparkline': 'false'},
                timeout=15, proxies=_get_proxy()
            )
            if resp.status_code != 200:
                break
            for c in resp.json():
                sym = c.get('symbol', '').upper()
                mcap = c.get('market_cap', 0) or 0
                if sym and mcap > 0:
                    result[sym] = mcap
        _market_caps_cache = result
        _market_caps_time = now
    except:
        pass
    return result

def get_long_short_ratio(symbol):
    try:
        _track_weight(2)  # 2 fapi calls
        global_data = requests.get(
            'https://fapi.binance.com/futures/data/globalLongShortAccountRatio',
            params={'symbol': symbol + 'USDT', 'period': '5m', 'limit': 1},
            timeout=5, proxies=_get_proxy()
        ).json()
        top_data = requests.get(
            'https://fapi.binance.com/futures/data/topLongShortAccountRatio',
            params={'symbol': symbol + 'USDT', 'period': '5m', 'limit': 1},
            timeout=5, proxies=_get_proxy()
        ).json()
        global_ratio = float(global_data[0]['longShortRatio']) if global_data else 1.0
        top_ratio = float(top_data[0]['longShortRatio']) if top_data else 1.0
        global_long_pct = round(global_ratio / (global_ratio + 1) * 100)
        top_long_pct = round(top_ratio / (top_ratio + 1) * 100)
        if top_long_pct > 55 and global_long_pct < 45:
            label = '✅大户吸筹'
        elif top_long_pct < 45 and global_long_pct > 55:
            label = '⚠️散户接盘'
        elif top_long_pct > 55:
            label = '大户偏多'
        elif top_long_pct < 45:
            label = '大户偏空'
        else:
            label = ''
        return top_long_pct, global_long_pct, label
    except:
        return 0, 0, ''

def calc_macd(closes, fast=12, slow=26, signal=9):
    """MACD: 返回 (dif, dea, hist)"""
    if len(closes) < slow + signal:
        return None, None, None
    def ema(data, period):
        k = 2 / (period + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(data[i] * k + result[-1] * (1 - k))
        return result
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    dif = [ema_fast[i] - ema_slow[i] for i in range(len(ema_fast))]
    dea = ema(dif, signal)
    hist = [dif[-1] - dea[-1]]
    return round(dif[-1], 6), round(dea[-1], 6), round(hist[-1], 6)

def calc_bollinger(closes, period=20, std=2):
    """布林带: 返回 (upper, middle, lower, bandwidth%)"""
    if len(closes) < period:
        return None, None, None, None
    import statistics
    middle = sum(closes[-period:]) / period
    stdev = statistics.stdev(closes[-period:])
    upper = middle + std * stdev
    lower = middle - std * stdev
    bw = (upper - lower) / middle * 100 if middle > 0 else 0
    return round(upper, 6), round(middle, 6), round(lower, 6), round(bw, 2)

def calc_obv(closes, volumes):
    """OBV: 量价背离检测"""
    if len(closes) < 2 or len(volumes) < 2:
        return None, None
    obv = 0
    obv_list = [0]
    for i in range(1, min(len(closes), len(volumes))):
        if closes[i] > closes[i-1]:
            obv += volumes[i]
        elif closes[i] < closes[i-1]:
            obv -= volumes[i]
        obv_list.append(obv)
    # Check divergence: price up but OBV down = bearish
    price_trend = closes[-1] > closes[-10] if len(closes) >= 10 else True
    obv_trend = obv_list[-1] > obv_list[-10] if len(obv_list) >= 10 else True
    if price_trend and not obv_trend:
        label = '量价背离(偏空)'
    elif not price_trend and obv_trend:
        label = '量价背离(偏多)'
    else:
        label = ''
    return obv_list[-1] if obv_list else 0, label

def get_liquidation_heatmap():
    """全市场爆仓数据（近24h）"""
    try:
        resp = requests.get('https://fapi.binance.com/futures/data/globalLongShortAccountRatio',
            params={'symbol': 'BTCUSDT', 'period': '5m', 'limit': 1}, timeout=5, proxies=_get_proxy())
        # This is approximate; full liquidation data requires multiple calls
        return None
    except:
        return None

_BINANCE_WEIGHTS.update({
    '/fapi/v1/fundingRate': 1,
    '/fapi/v1/openInterest': 1,
    '/trades': 5,
})

def get_active_buy_sell_ratio(symbol):
    try:
        trades = _get_binance('/aggTrades', {'symbol': symbol + 'USDT', 'limit': 500})
        buy_vol = sum(float(t['qty']) * float(t['price']) for t in trades if not t.get('isBuyerMaker', True))
        sell_vol = sum(float(t['qty']) * float(t['price']) for t in trades if t.get('isBuyerMaker', True))
        total = buy_vol + sell_vol
        if total > 0:
            ratio = buy_vol / total
            if ratio > 0.6: label = '主动买盘强'
            elif ratio < 0.4: label = '主动卖盘强'
            else: label = '买卖均衡'
            return ratio, label, buy_vol, sell_vol
        return 0.5, '-', 0, 0
    except:
        return 0.5, '-', 0, 0

def get_premium_index(symbol):
    try:
        data = _get_binance('/fapi/v1/premiumIndex', {'symbol': symbol + 'USDT'})
        idx = float(data.get('indexPrice', 0))
        mark = float(data.get('markPrice', 0))
        if idx > 0:
            premium = (mark / idx - 1) * 100
            return premium
        return None
    except:
        return None

def get_kline_volumes(symbol, interval="1h", limit=100):
    """获取K线成交量列表"""
    kls = _get_binance("/klines", {"symbol": symbol + "USDT", "interval": interval, "limit": str(limit)})
    return [float(k[5]) for k in kls]
