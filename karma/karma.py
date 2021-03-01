from datetime import datetime

from discord import Message
from sqlalchemy import desc, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy_utils import ScalarListException

from cogs.commands.admin import MiniKarmaMode
from config import CONFIG
from karma.parser import KarmaTransaction, create_transactions, parse_message
from models import Karma, KarmaChange, MiniKarmaChannel, User
from utils.aliases import get_name_string


def process_karma(message: Message, message_id: int, db_session: Session, timeout: int):
    reply = ""

    # Parse the message for karma modifications
    raw_karma = parse_message(message.clean_content, db_session)

    # If no karma'd items, just return
    if not raw_karma:
        return reply

    # TODO: Protect from byte-limit length chars

    # If the author was IRC, set the display name to be the irc user that karma'd, else use original display name
    display_name = get_name_string(message)

    # Process the raw karma tokens into a number of karma transactions
    transactions = create_transactions(message.author.name, display_name, raw_karma)

    if not transactions:
        return reply

    # Get karma-ing user
    user = db_session.query(User).filter(User.user_uid == message.author.id).first()

    # Get whether the channel is on mini karma or not
    channel = (
        db_session.query(MiniKarmaChannel)
        .filter(MiniKarmaChannel.channel == message.channel.id)
        .one_or_none()
    )
    if channel is None:
        karma_mode = MiniKarmaMode.Normal
    else:
        karma_mode = MiniKarmaMode.Mini

    def own_karma_error(name):
        if karma_mode == MiniKarmaMode.Normal:
            return f' • Could not change "{name}" because you cannot change your own karma! :angry:'
        else:
            return f'could not change "**{name}**" (own name)'

    def internal_error(name):
        if karma_mode == MiniKarmaMode.Normal:
            return f' • Could not create "{name}" due to an internal error.'
        else:
            return f'could not change "**{name}**" (internal error)'

    def cooldown_error(name, td):
        # Tell the user that the item is on cooldown
        if td.seconds < 60:
            seconds_plural = f"second{'s' if td.seconds != 1 else ''}"
            duration = f"{td.seconds} {seconds_plural}"
        else:
            mins = td.seconds // 60
            mins_plural = f"minute{'s' if mins != 1 else ''}"
            duration = f"{mins} {mins_plural}"

        if karma_mode == MiniKarmaMode.Normal:
            return f' • Could not change "{name}" since it is still on cooldown (last altered {duration} ago).\n'
        else:
            return f'could not change "**{name}**" (cooldown, last edit {duration} ago)'

    def success_item(tr: KarmaTransaction):
        # Give some sass if someone is trying to downvote the bot
        if tr.name.casefold() == "apollo" and tr.net_karma < 0:
            apollo_response = ":wink:"
        else:
            apollo_response = ""

        if tr.net_karma == 1:
            op = "++"
        elif tr.net_karma == -1:
            op = "--"
        else:
            op = "+-"

        # Build the karma item string
        if tr.reasons:
            if len(tr.reasons) > 1:
                reasons_plural = "reasons"
                reasons_has = "have"
            else:
                reasons_plural = "reason"
                reasons_has = "has"

            if karma_mode == MiniKarmaMode.Normal:
                if tr.self_karma:
                    return f" • **{truncated_name}** (new score is {karma_change.score}) and your {reasons_plural} {reasons_has} been recorded. *Fool!* that's less karma to you. :smiling_imp:"
                else:
                    return f" • **{truncated_name}** (new score is {karma_change.score}) and your {reasons_plural} {reasons_has} been recorded. {apollo_response}"
            else:
                return f"**{truncated_name}{op}** (now {karma_change.score}, {reasons_plural} recorded)"

        else:
            if karma_mode == MiniKarmaMode.Normal:
                if tr.self_karma:
                    return f" • **{truncated_name}** (new score is {karma_change.score}). *Fool!* that's less karma to you. :smiling_imp:"
                else:
                    return f" • **{truncated_name}** (new score is {karma_change.score}). {apollo_response}"
            else:
                return f"**{truncated_name}{op}** (now {karma_change.score})"

    # Start preparing the reply string
    if len(transactions) > 1:
        transaction_plural = "s"
    else:
        transaction_plural = ""

    items = []
    errors = []

    # Iterate over the transactions to write them to the database
    for transaction in transactions:
        # Truncate the name safely so we 2000 char karmas can be used
        truncated_name = (
            (transaction.name[300:] + ".. (truncated to 300 chars)")
            if len(transaction.name) > 300
            else transaction.name
        )

        # Catch any self-karma transactions early
        if transaction.self_karma and transaction.net_karma > -1:
            errors.append(own_karma_error(truncated_name))
            continue

        # Get the karma item from the database if it exists
        karma_item = (
            db_session.query(Karma)
            .filter(func.lower(Karma.name) == func.lower(transaction.name))
            .one_or_none()
        )

        # Update or create the karma item
        if not karma_item:
            karma_item = Karma(name=transaction.name)
            db_session.add(karma_item)
            try:
                db_session.commit()
            except (ScalarListException, SQLAlchemyError):
                db_session.rollback()
                errors.append(internal_error(truncated_name))
                continue

        # Get the last change (or none if there was none)
        last_change = (
            db_session.query(KarmaChange)
            .filter(KarmaChange.karma_id == karma_item.id)
            .order_by(desc(KarmaChange.created_at))
            .first()
        )

        if not last_change:
            # If the bot is being downvoted then the karma can only go up
            if transaction.name.casefold() == "apollo":
                new_score = abs(transaction.net_karma)
            else:
                new_score = transaction.net_karma

            karma_change = KarmaChange(
                karma_id=karma_item.id,
                user_id=user.id,
                message_id=message_id,
                reasons=transaction.reasons,
                change=new_score,
                score=new_score,
                created_at=datetime.utcnow(),
            )
            db_session.add(karma_change)
            try:
                db_session.commit()
            except (ScalarListException, SQLAlchemyError):
                db_session.rollback()
                errors.append(internal_error(truncated_name))
                continue
        else:
            time_delta = datetime.utcnow() - last_change.created_at

            if time_delta.seconds >= timeout:
                # If the bot is being downvoted then the karma can only go up
                if transaction.name.casefold() == "apollo":
                    new_score = last_change.score + abs(transaction.net_karma)
                else:
                    new_score = last_change.score + transaction.net_karma

                karma_change = KarmaChange(
                    karma_id=karma_item.id,
                    user_id=user.id,
                    message_id=message_id,
                    reasons=transaction.reasons,
                    score=new_score,
                    change=(new_score - last_change.score),
                    created_at=datetime.utcnow(),
                )
                db_session.add(karma_change)
                try:
                    db_session.commit()
                except (ScalarListException, SQLAlchemyError):
                    db_session.rollback()
                    errors.append(internal_error(truncated_name))
                    continue
            else:
                errors.append(cooldown_error(truncated_name, time_delta))
                continue

        # Update karma counts
        if transaction.net_karma == 0:
            karma_item.neutrals = karma_item.neutrals + 1
        elif transaction.net_karma == 1:
            karma_item.pluses = karma_item.pluses + 1
        elif transaction.net_karma == -1:
            # Make sure the changed operation is updated
            if transaction.name.casefold() == "apollo":
                karma_item.pluses = karma_item.pluses + 1
            else:
                karma_item.minuses = karma_item.minuses + 1

        items.append(success_item(transaction))

    # Get the name, either from discord or irc
    author_display = get_name_string(message)

    # Construct the reply string in totality
    # If you have error(s) and no items processed successfully
    if karma_mode == MiniKarmaMode.Normal:
        item_str = "\n".join(items)
        error_str = "\n".join(errors)
        if not item_str and error_str:
            reply = f"Sorry {author_display}, I couldn't karma the requested item{transaction_plural} because of the following problem{transaction_plural}:\n\n{error_str}"
        # If you have items processed successfully but some errors too
        elif item_str and error_str:
            reply = f"Thanks {author_display}, I have made changes to the following item(s) karma:\n\n{item_str}\n\nThere were some issues with the following item(s), too:\n\n{error_str}"
        # If all items were processed successfully
        else:
            reply = f"Thanks {author_display}, I have made changes to the following karma item{transaction_plural}:\n\n{item_str}"
    else:
        item_str = " ".join(items)
        error_str = " ".join(errors)
        reply = " ".join(filter(None, ["Changes:", item_str, error_str]))

    # Commit any changes (in case of any DB inconsistencies)
    try:
        db_session.commit()
    except (ScalarListException, SQLAlchemyError):
        db_session.rollback()
    return reply.rstrip()
