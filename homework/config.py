import re

import aiohttp


ROOTPAGE = "https://news.ycombinator.com/"
TIMEOUT = aiohttp.ClientTimeout(total=5)
MAX_RETRY = 3
MAX_WORKERS = 5
PERIOD = 60
DOWNLOADS_DIR = "/home/dmitriy/page"
number_pattern = re.compile(r"\n(\d{1,2})\.")
name_pattern = re.compile(r"\n\d+\. (.*)")
