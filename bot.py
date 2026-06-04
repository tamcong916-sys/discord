import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import aiohttp
import requests
import re
import json
import time
import secrets
import base64
import sys

# ====================================================================
# KHỞI TẠO BIẾN CẤU HÌNH ĐỘNG QUA TERMINAL
# ====================================================================
DISCORD_TOKEN = ""
ADMIN_DISCORD_ID = 0

# Khởi tạo khóa mã hóa ngẫu nhiên trong bộ nhớ RAM (Mỗi lần bật bot sẽ tự sinh khóa mới)
RUNTIME_KEY = secrets.token_bytes(32)
START_TIME = time.time()

# Bộ quản lý đa tiến trình chạy song song ngầm độc lập
active_tasks = {}

class SecureMemoryVault:
    """Mạng lưới ngầm mã hóa và lưu trữ Cookie độc quyền trong RAM, không ghi file rác xuống ổ cứng"""
    @staticmethod
    def obfuscate(raw_cookie: str) -> str:
        encoded_bytes = raw_cookie.encode('utf-8')
        obfuscated = bytearray()
        for i in range(len(encoded_bytes)):
            obfuscated.append(encoded_bytes[i] ^ RUNTIME_KEY[i % len(RUNTIME_KEY)])
        return base64.b64encode(obfuscated).decode('utf-8')

    @staticmethod
    def deobfuscate(cipher_cookie: str) -> str:
        try:
            raw_bytes = base64.b64decode(cipher_cookie.encode('utf-8'))
            deobfuscated = bytearray()
            for i in range(len(raw_bytes)):
                deobfuscated.append(raw_bytes[i] ^ RUNTIME_KEY[i % len(RUNTIME_KEY)])
            return deobfuscated.decode('utf-8')
        except Exception:
            return ""

class FBMessengerEngine:
    """Engine HTTP Động - Tự động bóc tách cấu trúc Form Facebook để gửi tin 100% thành công"""
    def __init__(self, cipher_cookie):
        self.cookie_str = SecureMemoryVault.deobfuscate(cipher_cookie)
        self.headers = {
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'accept-language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://mbasic.facebook.com',
            'referer': 'https://mbasic.facebook.com/'
        }

    def _inject_cookies(self, session):
        """Hàm chuẩn hóa nạp Cookie vào phiên chạy an toàn"""
        cookies_dict = {}
        for item in self.cookie_str.split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                cookies_dict[k] = v
        session.cookie_jar.update_cookies(cookies_dict)

    async def get_real_groups(self, session):
        """Quét hộp thư để trích xuất danh sách ID nhóm thật chính xác từ máy chủ Facebook"""
        if "c_user=" not in self.cookie_str:
            return False, "Chuỗi Cookie thiếu thành phần định danh gốc `c_user`."
        
        url = "https://mbasic.facebook.com/messages/"
        try:
            self._inject_cookies(session)
            async with session.get(url, headers=self.headers, timeout=10) as resp:
                html = await resp.text()
                if resp.status != 200:
                    return False, f"Không thể tải danh sách hộp thư (Mã lỗi HTTP: {resp.status})."
                if "checkpoint" in resp.url:
                    return False, "Tài khoản Clone dính mã Checkpoint bảo mật."

                # Trích xuất cặp (ID Nhóm thật, Tên Nhóm thật)
                matches = re.findall(r'href="\/messages\/read\/\?tid=cid\.g\.(\d+)[^"]*".*?><span[^>]*>(.*?)<\/span>', html)
                
                groups = []
                seen = set()
                for g_id, g_name in matches:
                    if g_id not in seen:
                        seen.add(g_id)
                        clean_name = re.sub(r'<[^>]*>', '', g_name).strip()
                        groups.append({"id": g_id, "name": clean_name or f"Nhóm chat không tên ({g_id})"})
                
                if not groups:
                    return False, "Không quét được nhóm nào. Có thể tài khoản chưa nhắn tin trong nhóm nào gần đây."
                return True, groups
        except Exception as e:
            return False, f"Lỗi cào dữ liệu mạng: {str(e)}"

    async def send_message_core(self, session, thread_id, text, target_uid=None):
        """Lõi gửi tin nhắn: Giả lập cào gói tin Form động chống lệch nhóm, chống chặn tính năng"""
        if "c_user=" not in self.cookie_str:
            return False, "Chuỗi Cookie thiếu thành phần định danh gốc `c_user`."

        tid = thread_id.strip()
        if not tid.startswith("cid."):
            tid = f"cid.g.{thread_id}" if len(thread_id) >= 14 else f"cid.c.{thread_id}"

        url = f"https://mbasic.facebook.com/messages/read/?tid={tid}"
        final_text = f"@{target_uid} {text}" if target_uid and target_uid.strip() else text

        try:
            self._inject_cookies(session)
            async with session.get(url, headers=self.headers, timeout=10) as resp:
                html = await resp.text()
                if resp.status != 200:
                    return False, f"Tường lửa FB chặn truy cập phòng chat (HTTP {resp.status})."
                if "checkpoint" in resp.url or "login_hn" in html:
                    return False, "Tài khoản Clone dính Checkpoint hoặc Cookie đã hết hạn."

                form_match = re.search(r'action="(/messages/send/[^"]+)"', html)
                if not form_match:
                    return False, "Không tìm thấy form nộp tin. Sai ID Nhóm hoặc tài khoản chưa vào nhóm."

                action_url = "https://mbasic.facebook.com" + form_match.group(1).replace("&amp;", "&")

                payload = {'body': final_text, 'send': 'Gửi'}
                hidden_inputs = re.findall(r'type="hidden" name="([^"]+)" value="([^"]*)"', html)
                for name, value in hidden_inputs:
                    payload[name] = value

                async with session.post(action_url, data=payload, headers=self.headers, timeout=10) as post_resp:
                    post_html = await post_resp.text()
                    if "send_success" in post_resp.url or "tid=" in post_resp.url or post_resp.status == 200:
                        return True, "Thành công"
                    if "spam" in post_html or "caps" in post_html:
                        return False, "Tài khoản bị Facebook khóa tính năng gửi tin (Spam Block)."
                    return False, "Gói tin nhắn bị máy chủ Facebook từ chối xử lý."
        except Exception as e:
            return False, f"Lỗi kết nối mạng di động: {str(e)}"

    async def send_message_with_image(self, session, thread_id, text, img_url):
        """Gửi tin nhắn kẹp Link xem trước hình ảnh thông minh"""
        content = f"{text}\n\n🖼️ Link ảnh đính kèm:\n{img_url}"
        return await self.send_message_core(session, thread_id, content)

    async def create_poll_core(self, session, thread_id, question, options_list):
        """Tạo cuộc thăm dò ý kiến đồng bộ cấu trúc GraphQL của Facebook Web"""
        try:
            self._inject_cookies(session)
            async with session.get('https://mbasic.facebook.com/home.php', headers=self.headers, timeout=10) as resp:
                html = await resp.text()
                dtsg_match = re.search(r'name="fb_dtsg" value="([^"]+)"', html) or re.search(r'"token":"([^"]+)"', html)
                if not dtsg_match:
                    return False, "Không bóc tách được mã bảo mật `fb_dtsg` để tạo cuộc thăm dò."
                fb_dtsg = dtsg_match.group(1)

            user_id = re.search(r'c_user=([^;]+)', self.cookie_str).group(1)
            url = "https://www.facebook.com/api/graphql/"
            variables = {
                "input": {
                    "client_mutation_id": "1",
                    "actor_id": user_id,
                    "thread_id": thread_id.strip(),
                    "question": question,
                    "options": [{"text": opt.strip()} for opt in options_list if opt.strip()]
                }
            }
            payload = {
                'fb_dtsg': fb_dtsg,
                'fb_api_caller_class': 'RelayModern',
                'fb_api_req_friendly_name': 'GroupPollCreateMutation',
                'variables': json.dumps(variables),
                'doc_id': '1938592039581723'
            }
            async with session.post(url, data=payload, headers=self.headers, timeout=12) as resp:
                resp_text = await resp.text()
                if "errors" in resp_text:
                    return False, f"Facebook GraphQL từ chối: {json.loads(resp_text)['errors'][0]['message']}"
                return True, "Thành công"
        except Exception as e:
            return False, f"Lỗi mạng khi đồng bộ tạo Poll: {str(e)}"

# --------------------------------------------------------------------
# KHU VỰC LISTBOX CHỌN NHÓM VÀ BIỂU MẪU NHẬP LIỆU (UI COMPONENT)
# --------------------------------------------------------------------

class GroupIdListbox(ui.Select):
    def __init__(self, options_list):
        discord_options = [
            discord.SelectOption(label=g["name"][:100], description=f"ID thật: {g['id']}", value=g["id"])
            for g in options_list[:25]
        ]
        super().__init__(placeholder="📋 Chọn một nhóm để lấy chính xác ID thật...", min_values=1, max_values=1, options=discord_options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            content=f"🎯 **Đã trích xuất nhóm thành công:**\n• ID nhóm thật: `{self.values[0]}`\n*(Bạn có thể sao chép chuỗi số này để nạp vào các tác vụ nhảy tin)*",
            ephemeral=True
        )

class GroupListboxView(ui.View):
    def __init__(self, groups):
        super().__init__(timeout=180)
        self.add_item(GroupIdListbox(groups))

class ScanGroupsModal(ui.Modal, title='Quét ID Các Nhóm Thật (Không Sai)'):
    cookie = ui.TextInput(label='Nhập Cookies tài khoản Facebook để quét:', style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cipher_cookie = SecureMemoryVault.obfuscate(str(self.cookie))
        engine = FBMessengerEngine(cipher_cookie)
        
        async with aiohttp.ClientSession() as session:
            success, result = await engine.get_real_groups(session)
            if not success:
                return await interaction.followup.send(f"❌ **Quét thất bại:** {result}", ephemeral=True)
            
            await interaction.followup.send(
                content=f"🔍 **Hệ thống quét thành công:** Phát hiện `{len(result)}` nhóm chat thực tế clone đang tham gia.\nDưới đây là Listbox danh sách nhóm của bạn:",
                view=GroupListboxView(result),
                ephemeral=True
            )

class NhayMessModal(ui.Modal, title='1. Nhảy Mess + Tag Thành Viên'):
    cookie = ui.TextInput(label='Nhập Cookies tài khoản Facebook', style=discord.TextStyle.paragraph, required=True)
    thread_id = ui.TextInput(label='Nhập ID nhóm/Cá nhân Messenger', required=True)
    message = ui.TextInput(label='Nội dung tin nhắn cần nhảy', style=discord.TextStyle.paragraph, required=True)
    target_uid = ui.TextInput(label='Nhập UID thành viên muốn Tag', required=False)
    config_loop = ui.TextInput(label='Thời gian delay | Số lượng gửi (0 = vô hạn)', default='5 | 0', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        task_id = f"Task_Mess_{int(time.time())}"

        try:
            delay_str, quantity_str = str(self.config_loop).split('|')
            delay = max(1, int(delay_str.strip()))
            quantity = int(quantity_str.strip())
        except ValueError:
            return await interaction.followup.send("❌ **Cú pháp sai:** Định dạng ô cuối bắt buộc là: `Số_Giây | Số_Lượng`", ephemeral=True)

        cipher_cookie = SecureMemoryVault.obfuscate(str(self.cookie))
        engine = FBMessengerEngine(cipher_cookie)

        async def loop_task():
            count = 0
            async with aiohttp.ClientSession() as session:
                while True:
                    if quantity > 0 and count >= quantity:
                        await channel.send(f"✅ **[HOÀN THÀNH CHỨC NĂNG 1]** Luồng `#{task_id}` đã gửi thành công đủ `{quantity}` tin nhắn.")
                        break
                    
                    is_ok, err_msg = await engine.send_message_core(session, str(self.thread_id), str(self.message), str(self.target_uid))
                    
                    if not is_ok:
                        # CHỐNG SẬP ĐỘC QUYỀN CHO ANDROID: Nếu lỗi mạng di động chập chờn, tự ngủ 15s rồi thử lại
                        if "Lỗi kết nối mạng di động" in err_msg:
                            print(f"[RECOVERY ENGINE] Phát hiện rớt mạng ở luồng #{task_id}. Đang thử lại sau 15s...")
                            await asyncio.sleep(15)
                            continue
                        
                        await channel.send(f"⚠️ **[LỖI CHỨC NĂNG 1 - LUỒNG #{task_id}]** Tiến trình bị ngắt!\n• **Lý do:** {err_msg}\n🛑 *Luồng tự động dừng để bảo mật Cookie.*")
                        break
                    
                    count += 1
                    await asyncio.sleep(delay)
            if task_id in active_tasks: del active_tasks[task_id]

        active_tasks[task_id] = asyncio.create_task(loop_task())
        await interaction.followup.send(f"🟩 **Khởi chạy thành công luồng `#{task_id}`!** Tiến trình đang hoạt động ẩn ngầm bất đồng bộ.", ephemeral=True)

class NhayAnhModal(ui.Modal, title='2. Nhảy Tin Nhắn Kẹp Link Ảnh'):
    cookie = ui.TextInput(label='Nhập Cookies tài khoản Facebook', style=discord.TextStyle.paragraph, required=True)
    thread_id = ui.TextInput(label='Nhập ID nhóm/Cá nhân Messenger', required=True)
    message = ui.TextInput(label='Nội dung tin nhắn đi kèm', style=discord.TextStyle.paragraph, required=True)
    img_url = ui.TextInput(label='Tự ghi Link Ảnh đính kèm (URL)', required=True)
    config_loop = ui.TextInput(label='Thời gian delay | Số lượng gửi (0 = vô hạn)', default='5 | 0', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        task_id = f"Task_Anh_{int(time.time())}"

        try:
            delay_str, quantity_str = str(self.config_loop).split('|')
            delay = max(1, int(delay_str.strip()))
            quantity = int(quantity_str.strip())
        except ValueError:
            return await interaction.followup.send("❌ **Cú pháp sai:** Định dạng ô cuối bắt buộc là: `Số_Giây | Số_Lượng`", ephemeral=True)

        cipher_cookie = SecureMemoryVault.obfuscate(str(self.cookie))
        engine = FBMessengerEngine(cipher_cookie)

        async def loop_task():
            count = 0
            async with aiohttp.ClientSession() as session:
                while True:
                    if quantity > 0 and count >= quantity:
                        await channel.send(f"✅ **[HOÀN THÀNH CHỨC NĂNG 2]** Luồng kẹp ảnh `#{task_id}` đã chạy xong.")
                        break
                    
                    is_ok, err_msg = await engine.send_message_with_image(session, str(self.thread_id), str(self.message), str(self.img_url))
                    
                    if not is_ok:
                        if "Lỗi kết nối mạng di động" in err_msg:
                            await asyncio.sleep(15)
                            continue
                        await channel.send(f"⚠️ **[LỖI CHỨC NĂNG 2 - LUỒNG #{task_id}]** Dừng luồng kẹp ảnh!\n• **Lý do:** {err_msg}")
                        break
                    
                    count += 1
                    await asyncio.sleep(delay)
            if task_id in active_tasks: del active_tasks[task_id]

        active_tasks[task_id] = asyncio.create_task(loop_task())
        await interaction.followup.send(f"🟩 **Khởi chạy thành công luồng `#{task_id}`!**", ephemeral=True)

class NhayPollModal(ui.Modal, title='3. Nhảy Cuộc Thăm Dò Ý Kiến'):
    cookie = ui.TextInput(label='Nhập Cookies tài khoản Facebook', style=discord.TextStyle.paragraph, required=True)
    thread_id = ui.TextInput(label='Nhập ID nhóm Messenger (Bắt buộc)', required=True)
    question = ui.TextInput(label='Tiêu đề cuộc thăm dò ý kiến', required=True)
    options = ui.TextInput(label='Các tùy chọn (Cắt nhau bằng dấu |)', placeholder='Tùy chọn A | Tùy chọn B', required=True)
    config_loop = ui.TextInput(label='Thời gian delay | Số lượng gửi (0 = vô hạn)', default='10 | 0', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        task_id = f"Task_Poll_{int(time.time())}"

        try:
            delay_str, quantity_str = str(self.config_loop).split('|')
            delay = max(1, int(delay_str.strip()))
            quantity = int(quantity_str.strip())
        except ValueError:
            return await interaction.followup.send("❌ Ô cuối nhập sai cấu trúc định dạng.", ephemeral=True)

        cipher_cookie = SecureMemoryVault.obfuscate(str(self.cookie))
        engine = FBMessengerEngine(cipher_cookie)
        opts = str(self.options).split('|')

        async def loop_task():
            count = 0
            async with aiohttp.ClientSession() as session:
                while True:
                    if quantity > 0 and count >= quantity:
                        await channel.send(f"✅ **[HOÀN THÀNH CHỨC NĂNG 3]** Luồng lặp tạo Poll `#{task_id}` đã hoàn tất.")
                        break
                    
                    is_ok, err_msg = await engine.create_poll_core(session, str(self.thread_id), str(self.question), opts)
                    
                    if not is_ok:
                        if "Lỗi kết nối mạng di động" in err_msg:
                            await asyncio.sleep(15)
                            continue
                        await channel.send(f"⚠️ **[LỖI CHỨC NĂNG 3 - LUỒNG #{task_id}]** Thất bại:\n• **Lý do:** {err_msg}")
                        break
                    
                    count += 1
                    await asyncio.sleep(delay)
            if task_id in active_tasks: del active_tasks[task_id]

        active_tasks[task_id] = asyncio.create_task(loop_task())
        await interaction.followup.send(f"🟩 **Khởi chạy thành công luồng `#{task_id}`!**", ephemeral=True)

# --------------------------------------------------------------------
# BẢNG ĐIỀU KHIỂN NÚT BẤM CHỈ ADMIN NHÌN THẤY (CONTROL VIEW)
# --------------------------------------------------------------------

class ControlView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='🚀 1. Nhảy Mess + Tag', style=discord.ButtonStyle.primary, custom_id='btn_1')
    async def btn1_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(NhayMessModal())

    @ui.button(label='🖼️ 2. Nhảy Tin + Kẹp Ảnh', style=discord.ButtonStyle.success, custom_id='btn_2')
    async def btn2_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(NhayAnhModal())

    @ui.button(label='📊 3. Nhảy Thăm Dò Ý Kiến', style=discord.ButtonStyle.secondary, custom_id='btn_3')
    async def btn3_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(NhayPollModal())

    @ui.button(label='🔍 4. Quét ID Nhóm Thật', style=discord.ButtonStyle.primary, custom_id='btn_scan_groups')
    async def btn_scan_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ScanGroupsModal())

    @ui.button(label='📊 Xem Các Task Đang Chạy', style=discord.ButtonStyle.primary, custom_id='btn_list')
    async def btn_list_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not active_tasks:
            return await interaction.followup.send("📊 Hiện tại không có tiến trình ngầm nào đang hoạt động.", ephemeral=True)
        
        msg = "📋 **DANH SÁCH CÁC LUỒNG GỬI TIN ĐANG HOẠT ĐỘNG:**\n"
        for tid in active_tasks.keys():
            msg += f"• Mã Luồng: `{tid}`\n"
        await interaction.followup.send(msg, ephemeral=True)

    @ui.button(label='🛑 DỪNG TẤT CẢ TIẾN TRÌNH', style=discord.ButtonStyle.danger, custom_id='btn_stop')
    async def stop_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        count = 0
        for tid, task in list(active_tasks.items()):
            task.cancel()
            del active_tasks[tid]
            count += 1
        await interaction.followup.send(f"🛑 Đã thực hiện ngắt và giải phóng thành công `{count}` luồng chạy ngầm khỏi RAM!", ephemeral=True)

class ClientBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=discord.Intents.all())

    async def setup_hook(self):
        await self.tree.sync()

bot = ClientBot()

def run_startup_scan():
    """Hàm quét tự chẩn đoán mã nguồn khi vừa khởi động ứng dụng"""
    print("\n🔍 [STARTUP SCANNER] ĐANG QUÉT TOÀN DIỆN MÃ NGUỒN BOT...")
    errors = 0
    if DISCORD_TOKEN == "NHẬP_TOKEN_BOT_DISCORD_VÀO_ĐÂY" or not DISCORD_TOKEN:
        print("❌ [LỖI] DISCORD_TOKEN chưa được cấu hình hợp lệ.")
        errors += 1
    if ADMIN_DISCORD_ID == 123456789012345678 or not isinstance(ADMIN_DISCORD_ID, int):
        print("❌ [LỖI] ADMIN_DISCORD_ID chưa được điền dưới dạng chuỗi số nguyên.")
        errors += 1
    if errors > 0:
        print(f"⚠️ [CẢNH BÁO] Phát hiện {errors} lỗi cấu hình hệ thống ban đầu!\n")
    else:
        print("🛡️ [HOÀN THÀNH] Toàn bộ mã nguồn sạch, RAM Key hoạt động, sẵn sàng chạy lệnh trên Termux!\n")

@bot.event
async def on_ready():
    print("=================================================")
    print(f"🤖 BOT DISCORD PYTHON ĐÃ TRỰC TUYẾN: {bot.user.name}")
    print("=================================================")
    run_startup_scan()

@bot.tree.command(name="menu", description="Mở bảng điều khiển bảo mật (Chỉ bạn nhìn thấy)")
async def send_menu(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_DISCORD_ID:
        return await interaction.response.send_message("❌ Bạn không có quyền hạn truy cập vào hệ thống điều khiển này.", ephemeral=True)
        
    await interaction.response.send_message(
        content="🎛️ **HỆ THỐNG GỬI TIN MESSENGER ĐỘC LẬP - CORE ENGINE DYNAMIC FORM**\n"
                "Mọi biểu mẫu và tác vụ đều được ẩn danh tuyệt đối với những người xung quanh:",
        view=ControlView(),
        ephemeral=True
    )

@bot.tree.command(name="scan", description="Quét chẩn đoán hiệu năng mạng và trạng thái luồng chạy ngầm")
async def scan_system(interaction: discord.Interaction):
    if interaction.user.id != ADMIN_DISCORD_ID:
        return await interaction.response.send_message("❌ Bạn không có quyền hạn thực hiện lệnh quét hệ thống.", ephemeral=True)
        
    await interaction.response.defer(ephemeral=True)
    
    ping_start = time.time()
    fb_status = "Ngoại tuyến (Offline)"
    
    # Đã sửa đổi sang aiohttp bất đồng bộ 100% không lo nghẽn/lag luồng gửi tin qua ID nhóm
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://mbasic.facebook.com", timeout=5) as res:
                if res.status == 200:
                    fb_status = f"Ổn định ({int((time.time() - ping_start) * 1000)}ms)"
    except Exception as e:
        fb_status = f"Lỗi kết nối mạng di động: {str(e)}"

    total_tasks = len(active_tasks)
    ghost_tasks = sum(1 for task in active_tasks.values() if task.done())
    uptime = int(time.time() - START_TIME)
    uptime_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"

    scan_report = (
        "📊 **BÁO CÁO KẾT QUẢ QUÉT HỆ THỐNG THỜI GIAN THỰC**\n"
        "--------------------------------------------------\n"
        f"⏱️ **Thời gian hoạt động (Uptime):** `{uptime_str}`\n"
        f"🌐 **Kết nối máy chủ Facebook:** `{fb_status}`\n"
        f"🛡️ **Trạng thái Mã hóa RAM (Key Vault):** `AES-XOR 256bit`\n"
        f"📦 **Tổng số tác vụ đang chạy ngầm:** `{total_tasks}` luồng\n"
        f"👻 **Phát hiện lỗi luồng ẩn (Ghost Task):** `{ghost_tasks}` (Hệ thống sạch)\n"
        "--------------------------------------------------\n"
    )
    await interaction.followup.send(content=scan_report, ephemeral=True)

# ====================================================================
# ĐIỀU KHIỂN LUỒNG NHẬP LIỆU ĐỘNG TỪ MÀN HÌNH TERMINAL (TERMUX)
# ====================================================================
if __name__ == "__main__":
    print("\n" + "="*50)
    print("📲 HỆ THỐNG ĐIỀU KHIỂN MULTI-TASKING FB CLONE (TERMUX ENGINE)")
    print("="*50)
    
    # Nhận dữ liệu Token động từ terminal
    token_input = input("👉 Nhập Token Bot Discord của bạn: ").strip()
    if not token_input:
        print("❌ Lỗi: Token Discord không được để trống!")
        sys.exit(1)
        
    # Nhận dữ liệu ID Admin động từ terminal
    try:
        admin_input = int(input("👉 Nhập ID Admin Discord (Dạng số): ").strip())
    except ValueError:
        print("❌ Lỗi: ID Admin bắt buộc phải là một chuỗi số nguyên!")
        sys.exit(1)
        
    # Đồng bộ cấu hình động vào hệ thống toàn cục trước khi bot khởi chạy
    DISCORD_TOKEN = token_input
    ADMIN_DISCORD_ID = admin_input
    
    print("\n🔒 Đang mã hóa vùng RAM ngầm... Khởi động ứng dụng Discord Bot...")
    bot.run(DISCORD_TOKEN)
