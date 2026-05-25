# -*- coding: utf-8 -*-
"""币安板块/赛道映射表 + 板块分析"""

COIN_SECTORS = {
    'BTC': ['Layer1', '蓝筹'], 'ETH': ['Layer1', '蓝筹', 'DeFi'], 'BNB': ['Layer1', 'BNB Chain', '蓝筹'],
    'SOL': ['Layer1', 'Solana生态'], 'ADA': ['Layer1'], 'AVAX': ['Layer1'], 'DOT': ['Layer1'],
    'NEAR': ['Layer1', 'AI'], 'ATOM': ['Layer1', 'Cosmos生态'], 'APT': ['Layer1'], 'SUI': ['Layer1'],
    'SEI': ['Layer1'], 'INJ': ['Layer1', 'DeFi'], 'TIA': ['Layer1', 'Modular'], 'FTM': ['Layer1'],
    'TRX': ['Layer1'], 'TON': ['Layer1', 'Ton生态'], 'MINA': ['Layer1', 'ZK'],
    'MATIC': ['Layer2'], 'POL': ['Layer2'], 'ARB': ['Layer2'], 'OP': ['Layer2'],
    'STRK': ['Layer2', 'ZK'], 'ZK': ['Layer2', 'ZK'], 'IMX': ['Layer2', 'GameFi'],
    'UNI': ['DeFi', '蓝筹'], 'AAVE': ['DeFi', '蓝筹'], 'MKR': ['DeFi', 'RWA', '蓝筹'],
    'LINK': ['DeFi', 'Oracle', '蓝筹'], 'CRV': ['DeFi'], 'SUSHI': ['DeFi'],
    'SNX': ['DeFi'], '1INCH': ['DeFi'], 'DYDX': ['DeFi'], 'JUP': ['DeFi'],
    'GMX': ['DeFi'], 'CAKE': ['DeFi'], 'LDO': ['DeFi', 'LSD'], 'PENDLE': ['DeFi', 'LSD'],
    'ENA': ['DeFi'], 'ETHFI': ['DeFi', 'LSD'], 'JTO': ['DeFi'],
    'DOGE': ['Meme', '蓝筹'], 'SHIB': ['Meme'], 'PEPE': ['Meme'], 'WIF': ['Meme'],
    'BONK': ['Meme'], 'FLOKI': ['Meme'], 'BOME': ['Meme'], 'PEOPLE': ['Meme'],
    'TURBO': ['Meme'], 'MEME': ['Meme'], 'NEIRO': ['Meme'],
    'FET': ['AI'], 'RNDR': ['AI', 'Depin'], 'WLD': ['AI'], 'TAO': ['AI'],
    'AKT': ['AI'], 'IO': ['AI', 'Depin'], 'ARKM': ['AI'], 'AI': ['AI'],
    'AXS': ['GameFi'], 'SAND': ['GameFi', 'Metaverse'], 'MANA': ['GameFi', 'Metaverse'],
    'GALA': ['GameFi'], 'ENJ': ['GameFi'], 'PIXEL': ['GameFi'], 'PORTAL': ['GameFi'],
    'HNT': ['Depin'], 'GRT': ['Depin', 'AI'], 'LPT': ['Depin'],
    'ONDO': ['RWA'], 'OM': ['RWA'], 'CFG': ['RWA'], 'RSR': ['RWA'],
    'RPL': ['LSD'], 'SSV': ['LSD'],
    'FIL': ['Storage'], 'STORJ': ['Storage'], 'AR': ['Storage'],
    'PYTH': ['Oracle'], 'BAND': ['Oracle'], 'API3': ['Oracle'], 'TRB': ['Oracle'],
    'BLUR': ['NFT'], 'GMT': ['NFT', 'GameFi'], 'SUPER': ['NFT', 'GameFi'],
    'HIGH': ['Metaverse'], 'ALICE': ['Metaverse'],
    'TIA': ['Modular'], 'DYM': ['Modular'], 'SAGA': ['Modular'],
    'XRP': ['支付'], 'XLM': ['支付'], 'LTC': ['支付', '蓝筹'], 'BCH': ['支付'],
    'ZEC': ['隐私'], 'XMR': ['隐私'],
}

SECTOR_NAMES = {
    'Layer1': '公链', 'Layer2': 'L2扩容', 'DeFi': 'DeFi', 'Meme': 'Meme币',
    'AI': 'AI概念', 'GameFi': '链游', 'NFT': 'NFT', 'Metaverse': '元宇宙',
    'Depin': 'Depin', 'RWA': 'RWA资产', 'LSD': 'LSD/LRT', 'Storage': '存储',
    'Oracle': '预言机', '蓝筹': '蓝筹', 'Modular': '模块化', 'ZK': '零知识证明',
    '支付': '支付', '隐私': '隐私',
}

MAINSTREAM = {'Layer1','Layer2','DeFi','Meme','AI','GameFi','NFT','Metaverse','Depin','RWA','LSD','Storage','Oracle','蓝筹','Modular','ZK','支付','隐私'}


def analyze_sectors(coins):
    """分析各主流板块涨跌情况"""
    sector_data = {}
    for c in coins:
        sym = c['symbol'].upper()
        if sym not in COIN_SECTORS:
            continue
        pct = c.get('change_24h', 0) or 0
        for sec in COIN_SECTORS[sym]:
            if sec not in MAINSTREAM:
                continue
            if sec not in sector_data:
                sector_data[sec] = {'total_pct': 0.0, 'count': 0, 'top_coins': []}
            sector_data[sec]['total_pct'] += pct
            sector_data[sec]['count'] += 1
            sector_data[sec]['top_coins'].append((sym, pct))
            sector_data[sec]['top_coins'].sort(key=lambda x: x[1], reverse=True)
            sector_data[sec]['top_coins'] = sector_data[sec]['top_coins'][:3]
    # Find laggards: coins in hot sectors that haven't moved yet (potential catch-up)
    for sec, data in sector_data.items():
        avg = data['total_pct'] / data['count']
        top_syms = set(s for s, _ in data['top_coins'])
        laggards = []
        for c in coins:
            sym = c['symbol'].upper()
            if sym not in COIN_SECTORS or sec not in COIN_SECTORS[sym]:
                continue
            if sym in top_syms:
                continue
            chg = c.get('change_24h', 0) or 0
            vol = c.get('volume_24h', 0) or 0
            if -2 < chg < 5 and vol >= 200000:
                laggards.append((sym, chg, vol))
        # Enhance laggards with deep data scoring
        import collector as _coll
        enhanced = []
        for sym, chg, vol in laggards[:10]:
            quality = 0
            # 1. OI trend
            try:
                oi_val, oi_chg = _coll.get_open_interest(sym)
                if oi_chg is not None:
                    if oi_chg > 3:
                        quality += 2
                    elif oi_chg > 0:
                        quality += 1
                    elif oi_chg < -3:
                        quality -= 1
            except:
                pass
            # 2. Orderbook
            try:
                ratio, ob_label = _coll.get_orderbook_ratio(sym)
                if ratio >= 1.3:
                    quality += 2
                elif ratio >= 1.1:
                    quality += 1
                elif ratio <= 0.7:
                    quality -= 1
            except:
                pass
            # 3. BTC correlation (low = independent)
            try:
                corr = _coll.get_btc_correlation(sym)
                if corr is not None and corr < 0.5:
                    quality += 2
                elif corr is not None and corr < 0.7:
                    quality += 1
            except:
                pass
            # 4. Price position in 24h range (near low = potential bounce)
            try:
                closes = _coll.get_klines(sym, '1h', 6)
                if len(closes) >= 6:
                    rng_high = max(closes)
                    rng_low = min(closes)
                    if rng_high > rng_low:
                        pos = (closes[-1] - rng_low) / (rng_high - rng_low)
                        if pos < 0.25:
                            quality += 2
                        elif pos < 0.4:
                            quality += 1
                        elif pos > 0.8:
                            quality -= 1
            except:
                pass
            enhanced.append((sym, chg, vol, quality))
        # Sort by quality score descending
        enhanced.sort(key=lambda x: x[3], reverse=True)
        data['laggards'] = [(s, c, v) for s, c, v, q in enhanced[:5]]
        if enhanced:
            print(f'[SECTOR] {sec}: {len(enhanced)} laggards scored, top: {enhanced[0][0]} Q={enhanced[0][3]}')
    results = []
    for sec, data in sector_data.items():
        if data['count'] < 2 or data['total_pct'] / data['count'] < 2.5:
            continue
        avg = data['total_pct'] / data['count']
        name = SECTOR_NAMES.get(sec, sec)
        results.append({
            'sector': sec,
            'name': name,
            'avg_pct': round(avg, 1),
            'count': data['count'],
            'top_coins': data['top_coins'],
            'laggards': data.get('laggards', []),
        })
    results.sort(key=lambda x: (x['avg_pct'] >= 0, abs(x['avg_pct'])), reverse=True)
    return results
