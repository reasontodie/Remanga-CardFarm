import asyncio
import json
import os.path

from asyncio import set_event_loop_policy
from asyncio import WindowsSelectorEventLoopPolicy

from curl_cffi.requests import Session
from curl_cffi.requests import Response
from curl_cffi.requests import AsyncSession

from loguru import logger

from libs.http_conn import AsyncHTTP, SyncHTTP


class ReManga:
    BASE_URL: str = 'https://api.remanga.org/api'
    BASE_PATHS: dict = {
        'login': '/users/login/',
        'current': '/v2/users/current',
        'count_bookmarks': '/users/{}/user_bookmarks',
        'bookmarks': '/users/{}/bookmarks',
        'catalog': '/search/catalog',
        'chapters': '/titles/chapters',
        'views': '/activity/views/'
    }

    SITE_URL: str = 'https://remanga.org'
    SITE_PATHS: dict = {
        'node': '/node-api/cookie/',
        'manga_page': '/_next/data/0WMsTVhcJNvltEilcpQjj/ru/manga/{}.json'
    }

    DATA_DIR = 'data'
    CACHE_PATH = 'data/{}_cache.json'

    set_event_loop_policy(WindowsSelectorEventLoopPolicy())

    def __init__(self,
                 username: str = None,
                 password: str = None,
                 token: str = None):

        self.username = username
        self.password = password
        self.token = token

        self.headers: dict = {
            'user-agent': 'okhttp',
            'refer': self.SITE_URL,
            "content-type": "application/json",
            "origin": self.SITE_URL,
            "agesubmitted": "true",
            'x-nextjs-data': "1"
        }

        self.user_info = None

        self.page = 0
        self.ignore_list = {}
        self.viewed_chapters = []
        self.need_to_view_title = {}
        self.need_to_view_chapters = {}

        self.sync_session = SyncHTTP(Session())
        self.async_session = AsyncHTTP(AsyncSession())

        self.__load_cache() or self.__login(self.username, self.password, self.token)
        self.__update_manga_page_path()
        logger.success(f'<{self.username or self.user_info.get("username")}: Successful login>')

    def __login(self,
                username: str = None,
                password: str = None,
                token: str = None) -> None:

        cookie_jar = ['agesubmitted=true;']

        def unpack_cookie(response: Response):
            return response.headers.get('set-cookie').split(';')[0].split('=')

        def get_cookie_server_user(user_meta):
            node_url = self.SITE_URL + self.SITE_PATHS.get("node")
            data = [{
                "key": "serverUser",
                "value": user_meta,
                "options": {"httpOnly": True}
            }]
            response = self.sync_session.req('POST', url=node_url, headers=self.headers, data=data)

            cookie = unpack_cookie(response)
            cookie_jar.append(f'{cookie[0]}={cookie[1]}')
            cookie_jar.append(f'user={cookie[1]}')

        def get_cookie_server_token(user_token: str):
            node_url = self.SITE_URL + self.SITE_PATHS.get("node")
            data = [{
                "key": "serverToken",
                "value": user_token,
                "options": {"httpOnly": True}
            }]
            response = self.sync_session.req('POST', url=node_url, headers=self.headers, data=data)

            cookie = unpack_cookie(response)
            cookie_jar.append(f'{cookie[0]}={cookie[1]};')

        def get_access_token():
            url = self.BASE_URL + self.BASE_PATHS["login"]
            payload = {
                'user': self.username,
                'password': self.password,
                'g-recaptcha-response': 'WITHOUT_TOKEN'
            }
            response = self.sync_session.req('POST', url=url, headers=self.headers, data=payload)

            cookie = unpack_cookie(response)

            self.user_info = response.json().get('content', {})
            cookie_jar.append(f'serverUser={json.dumps(response.json().get("content", {}))};')
            cookie_jar.append(f'{cookie[0]}={cookie[1]};')
            return response.json().get('content', {}).get('access_token')

        if (username and password) or token:
            access_token = token or get_access_token()
            cookie_jar.append(f'token={access_token};')

            self.headers['token'] = access_token
            self.headers['authorization'] = f'bearer {access_token}'

            metadata = self.get_current_user() if token else None
            self.user_info = metadata or self.user_info
            self.user_info['token'] = access_token

            get_cookie_server_user(json.dumps(self.user_info))
            get_cookie_server_token(access_token)
            self.headers['cookie'] = ' '.join(cookie_jar)
        else:
            raise ValueError('No auth credentials. Please provide information')

    def __update_manga_page_path(self):
        response = self.sync_session.req('GET', self.SITE_URL, headers=self.headers)
        for i in response.text.split():
            if '_buildManifest.js' in i:
                new_path = f'/_next/data/{i.split("/")[3]}' + '/ru/manga/{}.json'
                self.SITE_PATHS['manga_page'] = new_path
                logger.info(f'<New _next path: {new_path}')

    def get_current_user(self) -> dict:
        url = self.BASE_URL + self.BASE_PATHS["current"]
        print(url)
        print(self.headers)
        response = self.sync_session.req('GET', url=url, headers=self.headers)
        return response.json()

    async def __get_total_count_bookmarks(self) -> int:
        api_endpoint = self.BASE_PATHS['count_bookmarks'].format(self.user_info['id'])
        url = self.BASE_URL + api_endpoint
        response = await self.async_session.req('GET', url=url, headers=self.headers)
        count = 0

        for bookmark_type in response.json().get('content', []):
            count += bookmark_type.get('count')
        return count

    async def get_user_bookmarks_for_ignore(self) -> dict:
        bookmark_count = await self.__get_total_count_bookmarks()
        api_endpoint = self.BASE_PATHS['bookmarks'].format(self.user_info['id'])
        url = self.BASE_URL + api_endpoint
        querystring = {
            "type": "0",
            "count": f"{bookmark_count}",
            "page": "1"
        }
        response = await self.async_session.req('GET',
                                                url=url,
                                                headers=self.headers,
                                                params=querystring)

        for title in response.json().get('content', {}):
            title_id = title.get('title', {}).get('id', '')
            title_dir = title.get('title', {}).get('dir', '')
            self.ignore_list[title_id] = title_dir
        return self.ignore_list

    async def __unpack_catalog(self, content: list):
        for title in content:
            title_id = title.get('id')
            if title_id not in self.ignore_list and title_id not in self.need_to_view_title:
                self.need_to_view_title[title_id] = {
                    'dir': title['dir'],
                    'name': title['main_name']
                }
        
    async def get_catalog(self, order_by: str = 'id') -> dict:
        api_endpoint = self.BASE_PATHS['catalog']
        url = self.BASE_URL + api_endpoint
        querystring = {
            "content": "manga",
            "count": "3000",
            "ordering": order_by,
            "page": f"{self.page}"
        }
        response = await self.async_session.req('GET', url=url, headers=self.headers, params=querystring)

        await self.__unpack_catalog(response.json().get('content', []))
        return self.need_to_view_title

    async def __farm_view(self) -> None:

        async def view_chapter(chapter_i: tuple, m_dir: dict) -> None:
            url = self.BASE_URL + self.BASE_PATHS.get('views')
            payload = {"chapter": int(chapter_i[0]), "page": -1}
            await self.async_session.req('POST', url=url,
                                         headers=self.headers,
                                         data=payload)
            text = (f'<{self.username or self.user_info.get("username")}'
                    f' Viewed: Manga: {m_dir.get("name")}, Chapter: {chapter_i[1]}>')
            logger.info(text)
            self.viewed_chapters.append(chapter_i[0])

        async def get_manga_branch(m_dir: dict) -> None:
            url = self.SITE_URL + self.SITE_PATHS.get('manga_page').format(m_dir.get('dir'))
            querystring = {
                "content": "manga",
                "title": m_dir.get('dir'),
                "p": "chapters"
            }
            response = await self.async_session.req('GET', url=url,
                                                    headers=self.headers,
                                                    params=querystring)
            if response:
                data = response.json().get('pageProps', {}).get('fallbackData', {})
                branches = data.get('content', {}).get('branches', [])
                current_reading = data.get('content', {}).get('current_reading', {})
                if branches:
                    branch: int = branches[0].get('id')
                    chapter = float(current_reading.get("chapter")) if current_reading else 0.0
                    # return {"data": {"dir": manga_dir, "branch": branch, "last_chapter": chapter}}
                    await get_manga_chapters(branch, m_dir, chapter)

        async def get_manga_chapters(branch: int, m_dir, viewed_chapter: float):
            url = self.BASE_URL + self.BASE_PATHS.get('chapters')
            querystring = {
                "branch_id": f"{branch}",
                "user_data": "0"
            }
            response = await self.async_session.req('GET', url=url,
                                                    headers=self.headers,
                                                    params=querystring)

            if response:
                chapters = []
                for chapter in response.json().get('content', [])[::-1]:
                    if chapter.get('is_paid') is True:
                        continue
                    try:
                        if float(chapter.get('chapter', 0)) < viewed_chapter:
                            continue
                    except ValueError:
                        if float(chapter.get('chapter').replace('-', '.').split('.')[0]) < viewed_chapter:
                            continue
                    if chapter.get('id') not in self.viewed_chapters:
                        chapters.append((chapter.get('id'), chapter.get('chapter')))
                await asyncio.gather(*[view_chapter(chapter, m_dir) for chapter in chapters])
                # return chapters

        tasks = []
        for manga_dir in self.need_to_view_title.values():
            tasks.append(get_manga_branch(manga_dir))
        await asyncio.gather(*tasks)

    def __load_cache(self):
        path = self.CACHE_PATH.format(self.username) if self.username else self.CACHE_PATH.format(self.token)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                self.page = data.get('page')
                self.token = data.get('token')
                self.viewed = data.get('viewed')
                self.headers = data.get('headers')
                self.username = data.get('username')
                self.password = data.get('password')
                self.user_info = data.get('user_info')
                return True

    async def __save_viewed(self):
        if not os.path.exists(self.DATA_DIR):
            os.mkdir(self.DATA_DIR)
        path = self.CACHE_PATH.format(self.username) if self.username else self.CACHE_PATH.format(self.user_info["username"])
        with open(path, 'w', encoding='utf-8') as file:
            json.dump({
                "username": self.username or self.user_info.get("username"),
                "password": self.password,
                "token": self.token or self.user_info['token'],
                "headers": self.headers,
                "user_info": self.user_info,
                "page": self.page,
                "viewed'": self.viewed_chapters
            }, file)

    async def time_to_fun(self):
        await self.get_user_bookmarks_for_ignore()
        while True:
            self.page += 1
            await self.get_catalog()
            await self.__farm_view()
            await self.__save_viewed()
            logger.success(f'<{self.username or self.user_info.get("username")}: TIMEBREAK 20 SEC>')
            await asyncio.sleep(20)
