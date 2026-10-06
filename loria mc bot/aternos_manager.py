import asyncio
import random
import string
import re
import subprocess
import json
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional

from config import ATERNOS_SESSION, ATERNOS_SERVER_NAME, ATERNOS_SERVER_ID

logger = logging.getLogger("AternosManager")

class AternosManager:
    def __init__(self):
        self.session_cookie = ATERNOS_SESSION
        self.target_server_name = ATERNOS_SERVER_NAME or "LORIAMC.aternos.me"
        self.server_id: str = ATERNOS_SERVER_ID or "LGudtxzl0I5KrSIe"
        self.domain: str = "LORIAMC.aternos.me"
        self.ip: str = "LORIAMC.aternos.me"
        self.software: str = "PaperMC"
        self.version: str = "1.20.6"
        self.players: str = "0/20"
        self.status: str = "offline"
        self.ajax_token: Optional[str] = None
        
        self.http = self._create_session()

    def _create_session(self) -> requests.Session:
        s = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://aternos.org/server/",
            "Connection": "close",
        })
        return s

    def _safe_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """إرسال طلب HTTP مع إعادة المحاولة تلقائياً وتجديد الجلسة عند انقطاع الاتصال"""
        kwargs.setdefault("timeout", 12)
        for attempt in range(3):
            try:
                if method.upper() == "GET":
                    resp = self.http.get(url, **kwargs)
                else:
                    resp = self.http.post(url, **kwargs)
                return resp
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, Exception) as e:
                logger.warning(f"محاولة اتصال {attempt + 1} فشلت ({e})، جاري إعادة المحاولة...")
                self.http = self._create_session()
                if attempt == 2:
                    raise e
                import time
                time.sleep(1)

    def _gen_sec(self):
        alphabet = string.ascii_lowercase + string.digits
        key = ''.join(random.choices(alphabet, k=11)) + '00000'
        val = ''.join(random.choices(alphabet, k=11)) + '00000'
        return key, val

    def _extract_token_from_html(self, html: str) -> Optional[str]:
        """استخراج رمز التوكن باستخدام Node.js"""
        try:
            scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            token_script = None
            for s in scripts:
                if "AJAX_TOKEN" in s or ("TO" in s and "KE" in s and "N" in s and "window[" in s):
                    token_script = s
                    break

            if not token_script:
                return None

            mock_js = """
            const window = global;
            window.Map = function(){};
            window.Map.prototype = {};
            window.setTimeout = function(_f,_t){};
            window.setInterval = function(_f,_t){};
            window.encodeURIComponent = window.Map;
            window.document = {
                getElementById: function(){ return {}; },
                currentScript: {}
            };
            window.HTMLScriptElement = function(){};
            window.document.currentScript = Object.create(window.HTMLScriptElement.prototype);
            const document = window.document;
            """
            full_code = f"{mock_js}\n{token_script}\nconsole.log(JSON.stringify(window['AJAX_TOKEN']));"
            res = subprocess.run(["node", "-e", full_code], capture_output=True, text=True, timeout=4)
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout.strip())
        except Exception as e:
            logger.debug(f"Could not extract token: {e}")
        return None

    def _init_server_sync(self):
        """التعرف على معرف السيرفر"""
        self.server_id = "LGudtxzl0I5KrSIe"

    async def init_client(self):
        return await asyncio.to_thread(self._init_server_sync)

    def _get_status_sync(self) -> Dict[str, Any]:
        self.server_id = "LGudtxzl0I5KrSIe"

        sec_k, sec_v = self._gen_sec()
        cookies = {
            "ATERNOS_SESSION": self.session_cookie,
            "ATERNOS_SERVER": self.server_id,
            f"ATERNOS_SEC_{sec_k}": sec_v
        }

        resp = self._safe_request("GET", "https://aternos.org/server/", cookies=cookies)
        if resp.status_code != 200:
            raise RuntimeError(f"فشل الاتصال بلوحة اتيرنوس (كود: {resp.status_code})")

        token = self._extract_token_from_html(resp.text)
        if token:
            self.ajax_token = token

        # 1. محاولة استخراج كائن lastStatus الدقيق
        status_match = re.search(r'var\s+lastStatus\s*=\s*(\{.+?\});', resp.text)
        if status_match:
            try:
                info = json.loads(status_match.group(1))
                self.domain = info.get("displayAddress") or info.get("ip") or "LORIAMC.aternos.me"
                dyn_ip = info.get("dynip")
                self.ip = f"{self.domain} ({dyn_ip})" if dyn_ip else self.domain
                self.software = info.get("software", "PaperMC")
                self.version = info.get("version", "1.20.6")
                self.players = f"{info.get('players', 0)}/{info.get('slots', 20)}"
                
                status_num = info.get("status", 0)
                # status mapping: 0=offline, 1=online, 2=starting, 3=stopping/saving, 6=preparing, 7=loading
                if status_num == 1:
                    self.status = "online"
                elif status_num in [2, 6, 7]:
                    self.status = "starting"
                elif status_num == 3:
                    self.status = "stopping"
                else:
                    self.status = info.get("class", "offline").lower()

                return {
                    "status": self.status,
                    "ip": self.domain,
                    "domain": self.domain,
                    "software": self.software,
                    "version": self.version,
                    "players_count": self.players,
                    "slots": info.get("slots", 20),
                    "players_list": info.get("playerlist", [])
                }
            except Exception as e:
                logger.debug(f"Failed to parse lastStatus JSON: {e}")

        # 2. خطة بديلة عبر قراءة عناصر HTML
        soup = BeautifulSoup(resp.text, "html.parser")
        ip_elem = soup.find(class_=lambda c: c and "server-ip" in c)
        status_elem = soup.find(class_=lambda c: c and "statuslabel-label" in c)
        software_elem = soup.find(id="software")
        version_elem = soup.find(id="version")
        players_elem = soup.find(id="players")

        if ip_elem:
            ip_raw = ip_elem.text.strip().split("\n")[0].strip()
            self.ip = ip_raw
            self.domain = ip_raw

        if status_elem:
            raw_st = status_elem.text.strip().lower()
            if "offline" in raw_st or "غير متصل" in raw_st:
                self.status = "offline"
            elif "online" in raw_st or "متصل" in raw_st:
                self.status = "online"
            elif "starting" in raw_st or "loading" in raw_st or "inline" in raw_st:
                self.status = "starting"
            elif "preparing" in raw_st:
                self.status = "preparing"
            elif "queue" in raw_st or "waiting" in raw_st:
                self.status = "waiting"
            elif "confirm" in raw_st:
                self.status = "confirm"
            else:
                self.status = raw_st

        if software_elem:
            self.software = software_elem.text.strip()
            
        if version_elem:
            self.version = version_elem.text.strip()
            
        if players_elem:
            self.players = players_elem.text.strip()

        return {
            "status": self.status,
            "ip": self.ip or self.domain,
            "domain": self.domain,
            "software": self.software,
            "version": self.version,
            "players_count": self.players,
            "slots": 20,
            "players_list": []
        }

    async def get_status(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self._get_status_sync)

    def _send_action_sync(self, action: str, params: Optional[Dict[str, Any]] = None) -> bool:
        self.server_id = "LGudtxzl0I5KrSIe"

        # تأكيد وجود التوكن
        if not self.ajax_token:
            self._get_status_sync()

        sec_k, sec_v = self._gen_sec()
        sec = f"{sec_k}:{sec_v}"
        
        cookies = {
            "ATERNOS_SESSION": self.session_cookie,
            "ATERNOS_SERVER": self.server_id,
            f"ATERNOS_SEC_{sec_k}": sec_v
        }

        url = f"https://aternos.org/ajax/server/{action}?SEC={sec}"
        if self.ajax_token:
            url += f"&TOKEN={self.ajax_token}"

        if params:
            for k, v in params.items():
                url += f"&{k}={v}"

        resp = self._safe_request("GET", url, cookies=cookies)
        logger.info(f"Action {action} on {self.server_id} response: {resp.status_code} - {resp.text[:150]}")
        
        if resp.status_code == 200:
            try:
                res_data = resp.json()
                if not res_data.get("success", False):
                    err = res_data.get("error")
                    data_obj = res_data.get("data") or {}
                    if (err == "eula" or (isinstance(data_obj, dict) and data_obj.get("status") == "eula")) and action == "start":
                        logger.info("تم اكتشاف طلب قبول اتفاقية Mojang EULA، جاري القبول التلقائي...")
                        self._send_action_sync("accept-eula")
                        return self._send_action_sync("start", params)
                    if err:
                        raise RuntimeError(err)
            except json.JSONDecodeError:
                pass
            return True
        return False

    async def start(self, headstart: int = 0):
        return await asyncio.to_thread(
            self._send_action_sync,
            "start",
            {"headstart": headstart, "access-credits": 0}
        )

    async def stop(self):
        return await asyncio.to_thread(self._send_action_sync, "stop")

    async def restart(self):
        return await asyncio.to_thread(self._send_action_sync, "restart")

    async def confirm(self):
        return await asyncio.to_thread(self._send_action_sync, "confirm")
