import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from database.database import create_connection, create_table
from bot.conversation_handlers import (
    start,
    start_over,
    start_conversation,
    reply_and_new_message,
    start_image_conversation,
    generate_text_from_image,
    get_conversation_history,
    get_conversation_handler,
    done,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

CHOOSING, IMAGE_CHOICE, CONVERSATION, CONVERSATION_HISTORY = range(4)


def entry_points():
    return [
        CommandHandler("start", lambda update, context: start(update, context)),
        CallbackQueryHandler(
            lambda update, context: start_over(update, context, conn),
            pattern="^Start_Again",
        ),
    ]


def states():
    return {
        CHOOSING: [
            CallbackQueryHandler(
                lambda update, context: start_conversation(update, context),
                pattern="^New_Conversation$",
            ),
            CallbackQueryHandler(
                lambda update, context: start_image_conversation(update, context),
                pattern="^Image_Description$",
            ),
            CallbackQueryHandler(
                lambda update, context: get_conversation_history(update, context, conn),
                pattern="^PAGE#",
            ),
            CallbackQueryHandler(
                lambda update, context: done(update, context),
                pattern="^End_Conversation$",
            ),
        ],
        IMAGE_CHOICE: [
            MessageHandler(
                filters.PHOTO,
                lambda update, context: generate_text_from_image(update, context),
            )
        ],
        CONVERSATION: [
            MessageHandler(
                filters.TEXT & ~filters.Regex("^/"),
                lambda update, context: reply_and_new_message(update, context),
            )
        ],
        CONVERSATION_HISTORY: [
            CallbackQueryHandler(
                lambda update, context: get_conversation_history(update, context, conn),
                pattern="^PAGE#",
            ),
            MessageHandler(
                filters.Regex("^/conv"),
                lambda update, context: get_conversation_handler(update, context, conn),
            ),
        ],
    }


def fallbacks():
    return [
        CallbackQueryHandler(
            lambda update, context: done(update, context), pattern="^Done$"
        ),
        CallbackQueryHandler(
            lambda update, context: start_over(update, context, conn),
            pattern="^Start_Again",
        ),
    ]


def create_conv_handler():
    return ConversationHandler(
        entry_points=entry_points(), states=states(), fallbacks=fallbacks()
    )


def main() -> None:
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    conv_handler = create_conv_handler()
    application.add_handler(conv_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    database = "./conversations_data.db"

    conn = create_connection(database)
    create_table(conn)

    main()
