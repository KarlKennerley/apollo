from decimal import Decimal, InvalidOperation
from typing import Iterable, Sized

from config import CONFIG


def user_is_irc_bot(ctx):
    return ctx.author.id == CONFIG.UWCS_DISCORD_BRIDGE_BOT_ID


def get_name_string(message):
    # if message.clean_content.startswith("**<"): <-- FOR TESTING
    if user_is_irc_bot(message):
        return message.clean_content.split(" ")[0][3:-3]
    else:
        return f"{message.author.mention}"


def is_decimal(num):
    try:
        Decimal(num)
        return True
    except (InvalidOperation, TypeError):
        return False


def pluralise(l, word, single="", plural="s"):
    if len(l) > 1:
        return word + plural
    else:
        return word + single


def filter_out_none(iterable: Iterable):
    return [i for i in iterable if i is not None]


def format_list(el: list):
    if len(el) == 1:
        return el[0]
    elif len(el) == 2:
        return f"{el[0]} and {el[1]}"
    else:
        return f'{", ".join(el[:-1])}, and {el[-1]}'

