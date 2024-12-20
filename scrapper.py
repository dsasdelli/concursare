
import itertools
import json
import random
import argparse
import re
from bs4 import BeautifulSoup
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from chromedriver_py import binary_path
from urllib.parse import urlencode
from time import sleep
from selenium.webdriver.support.wait import WebDriverWait 

REMOVE_HTML_REGEX = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')

def remove_html(html):
  soup = BeautifulSoup(html, "html.parser")
  return soup.get_text(separator=" ").strip()

def remove_espacos(texto):
    return re.sub('\s+', ' ', texto)

URL = "https://www.qconcursos.com/questoes-de-concursos/questoes"
DISCIPLINES = {"POR_BRA": 1, "DIR_ADM": 2, "DIR_CON": 3, "DIR_CIV": 8, "DIR_PEN": 9, "DIR_TRI": 18}
MODALITIES = {"ME": 1 , "CE": 2}
ANOS = range(2000, 2025)
ESCOLARIDADES = {"F": [1], "M": [2], "S": [3], "FM": [1, 2], "MS": [2, 3], "FS": [1, 3], "FMS": [1, 2, 3]}
PER_PAGE = 20
MAX_RETRIES = 5

class ParsingException(Exception):
    pass

def create_driver():
    options = Options()
    options.headless = False
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument("--window-size=1920,1200")
    options.add_experimental_option('excludeSwitches', ['enable-logging'])

    service_object = Service(binary_path)
    return webdriver.Chrome(service=service_object, options=options)

def get_filter_question_size(driver):
    try:
        return int(driver.find_element(By.XPATH, '//h2[@class="q-page-results-title"]/strong').text.replace(".",""))
    except NoSuchElementException:
        raise ParsingException("Sem número de questões!")
    
def parse_condition(driver, page_expected_size):
    enunciations = driver.find_elements(By.XPATH, './/div[@class="q-question-body"]/div[@class="q-question-enunciation"]')
    ids = driver.find_elements(By.XPATH, './/div[@class="q-question-header"]/div[@class="q-ref"]/div[@class="q-id"]')
    # print(len(enunciations), len(ids), page_expected_size)
    return (len(enunciations) == page_expected_size and all([e.text for e in ids]))

def gen_url(base_url, discipline_id, modality_id, publication_year, difficulty, scholarity_id, page): 
    params = {
        'discipline_ids[]': discipline_id,
        'modality_ids[]': modality_id,
        'publication_year[]': publication_year,
        'difficulty[]': difficulty,
        'scholarity_ids[]': scholarity_id,
        'page': page,
        'per_page': PER_PAGE
    }
    query = {k: v for k, v in params.items() if v is not None}
    return f'{base_url}?{urlencode(query=query)}'

def parse_page(driver):
    def parse_question(question): 
        # Header:
        prefix = './/div[@class="q-question-header"]'
        id = re.sub('[^0-9]', '', question.find_element(By.XPATH, f'{prefix}/div[@class="q-ref"]/div[@class="q-id"]').text)
        breadcrumb = [b.text for b in question.find_elements(By.XPATH, f'{prefix}/div[@class="q-question-breadcrumb"]/a[@class="q-link"]')]
        breadcrumb_hidden = [b.get_attribute("innerText") for b in question.find_elements(By.XPATH, f'{prefix}/div[@class="q-question-breadcrumb"]/a[@class="q-link q-hidden-crumb"]')]
        subject = breadcrumb[0]
        themes = [t.strip().rstrip(',').strip() for t in [*breadcrumb[1:] , *breadcrumb_hidden]]
        # Info:
        prefix = './/div[@class="q-question-info"]'
        year = question.find_element(By.XPATH, f'{prefix}/span[1]').text
        year = year.replace("Ano: ", "")
        examiner = question.find_element(By.XPATH, f'{prefix}/span[2]').text
        examiner = examiner.replace("Banca: ", "")
        entity = question.find_element(By.XPATH, f'{prefix}/span[3]').text
        entity = entity.replace("Órgão: ", "")
        # Corpo:
        prefix = './/div[@class="q-question-body"]'
        # Corpo - Texto:
        texts = question.find_elements(By.XPATH, f'{prefix}/div[@class="q-question-text" or @class="q-question-text--print-hide"]')
        text = None
        text_img_url = None
        if(texts):
            text_html = texts[0].find_elements(By.XPATH, f'.//div[contains(@id, "question")]')[0]
            text_imgs = text_html.find_elements(By.XPATH, f'.//img')
            if(text_imgs):
                text_img_url = text_imgs[0].get_attribute('src')
            text = remove_espacos(remove_html(text_html.get_attribute("innerHTML"))).strip()
            text = text if text else None
        # Corpo - Enunciado:
        enunciation = question.find_element(By.XPATH, f'{prefix}/div[@class="q-question-enunciation"]')
        enunciation_text = enunciation.text
        enunciation_img_url = None
        enunciation_imgs = enunciation.find_elements(By.XPATH, f'.//img')
        if (enunciation_imgs):
             enunciation_img_url = enunciation_imgs[0].get_attribute('src')
             print(f"Aviso: Questão com enunciado em forma de imagem - {id}")
        if (not enunciation_text and not enunciation_imgs):
             print(f"Erro: Questão sem enunciado algum - {id}")
             raise ParsingException("Sem enunciado!") 
        nullified = bool(question.find_elements(By.XPATH, f'{prefix}//label[@class="q-question-label q-question-label--nullified"]'))
        outdated = bool(question.find_elements(By.XPATH, f'{prefix}//label[@class="q-question-label q-question-label--outdated"]'))
        # Corpo - Respostas:
        prefix = './/div[@class="q-question-body"]/div[contains(@class,"q-question-options")]'
        options_itens = [q.text for q in question.find_elements(By.XPATH, f'{prefix}//span[contains(@class,"q-option-item")]')]
        options_enums = [q.text for q in question.find_elements(By.XPATH, f'{prefix}//div[contains(@class,"q-item-enum")]')]
        options_itens = ["C", "E"] if all(not o for o in options_itens) and len(options_itens) == 2 and len(options_enums) == 2 else options_itens
        options = dict(zip(options_itens, options_enums))
        if (not options_enums):
            raise ParsingException("Sem alternativas!")
        return {
            'id': id, 
            'subject': subject, 
            'themes': themes, 
            'year': year, 
            'examiner': examiner, 
            'entity': entity, 
            'enunciation': enunciation_text, 
            'enunciation_img_url': enunciation_img_url,
            'nullified': nullified, 
            'outdated': outdated, 
            'options': options,
            'text': text,
            'text_img_url': text_img_url
        }

    def parse_answer(answer): 
        return answer.find_element(By.XPATH, f'.//span[@class="q-answer"]').get_attribute("innerText")
    
    questions = driver.find_elements(By.CLASS_NAME, 'q-question-item')
    question_list = [parse_question(q) for q in questions]

    answers = driver.find_elements(By.CLASS_NAME, 'q-feedback')
    answer_list = [parse_answer(a) for a in answers]

    return [{**q, 'answer': a} for q, a in zip(question_list, answer_list) if q is not None]

def get_pages(driver, base_url=URL, discipline_ids=[None], modality_ids=[None], publication_years=[None], difficulties=[None], scholarity_ids=[None], sleep_after=(1.0, 2.0), debug=False):
    complete_question_list = []
    missing_questions_size, complete_expected_question_size = (0, 0)
    for discipline_id, modality_id, publication_year, difficulty, scholarity_id in itertools.product(discipline_ids, modality_ids, publication_years, difficulties, scholarity_ids):
        filter_question_list, page = ([], 1)
        while page < 1000:
            try:
                url = gen_url(base_url, discipline_id, modality_id, publication_year, difficulty, scholarity_id, page)
                if debug:
                    print(f"Debug: Processing URL: {url}")
                
                # Obtém página:
                driver.get(url)

                # Se for a primeira página, obtém questões:
                if page == 1:
                    filter_expected_question_size = get_filter_question_size(driver)
                    complete_expected_question_size += filter_expected_question_size
                    print(f"Questões esperadas: {filter_expected_question_size}")
                                                    
                if filter_expected_question_size == 0:
                    print("Pulando para a próximo filtro")
                    break;    
                
                if (filter_expected_question_size - len(filter_question_list) >= PER_PAGE):
                    page_expected_question_size = PER_PAGE
                else:
                    page_expected_question_size = (filter_expected_question_size - len(filter_question_list)) % PER_PAGE
                WebDriverWait(driver, 10).until(lambda d: parse_condition(d, page_expected_question_size))

                questions = parse_page(driver)
                if len(questions) == 0:
                    if debug:
                        print("Nenhum resultado: página final alcançada")
                        print(f'{len(filter_question_list)}/{filter_expected_question_size} obtidas')
                        missing_questions_size += filter_expected_question_size - len(filter_question_list)
                    break
                filter_question_list.extend(questions)
                page = page + 1
                sleep(random.uniform(*sleep_after))
            except (ParsingException, TimeoutException) as e:
                driver.quit()
                print(f"Erro de parsing e repetindo página: {str(e)}")
                sleep(60)
                driver = create_driver()

        complete_question_list.extend(filter_question_list)
    if debug:
        print(f'Questões faltantes: {missing_questions_size}')
        print(f'Questões obtidas: {len(complete_question_list)}')
        print(f'Questões totais: {complete_expected_question_size}')
    return complete_question_list

parser = argparse.ArgumentParser()
parser.add_argument('-d', '--disciplina', help='Disciplina', choices=DISCIPLINES.keys(), required=True)
parser.add_argument('-m', '--modalidade', help='Modalidade', choices=MODALITIES.keys(), required=True)
parser.add_argument('-i', '--anoInicio', type=int, help='Ano de início', choices=ANOS, required=False, default=2000)
parser.add_argument('-f', '--anoFim', type=int, help='Ano de fim', choices=ANOS, required=False, default=2025)
parser.add_argument('-e', '--escolaridades', help='Escolaridades', choices=ESCOLARIDADES.keys(), required=False, default='FMS')
args = parser.parse_args()

driver = create_driver()
question_list = get_pages(
    driver, 
    discipline_ids=[DISCIPLINES[args.disciplina]],
    modality_ids=[MODALITIES[args.modalidade]], 
    publication_years=range(args.anoInicio, args.anoFim), 
    scholarity_ids=ESCOLARIDADES[args.escolaridades], 
    debug=True
)
driver.quit()

output = f'{args.disciplina}_{args.modalidade}_{args.anoInicio}_{args.anoFim}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'

with open(output, 'w', encoding='utf-8') as f:
    json.dump(question_list, f, ensure_ascii=False, indent=4)