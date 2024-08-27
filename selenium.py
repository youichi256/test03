
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver import DesiredCapabilities, Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


class Selenium:
    """排他制御クラス"""

    def __init__(self, logger: Logger, event: Event, queue_in: SimpleQueue, slack: Slack):
        self.logger = logger
        self.event = event
        self.queue_in = queue_in
        self.slack = slack
        self.queue_out = SimpleQueue()
        self.dir_log_img = "log/img"
        self.is_debug = _load_debug()
        self.selenium_count = 0
        self.lock = threading.Lock()
        self._fail = False

    def th_run(self):
        """
        排他ループ

        :return: なし
        """
        self.__selenium_init()
        get: Dict[str, Any] = {}
        try:
            while True:
                get = self.__queue_get(self.queue_in)
                if isinstance(get, str) and get == "-":
                    break
                if "wait_init" in get:  # Selenium初期化待ち
                    get["queue_out"].put(None)
                    continue
                try:
                    ret = self._get_url_selenium(get["thname"], get["url"], get["xpath"])
                except NoSuchElementException as err:
                    ret = "-" + err.__class__.__name__
                get["queue_out"].put(ret)
        except StopSignal:
            self.logger.warning("StopSignal")
        except Exception as err:
            self.logger.error("%s:%s", err.__class__.__name__, str(err))
            self.logger.error(traceback.format_exc())
            self.slack.message(MessageLevel.ERROR, "Seleniumエラー", f"Selenium処理で、{err.__class__.__name__}が発生しました。")
            if "queue_out" in get:
                get["queue_out"].put("-")
            self._fail = True
        self.__selenium_term()

    def __event_stop(self):
        if self.event.is_set():
            self.logger.debug("stop event")
            raise StopSignal(-1)

    def __queue_get(self, queue: SimpleQueue) -> Any:
        while True:
            try:
                ret = queue.get(timeout=1)
                break
            except Empty:
                self.__event_stop()
        return ret

    def __selenium_init(self) -> None:
        """Seleniumの初期化"""
        self.logger.debug("webdriverの初期化開始")
        self.selenium_options = Options()
        self.selenium_options.headless = True
        # self.selenium_options.add_argument(f"user-agent=xxxx")
        # self.selenium_options.add_argument("no-sandbox")
        # self.selenium_options.add_argument("disable-gpu")
        # self.selenium_options.add_argument("enable-automation")
        # self.selenium_options.add_argument("disable-browser-side-navigation")
        # self.selenium_options.add_argument("disable-extensions")
        # self.selenium_options.add_argument("disable-blink-features=AutomationControlled")
        self.selenium_options.add_argument("start-maximized")
        # self.selenium_options.add_argument("start-fullscreen")
        # self.selenium_options.add_argument("disable-infobars")
        # self.selenium_options.add_argument("disable-dev-shm-usage")
        self.selenium_options.add_argument("window-size=1280,1024")
        # self.selenium_options.add_argument(f"user-data-dir={os.getcwd()}/data/User-Data")
        # self.selenium_options.add_argument("lang=ja-JP")
        # self.selenium_options.add_experimental_option("prefs", {"intl.accept_languages": "ja-JP"})
        self.selenium_desired = DesiredCapabilities.CHROME
        self.selenium_desired["goog:loggingPrefs"] = {"performance": "ALL"}
        if os.name == "nt":
            import_module("chromedriver_binary")
        self.__selenium_init_sub()
        self.logger.debug("browserVersion=%s", self.selenium_driver.capabilities["browserVersion"])
        self.logger.debug("chromedriverVersion=%s", self.selenium_driver.capabilities["chrome"]["chromedriverVersion"])
        self.user_agent = self.selenium_driver.execute_script("return navigator.userAgent")
        self.user_agent = re.sub(" HeadlessChrome/", " Chrome/", self.user_agent)
        self.logger.debug("userAgent=%s", self.user_agent)
        self.logger.debug("webdriverの初期化完了")
        if self.is_debug:
            nowtime = datetime.datetime.now()
            for file in glob.glob(f"{self.dir_log_img}/*.png"):
                if nowtime.timestamp() - os.stat(file).st_mtime > 3600 * 12:
                    os.remove(file)

    def __selenium_init_sub(self) -> None:
        self.selenium_driver = Chrome(options=self.selenium_options, desired_capabilities=self.selenium_desired,
                                      keep_alive=True)
        self.selenium_driver.implicitly_wait(20)
        # self.driver.set_page_load_timeout(30)
        self.selenium_count = 0

    def __selenium_term(self) -> None:
        """Seleniumの終了"""
        self.logger.debug("webdriverの終了処理開始")
        self.__selenium_term_sub()
        self.logger.debug("webdriverの終了処理完了")

    def __selenium_term_sub(self) -> None:
        self.selenium_driver.quit()

    def __selenium_restart(self) -> None:
        self.logger.debug("webdriverの再起動開始")
        self.__selenium_term_sub()
        self.__selenium_init_sub()
        self.logger.debug("webdriverの再起動完了")

    def wait_init(self) -> None:
        """Selenium初期化待ち"""
        self.lock.acquire()
        self.queue_in.put({"wait_init": True, "queue_out": self.queue_out})
        self.__queue_get(self.queue_out)
        self.lock.release()

    def get_url_selenium(self, url: str, xpath: str) -> str:
        """Seleniumでページ取得(複数スレッド)"""
        if self._fail:
            return "-"
        self.lock.acquire()
        self.queue_in.put({"thname": threading.current_thread().name, "url": url, "xpath": xpath, "queue_out": self.queue_out})
        ret: str = self.__queue_get(self.queue_out)
        self.lock.release()

        if ret.startswith("-"):
            raise PageAnalysisError(url, None, f"{ret[1:]}({xpath})")
        return ret

    def _get_url_selenium(self, thname: str, url: str, xpath: str) -> str:
        """
        Seleniumでページ取得

        :param thname: スレッド名
        :param url: URL
        :param xpath: ロード待ち対象のXPATH
        :return: ページ内容
        """
        readbody = False
        last_raise = None
        for trycnt in range(10):
            time.sleep(2)
            time_s = time.perf_counter()
            if self.selenium_count >= 20:
                self.__selenium_restart()
            self.selenium_count = self.selenium_count + 1
            try:
                self.selenium_driver.get(url)
                self.selenium_driver.find_element(By.XPATH, xpath)
                self.logger.debug("page_get=%6.3fs %s", time.perf_counter() - time_s, url)
                readbody = True
                break
            except NoSuchElementException as err:
                self._save_screenshot()
                self.logger.warning("page_get=%6.3fs %s:%s(%s)", time.perf_counter() - time_s, err.__class__.__name__, str(err), url)
                self.logger.info("retry:%d", trycnt + 1)
                self.logger.warning("=== HTML ===\n%s", self.selenium_driver.page_source)
                self.slack.message(MessageLevel.WARNING, f"Selenium失敗({thname})", f"{err.__class__.__name__}:{str(err)}\n{url}")
                raise
            except (TimeoutException, WebDriverException, MaxRetryError) as err:
                self.__event_stop()
                self._save_screenshot()
                self.logger.warning("page_get=%6.3fs %s:%s(%s)", time.perf_counter() - time_s, err.__class__.__name__, str(err), url)
                self.logger.info("retry:%d", trycnt + 1)
                self.slack.message(MessageLevel.WARNING, f"Selenium失敗({thname})", f"{err.__class__.__name__}:{str(err)}:retry={trycnt + 1}\n{url}")
                last_raise = err
                time.sleep(3)
            except AttributeError as err:
                self._save_screenshot()
                self.logger.warning("page_get=%6.3fs %s:%s(%s)", time.perf_counter() - time_s, err.__class__.__name__, str(err), url)
                self.logger.info("retry:%d", trycnt + 1)
                self.slack.message(MessageLevel.WARNING, f"Selenium失敗({thname})", f"{err.__class__.__name__}:{str(err)}\n{url}")
                raise
            except IndexError:
                StopSignal.if_last_signal()
                raise
        if not readbody:
            raise last_raise
        html = self.selenium_driver.page_source
        self.__event_stop()
        self._save_screenshot()
        tabs = len(self.selenium_driver.window_handles)
        if tabs != 1:
            self.selenium_driver.switch_to.window(self.selenium_driver.window_handles[1])
            self._save_screenshot()
            raise ValueError(f"selenium tabs:{tabs}")

        # cookie_data = {}
        # for cookie in self.selenium_driver.get_cookies():
        #     cookie_data[cookie["name"]] = cookie["value"]
        #     self.logger.debug(cookie)

        # for entry_json in self.selenium_driver.get_log("performance"):
        #     # self.logger.debug(entry_json)
        #     logtime = datetime.datetime.fromtimestamp(entry_json["timestamp"] / 1000).strftime("%H:%M:%S") \
        #               + f".{entry_json['timestamp'] % 1000:03d}"
        #     entry = json.loads(entry_json["message"])
        #     if entry["message"]["method"] == "Network.requestWillBeSent":
        #         # self.logger.debug(entry["message"])
        #         self.logger.debug("%s %s %s", logtime,
        #                           entry["message"]["params"]["request"]["method"],
        #                           entry["message"]["params"]["request"]["url"])
        #     if entry["message"]["method"] == "Network.responseReceived":
        #         # self.logger.debug(entry["message"])
        #         self.logger.debug("%s %03d[%s] (%s) %s", logtime,
        #                           entry["message"]["params"]["response"]["status"],
        #                           entry["message"]["params"]["response"]["statusText"],
        #                           entry["message"]["params"]["response"]["mimeType"],
        #                           entry["message"]["params"]["response"]["url"])

        return html

    def _save_screenshot(self) -> None:
        if self.is_debug:
            time.sleep(1)
            nowtime = datetime.datetime.now()
            self.selenium_driver.save_screenshot(f"{self.dir_log_img}/cap_{nowtime.strftime('%Y%m%d_%H%M%S')}_{int(nowtime.microsecond / 1000):03d}.png")


