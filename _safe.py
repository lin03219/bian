import sys, py_compile
sys.stdout.reconfigure(encoding='utf-8')

L = chr(10)

# PART 1: Add collector functions
print("Part 1: Collector")
cfp = r"C:\Users\L\Documents\Codex\2026-05-23\2-6-token-10-100w-7\crypto_monitor\collector.py"
with open(cfp, "r", encoding="utf-8") as f:
    col = f.read()

insert_at = col.find("def get_kline_volumes")
new_funcs = (
    "def get_active_buy_sell_ratio(symbol):" + L +
    "    try:" + L +
    "        trades = _get_binance('/aggTrades', {'symbol': symbol + 'USDT', 'limit': 500})" + L +
    "        buy_vol = sum(float(t['qty']) * float(t['price']) for t in trades if not t.get('isBuyerMaker', True))" + L +
    "        sell_vol = sum(float(t['qty']) * float(t['price']) for t in trades if t.get('isBuyerMaker', True))" + L +
    "        total = buy_vol + sell_vol" + L +
    "        if total > 0:" + L +
    "            ratio = buy_vol / total" + L +
    "            if ratio > 0.6: label = '主动买盘强'" + L +
    "            elif ratio < 0.4: label = '主动卖盘强'" + L +
    "            else: label = '买卖均衡'" + L +
    "            return ratio, label, buy_vol, sell_vol" + L +
    "        return 0.5, '-', 0, 0" + L +
    "    except:" + L +
    "        return 0.5, '-', 0, 0" + L +
    L +
    "def get_premium_index(symbol):" + L +
    "    try:" + L +
    "        data = _get_binance('/fapi/v1/premiumIndex', {'symbol': symbol + 'USDT'})" + L +
    "        idx = float(data.get('indexPrice', 0))" + L +
    "        mark = float(data.get('markPrice', 0))" + L +
    "        if idx > 0:" + L +
    "            premium = (mark / idx - 1) * 100" + L +
    "            return premium" + L +
    "        return None" + L +
    "    except:" + L +
    "        return None" + L
)
col = col[:insert_at] + new_funcs + L + col[insert_at:]
with open(cfp, "w", encoding="utf-8") as f:
    f.write(col)
py_compile.compile(cfp, doraise=True)
print("  OK")

# PART 2: Modify main.py
print("Part 2: Main")
mfp = r"C:\Users\L\Documents\Codex\2026-05-23\2-6-token-10-100w-7\crypto_monitor\main.py"
with open(mfp, "r", encoding="utf-8") as f:
    ct = f.read()

# 2a: Change 15 -> 10 in deep analysis
ct = ct.replace("signals[:15]", "signals[:10]")
print("  2a: 15->10")

# 2b: Replace old _analyze_signal with _analyze_signal_detailed
old_sig = ct.find("def _analyze_signal(sig):")
old_sig_end = ct.find(L + L + "class MonitorWorker", old_sig)

new_sig = L + L + '''def _analyze_signal_detailed(sig):
    pct = sig.get('change_pct', 0); amp = sig.get('amplitude', 0)
    ob = sig.get('ob_label', ''); lt = sig.get('lt_label', '')
    corr = sig.get('btc_corr'); oi = sig.get('oi_label', '')
    c1 = sig.get('change_1h'); c4 = sig.get('change_4h')
    ls = sig.get('ls_label', ''); score = 0
    reasons_bull = []; reasons_bear = []; reasons_neutral = []
    if pct > 15: score += 3; reasons_bull.append(f'24h\u7206\u6da8{pct:.1f}%')
    elif pct > 8: score += 2; reasons_bull.append(f'24h\u5927\u6da8{pct:.1f}%')
    elif pct > 3: score += 1; reasons_bull.append(f'24h\u6da8{pct:.1f}%')
    elif pct < -15: score -= 3; reasons_bear.append(f'24h\u7206\u8dcc{abs(pct):.1f}%')
    elif pct < -8: score -= 2; reasons_bear.append(f'24h\u5927\u8dcc{abs(pct):.1f}%')
    elif pct < -3: score -= 1; reasons_bear.append(f'24h\u8dcc{abs(pct):.1f}%')
    if c1 is not None and c4 is not None:
        if c1 > 3 and c4 > 5: score += 2; reasons_bull.append(f'1h/4h\u540c\u6b65\u62c9\u5347({c1:.1f}%/{c4:.1f}%)')
        elif c1 > 0 and c4 > 0: score += 1; reasons_bull.append(f'\u77ed\u4e2d\u671f\u5747\u6da8(1h{c1:+.1f}%/4h{c4:+.1f}%)')
        elif c1 < -3 and c4 < -5: score -= 2; reasons_bear.append(f'1h/4h\u52a0\u901f\u4e0b\u8dcc')
        elif c1 < 0 and c4 < 0: score -= 1; reasons_bear.append('\u77ed\u4e2d\u671f\u5747\u8dcc')
        elif c1 > 0 and c4 < 0: reasons_neutral.append('1h\u6da8\u4f464h\u8dcc')
        elif c1 < 0 and c4 > 0: reasons_neutral.append('1h\u56de\u8c03\u4f464h\u4ecd\u6da8')
    if ob and ob != '-':
        if '\u4e70' in str(ob) and '\u5f3a' in str(ob): score += 1; reasons_bull.append('\u76d8\u53e3\u4e70\u76d8\u5f3a')
        elif '\u5356' in str(ob) and '\u5f3a' in str(ob): score -= 1; reasons_bear.append('\u76d8\u53e3\u5356\u76d8\u538b\u5236')
    if oi and oi != '-':
        if '\u591a\u5934\u52a0' in oi: score += 1; reasons_bull.append('OI\u589e+\u4ef7\u6da8\uff0c\u591a\u5934\u52a0\u4ed3')
        elif '\u7a7a\u5934\u5e73' in oi: score += 1; reasons_bull.append('\u7a7a\u5934\u5e73\u4ed3\u624e\u7a7a')
        elif '\u7a7a\u5934\u52a0' in oi: score -= 1; reasons_bear.append('OI\u589e+\u4ef7\u8dcc\uff0c\u7a7a\u5934\u52a0\u4ed3')
        elif '\u591a\u5934\u5e73' in oi: score -= 1; reasons_bear.append('\u591a\u5934\u5e73\u4ed3\u51fa\u9003')
    if corr is not None:
        if corr < 0.3: score += 1; reasons_bull.append(f'BTC\u72ec\u7acb({corr:.2f})')
        elif corr > 0.8: reasons_neutral.append(f'\u8ddf\u968fBTC({corr:.2f})')
    if ls and ls != '-':
        if '\u591a' in ls: reasons_bull.append(f'\u5927\u6237\u504f\u591a({ls})')
        elif '\u7a7a' in ls: reasons_bear.append(f'\u5927\u6237\u504f\u7a7a({ls})')
    if amp > 20: reasons_neutral.append(f'\u632f\u5e45{amp:.0f}%\u504f\u5927')
    elif amp < 2: reasons_neutral.append(f'\u632f\u5e45{amp:.1f}%\u6e05\u6de1')
    # MACD
    macd=sig.get('macd'); macd_sig=sig.get('macd_signal'); macd_hist=sig.get('macd_hist')
    if macd is not None and macd_sig is not None:
        if macd>macd_sig:
            if macd_hist and macd_hist>0: score+=2; reasons_bull.append('MACD\u91d1\u53c9+\u653e\u5927')
            else: score+=1; reasons_bull.append('MACD\u91d1\u53c9')
        elif macd<macd_sig:
            if macd_hist and macd_hist<0: score-=2; reasons_bear.append('MACD\u6b7b\u53c9+\u653e\u5927')
            else: score-=1; reasons_bear.append('MACD\u6b7b\u53c9')
    # Bollinger
    bb_u=sig.get('bb_upper'); bb_l=sig.get('bb_lower')
    if bb_u and bb_l and c1 and amp:
        if c1>5 and amp>10: reasons_bull.append('\u5e03\u6797\u5e26\u5f00\u53e3\u6269\u5927\u504f\u591a')
        elif c1<-5 and amp>10: reasons_bear.append('\u5e03\u6797\u5e26\u5f00\u53e3\u6269\u5927\u504f\u7a7a')
    # OBV
    obv_val=sig.get('obv')
    if obv_val is not None and c1 is not None:
        if c1>0 and obv_val>0: score+=1; reasons_bull.append('OBV\u91cf\u4ef7\u914d\u5408\u826f\u597d')
        elif c1<0 and obv_val<0: score-=1; reasons_bear.append('OBV\u8d44\u91d1\u6d41\u51fa')
        elif c1>0 and obv_val<0: reasons_bear.append('OBV\u80cc\u79bb\uff0c\u6da8\u52bf\u53ef\u7591')
    # MA
    ma_a=sig.get('ma_above'); ma_t=sig.get('ma_total')
    if ma_a is not None and ma_t:
        if ma_a==ma_t: score+=2; reasons_bull.append(f'\u5168\u90e8{ma_t}\u5747\u7ebf\u4e0a\u65b9')
        elif ma_a>ma_t//2: score+=1; reasons_bull.append(f'\u591a\u6570\u5747\u7ebf\u4e0a({ma_a}/{ma_t})')
        elif ma_a==0: score-=2; reasons_bear.append(f'\u5168\u90e8{ma_t}\u5747\u7ebf\u4e0b')
        else: reasons_neutral.append('\u5747\u7ebf\u4e4b\u95f4\u9707\u8361')
    # Active buy/sell
    abr=sig.get('active_buy_ratio')
    if abr:
        if abr>0.65: score+=1; reasons_bull.append(f'\u4e3b\u52a8\u4e70{abr*100:.0f}%')
        elif abr<0.35: score-=1; reasons_bear.append(f'\u4e3b\u52a8\u5356{(1-abr)*100:.0f}%')
    # Premium
    prem=sig.get('premium')
    if prem is not None:
        if prem>0.5: score+=1; reasons_bull.append(f'\u5408\u7ea6\u6ea2\u4ef7{prem:.1f}%')
        elif prem<-0.5: score-=1; reasons_bear.append(f'\u5408\u7ea6\u6298\u4ef7{abs(prem):.1f}%')
    # Short label
    analysis='\u2601\ufe0f\u6b63\u5e38'
    if pct>5 and ob=='\u4e70\u76d8\u5f3a':
        if oi=='\u591a\u5934\u52a0\u4ed3': analysis='\U0001f525\u4e3b\u529b\u62c9\u5347'
        elif corr and corr<0.5: analysis='\U0001f525\u72ec\u7acb\u62c9\u5347'
        else: analysis='\U0001f4c8\u4e3b\u529b\u62c9\u5347'
    elif pct>3:
        if oi=='\u7a7a\u5934\u5e73\u4ed3': analysis='\U0001f504\u7a7a\u5934\u8e29\u8e0f'
        elif corr and corr<0.4: analysis='\U0001f4aa\u72ec\u7acb\u8d70\u5f3a'
        elif ob=='\u4e70\u76d8\u5f3a': analysis='\U0001f4c8\u653e\u91cf\u7a81\u7834'
        else: analysis='\U0001f4c8\u8ddf\u6da8BTC'
    elif -2<pct<=3:
        if amp<2: analysis='\U0001f634\u6a2a\u76d8'
        elif oi=='\u7a7a\u5934\u52a0\u4ed3': analysis='\U0001f53b\u7a7a\u5934\u5e03\u5c40'
        else: analysis='\u27a1\ufe0f\u9707\u8361'
    elif pct<-5 and ob=='\u5356\u76d8\u5f3a':
        if oi=='\u7a7a\u5934\u52a0\u4ed3': analysis='\U0001f6a8\u7a7a\u5934\u7838\u76d8'
        elif corr and corr<0.5: analysis='\U0001f6a8\u72ec\u7acb\u7206\u8dcc'
        else: analysis='\U0001f4c9\u4e3b\u529b\u51fa\u8d27'
    elif pct<-3:
        if oi=='\u591a\u5934\u5e73\u4ed3': analysis='\U0001f3c3\u591a\u5934\u8e29\u8e0f'
        elif corr and corr<0.4: analysis='\U0001f53b\u72ec\u7acb\u8d70\u5f31'
        else: analysis='\U0001f4c9\u8ddf\u8dccBTC'
    # Verdict
    if score>=6: verdict='\U0001f7e2\u5f3a\u70c8\u770b\u6da8'; suggestion='\u591a\u6307\u6807\u5171\u632f\uff0c\u53ef\u987a\u52bf'
    elif score>=3: verdict='\U0001f7e2\u770b\u6da8'; suggestion='\u8d8b\u52bf\u504f\u591a\uff0c\u53ef\u8003\u8651\u5165\u573a'
    elif score>=1: verdict='\U0001f7e1\u504f\u591a'; suggestion='\u7565\u504f\u591a\uff0c\u8f7b\u4ed3\u8bd5\u63a2'
    elif score<=-6: verdict='\U0001f534\u5f3a\u70c8\u770b\u8dcc'; suggestion='\u591a\u6307\u6807\u5171\u632f\u770b\u7a7a\uff0c\u56de\u907f'
    elif score<=-3: verdict='\U0001f534\u770b\u8dcc'; suggestion='\u504f\u7a7a\uff0c\u4e0d\u5b9c\u505a\u591a'
    elif score<=-1: verdict='\U0001f7e0\u504f\u7a7a'; suggestion='\u7a7a\u5934\uff0c\u51cf\u4ed3\u89c2\u671b'
    else: verdict='\u26aa\u9707\u8361'; suggestion='\u65b9\u5411\u4e0d\u660e\uff0c\u89c2\u671b\u7b49\u5f85'
    sig['analysis']=analysis; sig['score']=score; sig['verdict']=verdict
    sig['suggestion']=suggestion; sig['reasons_bull']=reasons_bull
    sig['reasons_bear']=reasons_bear; sig['reasons_neutral']=reasons_neutral
    return analysis'''

ct = ct[:old_sig] + new_sig + ct[old_sig_end:]
print("  2b: _analyze_signal_detailed")

# 2c: Update call site
ct = ct.replace("s['analysis'] = _analyze_signal(s)", "_analyze_signal_detailed(s)")
print("  2c: call site updated")

# 2d: Add MACD/Bollinger/OBV/MA to deep analysis loop
# Find the deep analysis loop
mw_start = ct.find("class MonitorWorker(QThread):")
loop_idx = ct.find("for sym_idx, s in enumerate(signals[:10]):", mw_start)
loop_end = ct.find("            # 综合数据分析", loop_idx)

# Add new metric collection before the existing depth analysis
new_depth = (
    "                # Kline metrics (MACD/Bollinger/OBV/MA)" + L +
    "                try:" + L +
    "                    closes = collector.get_klines(sym, '1h', 35)" + L +
    "                    volumes = collector.get_kline_volumes(sym, '1h', 35)" + L +
    "                    if len(closes) >= 26:" + L +
    "                        macd, signal_v, hist = collector.calc_macd(closes)" + L +
    "                        s['macd'] = macd; s['macd_signal'] = signal_v; s['macd_hist'] = hist" + L +
    "                    if len(closes) >= 20:" + L +
    "                        upper, mid, lower = collector.calc_bollinger(closes)" + L +
    "                        s['bb_upper'] = upper; s['bb_lower'] = lower" + L +
    "                    if len(closes) >= 2 and len(volumes) >= 2:" + L +
    "                        s['obv'] = collector.calc_obv(closes, volumes)" + L +
    "                    mas = collector.calc_ma(closes)" + L +
    "                    if mas:" + L +
    "                        price = s.get('price', closes[-1])" + L +
    "                        above = sum(1 for v in mas.values() if price > v)" + L +
    "                        s['ma_above'] = above; s['ma_total'] = len(mas)" + L +
    "                except:" + L +
    "                    pass" + L +
    "                # Active buy/sell" + L +
    "                try:" + L +
    "                    abr, abl, _, _ = collector.get_active_buy_sell_ratio(sym)" + L +
    "                    s['active_buy_ratio'] = abr" + L +
    "                except:" + L +
    "                    pass" + L +
    "                # Contract premium" + L +
    "                try:" + L +
    "                    s['premium'] = collector.get_premium_index(sym)" + L +
    "                except:" + L +
    "                    pass" + L +
    "                "
)

# Insert before the existing orderbook/correlation code
ct = ct[:loop_idx] + new_depth + ct[loop_idx:]
print("  2d: new metrics added to loop")

with open(mfp, "w", encoding="utf-8") as f:
    f.write(ct)
py_compile.compile(mfp, doraise=True)
print("  main.py OK")

# PART 3: Update notifier
print("Part 3: Notifier")
nfp = r"C:\Users\L\Documents\Codex\2026-05-23\2-6-token-10-100w-7\crypto_monitor\notifier.py"
with open(nfp, "r", encoding="utf-8") as f:
    nf = f.read()

score_line = "entry_lines.append('{} " + chr(92) + "u8bc4" + chr(92) + "u5206 {:+.0f}'.format(verdict, score))"
new_score = "entry_lines.append('---')" + L + "            " + score_line
nf = nf.replace(score_line, new_score)

with open(nfp, "w", encoding="utf-8") as f:
    f.write(nf)
py_compile.compile(nfp, doraise=True)
print("  notifier OK")

print("ALL DONE")
