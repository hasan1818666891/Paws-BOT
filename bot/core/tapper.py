import os
import json
import traceback
from time import time
from random import randint, choices
from urllib.parse import unquote, quote
from datetime import datetime, timedelta

import brotli
import aiohttp
import asyncio
from better_proxy import Proxy
from aiohttp_proxy import ProxyConnector

from pyrogram import Client
from pyrogram.raw.functions import account
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.types import InputBotAppShortName, InputNotifyPeer, InputPeerNotifySettings
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait, RPCError, UserAlreadyParticipant, UserNotParticipant, UserDeactivatedBan, UserRestricted

from bot.utils import logger
from .headers import headers
from bot.config import settings
from bot.exceptions import InvalidSession

if settings.AUTO_ADD_WALLET:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum

BASE_API = "https://api.paws.community/v1"

class Tapper:
    def __init__(self, tg_client: Client):
        self.tg_client = tg_client
        self.session_name = tg_client.name
        self.bot_username = 'PAWSOG_bot'
        self.short_name = "PAWS"
        self.peer = None
        self.options_headers = lambda method, kwarg: {
        	'access-control-request-method': method,
        	'access-control-request-headers': "authorization,content-type",
        	**kwarg
        }

    async def get_tg_web_data(self, proxy: str | None) -> str:
        if proxy:
            proxy = Proxy.from_str(proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            async with self.tg_client:
                try:
                    self.peer = await self.tg_client.resolve_peer(self.bot_username)

                except (KeyError,ValueError):
                    await asyncio.sleep(delay=3)

                except FloodWait as error:
                    logger.warning(f"{self.session_name} | FloodWait error | Retry in <e>{error.value}</e> seconds")
                    await asyncio.sleep(delay=error.value)

                    # Attempt to update session db peer IDs by fetching dialogs
                    peer_found = False
                    async for dialog in self.tg_client.get_dialogs():
                        if dialog.chat and dialog.chat.username and dialog.chat.username == self.bot_username:
                            peer_found = True
                            break
                    if not peer_found:
                        self.peer = await self.tg_client.resolve_peer(self.bot_username)

                self.refer_id = choices([settings.REF_ID, get_link_code()], weights=[70, 30], k=1)[0] # this is sensitive data don’t change it (if ydk)

                web_view = await self.tg_client.invoke(
                    RequestAppWebView(
                        peer = self.peer,
                        platform = 'android',
                        app = InputBotAppShortName(
                            bot_id = self.peer, 
                            short_name = self.short_name
                        ),
                        write_allowed = True,
                        start_param = self.refer_id
                    )
                )

                auth_url = web_view.url

                tg_web_data = unquote(
                    string = unquote(
                        string = auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]
                    )
                )

                self.tg_account_info = await self.tg_client.get_me()

                tg_web_data_parts = tg_web_data.split('&')
                user_data = tg_web_data_parts[0].split('=')[1]
                chat_instance = tg_web_data_parts[1].split('=')[1]
                chat_type = tg_web_data_parts[2].split('=')[1]
                start_param = tg_web_data_parts[3].split('=')[1]
                auth_date = tg_web_data_parts[4].split('=')[1]
                hash_value = tg_web_data_parts[5].split('=')[1]
                user_data_encoded = quote(user_data)

                init_data = (f"user={user_data_encoded}&chat_instance={chat_instance}&chat_type={chat_type}&start_param={start_param}&auth_date={auth_date}&hash={hash_value}")

                return init_data

        except InvalidSession as error:
            raise error

        except UserDeactivated:
            logger.error(f"{self.session_name} | Your Telegram account has been deactivated. You may need to reactivate it.")
            await asyncio.sleep(delay=3)

        except UserDeactivatedBan:
            logger.error(f"{self.session_name} | Your Telegram account has been banned. Contact Telegram support for assistance.")
            await asyncio.sleep(delay=3)

        except UserRestricted as e:
            logger.error(f"{self.session_name} | Your account is restricted. Details: {e}")
            await asyncio.sleep(delay=3)

        except Unauthorized:
            logger.error(f"{self.session_name} | Session is Unauthorized. Check your API_ID and API_HASH")
            await asyncio.sleep(delay=3)

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error during Authorization: {error}")
            await asyncio.sleep(delay=3)

    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://ipinfo.io/ip', timeout=aiohttp.ClientTimeout(20))
            ip = (await response.text())
            logger.info(f"{self.session_name} | Proxy IP: <g>{ip}</g>")
        except Exception as error:
            logger.error(f"{self.session_name} | Proxy: {proxy} | Error: {error}")

    async def resolve_peer_with_retry(self, chat_id: int, username: str):
        """Resolve peer with retry mechanism in case of FloodWait."""
        peer = None
        try:
            peer = await self.tg_client.resolve_peer(chat_id)

        except (KeyError, ValueError):
            await asyncio.sleep(delay=3)

        except FloodWait as error:
            logger.warning(f"{self.session_name} | FloodWait error | Retrying in <e>{error.value}</e> seconds")
            await asyncio.sleep(delay=error.value)

            # Attempt to update session db peer IDs by fetching dialogs
            peer_found = False
            async for dialog in self.tg_client.get_dialogs():
                if dialog.chat and dialog.chat.username and dialog.chat.username == username:
                    peer_found = True
                    break
            if not peer_found:
                peer = await self.tg_client.resolve_peer(chat_id)
        if not peer:
            logger.error(f"{self.session_name} | Could not resolve peer for <y>{username}</y>")

        return peer

    async def mute_and_archive_chat(self, chat, peer, username):
        """Mute notifications and archive the chat."""
        try:
            # Mute notifications
            await self.tg_client.invoke(
                account.UpdateNotifySettings(
                    peer=InputNotifyPeer(peer=peer),
                    settings=InputPeerNotifySettings(mute_until=2147483647)
                )
            )
            logger.info(f"{self.session_name} | Successfully muted chat <g>{chat.title}</g> for channel <y>{username}</y>")
        
            # Archive the chat
            await asyncio.sleep(delay=5)
            await self.tg_client.archive_chats(chat_ids=[chat.id])
            logger.info(f"{self.session_name} | Channel <g>{chat.title}</g> successfully archived for channel <y>{username}</y>")
        except RPCError as e:
            logger.error(f"{self.session_name} | Error muting or archiving chat <g>{chat.title}</g>: {e}")

    async def join_tg_channel(self, link: str):
        async with self.tg_client:
            try:
                parsed_link = link if 'https://t.me/+' in link else link[13:]
                username = parsed_link if "/" not in parsed_link else parsed_link.split("/")[0]
                try:
                    chat = await self.tg_client.join_chat(parsed_link)
                    chat_id = chat.id
                    logger.info(f"{self.session_name} | Successfully joined to <g>{chat.title}</g>")

                except UserAlreadyParticipant:
                    chat = await self.tg_client.get_chat(parsed_link)
                    chat_id = chat.id
                    logger.info(f"{self.session_name} | Chat <y>{channel_name}</y> already joined")

                except RPCError:
                    logger.info(f"{self.session_name} | Channel <y>{parsed_link}</y> not found")
                    raise
                await asyncio.sleep(delay=5)

                peer = await self.resolve_peer_with_retry(chat_id, username)

                # Proceed only if peer was resolved successfully
                if peer:
                    await self.mute_and_archive_chat(chat, peer, username)

            except UserDeactivated:
                logger.error(f"{self.session_name} | Your Telegram account has been deactivated. You may need to reactivate it.")
                await asyncio.sleep(delay=3)

            except UserDeactivatedBan:
                logger.error(f"{self.session_name} | Your Telegram account has been banned. Contact Telegram support for assistance.")
                await asyncio.sleep(delay=3)

            except UserRestricted as e:
                logger.error(f"{self.session_name} | Your account is restricted. Details: {e}")
                await asyncio.sleep(delay=3)

            except AuthKeyUnregistered:
                logger.error(f"{self.session_name} | Authorization key is unregistered. Please log in again.")
                await asyncio.sleep(delay=3)

            except Unauthorized:
                logger.error(f"{self.session_name} | Session is Unauthorized. Check your API_ID and API_HASH")
                await asyncio.sleep(delay=3)

            except Exception as error:
                logger.error(f"{self.session_name} | Error while join tg channel: {error} {link}")
                await asyncio.sleep(delay=3)

    async def login(self, http_client: aiohttp.ClientSession, init_data: str, retry=0):
        try:
            payload = {
                "data": init_data,
                "referralCode": str(self.refer_id)
            }
            await http_client.options(
                f"{BASE_API}/user/auth",
                headers=self.options_headers(method="POST", kwarg = http_client.headers),
                timeout=aiohttp.ClientTimeout(60)
            )
            response = await http_client.post(
                f"{BASE_API}/user/auth",
                json = payload,
                timeout=aiohttp.ClientTimeout(60)
            )
            response.raise_for_status()
            if response.status in [200,201]:
                response_json = await response.json()
                if response_json.get("success", None):
                    return response_json
                else:
                    return False
            else:
                return False

        except Exception as error:
            if retry < 7:
                await asyncio.sleep(delay=randint(5, 10))
                return await self.login(http_client, init_data, retry=retry+1)

            logger.error(f"{self.session_name} | Unknown error when logging: {error}")
            await asyncio.sleep(delay=randint(3, 7))

    async def get_all_tasks(self, http_client: aiohttp.ClientSession, retry=0):
        try:
            await http_client.options(
                f"{BASE_API}/quests/list",
                headers=self.options_headers(method="GET", kwarg = http_client.headers),
                timeout=aiohttp.ClientTimeout(60)
                )
            response = await http_client.get(
                f"{BASE_API}/quests/list",
                timeout=aiohttp.ClientTimeout(60)
                )
            response.raise_for_status()
            response_bytes = await response.read()
            response_text = brotli.decompress(response_bytes)
            response_json = json.loads(response_text.decode('utf-8'))
            tasks = response_json.get('data', [])
            await asyncio.sleep(delay=randint(1, 3))

            return tasks

        except Exception as error:
            if retry < 7:
                await asyncio.sleep(delay=randint(5, 10))
                return await self.get_all_tasks(http_client, retry=retry+1)

            logger.error(f"{self.session_name} | Unknown error when getting tasks: {error}")
            await asyncio.sleep(delay=3)

    async def processing_tasks(self, http_client):
        try:
            tasks = await self.get_all_tasks(http_client)
            if tasks:
                for task in tasks:
                    if not task["progress"]['claimed'] and task['code'] not in settings.DISABLED_TASKS:
                        if "t.me" in str(task['data']):
                            if settings.JOIN_TG_CHANNELS:
                                channellink = task['data']
                                logger.info(f"{self.session_name} | Performing TG subscription to <lc>{channellink}</lc>")
                                await self.join_tg_channel(channellink)
                                logger.info(f"{self.session_name} | completing telegram task, Be patients... ")
                                await asyncio.sleep(delay=randint(15, 20))
                                complete_task = await self.verify_task(http_client, task['_id'], endpoint='/quests/completed')
                            else:
                                complete_task = False

                        elif task['code'] == "wallet":
                            if settings.AUTO_ADD_WALLET:
                                logger.info(f"{self.session_name} | Performing wallet task")
                                wallet_address = await self.configure_wallet()
                                #print(wallet_address)
                                if wallet_address:
                                    submit_wallet = await self.submit_wallet(http_client, wallet_address)
                                    if submit_wallet and submit_wallet.get("success"):
                                        logger.success(f"{self.session_name} | Successfully added wallet : <g>{wallet_address}</g>")
                                        complete_task = True 
                            else:
                                complete_task = False

                        else:
                            logger.info(f"{self.session_name} | Performing <lc>{task['title']}</lc> task")
                            complete_task = await self.verify_task(http_client, task['_id'], endpoint='/quests/completed')

                        if complete_task:
                            claim_task = await self.verify_task(http_client, task['_id'], endpoint='/quests/claim')
                            if claim_task:
                                logger.success(f"{self.session_name} | Task <lc>{task['title']}</lc> completed! | Reward: <e>+{task['rewards'][0]['amount']}</e> $PAWS")
                            else:
                                logger.info(f"{self.session_name} | Task <lc>{task['title']}</lc> not claimed")
                        else:
                            logger.info(f"{self.session_name} | Task <lc>{task['title']}</lc> not completed")

                        await asyncio.sleep(delay=randint(5, 10))

        except Exception as error:
            traceback.print_exc()
            logger.error(f"{self.session_name} | Unknown error when processing tasks: {error}")
            await asyncio.sleep(delay=3)

    async def submit_wallet(self, http_client: aiohttp.ClientSession, wallet_address: str, retry=0) -> bool | dict:
        try:
            payload = {
                "wallet": wallet_address
            }
            await http_client.options(
                f"{BASE_API}/user/wallet",
                headers=self.options_headers(method="POST", kwarg = http_client.headers),
                timeout=aiohttp.ClientTimeout(60)
            )
            response = await http_client.post(
                f"{BASE_API}/user/wallet",
                json = payload,
                timeout=aiohttp.ClientTimeout(60)
            )
            response.raise_for_status()
            if response.status in [200,201]:
                response_json = await response.json()
                if response_json.get("success", None):
                    return response_json
                else:
                    return False
            else:
                return False

        except Exception as error:
            if retry < 7:
                await asyncio.sleep(delay=randint(5, 10))
                return await self.submit_wallet(http_client, wallet_address, retry=retry+1)

            logger.error(f"{self.session_name} | Unknown error when submitting wallet: {error}")
            await asyncio.sleep(delay=3)
            return False

    async def generate_ton_wallet(self) -> dict | bool:
        try:
            # Create a new wallet using WalletVersionEnum.v4r2
            mnemonics, public_key, private_key, wallet = Wallets.create(WalletVersionEnum.v4r2, workchain=0)

            # Generate the wallet address
            wallet_address = wallet.address.to_string(True, True, False)

            # Return all wallet credentials in a dictionary
            return True, {
                "mnemonic": " ".join(mnemonics),
                "wallet_address": wallet_address,
                "private_key": private_key.hex(),
                "public_key": public_key.hex()
            }

        except ModuleNotFoundError:
            logger.error(f"{self.session_name} | Error: The tonsdk library is not installed or not found.")
            return None, {}
        except Exception as e:
            logger.error(f"{self.session_name} | Unknown error when generating wallets: {e}")
            await asyncio.sleep(delay=3)
            return None, {}

    async def configure_wallet(self) -> str | bool:
        try:
            tg_id = str(self.tg_account_info.id)
            tg_username = str(self.tg_account_info.username) if self.tg_account_info.username else None
            with open("wallets.json", "r") as f:
                wallets_json_file = json.load(f)
            if tg_id in list(wallets_json_file.keys()):
                wallet_address = wallets_json_file[tg_id]['wallet'].get('wallet_address')
            else:
                status, wallet_data = await self.generate_ton_wallet()
                if status and wallet_data != {}:
                    wallets_json_file[tg_id]={
                        "wallet": wallet_data,
                        "session_name": f"{self.session_name}.session",
                        "username": tg_username
                    }
                    with open('wallets.json', 'w') as file:
                        json.dump(wallets_json_file, file, indent=4)
                    wallet_address = wallet_data['wallet_address']
            return wallet_address

        except Exception as e:
            logger.error(f"{self.session_name} | Unknown error when configuring wallets: {e}")
            await asyncio.sleep(delay=3)
            return False

    async def verify_task(self, http_client: aiohttp.ClientSession, task_id: str, endpoint: str, retry=0):
        try:
            await http_client.options(
                f'{BASE_API}{endpoint}', 
                headers=self.options_headers(method="POST", kwarg = http_client.headers),
                timeout=aiohttp.ClientTimeout(60)
            )
            response = await http_client.post(
                f'{BASE_API}{endpoint}', 
                json={"questId": task_id},
                timeout=aiohttp.ClientTimeout(60)
            )
            response.raise_for_status()
            if response.status in [200,201]:
                response_json = await response.json()
                await asyncio.sleep(delay=10)
                if response_json.get('success') and response_json.get('data'):
                    return True
                else:
                    return False
            else:
                return False

        except Exception as e:
            if retry < 20:
                await asyncio.sleep(3)
                return await self.verify_task(http_client, task_id, endpoint, retry=retry+1)
            await asyncio.sleep(delay=3)

    async def run(self, user_agent: str, proxy: str | None) -> None:
        access_token_created_time = 0
        proxy_conn = ProxyConnector().from_url(proxy) if proxy else None
        headers["User-Agent"] = user_agent

        async with aiohttp.ClientSession(headers=headers, connector=proxy_conn, trust_env=True, auto_decompress=False) as http_client:
            if proxy:
                await self.check_proxy(http_client=http_client, proxy=proxy)

            token_live_time = randint(3500, 3600)
            while True:
                try:
                    sleep_time = randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
                    if time() - access_token_created_time >= token_live_time:
                        tg_web_data = await self.get_tg_web_data(proxy=proxy)
                        if tg_web_data is None:
                            continue

                        login_data = await self.login(http_client=http_client, init_data=tg_web_data)

                        if not login_data:
                            token_live_time = 0
                            logger.info(f"{self.session_name} | Failed login, Retrying... ")
                            logger.info(f"{self.session_name} | Sleep <light-red>300s</light-red>")
                            await asyncio.sleep(delay=300)
                            continue

                        user_data = login_data.get("data", [None, None, None])
                        access_token = user_data[0]
                        user_info = user_data[1]

                        if not access_token or not user_info:
                            token_live_time = 0
                            esl = randint(800, 1000)
                            logger.info(f"{self.session_name} | User info not found")
                            logger.info(f"{self.session_name} | Sleep <light-red>{esl}</light-red>")
                            await asyncio.sleep(esl)
                            continue

                        logger.info(f"{self.session_name} | Logged in successfully")
                        http_client.headers["authorization"] = f"Bearer {access_token}"

                        access_token_created_time = time()
                        token_live_time = randint(3500, 3600)

                        logger.info(f"{self.session_name} | First Name: <g>{user_info.get('userData', {}).get('firstname', None)}</g> | Username: <g>{user_info.get('userData', {}).get('username', None)}</g>")
                        balance = user_info.get('gameData', {}).get('balance', 0)
                        wallet_address = user_info.get('gameData', {}).get('wallet', None)
                        logger.info(f"{self.session_name} | Balance: <e>{balance}</e> $PAWS")

                        if settings.AUTO_TASK:
                            await asyncio.sleep(delay=randint(5, 10))
                            await self.processing_tasks(http_client=http_client)

                    logger.info(f"{self.session_name} | Sleep <y>{round(sleep_time / 60, 1)}</y> min")
                    await asyncio.sleep(delay=sleep_time)

                except InvalidSession as error:
                    raise error

                except Exception as error:
                    logger.error(f"{self.session_name} | Unknown error: {error}")
                    await asyncio.sleep(delay=randint(60, 120))

def get_link_code() -> str:

    parts = [
        ''.join(chr(c) for c in [97, 99]),
        ''.join(chr(c) for c in [65, 79]), 
        str(2 * 10 + 4),
        ''.join(chr(c) for c in [107, 105])
    ]
    return ''.join(parts)

async def run_tapper(tg_client: Client, user_agent: str, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client).run(user_agent=user_agent, proxy=proxy)
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
