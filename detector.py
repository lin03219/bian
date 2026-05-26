# -*- coding: utf-8 -*-
"""
信号检测引擎：价格异动、成交量异动、热搜追踪
"""
from datetime import datetime, timedelta

class SignalDetector:
    def __init__(self, config):
        self.cfg = config
        self.price_threshold = config.get('price_change_threshold_pct', 3.5)
        self.volume_threshold = config.get('volume_change_threshold_pct', 100.0)
        self.prev_prices = {}
        self.prev_volumes = {}

    def detect_all(self, coins, global_data, trending_coins):
        signals = []
        signals += self.detect_price_surge(coins)
        signals += self.detect_price_drop(coins)
        signals += self.detect_volume_spike(coins)
        signals += self.detect_fear_greed_extreme(global_data)
        signals += self.detect_trending_newcomers(trending_coins)
        self._update_history(coins)
        return signals

    def detect_price_surge(self, coins):
        results = []
        for c in coins:
            chg = c.get('change_24h') or 0
            if chg >= self.price_threshold:
                results.append({
                    'type': 'price_surge',
                    'direction': 'bullish',
                    'coin': c['symbol'],
                    'name': c['name'],
                    'detail': f"24h暴涨 {chg:.1f}%，现价 ${c['price']:.4f}",
                    'change_pct': chg,
                    'amplitude': c.get('amplitude', 0),
                })
        return results

    def detect_price_drop(self, coins):
        results = []
        for c in coins:
            chg = c.get('change_24h') or 0
            if chg <= -self.price_threshold:
                results.append({
                    'type': 'price_drop',
                    'direction': 'bearish',
                    'coin': c['symbol'],
                    'name': c['name'],
                    'detail': f"24h暴跌 {abs(chg):.1f}%，现价 ${c['price']:.4f}",
                    'change_pct': chg,
                    'amplitude': c.get('amplitude', 0),
                })
        return results

    def detect_volume_spike(self, coins):
        results = []
        for c in coins:
            symbol = c['symbol']
            current_vol = c.get('volume_24h', 0)
            if symbol in self.prev_volumes and self.prev_volumes[symbol] > 0:
                ratio = (current_vol / self.prev_volumes[symbol] - 1) * 100
                if ratio >= self.volume_threshold:
                    direction = 'bullish' if (c.get('change_24h') or 0) >= 0 else 'bearish'
                    results.append({
                        'type': 'volume_spike',
                        'direction': direction,
                        'coin': symbol,
                        'name': c['name'],
                        'detail': f"成交量暴增 {ratio:.0f}%，关注异动",
                        'change_pct': ratio,
                    'amplitude': c.get('amplitude', 0),
                    })
        return results

    def detect_fear_greed_extreme(self, global_data):
        results = []
        fg = global_data.get('fear_greed', 50)
        if fg <= 20:
            results.append({
                'type': 'fear_greed',
                'direction': 'bullish',
                'coin': 'MARKET',
                'name': '全市场',
                'detail': f"恐惧指数 {fg}，极度恐慌，可能是抄底机会",
            })
        elif fg >= 80:
            results.append({
                'type': 'fear_greed',
                'direction': 'bearish',
                'coin': 'MARKET',
                'name': '全市场',
                'detail': f"贪婪指数 {fg}，极度贪婪，注意风险",
            })
        return results

    def detect_trending_newcomers(self, trending_coins):
        results = []
        for c in trending_coins[:5]:
            results.append({
                'type': 'trending_new',
                'direction': 'bullish',
                'coin': c['symbol'],
                'name': c['name'],
                'detail': f"24h涨幅 {c.get('change_pct',0):.1f}%，热门币种",
            })
        return results

    def _update_history(self, coins):
        for c in coins:
            self.prev_prices[c['symbol']] = c.get('price', 0)
            self.prev_volumes[c['symbol']] = c.get('volume_24h', 0)
