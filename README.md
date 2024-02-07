# Ycrawler

Ycrawler is a simple web crawler that downloads and parses news articles from a specified website. It is designed to work with a specific website structure, but can be easily modified to work with other websites.

## Installation

To install Ycrawler, clone the repository and install the required packages:

* download this project
`pip install -r requirements.txt`
`cd homework`

### Usage

To run Ycrawler, use the following command:

Copy code
`python3 -m crawler.py  [-d] [-l LOG]`

#### Options

* -d, --debug: enable debug mode
* -l, --log: specify the log file (default: None)

Ycrawler will start downloading and parsing news articles from the specified website and save them to the DOWNLOADS_DIR directory. By default, it will run indefinitely, downloading new articles every PERIOD seconds. To stop Ycrawler, use Ctrl+C.

#### Example

To run Ycrawler and save the logs to a file called ycrawl.log, use the following command:

Copy code
`python3 -m crawler.py -l ycrawl.log` or  ycrawl.txt
This will start Ycrawler and save the logs to ycrawler.log.

To run Ycrawler in debug mode, use the following command:

Copy code
`python3 -m crawler.py -d`
This will start Ycrawler in debug mode, which will print detailed information about the crawling process to the console.

#### Configuration

Ycrawler can be configured by modifying the config.py file. The following settings are available:

ROOTPAGE: the root URL of the website to crawl
TIMEOUT: the timeout for HTTP requests (in seconds)
MAX_RETRY: the maximum number of retries for failed requests
MAX_WORKERS: the maximum number of worker threads
PERIOD: the period between crawling cycles (in seconds)
DOWNLOADS_DIR: the directory where downloaded files will be saved
