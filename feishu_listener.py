# -*- coding: utf-8 -*-
"""飞书远程指令监听 - 轮询群消息，解析并执行指令"""
import requests, time, json, threading

class FeishuListener:
    def __init__(self, app_id, app_secret, callback=None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.callback = callback
        self.token = None
        self.token_expire = 0
        self.last_check_time = 0
        self.bot_open_id = None
        self.running = False

    def _proxy(self):
        try:
            from config import get_config
            url = get_config().get("proxy", "")
            return {"http": url, "https": url} if url else None
        except:
            return None

    def _get_token(self):
        if self.token and time.time() < self.token_expire:
            return self.token
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=10, proxies=self._proxy())
            data = resp.json()
            if data.get("code") == 0:
                self.token = data["tenant_access_token"]
                self.token_expire = time.time() + data.get("expire", 3600) - 60
                if not self.bot_open_id:
                    try:
                        br = requests.get("https://open.feishu.cn/open-apis/bot/v3/info",
                            headers={"Authorization": f"Bearer {self.token}"},
                            timeout=5, proxies=self._proxy())
                        bd = br.json()
                        if bd.get("code") == 0:
                            self.bot_open_id = bd.get("bot", {}).get("open_id", "")
                    except:
                        pass
                return self.token
        except:
            pass
        return None

    def send_message(self, chat_id, text):
        token = self._get_token()
        if not token:
            return
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text})},
                timeout=10, proxies=self._proxy())
            return resp.json()
        except:
            return None

    def process(self):
        token = self._get_token()
        if not token:
            return
        try:
            resp = requests.get("https://open.feishu.cn/open-apis/im/v1/chats",
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": 50}, timeout=10, proxies=self._proxy())
            data = resp.json()
            if data.get("code") != 0:
                return
            chats = data.get("data", {}).get("items", [])
        except:
            return

        for chat in chats:
            chat_id = chat["chat_id"]
            try:
                resp = requests.get("https://open.feishu.cn/open-apis/im/v1/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"container_id_type": "chat", "container_id": chat_id,
                            "page_size": 5, "sort_type": "ByCreateTimeDesc"},
                    timeout=10, proxies=self._proxy())
                data = resp.json()
                if data.get("code") != 0:
                    continue
                msgs = data.get("data", {}).get("items", [])
            except:
                continue

            new_last = self.last_check_time
            for msg in msgs:
                ct = int(msg.get("create_time", "0"))
                if self.last_check_time > 0 and ct <= self.last_check_time:
                    continue
                if ct > new_last:
                    new_last = ct
                if msg.get("msg_type") == "system":
                    continue
                sid = msg.get("sender", {}).get("id", "")
                if self.bot_open_id and sid == self.bot_open_id:
                    continue
                raw = msg.get("body", {}).get("content", "{}")
                try:
                    text = json.loads(raw).get("text", "")
                except:
                    text = raw
                if text and self.callback:
                    self.callback(text, chat_id, chat.get("name", ""))
            self.last_check_time = new_last

    def start(self):
        self.running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self.running:
            try:
                self.process()
            except:
                pass
            time.sleep(5)

    def stop(self):
        self.running = False
