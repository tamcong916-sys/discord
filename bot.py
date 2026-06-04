import discord
from discord.ext import commands
from discord import ui
import asyncio
import aiohttp
import requests
import re
import json
import time

# Cấu hình Token Bot Discord của bạn
DISCORD_TOKEN = "NHẬP_TOKEN_BOT_DISCORD_VÀO_ĐÂY"
PREFIX = "/"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Bộ lưu trữ quản lý đa tác vụ ngầm độc lập (Chạy song song không giới hạn)
active_tasks = {}

class FBMessengerEngine:
    """
    CORE MIDDLEWARE: Tự động quản lý, trích xuất và duy trì mã bảo mật fb_dtsg
    Giúp liên kết và đồng bộ toàn diện với hệ thống Facebook Web & Messenger App
    """
    def __init__(self, cookie_str):
        self.cookie_str = cookie_str
        self.fb_dtsg = None
        self.headers = {
            'cookie': cookie_str,
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'accept': '*/*',
            'accept-language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://mbasic.facebook.com',
            'referer': 'https://mbasic.facebook.com/'
        }

    def refresh_fb_dtsg(self):
        """Cào trực tiếp từ lớp giao diện mbasic/web để lấy mã fb_dtsg mới nhất"""
        if "c_user=" not in self.cookie_str:
            return False, "Chuỗi Cookie không hợp lệ (Thiếu thành phần định danh `c_user`)."
        try:
            # Gửi yêu cầu giả lập trình duyệt sạch
            res = requests.get('https://mbasic.facebook.com/home.php', headers={'cookie': self.cookie_str, 'user-agent': self.headers['user-agent']}, timeout=10)
            if res.status_code != 200:
                return False, f"Máy chủ Facebook từ chối kết nối (Mã lỗi: HTTP {res.status_code})."
                
            # Thuật toán tìm kiếm mã token bảo mật fb_dtsg bằng Regex
            match = re.search(r'name="fb_dtsg" value="([^"]+)"', res.text)
            if match:
                self.fb_dtsg = match.group(1)
                return True, self.fb_dtsg
                
            # Phương án dự phòng nếu tài khoản đang chuyển hướng giao diện Web hiện đại
            match_www = re.search(r'"DTSGInitialData",\[\],{"token":"([^"]+)"}', res.text)
            if match_www:
                self.fb_dtsg = match_www.group(1)
                return True, self.fb_dtsg
                
            if "checkpoint" in res.url:
                return False, "Tài khoản của bạn đã bị dính mã **Checkpoint (Khóa bảo mật)** từ Facebook."
                
            return False, "Không thể bóc tách mã bảo mật `fb_dtsg`. Cookie có thể đã hết hạn hoặc bị đăng xuất."
        except requests.exceptions.RequestException as e:
            return False, f"Lỗi mạng khi kết nối đồng bộ Facebook: {str(e)}"

    async def send_message_with_tag(self, session, thread_id, text, target_uid=None):
        """Xử lý gửi tin nhắn + cấu trúc thẻ Tag UID đồng bộ sang App Messenger"""
        # Luôn kiểm tra và làm tươi mã fb_dtsg trước khi đóng gói payload
        if not self.fb_dtsg:
            success, res = self.refresh_fb_dtsg()
            if not success:
                return False, res

        url = "https://mbasic.facebook.com/messages/send/?icm=1&refid=12"
        # Định dạng thẻ tag tối ưu cho giao diện nền tảng
        final_text = f"@{target_uid} {text}" if target_uid and target_uid.strip() else text

        payload = {
            'fb_dtsg': self.fb_dtsg,
            'body': final_text,
            'send': 'Gửi',
            'tids': f'cid.g.{thread_id}' if len(thread_id) > 10 else thread_id, # Tự động nhận diện ID Nhóm hoặc ID Cá nhân
        }

        try:
            async with session.post(url, data=payload, headers=self.headers, timeout=12) as resp:
                resp_text = await resp.text()
                if resp.status != 200:
                    return False, f"Facebook Web phản hồi mã lỗi HTTP {resp.status}."
                if "t_id" in resp_text or "send_success" in resp.url or resp.status == 200:
                    return True, "Thành công"
                if "spam" in resp_text or "caps" in resp_text:
                    return False, "Tài khoản bị Facebook chặn tính năng gửi tin nhắn (Block Spam)."
                return False, "Gửi thất bại. Sai ID nhóm hoặc tài khoản chưa tham gia nhóm chat này."
        except Exception as e:
            return False, f"Lỗi kết nối bất đồng bộ: {str(e)}"

    async def send_message_with_image(self, session, thread_id, text, img_url):
        """Gửi tin nhắn tích hợp kẹp link hình ảnh hiển thị dạng Grid View cực thông minh"""
        content = f"{text}\n\n🖼️ **Hình ảnh đính kèm:**\n{img_url}"
        return await self.send_message_with_tag(session, thread_id, content)

    async def create_poll(self, session, thread_id, question, options_list):
        """Khởi tạo cuộc thăm dò ý kiến bằng cách đồng bộ trực tiếp với GraphQL Facebook Web"""
        if not self.fb_dtsg:
            success, res = self.refresh_fb_dtsg()
            if not success:
                return False, res

        try:
            user_id_match = re.search(r'c_user=([^;]+)', self.cookie_str)
            if not user_id_match:
                return False, "Không bóc tách được ID người dùng (c_user) từ Cookie."
            actor_id = user_id_match.group(1)

            url = "https://www.facebook.com/api/graphql/"
            options_data = [{"text": opt.strip()} for opt in options_list if opt.strip()]

            variables = {
                "input": {
                    "client_mutation_id": "1",
                    "actor_id": actor_id,
                    "thread_id": thread_id,
                    "question": question,
                    "options": options_data
                }
            }

            payload = {
                'fb_dtsg': self.fb_dtsg,
                'fb_api_caller_class': 'RelayModern',
                'fb_api_req_friendly_name': 'GroupPollCreateMutation',
                'variables': json.dumps(variables),
                'doc_id': '1938592039581723' # Document ID gốc của tính năng tạo cuộc thăm dò trên Facebook
            }

            async with session.post(url, data=payload, headers=self.headers, timeout=12) as resp:
                resp_text = await resp.text()
                if "errors" in resp_text:
                    err_data = json.loads(resp_text)
                    return False, f"Lỗi Facebook GraphQL: {err_data['errors'][0]['message']}"
                if resp.status == 200:
                    return True, "Thành công"
                return False, "Không thể khởi tạo cuộc thăm dò ý kiến (Lỗi cấu trúc hoặc thiếu quyền hạn)."
        except Exception as e:
            return False, f"Lỗi hệ thống đồng bộ Poll: {str(e)}"

# --------------------------------------------------------------------
# ĐỊNH NGHĨA CÁC BIỂU MẪU (MODAL) ĐỘC LẬP - KIỂM SOÁT LỖI TỪNG CHỨC NĂNG
# --------------------------------------------------------------------

class NhayMessModal(ui.Modal, title='1. Nhảy Tin Nhắn + Tag Thành Viên'):
    cookie = ui.TextInput(label='Nhập Cookies tài khoản Facebook', style=discord.TextStyle.paragraph, required=True)
    thread_id = ui.TextInput(label='Nhập ID nhóm/Cá nhân Messenger', placeholder='Ví dụ: 8532410934', required=True)
    message = ui.TextInput(label='Nội dung tin nhắn cần nhảy', style=discord.TextStyle.paragraph, required=True)
    target_uid = ui.TextInput(label='Nhập UID thành viên muốn Tag', placeholder='Để trống nếu không cần tag', required=False)
    config_loop = ui.TextInput(label='Thời gian delay | Số lượng gửi (0 = vô hạn)', placeholder='Ví dụ: 5 | 100', default='5 | 0', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        task_id = f"Task_NhayMess_{int(time.time())}"

        try:
            delay_str, quantity_str = str(self.config_loop).split('|')
            delay = max(1, int(delay_str.strip()))
            quantity = int(quantity_str.strip())
        except ValueError:
            return await interaction.followup.send("❌ **Lỗi cấu trúc:** Ô cuối cùng phải nhập đúng định dạng: `Số_Giây | Số_Lượng`")

        engine = FBMessengerEngine(str(self.cookie))
        success, check_res = engine.refresh_fb_dtsg()
        
        # BÁO LỖI RIÊNG BIỆT NGAY TỪ BƯỚC KHỞI CHẠY NẾU KHÔNG KẾT NỐI ĐƯỢC FB_DTSG
        if not success:
            return await interaction.followup.send(f"❌ **LỖI KHỞI CHẠY CHỨC NĂNG 1 (`{task_id}`):**\nKhông thể liên kết ứng dụng do: {check_res}")

        async def loop_task():
            count = 0
            async with aiohttp.ClientSession() as session:
                while True:
                    if quantity > 0 and count >= quantity:
                        await channel.send(f"✅ **[HOÀN THÀNH TÁC VỤ #{task_id}]** Chức năng **Nhảy Mess + Tag** đã hoàn thành gửi đủ số lượng `{quantity}` tin nhắn!")
                        break
                    
                    is_ok, err_msg = await engine.send_message_with_tag(session, str(self.thread_id), str(self.message), str(self.target_uid))
                    
                    # THÔNG BÁO LỖI RIÊNG BIỆT TRONG QUÁ TRÌNH CHẠY TASK 1
                    if not is_ok:
                        await channel.send(f"⚠️ **[LỖI CHỨC NĂNG 1 - TIẾN TRÌNH #{task_id}]** Bị ngắt kết nối giữa chừng!\n• **Lý do:** {err_msg}\n🛑 *Hệ thống đã tự động hủy bỏ luồng này để bảo vệ tài khoản.*")
                        break
                    
                    count += 1
                    await asyncio.sleep(delay)
            if task_id in active_tasks: del active_tasks[task_id]

        active_tasks[task_id] = asyncio.create_task(loop_task())
        await interaction.followup.send(f"🟩 **Kích hoạt thành công mã task `#{task_id}`!** Hệ thống đang tự động nhảy tin và tag UID ngầm qua kết nối `fb_dtsg`...")

class NhayAnhModal(ui.Modal, title='2. Nhảy Tin Nhắn Kẹp Link Ảnh'):
    cookie = ui.TextInput(label='Nhập Cookies tài khoản Facebook', style=discord.TextStyle.paragraph, required=True)
    thread_id = ui.TextInput(label='Nhập ID nhóm/Cá nhân Messenger', required=True)
    message = ui.TextInput(label='Nội dung tin nhắn đi kèm', style=discord.TextStyle.paragraph, required=True)
    img_url = ui.TextInput(label='Tự ghi Link Ảnh đính kèm (URL)', placeholder='https://example.com/image.png', required=True)
    config_loop = ui.TextInput(label='Thời gian delay | Số lượng gửi (0 = vô hạn)', default='5 | 0', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        task_id = f"Task_NhayAnh_{int(time.time())}"

        try:
            delay_str, quantity_str = str(self.config_loop).split('|')
            delay = max(1, int(delay_str.strip()))
            quantity = int(quantity_str.strip())
        except ValueError:
            return await interaction.followup.send("❌ **Lỗi cấu trúc:** Vui lòng nhập đúng định dạng ô cuối: `Số_Giây | Số_Lượng`")

        engine = FBMessengerEngine(str(self.cookie))
        success, check_res = engine.refresh_fb_dtsg()
        
        # BÁO LỖI RIÊNG BIỆT CHO CHỨC NĂNG 2 KHI SAI COOKIE/DTSG
        if not success:
            return await interaction.followup.send(f"❌ **LỖI KHỞI CHẠY CHỨC NĂNG 2 (`{task_id}`):**\nKết nối ứng dụng thất bại do: {check_res}")

        async def loop_task():
            count = 0
            async with aiohttp.ClientSession() as session:
                while True:
                    if quantity > 0 and count >= quantity:
                        await channel.send(f"✅ **[HOÀN THÀNH TÁC VỤ #{task_id}]** Chức năng **Nhảy Kẹp Ảnh** đã gửi đủ số lượng hoàn hảo!")
                        break
                    
                    is_ok, err_msg = await engine.send_message_with_image(session, str(self.thread_id), str(self.message), str(self.img_url))
                    
                    # THÔNG BÁO LỖI RIÊNG BIỆT TRONG QUÁ TRÌNH CHẠY TASK 2
                    if not is_ok:
                        await channel.send(f"⚠️ **[LỖI CHỨC NĂNG 2 - TIẾN TRÌNH #{task_id}]** Không thể gửi ảnh!\n• **Lý do:** {err_msg}\n🛑 *Luồng chạy ngầm đã được ngắt.*")
                        break
                    
                    count += 1
                    await asyncio.sleep(delay)
            if task_id in active_tasks: del active_tasks[task_id]

        active_tasks[task_id] = asyncio.create_task(loop_task())
        await interaction.followup.send(f"🟩 **Kích hoạt thành công mã task `#{task_id}`!** Hệ thống đang chạy vòng lặp gửi tin kẹp ảnh.")

class NhayPollModal(ui.Modal, title='3. Nhảy Cuộc Thăm Dò Ý Kiến'):
    cookie = ui.TextInput(label='Nhập Cookies tài khoản Facebook', style=discord.TextStyle.paragraph, required=True)
    thread_id = ui.TextInput(label='Nhập ID nhóm Messenger (Bắt buộc)', required=True)
    question = ui.TextInput(label='Tiêu đề cuộc thăm dò ý kiến', required=True)
    options = ui.TextInput(label='Các tùy chọn (Cắt nhau bằng dấu |)', placeholder='Tùy chọn 1 | Tùy chọn 2 | Tùy chọn 3', required=True)
    config_loop = ui.TextInput(label='Thời gian delay | Số lượng gửi (0 = vô hạn)', default='10 | 0', required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        task_id = f"Task_NhayPoll_{int(time.time())}"

        try:
            delay_str, quantity_str = str(self.config_loop).split('|')
            delay = max(1, int(delay_str.strip()))
            quantity = int(quantity_str.strip())
        except ValueError:
            return await interaction.followup.send("❌ **Lỗi cấu trúc:** Vui lòng nhập đúng định dạng ô cuối: `Số_Giây | Số_Lượng`")

        engine = FBMessengerEngine(str(self.cookie))
        success, check_res = engine.refresh_fb_dtsg()
        
        # BÁO LỖI RIÊNG BIỆT CHO CHỨC NĂNG 3 KHI KHÔNG TẠO ĐƯỢC GRAPHQL TOKEN
        if not success:
            return await interaction.followup.send(f"❌ **LỖI KHỞI CHẠY CHỨC NĂNG 3 (`{task_id}`):**\nKhông thể đồng bộ cấu trúc GraphQL do: {check_res}")

        opts = str(self.options).split('|')

        async def loop_task():
            count = 0
            async with aiohttp.ClientSession() as session:
                while True:
                    if quantity > 0 and count >= quantity:
                        await channel.send(f"✅ **[HOÀN THÀNH TÁC VỤ #{task_id}]** Chức năng **Tạo Cuộc Thăm Dò** đã chạy xong.")
                        break
                    
                    is_ok, err_msg = await engine.create_poll(session, str(self.thread_id), str(self.question), opts)
                    
                    # THÔNG BÁO LỖI RIÊNG BIỆT TRONG QUÁ TRÌNH CHẠY TASK 3
                    if not is_ok:
                        await channel.send(f"⚠️ **[LỖI CHỨC NĂNG 3 - TIẾN TRÌNH #{task_id}]** Không thể tạo Poll!\n• **Lý do:** {err_msg}\n🛑 *Dừng vòng lặp tác vụ.*")
                        break
                    
                    count += 1
                    await asyncio.sleep(delay)
            if task_id in active_tasks: del active_tasks[task_id]

        active_tasks[task_id] = asyncio.create_task(loop_task())
        await interaction.followup.send(f"🟩 **Kích hoạt thành công mã task `#{task_id}`!** Hệ thống đang tự động spam tạo cuộc thăm dò.")

# --------------------------------------------------------------------
# GIAO DIỆN NÚT BẤM ĐIỀU KHIỂN TRÊN DISCORD (VIEW COMPONENT)
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

    @ui.button(label='📊 Xem Gói Task Đang Chạy', style=discord.ButtonStyle.primary, custom_id='btn_list')
    async def btn_list_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not active_tasks:
            return await interaction.followup.send("📊 Hiện tại không có tiến trình ngầm nào đang hoạt động.")
        
        msg = "📋 **DANH SÁCH LUỒNG GỬI TIN FB ĐANG HOẠT ĐỘNG:**\n"
        for tid in active_tasks.keys():
            msg += f"• Mã Tiến Trình: `{tid}`\n"
        await interaction.followup.send(msg)

    @ui.button(label='🛑 DỪNG TẤT CẢ TIẾN TRÌNH', style=discord.ButtonStyle.danger, custom_id='btn_stop')
    async def stop_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        count = 0
        for tid, task in list(active_tasks.items()):
            task.cancel()
            del active_tasks[tid]
            count += 1
                
        if count > 0:
            await interaction.followup.send(f"🛑 Đã thực hiện lệnh cưỡng chế dừng thành công `{count}` luồng chạy ngầm của bạn!")
        else:
            await interaction.followup.send("⚠️ Hệ thống ghi nhận bạn không có tiến trình nào đang hoạt động.")

@bot.event
async def on_ready():
    print("=================================================")
    print(f"🤖 BOT DISCORD PYTHON TRỰC TUYẾN THÀNH CÔNG: {bot.user.name}")
    print("=================================================")

@bot.command(name="menu")
async def send_menu(ctx):
    """Lệnh kích hoạt Menu tổng điều khiển"""
    await ctx.send(
        content="🎛️ **BẢNG ĐIỀU KHIỂN HỆ THỐNG GỬI TIN FACEBOOK - ĐỒNG BỘ FB_DTSG TOÀN DIỆN**\n"
                "Mỗi nút bấm quản lý một biểu mẫu, một Task ngầm độc lập và có hệ thống báo lỗi chuyên biệt khi lỗi:",
        view=ControlView()
    )

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
