# -*- coding: utf8 -*-

import time
import json
import random
import platform
import configparser
from datetime import datetime
import logging


import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logging.basicConfig(level=logging.INFO)

logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()

fileHandler = logging.FileHandler("visa.log")
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)


config = configparser.ConfigParser()
config.read('config.ini')

USERNAME = config['USVISA']['USERNAME']
PASSWORD = config['USVISA']['PASSWORD']
SCHEDULE_ID = config['USVISA']['SCHEDULE_ID']
MY_SCHEDULE_DATE = config['USVISA']['MY_SCHEDULE_DATE']
COUNTRY_CODE = config['USVISA']['COUNTRY_CODE'] 
FACILITY_ID = config['USVISA']['FACILITY_ID']

SENDGRID_API_KEY = config['SENDGRID']['SENDGRID_API_KEY']
PUSH_TOKEN = config['PUSHOVER']['PUSH_TOKEN']
PUSH_USER = config['PUSHOVER']['PUSH_USER']

LOCAL_USE = config['CHROMEDRIVER'].getboolean('LOCAL_USE')
HUB_ADDRESS = config['CHROMEDRIVER']['HUB_ADDRESS']

REGEX_CONTINUE = "//a[contains(text(),'Continuar')]"


# def MY_CONDITION(month, day): return int(month) == 11 and int(day) >= 5
def MY_CONDITION(month, day): return True # No custom condition wanted for the new scheduled date

STEP_TIME = 0.5  # time between steps (interactions with forms): 0.5 seconds
RETRY_TIME = 60*10  # wait time between retries/checks for available dates: 10 minutes
EXCEPTION_TIME = 60*15  # wait time when an exception occurs: 30 minutes
COOLDOWN_TIME = 60*30  # wait time when temporary banned (empty list): 60 minutes

DATE_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
TIME_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date=%s&appointments[expedite]=false"
APPOINTMENT_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment"
EXIT = False


def send_notification(msg):
    print(f"Sending notification: {msg}")

    if SENDGRID_API_KEY:
        message = Mail(
            from_email='jorgesuarezch@gmail.com',
            to_emails=USERNAME,
            subject=msg[:30],
            html_content=msg)
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            response = sg.send(message)            
            logging.info('notification sent via sendgrid')
        except Exception as e:
            logging.error(e)
            print(e)

    if PUSH_TOKEN:
        url = "https://api.pushover.net/1/messages.json"
        data = {
            "token": PUSH_TOKEN,
            "user": PUSH_USER,
            "message": msg
        }
        requests.post(url, data)


def get_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    
    if LOCAL_USE:
        dr = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    else:
        dr = webdriver.Remote(command_executor=HUB_ADDRESS, options=options)
    return dr

driver = get_driver()


def login():
    # Bypass reCAPTCHA
    driver.get(f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv")
    time.sleep(STEP_TIME)
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    print("Login start...")
    href = driver.find_element(By.XPATH, '//*[@id="header"]/nav/div[2]/div[1]/ul/li[3]/a')
    href.click()
    time.sleep(STEP_TIME)
    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))

    print("\tclick bounce")
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    do_login_action()


def do_login_action():
    print("\tinput email")
    user = driver.find_element(By.ID, 'user_email')
    user.send_keys(USERNAME)
    time.sleep(random.randint(1, 3))

    print("\tinput pwd")
    pw = driver.find_element(By.ID, 'user_password')
    pw.send_keys(PASSWORD)
    time.sleep(random.randint(1, 3))

    print("\tclick privacy")
    box = driver.find_element(By.CLASS_NAME, 'icheckbox')
    box .click()
    time.sleep(random.randint(1, 3))

    print("\tcommit")
    btn = driver.find_element(By.NAME, 'commit')
    btn.click()
    time.sleep(random.randint(1, 3))

    Wait(driver, 60).until(
        EC.presence_of_element_located((By.XPATH, REGEX_CONTINUE)))
    print("\tlogin successful!")
    logging.info("\tlogin successful!")    


def get_json_content(url):
    driver.get(url)
    content = driver.find_element(By.TAG_NAME, 'pre').text

    return json.loads(content)

def fetch_available_dates(size=5):
    dates = get_json_content(DATE_URL)

    message = "available dates:" + ', '.join(dates)
    logging.info(message)
    print(message)

    return dates[:size]


def fetch_available_times(date):
    data = get_json_content(TIME_URL % date)
    time = data.get("available_times")[-1]
    
    message = f"Got time successfully! {date} {time}"
    logging.info(message)
    print(message)

    return time


def reschedule(date):
    global EXIT
    print(f"Starting Reschedule ({date})")

    time = fetch_available_times(date)
    driver.get(APPOINTMENT_URL)

    data = {
        "utf8": driver.find_element(by=By.NAME, value='utf8').get_attribute('value'),
        "authenticity_token": driver.find_element(by=By.NAME, value='authenticity_token').get_attribute('value'),
        "confirmed_limit_message": driver.find_element(by=By.NAME, value='confirmed_limit_message').get_attribute('value'),
        "use_consulate_appointment_capacity": driver.find_element(by=By.NAME, value='use_consulate_appointment_capacity').get_attribute('value'),
        "appointments[consulate_appointment][facility_id]": FACILITY_ID,
        "appointments[consulate_appointment][date]": date,
        "appointments[consulate_appointment][time]": time,
    }

    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": APPOINTMENT_URL,
        "Cookie": "_yatri_session=" + driver.get_cookie("_yatri_session")["value"]
    }

    r = requests.post(APPOINTMENT_URL, headers=headers, data=data)
    if(r.text.find('Successfully Scheduled') != -1):
        msg = f"Rescheduled Successfully! {date} {time}"
        send_notification(msg)
        EXIT = True
    else:
        msg = f"Reschedule Failed. {date} {time}"
        send_notification(msg)


def is_logged_in():
    driver.get(DATE_URL)
    content = driver.page_source
    if(content.find("error") != -1):
        return False
    return True


def print_dates(dates):
    print(dates_to_string(dates))


def dates_to_string(dates):
    result = "Available Dates:\n"
    for d in dates:
        result = result + "%s \t business_day: %s\n" % (d.get('date'), d.get('business_day'))
    
    return result

    
last_seen = None


def get_early_date(dates):
    global last_seen

    def is_earlier(date):
        my_date = datetime.strptime(MY_SCHEDULE_DATE, "%Y-%m-%d")
        new_date = datetime.strptime(date, "%Y-%m-%d")
        result = my_date > new_date
        print(f'Is {my_date} > {new_date}:\t{result}')
        return result

    print("Checking for an earlier date:")
    for d in dates:
        date = d.get('date')
        if is_earlier(date) and date != last_seen:
            _, month, day = date.split('-')
            if(MY_CONDITION(month, day)):
                last_seen = date
                return date


def push_notification(dates):
    msg = "date: "
    for d in dates:
        msg = msg + d.get('date') + '; '
    send_notification(msg)


def sleep(seconds):
    logging.info("sleep: %s minutes" % (seconds/60))
    time.sleep(EXCEPTION_TIME)


if __name__ == "__main__":
    retry_count = 0
    while 1:
        if retry_count > 6:
            break
        try:
            print("------------------")
            print(datetime.today())
            logging.info(f"Retry count: {retry_count}")
            print()

            if(not is_logged_in()):
                login()

            dates = fetch_available_dates()

            if not dates:
              msg = "List is empty"
              send_notification(msg)
              sleep(COOLDOWN_TIME)
              continue
            else:
                send_notification("available dates:" + ', '.join(dates))
            
            date = get_early_date(dates)

            
            logging.info(f"early date: {date}")
            
            if date:
                send_notification("an early date was found %s" % date)
                # reschedule(date)
                # push_notification(dates)
                EXIT=True
                break
            
            sleep(RETRY_TIME)

        except Exception as e:
            logging.error(e)
            retry_count += 1
            sleep(EXCEPTION_TIME)
    

    logging.info("Closing browser!")
    driver.close()

    if(not EXIT):
        send_notification("HELP! Crashed.")
