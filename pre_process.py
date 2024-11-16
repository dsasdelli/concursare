from PIL import Image
import requests
import pytesseract
from io import BytesIO

pytesseract.pytesseract.tesseract_cmd = "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"

text_img_url = ""
response = requests.get(text_img_url)
img = Image.open(BytesIO(response.content))
text = pytesseract.image_to_string(img, 'por+eng')