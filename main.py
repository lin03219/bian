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
            # 获取 1h/2h/8h 涨跌幅（前10个信号）
            for s in signals[:8]:
                sym = s.get('coin', '')
                if sym not in ('MARKET', 'ALTS', 'BTC.D'):
                    try:
                        closes = collector.get_klines(sym, '1h', 6)
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
            sigs_deep = [s for s in signals[:15] if s.get("coin","") not in ("MARKET","BTC.D")]
            for sym_idx, s in enumerate(signals[:15]):
                sym = s.get('coin', '')
                if sym in ('MARKET', 'BTC.D'):
                    continue
                # Status update every 5 coins to reduce GUI load
                if (sym_idx + 1) % 5 == 0 or sym_idx == 0:
                    self.status_update.emit(f'正在分析 {sym} 深度数据... ({sym_idx+1}/{len(signals[:15])})')
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
                s['analysis'] = _analyze_signal(s)
            
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




def _analyze_signal(sig):
    """综合盘口、大单、BTC相关性、OI、涨跌幅给出分析总结"""
    pct = sig.get('change_pct', 0)
    amp = sig.get('amplitude', 0)
    ob = sig.get('ob_label', '')
    lt = sig.get('lt_label', '')
    corr = sig.get('btc_corr')
    oi = sig.get('oi_label', '')
    # 强势拉升
    if pct > 5 and ob == '买盘强' and lt == '大单净买':
        if oi == '多头加仓':
            return '🔥主力加仓拉升'
        if corr is not None and corr < 0.5:
            return '🔥独立拉升'
        return '📈主力拉升'
    if pct > 3:
        if oi == '空头平仓':
            return '🔄空头踩踏上涨'
        if corr is not None and corr < 0.4:
            return '💪独立走强'
        if ob == '买盘强':
            return '📈放量突破'
        if lt == '大单净买':
            return '🐳大户吸筹'
        return '📈跟涨BTC'
    if -2 < pct <= 3:
        if amp < 2:
            return '😴横盘沉寂'
        if lt == '大单净买':
            return '👀蓄力吸筹'
        if lt == '大单净卖':
            return '⚠️暗中出货'
        if oi == '空头加仓':
            return '🔻空头布局'
        return '➡️窄幅震荡'
    if pct < -5 and ob == '卖盘强' and lt == '大单净卖':
        if oi == '空头加仓':
            return '🚨空头加码砸盘'
        if corr is not None and corr < 0.5:
            return '🚨独立暴跌'
        return '📉主力出货'
    if pct < -3:
        if oi == '多头平仓':
            return '🏃多头踩踏出逃'
        if corr is not None and corr < 0.4:
            return '🔻独立走弱'
        if lt == '大单净买':
            return '🔄打压吸筹'
        return '📉跟跌BTC'
    return '📊正常波动'


class QuickRankWorker(QThread):
    ranking_ready = Signal(list)
    
    def run(self):
        try:
            import collector
            coins = collector.get_top_coins(200)
            # print(f"[RANK] Fetched {len(coins)} coins from Binance")
            # Filter: market cap <= 400M
            try:
                mcaps = collector.get_market_caps()
                coins = [c for c in coins if mcaps.get(c['symbol'].upper(), 0) <= 400_000_000]
                # print(f"[RANK] After mcap filter: {len(coins)} coins")
            except:
                pass
            # Enhanced quick score (approximates full analysis)
            scored = []
            # Compute volume percentiles for relative scoring
            all_vols = sorted([c.get('volume_24h', 0) for c in coins], reverse=True)
            vol_p90 = all_vols[len(all_vols)//10] if len(all_vols) > 10 else 0
            vol_p50 = all_vols[len(all_vols)//2] if len(all_vols) > 2 else 0
            
            for c in coins:
                chg = c.get('change_24h', 0)
                amp = c.get('amplitude', 0)
                vol = c.get('volume_24h', 0)
                price = c.get('price', 0)
                
                score = 0.0
                
                # 1. 24h change (continuous, same range as full analysis: -3 to +3)
                score += max(-3.0, min(3.0, chg / 5.0))
                
                # 2. Amplitude bonus (volatility = opportunity)
                if amp > 30: score += 1.5
                elif amp > 20: score += 1.0
                elif amp > 10: score += 0.5
                elif amp > 5: score += 0.3
                
                # 3. Volume score (log-scale, relative)
                import math
                if vol > 0:
                    vol_log = math.log10(vol)
                    score += max(0.0, (vol_log - 5.5) * 0.5)  # ~0.5 at 10M, ~1.0 at 100M
                
                # 4. Price position in 24h range
                try:
                    high_24h = float(c.get('high_24h', 0))
                    low_24h = float(c.get('low_24h', 0))
                    if high_24h > low_24h and price > 0:
                        pos = (price - low_24h) / (high_24h - low_24h)
                        # Near low + positive change = potential breakout starting
                        if pos < 0.3 and chg > 0: score += 1.0
                        elif pos < 0.3: score += 0.3
                        # Near high + negative change = might reverse
                        elif pos > 0.8 and chg < 0: score -= 0.5
                except:
                    pass
                
                scored.append({
                    'symbol': c['symbol'],
                    'price': price,
                    'change_24h': chg,
                    'amplitude': amp,
                    'volume': vol,
                    'score': round(score, 1),
                })
            # Quick sort to find top candidates
            scored.sort(key=lambda x: x['score'], reverse=True)
            
            # Enhance top 30 with RSI + MA for better accuracy
            for idx in range(min(30, len(scored))):
                sym = scored[idx]['symbol']
                try:
                    closes = collector.get_klines(sym, '1h', 35)
                    if len(closes) >= 15:
                        # RSI
                        rsi = collector.calc_rsi(closes, 14)
                        if rsi is not None:
                            if rsi > 80:
                                scored[idx]['score'] -= 1.5
                            elif rsi > 70:
                                scored[idx]['score'] -= 0.5
                            elif rsi < 20:
                                scored[idx]['score'] += 1.5
                            elif rsi < 30:
                                scored[idx]['score'] += 0.5
                        # MA position
                        mas = collector.calc_ma(closes)
                        price = scored[idx]['price']
                        if mas and price > 0:
                            above = sum(1 for v in mas.values() if price > v)
                            total_ma = len(mas)
                            if above == total_ma:
                                scored[idx]['score'] += 1.5
                            elif above > total_ma // 2:
                                scored[idx]['score'] += 0.5
                            elif above == 0:
                                scored[idx]['score'] -= 1.0
                    scored[idx]['score'] = round(scored[idx]['score'], 1)
                except:
                    pass
            
            # Final sort and emit
            scored.sort(key=lambda x: x['score'], reverse=True)
            self.ranking_ready.emit(scored[:15])
        except Exception as e:
            self.ranking_ready.emit([{"symbol": "ERROR", "score": 0, "change_24h": 0, "amplitude": 0, "volume": 0, "price": 0, "error": str(e)}])

class CoinAnalysisDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('币种分析')
        self.setMinimumSize(500, 550)
        self._build_ui()
        self._load_ranking()

    def _build_ui(self):
        lo = QVBoxLayout(self)
        hl = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText('输入币种代号，如 BTC、ETH、GMT...')
        hl.addWidget(self.input_edit)
        self.analyze_btn = QPushButton('分析')
        self.analyze_btn.clicked.connect(self._analyze)
        hl.addWidget(self.analyze_btn)
        self.refresh_btn = QPushButton('刷新排行')
        self.refresh_btn.clicked.connect(self._load_ranking)
        hl.addWidget(self.refresh_btn)
        lo.addLayout(hl)
        self.result_area = QTextBrowser()
        self.result_area.setOpenExternalLinks(False)
        lo.addWidget(self.result_area)
        self.input_edit.returnPressed.connect(self._analyze)

    def _load_ranking(self):
        self.result_area.setHtml('<p style="color:#888;text-align:center;padding:40px">⏳ 正在加载币种排行...</p>')
        QApplication.processEvents()
        self.rank_worker = QuickRankWorker()
        self.rank_worker.ranking_ready.connect(self._show_ranking)
        self.rank_worker.finished.connect(lambda: self.refresh_btn.setEnabled(True))
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText('刷新中...')
        self.rank_worker.start()

    def _show_ranking(self, scored):
        self.refresh_btn.setText('刷新排行')
        self.refresh_btn.setEnabled(True)
        if not scored:
            self.result_area.setHtml('<p style="color:#888">暂无数据</p>')
            return
        if scored[0].get('error'):
            self.result_area.setHtml(f'<p style="color:red">排行加载失败: {scored[0]["error"]}</p>')
            return
        
        html = []
        html.append('<h2 style="margin-bottom:4px">币种评分排行 Top 15</h2>')
        html.append('<p style="color:#888;font-size:12px;margin-top:0">基于24h涨跌+振幅+成交量快速评分 | 点击币种名可分析</p>')
        html.append('<table style="width:100%;border-collapse:collapse;font-size:13px">')
        html.append('<tr style="background:#f5f5f5;border-bottom:2px solid #ddd">')
        html.append('<th style="padding:6px;text-align:left">#</th>')
        html.append('<th style="padding:6px;text-align:left">币种</th>')
        html.append('<th style="padding:6px;text-align:center">评分</th>')
        html.append('<th style="padding:6px;text-align:right">24h涨跌</th>')
        html.append('<th style="padding:6px;text-align:right">振幅</th>')
        html.append('<th style="padding:6px;text-align:right">成交量(USDT)</th></tr>')
        
        for idx, coin in enumerate(scored):
            rank = idx + 1
            sym = coin['symbol']
            score = coin['score']
            chg = coin['change_24h']
            amp = coin['amplitude']
            vol = coin['volume']
            price = coin['price']
            
            # Score color
            if score >= 4: sc = '#00AA00'
            elif score >= 2: sc = '#44BB00'
            elif score >= 0: sc = '#888888'
            elif score >= -2: sc = '#DD8800'
            else: sc = '#DD0000'
            
            # Change color
            cc = '#00AA00' if chg > 0 else ('#DD0000' if chg < 0 else '#888888')
            
            # Volume format
            if vol >= 1_000_000_000: vs = f'{vol/1_000_000_000:.1f}B'
            elif vol >= 1_000_000: vs = f'{vol/1_000_000:.1f}M'
            else: vs = f'{vol/1000:.0f}K'
            
            bg = '#fafafa' if rank % 2 == 0 else '#fff'
            html.append(f"<tr style='background:{bg};border-bottom:1px solid #eee'><td style='padding:5px;font-weight:bold;color:#888'>{rank}</td><td style='padding:5px;font-weight:bold'><a href='analyze_{sym}' style='color:#333;text-decoration:none'>{sym}</a></td><td style='padding:5px;text-align:center;font-weight:bold;color:{sc}'>{score:+.1f}</td><td style='padding:5px;text-align:right;color:{cc}'>{chg:+.1f}%</td><td style='padding:5px;text-align:right'>{amp:.1f}%</td><td style='padding:5px;text-align:right'>${vs}</td></tr>")
        
        html.append('</table>')
        html.append('<p style="color:#888;font-size:11px;margin-top:8px">提示: 输入币种代号查看完整深度分析</p>')
        
        self.result_area.setHtml(''.join(html))
        # Store scored data for click handling
        self._ranked_coins = {c['symbol']: c for c in scored}
        # Connect anchor clicked
        try:
            self.result_area.anchorClicked.disconnect()
        except:
            pass
        self.result_area.anchorClicked.connect(self._on_rank_click)

    def _on_rank_click(self, url):
        sym = url.toString()
        if sym.startswith('analyze_'):
            coin = sym.replace('analyze_', '')
            self.input_edit.setText(coin)
            self._analyze()

    def _analyze(self):
        sym = self.input_edit.text().strip().upper()
        if not sym:
            return
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText('分析中...')
        self.result_area.clear()
        QApplication.processEvents()
        try:
            self._do_analyze(sym)
        except Exception as e:
            self.result_area.setHtml(f'<p style="color:red">分析失败: {e}</p>')
        finally:
            self.analyze_btn.setEnabled(True)
            self.analyze_btn.setText('分析')

    def _do_analyze(self, sym):
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
                self.result_area.setHtml(f'<p style="color:red">未找到 {sym}，请检查代号</p>')
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
            self.result_area.setHtml(f'<p style="color:red">基础数据获取失败: {e}</p>')
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
        
        # Margin / Borrow info
        try:
            can_margin = collector.can_margin_trade(sym)
            if can_margin:
                lines.append('<p><b>可借币做空:</b> <span style="color:green;font-weight:bold">✅ 是</span> <span style="color:#888">(全仓/逐仓保证金)</span></p>')
            else:
                lines.append('<p><b>可借币做空:</b> <span style="color:red">❌ 不可</span> <span style="color:#888">(币安未开通保证金)</span></p>')
        except:
            pass
        
        # Sector
        if sec_names:
            lines.append(f'<p><b>所属板块:</b> {chr(44).join(sec_names)}</p>')
        
        self.result_area.setHtml(''.join(lines))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('新闻热点')
        self.setMinimumSize(700, 600)
        self.paused = False
        self.worker = None
        self.news_worker = None
        self.scheduler = None
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
        self.weight_lbl = QLabel('API: --/1200 wgt')
        self.weight_lbl.setStyleSheet('color:#888;font-size:11px;padding:2px 8px')
        hl.addWidget(self.weight_lbl)
        self.auto_btn = QPushButton('自动检测: OFF')
        self.auto_btn.setCheckable(True)
        self.auto_btn.toggled.connect(self._toggle_auto)
        hl.addWidget(self.auto_btn)
        
        self.check_btn = QPushButton('立即检测')
        self.check_btn.clicked.connect(self._run_check)
        hl.addWidget(self.check_btn)
        lo.addLayout(hl)
        
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        lo.addWidget(self.log_area)
        
        bl = QHBoxLayout()
        self.pause_btn = QPushButton('暂停检测')
        self.pause_btn.clicked.connect(self._toggle_pause)
        bl.addWidget(self.pause_btn)
        bl.addStretch()
        news_btn = QPushButton('新闻监控')
        news_btn.clicked.connect(self._fetch_news)
        bl.addWidget(news_btn)
        coin_btn = QPushButton('币种分析')
        coin_btn.clicked.connect(self._show_coin_analysis)
        bl.addWidget(coin_btn)
        set_btn = QPushButton('设置')
        set_btn.clicked.connect(self._show_settings)
        bl.addWidget(set_btn)
        lo.addLayout(bl)

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
        # Startup rate limit check
        try:
            import collector
            safe, est, limit, advice = collector.check_rate_limit(cpm)
            if not safe:
                self._log(f'!!! 币安API限流警告: 预计 {est} wgt/分钟 > {limit} 上限')
                self._log(f'!!! {advice}')
        except:
            pass

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
        for s in signals[:8]:
            typ = s.get('type','')
            if typ == 'market_overview':
                continue
            coin = s.get('coin','')
            detail = s.get('detail','')
            pct = s.get('change_pct', 0)
            emoji = '🟢' if pct > 0 else '🔴'
            oi_label = s.get('oi_label', '')
            oi_str = f' [{oi_label}]' if oi_label else ''
            self._log(f'{emoji} {coin}: {detail}{oi_str}')

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


    def _show_coin_analysis(self):
        dlg = CoinAnalysisDialog(self)
        dlg.exec()


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

    def _update_weight_display(self):
        try:
            import collector
            used, limit, remaining = collector.get_weight_status()
            pct = used / limit * 100 if limit > 0 else 0
            if pct > 90:
                clr = "red"
            elif pct > 60:
                clr = "orange"
            else:
                clr = "#888"
            self.weight_lbl.setText(f"API: {used}/{limit} wgt ({pct:.0f}%) - 重置倒计时 {remaining}s")
            self.weight_lbl.setStyleSheet(f"color:{clr};font-size:11px;padding:2px")
        except:
            pass

    def _log(self, text):
        self.log_area.append(text)
        # Auto scroll to bottom
        sb = self.log_area.verticalScrollBar()
        sb.setValue(sb.maximum())
        # Auto-scroll to bottom
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
    # Check for updates
    try:
        from PySide6.QtCore import QTimer
        def _check():
            import updater
            result = updater.check_update()
            if result is None:
                return
            has, latest, url, body = result
            if has:
                from PySide6.QtWidgets import QMessageBox
                msg = f"发现新版本 v{latest}{body[:200]}"
                reply = QMessageBox.question(w, "更新提示", msg,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if reply == QMessageBox.Yes:
                    ok, err = updater.download_and_replace(url)
                    if ok:
                        QMessageBox.information(w, "更新完成", "已下载新版本，请重启软件")
                    else:
                        QMessageBox.warning(w, "更新失败", err)
        QTimer.singleShot(3000, _check)
    except:
        pass
    sys.exit(app.exec())
