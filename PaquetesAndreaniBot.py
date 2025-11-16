"""
Bot de Telegram — Conteo de paquetes (versión corregida)
- Compatible con python-telegram-bot==13.15
- Acepta '1' y 'paquete' para registrar paquetes
- Soporta hasta 2 dueños/autorizados (owner1 y owner2)
- Pide TOKEN al iniciar si no hay BOT_TOKEN en ambiente
- Comandos principales: /start, /info, /iniciar, /finalizar, /mes, /tarifa, /apagarbot

Instrucciones: copia este archivo (reemplaza tu PaquetesAndreaniBot.py) y ejecútalo en tu venv.
"""

import os
import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

DB_FILENAME = 'paquetes.db'
DEFAULT_TARIFA = 0.0

# ---------------- DATABASE ----------------

def init_db():
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()

    # Tabla days
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            packages INTEGER DEFAULT 0,
            finished INTEGER DEFAULT 0,
            tarifa REAL DEFAULT {DEFAULT_TARIFA}
        )
    ''')

    # Tabla users
    c.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            tarifa REAL DEFAULT {DEFAULT_TARIFA}
        )
    ''')

    # Tabla config (guardaremos owner1 y owner2 aquí)
    c.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    conn.commit()
    conn.close()


def get_conn():
    return sqlite3.connect(DB_FILENAME)

# ---------------- Owners (hasta 2) ----------------

def get_owner_ids():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key='owner1'")
    r1 = c.fetchone()
    c.execute("SELECT value FROM config WHERE key='owner2'")
    r2 = c.fetchone()
    conn.close()
    ids = []
    if r1 and r1[0]:
        try:
            ids.append(int(r1[0]))
        except:
            pass
    if r2 and r2[0]:
        try:
            ids.append(int(r2[0]))
        except:
            pass
    return ids


def add_owner_id(uid):
    ids = get_owner_ids()
    if uid in ids:
        return True
    conn = get_conn()
    c = conn.cursor()
    if len(ids) == 0:
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('owner1', ?)", (str(uid),))
    elif len(ids) == 1:
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('owner2', ?)", (str(uid),))
    else:
        conn.close()
        return False
    conn.commit()
    conn.close()
    return True


def is_owner(uid):
    return uid in get_owner_ids()

# ---------------- Users & tarifa ----------------

def ensure_user(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE user_id=?', (uid,))
    if not c.fetchone():
        c.execute('INSERT INTO users (user_id, tarifa) VALUES (?, ?)', (uid, DEFAULT_TARIFA))
        conn.commit()
    conn.close()


def get_tarifa(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT tarifa FROM users WHERE user_id=?', (uid,))
    r = c.fetchone()
    conn.close()
    return float(r[0]) if r else float(DEFAULT_TARIFA)


def set_tarifa(uid, v):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (user_id, tarifa) VALUES (?, ?)', (uid, v))
    conn.commit()
    conn.close()

# ---------------- Days logic ----------------

def start_day(uid, date):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id FROM days WHERE user_id=? AND date=?', (uid, date))
    if c.fetchone():
        conn.close()
        return False
    tarifa = get_tarifa(uid)
    c.execute('INSERT INTO days (user_id, date, packages, finished, tarifa) VALUES (?, ?, 0, 0, ?)', (uid, date, tarifa))
    conn.commit()
    conn.close()
    return True


def add_package(uid, date, amount=1):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, finished FROM days WHERE user_id=? AND date=?', (uid, date))
    r = c.fetchone()
    if not r:
        conn.close()
        return None
    if r[1]:
        conn.close()
        return False
    c.execute('UPDATE days SET packages = packages + ? WHERE id=?', (amount, r[0]))
    conn.commit()
    c.execute('SELECT packages FROM days WHERE id=?', (r[0],))
    count = c.fetchone()[0]
    conn.close()
    return count


def finish_day(uid, date):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, packages, tarifa, finished FROM days WHERE user_id=? AND date=?', (uid, date))
    r = c.fetchone()
    if not r:
        conn.close()
        return None
    if r[3]:
        conn.close()
        return False
    packages = r[1]
    tarifa = r[2]
    pago = packages * tarifa
    c.execute('UPDATE days SET finished=1 WHERE id=?', (r[0],))
    conn.commit()
    conn.close()
    return {'packages': packages, 'tarifa': tarifa, 'pago': pago}


def get_month_summary(uid, year, month):
    conn = get_conn()
    c = conn.cursor()
    like = f"{year:04d}-{month:02d}-%"
    c.execute('SELECT date, packages, tarifa FROM days WHERE user_id=? AND date LIKE ?', (uid, like))
    rows = c.fetchall()
    conn.close()
    total_p = sum(r[1] for r in rows)
    total_pago = sum(r[1] * r[2] for r in rows)
    return {'total_packages': total_p, 'total_pago': total_pago, 'details': rows}

# ---------------- Keyboards ----------------

def make_keyboard(active=False):
    if active:
        keys = [[KeyboardButton('1'), KeyboardButton('paquete')],
                [KeyboardButton('/finalizar')],
                [KeyboardButton('/mes')],
                [KeyboardButton('/info')]]
    else:
        keys = [[KeyboardButton('/iniciar')],
                [KeyboardButton('/mes')],
                [KeyboardButton('/info')]]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)


def make_inline_keyboard(active=False):
    if active:
        buttons = [
            [InlineKeyboardButton('➕ Añadir paquete', callback_data='add_package')],
            [InlineKeyboardButton('⏹ Finalizar jornada', callback_data='finalizar')],
            [InlineKeyboardButton('📅 Resumen mes', callback_data='mes')]
        ]
    else:
        buttons = [
            [InlineKeyboardButton('🚀 Iniciar jornada', callback_data='iniciar')],
            [InlineKeyboardButton('📅 Resumen mes', callback_data='mes')]
        ]
    return InlineKeyboardMarkup(buttons)

# ---------------- Handlers ----------------

def cmd_start(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    # registrar dueño(s) si hay espacio
    added = add_owner_id(uid)
    if added:
        owners = get_owner_ids()
        if len(owners) == 1:
            update.message.reply_text('Hola Cristian! Te registré como owner principal del bot.')
        elif len(owners) == 2:
            update.message.reply_text('Hola! Se añadieron dos owners. Acceso compartido activado.')
    else:
        update.message.reply_text('Hola Cristian!')


def cmd_info(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Comandos:
/start
/iniciar
/finalizar
/mes
/tarifa <valor>
/apagarbot
/info
Mientras la jornada esté activa, enviar '1' o 'paquete' para sumar."
    )


def cmd_iniciar(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    if not is_owner(uid):
        update.message.reply_text('No estás autorizado para iniciar la jornada.')
        return
    ensure_user(uid)
    hoy = datetime.now().strftime('%Y-%m-%d')
    ok = start_day(uid, hoy)
    if ok:
        update.message.reply_text(f'Cristian, jornada iniciada para {hoy}.', reply_markup=make_keyboard(True))
    else:
        update.message.reply_text('Ya hay una jornada iniciada para hoy.', reply_markup=make_keyboard(True))


def cmd_finalizar(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    if not is_owner(uid):
        update.message.reply_text('No estás autorizado para finalizar la jornada.')
        return
    hoy = datetime.now().strftime('%Y-%m-%d')
    res = finish_day(uid, hoy)
    if res is None:
        update.message.reply_text('No hay jornada iniciada para hoy.', reply_markup=make_keyboard(False))
    elif res is False:
        update.message.reply_text('La jornada ya fue finalizada.', reply_markup=make_keyboard(False))
    else:
        p = res['packages']
        pago = res['pago']
        tarifa = res['tarifa']
        update.message.reply_text(f'Cristian, jornada finalizada. Paquetes: {p}
Tarifa por paquete: {tarifa} ARS
Pago total: {pago} ARS', reply_markup=make_keyboard(False))


def cmd_mes(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    if not is_owner(uid):
        update.message.reply_text('No estás autorizado para ver el resumen del mes.')
        return
    now = datetime.now()
    res = get_month_summary(uid, now.year, now.month)
    text = f"Resumen mes {now.year}-{now.month:02d}:
Paquetes totales: {res['total_packages']}
Pago total: {res['total_pago']} ARS
"
    if res['details']:
        text += '
Detalles por día:
'
        for d, packages, tarifa in res['details']:
            pago = packages * tarifa
            text += f"{d}: {packages} paquetes -> {pago} ARS
"
    update.message.reply_text(text, reply_markup=make_keyboard(False))


def cmd_tarifa(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    if not is_owner(uid):
        update.message.reply_text('No estás autorizado para cambiar la tarifa.')
        return
    ensure_user(uid)
    if not context.args:
        update.message.reply_text(f'Tarifa actual: {get_tarifa(uid)} ARS')
        return
    try:
        v = float(context.args[0])
    except:
        update.message.reply_text('Por favor indica un número. Ejemplo: /tarifa 150')
        return
    set_tarifa(uid, v)
    update.message.reply_text(f'Tarifa establecida en {v} ARS')

# ---------------- Shutdown ----------------

def cmd_apagarbot(update: Update, context: CallbackContext):
    uid = update.message.from_user.id
    if not is_owner(uid):
        update.message.reply_text('No estás autorizado para apagar el bot.')
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('⚠️ Confirmar apagar bot ⚠️', callback_data='confirm_shutdown')],
        [InlineKeyboardButton('❌ Cancelar', callback_data='cancel_shutdown')]
    ])
    update.message.reply_text('⚠️ APAGAR BOT ⚠️
Si confirmas, el bot se detendrá. ¿Estás seguro?', reply_markup=keyboard)

# ---------------- Callbacks (inline) ----------------

def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    query.answer()

    # Acciones que requieren autorización
    protected = ('add_package', 'finalizar', 'iniciar', 'mes', 'confirm_shutdown', 'shutdown')
    if data in protected and not is_owner(user_id):
        query.edit_message_text('No estás autorizado para esta acción.')
        return

    today = datetime.now().strftime('%Y-%m-%d')

    if data == 'add_package':
        res = add_package(user_id, today, 1)
        if res is None:
            query.edit_message_text('No hay jornada iniciada. Usa /iniciar para comenzar.')
        elif res is False:
            query.edit_message_text('La jornada ya fue finalizada, no se puede añadir.')
        else:
            query.edit_message_text(f'Paquetes registrados hoy: {res}')
    elif data == 'finalizar':
        res = finish_day(user_id, today)
        if res is None:
            query.edit_message_text('No hay jornada iniciada para hoy.')
        elif res is False:
            query.edit_message_text('La jornada ya fue finalizada.')
        else:
            p = res['packages']
            pago = res['pago']
            tarifa = res['tarifa']
            query.edit_message_text(f'Cristian, jornada finalizada. Paquetes: {p}
Tarifa por paquete: {tarifa} ARS
Pago total: {pago} ARS')
    elif data == 'iniciar':
        ok = start_day(user_id, today)
        if ok:
            query.edit_message_text(f'Cristian, jornada iniciada para {today}.')
        else:
            query.edit_message_text('Ya hay una jornada iniciada para hoy (o ya fue registrada).')
    elif data == 'mes':
        now = datetime.now()
        res = get_month_summary(user_id, now.year, now.month)
        text = f"Resumen mes {now.year}-{now.month:02d}:
Paquetes totales: {res['total_packages']}
Pago total: {res['total_pago']} ARS
"
        if res['details']:
            text += '
Detalles por día:
'
            for d, packages, tarifa in res['details']:
                pago = packages * tarifa
                text += f"{d}: {packages} paquetes -> {pago} ARS
"
        query.edit_message_text(text)
    elif data == 'confirm_shutdown':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton('⚠️ Apagar ahora (IRREVERSIBLE) ⚠️', callback_data='shutdown')],
            [InlineKeyboardButton('❌ Cancelar', callback_data='cancel_shutdown')]
        ])
        query.edit_message_text('CONFIRMACIÓN FINAL: ¿Deseas apagar el bot ahora?', reply_markup=keyboard)
    elif data == 'cancel_shutdown':
        query.edit_message_text('Apagado cancelado.')
    elif data == 'shutdown':
        query.edit_message_text('Apagando bot...')
        try:
            updater_ref = context.bot_data.get('updater_ref')
            if updater_ref:
                updater_ref.stop()
        except Exception:
            pass

# ---------------- Message handler ----------------

def handle_text(update: Update, context: CallbackContext):
    text = update.message.text.strip()
    uid = update.message.from_user.id
    today = datetime.now().strftime('%Y-%m-%d')

    # aceptar '1' o 'paquete' (case-insensitive)
    if text.lower() not in ('1', 'paquete'):
        return

    if not is_owner(uid):
        update.message.reply_text('No estás autorizado para añadir paquetes.')
        return

    res = add_package(uid, today, 1)
    if res is None:
        update.message.reply_text('No hay jornada iniciada. Usa /iniciar para comenzar.', reply_markup=make_keyboard(False))
    elif res is False:
        update.message.reply_text('La jornada ya fue finalizada, no se puede añadir.', reply_markup=make_keyboard(False))
    else:
        update.message.reply_text(f'Paquetes registrados hoy: {res}', reply_markup=make_keyboard(True))

# ---------------- Main ----------------

def main():
    init_db()

    token = os.environ.get('BOT_TOKEN')
    if not token:
        try:
            token = input('Ingrese el TOKEN del bot de Telegram: ').strip()
        except Exception:
            token = None
    if not token:
        print('No se proporcionó token. Exporta BOT_TOKEN o ingresalo al ejecutar.')
        return

    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    # handlers
    dp.add_handler(CommandHandler('start', cmd_start))
    dp.add_handler(CommandHandler('info', cmd_info))
    dp.add_handler(CommandHandler('iniciar', cmd_iniciar))
    dp.add_handler(CommandHandler('finalizar', cmd_finalizar))
    dp.add_handler(CommandHandler('mes', cmd_mes))
    dp.add_handler(CommandHandler('tarifa', cmd_tarifa))
    dp.add_handler(CommandHandler('apagarbot', cmd_apagarbot))

    dp.add_handler(CallbackQueryHandler(handle_callback))
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_text))

    # store updater ref so callbacks can stop the bot
    updater.bot_data['updater_ref'] = updater

    print('Bot iniciado...')
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
        
