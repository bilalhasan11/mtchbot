import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

import database as db

TOKEN = "8568453320:AAEJdxuRaE6lqiq4b-Yx4q0XlZT0jqsT6ik"
if not TOKEN:
    raise ValueError("BOT_TOKEN not set in HF Secrets")

# States
AGE, GENDER, LOOKING_FOR, CITY, NAME, BIO, PHOTOS = range(7)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Hi! I'm a simple match bot.\n\n"
        "Be safe online. No personal data is shared.\n\n"
        "What's your age? (18–99)"
    )
    return AGE

async def age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        age = int(update.message.text)
        if 18 <= age <= 99:
            context.user_data['age'] = age
            keyboard = [['I\'m male', 'I\'m female', 'Other']]
            await update.message.reply_text("Your gender:", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
            return GENDER
        else:
            await update.message.reply_text("Age must be 18–99.")
            return AGE
    except:
        await update.message.reply_text("Enter a number.")
        return AGE

async def gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    gender = text.split("'")[1] if "'" in text else text
    context.user_data['gender'] = gender
    keyboard = [['Women', 'Men', 'Everyone']]
    await update.message.reply_text("Who are you looking for?", reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True))
    return LOOKING_FOR

async def looking_for(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['looking_for'] = update.message.text
    await update.message.reply_text("Your city? (e.g., Lahore)")
    return CITY

async def city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['city'] = update.message.text
    await update.message.reply_text("Your name?")
    return NAME

async def name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Tell about yourself (bio):")
    return BIO

async def bio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['bio'] = update.message.text
    await update.message.reply_text("Send 1–3 photos (or /done to skip)")
    return PHOTOS

async def photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if update.message.photo:
        photo_file = update.message.photo[-1]
        path = db.download_photo(context.bot, photo_file, user_id)
        if 'photos' not in context.user_data:
            context.user_data['photos'] = []
        context.user_data['photos'].append(path)
        count = len(context.user_data['photos'])
        if count < 3:
            await update.message.reply_text(f"Photo {count}/3 added. Send more or /done")
            return PHOTOS
    # Save
    db.save_profile(
        user_id,
        context.user_data['name'],
        context.user_data['age'],
        context.user_data['gender'],
        context.user_data['looking_for'],
        context.user_data['city'],
        context.user_data['bio'],
        context.user_data.get('photos', [])
    )
    await update.message.reply_text(
        f"Profile saved!\n\n"
        f"{context.user_data['name']}, {context.user_data['age']}, {context.user_data['city']}\n"
        f"{context.user_data['bio']}\n\n"
        f"Use /swipe to find matches!"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def done_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await photos(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

# Swipe
async def swipe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = db.get_profile(user_id)
    if not profile:
        await update.message.reply_text("Use /start first.")
        return
    candidates = db.get_candidates(user_id)
    if not candidates:
        await update.message.reply_text("No one nearby. Try later!")
        return
    context.user_data['candidates'] = candidates
    context.user_data['index'] = 0
    await show_profile(update, context)

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idx = context.user_data['index']
    if idx >= len(context.user_data['candidates']):
        await update.message.reply_text("No more profiles. Use /swipe again.")
        return
    cand_id = context.user_data['candidates'][idx]
    cand = db.get_profile(cand_id)
    caption = f"{cand['name']}, {cand['age']}\n{cand['city']}\n{cand['bio'][:200]}"
    keyboard = [
        [InlineKeyboardButton("Like", callback_data=f"like_{cand_id}"),
         InlineKeyboardButton("Skip", callback_data=f"skip_{cand_id}")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if cand['photos']:
        with open(cand['photos'][0], 'rb') as f:
            await context.bot.send_photo(update.effective_chat.id, f, caption=caption, reply_markup=markup)
    else:
        await update.message.reply_text(caption, reply_markup=markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    if data.startswith('like_'):
        to_id = int(data.split('_')[1])
        mutual = db.add_like(user_id, to_id)
        if mutual:
            await query.edit_message_text("MATCH! Start chatting.")
            other = db.get_profile(to_id)
            await context.bot.send_message(to_id, f"MATCH with {db.get_profile(user_id)['name']}! Reply to chat.")
        else:
            await query.edit_message_text("Like sent.")
        context.user_data['index'] += 1
        await show_profile(update, context)
    elif data.startswith('skip_'):
        context.user_data['index'] += 1
        await show_profile(update, context)

async def matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    matches = db.get_matches(user_id)
    if not matches:
        await update.message.reply_text("No matches yet.")
        return
    text = "Your matches:\n"
    for m in matches:
        text += f"• {m['name']}, {m['age']} ({m['city']})\n"
    await update.message.reply_text(text)

def main():
    db.init_db()
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, gender)],
            LOOKING_FOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, looking_for)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name)],
            BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, bio)],
            PHOTOS: [MessageHandler(filters.PHOTO, photos), CommandHandler('done', done_photos)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler('swipe', swipe))
    app.add_handler(CommandHandler('matches', matches))
    app.add_handler(CallbackQueryHandler(button))

    print("Bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()