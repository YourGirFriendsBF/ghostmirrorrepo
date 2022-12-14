from random import SystemRandom
from string import ascii_letters, digits
from telegram.ext import CommandHandler
from threading import Thread
from time import sleep

from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.telegram_helper.message_utils import sendMessage, deleteMessage, delete_all_messages, update_all_messages, sendStatusMessage, sendMarkup
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.mirror_utils.status_utils.clone_status import CloneStatus
from bot import dispatcher, LOGGER, download_dict, download_dict_lock, Interval, config_dict, CHECK_FILE_SIZE
from bot.helper.ext_utils.bot_utils import is_gdrive_link, new_thread, get_user_task, get_readable_file_size, is_gdtot_link
from bot.helper.mirror_utils.download_utils.direct_link_generator import gdtot
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.telegram_helper.button_build import ButtonMaker

def _clone(message, bot):
    user_id = message.from_user.id
    total_task = len(download_dict)
    USER_TASKS_LIMIT = config_dict['USER_TASKS_LIMIT']
    TOTAL_TASKS_LIMIT = config_dict['TOTAL_TASKS_LIMIT']
    if user_id != config_dict['OWNER_ID']:
        if TOTAL_TASKS_LIMIT == total_task:
            return sendMessage(f"Total task limit: {TOTAL_TASKS_LIMIT}\nTasks processing: {total_task}\n\nTotal limit exceeded!", bot ,message)
        if USER_TASKS_LIMIT == get_user_task(user_id):
            return sendMessage(f"User task limit: {USER_TASKS_LIMIT} \nYour tasks: {get_user_task(user_id)}\n\nUser limit exceeded!", bot ,message)
    if config_dict['BOT_PM'] and message.chat.type != 'private':
        buttons = ButtonMaker()	
        try:
            msg = f'Test msg.'
            send = bot.sendMessage(message.from_user.id, text=msg)
            send.delete()
        except Exception as e:
            LOGGER.warning(e)
            bot_d = bot.get_me()
            b_uname = bot_d.username
            uname = f'<a href="tg://user?id={message.from_user.id}">{message.from_user.first_name}</a>'
            botstart = f"http://t.me/{b_uname}"
            buttons.buildbutton("Click here to start me!", f"{botstart}")
            startwarn = f"Dear {uname},\nI found that you haven't started me in PM yet.\n\n" \
                        f"Start me in PM so that i can send a copy of your Files/Links in your PM."
            message = sendMarkup(startwarn, bot, message, buttons.build_menu(1))
            return
    args = message.text.split()
    reply_to = message.reply_to_message
    link = ''
    multi = 0
    if len(args) > 1:
        link = args[1].strip()
        if link.strip().isdigit():
            multi = int(link)
            link = ''
        elif message.from_user.username:
            tag = f"@{message.from_user.username}"
        else:
            tag = message.from_user.mention_html(message.from_user.first_name)
    if reply_to:
        if len(link) == 0:
            link = reply_to.text.split(maxsplit=1)[0].strip()
        if reply_to.from_user.username:
            tag = f"@{reply_to.from_user.username}"
        else:
            tag = reply_to.from_user.mention_html(reply_to.from_user.first_name)
    is_gdtot = is_gdtot_link(link)
    if is_gdtot:
        try:
            msg = sendMessage(f"Processing: <code>{link}</code>", bot, message)
            LOGGER.info(f"Processing: {link}")
            if is_gdtot:
                link = gdtot(link)
            LOGGER.info(f"Processing GdToT: {link}")
            deleteMessage(bot, msg)
        except Exception as e:
            deleteMessage(bot, msg)
            return sendMessage(str(e), bot, message)
    if is_gdrive_link(link):
        gd = GoogleDriveHelper()
        res, size, name, files = gd.helper(link)
        if res != "":
            return sendMessage(res, bot, message)
        if config_dict['STOP_DUPLICATE']:
            LOGGER.info('Checking File/Folder if already in Drive...')
            smsg, button = gd.drive_list(name, True, True)
            if smsg:
                msg = "File/Folder is already available in Drive.\nHere are the search results:"
                return sendMarkup(msg, bot, message, button)
        if CHECK_FILE_SIZE:
            if CLONE_LIMIT := config_dict['CLONE_LIMIT']:
                user_id = message.from_user.id
                if user_id != config_dict['OWNER_ID']:
                    LOGGER.info('Checking File/Folder Size...')
                    if size > CLONE_LIMIT * 1024**3:
                        msg = f'Failed, Clone limit is {CLONE_LIMIT}GB.\nYour File/Folder size is {get_readable_file_size(size)}.'
                        return sendMessage(msg, bot, message)
        if multi > 1:
            sleep(4)
            nextmsg = type('nextmsg', (object, ), {'chat_id': message.chat_id, 'message_id': message.reply_to_message.message_id + 1})
            cmsg = message.text.split()
            cmsg[1] = f"{multi - 1}"
            nextmsg = sendMessage(" ".join(cmsg), bot, nextmsg)
            nextmsg.from_user.id = message.from_user.id
            sleep(4)
            Thread(target=_clone, args=(nextmsg, bot)).start()
        if files <= 20:
            msg = sendMessage(f"Cloning: <code>{link}</code>", bot, message)
            result, button = gd.clone(link)
            deleteMessage(bot, msg)
        else:
            drive = GoogleDriveHelper(name)
            gid = ''.join(SystemRandom().choices(ascii_letters + digits, k=12))
            clone_status = CloneStatus(drive, size, message, gid)
            with download_dict_lock:
                download_dict[message.message_id] = clone_status
            sendStatusMessage(message, bot)
            result, button = drive.clone(link)
            with download_dict_lock:
                del download_dict[message.message_id]
                count = len(download_dict)
            try:
                if count == 0:
                    Interval[0].cancel()
                    del Interval[0]
                    delete_all_messages()
                else:
                    update_all_messages()
            except IndexError:
                pass
        cc = f'\n\n<b>cc: </b>{tag}'
        if button in ["cancelled", ""]:
            sendMessage(f"{tag} {result}", bot, message)
        else:
            sendMarkup(result + cc, bot, message, button)
            LOGGER.info(f'Cloning Done: {name}')
        if config_dict['BOT_PM'] and message.chat.type != 'private':	
            try:	
                bot.sendMessage(message.from_user.id, 
                                text=result + cc, 
                                reply_markup=button, 
                                parse_mode='HTML')
            except Exception as e:	
                LOGGER.warning(e)	
                pass
        if MIRROR_LOG := config_dict['MIRROR_LOG']:
            try:
                bot.sendMessage(chat_id=MIRROR_LOG, 
                                text=result + cc, 
                                reply_markup=button, 
                                parse_mode='HTML')	
            except Exception as e:	
                LOGGER.warning(e)
                pass
    else:
        sendMessage("Send link along with command or by replying to the link by command.", bot, message)

@new_thread
def cloneNode(update, context):
    _clone(update.message, context.bot)

clone_handler = CommandHandler(BotCommands.CloneCommand, cloneNode,
                               filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)

dispatcher.add_handler(clone_handler)
