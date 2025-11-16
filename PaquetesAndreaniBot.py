"""
Bot de Telegram para contar paquetes por día y sumar pagos mensuales.
Diseñado para ejecutarse en Termux y guardarse en GitHub.

Comandos:
/iniciar - inicia la jornada (activa conteo para el día actual)
/finalizar - finaliza la jornada, muestra total de paquetes y pago del día
/mes - muestra el total acumulado del mes actual (paquetes y pago)
/tarifa <valor> - establece la tarifa por paquete (en la moneda que quieras)
/info - muestra ayuda con los comandos

Mecánica:
- Mientras la jornada está activa, enviar un mensaje que contenga solo "1" añade 1 paquete al conteo del día.
- El bot crea una pequeña base de datos sqlite para persistencia.
- También muestra un teclado dinámico (ReplyKeyboard) con botones útiles.

Dependencias:
python-telegram-bot

Instalación en Termux (ejemplo):
pkg install python git
pip install python-telegram-bot==13.15
export BOT_TOKEN="<tu_token_aqui>"
python bot_paquetes_telegram.py

Guarda este archivo en un repo y clona en Termux: git clone ...

"""

import os
import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Config
DB_FILENAME = 'paquetes.db'
DEFAULT_TARIFA = 0.0  # valor por paquete si no se establece

# --------------------- Helpers DB ---------------------

def init_db():
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            packages INTEGER DEFAULT 0,
            finished INTEGER DEFAULT 0,
            tarifa REAL DEFAULT ?
        )
    ''', (DEFAULT_TARIFA,))
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            tarifa REAL DEFAULT ?
        )
    ''', (DEFAULT_TARIFA,))
    conn.commit()
    conn.close()


def get_conn():
    return sqlite3.connect(DB_FILENAME)


def ensure_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE user_id=?', (user_id,))
    if not c.fetchone():
        c.execute('INSERT INTO users (user_id, tarifa) VALUES (?, ?)', (user_id, DEFAULT_TARIFA))
        conn.commit()
    conn.close()


def set_tarifa_db(user_id: int, tarifa: float):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO users (user_id, tarifa) VALUES (?, ?)', (user_id, tarifa))
    conn.commit()
    conn.close()


def get_tarifa(user_id: int) -> float:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT tarifa FROM users WHERE user_id=?', (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else DEFAULT_TARIFA


def start_day(user_id: int, date_str: str):
    conn = get_conn()
    c = conn.cursor()
    # check if there's an unfinished day for today
    c.execute('SELECT id FROM days WHERE user_id=? AND date=?', (user_id, date_str))
    if c.fetchone():
        conn.close()
        return False
    tarifa = get_tarifa(user_id)
    c.execute('INSERT INTO days (user_id, date, packages, finished, tarifa) VALUES (?, ?, 0, 0, ?)', (user_id, date_str, tarifa))
    conn.commit()
    conn.close()
    return True


def add_package(user_id: int, date_str: str, amount: int = 1):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, finished FROM days WHERE user_id=? AND date=?', (user_id, date_str))
    r = c.fetchone()
    if not r:
        conn.close()
        return None  # no session
    if r[1]:
        conn.close()
        return False  # already finished
    c.execute('UPDATE days SET packages = packages + ? WHERE id=?', (amount, r[0]))
    conn.commit()
    c.execute('SELECT packages FROM days WHERE id=?', (r[0],))
    new_count = c.fetchone()[0]
    conn.close()
    return new_count


def finish_day(user_id: int, date_str: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id, packages, tarifa, finished FROM days WHERE user_id=? AND date=?', (user_id, date_str))
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


def get_month_summary(user_id: int, year: int, month: int):
    conn = get_conn()
    c = conn.cursor()
    like = f"{year:04d}-{month:02d}-%"
    c.execute('SELECT date, packages, tarifa FROM days WHERE user_id=? AND date LIKE ?', (user_id, like))
    rows = c.fetchall()
    conn.close()
    total_packages = sum(r[1] for r in rows)
    total_pago = sum(r[1] * r[2] for r in rows)
    details = rows
    return {'total_packages': total_packages, 'total_pago': total_pago, 'details': details}

# --------------------- Bot handlers ---------------------


def make_keyboard(active: bool = False):
    # Dynamic keyboard: if active (in a working day) show "1" and "Finalizar"
    if active:
        keys = [[KeyboardButton('1')], [KeyboardButton('/finalizar'), KeyboardButton('/mes')], [KeyboardButton('/info')]]
    else:
        keys = [[KeyboardButton('/iniciar')], [KeyboardButton('/mes'), KeyboardButton('/info')]]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)


def cmd_start(update: Update, context: CallbackContext):
    update.message.reply_text('Hola! Soy el bot de conteo de paquetes. Usa /info para ver comandos.')


def cmd_info(update: Update, context: CallbackContext):
    text = (
        "Comandos disponibles:\n"
        "/iniciar - iniciar jornada del día (habilita contar paquetes)\n"
        "/finalizar - finalizar jornada y mostrar total del día\n"
        "/mes - mostrar total acumulado del mes actual\n"
        "/tarifa <valor> - establecer tarifa por paquete\n"
        "/info - mostrar esta ayuda\n\n"
        "Mientras la jornada esté activa, envía solo '1' para añadir un paquete."
    )
    update.message.reply_text(text)


def cmd_iniciar(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    ensure_user(user_id)
    today = datetime.now().strftime('%Y-%m-%d')
    ok = start_day(user_id, today)
    if ok:
        update.message.reply_text(f'Jornada iniciada para {today}. Envía "1" para contar paquetes.', reply_markup=make_keyboard(active=True))
    else:
        update.message.reply_text('Ya hay una jornada iniciada para hoy (o ya fue registrada).', reply_markup=make_keyboard(active=True))


def cmd_finalizar(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    today = datetime.now().strftime('%Y-%m-%d')
    res = finish_day(user_id, today)
    if res is None:
        update.message.reply_text('No hay jornada iniciada para hoy. Usa /iniciar para comenzar.', reply_markup=make_keyboard(active=False))
    elif res is False:
        update.message.reply_text('La jornada ya fue finalizada.', reply_markup=make_keyboard(active=False))
    else:
        p = res['packages']
        pago = res['pago']
        tarifa = res['tarifa']
        update.message.reply_text(f'Jornada finalizada. Paquetes: {p}\nTarifa por paquete: {tarifa}\nPago total: {pago}', reply_markup=make_keyboard(active=False))


def cmd_mes(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    now = datetime.now()
    summary = get_month_summary(user_id, now.year, now.month)
    text = f"Resumen mes {now.year}-{now.month:02d}:\nPaquetes totales: {summary['total_packages']}\nPago total: {summary['total_pago']}\n"
    # add brief details
    if summary['details']:
        text += '\nDetalles por día:\n'
        for d, packages, tarifa in summary['details']:
            pago = packages * tarifa
            text += f"{d}: {packages} paquetes -> {pago}\n"
    update.message.reply_text(text, reply_markup=make_keyboard(active=False))


def cmd_tarifa(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    ensure_user(user_id)
    args = context.args
    if not args:
        tarifa = get_tarifa(user_id)
        update.message.reply_text(f'Tarifa actual: {tarifa}')
        return
    try:
        tarifa = float(args[0])
    except ValueError:
        update.message.reply_text('Por favor indica un número. Ejemplo: /tarifa 150')
        return
    set_tarifa_db(user_id, tarifa)
    update.message.reply_text(f'Tarifa establecida en {tarifa}')


def handle_one_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    # accept only exact "1"
    if text != '1':
        return
    today = datetime.now().strftime('%Y-%m-%d')
    res = add_package(user_id, today, 1)
    if res is None:
        update.message.reply_text('No hay jornada iniciada. Usa /iniciar para comenzar.', reply_markup=make_keyboard(active=False))
    elif res is False:
        update.message.reply_text('La jornada ya fue finalizada, no se puede añadir.', reply_markup=make_keyboard(active=False))
    else:
        update.message.reply_text(f'Paquetes registrados hoy: {res}', reply_markup=make_keyboard(active=True))

# --------------------- Main ---------------------

def main():
    init_db()
    token = os.environ.get('BOT_TOKEN')
    if not token:
        print('Por favor exporta la variable BOT_TOKEN con el token del bot (export BOT_TOKEN="..." )')
        return
    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', cmd_start))
    dp.add_handler(CommandHandler('info', cmd_info))
    dp.add_handler(CommandHandler('iniciar', cmd_iniciar))
    dp.add_handler(CommandHandler('finalizar', cmd_finalizar))
    dp.add_handler(CommandHandler('mes', cmd_mes))
    dp.add_handler(CommandHandler('tarifa', cmd_tarifa))

    # message handler for exact '1'
    dp.add_handler(MessageHandler(Filters.text & (~Filters.command), handle_one_message))

    print('Bot iniciado...')
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
    
