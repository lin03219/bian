# -*- coding: utf-8 -*-
"""
配置管理模块：Webhook、监控参数、币种列表
"""
import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser('~')) / '.crypto_monitor'
CONFIG_FILE = CONFIG_DIR / 'config.json'

DEFAULT_CONFIG = {
    'channel': 'dingtalk',
    'webhook_url': '',
    'checks_per_minute': 4,
    'price_change_threshold_pct': 3.5,
    'volume_change_threshold_pct': 100.0,
    'watch_coins': [],
    'watch_unlocks': True,
    'unlock_ahead_hours': 48,
    'auto_start': True,
    'proxy': 'http://127.0.0.1:7890',
    'dingtalk_secret': '',
    'push_interval_seconds': 30,
    'blacklist': [],
    'santiment_key': '',
    'news_interval_minutes': 10,
    'feishu_secret': '',
    'rank_webhook_url': '',       # 排行榜独立推送webhook
    'rank_push_seconds': 30,  # 排行榜推送间隔(秒)       # 排行榜推送间隔(分钟)
    'feishu_app_id': 'cli_aa98546becf8dbda',
    'feishu_app_secret': 'oPG0ide5BOQE8IT7lJm0vbynRyyCXYcQ',
    'theme': 'light',  # 'light' or 'dark'
    'top_coins_count': 200,
    'min_volume_usdt': 500000,
    'max_market_cap': 400000000,
    'deep_analysis_count': 10,
    'feishu_display_count': 15,
    'btc_corr_filter': 0.7,
    'min_score_filter': 1,
}

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def get_config():
    return load_config()
