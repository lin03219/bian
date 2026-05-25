# -*- coding: utf-8 -*-
"""新闻热点 - 桌面版"""
import os

os.environ['QT_OPENGL'] = 'software'
os.environ['QSG_RENDER_LOOP'] = 'basic'
import sys
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMenu, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QDoubleSpinBox, QComboBox, QCheckBox, QGroupBox, QFormLayout,
    QMessageBox, QTextEdit, QWidget, QListWidget, QTextBrowser
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QAction
from apscheduler.schedulers.background import BackgroundScheduler
import collector
from detector import SignalDetector
import sector
import news_monitor
from notifier import Notifier
from config import get_config, save_config


class MonitorWorker(QThread):
    signals_detected = Signal(list)
    status_update = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = get_config()
        self.detector = SignalDetector(self.cfg)
        self.notifier = Notifier(self.cfg)

    def run(self):
        try:
            self.status_update.emit('正在拉取币安数据...')
            coins = collector.get_top_coins(200)
            # 过滤黑名单
            bl = self.cfg.get('blacklist', [])
            coins = [c for c in coins if c['symbol'].upper() not in [b.upper() for b in bl]]
            # 过滤市值>10亿的币种
            try:
                mcaps = collector.get_market_caps()
                coins = [c for c in coins if mcaps.get(c['symbol'].upper(), 0) <= 400_000_000]
                self.status_update.emit(f'市值过滤后剩余 {len(coins)} 币')
            except:
                pass
            global_data = collector.get_global_data()
            trending = collector.get_trending(coins)
            self.status_update.emit('正在分析信号...')
            signals = self.detector.detect_all(coins, global_data, trending)
            # 获取 1h/4h 涨跌幅
            for s in signals[:15]:
                sym = s.get('coin', '')
                if sym not in ('MARKET', 'ALTS', 'BTC.D'):
                    try:
                        closes = collector.get_klines(sym, '1h', 10)
                        n = len(closes)
                        if n >= 2:
                            s['change_1h'] = (closes[-1] / closes[-2] - 1) * 100
                        if n >= 5:
                            s['change_4h'] = (closes[-1] / closes[-5] - 1) * 100
                        # 4h振幅: 近4根1hK线最高最低
                        if n >= 4:
                            recent = closes[-4:]
                            s['amplitude'] = round((max(recent) - min(recent)) / closes[-1] * 100, 1)
                    except:
                        pass
            # 获取合约持仓量判断方向
            # 获取合约持仓量（内部使用，不展示）
            for s in signals[:20]:
                sym = s.get('coin', '')
                if sym in ('MARKET', 'ALTS', 'BTC.D'):
                    continue
                try:
                    oi_val, oi_chg = collector.get_open_interest(sym)
                    pct = s.get('change_pct', 0)
                    if oi_chg is not None:
                        if pct > 0 and oi_chg > 0:
                            s['oi_label'] = '多头加仓'
                        elif pct > 0 and oi_chg < 0:
                            s['oi_label'] = '空头平仓'
                        elif pct < 0 and oi_chg > 0:
                            s['oi_label'] = '空头加仓'
                        elif pct < 0 and oi_chg < 0:
                            s['oi_label'] = '多头平仓'
                except:
                    pass
            
            corr_cache = {}
            sigs_deep = [s for s in signals[:10] if s.get("coin","") not in ("MARKET","BTC.D")]
            for sym_idx, s in enumerate(signals[:10]):
                sym = s.get('coin', '')
                if sym in ('MARKET', 'BTC.D'):
                    continue
                # Status update every 5 coins to reduce GUI load
                if (sym_idx + 1) % 10 == 0 or sym_idx == 0:
                    self.status_update.emit(f'正在分析 {sym} 深度数据... ({sym_idx+1}/{len(signals[:10])})')
                # Kline metrics (MACD/Bollinger/OBV/MA)
                try:
                    closes = collector.get_klines(sym, '1h', 35)
                    volumes = collector.get_kline_volumes(sym, '1h', 35)
                    if len(closes) >= 26:
                        macd, signal_v, hist = collector.calc_macd(closes)
                        s['macd'] = macd; s['macd_signal'] = signal_v; s['macd_hist'] = hist
                    if len(closes) >= 20:
                        upper, mid, lower = collector.calc_bollinger(closes)
                        s['bb_upper'] = upper; s['bb_lower'] = lower
                    if len(closes) >= 2 and len(volumes) >= 2:
                        s['obv'] = collector.calc_obv(closes, volumes)
                    if len(closes) >= 15:
                        s['rsi_1h'] = collector.calc_rsi(closes)
                    mas = collector.calc_ma(closes)
                    if mas:
                        price = s.get('price', closes[-1])
                        above = sum(1 for v in mas.values() if price > v)
                        s['ma_above'] = above; s['ma_total'] = len(mas)
                except:
                    pass
                # Active buy/sell
                try:
                    abr, abl, _, _ = collector.get_active_buy_sell_ratio(sym)
                    s['active_buy_ratio'] = abr
                except:
                    pass
                # Contract premium
                try:
                    s['premium'] = collector.get_premium_index(sym)
                except:
                    pass
                try:
                    ratio, ob_label = collector.get_orderbook_ratio(sym)
                    s['ob_ratio'] = ratio
                    s['ob_label'] = ob_label
                except:
                    pass

                # BTC correlation (cached)
                try:
                    corr = collector.get_btc_correlation(sym)
                    s['btc_corr'] = corr
                except:
                    pass
                # Long/short ratio
                try:
                    top_l, glb_l, ls_label = collector.get_long_short_ratio(sym)
                    s['ls_top'] = top_l
                    s['ls_global'] = glb_l
                    s['ls_label'] = ls_label
                except:
                    pass
            
            # 综合数据分析，生成总结标签
            for s in signals[:20]:
                _analyze_signal_detailed(s)
            
            # 板块分析
            try:
                sector_signals = sector.analyze_sectors(coins)
                for ss in sector_signals[:8]:
                    signals.append({
                        'type': 'sector',
                        'sector': ss['sector'],
                        'name': ss['name'],
                        'avg_pct': ss['avg_pct'],
                        'count': ss['count'],
                        'top_coins': ss['top_coins'],
                        'laggards': ss.get('laggards', []),
                    })
            except:
                pass
            
            # 统计利好利空
            bullish = sum(1 for s in signals if s.get('change_pct', 0) > 0)
            bearish = sum(1 for s in signals if s.get('change_pct', 0) < 0)
            # 添加市场总览
            fg = global_data.get('fear_greed', 50)
            overview = {
                'type': 'market_overview',
                'total_coins': len(coins),
                'bullish': bullish,
                'bearish': bearish,
                'fear_greed': fg,
            }
            signals.insert(0, overview)
            if signals:
                self.signals_detected.emit(signals)
                if self.notifier.is_configured():
                    self.status_update.emit(f'推送 {len(signals)} 条信号到飞书...')
                    ok, msg = self.notifier.send_batch(signals)
                    if ok:
                        self.status_update.emit('推送完成')
                    else:
                        self.status_update.emit(f'推送失败: {msg}')
            now = datetime.now().strftime('%H:%M:%S')
            msg = f'{now}  检测到 {len(signals)} 条信号' if signals else f'{now}  监控正常，暂无异常信号'
            self.status_update.emit(msg)
        except Exception as e:
            self.status_update.emit(f'错误: {e}')



class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('设置 - 新闻系统')
        self.setMinimumWidth(450)
        self.cfg = get_config()
        self._build_ui()
        self._load()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        g1 = QGroupBox('推送设置')
        f1 = QFormLayout()
        self.ch_combo = QComboBox()
        self.ch_combo.addItems(['钉钉', '飞书'])
        f1.addRow('推送通道:', self.ch_combo)
        self.wh_edit = QLineEdit()
        self.wh_edit.setPlaceholderText('粘贴 Webhook URL...')
        f1.addRow('Webhook URL:', self.wh_edit)
        self.secret_edit = QLineEdit()
        self.secret_edit.setPlaceholderText('钉钉机器人加签密钥 (SEC开头)...')
        f1.addRow('加签密钥:', self.secret_edit)
        self.push_iv = QSpinBox(); self.push_iv.setRange(5,3600); self.push_iv.setSuffix(' 秒')
        f1.addRow('推送间隔:', self.push_iv)
        self.fs_secret = QLineEdit()
        self.fs_secret.setPlaceholderText('飞书签名校验密钥...')
        f1.addRow('飞书加签:', self.fs_secret)
        g1.setLayout(f1); lo.addWidget(g1)

        g3 = QGroupBox('代理设置')
        f3 = QFormLayout()
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText('http://127.0.0.1:7890')
        f3.addRow('HTTP 代理:', self.proxy_edit)
        g3.setLayout(f3); lo.addWidget(g3)

        g2 = QGroupBox('监控参数')
        f2 = QFormLayout()
        self.pc = QDoubleSpinBox(); self.pc.setRange(1,50); self.pc.setSuffix(' %')
        f2.addRow('价格异动阈值:', self.pc)
        self.vc = QDoubleSpinBox(); self.vc.setRange(50,1000); self.vc.setSuffix(' %')
        f2.addRow('成交量异动阈值:', self.vc)
        g2.setLayout(f2); lo.addWidget(g2)
        
        

        
        g5 = QGroupBox('新闻监控API（可选）')
        f5 = QFormLayout()
        self.st_key = QLineEdit()
        self.st_key.setPlaceholderText('Santiment API Key...')
        f5.addRow('Santiment:', self.st_key)
        self.news_iv = QSpinBox(); self.news_iv.setRange(1,120); self.news_iv.setSuffix(' 分钟')
        f5.addRow('新闻刷新间隔:', self.news_iv)
        g5.setLayout(f5); lo.addWidget(g5)
        g4 = QGroupBox('黑名单 (拉黑不看的币)')
        f4 = QVBoxLayout()
        hl = QHBoxLayout()
        self.bl_edit = QLineEdit()
        self.bl_edit.setPlaceholderText('输入币种代号，如 BTC、ETH...')
        hl.addWidget(self.bl_edit)
        add_btn = QPushButton('添加')
        add_btn.clicked.connect(self._add_blacklist)
        hl.addWidget(add_btn)
        f4.addLayout(hl)
        self.bl_list = QListWidget()
        self.bl_list.setMaximumHeight(120)
        f4.addWidget(self.bl_list)
        rm_btn = QPushButton('移除选中')
        rm_btn.clicked.connect(self._rm_blacklist)
        f4.addWidget(rm_btn)
        g4.setLayout(f4); lo.addWidget(g4)

        self.as_cb = QCheckBox('开机自动启动')
        lo.addWidget(self.as_cb)

        g6 = QGroupBox('主题设置')
        f6 = QFormLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(['白天模式', '黑夜模式'])
        f6.addRow('界面主题:', self.theme_combo)
        g6.setLayout(f6); lo.addWidget(g6)

        bl = QHBoxLayout()
        tb = QPushButton('测试推送')
        tb.clicked.connect(self._test_push); bl.addWidget(tb)
        bl.addStretch()
        sb = QPushButton('保存')
        sb.setDefault(True); sb.clicked.connect(self._save); bl.addWidget(sb)
        cb = QPushButton('取消')
        cb.clicked.connect(self.reject); bl.addWidget(cb)
        lo.addLayout(bl)

    def _load(self):
        self.wh_edit.setText(self.cfg.get('webhook_url',''))
        self.ch_combo.setCurrentIndex(0 if self.cfg.get('channel')=='dingtalk' else 1)
        self.pc.setValue(self.cfg.get('price_change_threshold_pct',5.0))
        self.vc.setValue(self.cfg.get('volume_change_threshold_pct',200.0))
        self.as_cb.setChecked(self.cfg.get('auto_start',True))
        self.proxy_edit.setText(self.cfg.get('proxy','http://127.0.0.1:7890'))
        self.secret_edit.setText(self.cfg.get('dingtalk_secret',''))
        self.fs_secret.setText(self.cfg.get('feishu_secret',''))
        self.push_iv.setValue(self.cfg.get('push_interval_seconds',30))
        self.st_key.setText(self.cfg.get('santiment_key',''))
        self.news_iv.setValue(self.cfg.get('news_interval_minutes',10))
        theme = self.cfg.get('theme', 'light')
        self.theme_combo.setCurrentIndex(0 if theme == 'light' else 1)
        # load blacklist
        self.bl_list.clear()
        for coin in self.cfg.get('blacklist', []):
            self.bl_list.addItem(coin)

    def _save(self):
        self.cfg['webhook_url']=self.wh_edit.text().strip()
        self.cfg['channel']='dingtalk' if self.ch_combo.currentIndex()==0 else 'feishu'
        self.cfg['price_change_threshold_pct']=self.pc.value()
        self.cfg['volume_change_threshold_pct']=self.vc.value()
        self.cfg['auto_start']=self.as_cb.isChecked()
        self.cfg['proxy']=self.proxy_edit.text().strip()
        self.cfg['dingtalk_secret']=self.secret_edit.text().strip()
        self.cfg['feishu_secret']=self.fs_secret.text().strip()
        self.cfg['push_interval_seconds']=self.push_iv.value()
        self.cfg['santiment_key']=self.st_key.text().strip()
        self.cfg['news_interval_minutes']=self.news_iv.value()
        self.cfg['theme']='light' if self.theme_combo.currentIndex()==0 else 'dark'
        # save blacklist
        bl = []
        for idx in range(self.bl_list.count()):
            bl.append(self.bl_list.item(idx).text())
        self.cfg['blacklist'] = bl
        save_config(self.cfg)
        sd=Path(os.getenv('APPDATA'))/'Microsoft'/'Windows'/'Start Menu'/'Programs'/'Startup'
        sc=sd/'crypto_monitor.bat'
        if self.cfg['auto_start']:
            sd.mkdir(parents=True,exist_ok=True)
            sc.write_text(f'@echo off{chr(10)}"{sys.executable}" "{Path(__file__).resolve()}"',encoding='utf-8')
        elif sc.exists():
            sc.unlink()
        self.accept()


    
    def _add_blacklist(self):
        coin = self.bl_edit.text().strip().upper()
        if coin:
            for idx in range(self.bl_list.count()):
                if self.bl_list.item(idx).text() == coin:
                    return
            self.bl_list.addItem(coin)
            self.bl_edit.clear()

    def _rm_blacklist(self):
        for item in self.bl_list.selectedItems():
            self.bl_list.takeItem(self.bl_list.row(item))
    def _test_push(self):
        url = self.wh_edit.text().strip()
        if not url:
            QMessageBox.warning(self, '提示', '请先填写 Webhook URL')
            return
        ch = 'dingtalk' if self.ch_combo.currentIndex() == 0 else 'feishu'
        proxy = self.proxy_edit.text().strip()
        secret = self.secret_edit.text().strip()
        fs_secret = self.fs_secret.text().strip()
        
        if ch == 'dingtalk':
            try:
                n = Notifier({'channel': ch, 'webhook_url': url, 'dingtalk_secret': secret})
                ok, err = n._post_dingtalk(chr(10).join(['测试消息', '', '收到说明配置成功！', '', '时间: 测试']))
                if ok:
                    QMessageBox.information(self, '成功', '已发送')
                else:
                    QMessageBox.warning(self, '失败', f'发送失败: {err}')
            except Exception as e:
                QMessageBox.warning(self, '失败', f'发送失败: {e}')
        else:
            # Feishu: use notifier with signature
            import requests, hmac, hashlib, base64, time as _t
            n = Notifier({'channel': 'feishu', 'webhook_url': url, 'feishu_secret': fs_secret})
            ok, err = n._post_feishu('测试消息 - 收到说明配置成功！')
            if ok:
                QMessageBox.information(self, '成功', '已发送')
            else:
                QMessageBox.warning(self, '失败', f'发送失败: {err}')





def _analyze_signal_detailed(sig):
    """综合盘口、大单、BTC相关性、OI、涨跌幅给出分析总结，计算评分"""
    pct = sig.get('change_pct', 0)
    amp = sig.get('amplitude', 0)
    c1 = sig.get('change_1h')
    c4 = sig.get('change_4h')
    ob = sig.get('ob_label', '')
    lt = sig.get('lt_label', '')
    corr = sig.get('btc_corr')
    oi = sig.get('oi_label', '')
    ls = sig.get('ls_label', '')
    rsi = sig.get('rsi_1h')
    change_24h = pct
    
    score = 0
    reasons_bull = []
    reasons_bear = []
    reasons_neutral = []
    
    # 24h change scoring
    if change_24h > 15:
        score += 3; reasons_bull.append(f'24h爆涨{change_24h:.1f}%，市场情绪极度亢奋，但追高风险也大')
    elif change_24h > 5:
        score += 2; reasons_bull.append(f'24h大涨{change_24h:.1f}%，资金明显流入，趋势强劲')
    elif change_24h > 2:
        score += 1; reasons_bull.append(f'24h涨{change_24h:.1f}%，走势稳健偏多')
    elif change_24h < -15:
        score -= 3; reasons_bear.append(f'24h暴跌{abs(change_24h):.1f}%，市场极度恐慌')
    elif change_24h < -5:
        score -= 2; reasons_bear.append(f'24h大跌{abs(change_24h):.1f}%，抛压明显')
    elif change_24h < -2:
        score -= 1; reasons_bear.append(f'24h跌{abs(change_24h):.1f}%，走势偏弱')
    
    # 1h/4h trend
    if c1 is not None and c4 is not None:
        if c1 > 0 and c4 > 0:
            if c1 > 3 and c4 > 3:
                score += 2; reasons_bull.append(f'1h涨{c1:.1f}%、4h涨{c4:.1f}%，短中期同步拉升')
            else:
                score += 1; reasons_bull.append(f'短中期均上涨(1h{c1:+.1f}%/4h{c4:+.1f}%)')
        elif c1 < 0 and c4 < 0:
            if c1 < -3 and c4 < -3:
                score -= 2; reasons_bear.append(f'1h跌{abs(c1):.1f}%、4h跌{abs(c4):.1f}%，加速下跌中')
            else:
                score -= 1; reasons_bear.append('短中期均下跌，空头主导')
        elif c1 < 0 and c4 > 0:
            reasons_neutral.append(f'1h回调但4h仍涨，可能是健康的回踩')
    
    # RSI
    if rsi is not None:
        if rsi > 75:
            score -= 2; reasons_bear.append(f'RSI高达{rsi:.0f}，极度超买，随时可能大幅回调')
        elif rsi > 65:
            score -= 1; reasons_bear.append(f'RSI={rsi:.0f}进入超买区')
        elif rsi < 25:
            score += 2; reasons_bull.append(f'RSI仅{rsi:.0f}，深度超卖，反弹概率很高')
        elif rsi < 35:
            score += 1; reasons_bull.append(f'RSI={rsi:.0f}偏低，超卖区域')
        else:
            reasons_neutral.append(f'RSI={rsi:.0f}中性，无极端信号')
    
    # Orderbook
    if ob:
        if ob == '买盘强':
            score += 1; reasons_bull.append('盘口买盘明显强于卖盘，下方有支撑')
        elif ob == '卖盘强':
            score -= 1; reasons_bear.append('盘口卖盘压制，上方有阻力')
        else:
            reasons_neutral.append('盘口买卖均衡')
    
    # Large trades
    if lt:
        if lt == '大单净买':
            score += 1; reasons_bull.append('大单净买入，大户在吸筹')
        elif lt == '大单净卖':
            score -= 1; reasons_bear.append('大单净卖出，大户在出货')
    
    # BTC correlation
    if corr is not None:
        if corr < 0.3:
            score += 1; reasons_bull.append(f'与BTC几乎不相关({corr:.2f})')
        elif corr > 0.8:
            reasons_neutral.append(f'跟随BTC({corr:.2f})')
    
    # Long/short
    if ls and ls != '-':
        if '多' in ls:
            reasons_bull.append(f'大户偏多({ls})')
        elif '空' in ls:
            reasons_bear.append(f'大户偏空({ls})')
    
    # Amplitude
    if amp > 20:
        reasons_neutral.append(f'振幅{amp:.0f}%偏大，交投活跃')
    elif amp < 2:
        reasons_neutral.append(f'振幅{amp:.1f}%清淡')
    
    # MACD
    macd_val = sig.get('macd')
    macd_sig_val = sig.get('macd_signal')
    macd_hist = sig.get('macd_hist')
    if macd_val is not None and macd_sig_val is not None:
        if macd_val > macd_sig_val:
            if macd_hist and macd_hist > 0:
                score += 2; reasons_bull.append('MACD金叉+放大')
            else:
                score += 1; reasons_bull.append('MACD金叉')
        elif macd_val < macd_sig_val:
            if macd_hist and macd_hist < 0:
                score -= 2; reasons_bear.append('MACD死叉+放大')
            else:
                score -= 1; reasons_bear.append('MACD死叉')
    
    # Bollinger
    bb_u = sig.get('bb_upper')
    bb_l = sig.get('bb_lower')
    if bb_u and bb_l and change_24h and amp:
        if change_24h > 5 and amp > 10:
            reasons_bull.append('布林带开口扩大偏多')
        elif change_24h < -5 and amp > 10:
            reasons_bear.append('布林带开口扩大偏空')
    
    # OBV
    obv_val = sig.get('obv')
    if obv_val is not None and change_24h is not None:
        if change_24h > 0 and obv_val > 0:
            score += 1; reasons_bull.append('OBV量价配合良好')
        elif change_24h < 0 and obv_val < 0:
            score -= 1; reasons_bear.append('OBV资金流出')
        elif change_24h > 0 and obv_val < 0:
            reasons_bear.append('OBV背离，涨势可疑')
    
    # MA
    ma_a = sig.get('ma_above')
    ma_t = sig.get('ma_total')
    if ma_a is not None and ma_t:
        if ma_a == ma_t:
            score += 2; reasons_bull.append(f'全部{ma_t}均线上方')
        elif ma_a > ma_t // 2:
            score += 1; reasons_bull.append(f'多数均线上({ma_a}/{ma_t})')
        elif ma_a == 0:
            score -= 2; reasons_bear.append(f'全部{ma_t}均线下')
        else:
            reasons_neutral.append('均线之间震荡')
    
    # Active buy/sell
    abr = sig.get('active_buy_ratio')
    if abr:
        if abr > 0.65:
            score += 1; reasons_bull.append(f'主动买{abr*100:.0f}%')
        elif abr < 0.35:
            score -= 1; reasons_bear.append(f'主动卖{(1-abr)*100:.0f}%')
    
    # Premium
    prem = sig.get('premium')
    if prem is not None:
        if prem > 0.5:
            score += 1; reasons_bull.append(f'合约溢价{prem:.1f}%')
        elif prem < -0.5:
            score -= 1; reasons_bear.append(f'合约折价{abs(prem):.1f}%')
    
    # Verdict
    if score >= 6:
        verdict = '🟢强烈看涨'
        suggestion = '多指标共振，可顺势做多，但注意RSI超买时减仓'
    elif score >= 3:
        verdict = '🟢看涨'
        suggestion = '趋势偏多，可考虑入场'
    elif score >= 1:
        verdict = '🟡偏多'
        suggestion = '略偏多，轻仓试探'
    elif score <= -6:
        verdict = '🔴强烈看跌'
        suggestion = '多指标共振看空，回避'
    elif score <= -3:
        verdict = '🔴看跌'
        suggestion = '偏空，不宜做多'
    elif score <= -1:
        verdict = '🟠偏空'
        suggestion = '空头，减仓观望'
    else:
        verdict = '⚪震荡'
        suggestion = '方向不明，观望等待'
    
    sig['analysis'] = '☁️正常'
    sig['score'] = score
    sig['verdict'] = verdict
    sig['suggestion'] = suggestion
    sig['reasons_bull'] = reasons_bull
    sig['reasons_bear'] = reasons_bear
    sig['reasons_neutral'] = reasons_neutral
    return verdict





def do_analyze_coin(sym):
    """Analyze a single coin, return HTML string"""
    import collector, sector
    
    # === STEP 1: Collect all data ===
    # Basic
    try:
        data = collector._get_binance('/ticker/24hr')
        coin_data = None
        for d in data:
            if d['symbol'] == sym + 'USDT':
                coin_data = d
                break
        if not coin_data:
            return f'<p style="color:red">未找到 {sym}，请检查代号</p>'
            return
        price = float(coin_data['lastPrice'])
        change_24h = float(coin_data['priceChangePercent'])
        high = float(coin_data['highPrice'])
        low = float(coin_data['lowPrice'])
        vol = float(coin_data['quoteVolume'])
        vol_base = float(coin_data['volume'])
        count = coin_data.get('count', 0)
        amp = round((high - low) / price * 100, 2)
        clr = lambda v: 'green' if v >= 0 else 'red'
    except Exception as e:
        return f'<p style="color:red">基础数据获取失败: {e}</p>'
        return
    
    # K-line & technical
    c1 = c4 = c24 = None
    rsi_1h = rsi_1d = None
    mas = {}
    vol_1d = None
    try:
        closes_1h = collector.get_klines(sym, '1h', 35)
        closes_1d = collector.get_klines(sym, '1d', 35)
        n1h = len(closes_1h)
        c1 = (closes_1h[-1] / closes_1h[-2] - 1) * 100 if n1h >= 2 else None
        c4 = (closes_1h[-1] / closes_1h[-5] - 1) * 100 if n1h >= 5 else None
        c24 = (closes_1h[-1] / closes_1h[-24] - 1) * 100 if n1h >= 24 else None
        rsi_1h = collector.calc_rsi(closes_1h, 14)
        rsi_1d = collector.calc_rsi(closes_1d, 14) if len(closes_1d) >= 15 else None
        mas = collector.calc_ma(closes_1h)
        vol_1d = collector.calc_volatility(closes_1d) if len(closes_1d) >= 8 else None
    except:
        pass
    
    # Orderbook
    bids = asks = []
    ratio = ob_label = ''
    try:
        bids, asks = collector.get_orderbook_depth(sym, 8)
    except:
        pass
    try:
        ratio, ob_label = collector.get_orderbook_ratio(sym)
    except:
        pass
    
    # Contract
    funding = oi_chg = oi_val = None
    top_l = glb_l = ls_label = None
    try:
        funding = collector.get_funding_rate(sym)
        oi_val, oi_chg = collector.get_open_interest(sym)
        top_l, glb_l, ls_label = collector.get_long_short_ratio(sym)
    except:
        pass
    
    # BTC correlation
    corr = None
    try:
        corr = collector.get_btc_correlation(sym)
    except:
        pass
    
    # Market cap
    mcap = turnover = 0
    try:
        mcaps = collector.get_market_caps()
        mcap = mcaps.get(sym, 0)
        turnover = (vol / mcap * 100) if mcap > 0 else 0
    except:
        pass
    
    # Sector
    sec_names = []
    try:
        secs = sector.COIN_SECTORS.get(sym, [])
        if secs:
            sec_names = [sector.SECTOR_NAMES.get(s, s) for s in secs]
    except:
        pass
    
    # === STEP 2: Compute verdict ===
    score = 0
    reasons_bull = []
    reasons_bear = []
    reasons_neutral = []
    
    if change_24h > 15:
        score += 3; reasons_bull.append(f'24h暴涨{change_24h:.1f}%，市场情绪极度亢奋，但追高风险也大')
    elif change_24h > 8:
        score += 2; reasons_bull.append(f'24h大涨{change_24h:.1f}%，资金明显流入，趋势强劲')
    elif change_24h > 3:
        score += 1; reasons_bull.append(f'24h涨{change_24h:.1f}%，走势稳健偏多')
    elif change_24h < -15:
        score -= 3; reasons_bear.append(f'24h暴跌{abs(change_24h):.1f}%，市场极度恐慌')
    elif change_24h < -8:
        score -= 2; reasons_bear.append(f'24h大跌{abs(change_24h):.1f}%，抛压明显')
    elif change_24h < -3:
        score -= 1; reasons_bear.append(f'24h跌{abs(change_24h):.1f}%，走势偏弱')
    
    if c1 is not None and c4 is not None:
        if c1 > 3 and c4 > 5:
            score += 2; reasons_bull.append(f'1h涨{c1:.1f}%、4h涨{c4:.1f}%，短中期同步拉升')
        elif c1 > 0 and c4 > 0:
            score += 1; reasons_bull.append(f'短中期均上涨(1h{c1:+.1f}%/4h{c4:+.1f}%)')
        elif c1 < -3 and c4 < -5:
            score -= 2; reasons_bear.append(f'1h跌{abs(c1):.1f}%、4h跌{abs(c4):.1f}%，加速下跌中')
        elif c1 < 0 and c4 < 0:
            score -= 1; reasons_bear.append('短中期均下跌，空头主导')
        elif c1 > 0 and c4 < 0:
            reasons_neutral.append('1h涨但4h跌，短期反弹但中期趋势不乐观')
        elif c1 < 0 and c4 > 0:
            reasons_neutral.append('1h回调但4h仍涨，可能是健康的回踩')
    
    if rsi_1h is not None:
        if rsi_1h > 85:
            score -= 2; reasons_bear.append(f'RSI高达{rsi_1h:.0f}，极度超买，随时可能大幅回调')
        elif rsi_1h > 70:
            score -= 1; reasons_bear.append(f'RSI={rsi_1h:.0f}进入超买区')
        elif rsi_1h < 20:
            score += 2; reasons_bull.append(f'RSI仅{rsi_1h:.0f}，深度超卖，反弹概率很高')
        elif rsi_1h < 30:
            score += 1; reasons_bull.append(f'RSI={rsi_1h:.0f}偏低，超卖区域')
        elif 40 <= rsi_1h <= 60:
            reasons_neutral.append(f'RSI={rsi_1h:.0f}中性，无极端信号')
    
    if mas:
        above_ma = sum(1 for v in mas.values() if price > v)
        total_ma = len(mas)
        if above_ma == total_ma:
            score += 2; reasons_bull.append(f'价格站上全部{total_ma}条均线，多头排列')
        elif above_ma > total_ma // 2:
            score += 1; reasons_bull.append(f'价格在多数均线上方({above_ma}/{total_ma})')
        elif above_ma == 0:
            score -= 2; reasons_bear.append(f'价格在全部{total_ma}条均线下方，空头排列')
        else:
            reasons_neutral.append('价格在均线之间震荡，方向不明确')
    
    if ob_label and ob_label != '-':
        if '买盘强' in str(ob_label):
            score += 1; reasons_bull.append('盘口买盘明显强于卖盘，下方有支撑')
        elif '卖盘强' in str(ob_label):
            score -= 1; reasons_bear.append('盘口卖盘压制，上方抛压较重')
    
    if funding is not None:
        if funding > 0.15:
            score -= 3; reasons_bear.append(f'资金费率极高({funding:.3f}%)！多头极度拥挤')
        elif funding > 0.08:
            score -= 1; reasons_bear.append(f'资金费率偏高({funding:.3f}%)')
        elif funding < -0.08:
            score += 2; reasons_bull.append(f'资金费率深度为负({funding:.3f}%)，逼空行情可能上演')
        elif funding < -0.03:
            score += 1; reasons_bull.append(f'资金费率偏负({funding:.3f}%)，空头付费')
    
    if oi_chg is not None:
        if change_24h > 3 and oi_chg > 5:
            score += 2; reasons_bull.append(f'价涨OI增{oi_chg:+.1f}%，多头加仓趋势')
        elif change_24h > 3 and oi_chg < -5:
            score -= 1; reasons_bear.append(f'价涨但OI大减{abs(oi_chg):.1f}%，多头获利了结')
        elif change_24h < -3 and oi_chg > 5:
            score += 1; reasons_bull.append(f'价跌但OI增{oi_chg:.1f}%，有资金逆势抄底')
        elif change_24h < -3 and oi_chg < -5:
            score -= 2; reasons_bear.append('价跌OI也跌，多头止损踩踏')
    
    if corr is not None:
        if corr < 0.2:
            score += 1; reasons_bull.append(f'与BTC几乎不相关({corr:.2f})，独立行情')
        elif corr > 0.85:
            reasons_neutral.append(f'高度跟随BTC(相关{corr:.2f})，涨跌看BTC脸色')
    
    if amp > 30:
        reasons_neutral.append(f'24h振幅高达{amp:.1f}%，波动剧烈，短线机会多但风险也大')
    elif amp > 15:
        reasons_neutral.append(f'振幅{amp:.1f}%偏大，交投活跃')
    
    if turnover > 0:
        if turnover > 200:
            reasons_neutral.append(f'换手率极高({turnover:.0f}%)，筹码快速换手')
        elif turnover > 80:
            reasons_neutral.append(f'换手率偏高({turnover:.0f}%)，交易活跃')
    
    if score >= 6:
        verdict_text = f'<span style="color:green;font-size:20px"><b>强烈看涨</b></span>'
        suggestion = '多个指标共振看多，可顺势做多，但注意RSI超买时减仓'
    elif score >= 3:
        verdict_text = f'<span style="color:green;font-size:20px"><b>看涨</b></span>'
        suggestion = '整体偏多，可以轻仓跟进，设好止损'
    elif score >= 1:
        verdict_text = f'<span style="color:#88aa00;font-size:20px"><b>偏多</b></span>'
        suggestion = '略偏多头，但信号不够强，建议小仓位试探'
    elif score >= -1:
        verdict_text = f'<span style="color:#888;font-size:20px"><b>震荡中性</b></span>'
        suggestion = '方向不明确，建议观望等待信号明朗'
    elif score >= -3:
        verdict_text = f'<span style="color:#cc6600;font-size:20px"><b>偏空</b></span>'
        suggestion = '略偏空头，不建议追多，已有仓位注意风险'
    elif score >= -6:
        verdict_text = f'<span style="color:red;font-size:20px"><b>看跌</b></span>'
        suggestion = '空头信号较多，回避做多，可考虑减仓'
    else:
        verdict_text = f'<span style="color:red;font-size:20px"><b>强烈看跌</b></span>'
        suggestion = '多个指标共振看空，建议离场观望，不要抄底'
    
    # === STEP 3: Build HTML with verdict FIRST ===
    lines = []
    lines.append(f'<h2>{sym} 综合分析</h2>')
    
    # VERDICT FIRST - styled card
    bg = '#e8f5e9' if score >= 3 else ('#fff3e0' if score >= 1 else ('#fce4ec' if score <= -3 else ('#fff8e1' if score <= -1 else '#f5f5f5')))
    border = '#4caf50' if score >= 3 else ('#ff9800' if score >= 1 else ('#f44336' if score <= -3 else ('#ffc107' if score <= -1 else '#9e9e9e')))
    icon = '\U0001f7e2' if score >= 3 else ('\U0001f7e1' if score >= 1 else ('\U0001f534' if score <= -3 else ('\U0001f7e0' if score <= -1 else '\u26aa')))
    
    lines.append(f'<div style="background:{bg};border-left:5px solid {border};border-radius:6px;padding:16px;margin:10px 0">')
    lines.append(f'<table style="width:100%;border:none"><tr>')
    lines.append(f'<td style="font-size:48px;width:60px;vertical-align:middle;text-align:center">{icon}</td>')
    lines.append(f'<td style="vertical-align:middle">')
    lines.append(f'<p style="font-size:20px;font-weight:bold;margin:0;color:#333">{verdict_text} <span style="font-size:14px;color:#888;font-weight:normal">评分 {score:+d}</span></p>')
    lines.append(f'<p style="font-size:13px;color:#555;margin:6px 0 0 0">\U0001f4a1 {suggestion}</p>')
    lines.append(f'</td></tr></table>')
    
    if reasons_bull or reasons_bear or reasons_neutral:
        lines.append('<table style="width:100%;margin-top:10px;font-size:13px">')
        if reasons_bull:
            for r in reasons_bull:
                lines.append(f'<tr><td style="color:#2e7d32;width:20px;vertical-align:top">\u2705</td><td style="color:#333;padding:2px 0">{r}</td></tr>')
        if reasons_bear:
            for r in reasons_bear:
                lines.append(f'<tr><td style="color:#c62828;width:20px;vertical-align:top">\u274c</td><td style="color:#333;padding:2px 0">{r}</td></tr>')
        if reasons_neutral:
            for r in reasons_neutral:
                lines.append(f'<tr><td style="color:#888;width:20px;vertical-align:top">\u2796</td><td style="color:#666;padding:2px 0">{r}</td></tr>')
        lines.append('</table>')
    lines.append('</div>')
    
    # THEN detailed data
    lines.append(f'<h3>基础行情</h3>')
    lines.append(f'<p><b>价格:</b> ${price:.6f}  <b style="color:{clr(change_24h)}">24h: {change_24h:+.2f}%</b></p>')
    lines.append(f'<p><b>24h高:</b> ${high:.6f}  <b>24h低:</b> ${low:.6f}  <b>振幅:</b> {amp:.1f}%</p>')
    lines.append(f'<p><b>成交量:</b> ${vol:,.0f} USDT (基础{vol_base:,.0f})  <b>成交笔数:</b> {count:,}</p>')
    
    # K-line
    def fc(v):
        if v is None: return '<span style="color:#888">-</span>'
        return f'<span style="color:{clr(v)}">{v:+.2f}%</span>'
    lines.append(f'<h3>K线涨跌</h3>')
    lines.append(f'<p><b>1h:</b> {fc(c1)}  <b>4h:</b> {fc(c4)}  <b>24hK:</b> {fc(c24)}</p>')
    
    if rsi_1h is not None:
        rsi_c = 'red' if rsi_1h > 70 else ('green' if rsi_1h < 30 else '#888')
        lines.append(f'<p><b>RSI(1h):</b> <span style="color:{rsi_c}">{rsi_1h:.1f}</span> <span style="color:#888">(超买&gt;70 / 超卖&lt;30)</span></p>')
    if mas:
        ma_parts = []
        for k, v in mas.items():
            diff = (price / v - 1) * 100
            ma_parts.append(f'<b>{k}:</b> ${v:.4f} <span style="color:{clr(diff)}">({diff:+.1f}%)</span>')
        lines.append(f'<p>{"  ".join(ma_parts)}</p>')
    if vol_1d is not None:
        lines.append(f'<p><b>年化波动率:</b> {vol_1d:.1f}%</p>')
    
    # Orderbook
    if bids and asks:
        lines.append(f'<h3>盘口深度 (前5档)</h3>')
        lines.append(f'<p><b>买盘:</b> ' + ' '.join([f'<span style="color:green">${b[0]:.4f}({b[1]:,.0f})</span>' for b in bids[:5]]) + '</p>')
        lines.append(f'<p><b>卖盘:</b> ' + ' '.join([f'<span style="color:red">${a[0]:.4f}({a[1]:,.0f})</span>' for a in asks[:5]]) + '</p>')
    if ob_label:
        ob_clr = 'green' if '买' in ob_label else ('red' if '卖' in ob_label else '#888')
        lines.append(f'<p><b>盘口力量:</b> <span style="color:{ob_clr}">{ob_label}</span> (买卖比 {ratio:.2f})</p>')
    
    # Contract
    lines.append(f'<h3>合约数据</h3>')
    if funding is not None:
        f_c = 'green' if funding > 0 else 'red'
        lines.append(f'<p><b>资金费率:</b> <span style="color:{f_c}">{funding:+.4f}%</span> <span style="color:#888">(正=多头付费)</span></p>')
    if oi_val:
        oi_str = f'<p><b>持仓量:</b> {oi_val:,.0f}张'
        if oi_chg is not None:
            oi_str += f'  <span style="color:{clr(oi_chg)}">{oi_chg:+.2f}%</span>'
        oi_str += '</p>'
        lines.append(oi_str)
    if top_l is not None:
        ls_str = f'<p><b>大户多空比:</b> {top_l:.2f}  <b>全局:</b> {glb_l:.2f}'
        if ls_label:
            ls_str += f'  <b>方向:</b> <span style="color:{clr(top_l-1)}">{ls_label}</span>'
        ls_str += '</p>'
        lines.append(ls_str)
    
    # BTC correlation
    if corr is not None:
        corr_c = 'green' if corr < 0.5 else ('red' if corr > 0.8 else '#888')
        note = '独立行情' if corr < 0.4 else ('跟随BTC' if corr > 0.8 else '部分相关')
        lines.append(f'<p><b>BTC相关性:</b> <span style="color:{corr_c}">{corr:.2f}</span> ({note})</p>')
    
    # Market cap
    if mcap > 0:
        lines.append(f'<h3>市值 & 流通</h3>')
        lines.append(f'<p><b>市值:</b> ${mcap:,.0f}  <b>换手率:</b> {turnover:.1f}%</p>')
    
    # Sector
    if sec_names:
        lines.append(f'<p><b>所属板块:</b> {chr(44).join(sec_names)}</p>')
    
    return ''.join(lines)
    return '<p>Analysis done</p>'

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('新闻热点')
        self.setMinimumSize(700, 600)
        self.paused = False
        self.worker = None
        self.news_worker = None
        self.scheduler = None
        self._log_buffer = []
        self._update_url = None
        self._update_version = None
        self._build_ui()
        self._start_scheduler()

    def _build_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        lo = QVBoxLayout(cw)
        
        hl = QHBoxLayout()
        self.status_lbl = QLabel('就绪')
        hl.addWidget(self.status_lbl)
        hl.addStretch()
        self.update_lbl = QLabel('')
        self.update_lbl.setStyleSheet('color:#fff;background:#e74c3c;border-radius:3px;padding:2px 8px;font-size:11px;font-weight:bold;')
        self.update_lbl.setVisible(False)
        self.update_lbl.mousePressEvent = lambda e: self._on_update_clicked()
        hl.addWidget(self.update_lbl)
        self.coin_input = QLineEdit()
        self.coin_input.setPlaceholderText('输入币种代号...')
        self.coin_input.setMaximumWidth(140)
        hl.addWidget(self.coin_input)
        self.coin_analyze_btn = QPushButton('分析')
        self.coin_analyze_btn.clicked.connect(self._analyze_coin)
        hl.addWidget(self.coin_analyze_btn)
        lo.addLayout(hl)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        lo.addWidget(self.log_area)
        
        bl = QHBoxLayout()
        self.pause_btn = QPushButton('暂停检测')
        self.pause_btn.clicked.connect(self._toggle_pause)
        bl.addWidget(self.pause_btn)
        self.auto_btn = QPushButton('自动检测: OFF')
        self.auto_btn.setCheckable(True)
        self.auto_btn.toggled.connect(self._toggle_auto)
        bl.addWidget(self.auto_btn)
        self.check_btn = QPushButton('立即检测')
        self.check_btn.clicked.connect(self._run_check)
        bl.addWidget(self.check_btn)
        bl.addStretch()
        news_btn = QPushButton('新闻监控')
        news_btn.clicked.connect(self._fetch_news)
        bl.addWidget(news_btn)
        set_btn = QPushButton('设置')
        set_btn.clicked.connect(self._show_settings)
        bl.addWidget(set_btn)
        lo.addLayout(bl)
        self._apply_theme()

    def _start_scheduler(self):
        self.scheduler = BackgroundScheduler()
        cfg = get_config()
        cpm = 4
        self.scheduler.add_job(self._run_check,'interval',minutes=1/cpm,id='c')
        self.scheduler.add_job(self._fetch_news, 'interval', minutes=cfg.get('news_interval_minutes',10), id='news')
        self.scheduler.start()

        # Weight display timer
        from PySide6.QtCore import QTimer
        self._weight_timer = QTimer()
        self._weight_timer.timeout.connect(self._update_weight_display)
        self._weight_timer.start(5000)  # every 5 seconds

        # Log flush timer (reduces GUI repaints)
        self._log_timer = QTimer()
        self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start(500)  # flush every 500ms
        # Startup rate limit check
        try:
            import collector
            safe, est, limit, advice = collector.check_rate_limit(cpm)
            if not safe:
                self._log(f'!!! 币安API限流警告: 预计 {est} wgt/分钟 > {limit} 上限')
                self._log(f'!!! {advice}')
        except:
            pass

    def _apply_theme(self):
        cfg = get_config()
        theme = cfg.get('theme', 'light')
        if theme == 'dark':
            dark = """
            QMainWindow, QDialog, QWidget { background-color: #1e1e2e; color: #cdd6f4; }
            QGroupBox { background-color: #252540; color: #cdd6f4; border: 1px solid #45475a; border-radius: 4px; margin-top: 10px; padding-top: 16px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #89b4fa; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; padding: 4px; border-radius: 3px; }
            QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #89b4fa; }
            QPushButton { background-color: #45475a; color: #cdd6f4; border: none; padding: 6px 14px; border-radius: 3px; font-weight: bold; }
            QPushButton:hover { background-color: #585b70; }
            QPushButton:pressed { background-color: #313244; }
            QPushButton:disabled { background-color: #313244; color: #585b70; }
            QTextEdit, QTextBrowser { background-color: #181825; color: #cdd6f4; border: 1px solid #45475a; border-radius: 3px; font-family: Consolas; }
            QListWidget { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; }
            QCheckBox { color: #cdd6f4; }
            QLabel { color: #cdd6f4; }
            QScrollBar:vertical { background: #1e1e2e; width: 10px; }
            QScrollBar::handle:vertical { background: #45475a; border-radius: 5px; min-height: 20px; }
            """
            self.setStyleSheet(dark)
        else:
            self.setStyleSheet("")

    def _run_check(self):
        import time as _t
        ts = _t.strftime('%H:%M:%S')
        if self.paused:
            self._log(f'[{ts}] 跳过: 已暂停')
            return
        if self.worker and self.worker.isRunning():
            self._log(f'[{ts}] 跳过: 上一轮还在跑')
            return
        # Check API weight quota
        try:
            import collector
            used, limit, remaining = collector.get_weight_status()
            if used > limit * 0.85:  # Over 85%, wait for next minute
                self._log(f'[{ts}] 跳过: API已用{used}/{limit} ({used/limit*100:.0f}%)，等待下分钟刷新')
                return
        except:
            pass
        self._log(f'[{ts}] 开始新一轮检测...')
        self.check_btn.setEnabled(False)
        self.check_btn.setText('检测中...')
        self.worker = MonitorWorker()
        self.worker.signals_detected.connect(self._on_signals)
        self.worker.status_update.connect(self._on_status)
        self.worker.finished.connect(self._on_done)
        self.worker.start()

    def _on_signals(self, signals):
        # Log only shows status; coin details go to Feishu only
        pass
    def _on_status(self, text):
        self.status_lbl.setText(text)
        self._log(text)

    def _on_done(self):
        import time as _t
        ts = _t.strftime('%H:%M:%S')
        self._log(f'[{ts}] 检测完成')
        self.check_btn.setEnabled(not self.paused)
        self.check_btn.setText('立即检测')
        self.worker = None

    def _toggle_auto(self, checked):
        self.auto_btn.setText('自动检测: ON' if checked else '自动检测: OFF')
        try:
            (self.scheduler.resume_job if checked else self.scheduler.pause_job)('c')
        except: pass

    def _toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.pause_btn.setText('继续检测')
            self.check_btn.setEnabled(False)
            try: self.scheduler.pause_job('c')
            except: pass
            self._log('=== 检测已暂停 ===')
        else:
            self.pause_btn.setText('暂停检测')
            self.check_btn.setEnabled(True)
            try: self.scheduler.resume_job('c')
            except: pass
            self._log('=== 检测已恢复 ===')


    def _add_to_blacklist(self, coin):
        cfg = get_config()
        bl = cfg.get("blacklist", [])
        if coin.upper() in [b.upper() for b in bl]:
            self._log(f"{coin} 已在黑名单中")
            return
        bl.append(coin.upper())
        cfg["blacklist"] = bl
        save_config(cfg)
        self._log(f"=== {coin} 已加入黑名单 ===")
    def _on_update_clicked(self):
        if not self._update_url:
            return
        reply = QMessageBox.question(self, '确认更新',
            f'发现新版本 v{self._update_version}，是否立即更新？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return
        self.update_lbl.setText('正在更新...')
        self.update_lbl.setStyleSheet('color:#fff;background:#f39c12;border-radius:3px;padding:2px 8px;font-size:11px;font-weight:bold')
        self.update_lbl.setEnabled(False)
        import updater
        def _cb(done, total):
            pass
        ok, err = updater.download_and_replace(self._update_url, _cb)
        if ok:
            self.update_lbl.setText('更新完成,请重启')
            self.update_lbl.setStyleSheet('color:#fff;background:#27ae60;border-radius:3px;padding:2px 8px;font-size:11px;font-weight:bold')
            QMessageBox.information(self, '更新完成', '新版本已下载，请手动重启软件。')
            self._log(f'=== 已下载 v{self._update_version}，请手动重启软件 ===')
        else:
            self.update_lbl.setText('更新失败')
            self.update_lbl.setStyleSheet('color:#fff;background:#e74c3c;border-radius:3px;padding:2px 8px;font-size:11px;font-weight:bold')
            self._log(f'更新失败: {err}')
    def _fetch_news(self):
        self._log('正在拉取新闻热点...')
        self.news_worker = NewsWorker()
        self.news_worker.news_ready.connect(self._on_news)
        self.news_worker.start()

    def _on_news(self, news):
        self._log(f'获取到 {len(news)} 条新闻')
        for n in news[:10]:
            src = n.get('source', '')
            title = n.get('title', '')
            self._log(f'  [{src}] {title}')
        cfg = get_config()
        if not cfg.get('webhook_url'):
            self._log('未配置Webhook，跳过新闻推送')
            return
        # Send news to DingTalk
        import time as _time
        from datetime import datetime as _dt
        nf = Notifier(cfg)
        ts = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
        lines = [f'## 📰 热点新闻 {ts}', '']
        for n in news[:15]:
            src = n.get('source', '')
            title = n.get('title', '')
            url = n.get('url', '')
            bull = n.get('bull_score')
            curs = n.get('currencies', [])
            if bull is not None:
                emoji = '🟢' if bull > 60 else ('🔴' if bull < 40 else '⚪')
                title = f'{emoji} {title}'
            if curs:
                title += f'  ({" ".join(curs[:5])})'
            lines.append(f'- [{src}] {title}')
        if cfg.get('channel') == 'feishu':
            nf._post_feishu(chr(10).join(lines))
            self._log('新闻已推送到飞书')
        else:
            nf._post_dingtalk(chr(10).join(lines))
            self._log('新闻已推送到钉钉')


    def _analyze_coin(self):
        sym = self.coin_input.text().strip().upper()
        if not sym:
            return
        self._log(f'\u6b63\u5728\u5206\u6790 {sym}...')
        try:
            html = do_analyze_coin(sym)
            dlg = QDialog(self)
            dlg.setWindowTitle(f'{sym} \u5206\u6790\u7ed3\u679c')
            dlg.setMinimumSize(550, 600)
            lo = QVBoxLayout(dlg)
            tb = QTextBrowser()
            tb.setOpenExternalLinks(False)
            tb.setHtml(html)
            lo.addWidget(tb)
            dlg.exec()
            self._log(f'{sym} \u5206\u6790\u5b8c\u6210')
        except Exception as e:
            self._log(f'\u5206\u6790\u5931\u8d25: {e}')

    def _show_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            try: self.scheduler.remove_job('c')
            except: pass
            cfg = get_config()
            cpm = 4
            self.scheduler.add_job(self._run_check,'interval',minutes=1/cpm,id='c')
            # Rate limit check
            try:
                import collector
                safe, est, limit, advice = collector.check_rate_limit(cpm)
                if not safe:
                    self._log(f'!!! 币安API限流警告: 预计 {est} weight/分钟 > {limit} 上限')
                    self._log(f'!!! {advice}')
                else:
                    self._log(f'API额度: {est}/{limit} weight/分钟 {advice}')
            except:
                pass
            self._apply_theme()

    def _update_weight_display(self):
        try:
            import collector
            used, limit, remaining = collector.get_weight_status()
            self.setWindowTitle(f'新闻热点  [API: {used}/{limit}]')
        except:
            pass
    def _log(self, text):
        self._log_buffer.append(text)
        # Keep only last 200 lines to avoid memory issues
        if len(self._log_buffer) > 200:
            self._log_buffer = self._log_buffer[-200:]

    def _flush_log(self):
        if not self._log_buffer:
            return
        # Only update if text changed to reduce repaints
        current = self.log_area.toPlainText()
        new_text = chr(10).join(self._log_buffer)
        if current != new_text:
            self.log_area.setPlainText(new_text)
            sb = self.log_area.verticalScrollBar()
            sb.setValue(sb.maximum())
    def closeEvent(self, event):
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
        event.accept()



class NewsWorker(QThread):
    news_ready = Signal(list)
    
    def run(self):
        try:
            from news_monitor import fetch_all_news
            cfg = get_config()
            news = fetch_all_news(cfg)
            self.news_ready.emit(news)
        except Exception as e:
            self.news_ready.emit([{'source': 'ERROR', 'title': str(e)}])

if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    # Check for updates (silent, shows label if available)
    try:
        from PySide6.QtCore import QTimer
        def _check():
            import updater
            result = updater.check_update()
            if result is None:
                return
            has, latest, url, body = result
            if has:
                w._update_url = url
                w._update_version = latest
                w.update_lbl.setText(f'🔄 更新 v{latest}')
                w.update_lbl.setVisible(True)
                w.setWindowTitle(f'新闻热点 [新版 v{latest}]')
        QTimer.singleShot(3000, _check)
    except:
        pass
    sys.exit(app.exec())
