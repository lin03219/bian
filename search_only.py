
# -*- coding: utf-8 -*-
"""???? - ???????"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QLabel)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
import collector

def analyze_coin(sym):
    """Single coin analysis - returns HTML string"""
    sym = sym.upper().strip()
    try:
        data = collector._get_binance("/ticker/24hr")
        coin_data = None
        for d in data:
            if d["symbol"] == sym + "USDT":
                coin_data = d
                break
        if not coin_data:
            return f'<p style="color:red">\u672a\u627e\u5230 {sym}\uff0c\u8bf7\u68c0\u67e5\u4ee3\u53f7</p>'
        price = float(coin_data["lastPrice"])
        change_24h = float(coin_data["priceChangePercent"])
        high = float(coin_data["highPrice"])
        low = float(coin_data["lowPrice"])
        vol = float(coin_data["quoteVolume"])
        amp = round((high - low) / price * 100, 2)
        clr = lambda v: "green" if v >= 0 else "red"
    except Exception as e:
        return f'<p style="color:red">\u57fa\u7840\u6570\u636e\u83b7\u53d6\u5931\u8d25: {e}</p>'

    c1 = c4 = rsi_1h = None
    mas = {}
    try:
        closes_1h = collector.get_klines(sym, "1h", 35)
        n1h = len(closes_1h)
        c1 = (closes_1h[-1] / closes_1h[-2] - 1) * 100 if n1h >= 2 else None
        c4 = (closes_1h[-1] / closes_1h[-5] - 1) * 100 if n1h >= 5 else None
        rsi_1h = collector.calc_rsi(closes_1h, 14)
        mas = collector.calc_ma(closes_1h)
    except:
        pass

    ob_label = ratio_val = ""
    wall_score = cum_imbalance = 0
    try:
        ratio_val, ob_label = collector.get_orderbook_ratio(sym)
        _, _, cum_imbalance, wall_score = collector.get_orderbook_deep(sym)
    except:
        pass

    funding = oi_chg = None
    ls_label = ""
    try:
        funding = collector.get_funding_rate(sym)
        _, oi_chg = collector.get_open_interest(sym)
        _, _, ls_label = collector.get_long_short_ratio(sym)
    except:
        pass

    corr = None
    try:
        corr = collector.get_btc_correlation(sym)
    except:
        pass

    macd_val = macd_sig = macd_hist = obv_val = None
    premium = active_buy_ratio = lt_label = None
    try:
        closes_1h2 = collector.get_klines(sym, "1h", 35)
        volumes_1h = collector.get_kline_volumes(sym, "1h", 35)
        if len(closes_1h2) >= 26:
            macd_val, macd_sig, macd_hist = collector.calc_macd(closes_1h2)
        if len(closes_1h2) >= 2 and len(volumes_1h) >= 2:
            obv_val, _ = collector.calc_obv(closes_1h2, volumes_1h)
        premium = collector.get_premium_index(sym)
        abr, abl, _, _ = collector.get_active_buy_sell_ratio(sym)
        active_buy_ratio = abr
        lt_label = abl if abl and abl != "-" else ""
    except:
        pass

    # Build data dict for unified scoring
    from main import _compute_unified_score
    d = {
        "change_24h": change_24h, "c1": c1, "c4": c4, "rsi": rsi_1h,
        "mas_dict": mas, "price": price, "ob_label": ob_label,
        "wall_score": wall_score, "cum_imbalance": cum_imbalance,
        "lt_label": lt_label, "btc_corr": corr, "ls_label": ls_label,
        "macd_val": macd_val, "macd_sig": macd_sig, "macd_hist": macd_hist,
        "amp": amp, "obv_val": obv_val,
        "active_buy_ratio": active_buy_ratio, "premium": premium,
        "funding_rate": funding, "oi_chg_pct": oi_chg,
    }
    result = _compute_unified_score(d)
    score = result["score"]
    reasons_bull = result["reasons_bull"]
    reasons_bear = result["reasons_bear"]
    reasons_neutral = result["reasons_neutral"]
    verdict_label = result["verdict"]
    suggestion = result["suggestion"]

    if score >= 6:
        verdict_html = f'<span style="color:green;font-size:22px"><b>{verdict_label}</b></span>'
    elif score >= 3:
        verdict_html = f'<span style="color:green;font-size:22px"><b>{verdict_label}</b></span>'
    elif score >= 1:
        verdict_html = f'<span style="color:#88aa00;font-size:22px"><b>{verdict_label}</b></span>'
    elif score >= -1:
        verdict_html = f'<span style="color:#888;font-size:22px"><b>{verdict_label}</b></span>'
    elif score >= -3:
        verdict_html = f'<span style="color:#cc6600;font-size:22px"><b>{verdict_label}</b></span>'
    elif score >= -6:
        verdict_html = f'<span style="color:red;font-size:22px"><b>{verdict_label}</b></span>'
    else:
        verdict_html = f'<span style="color:red;font-size:22px"><b>{verdict_label}</b></span>'

    def fc(v):
        if v is None: return '<span style="color:#888">-</span>'
        return f'<span style="color:{clr(v)}">{v:+.2f}%</span>'

    lines = []
    lines.append(f'<div style="font-family:sans-serif;padding:10px">')
    lines.append(f'<h2>{sym} \u7efc\u5408\u5206\u6790</h2>')
    lines.append(f'<table><tr>')
    icon = "\U0001f7e2" if score >= 3 else ("\U0001f7e1" if score >= 1 else ("\U0001f534" if score <= -3 else "\u26aa"))
    lines.append(f'<td style="font-size:48px;width:60px;text-align:center">{icon}</td>')
    lines.append(f'<td>{verdict_html} <span style="font-size:14px;color:#888">\u8bc4\u5206 {score:+d}</span><br>')
    lines.append(f'<span style="font-size:13px;color:#555">\U0001f4a1 {suggestion}</span></td></tr></table>')

    if reasons_bull or reasons_bear or reasons_neutral:
        lines.append('<table style="width:100%;margin-top:10px;font-size:13px">')
        for r in reasons_bull:
            lines.append(f'<tr><td style="color:#2e7d32;width:20px">\u2705</td><td style="color:#333;padding:2px 0">{r}</td></tr>')
        for r in reasons_bear:
            lines.append(f'<tr><td style="color:#c62828;width:20px">\u274c</td><td style="color:#333;padding:2px 0">{r}</td></tr>')
        for r in reasons_neutral:
            lines.append(f'<tr><td style="color:#888;width:20px">\u2796</td><td style="color:#666;padding:2px 0">{r}</td></tr>')
        lines.append('</table>')

    lines.append(f'<h3>\u57fa\u7840\u884c\u60c5</h3>')
    lines.append(f'<p><b>\u4ef7\u683c:</b> ${price:.6f} <b style="color:{clr(change_24h)}">24h: {change_24h:+.2f}%</b></p>')
    lines.append(f'<p><b>24h\u9ad8:</b> ${high:.6f} <b>24h\u4f4e:</b> ${low:.6f} <b>\u632f\u5e45:</b> {amp:.1f}%</p>')
    lines.append(f'<p><b>\u6210\u4ea4\u91cf:</b> ${vol:,.0f} USDT</p>')
    lines.append(f'<p><b>1h:</b> {fc(c1)} <b>4h:</b> {fc(c4)}</p>')
    if rsi_1h is not None:
        lines.append(f'<p><b>RSI(1h):</b> {rsi_1h:.1f}</p>')
    if ob_label:
        lines.append(f'<p><b>\u76d8\u53e3:</b> {ob_label} (\u4e70\u5356\u6bd4 {ratio_val})</p>')
    if funding is not None:
        lines.append(f'<p><b>\u8d44\u91d1\u8d39\u7387:</b> {funding:+.4f}%</p>')
    if oi_chg is not None:
        lines.append(f'<p><b>OI\u53d8\u5316:</b> <span style="color:{clr(oi_chg)}">{oi_chg:+.2f}%</span></p>')
    lines.append('</div>')
    return "".join(lines)


class SearchWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("\u65b0\u95fb\u641c\u7d22")
        self.setMinimumSize(550, 600)
        central = QWidget()
        self.setCentralWidget(central)
        lo = QVBoxLayout(central)
        lo.setContentsMargins(15, 15, 15, 15)

        title = QLabel("\U0001f50d \u65b0\u95fb\u641c\u7d22 - \u5e01\u5b89\u5355\u5e01\u5206\u6790")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        lo.addWidget(title)

        hl = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("\u8f93\u5165\u5e01\u79cd\u4ee3\u53f7\uff0c\u5982 BTC\u3001ETH\u3001SOL...")
        self.input.setMinimumHeight(36)
        self.input.returnPressed.connect(self._search)
        hl.addWidget(self.input)

        self.btn = QPushButton("\u5206\u6790")
        self.btn.setMinimumHeight(36)
        self.btn.setMinimumWidth(80)
        self.btn.clicked.connect(self._search)
        hl.addWidget(self.btn)
        lo.addLayout(hl)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setHtml("<p style='color:#888'>\u8f93\u5165\u5e01\u79cd\u4ee3\u53f7\u70b9\u5206\u6790</p>")
        lo.addWidget(self.result)

    def _search(self):
        sym = self.input.text().strip()
        if not sym:
            return
        self.btn.setEnabled(False)
        self.btn.setText("\u5206\u6790\u4e2d...")
        self.result.setHtml("<p>\U0001f504 \u6b63\u5728\u62c9\u53d6\u6570\u636e...</p>")
        QApplication.processEvents()
        try:
            html = analyze_coin(sym)
            self.result.setHtml(html)
        except Exception as e:
            self.result.setHtml(f'<p style="color:red">\u5206\u6790\u5931\u8d25: {e}</p>')
        self.btn.setEnabled(True)
        self.btn.setText("\u5206\u6790")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = SearchWindow()
    w.show()
    sys.exit(app.exec())
