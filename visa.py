# -*- coding: utf8 -*-

import time
import json
import random
import platform
import configparser
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
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

from pushbullet import Pushbullet

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
ASC_FACILITY_ID = config['USVISA']['ASC_FACILITY_ID']

SENDGRID_API_KEY = config['SENDGRID']['SENDGRID_API_KEY']
PUSHBULLET_API_KEY = config['PUSHBULLET']['PUSHBULLET_API_KEY']
PUSH_TOKEN = config['PUSHOVER']['PUSH_TOKEN']
PUSH_USER = config['PUSHOVER']['PUSH_USER']

LOCAL_USE = config['CHROMEDRIVER'].getboolean('LOCAL_USE')
HUB_ADDRESS = config['CHROMEDRIVER']['HUB_ADDRESS']

REGEX_CONTINUE = "//a[contains(text(),'Continue')]"


# def MY_CONDITION(month, day): return int(month) == 11 and int(day) >= 5
def MY_CONDITION(month, day): return True # No custom condition wanted for the new scheduled date

STEP_TIME = 0.5  # time between steps (interactions with forms): 0.5 seconds
RETRY_TIME = 60*10  # wait time between retries/checks for available dates: 10 minutes
EXCEPTION_TIME = 60*15  # wait time when an exception occurs: 15 minutes
COOLDOWN_TIME = 60*30  # wait time when temporary banned (empty list): 60 minutes

BASE_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment"
DATE_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
TIME_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date=%s&appointments[expedite]=false"
APPOINTMENT_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment"


def send_notification(msg):
    message = f"{msg}\n{APPOINTMENT_URL}"
    logging.info(f"Sending notification: {message}")

    if SENDGRID_API_KEY:
        mail = Mail(
            from_email='jorgesuarezch@gmail.com',
            to_emails=USERNAME,
            subject=msg[:30],
            html_content=message)
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            response = sg.send(mail)            
            logging.info('notification sent via sendgrid')
        except Exception as e:
            logging.error(e)
    
    if PUSHBULLET_API_KEY:
        try:
            pb = Pushbullet(PUSHBULLET_API_KEY)
            response = pb.push_note("Visa Re-Scheduler", f"{msg}\n{APPOINTMENT_URL}")
            logging.info('notification sent via pushbullet')
        except Exception as e:
            logging.error(e)
        

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

def fetch_available_times(date):
    data = get_json_content(TIME_URL % date)
    time = data.get("available_times")[-1]
    
    message = f"Got time successfully! {date} {time}"
    logging.info(message)
    print(message)

    return time

def build_payload(consulate_date, consulate_time, asc_date, asc_time):
    return {
        "appointments[consulate_appointment][facility_id]": FACILITY_ID,
        "appointments[consulate_appointment][date]": consulate_date,
        "appointments[consulate_appointment][time]": consulate_time,
        "appointments[asc_appointment][facility_id]": ASC_FACILITY_ID,
        "appointments[asc_appointment][date]": asc_date,
        "appointments[asc_appointment][time]": asc_time
    }

def parse_date(date):
    return datetime.strptime(date, "%Y-%m-%d")

def fetch_consulate_dates(current_date):
    """Return all early potential dates to reschedule"""

    def is_valid_date(d):
        date = parse_date(d)
        current = parse_date(current_date)
        min_date = date.today() + relativedelta(months=+1)
         
        return date < current and date > min_date

    url = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
    dates = get_json_content(url)

    dates = list(map(lambda d: d.get('date'), dates))
    dates = list(filter(is_valid_date, dates))

    return dates

def fetch_consulate_times(consulate_date):
    url = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date={consulate_date}&appointments[expedite]=false"
    response = get_json_content(url)

    return response.get("available_times")


def fetch_asc_dates(consulate_date, consulate_time):
    url = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{ASC_FACILITY_ID}.json?appointments[expedite]=false&consulate_id={FACILITY_ID}&consulate_date={consulate_date}&consulate_time={consulate_time}"
    dates = get_json_content(url)

    current_date = parse_date(consulate_date)

    dates = list(map(lambda d: d.get('date'), dates))
    dates = list(filter(lambda d: parse_date(d) < current_date, dates))

    return dates

def fetch_asc_times(asc_date, consulate_date, consulate_time):
    url = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{ASC_FACILITY_ID}.json?appointments[expedite]=false&consulate_id={FACILITY_ID}&consulate_date={consulate_date}&consulate_time={consulate_time}&date={asc_date}"
    response = get_json_content(url)

    return response.get("available_times")

def get_payload(current_date):
    consulate_dates = fetch_consulate_dates(current_date)

    if not consulate_dates:
        """No dates to reschedule"""
        return None

    send_notification("an early date was found %s" % consulate_dates[0])

    for consulate_date in consulate_dates:
        consulate_times = fetch_consulate_times(consulate_date)

        if not consulate_times:
            continue

        consulate_time = consulate_times[-1]

        asc_dates = fetch_asc_dates(consulate_date, consulate_time)

        if not asc_dates:
            continue
        
        
        # pick the closest date to the consulate date. 
        # Note: it is assumed dates are sorted asc
        asc_date = asc_dates[-1]

        asc_times = fetch_asc_times(asc_date, consulate_date, consulate_time)

        if not asc_times:
            continue

        asc_time = asc_times[-1]

        

        return {
            'consulate_date': consulate_date,
            'consulate_time': consulate_time,
            'asc_date': asc_date,
            'asc_time': asc_time,
        }
        # return build_payload(consulate_date, consulate_time, asc_date, asc_time)



def reschedule(payload):
    logging.info(f"Starting Reschedule ({payload})")

    driver.get(APPOINTMENT_URL)

    btn = driver.find_element(By.NAME, 'commit')
    btn.click()

    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "appointments[consulate_appointment][facility_id]")))

    driver.execute_script("""
    async function sleep(ms) {
        return new Promise(function(resolve, reject){
            window.setTimeout(function(){resolve(ms)}, ms)
        })
    }
    async function main() {
        const data = {
appointments_consulate_appointment_date: '%s',
appointments_consulate_appointment_time: '%s',
appointments_asc_appointment_date: '%s',
appointments_asc_appointment_time: '%s',
        };

        for(let entry of Object.entries(data)) {
            const [field, value] = entry
            const input = document.getElementById(field);
            input.value = value;
            input.insertAdjacentHTML('beforebegin', `<input type="text" name='${input.attributes.name}' value='${value}' />`);
            input.remove()

            // input.dispatchEvent(new Event('change'));

            // await sleep(5000);
        }

        document.getElementById('appointments_submit').removeAttribute('data-confirm')
        document.getElementById('appointments_submit').removeAttribute('disabled')
        document.getElementById('appointments_submit').click();
    }

    main()
        
    """ % (
        payload.get('consulate_date'),
        payload.get('consulate_time'),
        payload.get('asc_date'),
        payload.get('asc_time')
        )
    )
    time.sleep(1)

    Wait(driver, 60).until(
        EC.presence_of_element_located((By.XPATH, "//button[contains(text(),'OK')]")))

    popoup = driver.find_element(By.ID, 'flash_messages')

    if popoup.text.find('could not be scheduled'):
        send_notification(f"Reschedule failed {payload.get('consulate_date')}")

        return False
    
    else:
        send_notification(f"Reschedule success {payload.get('consulate_date')}")

    return True
    

def is_logged_in():
    driver.get(DATE_URL)
    content = driver.page_source
    if(content.find("error") != -1):
        return False
    return True

def sleep(seconds):
    logging.info("sleep: %s minutes" % (seconds/60))
    time.sleep(seconds)


if __name__ == "__main__":
    retry_count = 0
    login()

    while 1:
        if retry_count > 10:
            send_notification("HELP! Crashed.")
            break
        try:
            logging.info(f"Attempt: {retry_count}")

            if not is_logged_in():
                login()
                continue
            
            payload = get_payload(MY_SCHEDULE_DATE)

            if payload:
                logging.info("Starting reschedule")
                logging.info(payload)
                send_notification("Starting reschedule")

                was_successful = reschedule(payload)

                if was_successful:
                    break
                

            sleep(RETRY_TIME)

        except Exception as e:
            logging.error(e)
            retry_count += 1
            sleep(EXCEPTION_TIME)
    

    try:
        logging.info("Closing browser!")
        driver.close()
    except Exception as e:
        logging.error(e)
