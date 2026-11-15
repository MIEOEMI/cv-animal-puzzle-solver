#拉取网页上的图片进行识别并给出落子方案

import requests
from bs4 import BeautifulSoup
import cv2
if __name__ == "__main__":
    url="https://f27e491f.cv-animal-puzzle.pages.dev/?mode=exam"
    #加载网页并传回图片 
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    img_tag = soup.find('img')
    img_url = img_tag['src']
    img_response = requests.get(img_url)
    with open('image.jpg', 'wb') as f:
        f.write(img_response.content)