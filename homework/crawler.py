import os
import sys
import time
import random
import asyncio
import hashlib
import logging
import mimetypes
from urllib.parse import urljoin
from optparse import OptionParser

import aiohttp
import aiofiles
import aiofiles.os
from bs4 import BeautifulSoup

from config import ROOTPAGE, TIMEOUT, MAX_RETRY, MAX_WORKERS, PERIOD, DOWNLOADS_DIR
from thetypes import NewsItem, counter, tracker
from config import name_pattern


def get_filename(filename: str):
    h = hashlib.md5(bytes(filename, encoding="utf8"))
    return h.hexdigest()


def get_only_new(newslist: list[NewsItem]):
    try:
        registered_news = os.listdir(DOWNLOADS_DIR)
    except FileNotFoundError:
        return newslist
    else:
        return [el for el in newslist if el.id not in registered_news]


def get_extra_links(dirname: str, links: list[str]):
    extra_links = []
    files = os.listdir("/".join((DOWNLOADS_DIR, dirname)))
    try:
        files.remove("links.txt")
    except ValueError:
        pass
    for link in list(set(links)):
        if ".".join((get_filename(link), "html")) not in files:
            extra_links.append(link)
    return extra_links


async def save_file(newsdir, filename, content):
    h = hashlib.md5(bytes(filename, encoding="utf8"))
    filename = h.hexdigest()
    filename = ".".join((filename, "html"))
    path = "/".join((DOWNLOADS_DIR, newsdir, filename))
    if os.path.exists(path):
        logging.debug("File %s already exists" % filename)
        return
    async with aiofiles.open(path, "w") as f:
        await f.write(content)
    logging.debug("File %s saved" % filename)
    await counter.incr_files()


async def make_dirs(names: str or list[str]):
    if isinstance(names, str):
        names = [names]
    for dirname in names:
        path = "/".join((DOWNLOADS_DIR, dirname))
        if not os.path.isdir(path):
            await aiofiles.os.makedirs(path)
            logging.debug("Directory %s created" % dirname)
        else:
            logging.debug("Directory %s already exists" % dirname)


def parse_news_list(html: str) -> list[NewsItem]:
    """
    Returns list of NewsItems.
    """
    soup = BeautifulSoup(html, features="html.parser")
    news_table = soup.find("table", id="hnmain")
    raw_news_list = news_table.find_all("tr", class_="athing")
    news_list = []
    for el in raw_news_list:
        news_id = el["id"]
        name = name_pattern.search(el.text).group(1)
        a_tag = el.find("a", "titlelink")
        link = a_tag.get("href") if a_tag else ""
        if not link.startswith("http"):
            logging.debug("Got internal link")
            link = urljoin(ROOTPAGE, link)
        comments_page = urljoin(ROOTPAGE, f"item?id={news_id}")
        news_list.append(
            NewsItem(name=name, link=link, id=news_id, comments_page=comments_page)
        )
    logging.debug("Made newslist, length: %s" % len(news_list))
    return news_list


def parse_comments_page(html: str) -> list[str]:
    """
    Return list of parsed links
    """
    result_list = []
    soup = BeautifulSoup(html, features="html.parser")
    comments = soup.find_all("span", "commtext c00")
    for comm in comments:
        link: str = comm.find("a")
        if not link:
            continue
        link = link["href"]
        m_type, _ = mimetypes.guess_type(link)
        if link.startswith("http") and not m_type:
            result_list.append(link)
    result_list = list(set(result_list))
    logging.debug("Parsing result list length: %s" % len(result_list))
    return result_list


async def fetch(session, page):
    html = ""
    for i in range(MAX_RETRY):
        try:
            async with session.get(page) as response:
                html = await response.text()
                break
        except TimeoutError:
            await asyncio.sleep(random.randint(1, 3) / 10 + round(2 * i / 10))
            continue
        except Exception as exc:
            err = type(exc).__name__
            logging.error("%s: Cannot get %s" % (err, page))
            break
    return html


async def download_page(page, client=None, register_count=True):
    html = ""
    logging.debug("Sheduled downloading %s..." % page[:20])
    if not client:
        client = aiohttp.ClientSession(timeout=TIMEOUT)
    async with client:
        html = await fetch(client, page)
        logging.debug("Success: %s..." % page[:20])
    if html and register_count:
        await counter.incr_download()
    return html


async def slow_download(
    url: str,
    sema: asyncio.Semaphore,
    target_name: str = "page",
    error_condition=lambda x: False,
    retry_for: int = MAX_RETRY,
):
    result = ""
    for i in range(retry_for * 2):
        try:
            logging.debug("Waiting for download slot")
            async with sema:
                result = await download_page(url, register_count=False)
                if error_condition(result):
                    raise ConnectionRefusedError("Server not able to serve reqs")
        except ConnectionRefusedError:
            result = ""
            await asyncio.sleep(random.randint(5, 20) / 10 + i)
    if result:
        await counter.incr_download()
    return result


async def register(newspiece: NewsItem, sema: asyncio.Semaphore):
    """
    Register a newspiece in file system:
    * make folder with news <id> (if no folder)
    * make a file <links.txt> in that folder (if no file)
        and save there the comments url and news url.
    * read urls from <links.txt>
    * download and parse comments
    * get set difference {new urls} - {old urls}
    * save new links in <links.txt>
    """

    # Registering newspiece in file system.
    # file <links.txt> is used to store links
    files = os.listdir("/".join((DOWNLOADS_DIR, newspiece.id)))
    linkfile = "/".join((DOWNLOADS_DIR, newspiece.id, "links.txt"))
    if "links.txt" not in files:
        buffer = (
            (newspiece.comments_page + "\n", newspiece.link + "\n")
            if newspiece.comments_page != newspiece.link
            else (newspiece.comments_page + "\n")
        )
        async with aiofiles.open(linkfile, "w") as f:
            await f.writelines(buffer)

    async with aiofiles.open(linkfile, "r") as f_r:
        links = await f_r.readlines()
    links = [link[:-1] for link in links]
    comments_page = links[0]

    error_condition = lambda x: x.startswith("<html>")
    comments_html = await slow_download(
        url=comments_page,
        sema=sema,
        target_name=newspiece.id,
        error_condition=error_condition,
    )

    if not comments_html:
        logging.error("Could not get comments page for %s" % newspiece.id)
        await tracker.append(newspiece)
        return

    links_from_comments = parse_comments_page(comments_html)
    links_to_append = list(set(links_from_comments) - set(links))
    logging.debug(
        "Got %s new links from comments %s" % (len(links_from_comments), newspiece.id)
    )

    if not links_to_append:
        return
    logging.debug(
        "Appending %s new links into %s" % (len(links_to_append), newspiece.id)
    )
    async with aiofiles.open(linkfile, "a") as f_a:
        await f_a.writelines([lnk + "\n" for lnk in links_to_append])


async def worker(name, queue):
    logging.debug("%s started" % name)
    while True:
        link, folder = await queue.get()
        try:
            html = await download_page(link)
        except Exception:
            logging.exception("Cannot download from %s" % link)
        else:
            await save_file(newsdir=folder, filename=link, content=html)
        finally:
            queue.task_done()


async def cycle(startflag=None):
    """
    One cycle of parsing and downloading.
    * getting and parsing main page
    * making dirs and files to store news and urls
    * downloading comments for each page, parsing
        and saving links
    * downloading html for every registered outbound url
    """
    await counter.zero()
    logging.info("Getting news list...")
    main_html = await download_page(ROOTPAGE)
    news_list = get_only_new(parse_news_list(main_html))

    news_list = news_list + tracker.unregistered
    await tracker.zero()

    if not news_list:
        logging.info("Everything is up-to-date. Idle...")
        return

    logging.info("Making dirs...")
    await make_dirs([piece.id for piece in news_list])

    phrase = "It could take 2-3 min"
    add_this_to_log = "" if not startflag else phrase
    logging.info("Registering incoming news... %s" % add_this_to_log)

    sema = asyncio.Semaphore(1)
    registrators = [register(newspiece, sema) for newspiece in news_list]
    await asyncio.gather(*registrators, return_exceptions=True)

    if tracker.unregistered:  # unregistered from current cycle
        logging.info("We'll try to download unregistered items in next cycle")

    news_to_download = [el.id for el in news_list]

    if not news_to_download:
        logging.info("Nothing to download yet. Idle...")
        return

    logging.info("Init downloading...")
    queue = asyncio.Queue(maxsize=10)
    tasks = []
    for i in range(MAX_WORKERS):
        task = asyncio.create_task(worker(f"worker-{i}", queue))
        tasks.append(task)

    news_folders = news_to_download
    for folder in news_folders:
        linkfile = "/".join((DOWNLOADS_DIR, folder, "links.txt"))
        async with aiofiles.open(linkfile, "r") as f:
            links = await f.readlines()
            links = [link[:-1] for link in links[1:]]
        links_to_download = get_extra_links(folder, links)
        [await queue.put((link, folder)) for link in links_to_download]

    await queue.join()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logging.info(
        "Total downloaded pages: %s; "
        "total new pages saved: %s"
        % (counter.total_downloads, counter.total_saved_files)
    )


async def main():
    startflag = True
    try:
        while True:
            start = time.time()
            await cycle(startflag)
            elapsed = round(time.time() - start, 2)
            logging.info("Last cycle completed in %s sec" % elapsed)
            startflag = False
            await asyncio.sleep(PERIOD)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    op = OptionParser()
    op.add_option("-d", "--debug", action="store_true", default=False)
    op.add_option("-l", "--log", action="store", default=None)
    opts, args = op.parse_args()
    logging.basicConfig(
        filename=opts.log,
        level=(logging.INFO if not opts.debug else logging.DEBUG),
        format="[%(asctime)s] %(levelname).1s %(message)s",
        datefmt="%Y.%m.%d %H:%M:%S",
    )
    logging.info("Ycrawler started with options: %s" % opts)
    try:
        start = time.time()
        asyncio.run(main())
    except KeyboardInterrupt:
        elapsed = time.time() - start
        units = ("sec", "min", "h")
        for i in range(3):
            if elapsed > 60:
                elapsed = round(elapsed / 60, 2)
            else:
                break
        unit = units[i]
        logging.info("Worked for %s %s" % (round(elapsed, 2), unit))
    except Exception as e:
        logging.exception("Unexpected error: %s" % e)
        sys.exit(1)
