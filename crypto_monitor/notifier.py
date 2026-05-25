# -*- coding: utf-8 -*-
"""
推送模块：钉钉 / 飞书群机器人 Webhook
"""
import json, hmac, hashlib, base64, time, urllib.parse
from datetime import datetime
import requests
from config import get_config


def _fmt_pct(v):
    if v is None:
        return '-'
    return f'{v:+.1f}%'


def _make_summary(score, reasons_bull, reasons_bear):
    """G版：根据评分和因子生成简短判断"""
    if score >= 6:
        return "多指标共振，趋势多"
    elif score >= 4:
        bull_short = reasons_bull[0] if reasons_bull else "放量突破"
        return f"{bull_short[:8]}，做多信号"
    elif score >= 2:
        if reasons_bull:
            return f"{reasons_bull[0][:8]}，偏多"
        return "短期偏多，可关注"
    elif score >= 1:
        return "略偏多，轻仓试"
    elif score <= -6:
        return "全面看空，回避"
    elif score <= -4:
        bear_short = reasons_bear[0] if reasons_bear else "趋势走弱"
        return f"{bear_short[:8]}，离场信号"
    elif score <= -2:
        if reasons_bear:
            return f"{reasons_bear[0][:8]}，偏空"
        return "短期偏空，减仓"
    elif score <= -1:
        return "略偏空，观望"
    else:
        return "无信号，继续等"


def _check_accumulation(sig):
    """C版：检测庄家建仓信号 (≥3条触发)"""
    pct = sig.get("change_pct", 0)
    oi = sig.get("oi_label", "")
    lt = sig.get("lt_label", "")
    ob = sig.get("ob_label", "")
    ws = sig.get("wall_score", 0)
    fr = sig.get("funding_rate")
    ls = sig.get("ls_label", "")
    hints = []
    score = 0
    if oi in ("多头加仓", "空头平仓") and -2 < pct < 2:
        hints.append("OI↑"); score += 1
    if lt == "大单净买":
        hints.append("大单买"); score += 1
    if ob == "买盘强" or ws >= 1:
        hints.append("盘口托"); score += 1
    if fr is not None and fr < -0.005 and pct > -3:
        hints.append("费率负"); score += 1
    if ls and "多" in ls:
        hints.append(ls); score += 1
    if score >= 3:
        return " | 🏗建仓: " + "/".join(hints)
    return ""


class Notifier:

    def __init__(self, config):
        self.channel = config.get('channel', 'dingtalk')
        self.webhook_url = config.get('webhook_url', '')
        self.dingtalk_secret = config.get('dingtalk_secret', '')
        self.feishu_secret = config.get('feishu_secret', '')
        self.last_push_time = 0

    def is_configured(self):
        return bool(self.webhook_url)

    def send(self, signal):
        if not self.webhook_url:
            return False
        if self.channel == 'dingtalk':
            ok, _ = self._send_dingtalk(signal)
            return ok
        elif self.channel == 'feishu':
            ok, _ = self._post_feishu(signal.get('coin','') + ': ' + signal.get('detail',''))
            return ok
        return False

    def send_batch(self, signals):
        if not signals:
            return True, ''
        if self.channel == 'dingtalk':
            return self._send_dingtalk_batch(signals)
        elif self.channel == 'feishu':
            return self._send_feishu_batch_text(signals)
        return True, ''

    def _sign_dingtalk_url(self, url):
        secret = self.dingtalk_secret
        if not secret:
            return url
        ts = str(round(time.time() * 1000))
        string_to_sign = ts + chr(10) + secret
        hmac_code = hmac.new(
            secret.encode(),
            string_to_sign.encode(),
            hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode())
        sep = '&' if '?' in url else '?'
        return f'{url}{sep}timestamp={ts}&sign={sign}'

    def _sign_feishu_url(self, url):
        secret = self.feishu_secret.strip()
        if not secret:
            return url
        ts = str(int(time.time()))
        # Feishu: timestamp+newline+secret as HMAC key, empty message
        string_to_sign = f'{ts}\n{secret}'
        hmac_code = hmac.new(
            string_to_sign.encode('utf-8'),
            b'',
            hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode('utf-8'))
        sep = '&' if '?' in url else '?'
        return f'{url}{sep}timestamp={ts}&sign={sign}'

    def _send_dingtalk(self, signal):
        if not self.webhook_url:
            return False, ''
        return self._send_dingtalk_batch([signal])

    def _send_dingtalk_batch(self, signals):
        if not self.webhook_url or not signals:
            return False, ''
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        lines = [f'{ts}', '']
        # Collect signals by direction
        bullish_sigs = []
        bearish_sigs = []
        neutral_sigs = []
        overview_line = ''
        for sig in signals[:15]:
            typ = sig.get('type', '')
            if typ == 'market_overview':
                bullish = sig.get('bullish', 0)
                bearish = sig.get('bearish', 0)
                fg = sig.get('fear_greed', 50)
                fg_label = '恐慌' if fg <= 40 else ('中性' if fg <= 60 else '贪婪')
                fg_emoji = '😱' if fg <= 40 else ('😐' if fg <= 60 else '😈')
                overview_line = f'利好{bullish} | 利空{bearish} | 恐惧贪婪 {fg}{fg_emoji}'
                continue
            if typ == 'sector':
                continue
            if typ not in ('price_surge', 'price_drop', 'volume_spike', 'fear_greed', 'trending_new'):
                continue
            if sig.get('btc_corr', 0) and sig['btc_corr'] > 0.7:
                continue
            coin = sig.get('coin', '')
            def _cp(v):
                if v is None: return ('-', '#000000')
                return (s, '#00AA00' if v > 0 else '#DD0000' if v < 0 else '#000000')
            s1, clr1 = _cp(c1)
            s4, clr4 = _cp(c4)
            s4, clr4 = _cp(c4)
            ob = sig.get('ob_label', '')
            ob_tag = ''
            if ob and ob != '-':
                c = '#00AA00' if '买' in ob else ('#DD0000' if '卖' in ob else '#888888')
                ob_tag = f'<font color={c}>{ob}</font>'
            lt = sig.get('lt_label', '')
            lt_tag = ''
            if lt and lt != '-':
                c = '#00AA00' if '买' in lt else ('#DD0000' if '卖' in lt else '#888888')
                lt_tag = f'<font color={c}>{lt}</font>'
            corr = sig.get('btc_corr')
            corr_tag = ''
            if corr is not None and corr > 0.8:
                corr_tag = f'corr:<font color=#DD0000>{corr:.1f}</font>'
            # Build compact line: 币名 1h/2h/8h 振幅 盘口 大单 BTC 总结
            parts = []
            parts.append(f'**{coin}**')
            parts.append(f'<font color={clr1}>{s1}</font></font>')
            extra = []
            if amp > 0:
                extra.append(f'4h振幅{amp:.0f}%')
            if ob_tag:
                extra.append(ob_tag)
            if lt_tag:
                extra.append(lt_tag)
            if corr_tag:
                extra.append(corr_tag)
            if extra:
                parts.append('  '.join(extra))
            entry = '  '.join(parts)
            if pct > 2:
                bullish_sigs.append((amp, entry))
            elif pct < -2:
                bearish_sigs.append((amp, entry))
            else:
                neutral_sigs.append((amp, entry))
        # Build output
        lines.append(f'## 📊 新闻热点 {ts}')
        lines.append(f'> {overview_line}')
        lines.append('')
        if bullish_sigs:
            lines.append('### 🟢 利好')
            bullish_sigs.sort(key=lambda x: x[0], reverse=True)
            for _, b in bullish_sigs:
                lines.append(f'- {b}')
            lines.append('')
        if bearish_sigs:
            lines.append('### 🔴 利空')
            bearish_sigs.sort(key=lambda x: x[0], reverse=True)
            for _, b in bearish_sigs:
                lines.append(f'- {b}')
            lines.append('')
        if neutral_sigs:
            lines.append('### ⚪ 震荡')
            neutral_sigs.sort(key=lambda x: x[0], reverse=True)
            for _, b in neutral_sigs:
                lines.append(f'- {b}')
            lines.append('')
        # Sector analysis
        sector_sigs = []
        for sig in signals:
            if sig.get('type') == 'sector':
                sector_sigs.append(sig)
        if sector_sigs:
            lines.append('---')
            lines.append('### 📈 板块热力')
            for ss in sector_sigs[:5]:
                avg = ss['avg_pct']
                name = ss['name']
                cnt = ss['count']
                clr = '#00AA00' if avg > 0 else ('#DD0000' if avg < 0 else '#888888')
                direction = '↑' if avg > 0 else ('↓' if avg < 0 else '→')
                coins_str = ''
                for sym, pct in ss.get('top_coins', []):
                    c2 = '#00AA00' if pct > 0 else '#DD0000'
                    coins_str += f' <font color={c2}>{sym}({pct:+.1f}%)</font>'
                lines.append(f'- <font color={clr}>{name} {direction}{abs(avg):.1f}%</font>  ({cnt}币){coins_str}')
            lines.append('')
        return self._post_dingtalk(chr(10).join(lines))

    def _post_dingtalk(self, content):
        now = time.time()
        cfg = get_config()
        interval = cfg.get('push_interval_seconds', 30)
        if now - self.last_push_time < interval:
            return False, f'节流: 距上次推送仅{now-self.last_push_time:.0f}秒，需间隔{interval}秒'
        self.last_push_time = now
        url = self._sign_dingtalk_url(self.webhook_url)
        title = content.split(chr(10))[0] if content else '新闻热点'
        payload = {'msgtype': 'markdown', 'markdown': {'title': title, 'text': content}}
        try:
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()
            if result.get('errcode') == 0:
                return True, ''
            return False, result.get('errmsg', resp.text[:100])
        except Exception as e:
            return False, str(e)[:100]

    def _post_feishu(self, text):
        if not self.webhook_url:
            return False, ''
        now = time.time()
        cfg = get_config()
        interval = cfg.get('push_interval_seconds', 30)
        if now - self.last_push_time < interval:
            return False, f'throttled {now-self.last_push_time:.0f}s < {interval}s'
        self.last_push_time = now
        print(f'[PUSH] {now} sending to feishu...')
        payload = {'msg_type': 'text', 'content': {'text': text}}
        try:
            proxy_url = cfg.get('proxy', '')
            proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
            url = self._sign_feishu_url(self.webhook_url)
            resp = requests.post(url, json=payload, timeout=15, proxies=proxies)
            result = resp.json()
            code = result.get('code', result.get('StatusCode'))
            if code == 0:
                return True, ''
            return False, result.get('msg', result.get('StatusMessage', resp.text[:200]))
        except Exception as e:
            return False, str(e)[:200]

    def _send_feishu_text(self, signal):
        coin = signal.get('coin', '')
        detail = signal.get('detail', '')
        pct = signal.get('change_pct', 0)
        emoji = '\u2705' if pct > 0 else ('\u274c' if pct < 0 else '\u2796')
        return self._post_feishu(f"{emoji} {coin}: {detail}")[0]

    def _send_feishu_batch_text(self, signals):
        if not signals:
            return False, ''
        now = time.time()
        cfg = get_config()
        interval = cfg.get('push_interval_seconds', 30)
        if now - self.last_push_time < interval:
            return False, 'throttled'
        self.last_push_time = now
        print(f"[FEISHU] sending batch at {time.strftime("%H:%M:%S")}, {len(signals)} signals")
        
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        md_lines = []
        overview = ''
        print(f'[FEISHU DEBUG] overview init done')
        
        all_signals = []
        for sig in signals[:15]:
            typ = sig.get('type', '')
            if typ == 'market_overview':
                bl = sig.get('bullish', 0)
                br = sig.get('bearish', 0)
                overview = f'利好{bl} | 利空{br}'
                continue
            if typ == 'sector':
                continue
            if sig.get('btc_corr', 0) and sig['btc_corr'] > 0.7:
                continue
            coin = sig.get('coin', '')
            
            
            score = sig.get('score', 0)
            verdict = sig.get('verdict', '')
            suggestion = sig.get('suggestion', '')
            reasons_bull = sig.get('reasons_bull', [])
            reasons_bear = sig.get('reasons_bear', [])
            reasons_neutral = sig.get('reasons_neutral', [])
            entry_lines = []
            # 只显示：币名 + 1h/4h + 评分
            summary = _make_summary(score, reasons_bull, reasons_bear)
            accu = _check_accumulation(sig)
            entry_lines.append("<font color='#0066FF'>\u25cf</font> **{} [{:+d}]** {}{}".format(coin, score, summary, accu))
            entry = chr(10).join(entry_lines)


            all_signals.append((score, entry))
        
        md_lines.append(f'> {overview}')
        md_lines.append('')
        all_signals.sort(key=lambda x: x[0], reverse=True)
        for _, entry in all_signals:
            md_lines.append(entry)
        md_lines.append('')
        sector_sigs = [s for s in signals if s.get('type') == 'sector']
        if sector_sigs:
            md_lines.append('---')
            md_lines.append('**\U0001f4c8 板块热力**')
            for ss in sector_sigs[:5]:
                avg = ss['avg_pct']
                name = ss['name']
                cnt = ss['count']
                dirr = '\u2191' if avg > 0 else ('\u2193' if avg < 0 else '\u2192')
                cs = ''
                for sym, p in ss.get('top_coins', []):
                    pc = '#00AA00' if p > 0 else ('#DD0000' if p < 0 else '#888888')
                    cs += f' <font color=\'{pc}\'>{sym}({p:+.1f}%)</font>'
                ac = '#00AA00' if avg > 0 else ('#DD0000' if avg < 0 else '#888888')
                md_lines.append(f'- **<font color=\'{ac}\'>{name}</font>** {dirr}{abs(avg):.1f}%  ({cnt}\u5e01){cs}')
                # Show laggards (catch-up candidates)
                laggards = ss.get("laggards", [])
                if laggards:
                    ls = ""
                    for sym, chg, vol in laggards[:2]:
                        lc = "#00AA00" if chg > 0 else ("#DD0000" if chg < 0 else "#888888")
                        ls += f" <font color='{lc}'>{sym}({chg:+.1f}%)"
                    md_lines.append(f"  💤补涨候选:{ls}")
            md_lines.append('')
        
        md_content = chr(10).join(md_lines)
        
        payload = {
            'msg_type': 'interactive',
            'card': {
                'header': {
                    'title': {'tag': 'plain_text', 'content': f'\u65b0\u95fb\u70ed\u70b9 {ts}'},
                    'template': 'blue'
                },
                'elements': [{
                    'tag': 'markdown',
                    'content': md_content
                }]
            }
        }
        
        url = self._sign_feishu_url(self.webhook_url)
        try:
            proxy_url = cfg.get('proxy', '')
            proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
            print(f"[FEISHU DEBUG] posting to feishu, md_content({len(md_content)} chars): {md_content[:100]}")
            resp = requests.post(url, json=payload, timeout=15, proxies=proxies)
            result = resp.json()
            code = result.get('code') or result.get('StatusCode')
            if code == 0:
                print(f"[FEISHU] send OK")
                return True, ''
            err = result.get("msg", result.get("StatusMessage", resp.text[:200]))
            print(f"[FEISHU] send FAIL: {err}")
            return False, err

        except Exception as e:
            print(f"[FEISHU] send EXCEPTION: {e}")
            return False, str(e)[:200]
    def send_arb_batch(self, arb_signals):
        """发送套利信号到独立飞书群"""
        print('[ARB DEBUG] send_arb_batch called, signals: {}'.format(len(arb_signals)))
        cfg = get_config()
        url = cfg.get("arb_webhook_url", "")
        secret = cfg.get("arb_feishu_secret", "")
        if not url or not arb_signals:
            return False, ""
        
        ts = __import__("datetime").datetime.now().strftime("%H:%M:%S")
        lines = [f"\U0001f4ca 套利扫描 {ts}", ""]
        
        for a in arb_signals[:8]:
            coin = a.get("coin", "")
            spot = a.get("spot_price", 0)
            mark = a.get("mark_price", 0)
            prem = a.get("spot_premium") or 0
            fr = a.get("funding_rate") or 0
            ob = a.get("ob_label", "")
            ws = a.get("wall_score", 0)
            oi = a.get("oi_label", "")
            
            # 综合评分
            arb_score = 0
            if (prem or 0) >= 0.5:
                arb_score += 3
            elif (prem or 0) >= 0.3:
                arb_score += 1
            # 盘口深度
            if ob == "买盘强" or (ws or 0) >= 1:
                arb_score += 1
            # OI稳定
            if oi and oi not in ("多头加仓", "空头加仓"):
                arb_score += 1
            
            if arb_score >= 4:
                tag = "\U0001f7e2 推荐"
            elif arb_score >= 2:
                tag = "\U0001f7e1 关注"
            else:
                continue
            
            fr_sign = "+" if (fr or 0) > 0 else ""
            info = f"溢价{prem:.1f}%"
            if ob:
                info += f" {ob}"
            if oi:
                info += f" {oi}"
            lines.append(f"\u25cf **{coin}** 现{spot:.4f} 合{mark:.4f} {info} 费率{fr_sign}{fr:.3f}% {tag}")
        
        if len(lines) == 2:
            return False, "no qualified arb"
        
        import hmac, hashlib, base64, urllib.parse
        if secret:
            t = str(int(__import__("time").time()))
            sig_str = f"{t}\n{secret}"
            sig = hmac.new(sig_str.encode("utf-8"), b"", hashlib.sha256).digest()
            s = urllib.parse.quote_plus(base64.b64encode(sig).decode("utf-8"))
            url = f"{url}?timestamp={t}&sign={s}"
        
        payload = {"msg_type": "text", "content": {"text": chr(10).join(lines)}}
        try:
            resp = __import__("requests").post(url, json=payload, timeout=15)
            r = resp.json()
            if r.get("code") == 0:
                print(f"[ARB] sent {len(lines)-2} signals")
                return True, ""
            return False, r.get("msg", "")
        except Exception as e:
            return False, str(e)

    def _send_feishu_batch(self, signals):
        for sig in signals[:5]:
            self._send_feishu(sig)
