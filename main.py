import asyncio

from libs import ReManga


def load_accounts() -> list:
    with open('accounts.txt', 'r', encoding='utf-8') as file:
        return [acc.replace('\n', '') for acc in file.readlines()]


async def main():
    tasks = []
    for account in load_accounts():
        data = account.split(':')
        if len(data) > 1:
            username, password, token = data if len(data) == 3 else (data[0], data[1], None)
        else:
            username, password, token = None, None, data[0]
        tasks.append(ReManga(username=username, password=password, token=token).time_to_fun())

    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())
