import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands

from config import DISCORD_TOKEN, NOTIFICATION_ROLE_ID, ADMIN_ROLE_IDS
from aternos_manager import AternosManager

# إعداد التسجيل (Logging)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AternosBot")

# إعداد البوت
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
aternos = AternosManager()

# مهمة المراقبة الحالية لضمان تشغيل مراقب واحد فقط دائماً
current_watch_task: asyncio.Task = None
notification_sent = False

async def has_admin_permission(interaction: discord.Interaction) -> bool:
    """التحقق الشامل والمباشر من رتب المستخدم في ديسكورد"""
    if not interaction.guild:
        return False

    # 1. إذا كان صاحب السيرفر
    if interaction.guild.owner_id == interaction.user.id:
        return True

    user_role_ids = set()
    user_role_names = set()

    # أ) من _data الداخلي لـ interaction
    if hasattr(interaction, "_data") and isinstance(interaction._data, dict):
        mem_data = interaction._data.get("member", {})
        for r_id in mem_data.get("roles", []):
            user_role_ids.add(str(r_id))
            if str(r_id).isdigit():
                user_role_ids.add(int(r_id))

    # ب) من interaction.user._roles
    if hasattr(interaction.user, "_roles"):
        for r_id in getattr(interaction.user, "_roles", []):
            user_role_ids.add(str(r_id))
            if str(r_id).isdigit():
                user_role_ids.add(int(r_id))

    # ج) من interaction.user.roles
    if hasattr(interaction.user, "roles"):
        for role in getattr(interaction.user, "roles", []):
            user_role_ids.add(str(role.id))
            user_role_ids.add(role.id)
            user_role_names.add(role.name.lower())

    # د) محاولة fetch_member من ديسكورد API مباشرة
    try:
        member = await interaction.guild.fetch_member(interaction.user.id)
        if member:
            if hasattr(member, "_roles"):
                for r_id in member._roles:
                    user_role_ids.add(str(r_id))
                    if str(r_id).isdigit():
                        user_role_ids.add(int(r_id))
            for role in member.roles:
                user_role_ids.add(str(role.id))
                user_role_ids.add(role.id)
                user_role_names.add(role.name.lower())
    except Exception as e:
        logger.debug(f"fetch_member notice: {e}")

    # تحويل الرتب المستهدفة للمطابقة
    admin_targets = set(ADMIN_ROLE_IDS) | {str(r) for r in ADMIN_ROLE_IDS}

    # 2. مطابقة المعرفات (Role IDs)
    if any(r in admin_targets for r in user_role_ids):
        logger.info(f"تم السماح للمستخدم {interaction.user.name} عبر مطابقة ID الرتبة.")
        return True

    # 3. مطابقة اسم الرتبة (مثل Mc Admin أو Mc Owner)
    for name in user_role_names:
        if "mc admin" in name or "mc owner" in name or "admin" in name or "owner" in name:
            logger.info(f"تم السماح للمستخدم {interaction.user.name} عبر اسم الرتبة: {name}")
            return True

    # 4. صلاحيات الأدمن الإدارية
    if hasattr(interaction.user, "guild_permissions") and interaction.user.guild_permissions.administrator:
        return True

    logger.info(f"فحص صلاحيات {interaction.user.name} - رتب الـ IDs: {user_role_ids} - الأسماء: {user_role_names} - الأدمن المطلوب: {admin_targets}")
    return False

STATUS_MAP = {
    "offline": ("🔴 مغلق (Offline)", 0xE74C3C),
    "online": ("🟢 يعمل (Online)", 0xFF77A9),
    "starting": ("🟡 جاري التشغيل (Starting...)", 0xF1C40F),
    "loading": ("🟡 جاري التحميل (Loading...)", 0xF1C40F),
    "preparing": ("🟡 جاري التحضير (Preparing...)", 0xF39C12),
    "waiting": ("⏳ في قائمة الانتظار (In Queue...)", 0x3498DB),
    "stopping": ("🟠 جاري الإيقاف (Stopping...)", 0xE67E22),
    "saving": ("💾 جاري حفظ البيانات (Saving...)", 0x9B59B6),
    "confirm": ("⚠️ مطلوب التأكيد (Confirming...)", 0xE67E22),
}

async def safe_reply(interaction: discord.Interaction, embed: discord.Embed = None, content: str = None, ephemeral: bool = False):
    """إرسال الرد بدقة دون تكرار"""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
    except Exception as e:
        logger.warning(f"تعذر الرد عبر interaction ({e})")
        # لا نقوم بالإرسال في الشات العام إذا كان الأمر مخصصاً للظهور السري (ephemeral)
        if not ephemeral and interaction.channel:
            try:
                await interaction.channel.send(content=content, embed=embed)
            except Exception as ch_err:
                logger.error(f"فشل الإرسال في الروم: {ch_err}")

def create_status_embed(data: dict) -> discord.Embed:
    raw_status = data.get("status", "offline").lower()
    title_text, color = STATUS_MAP.get(raw_status, (f"⚪ الحالة: {raw_status}", 0xFF77A9))
    
    embed = discord.Embed(
        title=f"⛏️ حالة سيرفر ماينكرافت: {data.get('domain', 'Aternos')}",
        description=f"**الحالة:** {title_text}",
        color=color
    )
    
    embed.add_field(name="🌐 العنوان (IP):", value=f"`{data.get('ip', 'غير متاح')}`", inline=True)
    embed.add_field(name="🎮 الإصدار:", value=f"`{data.get('software', 'Vanilla')} {data.get('version', '')}`", inline=True)
    embed.add_field(
        name="👥 اللاعبين المتصلين:",
        value=f"`{data.get('players_count', 0)} / {data.get('slots', 20)}`",
        inline=False
    )
    
    players_list = data.get("players_list", [])
    if players_list:
        players_str = ", ".join([f"`{p}`" for p in players_list])
        embed.add_field(name="📋 المتواجدون الآن:", value=players_str, inline=False)
        
    embed.set_footer(text="Aternos Server Manager Bot • تم التحديث")
    embed.timestamp = discord.utils.utcnow()
    return embed

def start_single_watcher(interaction: discord.Interaction):
    """إلغاء أي مراقب سابق وتشغيل مراقب واحد فقط لمنع تكرار الرسائل"""
    global current_watch_task, notification_sent
    if current_watch_task and not current_watch_task.done():
        current_watch_task.cancel()
        
    notification_sent = False
    current_watch_task = asyncio.create_task(watch_server_startup(interaction))

async def watch_and_start_after_stop(interaction: discord.Interaction):
    """الانتظار حتى ينتهي السيرفر من الإيقاف ثم تشغيله تلقائياً"""
    try:
        for _ in range(25):  # الانتظار لمدة تصل إلى دقيقتين
            await asyncio.sleep(5)
            st = await aternos.get_status()
            raw_st = st.get("status", "offline").lower()
            if raw_st == "offline":
                logger.info("اكتمل إيقاف السيرفر، جاري البدء بالتشغيل الآن...")
                await aternos.start()
                embed = discord.Embed(
                    title="🚀 تم بدء تشغيل السيرفر تلقائياً!",
                    description="اكتمل إيقاف الجلسة السابقة والآن السيرفر في مرحلة الإقلاع، سيتم إشعاركم فور اكتمال التشغيل.",
                    color=0xFF77A9
                )
                try:
                    if interaction and hasattr(interaction, "followup"):
                        await interaction.followup.send(embed=embed)
                    elif interaction and interaction.channel:
                        await interaction.channel.send(embed=embed)
                except Exception:
                    pass
                start_single_watcher(interaction)
                return
                
        if interaction and interaction.channel:
            try:
                await interaction.channel.send("⚠️ استغرق إيقاف السيرفر وقتاً طويلاً، يرجى كتابة الأمر `/start` مرة أخرى.")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"خطأ أثناء انتظار إيقاف السيرفر: {e}")

async def watch_server_startup(interaction: discord.Interaction):
    """مهمة في الخلفية لمراقبة تشغيل السيرفر حتى يصبح Online (ترسل إشعاراً واحداً فقط)"""
    global notification_sent
    try:
        max_checks = 120  # الفحص لمدة تصل إلى 20 دقيقة (كل 10 ثوان)
        checks = 0
        
        while checks < max_checks:
            await asyncio.sleep(10)
            checks += 1
            
            try:
                data = await aternos.get_status()
                raw_status = data.get("status", "offline").lower()
                
                # تأكيد الطابور تلقائياً إذا طلب اتيرنوس ذلك
                if raw_status == "confirm":
                    logger.info("تأكيد الطابور تلقائياً...")
                    await aternos.confirm()
                
                # إذا أصبح السيرفر أونلاين ولم يتم إرسال الإشعار مسبقاً
                if raw_status == "online":
                    if not notification_sent:
                        notification_sent = True
                        user_mention = interaction.user.mention if (interaction and interaction.user) else ""
                        mention_text = f"<@&{NOTIFICATION_ROLE_ID}>" if NOTIFICATION_ROLE_ID else user_mention
                        
                        embed = discord.Embed(
                            title="🎉 السيرفر شغال الآن وهو جاهز للعب!",
                            description="يا أميرات السيرفر متاح وجاهز للدخول الآن!\n\nاستمتعوا باللعب! 🎮",
                            color=0xFF77A9
                        )
                        embed.add_field(name="📌 الآي بي (IP):", value=f"`{data.get('ip')}`", inline=False)
                        embed.add_field(name="🎮 الإصدار:", value=f"`{data.get('software')} {data.get('version')}`", inline=False)
                        embed.set_footer(text="استمتعوا باللعب! 🎮")
                        embed.timestamp = discord.utils.utcnow()
                        
                        sent = False
                        # 1. المحاولة عبر interaction followup (يعمل ويتجاوز قيود صلاحيات الروم)
                        try:
                            if interaction and hasattr(interaction, "followup"):
                                await interaction.followup.send(content=mention_text, embed=embed)
                                sent = True
                                logger.info("تم إرسال إشعار تشغيل السيرفر عبر followup بنجاح!")
                        except Exception as follow_err:
                            logger.warning(f"تعذر الإرسال عبر followup ({follow_err})، جاري المحاولة عبر القناة المباشرة...")

                        # 2. المحاولة عبر القناة المباشرة
                        if not sent and interaction and interaction.channel:
                            try:
                                await interaction.channel.send(content=mention_text, embed=embed)
                                sent = True
                                logger.info("تم إرسال إشعار تشغيل السيرفر في القناة بنجاح!")
                            except Exception as ch_err:
                                logger.error(f"تعذر إرسال الإشعار في القناة: {ch_err}")

                        # 3. خطة احتياطية في الخاص للمستخدم
                        if not sent and interaction and interaction.user:
                            try:
                                await interaction.user.send(content=mention_text, embed=embed)
                                logger.info("تم إرسال الإشعار في الخاص للمستخدم بنجاح!")
                            except Exception:
                                pass
                    break
                
                # إذا تم إيقاف السيرفر بعد البدء
                elif raw_status == "offline" and checks > 6:
                    logger.info("توقف السيرفر أو فشل التشغيل.")
                    break
                    
            except Exception as e:
                logger.error(f"خطأ أثناء مراقبة السيرفر: {e}")
                
    except asyncio.CancelledError:
        logger.info("تم إلغاء مهمة المراقبة السابقة بنجاح.")

@bot.event
async def on_ready():
    logger.info(f"تم تسجيل الدخول بنجاح كـ {bot.user} (ID: {bot.user.id})")
    try:
        await aternos.init_client()
        logger.info("تم الاتصال بـ Aternos بنجاح!")
    except Exception as e:
        logger.error(f"تحذير: فشل الاتصال الأولي باتيرنوس ({e})")
        
    try:
        synced = await bot.tree.sync()
        logger.info(f"تمت مزامنة {len(synced)} أمر من أوامر السلاش (Slash Commands).")
    except Exception as e:
        logger.error(f"فشل في مزامنة أوامر السلاش: {e}")
        
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="/start | /status")
    )

@bot.tree.command(name="status", description="عرض حالة سيرفر ماينكرافت ومعلومات الاتصال")
async def status_cmd(interaction: discord.Interaction):
    try:
        await interaction.response.defer(thinking=True)
    except Exception:
        pass
        
    try:
        data = await aternos.get_status()
        embed = create_status_embed(data)
        await safe_reply(interaction, embed=embed)
    except Exception as e:
        logger.error(f"خطأ في أمر status: {e}")
        await safe_reply(interaction, content=f"❌ حدث خطأ أثناء جلب حالة السيرفر:\n`{e}`", ephemeral=True)

@bot.tree.command(name="start", description="تشغيل سيرفر ماينكرافت على Aternos")
async def start_cmd(interaction: discord.Interaction):
    try:
        await interaction.response.defer(thinking=True)
    except Exception:
        pass
        
    try:
        status_data = await aternos.get_status()
        current_status = status_data.get("status", "offline").lower()
        
        if current_status == "online":
            embed = discord.Embed(
                title="⚡ السيرفر شغال بالفعل!",
                description=f"السيرفر متصل ومتاح للعب الآن عبر الآي بي:\n`{status_data.get('ip')}`",
                color=0xFF77A9
            )
            await safe_reply(interaction, embed=embed)
            return
            
        if current_status in ["starting", "loading", "preparing", "waiting", "confirm"]:
            embed = discord.Embed(
                title="⏳ السيرفر جاري تشغيله بالفعل!",
                description="السيرفر الآن في مرحلة الإقلاع / الانتظار، سيتم إشعاركم فور اكتمال التشغيل.",
                color=0xF1C40F
            )
            await safe_reply(interaction, embed=embed)
            start_single_watcher(interaction)
            return

        if current_status in ["stopping", "saving"]:
            embed = discord.Embed(
                title="⏳ السيرفر في مرحلة الإيقاف حالياً",
                description="جاري حفظ العالم وإنهاء الجلسة السابقة، سأقوم ببدء تشغيله تلقائياً فور اكتمال الإيقاف...",
                color=0xE67E22
            )
            await safe_reply(interaction, embed=embed)
            asyncio.create_task(watch_and_start_after_stop(interaction))
            return
            
        # إرسال طلب التشغيل
        await aternos.start()
        
        embed = discord.Embed(
            title="🚀 تم إرسال أمر التشغيل بنجاح!",
            description="جاري تحضير السيرفر ووضعه في قائمة الانتظار...\nسأقوم بإرسال تنبيه في هذا الروم أول ما يشتغل ويصبح **Online**.",
            color=0xFF77A9
        )
        embed.set_footer(text="يرجى الانتظار قليلاً...")
        await safe_reply(interaction, embed=embed)
        
        # بدء مهمة المراقبة المنفردة في الخلفية
        start_single_watcher(interaction)
        
    except Exception as e:
        logger.error(f"خطأ في أمر start: {e}")
        await safe_reply(interaction, content=f"❌ تعذر تشغيل السيرفر:\n`{e}`", ephemeral=True)

@bot.tree.command(name="stop", description="إيقاف تشغيل السيرفر (للمشرفين فقط)")
async def stop_cmd(interaction: discord.Interaction):
    try:
        await interaction.response.defer(thinking=True, ephemeral=True)
    except Exception:
        pass
        
    if not await has_admin_permission(interaction):
        embed = discord.Embed(
            title="🚫 غير مصرح لك",
            description="عذراً، هذا الأمر متاح فقط للمشرفين والرتب المصرح لها!",
            color=0xE74C3C
        )
        await safe_reply(interaction, embed=embed, ephemeral=True)
        return
        
    try:
        await aternos.stop()
        embed = discord.Embed(
            title="🛑 تم إرسال أمر الإيقاف",
            description="جاري إيقاف السيرفر وحفظ البيانات الآن...",
            color=0xE67E22
        )
        await safe_reply(interaction, embed=embed, ephemeral=True)
    except Exception as e:
        logger.error(f"خطأ في أمر stop: {e}")
        await safe_reply(interaction, content=f"❌ تعذر إيقاف السيرفر:\n`{e}`", ephemeral=True)

@bot.tree.command(name="restart", description="إعادة تشغيل السيرفر (للمشرفين فقط)")
async def restart_cmd(interaction: discord.Interaction):
    try:
        await interaction.response.defer(thinking=True, ephemeral=True)
    except Exception:
        pass
        
    if not await has_admin_permission(interaction):
        embed = discord.Embed(
            title="🚫 غير مصرح لك",
            description="عذراً، هذا الأمر متاح فقط للمشرفين والرتب المصرح لها!",
            color=0xE74C3C
        )
        await safe_reply(interaction, embed=embed, ephemeral=True)
        return
        
    try:
        await aternos.restart()
        embed = discord.Embed(
            title="🔄 جاري إعادة تشغيل السيرفر",
            description="تم إرسال أمر إعادة التشغيل بنجاح، سيتم تنبيهكم عند عودته للعمل.",
            color=0xFF77A9
        )
        await safe_reply(interaction, embed=embed, ephemeral=True)
        start_single_watcher(interaction)
    except Exception as e:
        logger.error(f"خطأ في أمر restart: {e}")
        await safe_reply(interaction, content=f"❌ تعذر إعادة تشغيل السيرفر:\n`{e}`", ephemeral=True)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("خطأ: يرجى التأكد من إضافة DISCORD_TOKEN في ملف .env")
    else:
        bot.run(DISCORD_TOKEN)
