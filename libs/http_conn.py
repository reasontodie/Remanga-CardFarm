from typing import Dict, Any, Optional, Union, List

from curl_cffi.requests import AsyncSession, Session, Response
from loguru import logger


class BaseHTTP:
    def __init__(self, session: Union[Session, AsyncSession]):
        self.session = session

    @staticmethod
    def parse_response(response):
        if response.status_code == 200:
            return response.json()

    @staticmethod
    def log(url, method, status_code):
        logger.debug(f'<{url}, method:{method}, status: {status_code}>')

    @staticmethod
    def err_status_log(url, method, status_code, text):
        logger.error(f'<{url}, method:{method}, status: {status_code}, text: {text}>')

    @staticmethod
    def err_log(url, method, exception):
        logger.critical(f'<{url}, method: {method}, exception: {exception}>')


class SyncHTTP(BaseHTTP):
    def __init__(self, session: Session):
        super().__init__(session)

    def req(self,
            method: str,
            url: str,
            headers: Optional[Dict[str, Any]] = None,
            params: Optional[Dict[str, Any]] = None,
            data: Optional[Dict[str, Any] | List[Any]] = None) -> Response | None:
        retry = 0
        max_retry = 30
        while retry < max_retry:
            try:

                response = self.session.request(method=method,
                                                url=url,
                                                headers=headers,
                                                params=params,
                                                json=data)
                if response.status_code in [200, 204]:
                    self.log(url, response.request.method, response.status_code)
                    return response
                elif response.status_code in [501, 503, 429]:
                    continue
                elif response.status_code in [404]:
                    return
                elif response.status_code in [401]:
                    retry = max_retry
                    raise ValueError(f'Wrong auth credentials on token: {headers.get("token")}')
                elif response.status_code in [400]:
                    retry = max_retry
                    raise ValueError(f'Wrong auth credentials on user: {data.get("user")} | token: {data.get("token")}')
                self.err_status_log(url, method, response.status_code, response.text)
                retry += 1

            except Exception as err:
                self.err_log(url, method, err)


class AsyncHTTP(BaseHTTP):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def req(self,
                  method: str,
                  url: str,
                  headers: Optional[Dict[str, Any]] = None,
                  params: Optional[Dict[str, Any]] = None,
                  data: Optional[Dict[str, Any] | List[Any]] = None) -> Response | None:
        retry = 0
        while retry < 400:
            try:

                response = await self.session.request(method=method,
                                                      url=url,
                                                      headers=headers,
                                                      params=params,
                                                      json=data)
                if response.status_code in [200, 204]:
                    self.log(url, response.request.method, response.status_code)
                    return response
                elif response.status_code in [501, 503, 429]:
                    continue
                elif response.status_code in [404]:
                    return
                self.err_status_log(url, method, response.status_code, response.text)
                retry += 1

            except Exception as err:
                self.err_log(url, method, err)
