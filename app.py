
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from telegram.request import HTTPXRequest
import sqlite3
from datetime import datetime, timedelta
import os
from flask import Flask, render_template_string, request, redirect, url_for, flash, session
import threading
import time

flask_app = Flask(__name__)
flask_app.secret_key = 'your-secret-key-123456'
USERNAME = "admin"
PASSWORD = "123456"

NAME, LAST_NAME, MESSAGE_TO_ADMIN = range(3)
ADMIN_ID = 1718923270
TOKEN = os.environ.get("TELEGRAM_TOKEN")

def get_db():
    conn = sqlite3.connect('shifts.db')
    return conn

def create_tables():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        first_name TEXT,
        last_name TEXT,
        username TEXT,
        reg_date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        start_time TEXT,
        end_time TEXT,
        salary INTEGER,
        status TEXT DEFAULT 'available'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        shift_id INTEGER,
        status TEXT DEFAULT 'pending',
        reg_date TEXT,
        cancel_deadline TEXT,
        FOREIGN KEY (shift_id) REFERENCES shifts (id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        message TEXT,
        admin_reply INTEGER DEFAULT 0,
        reply_to_id INTEGER DEFAULT NULL,
        timestamp TEXT,
        is_read INTEGER DEFAULT 0
    )''')
    try:
        c.execute("ALTER TABLE reservations ADD COLUMN cancel_deadline TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

create_tables()

async def start(update: Update, context):
    user_id = str(update.effective_user.id)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT first_name, last_name FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        await main_menu(update, context)
    else:
        await update.message.reply_text("👋 خوش آمدید! لطفاً **نام** خود را وارد کنید:")
        return NAME

async def get_name(update: Update, context):
    context.user_data['first_name'] = update.message.text
    await update.message.reply_text("✅ حالا **نام خانوادگی** خود را وارد کنید:")
    return LAST_NAME

async def get_last_name(update: Update, context):
    user_id = str(update.effective_user.id)
    first_name = context.user_data['first_name']
    last_name = update.message.text
    username = update.effective_user.username or ''
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, first_name, last_name, username, reg_date) VALUES (?, ?, ?, ?, ?)",
              (user_id, first_name, last_name, username, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ ثبت نام شما با موفقیت انجام شد!\nخوش آمدید {first_name} {last_name}")
    await main_menu(update, context)
    return ConversationHandler.END

async def main_menu(update: Update, context):
    keyboard = [
        [InlineKeyboardButton("📅 رزرو شیفت", callback_data='reserve')],
        [InlineKeyboardButton("📋 وضعیت رزرو من", callback_data='my_reservations')],
        [InlineKeyboardButton("❌ لغو رزرو", callback_data='cancel_reservation')],
        [InlineKeyboardButton("📩 ارسال پیام به ادمین", callback_data='send_message_to_admin')],
        [InlineKeyboardButton("📨 پیام‌های من", callback_data='my_messages')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📋 منوی اصلی:", reply_markup=reply_markup)

async def show_shifts(update: Update, context):
    query = update.callback_query
    await query.answer()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, date, start_time, end_time, salary FROM shifts WHERE status='available' ORDER BY date, start_time")
    shifts = c.fetchall()
    conn.close()
    if not shifts:
        await query.message.reply_text("📭 هیچ شیفت موجودی در حال حاضر وجود ندارد.")
        return
    keyboard = []
    for s in shifts:
        shift_id, date, start, end, salary = s
        btn_text = f"📅 {date} | {start}-{end} | حقوق: {salary} تومان"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"select_shift_{shift_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("🔽 لطفاً شیفت مورد نظر را انتخاب کنید:", reply_markup=reply_markup)

async def select_shift(update: Update, context):
    query = update.callback_query
    await query.answer()
    shift_id = int(query.data.replace('select_shift_', ''))
    user_id = str(update.effective_user.id)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM reservations WHERE user_id=? AND shift_id=? AND status != 'cancelled'", (user_id, shift_id))
    if c.fetchone():
        await query.message.reply_text("⚠️ شما قبلاً برای این شیفت رزرو کرده‌اید!")
        conn.close()
        return
    c.execute("INSERT INTO reservations (user_id, shift_id, status, reg_date) VALUES (?, ?, ?, ?)",
              (user_id, shift_id, 'pending', datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()
    await query.message.reply_text("✅ رزرو شما با موفقیت ثبت شد. منتظر تأیید ادمین باشید.")

async def my_reservations(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT r.id, s.date, s.start_time, s.end_time, s.salary, r.status, r.cancel_deadline
        FROM reservations r JOIN shifts s ON r.shift_id = s.id
        WHERE r.user_id=? AND r.status != 'cancelled'
        ORDER BY s.date, s.start_time
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.message.reply_text("📭 شما هیچ رزرو فعالی ندارید.")
        return
    text = "📋 **رزروهای شما:**\n\n"
    for r in rows:
        deadline_str = r[6] if r[6] else "بدون محدودیت"
        text += f"#{r[0]} | {r[1]} {r[2]}-{r[3]} | حقوق {r[4]} | وضعیت: {r[5]} | فرصت لغو تا: {deadline_str}\n"
    await query.message.reply_text(text)

async def cancel_reservation(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT r.id, s.date, s.start_time, s.end_time, r.cancel_deadline
        FROM reservations r JOIN shifts s ON r.shift_id = s.id
        WHERE r.user_id=? AND r.status = 'confirmed'
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.message.reply_text("📭 شما هیچ رزرو تأیید شده‌ای برای لغو ندارید.")
        return
    keyboard = []
    for r in rows:
        res_id, date, start, end, deadline = r
        can_cancel = False
        if deadline:
            try:
                deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M:%S")
                if datetime.now() <= deadline_dt:
                    can_cancel = True
            except:
                pass
        if can_cancel:
            btn_text = f"لغو #{r[0]} - {r[1]} {r[2]}-{r[3]}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"cancel_res_{r[0]}")])
        else:
            btn_text = f"⛔ #{r[0]} - {r[1]} {r[2]}-{r[3]} (فرصت لغو گذشته)"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data="noop")])
    if not keyboard:
        await query.message.reply_text("⛔ هیچ رزرو قابل لغویی وجود ندارد. فرصت لغو همه به پایان رسیده است.")
        return
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("❌ لطفاً رزروی که می‌خواهید لغو کنید را انتخاب کنید:", reply_markup=reply_markup)

async def confirm_cancel(update: Update, context):
    query = update.callback_query
    await query.answer()
    if query.data == "noop":
        await query.message.reply_text("⛔ این رزرو قابل لغو نیست.")
        return
    res_id = int(query.data.replace('cancel_res_', ''))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT cancel_deadline, status FROM reservations WHERE id=?", (res_id,))
    row = c.fetchone()
    if not row:
        await query.message.reply_text("❌ رزرو پیدا نشد.")
        conn.close()
        return
    deadline_str, status = row
    if status != 'confirmed':
        await query.message.reply_text("❌ این رزرو قابل لغو نیست.")
        conn.close()
        return
    can_cancel = False
    if deadline_str:
        try:
            deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() <= deadline_dt:
                can_cancel = True
        except:
            pass
    if not can_cancel:
        await query.message.reply_text("⛔ امکان لغو شیفت نیست. فرصت لغو شما به پایان رسیده است.")
        conn.close()
        return
    c.execute("UPDATE reservations SET status='cancelled' WHERE id=?", (res_id,))
    conn.commit()
    conn.close()
    await query.message.reply_text("✅ رزرو شما با موفقیت لغو شد.")

async def send_message_to_admin(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("✍️ لطفاً پیام خود را برای ادمین بنویسید:")
    return MESSAGE_TO_ADMIN

async def receive_message_from_user(update: Update, context):
    user_id = str(update.effective_user.id)
    message_text = update.message.text
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO messages (user_id, message, admin_reply, timestamp) VALUES (?, ?, ?, ?)",
              (user_id, message_text, 0, timestamp))
    conn.commit()
    conn.close()
    try:
        user_full_name = update.effective_user.first_name or ""
        if update.effective_user.last_name:
            user_full_name += " " + update.effective_user.last_name
        admin_msg = f"📩 پیام جدید از {user_full_name} (آیدی: {user_id}):\n\n{message_text}"
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg)
    except Exception as e:
        print(f"خطا در ارسال به ادمین: {e}")
    await update.message.reply_text("✅ پیام شما با موفقیت به ادمین ارسال شد. در اسرع وقت پاسخ داده می‌شود.")
    return ConversationHandler.END

async def my_messages(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = str(update.effective_user.id)
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT message, timestamp
        FROM messages
        WHERE user_id=? AND admin_reply=1
        ORDER BY timestamp DESC
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.message.reply_text("📭 شما هیچ پیامی از ادمین ندارید.")
        return
    text = "📨 **پاسخ‌های ادمین:**\n\n"
    for msg, ts in rows:
        text += f"📩 {msg}\n⏱️ {ts}\n\n"
    await query.message.reply_text(text)

async def admin_panel(update: Update, context):
    if str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("🚫 دسترسی ندارید!")
        return
    keyboard = [
        [InlineKeyboardButton("➕ تعریف شیفت جدید", callback_data='admin_add_shift')],
        [InlineKeyboardButton("📋 لیست شیفت‌ها", callback_data='admin_list_shifts')],
        [InlineKeyboardButton("📊 لیست رزروها", callback_data='admin_list_reservations')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👑 **پنل مدیریت**", reply_markup=reply_markup)

async def admin_add_shift(update: Update, context):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("📝 لطفاً اطلاعات شیفت را به صورت زیر وارد کنید:\n"
                                   "`تاریخ (YYYY-MM-DD), ساعت شروع, ساعت پایان, حقوق`\n"
                                   "مثال: 2026-06-20, 08:00, 12:00, 500000")
    context.user_data['admin_action'] = 'add_shift'

async def admin_input_shift(update: Update, context):
    if context.user_data.get('admin_action') == 'add_shift':
        try:
            parts = update.message.text.split(',')
            date = parts[0].strip()
            start = parts[1].strip()
            end = parts[2].strip()
            salary = int(parts[3].strip())
            conn = get_db()
            c = conn.cursor()
            c.execute("INSERT INTO shifts (date, start_time, end_time, salary) VALUES (?, ?, ?, ?)",
                      (date, start, end, salary))
            conn.commit()
            conn.close()
            await update.message.reply_text("✅ شیفت جدید با موفقیت اضافه شد.")
        except Exception as e:
            await update.message.reply_text(f"❌ خطا در ثبت شیفت: {str(e)}")
        context.user_data['admin_action'] = None
        return
    await update.message.reply_text("دستور نامعتبر.")

async def admin_list_shifts(update: Update, context):
    query = update.callback_query
    await query.answer()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, date, start_time, end_time, salary, status FROM shifts ORDER BY date, start_time")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.message.reply_text("📭 هیچ شیفتی تعریف نشده است.")
        return
    text = "📋 **لیست شیفت‌ها:**\n\n"
    for r in rows:
        text += f"#{r[0]} | {r[1]} {r[2]}-{r[3]} | {r[4]} تومان | وضعیت: {r[5]}\n"
    await query.message.reply_text(text)

async def admin_list_reservations(update: Update, context):
    query = update.callback_query
    await query.answer()
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT r.id, u.first_name, u.last_name, s.date, s.start_time, s.end_time, s.salary, r.status, r.cancel_deadline
        FROM reservations r
        JOIN users u ON r.user_id = u.user_id
        JOIN shifts s ON r.shift_id = s.id
        WHERE r.status != 'cancelled'
        ORDER BY s.date, s.start_time
    ''')
    rows = c.fetchall()
    conn.close()
    if not rows:
        await query.message.reply_text("📭 هیچ رزرو فعالی ثبت نشده است.")
        return
    text = "📊 **لیست رزروها:**\n\n"
    for r in rows:
        deadline = r[8] if r[8] else "بدون محدودیت"
        text += f"#{r[0]} | {r[1]} {r[2]} | {r[3]} {r[4]}-{r[5]} | {r[6]} تومان | وضعیت: {r[7]} | فرصت لغو: {deadline}\n"
    await query.message.reply_text(text)

def run_bot():
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=30.0)
    app = Application.builder().token(TOKEN).request(request).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_last_name)],
        },
        fallbacks=[],
    )
    app.add_handler(conv_handler)

    msg_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(send_message_to_admin, pattern='send_message_to_admin')],
        states={
            MESSAGE_TO_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message_from_user)],
        },
        fallbacks=[],
    )
    app.add_handler(msg_handler)

    app.add_handler(CallbackQueryHandler(show_shifts, pattern='reserve'))
    app.add_handler(CallbackQueryHandler(my_reservations, pattern='my_reservations'))
    app.add_handler(CallbackQueryHandler(cancel_reservation, pattern='cancel_reservation'))
    app.add_handler(CallbackQueryHandler(select_shift, pattern='select_shift_'))
    app.add_handler(CallbackQueryHandler(confirm_cancel, pattern='cancel_res_'))
    app.add_handler(CallbackQueryHandler(my_messages, pattern='my_messages'))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(admin_add_shift, pattern='admin_add_shift'))
    app.add_handler(CallbackQueryHandler(admin_list_shifts, pattern='admin_list_shifts'))
    app.add_handler(CallbackQueryHandler(admin_list_reservations, pattern='admin_list_reservations'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_input_shift))

    print("🤖 ربات با قابلیت پیام به ادمین راه‌اندازی شد!")
    app.run_polling(bootstrap_retries=-1)

@flask_app.route('/')
def panel():
    return "پنل مدیریت ربات شیفت - در Render فعال است!"

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host='0.0.0.0', port=port, debug=False)
