# bot/main.py
import asyncio
import logging
import os
import re
from typing import Dict

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message

from bot.config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID
from bot import db
from bot.extractor import extract_links_from_channel
from bot.distributor import distribute_links_to_sessions, estimate_needed_sessions
from bot.joiner import run_session_joiner
from bot.utils import normalize_tme_link

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

# ---------------- In-memory user states ----------------
USER_STATE: Dict[int, str] = {}
STATE_WAIT_SESSION = "wait_session"
STATE_WAIT_CHANNELS = "wait_channels"

# ---------------- Join control ----------------
JOIN_RUNNING = False
STOP_EVENT = asyncio.Event()
JOIN_LOCK = asyncio.Lock()


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة جلسة", callback_data="add_session"),
         InlineKeyboardButton("👁️ عرض الجلسات", callback_data="view_sessions")],

        [InlineKeyboardButton("🗑️ حذف جلسة", callback_data="delete_session")],

        [InlineKeyboardButton("📥 طلب قنوات الروابط", callback_data="request_channels")],

        [InlineKeyboardButton("🚀 توزيع + انضمام", callback_data="start_join")],

        [InlineKeyboardButton("📤 تصدير الروابط", callback_data="export_links")],

        [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],

        [InlineKeyboardButton("🛑 إيقاف الانضمام", callback_data="stop_join")],
    ])


bot = Client(
    "multi_session_joiner_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


def _fmt_stats_text(st: dict) -> str:
    sessions = st.get("sessions", 0)

    total_links = st.get("total_links", 0)
    dead_links = st.get("dead_links", 0)

    reserve_links = st.get("reserve_links", 0)
    reserve_target = st.get("reserve_target", 0)

    assigned = st.get("assigned", 0)
    unassigned = st.get("unassigned", 0)

    pending = st.get("pending", 0)
    requested = st.get("requested", 0)
    success = st.get("success", 0)
    failed = st.get("failed", 0)

    processed = success + failed
    success_rate = (success / processed * 100.0) if processed else 0.0

    txt = (
        "📊 **الإحصائيات**\n\n"
        f"👥 Sessions (Active): {sessions}\n\n"
        f"🔗 Links Total: {total_links}\n"
        f"☠️ Dead Links: {dead_links}\n\n"
        f"📦 Reserve Pool (Active Unassigned): {reserve_links}\n"
        f"🎯 Reserve Target: {reserve_target}\n\n"
        f"📌 Assigned: {assigned}\n"
        f"🆓 Unassigned (Any): {unassigned}\n\n"
        f"⏳ Pending joins: {pending}\n"
        f"🕒 Requested (Waiting approval): {requested}\n"
        f"✅ Success: {success}\n"
        f"❌ Failed: {failed}\n"
        f"📈 Success rate: {success_rate:.2f}%\n"
    )

    per_session = st.get("per_session", [])
    if per_session:
        txt += "\n👤 **Per Session:**\n"
        for r in per_session:
            txt += (
                f"- Session {r['session_id']}: "
                f"⏳ {r.get('pending', 0)} | "
                f"🕒 {r.get('requested', 0)} | "
                f"✅ {r.get('success', 0)} | "
                f"❌ {r.get('failed', 0)}\n"
            )

    return txt


def _safe_write_txt_file(filepath: str, lines: list[str]) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        if not lines:
            f.write("")
        else:
            f.write("\n".join(lines))


@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        await message.reply_text("❌ هذا البوت خاص.")
        return

    await message.reply_text(
        "مرحباً بك.\n\n"
        "هذا بوت إدارة جلسات Telethon لاستخراج روابط القنوات وتوزيعها (1000 لكل حساب) ثم الانضمام لها.\n\n"
        "✅ يدعم:\n"
        "- Reserve روابط للاستبدال الفوري\n"
        "- وسم الروابط الميتة Dead وعدم تكرارها\n"
        "- FloodWait Sleep وإكمال تلقائي\n"
        "- Join Request حالة requested بدل فشل\n"
        "- تصدير الروابط لكل Session + الاحتياطي\n",
        reply_markup=main_keyboard()
    )


@bot.on_callback_query()
async def callbacks(client: Client, cq: CallbackQuery):
    global JOIN_RUNNING

    if cq.from_user.id != OWNER_ID:
        await cq.answer("Not allowed", show_alert=True)
        return

    data = cq.data

    # ---------------- add_session ----------------
    if data == "add_session":
        USER_STATE[cq.from_user.id] = STATE_WAIT_SESSION
        await cq.message.edit_text(
            "➕ **إضافة جلسة Telethon**\n\n"
            "أرسل الآن StringSession (نص طويل)\n"
            "ملاحظة: سيتم قبول الرسالة إذا طولها أكبر من 100 حرف.",
            reply_markup=main_keyboard()
        )
        await cq.answer()
        return

    # ---------------- view_sessions ----------------
    if data == "view_sessions":
        sessions = db.list_sessions()
        if not sessions:
            await cq.message.edit_text("لا توجد جلسات.", reply_markup=main_keyboard())
        else:
            txt = "👥 **الجلسات:**\n\n"
            for s in sessions:
                sid, _, phone, created = s
                txt += f"- ID: `{sid}` | 📱 {phone or '-'} | 📅 {created}\n"
            await cq.message.edit_text(txt, reply_markup=main_keyboard())
        await cq.answer()
        return

    # ---------------- delete_session ----------------
    if data == "delete_session":
        sessions = db.list_sessions()
        if not sessions:
            await cq.message.edit_text("لا توجد جلسات لحذفها.", reply_markup=main_keyboard())
        else:
            kb = []
            for s in sessions:
                sid = s[0]
                kb.append([InlineKeyboardButton(f"حذف الجلسة {sid}", callback_data=f"del_{sid}")])
            kb.append([InlineKeyboardButton("رجوع", callback_data="back")])
            await cq.message.edit_text("اختر الجلسة المراد حذفها:", reply_markup=InlineKeyboardMarkup(kb))
        await cq.answer()
        return

    if data.startswith("del_"):
        sid = int(data.split("_")[-1])
        db.delete_session(sid)  # soft delete
        await cq.message.edit_text(
            f"✅ تم حذف الجلسة {sid} (Soft Delete)\n"
            "📌 الروابط المعلقة تم إرجاعها إلى Unassigned تلقائياً.",
            reply_markup=main_keyboard()
        )
        await cq.answer()
        return

    # ---------------- request_channels ----------------
    if data == "request_channels":
        USER_STATE[cq.from_user.id] = STATE_WAIT_CHANNELS
        await cq.message.edit_text(
            "📥 **إرسال قنوات الروابط**\n\n"
            "أرسل الآن روابط قنواتك الخاصة (يمكن أكثر من رابط برسالة واحدة).\n"
            "البوت سيقوم باستخراج روابط تيليجرام من الرسائل.\n\n"
            "مثال:\n"
            "https://t.me/channel1\n"
            "https://t.me/channel2",
            reply_markup=main_keyboard()
        )
        await cq.answer()
        return

    # ---------------- export_links ----------------
    if data == "export_links":
        sessions = db.list_sessions()
        if not sessions:
            await cq.answer("لا توجد Sessions.", show_alert=True)
            return

        await cq.message.edit_text(
            "📤 **تصدير الروابط**\n\n"
            "جاري تجهيز الملفات...\n"
            "- سيتم إرسال ملف لكل Session (حتى 1000 رابط)\n"
            "- وسيتم إرسال ملف Reserve (500 رابط احتياطي)\n",
            reply_markup=main_keyboard()
        )
        await cq.answer()

        # Export per session
        for sid, _, phone, _ in sessions:
            links = db.get_links_for_session_export(sid, limit=1000)

            filename = f"/tmp/session_{sid}_links.txt"
            _safe_write_txt_file(filename, links)

            caption = (
                f"📌 Session {sid}\n"
                f"📱 Phone: {phone or '-'}\n"
                f"🔗 Links: {len(links)}"
            )
            await cq.message.reply_document(filename, caption=caption)

        # Export reserve
        reserve_links = db.get_reserve_links_export(limit=500)
        reserve_file = "/tmp/reserve_links_500.txt"
        _safe_write_txt_file(reserve_file, reserve_links)

        await cq.message.reply_document(
            reserve_file,
            caption=f"📦 Reserve Links (احتياطي)\n🔗 Links: {len(reserve_links)}"
        )

        await cq.message.reply_text("✅ تم التصدير بنجاح.", reply_markup=main_keyboard())
        return

    # ---------------- start_join ----------------
    if data == "start_join":
        if JOIN_RUNNING:
            await cq.answer("عملية الانضمام تعمل بالفعل!", show_alert=True)
            return

        async with JOIN_LOCK:
            if JOIN_RUNNING:
                await cq.answer("عملية الانضمام تعمل بالفعل!", show_alert=True)
                return

            JOIN_RUNNING = True
            STOP_EVENT.clear()

            await cq.message.edit_text(
                "🚀 بدء العملية:\n"
                "1) توزيع الروابط 1000 لكل Session (مع الحفاظ على Reserve)\n"
                "2) تشغيل الانضمام لكل الحسابات بالتوازي\n\n"
                "سيتم إرسال تقارير هنا.",
                reply_markup=main_keyboard()
            )
            await cq.answer()

            asyncio.create_task(orchestrate_join(cq.message))
        return

    # ---------------- stats ----------------
    if data == "stats":
        st = db.get_stats()
        needed = estimate_needed_sessions()

        txt = _fmt_stats_text(st)
        txt += (
            "\n\n🧮 **تقدير Sessions إضافية مطلوبة**\n"
            f"- Unassigned Active: {needed.get('unassigned_active')}\n"
            f"- Reserve Target: {needed.get('reserve_target')}\n"
            f"- Distributable: {needed.get('distributable')}\n"
            f"- Needed Sessions: {needed.get('needed_sessions')}\n"
        )

        await cq.message.edit_text(txt, reply_markup=main_keyboard())
        await cq.answer()
        return

    # ---------------- stop_join ----------------
    if data == "stop_join":
        if not JOIN_RUNNING:
            await cq.answer("لا توجد عملية انضمام شغالة.", show_alert=True)
            return
        STOP_EVENT.set()
        await cq.message.edit_text("🛑 تم طلب الإيقاف... سيتم الإيقاف بأقرب فرصة.", reply_markup=main_keyboard())
        await cq.answer()
        return

    # ---------------- back ----------------
    if data == "back":
        await cq.message.edit_text("اختر:", reply_markup=main_keyboard())
        await cq.answer()
        return


@bot.on_message(filters.private & ~filters.command("start"))
async def private_text_handler(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    state = USER_STATE.get(message.from_user.id)

    # ---------------- add session flow ----------------
    if state == STATE_WAIT_SESSION:
        text = (message.text or "").strip()
        if len(text) < 100:
            await message.reply_text("❌ هذه ليست StringSession صحيحة (قصيرة جداً).")
            return

        ok = db.add_session(text)
        if ok:
            await message.reply_text("✅ تمت إضافة الجلسة بنجاح.", reply_markup=main_keyboard())
        else:
            await message.reply_text("⚠️ هذه الجلسة موجودة مسبقاً.", reply_markup=main_keyboard())

        USER_STATE.pop(message.from_user.id, None)
        return

    # ---------------- channels extraction flow ----------------
    if state == STATE_WAIT_CHANNELS:
        text = message.text or ""
        channel_links = re.findall(r"(https?://t\.me/\S+)", text)
        channel_links = [normalize_tme_link(x) for x in channel_links]

        if not channel_links:
            await message.reply_text("❌ لم أجد روابط قنوات تيليجرام في رسالتك.")
            return

        sessions = db.list_sessions()
        if not sessions:
            await message.reply_text("❌ لازم تضيف Session واحدة على الأقل لاستخراج الروابط.")
            return

        # use first session for extraction
        session_string = sessions[0][1]

        total_added = 0
        for ch in channel_links:
            await message.reply_text(f"⏳ استخراج الروابط من: {ch}")
            try:
                links = await extract_links_from_channel(session_string, ch)
                added = db.add_links(links, source_channel=ch)
                total_added += added
                await message.reply_text(f"✅ تم استخراج {len(links)} رابط / تم إضافة الجديد منها: {added}")
            except Exception as e:
                await message.reply_text(f"❌ فشل استخراج {ch}\nالسبب: {e}")

        USER_STATE.pop(message.from_user.id, None)
        await message.reply_text(
            f"🏁 انتهى الاستخراج. إجمالي الروابط الجديدة: {total_added}",
            reply_markup=main_keyboard()
        )
        return


async def orchestrate_join(message: Message):
    """
    1) distribute (respect reserve)
    2) join concurrently for all active sessions
    """
    global JOIN_RUNNING

    try:
        sessions = db.list_sessions()
        if not sessions:
            await message.reply_text("❌ لا توجد Sessions.")
            return

        # 1) distribute
        report = distribute_links_to_sessions()
        if not report.get("ok"):
            await message.reply_text(f"❌ فشل التوزيع: {report.get('error')}")
            return

        txt = (
            "📌 **تقرير التوزيع**\n"
            f"- Sessions: {report['sessions']}\n"
            f"- Unassigned Active Before: {report.get('unassigned_active_before')}\n"
            f"- Reserve Target: {report.get('reserve_target')}\n"
            f"- Distributable Before: {report.get('distributable_before')}\n"
            f"- Assigned Total: {report['assigned_total']}\n"
            f"- Unassigned Active After: {report.get('unassigned_active_after')}\n"
            f"- Reserve After: {report.get('reserve_after')}\n\n"
        )
        for row in report["per_session"]:
            txt += f"Session {row['session_id']}: assigned {row['assigned']}\n"

        await message.reply_text(txt)

        # 2) join concurrently
        await message.reply_text("🚀 بدء الانضمام بالتوازي لكل الجلسات...")

        tasks = []
        for sid, session_string, _, _ in sessions:
            tasks.append(run_session_joiner(sid, session_string, limit=1000, stop_flag=STOP_EVENT))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_txt = "🏁 **نتيجة الانضمام**\n\n"
        for res in results:
            if isinstance(res, Exception):
                final_txt += f"❌ خطأ: {res}\n"
            else:
                final_txt += (
                    f"- Session {res.get('session_id')}: "
                    f"✅ {res.get('success', 0)} | "
                    f"🕒 {res.get('requested', 0)} | "
                    f"❌ {res.get('failed', 0)}\n"
                )

        await message.reply_text(final_txt)

    finally:
        JOIN_RUNNING = False


if __name__ == "__main__":
    db.init_db()
    bot.run()
