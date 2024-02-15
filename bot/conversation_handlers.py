import io
import os
import logging
import uuid
import math
import pickle
from functools import wraps


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import PIL.Image

from core import GeminiChat
from database.database import (
    create_conversation,
    get_user_conversation_count,
    select_conversations_by_user,
    select_conversation_by_id,
    delete_conversation_by_id,
)
from helpers.inline_paginator import InlineKeyboardPaginator
from helpers.helpers import conversations_page_content, strip_markdown
from dotenv import load_dotenv


load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

CHOOSING, IMAGE_CHOICE, CONVERSATION, CONVERSATION_HISTORY = range(4)


def restricted(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != int(os.getenv("AUTHORIZED_USER")):
            logger.info(f"Unauthorized access denied for {user_id}.")
            await update.message.reply_animation(
                "https://github.com/sudoAlireza/GeminiBot/assets/87416117/beeb0fd2-73c6-4631-baea-2e3e3eeb9319",
                caption="This is my persoanl GeminiBot, to run your own Bot look at:\nhttps://github.com/sudoAlireza/GeminiBot",
            )
            return
        return await func(update, context, *args, **kwargs)

    return wrapped


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation with /start command and ask the user for input."""
    query = update.callback_query
    logger.info("Received command: /start")

    keyboard = [
        [
            InlineKeyboardButton(
                "Start New Conversation", callback_data="New_Conversation"
            ),
            InlineKeyboardButton(
                "Image Description", callback_data="Image_Description"
            ),
        ],
        [InlineKeyboardButton("Chat History", callback_data="PAGE#1")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        text="Hi. It's Gemini Chat Bot. You can ask me anything and talk to me about what you want",
        reply_markup=reply_markup,
    )

    return CHOOSING


@restricted
async def start_over(update: Update, context: ContextTypes.DEFAULT_TYPE, conn) -> int:
    """Start the conversation with button and ask the user for input."""
    query = update.callback_query
    await query.answer()

    prev_message = context.user_data.get("to_delete_message")
    if prev_message:
        await context.bot.delete_message(
            chat_id=prev_message.chat_id, message_id=prev_message.id
        )
        context.user_data["to_delete_message"]

    try:
        user_details = query.from_user
        user_id = user_details.id
        conversation_id = context.user_data.get("conversation_id")
        gemini_chat: GeminiChat = context.user_data.get("gemini_chat")

        if gemini_chat or conversation_id:
            if "_SAVE" in query.data:
                conversation_history = gemini_chat.get_chat_history()
                conversation_title = gemini_chat.get_chat_title()

                conversation_id = conversation_id or f"conv{uuid.uuid4().hex[:6]}"
                with open(f"./pickles/{conversation_id}.pickle", "wb") as fp:
                    pickle.dump(conversation_history, fp)

                conv = (
                    conversation_id,
                    user_id,
                    conversation_title,
                )
                create_conversation(conn, conv)
                logger.info(f"conversation {conversation_id} saved in db and closed")

            else:
                logger.info(f"conversation {conversation_id} closed without saving")

            gemini_chat.close()
        else:
            logger.info("No active chat to close")

        gemini_chat = None
        context.user_data["gemini_chat"] = None
        context.user_data["conversation_id"] = None

    except Exception as e:
        logger.error("Error during conversation handling: %s", e)

    keyboard = [
        [
            InlineKeyboardButton(
                "Start New Conversation", callback_data="New_Conversation"
            )
        ],
        [InlineKeyboardButton("Image Description", callback_data="Image_Description")],
        [InlineKeyboardButton("Chat History", callback_data="PAGE#1")],
        [InlineKeyboardButton("Start Again", callback_data="Start_Again")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await context.bot.send_message(
        query.message.chat.id,
        text="Hi. It's Gemini Chat Bot. You can ask me anything and talk to me about what you want",
        reply_markup=reply_markup,
    )
    context.user_data["to_delete_message"] = msg

    return CHOOSING


@restricted
async def start_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user to start conversation by writing any message."""
    query = update.callback_query
    await query.answer()

    logger.info("Received callback: New_Conversation")
    message_content = "You asked for a conversation. OK, Let's start conversation!"

    conv_id = context.user_data.get("conversation_id")
    if conv_id:
        message_content = "You asked for a continue conversation. OK, Let's go!"

    keyboard = [[InlineKeyboardButton("Return to menu", callback_data="Start_Again")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await query.edit_message_text(
        query.message.chat.id,
        text=message_content,
        reply_markup=reply_markup,
    )
    context.user_data["to_delete_message"] = msg

    return CONVERSATION


@restricted
async def reply_and_new_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Send user message to Gemini core and respond and wait for new message or exit command"""
    query = update.callback_query

    keyboard = [[InlineKeyboardButton("Back to menu", callback_data="Start_Again")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = await update.message.reply_text(
        text="Wait for response processing...",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )

    ##############

    text = update.message.text
    conv_id = context.user_data.get("conversation_id")
    conversation_history = []
    if conv_id:
        with open(f"./pickles/{conv_id}.pickle", "rb") as fp:
            conversation_history = pickle.load(fp)

    gemini_chat = context.user_data.get("gemini_chat")
    if not gemini_chat:
        logger.info("Creating new conversation instance")
        gemini_chat = GeminiChat(
            gemini_token=os.getenv("GEMINI_API_TOKEN"),
            chat_history=conversation_history,
        )
        gemini_chat.start_chat()

    response = gemini_chat.send_message(text).encode("utf-8").decode("utf-8", "ignore")

    context.user_data["gemini_chat"] = gemini_chat

    keyboard = [
        [
            InlineKeyboardButton(
                "Save and Back to menu", callback_data="Start_Again_SAVE"
            )
        ],
        [
            InlineKeyboardButton(
                "Back to menu without saving", callback_data="Start_Again"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            text=response,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            chat_id=update.message.chat_id,
        )
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.id)

    except Exception as e:
        await context.bot.send_message(
            text=strip_markdown(response),
            reply_markup=reply_markup,
            chat_id=update.message.chat_id,
        )
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.id)
        logging.warning(__name__, e)

    return CONVERSATION


@restricted
async def get_conversation_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, conn
) -> int:
    """Get conversation from database and ask user if wants new conversation or not"""

    query_messsage = update.message.text.replace("/", "")
    context.user_data["conversation_id"] = query_messsage
    user_details = update.message.from_user.id
    conv_specs = (user_details, query_messsage)

    conversation = select_conversation_by_id(conn, conv_specs)

    message_content = f"Conversation {conversation.get('conv_id')} retrieved and title is: {conversation.get('title')}"

    keyboard = [
        [
            InlineKeyboardButton(
                "Continue Conversations", callback_data="New_Conversation"
            )
        ],
        [
            InlineKeyboardButton(
                "Delete Conversation", callback_data="Delete_Conversation"
            )
        ],
        [InlineKeyboardButton("Back to menu", callback_data="Start_Again")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = await update.message.reply_text(
        text=message_content, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
    )
    context.user_data["to_delete_message"] = msg

    return CONVERSATION_HISTORY


@restricted
async def delete_conversation_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, conn
) -> int:
    """Delete conversation if user clicks on Delete button"""
    query = update.callback_query

    await query.answer()

    conversation_id = context.user_data["conversation_id"]
    user_details = query.from_user.id
    conv_specs = (user_details, conversation_id)

    conversation = delete_conversation_by_id(conn, conv_specs)

    keyboard = [[InlineKeyboardButton("Back to menu", callback_data="Start_Again")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = await query.edit_message_text(
        text="Conversation history deleted successfully. Back to menu Start new Conversation",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
    )
    context.user_data["to_delete_message"] = msg

    return CHOOSING


@restricted
async def start_image_conversation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ask user to upload an image with caption"""
    query = update.callback_query
    logger.info("Received callback: Image_Description")

    keyboard = [[InlineKeyboardButton("Back to menu", callback_data="Start_Again")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = await query.edit_message_text(
        f"You asked for Image description. OK, Send your image with caption!",
        reply_markup=reply_markup,
    )
    context.user_data["to_delete_message"] = msg

    return IMAGE_CHOICE


@restricted
async def generate_text_from_image(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Send image to Gemini core and send response to user"""
    query = update.callback_query
    logger.info("Received callback: generate_text_from_image")

    keyboard = [[InlineKeyboardButton("Back to menu", callback_data="Start_Again")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await update.message.reply_text(
        text="Wait for response processing...",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )

    photo_file = await update.message.photo[-1].get_file()
    buf = io.BytesIO()
    await photo_file.download_to_memory(buf)
    buf.name = "user_image.jpg"
    buf.seek(0)

    image = PIL.Image.open(buf)

    gemini_image_chat = GeminiChat(
        gemini_token=os.getenv("GEMINI_API_TOKEN"), image=image
    )

    try:
        response = response = (
            gemini_image_chat.send_image(update.message.caption)
            .encode("utf-8")
            .decode("utf-8", "ignore")
        )

        if not response:
            raise Exception("Empty response from Gemini")
    except Exception as e:
        logger.warning("Error during image processing: %s", e)
        response = "Couldn't generate a response. Please try again."

    buf.close()
    del photo_file
    del image

    keyboard = [[InlineKeyboardButton("Back to menu", callback_data="Start_Again")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            text=response,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            chat_id=update.message.chat_id,
        )
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.id)

    except Exception as e:
        await context.bot.send_message(
            text=strip_markdown(response),
            reply_markup=reply_markup,
            chat_id=update.message.chat_id,
        )
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.id)
        logging.warning(__name__, e)

    return CHOOSING


@restricted
async def get_conversation_history(
    update: Update, context: ContextTypes.DEFAULT_TYPE, conn
) -> int:
    """Read conversations history of the user"""
    query = update.callback_query
    await query.answer()
    logger.info("Received callback: PAGE#")

    conversations_count = get_user_conversation_count(conn, query.from_user.id)
    total_pages = math.ceil(float(conversations_count / 10))

    page_number = int(query.data.split("#")[1])
    offset = (page_number - 1) * 10

    conversations = select_conversations_by_user(conn, (query.from_user.id, offset))
    if conversations:
        page_content = conversations_page_content(conversations)
    else:
        page_content = "You have not any chat history"

    paginator = InlineKeyboardPaginator(
        total_pages, current_page=page_number, data_pattern="PAGE#{page}"
    )
    paginator.add_after(
        InlineKeyboardButton("Back to menu", callback_data="Start_Again")
    )

    msg = await query.edit_message_text(
        page_content,
        reply_markup=paginator.markup,
        parse_mode=ParseMode.MARKDOWN,
    )
    context.user_data["to_delete_message"] = msg

    return CONVERSATION_HISTORY


@restricted
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """End the conversation."""
    # To-Do: Remove this handler and handle ending with start and start_over handlers
    query = update.callback_query
    logger.info("Received callback: Done")

    try:
        user_data = context.user_data
        gemini_chat = user_data["gemini_chat"]

        gemini_chat.close()
    except:
        pass

    user_data["gemini_chat"] = None

    keyboard = [
        [
            InlineKeyboardButton(
                "Start New Conversation", callback_data="New_Conversation"
            )
        ],
        [InlineKeyboardButton("Image Description", callback_data="Image_Description")],
        [InlineKeyboardButton("Refresh", callback_data="Start_Again")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message("Until next time!", reply_markup=reply_markup)

    user_data.clear()
    return CHOOSING
