import uuid

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from config import get_logger
from item_management import get_items
# Assuming get_minecraft_username is in user_management
# from user_management import get_minecraft_username

logger = get_logger(__name__)


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    results = []
    if query:
        all_items = get_items()
        if not all_items:
            logger.warning(
                "Inline query: lista ITEMS vuota o non disponibile.")
        else:
            matches = [
                i for i in all_items
                if query in i["id"].lower() or query in i["name"].lower()
            ]
            # Ensure minecraft_username is fetched for the template string
            # This is tricky for inline mode as user context isn't directly tied
            # For now, use a placeholder or instruct user to replace it.
            # A better approach would be a different command structure for inline results.
            mc_user_placeholder = "{MINECRAFT_USERNAME}" # Placeholder

            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title=i["name"],
                    description=f'ID: {i["id"]}',
                    input_message_content=InputTextMessageContent(
                        # User will need to replace placeholder or bot needs to know username
                        f'/give {mc_user_placeholder} {i["id"]} 1'
                    )
                ) for i in matches[:20] # Show max 20 results
            ]
    await update.inline_query.answer(results, cache_time=10)
