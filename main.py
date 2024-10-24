import os
import json
import qrcode
import logging
import asyncio
import requests
import mysql.connector
from dotenv import load_dotenv
from mysql.connector import Error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, CallbackContext

load_dotenv()

config = {
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_DATABASE'),
}

def connect_to_database():
    try:
        connection = mysql.connector.connect(**config)
        if connection.is_connected():
            print("Conexão bem-sucedida ao banco de dados")
            return connection
    except Error as e:
        print(f"Erro ao conectar ao banco de dados: {e}")
        return None

connection = connect_to_database()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}

services = [
    {'id': 2007, 'name': 'Curtidas Brasileiras', 'price': 4.0},
    {'id': 2008, 'name': 'Seguidores Brasileiros', 'price': 18.0},
    {'id': 2009, 'name': 'Visualizações de Vídeos', 'price': 1.0}
]

async def start_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = {}
    await hello(update, context)

async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f'Olá, {update.effective_user.first_name}!')
    await ask_service(update, context)

async def ask_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(service['name'], callback_data=str(service['id']))] for service in services]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Qual serviço gostaria de adquirir?', reply_markup=reply_markup)

async def service_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    
    selected_service_id = int(query.data)
    service = next((s for s in services if s['id'] == selected_service_id), None)

    if service:
        user_sessions[user_id]['service'] = service
        
        response_text = f"Quantos {service['name']} você gostaria?"
        await query.message.reply_text(response_text)

async def ask_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    quantity = update.message.text

    if user_id in user_sessions and 'service' in user_sessions[user_id]:
        user_sessions[user_id]['quantity'] = quantity
        
        service = user_sessions[user_id]['service']
        
        if service['id'] == 2008: 
            await update.message.reply_text('Qual o link do perfil?')
        elif service['id'] == 2007: 
            await update.message.reply_text('Qual o link da publicação?')
        elif service['id'] == 2009: 
            await update.message.reply_text('Qual o link do Reels?')
    else:
        await update.message.reply_text('Você ainda não escolheu um serviço.')

async def ask_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = update.message.text

    if user_id in user_sessions and 'quantity' in user_sessions[user_id]:
        user_sessions[user_id]['link'] = link
        await show_order_summary(update, context)
    else:
        await update.message.reply_text('Você ainda não informou a quantidade.')

async def show_order_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session_data = user_sessions[user_id]
    
    quantity = int(session_data['quantity'])
    service = session_data['service']
    total_price = (quantity / 1000) * service['price']

    summary_message = (
        f"Informações do pedido:\n"
        f"\n"
        f"{quantity} - {service['name']}\n"
        f"\n"
        f"Valor total: R${total_price:.2f}"
    )
    
    keyboard = [
        [InlineKeyboardButton("Concluir Pedido", callback_data='confirm')],
        [InlineKeyboardButton("Cancelar", callback_data='cancel')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(summary_message, reply_markup=reply_markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()

    if query.data == 'confirm':
        await confirm_order(update, context)
    elif query.data == 'cancel':
        await query.message.reply_text('É sempre um prazer te atender!')
        del user_sessions[user_id]

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in user_sessions:
        await start_conversation(update, context)
    elif 'service' not in user_sessions[user_id]:
        await ask_service(update, context)
    elif 'quantity' not in user_sessions[user_id]:
        await ask_quantity(update, context)
    elif 'link' not in user_sessions[user_id]:
        await ask_link(update, context)

def enviar_imagem(file_path, chat_id, token):
    body = {
        'chat_id': chat_id,
    }
    with open(file_path, 'rb') as f:
        files = {
            'photo': f
        }
        r = requests.post(f'https://api.telegram.org/bot{token}/sendPhoto', data=body, files=files)
        
    if r.status_code >= 400:
        print(f'Houve um erro ao enviar mensagem. Detalhe: {r.text}')
    else:
        print('Mensagem enviada com sucesso.')

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session_data = user_sessions.get(user_id)
    
    if session_data is None:
        await update.callback_query.message.reply_text("Sessão não encontrada. Tente novamente mais tarde.")
        return

    quantity = int(session_data['quantity'])
    service = session_data['service']
    total_price = (quantity / 1000) * service['price']

    request_data = {
        "requestNumber": "12345",
        "dueDate": "2030-10-30",
        "amount": total_price,
        "callbackUrl": os.getenv('GATEWAY_WEBHOOK'),
        "client": {
            "name": os.getenv('GATEWAY_NAME'),
            "document": os.getenv('GATEWAY_CPF'),
            "email": os.getenv('GATEWAY_EMAIL')
        }
    }
    
    headers = {
        'ci': os.getenv('CLIENT_ID'),
        'cs': os.getenv('CLIENT_SECRET'),
        'Content-Type': 'application/json'
    }

    response = requests.post(os.getenv('GATEWAY_ENDPOINT'), headers=headers, json=request_data)

    if response.status_code == 200:
        response_data = response.json()
        
        save_to_database(response_data['idTransaction'], service['id'], quantity, session_data['link'], user_id, total_price)

        payment_code = response_data['paymentCode']
        qr_code_image = generate_qr_code_image(payment_code) 
        qr_code_image_path = os.path.join(os.getcwd(), "qrcode.png") 

        token = os.getenv('TELEGRAM_TOKEN')
        chat_id = update.effective_chat.id 
        enviar_imagem(qr_code_image_path, chat_id, token)

        await context.bot.send_message(chat_id=chat_id, text=f"`{payment_code}`.\n Clique para copiar.", parse_mode='Markdown')

        await asyncio.sleep(20)

        confirm_payments = "Já realizou o pagamento?"
        
        keyboard = [
            [InlineKeyboardButton("Sim, paguei!", callback_data=f'confirm_payment:{response_data["idTransaction"]}')],
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(chat_id=chat_id, text=confirm_payments, reply_markup=reply_markup)
        
    else:
        await update.callback_query.message.reply_text("Erro ao processar o pedido. Tente novamente mais tarde.")



def create_connection():
    try:
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            database=os.getenv('DB_DATABASE'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD')
        )
        if connection.is_connected():
            print("Conexão com o banco de dados estabelecida.")
            return connection
    except Error as e:
        print(f"Erro ao conectar ao MySQL: {e}")
    return None


async def check_payment_new(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = update.effective_chat.id 
    await query.answer()  

    id_transaction = query.data.split(":")[1]

    status = check_payment_status_in_db(id_transaction)

    if status == "WAITING_FOR_APPROVAL":
        await query.message.reply_text("O pagamento ainda está pendente.")
    elif status == "PAID_OUT":
        await query.message.reply_text("Pagamento confirmado!")
        
        await asyncio.sleep(3)
        keyboard = [
            [InlineKeyboardButton("OK", callback_data='cancel')]
        ]
        
        confirm_msg = "Seu pedido será iniciado em breve."
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=chat_id, text=confirm_msg, reply_markup=reply_markup)
    else:
        await query.message.reply_text("Pagamento não encontrado. Verifique os detalhes novamente.")

def check_payment_status_in_db(id_transaction):
    global connection 

    if connection is None or not connection.is_connected():
        print("Conexão com o banco de dados não está ativa. Tentando conectar...")
        connection = create_connection()  

    if connection is None or not connection.is_connected():
        return 'WAITING_FOR_APPROVAL'

    cursor = connection.cursor()
    query = "SELECT statusDeposit FROM orders WHERE idTransaction = %s"

    try:
        cursor.execute(query, (id_transaction,))
        result = cursor.fetchone()

        if result:
            return result[0]
    except Error as e:
        print(f"Erro ao consultar o status do pagamento: {e}")
    finally:
        cursor.close()

    return 'WAITING_FOR_APPROVAL'


def save_to_database(idTransaction, idService, quantity, link, chatId, totalDeposit):
    try:
        connection = mysql.connector.connect(**config)
        if connection.is_connected():
            cursor = connection.cursor()
            sql_insert_query = """INSERT INTO orders (idTransaction, idService, quantity, link, chatId, totalDeposit, statusDeposit) 
                                  VALUES (%s, %s, %s, %s, %s, %s, %s)"""
            cursor.execute(sql_insert_query, (idTransaction, idService, quantity, link, chatId, totalDeposit, 'WAITING_FOR_APPROVAL'))
            connection.commit()
            cursor.close()
    except Error as e:
        print(f"Erro ao conectar ao MySQL: {e}")
    finally:
        if connection.is_connected():
            connection.close()


def generate_qr_code_image(payment_code):
    qr = qrcode.make(payment_code)
    qr_image_path = "qrcode.jpg"  
    qr.save(qr_image_path)
    return qr_image_path

def main():
    app = ApplicationBuilder().token(os.getenv('TELEGRAM_TOKEN')).build()

    app.add_handler(CommandHandler("start", start_conversation))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(CallbackQueryHandler(service_selected, pattern='^(2007|2008|2009)$'))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern='^(confirm|cancel|confirm_payment)$'))
    app.add_handler(CallbackQueryHandler(check_payment_new, pattern='^confirm_payment:.*$'))

    app.run_polling()

if __name__ == '__main__':
    main()
