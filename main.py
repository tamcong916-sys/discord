import os
import discord
from discord.ext import commands

# Cấu hình Intents (quyền hạn cơ bản cho bot)
intents = discord.Intents.default()
intents.message_content = True  # Cần thiết để bot đọc được tin nhắn

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Bot đã kết nối thành công với tên: {bot.user}")


@bot.command()
async def ping(ctx):
    """Gõ !ping -> Bot trả lời Pong!"""
    await ctx.send("Pong! 🏓 Bot đang hoạt động hoàn hảo!")


@bot.command()
async def xin_chao(ctx):
    """Gõ !xin_chao -> Bot chào lại"""
    await ctx.send(f"Xin chào {ctx.author.mention}! Chúc bạn một ngày tốt lành!")


# Thay 'TOKEN_CUA_BAN' bằng Token Bot lấy từ Discord Developer Portal
# CẢNH BÁO: Không công khai Token này lên GitHub public!
TOKEN = os.getenv("DISCORD_TOKEN", "THAY_TOKEN_CUA_BAN_VAO_DAY")

if __name__ == "__main__":
    if TOKEN == "THAY_TOKEN_CUA_BAN_VAO_DAY":
        print("⚠️ Lỗi: Bạn chưa điền Discord Bot Token!")
    else:
        bot.run(TOKEN)
